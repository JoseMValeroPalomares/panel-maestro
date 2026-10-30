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
    return {"key": title, "kind": kind, "title": title, "start": start, "end": end, "all_day": all_day, "done": done, "type": type_,
            "item_id": 1, "id": 1, "day": start[:10]}


def test_estados():
    assert pa.status({"entries": []}, NOW)["class"] == "sin-eventos"
    s = pa.status({"entries": [ev("Dentista", "2026-10-24T17:00", "2026-10-24T18:00")]}, NOW)
    assert s["class"] == "proximo" and "en 30 min Dentista" in s["text"]
    s = pa.status({"entries": [ev("Clase", "2026-10-24T16:00", "2026-10-24T17:00")]}, NOW)
    assert s["class"] == "ahora" and "hasta 17:00" in s["text"]
    s = pa.status({"entries": [ev("Cena", "2026-10-24T21:00", "2026-10-24T22:00")]}, NOW)
    assert s["class"] == "con-eventos" and "21:00 Cena" in s["text"]
    s = pa.status({"entries": [ev("Leer", "2026-10-24T15:00", "2026-10-24T15:30", kind="routine", type_="rutina")]}, NOW)
    assert s["class"] == "retrasado" and "1 pendiente" in s["text"]
    s = pa.status({"entries": [ev("Leer", "2026-10-24T15:00", "2026-10-24T15:30", kind="routine", type_="rutina", done=True)]}, NOW)
    assert s["class"] == "sin-eventos"


def test_tooltip_mes_y_agenda():
    data = {"entries": [ev("Examen", "2026-10-25T09:00", "2026-10-25T11:00", type_="examen"), ev("Puente", "2026-10-24", "2026-10-26", all_day=True)]}
    t = pa.tooltip(data, NOW, True, 0)
    assert "Octubre 2026" in t and "<b>24</b>" in t and "Hoy · sábado 24" in t and "Mañana · domingo 25" in t
    assert t.count("Puente") == 2 and "Examen" in t  # el de varios días sale en los dos
    assert "Noviembre 2026" in pa.tooltip(data, NOW, True, 1)
    assert "Sin conexión" in pa.tooltip(data, NOW, False, 0)


def test_sin_conexion_usa_la_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "AGENDA", tmp_path / "agenda.json")
    hoy = datetime.now().date().isoformat()
    (tmp_path / "agenda.json").write_text(json.dumps({"entries": [ev("Guardado", f"{hoy}T23:58", f"{hoy}T23:59")], "saved_at": 1}))

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
    data = {"entries": [ev("Dentista", "2026-10-24T17:00", "2026-10-24T18:00"), ev("Viaje", "2026-10-28", "2026-10-29", all_day=True),
                        {**ev("Mañana", "2026-10-24T07:00", "2026-10-24T07:30", kind="routine", type_="rutina"),
                         "steps": [{"title": "a", "done": True}, {"title": "b", "done": False}]}],
            "overdue": [ev("Pagar luz", "2026-10-20", kind="task", all_day=True, type_="tarea")]}
    t = pa.tooltip(data, NOW, True, 0)
    assert "Sábado, 24 de octubre" in t and "1/2 pasos" in t and "Próximos días" in t and "Viaje" in t and "Atrasadas · 1" in t
    rows, what, heads, late, sel = pa.menu_rows(data, NOW.date(), NOW)
    assert what[:3] == ["new-event", "capture", "open-cal"]
    assert late and what[late[0]]["title"] == "Pagar luz" and what[late[0]]["overdue"]
    assert all(what[h] is None for h in heads) and "HOY" in rows[heads[1]]
    assert what[sel]['title'] == "Dentista"  # se abre sobre lo siguiente de hoy
