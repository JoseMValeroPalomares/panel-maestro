"""Captura rápida del escritorio (scripts/desktop/quick_capture.sh + panel_client.py) contra el Panel
de pruebas, con rofi y notify-send simulados. Las peticiones llevan el token Bearer de verdad."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_TOKEN

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/desktop/quick_capture.sh"


@pytest.fixture()
def panel(app, client, tmp_path):  # client: arranca el Panel (BD creada)
    """Servidor HTTP local que reenvía al Panel (TestClient sin sesión: solo vale el token)."""
    tc = TestClient(app)

    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            r = tc.request(method, self.path, content=body, headers={k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")})
            self.send_response(r.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(r.content)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tc
    srv.shutdown()


@pytest.fixture()
def env(tmp_path, panel):
    url, _ = panel
    token = tmp_path / "token"
    token.write_text(TEST_API_TOKEN + "\n")
    token.chmod(0o600)
    answers, log = tmp_path / "answers", tmp_path / "log"
    fake_rofi = tmp_path / "rofi"
    fake_rofi.write_text(f"""#!/usr/bin/env bash
printf 'ROFI %s\\n' "$*" >> {log}
line=$(head -n1 {answers}); sed -i '1d' {answers}; [ -z "$line" ] && exit 1
# «@10 texto» = el texto con la tecla Alt+1 (código de salida 10), como rofi
if [[ "$line" =~ ^@([0-9]+)\ (.*)$ ]]; then printf '%s' "${{BASH_REMATCH[2]}}"; exit "${{BASH_REMATCH[1]}}"; fi
printf '%s' "$line"
""")
    fake_notify = tmp_path / "notify"
    fake_notify.write_text(f"#!/usr/bin/env bash\nprintf 'NOTIFY %s\\n' \"$*\" >> {log}\n")
    for f in (fake_rofi, fake_notify):
        f.chmod(0o755)
    answers.write_text("")
    e = {**os.environ, "PANEL_URL": url, "PANEL_TOKEN_FILE": str(token), "PANEL_STATE_DIR": str(tmp_path / "state"),
         "PANEL_ROFI": str(fake_rofi), "PANEL_NOTIFY": str(fake_notify), "PANEL_TIMEOUT": "3"}
    return e, answers, log


def run(env, *args, answers=()):
    e, ans, _ = env
    ans.write_text("".join(a + "\n" for a in answers))
    return subprocess.run(["bash", str(SCRIPT), *args], env=e, capture_output=True, text=True, timeout=30)


def items(panel):
    _, tc = panel
    return tc.get("/api/items", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}).json()["items"]


def test_cada_prefijo_crea_su_elemento(env, panel):
    for text in ("comprar pilas desde rofi", "t: tarea desde rofi", "i: idea desde rofi", "r: estirar de lunes a viernes 7:30"):
        r = run(env, text)
        assert r.returncode == 0, r.stderr
    por_texto = {i["text"]: i for i in items(panel)}
    assert por_texto["comprar pilas desde rofi"]["origin"] == "inbox"
    assert por_texto["tarea desde rofi"]["type"] == "tarea"
    assert por_texto["idea desde rofi"]["type"] == "idea"
    rut = por_texto["Estirar"]
    assert rut["type"] == "rutina" and rut["due_time"] == "07:30" and rut["repeat"]["days"] == [0, 1, 2, 3, 4]
    assert "NOTIFY -a Panel -u low" in env[2].read_text()


def test_menu_y_vista_previa_del_evento(env, panel):
    # primer paso: el texto; segundo: la vista previa, que se confirma
    r = run(env, answers=["e: dentista mañana 17:00", "Guardar el evento"])
    assert r.returncode == 0, r.stderr
    log = env[2].read_text()
    assert "panel-captura.rasi" in log and "t:</b> tarea" in log          # ayuda con los prefijos
    assert "panel-confirmar.rasi" in log and "<b>Dentista</b>" in log and "17:00–18:00" in log
    _, tc = panel
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=1)).isoformat()
    ev = tc.get(f"/api/calendar/entries?start={d}&end={d}", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}).json()["entries"]
    assert any(e["title"] == "Dentista" and e["start"] == f"{d}T17:00" for e in ev)
    # Esc en la vista previa: no se guarda nada
    antes = len(items(panel))
    run(env, answers=["e: cena mañana 21:00", ""])
    assert len(items(panel)) == antes


def test_fecha_ambigua_va_al_inbox_para_revisar(env, panel):
    r = run(env, answers=["e: llamar al taller el día que pueda", "Guardar en el Inbox"])
    assert r.returncode == 0
    it = next(i for i in items(panel) if i["text"].startswith("llamar al taller"))
    assert it["category"] == "Revisar fecha"
    log = env[2].read_text()
    assert "No entiendo la fecha" in log and "Panel: revisar fecha" in log


def test_sin_conexion_cola_y_reenvio(env, panel):
    e, _, log = env
    caido = {**e, "PANEL_URL": "http://127.0.0.1:9"}  # nadie escucha
    r = subprocess.run(["bash", str(SCRIPT), "t: primera sin conexión"], env=caido, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "Panel sin conexión" in log.read_text()
    subprocess.run(["bash", str(SCRIPT), "i: segunda sin conexión"], env=caido, capture_output=True, text=True, timeout=30)
    cola = Path(e["PANEL_STATE_DIR"]) / "cola.jsonl"
    assert [json.loads(x)["text"] for x in cola.read_text().splitlines()] == ["t: primera sin conexión", "i: segunda sin conexión"]
    # vuelve el panel: la siguiente captura vacía la cola antes (en orden)
    run(env, "t: tercera con conexión")
    textos = [i["text"] for i in items(panel)]
    assert {"primera sin conexión", "segunda sin conexión", "tercera con conexión"} <= set(textos)
    assert not cola.exists()
    # también se reenvía sola (la Waybar llama a «flush»)
    subprocess.run(["bash", str(SCRIPT), "t: cuarta"], env=caido, capture_output=True, timeout=30)
    out = subprocess.run(["python3", str(ROOT / "scripts/desktop/panel_client.py"), "flush"], env=e, capture_output=True, text=True, timeout=30)
    assert json.loads(out.stdout)["sent"] == 1


def test_token_con_permisos_abiertos_se_rechaza(env, tmp_path):
    e, _, _ = env
    Path(e["PANEL_TOKEN_FILE"]).chmod(0o644)
    out = subprocess.run(["python3", str(ROOT / "scripts/desktop/panel_client.py"), "capture", "x"], env=e, capture_output=True, text=True)
    assert out.returncode == 1 and "600" in json.loads(out.stdout)["message"]


def test_alt_numero_elige_el_tipo_y_tarea_con_fecha(env, panel):
    # Alt+2 = idea sin escribir el prefijo (sin fecha: no pregunta)
    assert run(env, answers=["@11 idea con alt dos"]).returncode == 0
    assert next(i for i in items(panel) if i["text"] == "idea con alt dos")["type"] == "idea"
    # Alt+1 con fecha: vista previa de la tarea, «Corregir el texto» vuelve al menú con el texto, y se guarda
    r = run(env, answers=["@10 llamar a Juan el viernes", "Corregir el texto", "t: llamar a Juana el viernes", "Guardar"])
    assert r.returncode == 0, r.stderr
    log = env[2].read_text()
    assert "Tarea: <b>Llamar a Juan</b>" in log and "-filter t: llamar a Juan el viernes" in log
    it = next(i for i in items(panel) if i["text"] == "Llamar a Juana")
    assert it["type"] == "tarea" and it["due_date"]
    # rutina desde el menú: también se confirma («Cada día…»)
    run(env, answers=["@12 estirar la espalda cada día a las 7", "Cancelar"])
    assert not any(i["text"] == "Estirar la espalda" for i in items(panel))  # (otro test ya crea «Meditar»)
