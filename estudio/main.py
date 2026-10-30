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
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from colorthief import ColorThief

from core.templating import render

from .esp32_link import LINK, keep_connected
from .calendar_sync import CalendarSyncBridge
from .note_review import NoteReviewBridge


# =====================================================================
# CONFIGURACION
# =====================================================================
from core import config

ESP32_HOST = config.ESP32_HOST
ESP32_WS_URL = f"ws://{ESP32_HOST}/ws" if ESP32_HOST else ""  # sin placa, vacío: nadie intenta conectar

POLL_INTERVAL_SEC = 1.0

IMG_W = 120
IMG_H = 120  # carátula cuadrada; el firmware acepta hasta 160x160 (160x120 es el fondo)

STATIC_DIR = Path(__file__).parent / "static"

# =====================================================================
# UTILIDADES: playerctl / MPRIS
# =====================================================================
FIELD_SEP = "\x1f"


def run_playerctl(args, timeout=2):
    try:
        result = subprocess.run(
            ["playerctl"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_metadata():
    fmt = FIELD_SEP.join([
        "{{status}}", "{{mpris:trackid}}", "{{title}}",
        "{{artist}}", "{{mpris:length}}", "{{mpris:artUrl}}"
    ])
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
            path = art_url[len("file://"):]
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


def build_image_frame_and_accent(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        frame = build_cover_frame(img)

        ct = ColorThief(io.BytesIO(image_bytes))
        accent = rgb_to_565(*ct.get_color(quality=3))

        return frame, accent
    except Exception as e:
        print(f"[spotify-bridge] Error generando imagen de fondo: {e}")
        return None, None


# =====================================================================
# PUENTE SPOTIFY <-> ESP32 (cliente websocket hacia el ESP32)
# =====================================================================
class SpotifyBridge:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.last_trackid = None
        self.cached_accent = None
        self.track_start_monotonic = None
        self.last_sent_status = None

    async def run_forever(self):
        # Espera creciente, pausa y «Reintentar» comunes a todos los puentes (esp32_link.py)
        await keep_connected(self.session, ESP32_WS_URL, self._serve, heartbeat=15, max_msg_size=0)

    async def _serve(self, ws):
        self.last_trackid = None  # tras reconectar, la carátula se vuelve a mandar
        self.last_sent_status = None
        await asyncio.gather(
            self._sender_loop(ws),
            self._receiver_loop(ws),
        )

    async def _sender_loop(self, ws: aiohttp.ClientWebSocketResponse):
        while not ws.closed:
            payload = await self._build_payload(ws)
            if payload is not None:
                await ws.send_str(json.dumps(payload))
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

    async def _build_payload(self, ws: aiohttp.ClientWebSocketResponse):
        # playerctl y la carátula, en un hilo: en el bucle pararían todo el panel en cada sondeo (hasta 2 s si cuelga)
        meta = await asyncio.to_thread(get_metadata)

        if meta is None:
            if self.last_sent_status == "stopped":
                return None
            self.last_sent_status = "stopped"
            self.last_trackid = None
            self.cached_accent = None
            return {"type": "nowplaying", "status": "stopped"}

        status = meta["status"]
        trackid = meta["trackid"]

        if trackid != self.last_trackid:
            self.last_trackid = trackid
            self.track_start_monotonic = time.monotonic()
            art_bytes = await fetch_art_bytes(self.session, meta["art_url"])
            if art_bytes:
                frame, accent = await asyncio.to_thread(build_image_frame_and_accent, art_bytes)
                self.cached_accent = accent
                if frame is not None:
                    await ws.send_bytes(frame)
            else:
                self.cached_accent = None

        pos = await asyncio.to_thread(get_position_sec)
        if pos is None or (pos == 0 and status == "playing" and
                            time.monotonic() - (self.track_start_monotonic or 0) > 3):
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
        }
        if self.cached_accent is not None:
            payload["accent_color"] = self.cached_accent

        return payload


# =====================================================================
# CICLO DE VIDA + APP FASTAPI
# =====================================================================
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    if config.DISABLE_BRIDGES:
        print("[estudio] Puentes desactivados (PANEL_DISABLE_BRIDGES)")
        LINK.state = "disabled"
        yield
        return
    print("[estudio] Iniciando puentes Spotify / iCloud / Repaso de notas...")
    if not ESP32_HOST:
        LINK.state = "disabled"  # sin placa solo queda la sincronía con iCloud
    # Conectar a una placa apagada falla en segundos, no a los 5 min por defecto
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=8, sock_connect=5))
    app.state.http_session = session

    # Calendario del Panel ↔ iCloud ↔ ESP32 (antes solo iCloud ↔ ESP32)
    tasks = [asyncio.create_task(CalendarSyncBridge(session, ESP32_WS_URL).run_forever())]
    if ESP32_HOST:
        tasks.append(asyncio.create_task(SpotifyBridge(session).run_forever()))
        tasks.append(asyncio.create_task(NoteReviewBridge(session, ESP32_WS_URL).run_forever()))

    yield
    print("[estudio] Apagando puentes...")
    for task in tasks:
        task.cancel()
    await app.state.http_session.close()

app = FastAPI(title="Panel ESP32 - Estudio", lifespan=lifespan)


@app.get("/config")
async def handle_config():
    return JSONResponse({"esp32_ws_url": ESP32_WS_URL, "esp32_host": ESP32_HOST})


async def _tcp_check() -> bool:
    if not ESP32_HOST:
        return False
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ESP32_HOST, 80), timeout=1.5)
        writer.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


@app.get("/api/esp32-status")
async def esp32_status(check: bool = True):
    """Estado de la conexión (el mismo para los puentes y la web). Con check=1 se
    comprueba además por TCP (1,5 s) que la placa responde, para que el navegador no
    abra el WebSocket a ciegas y llene la consola de errores."""
    out = {**LINK.status(), "esp32_ws_url": ESP32_WS_URL, "host": ESP32_HOST}
    if check and LINK.state != "online":
        reachable = await _tcp_check()
        out["online"] = reachable
        if reachable and LINK.state == "offline":
            LINK.retry()  # la placa ha vuelto: los puentes no esperan a que acabe la pausa
    return out


@app.post("/api/esp32/retry")
async def esp32_retry():
    LINK.retry()
    return {**LINK.status(), "online": await _tcp_check(), "esp32_ws_url": ESP32_WS_URL}


@app.get("/")
def estudio_page(request: Request):
    return render(request, "estudio.html", "estudio", "Estudio", esp32_host=ESP32_HOST)


# IMPORTANTE: este mount va SIEMPRE al final del archivo, despues de
# todas las rutas (como /config arriba). Un StaticFiles montado en "/"
# capturaria cualquier ruta declarada despues de el.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
