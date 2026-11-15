"""Las piezas de estudio/icloud_sync.py que sigue usando la sincronía en tres vías (T-1): conectar con el calendario,
borrar en iCloud y leer el calendario del ESP32. Con dobles: ni red, ni iCloud, ni placa."""

import asyncio
import json

import aiohttp
import pytest

from estudio import esp32_link
from estudio import icloud_sync as legacy

# ── CalDAV ─────────────────────────────────────────────────────────────────


class Cal:
    def __init__(self, name):
        self.name = name


class Principal:
    def __init__(self, names):
        self.cals = [Cal(n) for n in names]
        self.made = []

    def calendars(self):
        return self.cals

    def make_calendar(self, name):
        self.made.append(name)
        return Cal(name)


def _fake_dav(monkeypatch, principal):
    class Client:
        def __init__(self, **kw):
            self.kw = kw

        def principal(self):
            return principal

    monkeypatch.setattr(legacy.caldav, "DAVClient", Client)


def test_conecta_con_el_calendario_que_existe(monkeypatch):
    p = Principal(["Otro", legacy.ICLOUD_CALENDAR_NAME])
    _fake_dav(monkeypatch, p)
    assert legacy._connect_calendar().name == legacy.ICLOUD_CALENDAR_NAME
    assert p.made == []  # no crea otro


def test_crea_el_calendario_si_no_existe(monkeypatch):
    p = Principal(["Otro"])
    _fake_dav(monkeypatch, p)
    assert legacy._connect_calendar().name == legacy.ICLOUD_CALENDAR_NAME
    assert p.made == [legacy.ICLOUD_CALENDAR_NAME]


class Obj:
    def __init__(self, fail=False):
        self.fail, self.deleted = fail, False

    def delete(self):
        if self.fail:
            raise RuntimeError("412 Precondition Failed")
        self.deleted = True


def test_borrar_en_icloud():
    ok, mal = Obj(), Obj(fail=True)
    objects = {"a": ok, "b": mal}
    assert legacy._icloud_delete(objects, "a") is True and ok.deleted
    assert legacy._icloud_delete(objects, "no-estaba") is True  # ya no está: cuenta como borrado
    assert legacy._icloud_delete(objects, "b") is False  # el fallo se reintenta en el siguiente ciclo


def test_eventos_del_esp32_sin_uid_reciben_uno():
    evs = legacy._events_from_esp32(
        [
            {"uid": "u1", "date": "2026-11-20", "title": " Examen ", "type": "examen"},
            {"date": "2026-11-21", "title": "Sin uid", "type": "evento"},
        ]
    )
    assert evs["u1"] == {"date": "2026-11-20", "title": "Examen", "type": "examen"}
    nuevo = next(k for k in evs if k != "u1")
    assert nuevo.endswith("@panel-estudio")


# ── calendario del ESP32 por WebSocket ─────────────────────────────────────


class Msg:
    def __init__(self, data, kind=aiohttp.WSMsgType.TEXT):
        self.type, self.data = kind, data


class WS:
    def __init__(self, msgs, close_code=1000):
        self.msgs, self.sent, self.close_code = list(msgs), [], close_code

    async def send_str(self, s):
        self.sent.append(json.loads(s))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.msgs:
            raise StopAsyncIteration
        return self.msgs.pop(0)


class Session:
    def __init__(self, ws):
        self.ws = ws

    def ws_connect(self, *a, **kw):
        ws = self.ws

        class Ctx:
            async def __aenter__(self):
                return ws

            async def __aexit__(self, *exc):
                return False

        return Ctx()


@pytest.fixture()
def link(monkeypatch):
    nuevo = esp32_link.Esp32Link()
    monkeypatch.setattr(legacy, "LINK", nuevo)
    return nuevo


def test_lee_el_calendario_e_ignora_lo_demas(link):
    ws = WS(
        [
            Msg(b"\x00\x01", aiohttp.WSMsgType.BINARY),  # carátula
            Msg(json.dumps({"type": "pomodoro", "left": 300})),  # difusión de otro cliente
            Msg(
                json.dumps(
                    {
                        "type": "calendar_list",
                        "events": [{"uid": "x", "date": "2026-11-15", "title": "A", "type": "evento"}],
                    }
                )
            ),
        ]
    )
    bridge = legacy.IcloudSyncBridge(Session(ws), "ws://placa/ws")
    evs = asyncio.run(bridge._get_esp32_events())
    assert ws.sent == [{"type": "calendar_get"}]
    assert evs == {"x": {"date": "2026-11-15", "title": "A", "type": "evento"}}
    assert link.last_ok  # contacto puntual: cuenta como visto (el estado lo llevan los puentes conectados)


def test_conexion_cerrada_sin_calendario_avisa_una_vez(link, monkeypatch):
    registros = []
    monkeypatch.setattr(legacy.log, "warning", lambda msg, *a: registros.append(msg % a if a else msg))
    bridge = legacy.IcloudSyncBridge(Session(WS([Msg(json.dumps({"type": "pomodoro"}))], close_code=1006)), "ws://p")
    assert asyncio.run(bridge._get_esp32_events()) is None
    bridge.session = Session(WS([], close_code=1006))
    assert asyncio.run(bridge._get_esp32_events()) is None
    avisos = [m for m in registros if "cerró la conexión" in m]
    assert len(avisos) == 1 and "1006" in avisos[0]  # el panel avisa al cambiar de estado, no en cada ciclo


def test_respuesta_rota_no_rompe_el_ciclo(link):
    bridge = legacy.IcloudSyncBridge(Session(WS([Msg("{no es json")])), "ws://p")
    assert asyncio.run(bridge._get_esp32_events()) is None
    assert bridge._esp_problem == "error:JSONDecodeError"


def test_en_pausa_ni_lo_intenta(link, monkeypatch):
    monkeypatch.setattr(link, "state", "offline")
    monkeypatch.setattr(link, "can_try", lambda: False)

    class Nunca:
        def ws_connect(self, *a, **kw):
            raise AssertionError("no debía conectar")

    assert asyncio.run(legacy.IcloudSyncBridge(Nunca(), "ws://p")._get_esp32_events()) is None
