"""P-2: módulo de la Waybar del contador (scripts/desktop/panel_contador.py) con el Panel simulado."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/desktop"))
spec = importlib.util.spec_from_file_location("panel_contador", ROOT / "scripts/desktop/panel_contador.py")
pcon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pcon)

T0 = 1_800_000_000.0


def activa(**kw):
    return {
        "id": 5,
        "item_id": 9,
        "titulo": "Estudiar el tema 4 de IG",
        "padre": None,
        "tipo": "tarea",
        "prevista_min": 30,
        "estado": "marcha",
        "segundos": 600.0,
        "tramo_inicio": T0,
        "href": "/tareas?item=9",
        **kw,
    }


@pytest.fixture(autouse=True)
def estado_aparte(tmp_path, monkeypatch):
    monkeypatch.setattr(pcon.pc, "STATE", tmp_path)
    monkeypatch.setattr(pcon, "VISTO", tmp_path / "contador.json")
    monkeypatch.setattr(pcon, "PIDS", tmp_path / "contador.pids")


def test_render_calcula_el_tiempo_en_local():
    out = pcon.render({"activa": activa()}, now=T0 + 65)  # 10 min de antes + 1:05 de este tramo
    assert out["text"].endswith("11:05  Estudiar el tema 4 de IG") and out["class"] == ["marcha"]
    assert "30 min previstos" in out["tooltip"] and "Clic: pausar" in out["tooltip"]
    # con desfase: el reloj del portátil va 5 s por detrás del Panel
    assert "11:10" in pcon.render({"activa": activa()}, offset=5, now=T0 + 65)["text"]
    pausa = pcon.render({"activa": activa(estado="pausa", tramo_inicio=None)}, now=T0 + 999)
    assert "10:00" in pausa["text"] and pausa["class"] == ["pausa"] and "en pausa" in pausa["tooltip"]
    pasado = pcon.render({"activa": activa()}, now=T0 + 25 * 60)
    assert pasado["class"] == ["marcha", "pasado"] and "0:35:00" not in pasado["text"] and "35:00" in pasado["text"]
    assert pcon.render({"activa": None})["text"] == "" and pcon.render(None)["class"] == ["sin-conexion"]
    larga = pcon.render({"activa": activa(segundos=3 * 3600 + 5, tramo_inicio=None, estado="pausa")})
    assert "3:00:05" in larga["text"]
    paso = pcon.render({"activa": activa(tipo="paso", padre="Mañana")}, now=T0)
    assert "Paso de «Mañana»" in paso["tooltip"]
    assert "&lt;b&gt;" in pcon.render({"activa": activa(titulo="<b>x</b>")}, now=T0)["text"]  # Pango escapado


def test_notifica_al_empezar_y_al_pasarse_una_vez(monkeypatch):
    avisos = []
    monkeypatch.setattr(pcon, "notify", lambda *a: avisos.append(a))
    st = {"activa": activa()}
    assert pcon.notices(st, now=T0 + 60) == ["empezada"]
    assert pcon.notices(st, now=T0 + 120) == []  # ya avisado (también tras reiniciar la Waybar: va a disco)
    assert pcon.notices(st, now=T0 + 21 * 60) == ["pasada"]  # 10 + 21 > 30 min
    assert pcon.notices(st, now=T0 + 40 * 60) == []
    assert pcon.notices({"activa": activa(id=6)}, now=T0) == ["empezada"]  # otra sesión
    assert [a[1] for a in avisos][:2] == ["En marcha: Estudiar el tema 4 de IG", "Pasaste los 30 min previstos"]


def test_bucle_pregunta_poco_y_pinta_cada_segundo(monkeypatch, capsys):
    llamadas = []

    def req(method, path, body=None):
        llamadas.append((method, path))
        return {"ahora": pcon.time.time(), "activa": activa(tramo_inicio=pcon.time.time())}

    monkeypatch.setattr(pcon.pc, "request", req)
    monkeypatch.setattr(pcon, "notify", lambda *a: None)
    reloj = [0.0]
    monkeypatch.setattr(pcon.time, "monotonic", lambda: reloj[0])

    def dormir(s):  # 1 s de reloj por vuelta; el tiempo real avanza en `elapsed`
        reloj[0] += s
        pcon.time.sleep(0)

    monkeypatch.setattr(pcon, "REFRESCO", 30)
    pcon.run(max_lines=1, sleep=dormir)
    assert llamadas == [("GET", "/api/contador")]  # primera vez: GET; luego, latidos
    out = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert out["class"] == ["marcha"] and "Estudiar" in out["text"]
    assert (pcon.pc.STATE / "contador.pids" / str(pcon.os.getpid())).exists()


def test_clic_pausa_o_sigue_y_avisa_al_modulo(monkeypatch):
    enviados = []
    estado = {"activa": activa()}
    monkeypatch.setattr(pcon.pc, "request", lambda m, p, b=None: enviados.append((m, p)) or estado)
    toques = []
    monkeypatch.setattr(pcon, "poke", lambda: toques.append(1))
    assert pcon.toggle() == 0
    assert ("POST", "/api/contador/pausar") in enviados and toques
    estado["activa"] = activa(estado="pausa", tramo_inicio=None)
    enviados.clear()
    pcon.toggle()
    assert ("POST", "/api/contador/seguir") in enviados


def test_menu_cambiar_a_una_actividad_libre(monkeypatch):
    enviados = []

    def req(m, p, b=None):
        enviados.append((m, p, b))
        if p.startswith("/api/calendar/agenda"):
            return {"entries": [{"kind": "task", "item_id": 3, "title": "Llamar", "done": False}], "overdue": []}
        return {"ahora": T0, "activa": activa()}

    monkeypatch.setattr(pcon.pc, "request", req)
    monkeypatch.setattr(pcon, "poke", lambda: None)
    respuestas = iter([(2, ""), (None, "Ordenar el escritorio")])  # «Cambiar a otra…» y luego escribir
    monkeypatch.setattr(pcon, "rofi", lambda *a, **k: next(respuestas))
    assert pcon.menu() == 0
    assert ("POST", "/api/contador/empezar", {"titulo": "Ordenar el escritorio"}) in enviados
    respuestas = iter([(2, ""), (0, "")])  # o elegir una tarea de hoy
    monkeypatch.setattr(pcon, "rofi", lambda *a, **k: next(respuestas))
    pcon.menu()
    assert ("POST", "/api/contador/empezar", {"item_id": 3}) in enviados


def test_poke_avisa_a_cada_barra_y_olvida_pids_viejos(monkeypatch):
    d = pcon.pc.STATE / "contador.pids"
    d.mkdir()
    for pid in ("4242", "4343", "999"):
        (d / pid).touch()
    vivos = {4242, 4343}  # una instancia por monitor; el 999 ya es otro programa
    monkeypatch.setattr(pcon, "_es_modulo", lambda pid: pid in vivos)
    enviadas = []
    monkeypatch.setattr(pcon.os, "kill", lambda pid, sig: enviadas.append((pid, sig)))
    pcon.poke()
    assert sorted(enviadas) == [(4242, pcon.signal.SIGUSR1), (4343, pcon.signal.SIGUSR1)]
    assert sorted(f.name for f in d.iterdir()) == ["4242", "4343"]


def test_es_modulo_no_confunde_el_clic_ni_otros_programas():
    assert not pcon._es_modulo(pcon.os.getpid())  # pytest no es el módulo
    assert not pcon._es_modulo(0)
