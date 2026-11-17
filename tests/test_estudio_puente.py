"""Puente Spotify ↔ ESP32 de estudio/main.py (T-1): lo que no necesita placa ni reproductor.
playerctl y el WebSocket se sustituyen por dobles; no se abre ninguna conexión."""

import asyncio
import io
import struct

import pytest
from PIL import Image

from estudio import main as est

SEP = est.FIELD_SEP


def _png(color=(200, 30, 30), size=(300, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeWS:
    def __init__(self):
        self.closed = False
        self.binary: list[bytes] = []

    async def send_bytes(self, data):
        self.binary.append(data)


# ── playerctl ──────────────────────────────────────────────────────────────


def test_metadata_completa(monkeypatch):
    raw = SEP.join(["Playing", "/track/1", "Canción", "Grupo", "185000000", "file:///tmp/a.png"])
    monkeypatch.setattr(est, "run_playerctl", lambda args, timeout=2: raw)
    m = est.get_metadata()
    assert m == {
        "status": "playing",
        "trackid": "/track/1",
        "title": "Canción",
        "artist": "Grupo",
        "duration_sec": 185,
        "art_url": "file:///tmp/a.png",
    }


def test_metadata_incompleta_o_rara(monkeypatch):
    monkeypatch.setattr(est, "run_playerctl", lambda args, timeout=2: SEP.join(["", "id", "", "", "no-num"]))
    m = est.get_metadata()
    assert m["status"] == "stopped" and m["title"] == "Desconocido" and m["duration_sec"] == 0 and m["art_url"] == ""
    monkeypatch.setattr(est, "run_playerctl", lambda args, timeout=2: None)
    assert est.get_metadata() is None


@pytest.mark.parametrize(("raw", "esperado"), [("12.5", 12.5), (None, None), ("abc", None)])
def test_posicion(monkeypatch, raw, esperado):
    monkeypatch.setattr(est, "run_playerctl", lambda args, timeout=2: raw)
    assert est.get_position_sec() == esperado


def test_comandos_solo_los_conocidos(monkeypatch):
    llamadas = []
    monkeypatch.setattr(est, "run_playerctl", lambda args, timeout=2: llamadas.append(args))
    for accion in ("play_pause", "next", "volume_down", "rm -rf", ""):
        est.playerctl_command(accion)
    assert llamadas == [["play-pause"], ["next"], ["volume", "0.05-"]]


def test_playerctl_ausente_no_rompe(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(est.subprocess, "run", boom)
    assert est.run_playerctl(["status"]) is None


# ── carátula ───────────────────────────────────────────────────────────────


def test_rgb565():
    assert est.rgb_to_565(255, 255, 255) == 0xFFFF
    assert est.rgb_to_565(0, 0, 0) == 0
    assert (
        est.rgb_to_565(255, 0, 0) == 0xF800
        and est.rgb_to_565(0, 255, 0) == 0x07E0
        and est.rgb_to_565(0, 0, 255) == 0x1F
    )


def test_marco_de_caratula_tamano_y_color():
    frame = est.build_cover_frame(Image.new("RGB", (400, 100), (255, 0, 0)))
    w, h = struct.unpack(">HH", frame[:4])
    assert (w, h) == (est.IMG_W, est.IMG_H)
    assert len(frame) == 4 + w * h * 2
    assert struct.unpack(">H", frame[4:6])[0] == 0xF800  # recorta al centro, no deforma ni cambia el color


def test_marco_y_acento_con_bytes_validos_y_rotos(capsys):
    frame, accent = est.build_image_frame_and_accent(_png((10, 200, 10)))
    assert frame and isinstance(accent, int)
    assert est.build_image_frame_and_accent(b"no es una imagen") == (None, None)
    # El color dominante: el más frecuente; el blanco puro (fondos, marcos) no cuenta
    assert accent == est.rgb_to_565(10, 200, 10)
    from PIL import Image

    mitad = Image.new("RGB", (100, 100), (255, 255, 255))
    mitad.paste((200, 20, 20), (0, 0, 40, 100))
    r, g, b = est.dominant_color(mitad)
    assert r > 180 and g < 60 and b < 60
    assert est.dominant_color(Image.new("RGB", (8, 8), (255, 255, 255))) == (255, 255, 255)  # si no hay otro


def test_caratula_de_archivo_y_esquemas_no_admitidos(tmp_path):
    img = tmp_path / "c.png"
    img.write_bytes(b"datos")

    async def go():
        assert await est.fetch_art_bytes(None, f"file://{img}") == b"datos"
        assert await est.fetch_art_bytes(None, f"file://{tmp_path}/no-existe.png") is None
        assert await est.fetch_art_bytes(None, "ftp://x/y.png") is None
        assert await est.fetch_art_bytes(None, "") is None

    asyncio.run(go())


# ── carga útil hacia el ESP32 ──────────────────────────────────────────────


def test_payload_parado_se_manda_una_vez(monkeypatch):
    monkeypatch.setattr(est, "get_metadata", lambda: None)
    bridge, ws = est.SpotifyBridge(None), FakeWS()

    async def go():
        assert await bridge._build_payload(ws) == {"type": "nowplaying", "status": "stopped"}
        assert await bridge._build_payload(ws) is None  # no repite «parado» cada segundo

    asyncio.run(go())


def test_payload_pista_nueva_manda_caratula_y_acento(monkeypatch, tmp_path):
    img = tmp_path / "c.png"
    img.write_bytes(_png())
    meta = {
        "status": "playing",
        "trackid": "t1",
        "title": "A",
        "artist": "B",
        "duration_sec": 200,
        "art_url": f"file://{img}",
    }
    monkeypatch.setattr(est, "get_metadata", lambda: dict(meta))
    monkeypatch.setattr(est, "get_position_sec", lambda: 42.7)
    bridge, ws = est.SpotifyBridge(None), FakeWS()

    async def go():
        p = await bridge._build_payload(ws)
        assert p["position_sec"] == 42 and p["duration_sec"] == 200 and p["title"] == "A"
        assert not ws.binary  # la carátula va después del título (tests/test_estudio_caratula.py)
        await bridge._send_cover_if_due(ws)
        assert len(ws.binary) == 1
        p = await bridge._build_payload(ws)
        await bridge._send_cover_if_due(ws)
        assert "accent_color" in p and len(ws.binary) == 1  # misma pista: la carátula no se vuelve a mandar

    asyncio.run(go())


def test_payload_sin_posicion_usa_el_reloj(monkeypatch):
    meta = {"status": "playing", "trackid": "t2", "title": "A", "artist": "", "duration_sec": 0, "art_url": ""}
    monkeypatch.setattr(est, "get_metadata", lambda: dict(meta))
    monkeypatch.setattr(est, "get_position_sec", lambda: None)
    bridge = est.SpotifyBridge(None)
    p = asyncio.run(bridge._build_payload(FakeWS()))
    assert p["position_sec"] == 0 and "accent_color" not in p


# ── API de la sub-app ──────────────────────────────────────────────────────


def test_estado_sin_placa(client):
    r = client.get("/estudio/api/esp32-status")
    assert r.status_code == 200
    body = r.json()
    assert {"state", "esp32_ws_url", "host"} <= set(body)
    if not est.ESP32_HOST:
        assert body["online"] is False
    assert client.get("/estudio/config").json()["esp32_host"] == est.esp32_host()
