#!/usr/bin/env python3
"""
estudio/main.py  (PYTHON - FastAPI)

Sub-aplicacion FastAPI del Panel ESP32 (Reloj / Spotify / Estudio).
Migrado desde aiohttp.web para poder fusionarse con el Cerebro Digital
en un unico proceso uvicorn (se monta en el proceso raiz con
`app.mount("/estudio", app)` desde el main.py de nivel superior).

IMPORTANTE: el puente Spotify/iCloud <-> ESP32 sigue actuando como
CLIENTE websocket hacia el ESP32 (usa aiohttp.ClientSession para eso),
eso no ha cambiado nada respecto a la version aiohttp original. Lo
unico que cambia es quien atiende al NAVEGADOR: antes aiohttp.web,
ahora FastAPI/Starlette, para poder vivir bajo el prefijo "/estudio"
dentro del mismo proceso que el Cerebro Digital.

NO CONFUNDIR con el firmware del ESP32 (main.ino, en C++) ni con el
main.py de la RAIZ del proyecto panel-maestro (ese solo hace los
app.mount(...) de las tres apps). Este archivo es exclusivamente
Python y vive dentro de la carpeta estudio/.
"""

import asyncio
import contextlib
import io
import json
import struct
import subprocess
import time
from pathlib import Path

import aiohttp
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

# =====================================================================
# CONFIGURACION
# =====================================================================
from core import config, red
from core.templating import render

from .calendar_sync import CalendarSyncBridge
from .esp32_link import LINK, buscar_placa, keep_connected
from .note_review import NoteReviewBridge

# Sin ESP32_HOST no hay placa. Con él («auto» o una dirección), dónde está lo dice core/red.py en cada momento:
# aquí no se guarda ninguna IP.
ESP32_HOST = config.ESP32_HOST


def esp32_host() -> str:
    """La dirección de la placa en este momento (core/red.py la busca y la recuerda); «» sin placa."""
    return red.esp32_host() if ESP32_HOST else ""


def esp32_ws_url() -> str:
    return red.esp32_ws_url() if ESP32_HOST else ""


# Puente /estudio/ws (navegador ↔ placa): límites que protegen a la placa
PROXY_MAX = 4  # pestañas a la vez (el firmware admite 8 clientes y el panel ya ocupa 3)
PROXY_MAX_TEXT = 32 * 1024  # los mismos topes que el firmware (device.cpp: MAX_TEXT, MAX_BINARY)
PROXY_MAX_BINARY = 48 * 1024
_proxy_abiertos = 0


POLL_INTERVAL_SEC = 1.0
# Carátula: esperas (s) antes de cada intento; agotados, se deja el disco de la placa
COVER_RETRY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0, 15.0)
COVER_CACHE_MAX = 12  # ~29 KB cada una

IMG_W = 120
IMG_H = 120  # carátula cuadrada; el firmware acepta hasta 160x160 (160x120 es el fondo)

STATIC_DIR = Path(__file__).parent / "static"

# =====================================================================
# UTILIDADES: playerctl / MPRIS
# =====================================================================
FIELD_SEP = "\x1f"


def run_playerctl(args, timeout=2):
    if config.IS_WINDOWS:  # P-12: no hay MPRIS en Windows; no se lanza un proceso que no existe en cada sondeo
        return None
    try:
        result = subprocess.run(["playerctl"] + args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_metadata():
    fmt = FIELD_SEP.join(
        ["{{status}}", "{{mpris:trackid}}", "{{title}}", "{{artist}}", "{{mpris:length}}", "{{mpris:artUrl}}"]
    )
    raw = run_playerctl(["metadata", "--format", fmt])
    if not raw:
        return None

    parts = raw.split(FIELD_SEP)
    while len(parts) < 6:
        parts.append("")
    status, trackid, title, artist, length_us, art_url = parts[:6]

    try:
        duration_sec = int(int(length_us) / 1_000_000) if length_us else 0
    except ValueError:
        duration_sec = 0

    return {
        "status": status.lower() if status else "stopped",
        "trackid": trackid,
        "title": title or "Desconocido",
        "artist": artist or "",
        "duration_sec": duration_sec,
        "art_url": art_url,
    }


def get_position_sec():
    raw = run_playerctl(["position"])
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def playerctl_command(action):
    mapping = {
        "play_pause": ["play-pause"],
        "next": ["next"],
        "previous": ["previous"],
        "volume_up": ["volume", "0.05+"],
        "volume_down": ["volume", "0.05-"],
    }
    args = mapping.get(action)
    if args:
        run_playerctl(args)


# =====================================================================
# UTILIDADES: caratula -> imagen real SIN desenfoque (RGB565 binario)
# =====================================================================
def rgb_to_565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


async def fetch_art_bytes(session: aiohttp.ClientSession, art_url: str):
    if not art_url:
        return None
    try:
        if art_url.startswith("file://"):
            path = art_url[len("file://") :]
            return await asyncio.to_thread(Path(path).read_bytes)
        if art_url.startswith("http://") or art_url.startswith("https://"):
            async with session.get(art_url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    return await resp.read()
        return None
    except Exception:
        return None


def build_cover_frame(img: Image.Image) -> bytes:
    """Cabecera ancho/alto (big-endian) + píxeles RGB565 big-endian. Recorta al
    centro en vez de estirar, para que una carátula no cuadrada no se deforme."""
    small = ImageOps.fit(img.convert("RGB"), (IMG_W, IMG_H), Image.LANCZOS)
    raw = small.tobytes()
    body = bytearray(IMG_W * IMG_H * 2)
    for i in range(IMG_W * IMG_H):
        struct.pack_into(">H", body, i * 2, rgb_to_565(raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]))
    return struct.pack(">HH", IMG_W, IMG_H) + bytes(body)


def dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """Color dominante de una imagen (corte por la mediana, 5 colores; el más frecuente que no sea blanco puro).
    Antes lo daba `colorthief`, que usa `Image.getdata` (desaparece en Pillow 14); con Pillow solo es lo mismo."""
    small = img.convert("RGB")
    small.thumbnail((96, 96))
    q = small.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    colores = [tuple(pal[i * 3 : i * 3 + 3]) for _, i in sorted(q.getcolors() or [], reverse=True)]
    colores = [c for c in colores if len(c) == 3]
    if not colores:
        return (128, 128, 128)
    return next((c for c in colores if not all(v > 250 for v in c)), colores[0])


def build_image_frame_and_accent(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        frame = build_cover_frame(img)
        accent = rgb_to_565(*dominant_color(img))

        return frame, accent
    except Exception as e:
        print(f"[spotify-bridge] Error generando imagen de fondo: {e}")
        return None, None


# =====================================================================
# PUENTE SPOTIFY <-> ESP32 (cliente websocket hacia el ESP32)
# =====================================================================
class SpotifyBridge:
    """Manda a la placa lo que suena (título, posición) y su carátula.

    La carátula va SIEMPRE después del `nowplaying` que estrena su título: el firmware tira la que tenga en cuanto
    llega un título distinto, así que mandada antes (como se hacía) la borraba su propia canción. Se decide por
    (trackid, título, imagen), no solo por trackid: los navegadores dan el mismo para todos los vídeos y muchos
    reproductores publican la imagen un momento después que el título. Si no llega se reintenta con espera creciente
    y, agotados los intentos, se deja el disco de la placa (nunca se queda esperando)."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.last_track = None  # (trackid, título): lo que la placa considera «la canción»
        self.cached_accent = None
        self.track_start_monotonic = None
        self.last_sent_status = None
        self.cover_key = None  # (trackid, título, art_url) de la carátula que toca
        self.cover_sent = False
        self.cover_tries = 0
        self.cover_next = 0.0
        self.cover_cache: dict[str, tuple[bytes, int | None]] = {}  # art_url → (marco, acento)

    async def run_forever(self):
        # Espera creciente, pausa y «Reintentar» comunes a todos los puentes (esp32_link.py)
        await keep_connected(self.session, esp32_ws_url, self._serve, heartbeat=15, max_msg_size=0)

    async def _serve(self, ws):
        self._reset()  # tras reconectar, la carátula se vuelve a mandar
        await asyncio.gather(
            self._sender_loop(ws),
            self._receiver_loop(ws),
        )

    def _reset(self):
        self.last_track = None
        self.last_sent_status = None
        self.cover_key = None
        self.cover_sent = False

    async def _sender_loop(self, ws: aiohttp.ClientWebSocketResponse):
        while not ws.closed:
            payload = await self._build_payload(ws)
            if payload is not None:
                await ws.send_str(json.dumps(payload))
            await self._send_cover_if_due(ws)  # después del título (ver la clase)
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _receiver_loop(self, ws: aiohttp.ClientWebSocketResponse):
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "cmd":
                    action = data.get("action", "")
                    print(f"[spotify-bridge] Comando recibido: {action}")
                    await asyncio.to_thread(playerctl_command, action)
                elif data.get("type") == "heartbeat":  # latido del firmware: IP, MAC, versión, memoria, señal
                    await asyncio.to_thread(red.latido_esp32, data)

    async def _build_payload(self, ws: aiohttp.ClientWebSocketResponse):
        # playerctl y la carátula, en un hilo: en el bucle pararían todo el panel en cada sondeo (hasta 2 s si cuelga)
        meta = await asyncio.to_thread(get_metadata)

        if meta is None:
            self.cover_key = None
            if self.last_sent_status == "stopped":
                return None
            self.last_sent_status = "stopped"
            self.last_track = None
            self.cached_accent = None
            return {"type": "nowplaying", "status": "stopped"}

        status = meta["status"]
        track = (meta["trackid"], meta["title"])
        if track != self.last_track:
            self.last_track = track
            self.track_start_monotonic = time.monotonic()
            self.cached_accent = None
        key = (*track, meta["art_url"])
        if key != self.cover_key:  # canción nueva, o su imagen acaba de aparecer o cambiar
            self.cover_key = key
            self.cover_sent = False
            self.cover_tries = 0
            self.cover_next = 0.0
            if meta["art_url"] in self.cover_cache:  # el acento, ya en este mismo mensaje
                self.cached_accent = self.cover_cache[meta["art_url"]][1]

        pos = await asyncio.to_thread(get_position_sec)
        if pos is None or (
            pos == 0 and status == "playing" and time.monotonic() - (self.track_start_monotonic or 0) > 3
        ):
            pos = time.monotonic() - (self.track_start_monotonic or time.monotonic())
        pos = max(0, int(pos))

        self.last_sent_status = status

        payload = {
            "type": "nowplaying",
            "status": status,
            "title": meta["title"],
            "artist": meta["artist"],
            "position_sec": pos,
            "duration_sec": meta["duration_sec"],
            "has_art": bool(meta["art_url"]),  # sin imagen, la placa suelta la carátula anterior (firmware 2026.11)
        }
        if self.cached_accent is not None:
            payload["accent_color"] = self.cached_accent

        return payload

    async def _send_cover_if_due(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Manda la carátula de `cover_key` si falta: de la caché, o pidiéndola con reintentos contados."""
        if self.cover_key is None or self.cover_sent:
            return
        art_url = self.cover_key[2]
        if not art_url or self.cover_tries >= len(COVER_RETRY_DELAYS) or time.monotonic() < self.cover_next:
            return
        cached = self.cover_cache.get(art_url)
        if cached is None:
            art_bytes = await fetch_art_bytes(self.session, art_url)
            frame, accent = (
                await asyncio.to_thread(build_image_frame_and_accent, art_bytes) if art_bytes else (None, None)
            )
            if frame is None:  # aún no está (o falló): otro intento más tarde, hasta agotar los previstos
                self.cover_tries += 1
                if self.cover_tries < len(COVER_RETRY_DELAYS):
                    self.cover_next = time.monotonic() + COVER_RETRY_DELAYS[self.cover_tries]
                else:
                    print(f"[spotify-bridge] Sin carátula tras {self.cover_tries} intentos: {art_url[:120]}")
                return
            cached = (frame, accent)
            if not art_url.startswith("file://"):  # un archivo local puede cambiar de contenido con el mismo nombre
                self.cover_cache[art_url] = cached
                while len(self.cover_cache) > COVER_CACHE_MAX:
                    self.cover_cache.pop(next(iter(self.cover_cache)))
        await ws.send_bytes(cached[0])
        self.cover_sent = True
        self.cached_accent = cached[1]


# =====================================================================
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_session = None
    if config.DISABLE_BRIDGES:
        print("[estudio] Puentes desactivados (PANEL_DISABLE_BRIDGES)")
        LINK.state = "disabled"
        yield
        if app.state.http_session is not None:  # la abrió el puente /estudio/ws
            await app.state.http_session.close()
        return
    print("[estudio] Iniciando puentes Spotify / iCloud / Repaso de notas...")
    if not ESP32_HOST:
        LINK.state = "disabled"  # sin placa solo queda la sincronía con iCloud
    # Conectar a una placa apagada falla en segundos, no a los 5 min por defecto
    session = _nueva_sesion()
    app.state.http_session = session

    # Calendario del Panel ↔ iCloud ↔ ESP32 (antes solo iCloud ↔ ESP32)
    tasks = [asyncio.create_task(CalendarSyncBridge(session, esp32_ws_url if ESP32_HOST else "").run_forever())]
    if ESP32_HOST:
        tasks.append(asyncio.create_task(SpotifyBridge(session).run_forever()))
        tasks.append(asyncio.create_task(NoteReviewBridge(session, esp32_ws_url).run_forever()))

    yield
    print("[estudio] Apagando puentes...")
    for task in tasks:
        task.cancel()
    await app.state.http_session.close()


def _nueva_sesion() -> aiohttp.ClientSession:
    # Conectar a una placa apagada falla en segundos, no a los 5 min por defecto
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=8, sock_connect=5))


app = FastAPI(title="Panel ESP32 - Estudio", lifespan=lifespan)


@app.get("/config")
async def handle_config():
    return JSONResponse({"esp32_ws_url": esp32_ws_url(), "esp32_host": esp32_host(), "ws_path": "/estudio/ws"})


async def _tcp_check() -> bool:
    host = esp32_host()
    if not host:
        return False
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, 80), timeout=1.5)
        writer.close()
        return True
    except (TimeoutError, OSError):
        return False


@app.websocket("/ws")
async def ws_proxy(websocket: WebSocket):
    """Puente navegador ↔ placa. La web de Estudio ya no abre `ws://<ip>/ws` por su cuenta: bajo HTTPS el navegador
    lo bloquea (contenido mixto) y desde fuera de casa esa IP no existe. Entra por aquí (con la sesión del panel:
    core/auth.py) y el panel, que sí está en la red de la placa, reenvía en los dos sentidos.

    Códigos de cierre: 4404 sin placa configurada · 4429 demasiadas pestañas · 4502 la placa no responde."""
    global _proxy_abiertos
    await websocket.accept()
    url = esp32_ws_url()
    if not url:
        await websocket.close(code=4404, reason="Sin placa configurada")
        return
    if _proxy_abiertos >= PROXY_MAX:
        await websocket.close(code=4429, reason="Demasiadas conexiones con la placa")
        return
    if websocket.app.state.http_session is None:
        websocket.app.state.http_session = _nueva_sesion()
    session = websocket.app.state.http_session
    _proxy_abiertos += 1
    try:
        async with session.ws_connect(url, heartbeat=15, max_msg_size=1024 * 1024) as placa:
            red.visto_esp32()

            async def subir() -> None:  # navegador → placa
                while True:
                    m = await websocket.receive()
                    if m["type"] == "websocket.disconnect":
                        return
                    if m.get("text") is not None:
                        if len(m["text"]) <= PROXY_MAX_TEXT:
                            await placa.send_str(m["text"])
                    elif m.get("bytes") is not None and len(m["bytes"]) <= PROXY_MAX_BINARY:
                        await placa.send_bytes(m["bytes"])

            async def bajar() -> None:  # placa → navegador
                async for msg in placa:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await websocket.send_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await websocket.send_bytes(msg.data)

            tareas = [asyncio.create_task(subir()), asyncio.create_task(bajar())]
            try:
                await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tareas:
                    t.cancel()
                await asyncio.gather(*tareas, return_exceptions=True)
        with contextlib.suppress(Exception):
            await websocket.close(code=1000)
    except (aiohttp.ClientError, OSError, TimeoutError) as e:
        print(f"[estudio] Puente /ws: la placa no responde en {url}: {e!r}")
        with contextlib.suppress(Exception):
            await websocket.close(code=4502, reason="La placa no responde")
        await buscar_placa()  # ¿ha cambiado de IP? (como mucho una búsqueda por minuto)
    finally:
        _proxy_abiertos -= 1


@app.get("/api/esp32-status")
async def esp32_status(check: bool = True):
    """Estado de la conexión (el mismo para los puentes y la web). Con check=1 se
    comprueba además por TCP (1,5 s) que la placa responde, para que el navegador no
    abra el WebSocket a ciegas y llene la consola de errores."""
    out = {**LINK.status(), "esp32_ws_url": esp32_ws_url(), "host": esp32_host(), "ws_path": "/estudio/ws"}
    if check and LINK.state != "online":
        reachable = await _tcp_check()
        out["online"] = reachable
        if reachable and LINK.state == "offline":
            LINK.retry()  # la placa ha vuelto: los puentes no esperan a que acabe la pausa
    return out


@app.post("/api/esp32/retry")
async def esp32_retry():
    LINK.retry()
    return {
        **LINK.status(),
        "online": await _tcp_check(),
        "esp32_ws_url": esp32_ws_url(),
        "host": esp32_host(),
        "ws_path": "/estudio/ws",
    }


@app.get("/")
def estudio_page(request: Request):
    return render(request, "estudio.html", "estudio", "Estudio", esp32_host=esp32_host())


# IMPORTANTE: este mount va SIEMPRE al final del archivo, despues de
# todas las rutas (como /config arriba). Un StaticFiles montado en "/"
# capturaria cualquier ruta declarada despues de el.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
