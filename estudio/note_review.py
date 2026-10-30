# =====================================================================
# Archivo nuevo: estudio/note_review.py
#
# Puente de repaso de notas al azar. Mismo patrón que SpotifyBridge /
# IcloudSyncBridge (abre su propia conexión WebSocket como CLIENTE
# hacia el ESP32). Cada 15 minutos elige una nota "consolidado" al azar
# puro y le manda un fragmento al ESP32. Cuando el ESP32 avisa que
# pulsaste OK, abre esa nota en el navegador de ESTE MISMO PC.
# =====================================================================

import json
import random
import re
import asyncio
import webbrowser
import aiohttp

REVIEW_INTERVAL_SEC = 15*60  # una nota nueva cada 15 minutos
SNIPPET_MAX_CHARS = 220

# IP real de este PC (donde corre uvicorn), puerto de FastAPI.
from core import config

from .esp32_link import keep_connected

SERVER_BASE_URL = config.SERVER_BASE_URL


class NoteReviewBridge:
    def __init__(self, session: aiohttp.ClientSession, esp32_ws_url: str):
        self.session = session
        self.esp32_ws_url = esp32_ws_url
        self._last_note_id = None

    async def run_forever(self):
        # Reintentos con espera creciente y pausa comunes a todos los puentes (esp32_link.py)
        await keep_connected(self.session, self.esp32_ws_url, self._serve, heartbeat=15)

    async def _serve(self, ws):
        await asyncio.gather(
            self._sender_loop(ws),
            self._receiver_loop(ws),
        )

    async def _sender_loop(self, ws: aiohttp.ClientWebSocketResponse):
        while not ws.closed:
            snippet = _pick_random_consolidated_snippet()
            if snippet is not None:
                self._last_note_id = snippet["id"]
                await ws.send_str(_build_review_payload(snippet))
                print(f"[note-review] Enviada nota #{snippet['id']}: {snippet['title']}")
            else:
                print("[note-review] No hay notas consolidadas con contenido todavía")
            await asyncio.sleep(REVIEW_INTERVAL_SEC)

    async def _receiver_loop(self, ws: aiohttp.ClientWebSocketResponse):
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            kind = data.get("type")
            if kind == "open_note_request":
                note_id = data.get("note_id", self._last_note_id)
                if note_id is not None:
                    self._open_note_in_browser(note_id)
            # Pantalla «Notas» del ESP32: pide la lista y, al abrir una, su texto
            elif kind == "notes_list_request":
                await ws.send_str(json.dumps({"type": "notes_list", "notes": list_notes_for_esp32()}, ensure_ascii=False))
            elif kind == "note_request":
                content = note_content_for_esp32(str(data.get("note_id", "")))
                if content is not None:
                    await ws.send_str(json.dumps(content, ensure_ascii=False))

    def _open_note_in_browser(self, note_id):
        url = f"{SERVER_BASE_URL}/?note={note_id}"
        try:
            opened = webbrowser.open(url, new=2)
            if opened:
                print(f"[note-review] Abriendo nota #{note_id} en el navegador")
            else:
                print(f"[note-review] webbrowser.open() devolvió False para la nota #{note_id}")
        except Exception as e:
            print(f"[note-review] No se pudo abrir el navegador: {e}")


def _pick_random_consolidated_snippet():
    from app.database import get_db

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, category, content FROM notes WHERE status='consolidado' AND COALESCE(encrypted, 0) = 0"
        ).fetchall()

    if not rows:
        return None

    note = random.choice(rows)  # nota al azar puro, misma probabilidad para todas
    content = note["content"] or ""

    paragraphs = [p for p in (clean_snippet(b) for b in _candidate_blocks(content)) if p]
    if not paragraphs:
        return None
    # Mejor un párrafo con algo de sustancia que una línea suelta de dos palabras
    paragraphs = [p for p in paragraphs if len(p) >= 20] or paragraphs

    snippet = truncate_snippet(random.choice(paragraphs))

    return {
        "id": note["id"],
        "title": note["title"] or "(sin título)",
        "category": note["category"] or "General",
        "snippet": snippet,
    }


# El ESP32 guarda el fragmento en un búfer de 480 bytes (UTF-8, con el \0).
SNIPPET_MAX_BYTES = 470

_FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
_MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.S)

# Lo que dibuja la fuente del ESP32 (esp32_deskclock/tools/make_fonts.py): ASCII, Latin-1 y
# unos pocos signos. Lo demás (emojis...) saldría como huecos: se cambia o se quita.
_FONT_CHARS = set(map(chr, range(0x20, 0x7F))) | set(map(chr, range(0xA0, 0x100))) | set("–—‘’“”•…€←→↑↓›✓")
_CHAR_SUBST = {"✅": "✓", "✔": "✓", "☑": "✓", "⇒": "→", "−": "-"}


def _candidate_blocks(content: str) -> list[str]:
    """Párrafos de la nota sin frontmatter, bloques de código, títulos ni tablas."""
    content = _FRONTMATTER_RE.sub("", content.replace("\r\n", "\n"))
    content = _FENCE_RE.sub("\n", content)
    content = _MATH_BLOCK_RE.sub("\n", content)
    blocks = []
    for block in re.split(r"\n\s*\n", content):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        lines = [l for l in lines if not re.match(r"\s*(#{1,6}\s|\||(-{3,}|\*{3,}|_{3,})\s*$)", l)]
        if lines:
            blocks.append("\n".join(lines))
    return blocks


def clean_snippet(text: str) -> str:
    """Quita la sintaxis Markdown y deja texto plano en una sola línea."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                      # imágenes
    text = re.sub(r"!\[\[[^\]]*\]\]", "", text)                            # incrustados ![[...]]
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)              # [[nota|alias]]
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)                         # [[nota]]
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)                     # [texto](url)
    text = re.sub(r"<[^>\n]+>", "", text)                                   # HTML y <url>
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)                        # citas
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?", "", text, flags=re.M)  # listas y casillas
    text = re.sub(r"(\*\*|__|~~|==)(.+?)\1", r"\2", text)                   # negrita, tachado, resaltado
    text = re.sub(r"(?<![\w*])[*_](\S(?:.*?\S)?)[*_](?![\w*])", r"\1", text)  # cursiva (no toca snake_case)
    text = re.sub(r"`([^`]*)`", r"\1", text)                                # código en línea
    text = re.sub(r"(?<!\S)#(?=[\w/-])", "", text)                          # #etiquetas
    text = "".join(c if c in _FONT_CHARS else _CHAR_SUBST.get(c, " ") for c in text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if re.search(r"[^\W\d_]", text) else ""  # sin ninguna letra no sirve de repaso


def truncate_snippet(text: str) -> str:
    if len(text) > SNIPPET_MAX_CHARS:
        text = text[:SNIPPET_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    while len(text.encode()) > SNIPPET_MAX_BYTES:
        text = text[:-2] + "…"
    return text


# Pantalla «Notas» del ESP32: nada cifrado (bóveda) ni índices
NOTES_LIST_MAX = 160          # notes::MAX_NOTES en el firmware
NOTE_TEXT_MAX_BYTES = 5800    # notes::MAX_TEXT = 6000


def _fit_bytes(text: str, max_bytes: int) -> str:
    """Recorta a max_bytes de UTF-8 sin partir caracteres."""
    raw = text.encode()
    return text if len(raw) <= max_bytes else raw[:max_bytes].decode(errors="ignore")


def _clean_category(category) -> str:
    return re.sub(r"\s*-\s*$", "", category or "").strip() or "General"


def list_notes_for_esp32() -> list[dict]:
    from app.database import get_db

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, category FROM notes "
            "WHERE COALESCE(encrypted, 0) = 0 AND COALESCE(status, '') != 'indice'"
        ).fetchall()
    notes = [{"id": r["id"], "title": _fit_bytes(r["title"] or "(sin título)", 70),
              "category": _fit_bytes(_clean_category(r["category"]), 46)} for r in rows]
    notes.sort(key=lambda n: (n["category"].casefold(), n["title"].casefold()))
    return notes[:NOTES_LIST_MAX]


def note_content_for_esp32(note_id: str):
    from app.database import get_db

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, title, category, content FROM notes WHERE id = ? AND COALESCE(encrypted, 0) = 0",
            (note_id,),
        ).fetchone()
    if row is None:
        return None
    paragraphs = [p for p in (clean_snippet(b) for b in _candidate_blocks(row["content"] or "")) if p]
    text = "\n\n".join(paragraphs)
    if len(text.encode()) > NOTE_TEXT_MAX_BYTES:
        text = _fit_bytes(text, NOTE_TEXT_MAX_BYTES - 3).rstrip() + "…"
    return {
        "type": "note_content",
        "note_id": row["id"],
        "title": row["title"] or "(sin título)",
        "category": _clean_category(row["category"]),
        "text": text,
    }


def _build_review_payload(snippet: dict) -> str:
    return json.dumps({
        "type": "review_note",
        "note_id": snippet["id"],
        "title": snippet["title"],
        "category": snippet["category"],
        "snippet": snippet["snippet"],
    })
