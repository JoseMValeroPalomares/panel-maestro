"""Carátula de lo que suena (música o un vídeo del navegador) en la pantalla del ESP32.

La placa de pega repite lo que hace el firmware volcado (`esp32_deskclock/src/model/media.cpp`): al llegar un título
distinto tira la carátula que tuviera. El puente tiene que dejarla puesta pase lo que pase con el orden, con el
`trackid` (los navegadores dan siempre el mismo) y con una carátula que llega tarde o falla a la primera."""

import asyncio
import io
import json

from PIL import Image

from estudio import main as est


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


class PlacaDePega:
    """Doble del WebSocket que se comporta como music::update / music::setCover del firmware."""

    def __init__(self, vueltas: int):
        self.closed = False
        self.vueltas = vueltas
        self.titulo = ""
        self.caratula: bytes | None = None
        self.recibidas = 0

    async def send_str(self, texto: str):
        m = json.loads(texto)
        if m.get("status") in ("playing", "paused"):
            if m.get("title", "") != self.titulo and self.caratula:
                self.caratula = None  # «canción nueva: la carátula vieja ya no vale»
            self.titulo = m.get("title", "")
        self.vueltas -= 1
        if self.vueltas <= 0:
            self.closed = True

    async def send_bytes(self, datos: bytes):
        self.caratula = datos
        self.recibidas += 1


def _preparar(monkeypatch, pistas, arte):
    """`pistas`: una por vuelta (la última se repite). `arte(url)` → bytes o None."""
    cola = list(pistas)

    def metadata():
        m = cola.pop(0) if len(cola) > 1 else cola[0]
        return None if m is None else {"status": "playing", "artist": "", "duration_sec": 100, **m}

    async def traer(_session, url):
        return arte(url)

    monkeypatch.setattr(est, "get_metadata", metadata)
    monkeypatch.setattr(est, "get_position_sec", lambda: 1.0)
    monkeypatch.setattr(est, "fetch_art_bytes", traer)
    monkeypatch.setattr(est, "POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(est, "COVER_RETRY_DELAYS", (0, 0, 0, 0), raising=False)


def _sonar(vueltas: int) -> PlacaDePega:
    placa = PlacaDePega(vueltas)
    asyncio.run(est.SpotifyBridge(None)._sender_loop(placa))
    return placa


def test_cancion_nueva_la_caratula_no_la_borra_su_propio_titulo(monkeypatch):
    _preparar(
        monkeypatch, [{"trackid": "t1", "title": "A", "art_url": "http://x/a.png"}], lambda url: _png((200, 0, 0))
    )
    placa = _sonar(3)
    assert placa.caratula is not None, "el título de la canción llegó después de su carátula y la tiró"
    assert placa.recibidas == 1  # y no se manda en cada vuelta


def test_video_del_navegador_mismo_trackid_otro_titulo(monkeypatch):
    # Firefox y Chromium dan siempre el mismo trackid: lo que cambia es el título y la imagen
    pistas = [
        {"trackid": "/org/mpris/MediaPlayer2/firefox", "title": "Vídeo 1", "art_url": "file:///tmp/1.png"},
        {"trackid": "/org/mpris/MediaPlayer2/firefox", "title": "Vídeo 2", "art_url": "file:///tmp/2.png"},
    ]
    artes = {"file:///tmp/1.png": _png((200, 0, 0)), "file:///tmp/2.png": _png((0, 0, 200))}
    _preparar(monkeypatch, pistas, artes.get)
    placa = _sonar(4)
    assert placa.titulo == "Vídeo 2"
    assert placa.caratula is not None and placa.recibidas == 2


def test_la_imagen_llega_despues_que_el_titulo(monkeypatch):
    pistas = [
        {"trackid": "t1", "title": "A", "art_url": ""},
        {"trackid": "t1", "title": "A", "art_url": "http://x/a.png"},
    ]
    _preparar(monkeypatch, pistas, lambda url: _png((0, 200, 0)))
    assert _sonar(4).caratula is not None


def test_si_falla_se_reintenta_y_luego_se_rinde(monkeypatch):
    intentos = []

    def arte(url):
        intentos.append(url)
        return _png((9, 9, 9)) if len(intentos) == 3 else None

    _preparar(monkeypatch, [{"trackid": "t1", "title": "A", "art_url": "http://x/a.png"}], arte)
    placa = _sonar(6)
    assert placa.caratula is not None and len(intentos) == 3  # dos fallos, a la tercera llega y ya no se pide más

    intentos.clear()
    _preparar(
        monkeypatch, [{"trackid": "t9", "title": "Z", "art_url": "http://x/z.png"}], lambda url: intentos.append(url)
    )
    placa = _sonar(30)
    assert placa.caratula is None and len(intentos) == 4  # se rinde: ni se queda esperando ni insiste para siempre


def test_volver_a_una_cancion_no_la_descarga_otra_vez(monkeypatch):
    intentos = []

    def arte(url):
        intentos.append(url)
        return _png((1, 2, 3))

    pistas = [
        {"trackid": "t1", "title": "A", "art_url": "http://x/a.png"},
        {"trackid": "t2", "title": "B", "art_url": "http://x/b.png"},
        {"trackid": "t1", "title": "A", "art_url": "http://x/a.png"},
    ]
    _preparar(monkeypatch, pistas, arte)
    placa = _sonar(5)
    assert placa.caratula is not None and placa.recibidas == 3
    assert intentos == ["http://x/a.png", "http://x/b.png"]  # la tercera sale de la caché
