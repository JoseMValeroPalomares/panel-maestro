"""V-4: con el ESP32 apagado o mudo, la sincronía del calendario avisa en el log una vez, no en cada ciclo."""

import asyncio
import logging

import aiohttp
import pytest

from estudio import calendar_sync as cs
from estudio import esp32_link
from estudio import icloud_sync as legacy


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SesionCaida:
    """ws_connect que falla siempre igual: `error` es la excepción que lanza al conectar."""

    def __init__(self, error):
        self.error = error

    def ws_connect(self, *a, **kw):
        error = self.error

        class Ctx:
            async def __aenter__(self):
                raise error

            async def __aexit__(self, *exc):
                return False

        return Ctx()


class Recoge(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.registros = []

    def emit(self, record):
        self.registros.append(record)


@pytest.mark.parametrize(
    "error",
    [
        aiohttp.ClientConnectionError("Connect call failed"),  # apagado: no conecta
        TimeoutError(),  # mudo: no contesta
        OSError(113, "No route to host"),
    ],
)  # otro fallo cualquiera
def test_cinco_ciclos_con_el_esp32_caido_dan_un_solo_aviso(monkeypatch, error):
    reloj = Reloj()
    link = esp32_link.Esp32Link(clock=reloj)
    for mod in (cs, legacy, esp32_link):
        monkeypatch.setattr(mod, "LINK", link)
    monkeypatch.setattr(cs, "panel_events", lambda: {})
    recoge = Recoge()
    panel_log = logging.getLogger("panel")
    panel_log.addHandler(recoge)
    nivel = panel_log.level
    panel_log.setLevel(logging.INFO)
    try:
        bridge = cs.CalendarSyncBridge(SesionCaida(error), "ws://esp32.invalido/ws")
        for _ in range(5):
            asyncio.run(bridge._sync_esp32({"esp32": {}}))
            reloj.t = link.next_attempt + 1  # el siguiente ciclo sí intenta (pasada la espera o la pausa)
    finally:
        panel_log.removeHandler(recoge)
        panel_log.setLevel(nivel)
    avisos = [r for r in recoge.registros if r.levelno >= logging.WARNING]
    assert len(avisos) == 1, [r.getMessage() for r in recoge.registros]
    assert len(recoge.registros) <= 2  # como mucho, «no responde» (info) y «sin conexión» (aviso)
