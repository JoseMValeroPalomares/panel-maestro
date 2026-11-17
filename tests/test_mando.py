"""Centro de mando en rofi y avisos con botones del escritorio (P-11), contra el Panel de pruebas con rofi,
notify-send, xdg-open y pkill simulados (nada llega al escritorio de verdad)."""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from tests.conftest import TEST_API_TOKEN
from tests.test_desktop_capture import panel  # noqa: F401 — fixture

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "scripts/desktop"
H = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
HOY = date.today().isoformat()

FAKE_ROFI = r"""#!/usr/bin/env python3
# Respuestas, una por llamada: «=texto» elige la primera fila que lo contiene, «?texto» escribe texto (Ctrl+Intro),
# «ESC» cierra; delante, «@N » sale con el código N (Alt+tecla: 10… acciones, 15… modos).
import json, re, sys
from pathlib import Path
log, ans = Path(sys.argv[0]).with_name("log"), Path(sys.argv[0]).with_name("answers")
rows = sys.stdin.read().split("\n")
with log.open("a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "rows": rows}, ensure_ascii=False) + "\n")
lines = ans.read_text().splitlines()
if not lines:
    sys.exit(1)
line, rest = lines[0], lines[1:]
ans.write_text("".join(x + "\n" for x in rest))
rc = 0
m = re.match(r"@(\d+) ?(.*)$", line)
if m:
    rc, line = int(m.group(1)), m.group(2)
if line == "ESC":
    sys.exit(1)
if line.startswith("="):
    plain = [re.sub("<[^>]+>", "", r) for r in rows]
    idx = next((i for i, r in enumerate(plain) if line[1:] in r), None)
    if idx is None:
        print("NO ESTÁ: " + line, file=sys.stderr)
        sys.exit(1)
    print(f"{idx}|{rows[idx]}", end="")
elif line.startswith("?"):
    print(f"-1|{line[1:]}", end="")
sys.exit(rc)
"""


@pytest.fixture()
def desk(tmp_path, panel):  # noqa: F811
    url, tc = panel
    tok = tmp_path / "token"
    tok.write_text(TEST_API_TOKEN + "\n")
    tok.chmod(0o600)
    rofi = tmp_path / "rofi"
    rofi.write_text(FAKE_ROFI)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name in ("xdg-open", "pkill"):
        (bin_ / name).write_text(
            f"#!/usr/bin/env bash\nprintf '{name.upper()} %s\\n' \"$*\" >> {tmp_path / 'sys.log'}\n"
        )
    notify = tmp_path / "notify"
    # notify-send simulado: apunta los argumentos y, si hay respuesta en «boton», la escribe (el botón pulsado)
    notify.write_text(
        f"#!/usr/bin/env bash\nprintf 'NOTIFY %s\\n' \"$*\" >> {tmp_path / 'sys.log'}\n"
        f"[ -s {tmp_path / 'boton'} ] && cat {tmp_path / 'boton'}\nexit 0\n"
    )
    for f in (rofi, notify, *bin_.iterdir()):
        f.chmod(0o755)
    (tmp_path / "answers").write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "PANEL_URL": url,
        "PANEL_TOKEN_FILE": str(tok),
        "PANEL_STATE_DIR": str(tmp_path / "state"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PANEL_ROFI": str(rofi),
        "PANEL_NOTIFY": str(notify),
        "PANEL_TIMEOUT": "5",
    }

    class D:
        def run(self, *answers, args=("--modo", "hoy")):
            (tmp_path / "answers").write_text("".join(a + "\n" for a in answers))
            r = subprocess.run([sys.executable, str(DESK / "panel_mando.py"), *args], env=env,
                               capture_output=True, text=True, timeout=60)  # fmt: skip
            assert "NO ESTÁ" not in r.stderr, r.stderr
            return r

        def calls(self):
            log = tmp_path / "log"
            return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

        def syslog(self):
            f = tmp_path / "sys.log"
            return f.read_text() if f.exists() else ""

        def api(self, method, path, **kw):
            return tc.request(method, path, headers=H, **kw)

        def item(self, text, **kw):
            return self.api("POST", "/api/items", json={"text": text, "type": "tarea", **kw}).json()["id"]

        def get(self, item_id):
            return next((i for i in self.api("GET", "/api/items").json()["items"] if i["id"] == item_id), None)

    d = D()
    d.env, d.tmp = env, tmp_path
    return d


def test_hoy_completar_con_alt_c_y_vuelve_a_la_misma_fila(desk):
    t = desk.item("Mando completar", due_date=HOY)
    desk.run("@10 =Mando completar", "ESC")
    assert desk.get(t)["done"] is True
    calls = desk.calls()
    assert len(calls) == 2  # tras la acción, el menú se vuelve a abrir
    first = calls[0]
    assert "Hoy" in first["args"][first["args"].index("-mesg") + 1]
    assert any("Empezar el contador" in r for r in first["rows"]) and any("HOY" in r for r in first["rows"])
    # las Alt+número son los modos y las Alt+letra las acciones
    a = first["args"]
    assert a[a.index("-kb-custom-1") + 1] == "Alt+c" and a[a.index("-kb-custom-6") + 1] == "Alt+1"
    assert "Panel: Hecho" in desk.syslog()


def test_atrasada_posponer_la_trae_a_hoy_y_alt_m_a_manana(desk):
    ayer = (date.today() - timedelta(days=1)).isoformat()
    a, b = desk.item("Mando vieja A", due_date=ayer), desk.item("Mando vieja B", due_date=ayer)
    desk.run("@11 =Mando vieja A", "@12 =Mando vieja B", "ESC")
    assert desk.get(a)["due_date"] == HOY
    assert desk.get(b)["due_date"] == (date.today() + timedelta(days=1)).isoformat()


def test_modos_con_alt_numero(desk):
    desk.api("POST", "/api/calendar/events", json={"title": "Mando evento", "start": f"{HOY}T23:30"})
    desk.run("@16 ", "@17 ", "@15 ", "ESC")
    calls = desk.calls()
    mesgs = [c["args"][c["args"].index("-mesg") + 1] for c in calls]
    assert "<b>Semana</b>" in mesgs[1] and any("Abrir el calendario" in r for r in calls[1]["rows"])
    assert "<b>Buscar</b>" in mesgs[2] and "-no-custom" not in calls[2]["args"]  # en Buscar se puede escribir
    assert "<b>Hoy</b>" in mesgs[3]
    # Alt+4 abre la captura y se cierra
    r = desk.run("@18 ")
    assert r.returncode == 0 and len(desk.calls()) == 5


def test_buscar_tareas_notas_y_dentro_del_texto(desk):
    desk.item("Mando buscar comprar pilas")
    desk.api(
        "POST",
        "/api/notes/mando-nota-receta",
        json={"title": "Mando nota receta", "category": "General", "content": "Lleva cardamomo y canela"},
    )
    desk.run("@17 ", "=Mando nota receta")
    rows = desk.calls()[1]["rows"]
    assert any("Mando buscar comprar pilas" in r for r in rows) and any("Mando nota receta" in r for r in rows)
    assert "XDG-OPEN" in desk.syslog() and "/?note=" in desk.syslog()

    desk.run("@17 ", "?cardamomo", "ESC")
    fts = desk.calls()[-1]
    assert any("Mando nota receta" in r and "cardamomo" in r for r in fts["rows"])
    assert "Dentro del texto" in fts["args"][fts["args"].index("-mesg") + 1]


def test_borrar_solo_desde_las_opciones_y_con_confirmacion(desk):
    t = desk.item("Mando borrar", due_date=HOY)
    desk.run("=Mando borrar", "=Borrar", "=Cancelar", "ESC")
    assert desk.get(t) is not None
    desk.run("=Mando borrar", "=Borrar", "=Borrar", "ESC")
    assert desk.get(t) is None
    assert "A la papelera" in desk.syslog()


def test_empezar_el_contador_y_completarlo_desde_su_fila(desk):
    t = desk.item("Mando contador", due_date=HOY)
    desk.run("@14 =Mando contador", "ESC")
    st = desk.api("GET", "/api/contador").json()["activa"]
    assert st and st["item_id"] == t
    desk.run("@10 =Mando contador", "ESC")  # la primera fila que lo contiene es la del contador
    assert desk.api("GET", "/api/contador").json()["activa"] is None and desk.get(t)["done"] is True


def _aviso(desk, r, boton):
    (desk.tmp / "boton").write_text(boton)
    return subprocess.run([sys.executable, str(DESK / "panel_agenda.py"), "--aviso", json.dumps(r)], env=desk.env,
                          capture_output=True, text=True, timeout=60)  # fmt: skip


def test_aviso_de_tarea_con_botones(desk):
    when = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
    t = desk.item("Mando aviso", due_date=when.date().isoformat(), due_time=when.strftime("%H:%M"))
    r = next(x for x in desk.api("GET", "/api/reminders?horizon=30").json()["reminders"] if x.get("item_id") == t)
    _aviso(desk, r, "1h")
    assert desk.get(t)["due_time"] == (when + timedelta(hours=1)).strftime("%H:%M")
    assert "--action=done=Completar" in desk.syslog() and "--action=start=Empezar" in desk.syslog()
    _aviso(desk, r, "done")
    assert desk.get(t)["done"] is True
    _aviso(desk, {"kind": "resumen", "key": "resumen@x", "title": "Hoy", "body": "1 tarea", "url": "/hoy"}, "default")
    assert "XDG-OPEN" in desk.syslog() and "/hoy" in desk.syslog()


def test_los_avisos_se_reclaman_y_no_se_repiten(monkeypatch, tmp_path):
    sys.path.insert(0, str(DESK))
    import panel_agenda as pa

    rems = [{"key": k, "kind": "tarea", "fire_at": "2026-11-15T08:00", "title": k, "body": ""} for k in ("a", "b", "c")]
    enviados, lanzados = [], []

    def req(method, path, body=None):
        enviados.append((method, path, body))
        if path.startswith("/api/reminders?"):
            return {"now": "2026-11-15T09:00", "settings": {}, "reminders": rems, "shown": ["a"]}
        if path == "/api/reminders/vistos":
            return {"claimed": ["c"]}  # «b» lo enseñó el navegador a la vez
        return {}

    monkeypatch.setattr(pa.pc, "request", req)
    monkeypatch.setattr(pa.pc, "queued", lambda: [])
    monkeypatch.setattr(pa, "SEEN", tmp_path / "avisos.json")
    monkeypatch.setattr(pa.pc, "STATE", tmp_path)
    monkeypatch.setattr(pa, "late_jobs", lambda: [])
    monkeypatch.setattr(pa, "spawn", lambda *a: lanzados.append(a))
    pa.side_jobs()
    assert ("POST", "/api/reminders/vistos", {"keys": ["b", "c"]}) in enviados
    assert [json.loads(a[1])["key"] for a in lanzados] == ["c"]
    pa.side_jobs()  # la segunda vez ya no se reclama nada
    assert len([e for e in enviados if e[1] == "/api/reminders/vistos"]) == 1

    # un Panel viejo (sin /api/reminders/vistos, servicio sin reiniciar) sigue avisando como antes
    def viejo(method, path, body=None):
        if path == "/api/reminders/vistos":
            raise RuntimeError("Error 404")
        return {"now": "2026-11-15T09:00", "settings": {}, "reminders": [{**rems[0], "key": "d"}]}

    monkeypatch.setattr(pa.pc, "request", viejo)
    pa.side_jobs()
    assert json.loads(lanzados[-1][1])["key"] == "d"


def test_barra_con_atrasadas_copias_y_cuenta_atras():
    sys.path.insert(0, str(DESK))
    import panel_agenda as pa

    now = datetime(2026, 11, 16, 10, 0)
    st = pa.status({"entries": [{"key": "x", "kind": "event", "title": "Examen", "start": "2026-11-16T12:10",
                                 "end": "2026-11-16T13:00", "all_day": False, "type": "examen"}]}, now)  # fmt: skip
    txt = pa.bar_text(st, now, late=3, copias=True)
    assert "en 2 h 10 Examen" in txt and f"{pa.I_LATE} 3" in txt and pa.I_BACKUP in txt
    assert pa.I_LATE not in pa.bar_text(st, now) and f"{pa.I_LATE} 20+" in pa.bar_text(st, now, late=20)
