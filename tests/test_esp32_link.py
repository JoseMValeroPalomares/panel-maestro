"""Conexión con el ESP32: pocos intentos, pausa, «Reintentar» y log sin bucles."""
import asyncio
import logging
import threading

from estudio.esp32_link import Esp32Link


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_espera_creciente_y_pausa():
    c = Clock()
    link = Esp32Link(fast_delays=(3, 6, 12), pause=600, clock=c)
    for espera in (3, 6, 12):
        assert link.can_try()
        link.failed("rechazada")
        assert link.state == "connecting"
        assert not link.can_try()
        c.t += espera
    link.failed("rechazada")
    assert link.state == "offline"
    c.t += 599
    assert not link.can_try()
    c.t += 1
    assert link.can_try()


def test_fallos_simultaneos_cuentan_una_vez():
    c = Clock()
    link = Esp32Link(clock=c)
    link.failed("a")
    link.failed("b")  # otro puente, mismo intento
    assert link.failures == 1


def test_reintentar_y_conectar():
    c = Clock()
    link = Esp32Link(fast_delays=(1,), pause=600, clock=c)
    link.failed("x")
    c.t += 1
    link.failed("x")
    assert link.state == "offline"
    link.retry()
    assert link.can_try() and link.state == "connecting" and link.failures == 0
    link.ok()
    assert link.status()["online"] and link.status()["last_ok"]
    link.closed()
    assert link.state == "connecting" and link.can_try()


def test_log_sin_bucles(caplog):
    c = Clock()
    link = Esp32Link(fast_delays=(3, 6, 12), pause=600, clock=c)
    with caplog.at_level(logging.INFO, logger="panel.esp32"):
        for _ in range(50):  # una hora larga de intentos
            link.failed("rechazada")
            c.t += 700
    assert len(caplog.records) <= 2, [r.getMessage() for r in caplog.records]


def test_wait_turn_despierta_al_reintentar():
    async def main():
        c = Clock()
        link = Esp32Link(fast_delays=(), pause=600, clock=c)
        link.failed("x")
        assert link.state == "offline"
        waiter = asyncio.create_task(link.wait_turn())
        await asyncio.sleep(0.05)
        assert not waiter.done()
        link.retry()
        await asyncio.wait_for(waiter, 1)
    # En un hilo propio: las pruebas de navegador dejan un bucle de asyncio en el principal
    errors = []
    t = threading.Thread(target=lambda: _run(main, errors))
    t.start()
    t.join(5)
    assert not errors, errors


def _run(coro_fn, errors):
    try:
        asyncio.run(coro_fn())
    except Exception as e:  # noqa: BLE001
        errors.append(e)


def test_api_estado_y_reintento(client):
    r = client.get("/estudio/api/esp32-status?check=false")
    assert r.status_code == 200
    assert {"state", "online", "retry_in"} <= set(r.json())
    r = client.post("/estudio/api/esp32/retry")
    assert r.status_code == 200 and "online" in r.json()
