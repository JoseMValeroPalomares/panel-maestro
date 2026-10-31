"""Sincronía del calendario: Panel ↔ iCloud (CalDAV simulado) ↔ ESP32 (simulado)."""
import asyncio
import json
import threading
from datetime import date, timedelta

import pytest

from app.database import get_db
from estudio import calendar_sync as cs
from estudio import icloud_sync as legacy

D = lambda n: (date(2030, 1, 7) + timedelta(days=n)).isoformat()  # noqa: E731  (lejos de otros tests)


class FakeObj:
    def __init__(self, cal, data):
        self.cal, self.data = cal, data

    def load(self):
        pass

    def save(self):
        pass

    def delete(self):
        self.cal.objs.remove(self)


class FakeCal:
    def __init__(self):
        self.objs = []

    def events(self):
        return list(self.objs)

    def save_event(self, ics):
        self.objs.append(FakeObj(self, ics))

    def add(self, uid, ev):
        self.save_event(cs.build_ics(uid, cs.canon(ev)))

    def view(self):
        return cs.icloud_fetch(self, {})


class FakeWS:
    def __init__(self, sink):
        self.sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send_str(self, s):
        self.sink.append(json.loads(s))


class FakeSession:
    def __init__(self):
        self.sent = []

    def ws_connect(self, *a, **k):
        return FakeWS(self.sent)


@pytest.fixture()
def mundo(client, monkeypatch, tmp_path):  # client: arranca el Panel (BD creada)
    cal = FakeCal()
    esp = {"events": {}}
    monkeypatch.setattr(cs, "STATE_FILE", tmp_path / "estado.json")
    monkeypatch.setattr(legacy, "ICLOUD_USERNAME", "u")
    monkeypatch.setattr(legacy, "ICLOUD_APP_PASSWORD", "p")
    monkeypatch.setattr(legacy, "_connect_calendar", lambda: cal)
    session = FakeSession()
    bridge = cs.CalendarSyncBridge(session, "ws://esp32/ws")

    async def leer_esp32():
        return {uid: dict(v) for uid, v in esp["events"].items()}
    bridge._legacy._get_esp32_events = leer_esp32
    monkeypatch.setattr(cs.asyncio, "sleep", _no_sleep)
    with get_db() as conn:
        conn.execute("DELETE FROM events")  # BD de pruebas: sin los eventos de otros tests

    def ciclo():
        _run(bridge.sync_once())
        if session.sent:  # el ESP32 se queda con la lista que se le manda
            esp["events"] = {e["uid"]: {"date": e["date"], "title": e["title"], "type": e["type"]} for e in session.sent[-1]["events"]}
    return cal, esp, ciclo


async def _no_sleep(*a, **k):
    return None


def _run(coro):
    err = []
    t = threading.Thread(target=lambda: _safe(coro, err))
    t.start()
    t.join(10)
    assert not err, err


def _safe(coro, err):
    try:
        asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        err.append(e)


def panel():
    with get_db() as conn:
        return {r["uid"]: dict(r) for r in conn.execute("SELECT * FROM events")}


def test_three_way_reglas():
    tw = cs.three_way
    last = {"a": 1, "b": 1, "c": 1, "d": 1}
    p = tw({"a": 1, "b": 2, "c": 1, "n": 5}, {"a": 1, "b": 1, "c": 3, "m": 7}, {**last, "d": 1})
    assert p["same"] == {"a": 1}
    assert p["to_remote"] == {"b": 2, "n": 5}       # cambió en el Panel / nuevo en el Panel
    assert p["to_local"] == {"c": 3, "m": 7}        # cambió fuera / nuevo fuera
    assert set(p["del_local"]) == set() and set(p["del_remote"]) == set()
    p = tw({"x": 1}, {"y": 1}, {"x": 1, "y": 1})    # x se borró fuera, y en el Panel
    assert p["del_local"] == ["x"] and p["del_remote"] == ["y"]
    p = tw({"z": 1}, {"z": 2}, {"z": 0})            # cambió en los dos: gana el Panel
    assert p["to_remote"] == {"z": 1}


def test_union_inicial_sin_borrar_nada(mundo):
    cal, esp, ciclo = mundo
    cal.add("u1", {"title": "Examen Mates", "start": D(0), "end": None, "all_day": True, "kind": "examen"})
    cal.add("u2", {"title": "Tutoría", "start": f"{D(1)}T10:00", "end": f"{D(1)}T11:00", "all_day": False, "kind": "evento"})
    esp["events"] = {"u1": {"date": D(0), "title": "Examen Mates", "type": "examen"},
                     "u3": {"date": D(2), "title": "Entrega TFG", "type": "entrega"}}
    ciclo()
    p = panel()
    assert set(p) == {"u1", "u2", "u3"}
    assert p["u2"]["start"] == f"{D(1)}T10:00" and p["u1"]["kind"] == "examen"
    ciclo()  # el segundo ciclo sube a iCloud lo que vino del ESP32 y todo queda igual
    assert set(cal.view()) == {"u1", "u2", "u3"} and set(esp["events"]) == {"u1", "u2", "u3"}
    ciclo()
    assert len(panel()) == 3


def test_borrados_y_ediciones_en_cada_sentido(mundo):
    cal, esp, ciclo = mundo
    from app.calendar import EventIn, EventPatch, create_event, delete_event, update_event
    a = create_event(EventIn(title="Dentista", start=f"{D(3)}T17:00"))
    b = create_event(EventIn(title="Cine", start=f"{D(4)}T20:00"))
    ciclo()
    uid_a = next(u for u, r in panel().items() if r["id"] == a)
    uid_b = next(u for u, r in panel().items() if r["id"] == b)
    assert {uid_a, uid_b} <= set(cal.view()) and {uid_a, uid_b} <= set(esp["events"])
    # el ESP32 mueve «Dentista» de día: el Panel cambia el día y conserva la hora
    esp["events"][uid_a]["date"] = D(5)
    ciclo()
    assert panel()[uid_a]["start"] == f"{D(5)}T17:00" and panel()[uid_a]["end"] == f"{D(5)}T18:00"
    ciclo()
    assert cal.view()[uid_a]["start"] == f"{D(5)}T17:00"
    # se edita en el Panel → llega a iCloud
    update_event(b, EventPatch(title="Cine con Ana"))
    ciclo()
    assert cal.view()[uid_b]["title"] == "Cine con Ana" and esp["events"][uid_b]["title"] == "Cine con Ana"
    # se borra en iCloud → desaparece del Panel (a la papelera) y del ESP32
    next(o for o in cal.objs if uid_a in o.data).delete()
    ciclo()
    assert uid_a not in panel() and uid_a not in esp["events"]
    # se borra en el Panel → desaparece de iCloud y del ESP32
    delete_event(b)
    ciclo()
    assert uid_b not in cal.view() and uid_b not in esp["events"]


def test_guarda_lectura_vacia(mundo):
    cal, esp, ciclo = mundo
    for i in range(5):
        cal.add(f"g{i}", {"title": f"Evento {i}", "start": D(i), "end": None, "all_day": True, "kind": "evento"})
    ciclo()
    assert len(panel()) == 5
    cal.objs.clear()  # iCloud devuelve 0 de repente
    ciclo()
    assert len(panel()) == 5  # nada borrado
    assert cs.STATUS["icloud"]["state"] == "error"


def test_sin_duplicados(mundo):
    cal, esp, ciclo = mundo
    from app.calendar import EventIn, create_event
    create_event(EventIn(title="Reunión", start=D(6), all_day=True))
    cal.add("ext-1", {"title": "reunión", "start": D(6), "end": None, "all_day": True, "kind": "evento"})
    ciclo()
    p = panel()
    assert [r["title"] for r in p.values()] == ["Reunión"] and "ext-1" in p  # el Panel adoptó el uid de iCloud
    ciclo()
    assert len(cal.view()) == 1


def test_lugar_en_los_dos_sentidos(mundo):
    cal, esp, ciclo = mundo
    from app.calendar import EventIn, EventPatch, create_event, update_event
    a = create_event(EventIn(title="Médico", start=f"{D(8)}T10:00"))
    ciclo()
    uid = next(u for u, r in panel().items() if r["id"] == a)
    assert "location" not in cal.view()[uid]  # sin lugar: la forma de siempre
    update_event(a, EventPatch(location="Centro de salud"))
    ciclo()
    assert cal.view()[uid]["location"] == "Centro de salud"
    # cambia en iCloud (otro lugar) → llega al Panel
    obj = next(o for o in cal.objs if uid in o.data)
    obj.data = cs.build_ics(uid, {**cal.view()[uid], "location": "Hospital"})
    ciclo()
    assert panel()[uid]["location"] == "Hospital"


def test_vaciar_los_dos_lados_no_es_un_error(mundo):
    """Lo borrado en el Panel y en el móvil coincide: antes daba «lectura fallida» en cada ciclo, para siempre."""
    cal, esp, ciclo = mundo
    for i in range(5):
        cal.add(f"v{i}", {"title": f"Evento {i}", "start": D(i), "end": None, "all_day": True, "kind": "evento"})
    ciclo()
    assert len(panel()) == 5

    with get_db() as conn:
        conn.execute("DELETE FROM events")
    ciclo()  # solo el Panel vacío: la guarda sigue protegiendo iCloud
    assert len(cal.view()) == 5 and cs.STATUS["icloud"]["state"] == "error"

    cal.objs.clear()  # ahora también en el móvil
    esp["events"] = {}
    ciclo()
    assert cs.STATUS["icloud"]["state"] == "ok" and cs.STATUS["esp32"]["state"] == "ok"
    assert cs.load_state() == {"icloud": {}, "esp32": {}}

    cal.add("v9", {"title": "Nuevo", "start": D(0), "end": None, "all_day": True, "kind": "evento"})
    ciclo()  # y la sincronía sigue viva
    assert [e["title"] for e in panel().values()] == ["Nuevo"]
