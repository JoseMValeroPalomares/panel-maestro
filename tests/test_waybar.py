"""Módulo de la Waybar (scripts/desktop/panel_agenda.py): estados, tooltip y caché sin conexión."""

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/desktop"))
spec = importlib.util.spec_from_file_location("panel_agenda", ROOT / "scripts/desktop/panel_agenda.py")
pa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pa)

NOW = datetime(2026, 10, 24, 16, 30)


def ev(title, start, end=None, kind="event", done=False, all_day=False, type_="evento"):
    return {
        "key": title,
        "kind": kind,
        "title": title,
        "start": start,
        "end": end,
        "all_day": all_day,
        "done": done,
        "type": type_,
        "item_id": 1,
        "id": 1,
        "day": start[:10],
    }


def test_estados():
    assert pa.status({"entries": []}, NOW)["class"] == "sin-eventos"
    s = pa.status({"entries": [ev("Dentista", "2026-10-24T17:00", "2026-10-24T18:00")]}, NOW)
    assert s["class"] == "proximo" and "en 30 min Dentista" in s["text"]
    s = pa.status({"entries": [ev("Clase", "2026-10-24T16:00", "2026-10-24T17:00")]}, NOW)
    assert s["class"] == "ahora" and "hasta 17:00" in s["text"]
    s = pa.status({"entries": [ev("Cena", "2026-10-24T21:00", "2026-10-24T22:00")]}, NOW)
    assert s["class"] == "con-eventos" and "21:00 Cena" in s["text"]
    s = pa.status(
        {"entries": [ev("Leer", "2026-10-24T15:00", "2026-10-24T15:30", kind="routine", type_="rutina")]}, NOW
    )
    assert s["class"] == "retrasado" and "1 pendiente" in s["text"]
    s = pa.status(
        {"entries": [ev("Leer", "2026-10-24T15:00", "2026-10-24T15:30", kind="routine", type_="rutina", done=True)]},
        NOW,
    )
    assert s["class"] == "sin-eventos"


def test_tooltip_mes_y_agenda():
    data = {
        "entries": [
            ev("Examen", "2026-10-25T09:00", "2026-10-25T11:00", type_="examen"),
            ev("Puente", "2026-10-24", "2026-10-26", all_day=True),
        ]
    }
    t = pa.tooltip(data, NOW, True, 0)
    assert "Octubre 2026" in t and "<b>24</b>" in t and "Hoy · sábado 24" in t and "Mañana · domingo 25" in t
    assert t.count("Puente") == 2 and "Examen" in t  # el de varios días sale en los dos
    assert "Noviembre 2026" in pa.tooltip(data, NOW, True, 1)
    assert "Sin conexión" in pa.tooltip(data, NOW, False, 0)


def test_sin_conexion_usa_la_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "AGENDA", tmp_path / "agenda.json")
    hoy = datetime.now().date().isoformat()
    (tmp_path / "agenda.json").write_text(
        json.dumps({"entries": [ev("Guardado", f"{hoy}T23:58", f"{hoy}T23:59")], "saved_at": 1})
    )

    def caido(*a, **k):
        raise pa.pc.Offline("no")

    monkeypatch.setattr(pa.pc, "request", caido)
    monkeypatch.setattr(pa, "MONTH", tmp_path / "mes")
    out = pa.waybar()
    assert "sin-conexion" in out["class"] and "Guardado" in out["tooltip"]


def test_barra_tooltip_y_menu_nuevos():
    st = pa.status({"entries": [ev("Dentista", "2026-10-24T17:00", "2026-10-24T18:00")]}, NOW)
    txt = pa.bar_text(st, NOW)
    assert "<b>16:30</b>" in txt and "sáb 24" in txt and "en 30 min Dentista" in txt
    data = {
        "entries": [
            ev("Dentista", "2026-10-24T17:00", "2026-10-24T18:00"),
            ev("Viaje", "2026-10-28", "2026-10-29", all_day=True),
            {
                **ev("Mañana", "2026-10-24T07:00", "2026-10-24T07:30", kind="routine", type_="rutina"),
                "steps": [{"title": "a", "done": True}, {"title": "b", "done": False}],
            },
        ],
        "overdue": [ev("Pagar luz", "2026-10-20", kind="task", all_day=True, type_="tarea")],
    }
    t = pa.tooltip(data, NOW, True, 0)
    assert (
        "Sábado, 24 de octubre" in t
        and "1/2 pasos" in t
        and "Próximos días" in t
        and "Viaje" in t
        and "Atrasadas · 1" in t
    )
    rows, what, heads, late, sel = pa.menu_rows(data, NOW.date(), NOW)
    assert what[:3] == ["new-event", "capture", "open-cal"]
    assert late and what[late[0]]["title"] == "Pagar luz" and what[late[0]]["overdue"]
    assert all(what[h] is None for h in heads) and "HOY" in rows[heads[1]]
    assert what[sel]["title"] == "Dentista"  # se abre sobre lo siguiente de hoy


def test_color_de_la_asignatura_y_contexto():
    """Una clase o entrega de una asignatura sale con su color (Mocha) y el tooltip dice el contexto."""
    import importlib

    pa = importlib.import_module("panel_agenda")
    e = {
        "kind": "event",
        "type": "clase",
        "title": "GABD · Clase",
        "start": "2026-11-11T08:35",
        "end": "2026-11-11T10:30",
        "all_day": False,
        "color": "cat-6",
        "contexto": "universidad",
    }
    assert "#f9e2af" in pa.entry_line(e)
    assert pa.CONTEXTO in ("waybar", "activo", "todo", "puntual", "universidad", "proyectos")
    from datetime import datetime

    tip = pa.tooltip({"entries": [e], "contexto": "universidad"}, datetime(2026, 11, 11, 9, 0), True, 0)
    assert "Universidad" in tip and "GABD · Clase" in tip


def test_aviso_de_copias_clase_tooltip_y_una_notificacion_al_dia(tmp_path, monkeypatch):
    hoy = datetime.now().date().isoformat()
    respuestas = {"/api/backups/status": {"health": "antigua", "age_h": 50.0}}

    def req(method, path, *a, **k):
        if path.startswith("/api/calendar/agenda"):
            return {"entries": [ev("Algo", f"{hoy}T23:58", f"{hoy}T23:59")]}
        if path.startswith("/api/reminders"):
            return {"now": 0, "reminders": [], "settings": {}}
        return respuestas[path]

    avisos = []
    monkeypatch.setattr(pa.pc, "request", req)
    monkeypatch.setattr(pa.pc, "queued", lambda: 0)
    monkeypatch.setattr(pa, "notify", lambda *a, avisos=avisos: avisos.append(a))
    for name, value in (
        ("AGENDA", tmp_path / "agenda.json"),
        ("MONTH", tmp_path / "mes"),
        ("SEEN", tmp_path / "avisos.json"),
        ("COPIAS_AVISADO", tmp_path / "copias-avisado"),
        ("CACHE", tmp_path),
    ):
        monkeypatch.setattr(pa, name, value)
    monkeypatch.setattr(pa.pc, "STATE", tmp_path)
    out = pa.waybar()
    assert "copias-aviso" in out["class"] and "La última copia tiene 2 días" in out["tooltip"]
    pa.waybar()
    assert len([a for a in avisos if "copias" in a[1]]) == 1  # una al día como mucho

    respuestas["/api/backups/status"] = {"health": "ok", "age_h": 3}
    out = pa.waybar()
    assert "copias-aviso" not in out["class"] and "copia" not in out["tooltip"]


# ─────────────────────────────────────────────
# P-1: tareas atrasadas con botones
# ─────────────────────────────────────────────

ATRASADA = {"id": 7, "title": "Pagar la luz", "dias": 2, "due_date": "2026-10-22", "href": "/tareas?item=7"}


def test_atrasadas_se_anotan_y_se_lanzan_una_por_tarea(monkeypatch):
    llamadas, lanzadas = [], []
    resto = [{**ATRASADA, "id": i, "title": f"T{i}"} for i in range(10, 13)]

    def req(method, path, body=None):
        llamadas.append((method, path, body))
        if method == "GET":
            assert "avisar=1" in path and "contexto=" in path
            return {"atrasadas": [ATRASADA, *resto], "avisar": [7, 10, 11, 12]}
        return {"status": "success"}

    monkeypatch.setattr(pa.pc, "request", req)
    monkeypatch.setattr(pa, "spawn", lambda *a: lanzadas.append(a))
    out = pa.late_jobs()
    assert [e["id"] for e in out] == [7, 10, 11, 12]
    assert ("POST", "/api/items/atrasadas/avisadas", {"ids": [7, 10, 11, 12]}) in llamadas  # se anota antes de avisar
    assert [a[0] for a in lanzadas] == ["--atrasada"] * 3 + ["--atrasadas-resto"]
    assert json.loads(lanzadas[-1][1]) == [12]


def test_sin_nada_que_avisar_no_anota_ni_lanza(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        pa.pc,
        "request",
        lambda m, p, b=None: llamadas.append(m) or {"atrasadas": [ATRASADA], "avisar": []},
    )
    monkeypatch.setattr(pa, "spawn", lambda *a: (_ for _ in ()).throw(AssertionError("no debe lanzar")))
    assert pa.late_jobs() == [] and llamadas == ["GET"]


def _fake_notify(tmp_path, respuesta):
    """notify-send simulado: guarda sus argumentos y «pulsa» el botón `respuesta` (lo escribe por stdout)."""
    log = tmp_path / "args.json"
    script = tmp_path / "notify-send"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"print({respuesta!r})\n"
    )
    script.chmod(0o755)
    return script, log


def test_cada_boton_llama_a_la_api(tmp_path, monkeypatch):
    esperado = {
        "completar": {"ids": [7], "action": "completar"},
        "manana": {"ids": [7], "action": "posponer", "value": "manana"},
        "hoy_no": {"ids": [7], "action": "hoy_no"},
        "borrar": {"ids": [7], "action": "borrar"},
    }
    monkeypatch.setattr(pa, "refresh_bar", lambda: None)
    for boton, body in esperado.items():
        script, log = _fake_notify(tmp_path, boton)
        monkeypatch.setenv("PANEL_NOTIFY", str(script))
        enviados, avisos = [], []
        monkeypatch.setattr(pa.pc, "request", lambda m, p, b=None, enviados=enviados: enviados.append((m, p, b)) or {})
        monkeypatch.setattr(pa, "notify", lambda *a, avisos=avisos: avisos.append(a))
        assert pa.late_notification(ATRASADA)
        assert enviados == [("POST", "/api/items/atrasadas/accion", body)]
        args = json.loads(log.read_text())
        assert "Pagar la luz" in args and any("hace 2 días" in a for a in args)
        assert {"--action=completar=Completar", "--action=manana=Mañana", "--action=hoy_no=Hoy no"} <= set(args)
        assert avisos and avisos[0][2] == "Pagar la luz"  # confirmación discreta


def test_cerrar_sin_elegir_no_hace_nada_y_el_clic_abre_el_panel(tmp_path, monkeypatch):
    script, _ = _fake_notify(tmp_path, "")
    monkeypatch.setenv("PANEL_NOTIFY", str(script))
    monkeypatch.setattr(pa.pc, "request", lambda *a: (_ for _ in ()).throw(AssertionError("no debe llamar")))
    assert pa.late_notification(ATRASADA) == ""
    script, _ = _fake_notify(tmp_path, "default")
    monkeypatch.setenv("PANEL_NOTIFY", str(script))
    abiertos, popen = [], pa.subprocess.Popen

    def fake_popen(cmd, **k):
        if cmd[0] != "xdg-open":
            return popen(cmd, **k)  # el notify-send simulado sí se ejecuta
        abiertos.append(cmd)

    monkeypatch.setattr(pa.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(pa.pc, "base_url", lambda: "http://panel")
    assert pa.late_notification(ATRASADA) == "" and abiertos == [["xdg-open", "http://panel/tareas?item=7"]]


def test_resto_hoy_no_a_todas(tmp_path, monkeypatch):
    script, log = _fake_notify(tmp_path, "hoy_no")
    monkeypatch.setenv("PANEL_NOTIFY", str(script))
    enviados = []
    monkeypatch.setattr(pa.pc, "request", lambda m, p, b=None: enviados.append(b) or {})
    assert pa.late_rest_notification([10, 11]) == "Calladas hasta mañana"
    assert enviados == [{"ids": [10, 11], "action": "hoy_no"}]
    assert "Y 2 tareas atrasadas más" in json.loads(log.read_text())


def test_avisos_de_escritorio_apagados_no_avisan_atrasadas(monkeypatch):
    def req(m, p, b=None):
        if p.startswith("/api/reminders"):
            return {"now": "2026-10-24T10:00", "reminders": [], "settings": {"escritorio": {"on": False}}}
        raise AssertionError(f"no debe pedir {p}")

    monkeypatch.setattr(pa.pc, "request", req)
    monkeypatch.setattr(pa.pc, "queued", lambda: 0)
    pa.side_jobs()
