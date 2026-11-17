"""Puente /estudio/ws (navegador ↔ placa) y autenticación de WebSocket (core/auth.py)."""

import asyncio
from pathlib import Path

import aiohttp
import pytest
from starlette.websockets import WebSocketDisconnect

from core import config, red
from estudio import main as est
from tests.conftest import TEST_API_TOKEN

ORIGEN = {"origin": "http://testserver"}


class Msg:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data


class PlacaFalsa:
    """Lo que devuelve `session.ws_connect`: guarda lo que le mandan y entrega lo que haya en su cola."""

    def __init__(self):
        self.recibido: list = []
        self.cola: asyncio.Queue = asyncio.Queue()
        self.cerrada = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        self.cerrada = True
        return False

    async def send_str(self, texto):
        self.recibido.append(texto)
        if texto == '{"type": "get_state"}':
            await self.cola.put(Msg(aiohttp.WSMsgType.TEXT, '{"type": "pomodoro_state", "run": "stopped"}'))
            await self.cola.put(Msg(aiohttp.WSMsgType.BINARY, b"\x00\x01\x02"))
        if texto == "cierra":
            await self.cola.put(None)

    async def send_bytes(self, datos):
        self.recibido.append(datos)

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self.cola.get()
        if m is None:
            raise StopAsyncIteration
        return m


class SesionFalsa:
    def __init__(self, placa=None, error=None):
        self.placa = placa
        self.error = error
        self.urls: list[str] = []

    def ws_connect(self, url, **kw):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.placa

    async def close(self):
        pass


@pytest.fixture()
def con_placa(client, monkeypatch):
    """Placa «en 192.168.1.35» atendida por una sesión de pega (no se abre ninguna conexión real)."""
    archivo = Path(config.DATA_DIR) / "red.json"
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()
    monkeypatch.setattr(config, "ESP32_HOST", "auto")
    monkeypatch.setattr(est, "ESP32_HOST", "auto")
    red.cargar()["esp32"]["ip"] = "192.168.1.35"
    buscadas = []

    async def buscar():
        buscadas.append(1)

    monkeypatch.setattr(est, "buscar_placa", buscar)
    placa = PlacaFalsa()
    sesion = SesionFalsa(placa)
    monkeypatch.setattr(est.app.state, "http_session", sesion, raising=False)
    yield placa, sesion, buscadas
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()


def test_sin_sesion_no_se_abre(anon):
    with pytest.raises(WebSocketDisconnect) as e, anon.websocket_connect("/estudio/ws", headers=ORIGEN):
        pass
    assert e.value.code == 1008


def test_con_sesion_pero_desde_otra_web_no_se_abre(client):
    """Un WebSocket no lleva la política del mismo origen: la cookie sola no basta (CSWSH)."""
    for cabeceras in ({"origin": "https://otra-web.example"}, {"origin": "null"}, {}):
        with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect("/estudio/ws", headers=cabeceras):
            pass
        assert e.value.code == 1008


def test_sin_placa_cierra_con_su_codigo(client, monkeypatch):
    monkeypatch.setattr(est, "ESP32_HOST", "")
    with client.websocket_connect("/estudio/ws", headers=ORIGEN) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4404


def test_reenvia_en_los_dos_sentidos(client, con_placa):
    placa, sesion, _ = con_placa
    with client.websocket_connect("/estudio/ws", headers=ORIGEN) as ws:
        ws.send_text('{"type": "get_state"}')
        assert ws.receive_text() == '{"type": "pomodoro_state", "run": "stopped"}'
        assert ws.receive_bytes() == b"\x00\x01\x02"
        ws.send_bytes(b"\x00\xa0\x00\x78" + bytes(100))  # el fondo, en binario
        ws.send_text("x" * (est.PROXY_MAX_TEXT + 1))  # demasiado grande para la placa: no pasa
        ws.send_bytes(bytes(est.PROXY_MAX_BINARY + 1))
        ws.send_text("cierra")  # la placa cuelga → el puente cierra al navegador
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 1000
    assert sesion.urls == ["ws://192.168.1.35/ws"]
    assert placa.recibido == ['{"type": "get_state"}', b"\x00\xa0\x00\x78" + bytes(100), "cierra"]
    assert placa.cerrada and est._proxy_abiertos == 0


def test_el_navegador_se_va_y_se_suelta_la_placa(client, con_placa):
    placa, _, _ = con_placa
    with client.websocket_connect("/estudio/ws", headers=ORIGEN) as ws:
        ws.send_text('{"type": "get_state"}')
        ws.receive_text()
    for _ in range(50):  # el cierre llega al puente un instante después
        if placa.cerrada:
            break
        __import__("time").sleep(0.02)
    assert placa.cerrada and est._proxy_abiertos == 0


def test_con_el_token_vale_sin_origin(anon, con_placa):
    with anon.websocket_connect("/estudio/ws", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}) as ws:
        ws.send_text('{"type": "get_state"}')
        assert "pomodoro_state" in ws.receive_text()


def test_placa_apagada_cierra_y_la_busca(client, con_placa, monkeypatch):
    _, _, buscadas = con_placa
    monkeypatch.setattr(est.app.state, "http_session", SesionFalsa(error=aiohttp.ClientConnectionError("apagada")))
    with client.websocket_connect("/estudio/ws", headers=ORIGEN) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4502 and buscadas == [1] and est._proxy_abiertos == 0


def test_tope_de_pestanas(client, con_placa, monkeypatch):
    monkeypatch.setattr(est, "_proxy_abiertos", est.PROXY_MAX)
    with client.websocket_connect("/estudio/ws", headers=ORIGEN) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 4429


def test_el_latido_llega_a_la_red(con_placa):
    """El puente de música es quien escucha a la placa: su latido actualiza la dirección y el estado."""

    class WS:
        closed = False

        def __init__(self):
            self.mensajes = [
                Msg(
                    aiohttp.WSMsgType.TEXT,
                    '{"type": "heartbeat", "ip": "192.168.1.34", "mac": "24:0a:c4:12:34:56", "fw": "2.4.0", "heap": 150000}',
                ),
                Msg(aiohttp.WSMsgType.TEXT, "no es json"),
            ]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.mensajes:
                raise StopAsyncIteration
            return self.mensajes.pop(0)

    asyncio.run(est.SpotifyBridge(session=None)._receiver_loop(WS()))
    e = red.estado()["esp32"]
    assert e["ip"] == "192.168.1.34" and e["fw"] == "2.4.0" and e["heap"] == 150000 and e["en_linea"] is True


def test_estado_dice_por_donde_entrar(client, con_placa):
    body = client.get("/estudio/api/esp32-status?check=0").json()
    assert body["ws_path"] == "/estudio/ws" and body["host"] == "192.168.1.35"
    assert "192.168.1.35" in client.get("/estudio/").text
