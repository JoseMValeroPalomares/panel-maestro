"""Rutas de la extensión de Firefox: el alias POST /api/inbox (versiones 2.x ya instaladas) y su comprobación de estado."""
import re
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.items import ItemIn, _clean_body, counts, create
from app.notes_core import PRIORITIES, normalize_item_type
from app.ordering import next_resource_order
from app.vault import do_scrape_and_save, find_video

router = APIRouter()


def _clean_priority(v: str | None, allow_empty: bool = False) -> str | None:
    """Prioridad del Inbox: alta, media o baja; "" (al editar) la quita."""
    if v is None or (v == "" and allow_empty):
        return v
    if v not in PRIORITIES:
        raise ValueError("La prioridad es alta, media o baja")
    return v


class InboxItem(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    item_type: str = Field(default="nota", max_length=20)
    parent_id: int | None = None
    priority: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=60)

    @field_validator("content")
    @classmethod
    def _content(cls, v):
        return _clean_body(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        return _clean_priority(v or None)

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        return (v or "").strip() or None


@router.post("/api/inbox")
def add_inbox_item(item: InboxItem):
    """Alias de POST /api/items para la extensión de Firefox 2.x ya instalada (envía content/item_type)."""
    new_id = create(ItemIn(text=item.content, type="idea" if normalize_item_type(item.item_type) == "nota" else "tarea",
                           parent_id=item.parent_id, priority=item.priority, category=item.category))
    return {"status": "success", "id": new_id}


@router.get("/api/ext/status")
def extension_status():
    """Para la extensión de Firefox: comprueba la conexión y el token, y da los pendientes (mismo contador que el panel)."""
    pending = counts()["pendientes"]
    with get_db() as conn:
        cats = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM inbox WHERE category IS NOT NULL AND category != '' ORDER BY category")]
    return {"ok": True, "pending": pending, "inbox_categories": cats, "api": 2}


# ── YouTube: vídeos vistos de los canales del Baúl ──────────────────────────────────────────────────────────────
# Solo cuentan los canales guardados en el Baúl: de los demás no se guarda nada. «Visto» se anota en yt_vistos
# (para marcar las miniaturas en la página del canal) y en el propio Baúl (resources.watched).
VIDEO_RE = re.compile(r"^[\w-]{11}$")
_CANAL_URL = re.compile(r"youtube\.com/(?:@([^/?#\s]+)|channel/([\w-]+)|(?:c|user)/([^/?#\s]+))", re.IGNORECASE)


def _canal_clave(texto: str) -> str:
    """'@Nombre', '/@nombre', URL de canal o 'UC…' → clave comparable en minúsculas ('@nombre' o 'uc…')."""
    t = unquote((texto or "").strip())
    m = _CANAL_URL.search(t)
    if m:
        return ("@" + m.group(1) if m.group(1) else m.group(2) or "@" + m.group(3)).lower()
    t = t.lstrip("/")
    return t.lower() if t.startswith("@") or t.upper().startswith("UC") else "@" + t.lower()


def _canal_en_baul(conn, clave: str):
    """Recurso del Baúl que es ese canal (o None)."""
    if not clave or clave == "@":
        return None
    for r in conn.execute("SELECT * FROM resources WHERE resource_type='youtube' AND url LIKE '%youtube.com/%'"):
        if _canal_clave(r["url"]) == clave:
            return r
    return None


class VistoIn(BaseModel):
    video_id: str
    channel: str = Field(max_length=300)  # '@handle', URL del canal o 'UC…'
    title: str = Field(default="", max_length=500)

    @field_validator("video_id")
    @classmethod
    def _vid(cls, v):
        if not VIDEO_RE.match(v):
            raise ValueError("Identificador de vídeo no válido")
        return v


@router.post("/api/ext/youtube/visto")
def youtube_visto(data: VistoIn, background_tasks: BackgroundTasks):
    """Marca un vídeo como visto si su canal está en el Baúl; lo añade al Baúl (visto) si no estaba. Idempotente."""
    clave = _canal_clave(data.channel)
    with get_db() as conn:
        canal = _canal_en_baul(conn, clave)
        if not canal:
            return {"tracked": False}
        conn.execute("INSERT OR IGNORE INTO yt_vistos (video_id, channel, title) VALUES (?, ?, ?)",
                     (data.video_id, clave, data.title or None))
        row = find_video(conn, data.video_id)
        if row:
            if not row["watched"]:
                conn.execute("UPDATE resources SET watched=1, watch_later=0 WHERE id=?", (row["id"],))
            created = False
        else:
            url = f"https://www.youtube.com/watch?v={data.video_id}"
            cat = canal["category"] or "General"
            conn.execute("""INSERT INTO resources (url, title, description, category, resource_type, channel, watch_later, watched, sort_order)
                            VALUES (?, ?, '', ?, 'youtube', ?, 0, 1, ?)""",
                         (url, data.title or url, cat, canal["channel"] or canal["title"], next_resource_order(conn, cat)))
            created = True
    if created:  # miniatura, título y canal reales, como al guardarlo a mano
        background_tasks.add_task(do_scrape_and_save, url, cat)
    return {"tracked": True, "created": created}


@router.get("/api/ext/youtube/video")
def youtube_video(id: str):
    """¿Está este vídeo en el Baúl (con cualquier forma de URL) y cómo? La extensión lo usa para clasificar sola."""
    if not VIDEO_RE.match(id):
        raise HTTPException(400, "Identificador de vídeo no válido")
    with get_db() as conn:
        r = find_video(conn, id)
    return {"exists": bool(r), "watched": bool(r and r["watched"]), "watch_later": bool(r and r["watch_later"]), "category": r["category"] if r else None}


@router.get("/api/ext/youtube/canal")
def youtube_canal(channel: str):
    """Vídeos vistos de un canal del Baúl, para marcarlos en su página de YouTube."""
    clave = _canal_clave(channel)
    with get_db() as conn:
        canal = _canal_en_baul(conn, clave)
        if not canal:
            return {"tracked": False, "watched": []}
        ids = {r[0] for r in conn.execute("SELECT video_id FROM yt_vistos WHERE channel=?", (clave,))}
        # lo marcado a mano en el Baúl también cuenta (sus vídeos llevan el nombre del canal)
        nombre = canal["channel"] or canal["title"]
        for r in conn.execute("SELECT url FROM resources WHERE watched=1 AND resource_type='youtube' AND channel=?", (nombre,)):
            m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", r[0])
            if m:
                ids.add(m.group(1))
    return {"tracked": True, "watched": sorted(ids)}
