"""Baúl: enlaces web y de YouTube, con metadatos y miniatura que se obtienen en segundo plano (app/scraper.py)."""
import os
import re
import sqlite3
import threading
import time

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.ordering import next_resource_order
from app.scraper import cache_thumbnail, canonical_youtube_url, fetch_metadata, youtube_video_id
from core import config
from core.logging_config import get_logger

router = APIRouter()
log = get_logger("cerebro")

THUMBS_DIR = os.path.join(str(config.UPLOADS_DIR), "thumbs")


class ResourceIn(BaseModel):
    url: str = Field(max_length=2048)
    category: str = Field(default="General", max_length=120)
    watch_later: bool = False
    watched: bool = False  # lo guarda ya como visto (extensión)

    @field_validator("url")
    @classmethod
    def _url_http(cls, v):
        v = v.strip()
        if not re.match(r"^https?://[^\s/]+", v, re.IGNORECASE):
            raise ValueError("La URL debe empezar por http:// o https://")
        return v


class ResourceUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=120)
    watch_later: bool | None = None


def do_scrape_and_save(url: str, category: str):
    meta = fetch_metadata(url)
    image = (cache_thumbnail(meta["image"], THUMBS_DIR) or meta["image"]) if meta.get("image") else ""
    with get_db() as conn:
        conn.execute('''
            UPDATE resources SET title=?, description=?, image=?, resource_type=?, channel=? WHERE url=?
        ''', (meta['title'], meta['description'], image, meta['resource_type'], meta.get('channel'), url))


def backfill_thumbnails():
    """Pasa a caché local las miniaturas externas de recursos antiguos (una vez por recurso)."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, image FROM resources WHERE image LIKE 'http%'").fetchall()
    done = 0
    for row in rows:
        local = cache_thumbnail(row["image"], THUMBS_DIR)
        if local:  # si falla se conserva la URL original; la interfaz solo pinta imágenes locales
            with get_db() as conn:
                conn.execute("UPDATE resources SET image=? WHERE id=?", (local, row["id"]))
            done += 1
    if rows:
        log.info("Miniaturas cacheadas: %d de %d", done, len(rows))


def backfill_video_metadata():
    """Vídeos de YouTube guardados sin miniatura (los que creaba la extensión al marcarlos vistos): pide sus metadatos."""
    with get_db() as conn:
        rows = conn.execute("SELECT url, category FROM resources WHERE resource_type='youtube' AND url LIKE '%watch?v=%' "
                            "AND (image IS NULL OR image = '')").fetchall()
    for row in rows:
        do_scrape_and_save(row["url"], row["category"])
    if rows:
        log.info("Metadatos de vídeos sin miniatura: %d", len(rows))


_canales_lock = threading.Lock()
_YT_CANAL = re.compile(r"youtube\.com/(@|channel/|c/|user/)")


def pendientes_de_canal() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, url FROM resources WHERE resource_type='youtube' AND (channel IS NULL OR TRIM(channel)='')").fetchall()
                if not _YT_CANAL.search(r["url"])]


def backfill_channels(pausa_s: float = 1.5, reintentos: int = 3, dormir=time.sleep) -> int:
    """Rellena el canal de los vídeos de YouTube que no lo tienen (los antiguos). Despacio (una petición cada `pausa_s`),
    con reintentos de espera creciente y una sola tarea a la vez. Devuelve cuántos se rellenaron."""
    if not _canales_lock.acquire(blocking=False):
        return 0
    hechos = 0
    try:
        for fila in pendientes_de_canal():
            canal = ""
            for intento in range(max(1, reintentos)):
                try:
                    canal = (fetch_metadata(fila["url"]).get("channel") or "").strip()
                except Exception:  # red caída, límite de YouTube…
                    canal = ""
                if canal:
                    break
                dormir(min(30.0, 2.0 ** (intento + 1)))
            if canal:
                with get_db() as conn:
                    conn.execute("UPDATE resources SET channel=? WHERE id=?", (canal, fila["id"]))
                hechos += 1
            dormir(pausa_s)
        if hechos:
            log.info("Canales de YouTube rellenados: %d", hechos)
    finally:
        _canales_lock.release()
    return hechos


@router.post("/api/resources/backfill-channels")
def start_backfill_channels(background_tasks: BackgroundTasks):
    """Lanza en segundo plano el relleno de canales (el Baúl lo pide al abrir «Vistos» si hay vídeos sin canal)."""
    pendientes = len(pendientes_de_canal())
    if pendientes and not _canales_lock.locked():
        background_tasks.add_task(backfill_channels)
    return {"pendientes": pendientes, "en_curso": _canales_lock.locked()}


def find_video(conn, video_id: str):
    """Recurso del Baúl que es ese vídeo de YouTube, guardado con cualquier forma de URL (o None)."""
    for r in conn.execute("SELECT id, url, watched, watch_later, category FROM resources WHERE url LIKE '%youtu%'"):
        if youtube_video_id(r["url"]) == video_id:
            return r
    return None


@router.post("/api/resources")
def add_resource(resource: ResourceIn, background_tasks: BackgroundTasks):
    vid = youtube_video_id(resource.url)
    if vid:  # un vídeo se identifica por su ID, no por la URL: con lista, tiempo, shorts o youtu.be es el mismo
        resource.url = canonical_youtube_url(vid)
        with get_db() as conn:
            previo = find_video(conn, vid)
            if previo:
                if resource.watched and not previo["watched"]:  # «visto» sobre un vídeo ya guardado: lo marca
                    conn.execute("UPDATE resources SET watched=1, watch_later=0 WHERE id=?", (previo["id"],))
                    return {"status": "updated", "message": "Marcado como visto"}
                return JSONResponse(status_code=409, content={"error": "URL ya existe"})
    with get_db() as conn:
        try:
            conn.execute('''
                INSERT INTO resources (url, title, description, category, watch_later, watched, sort_order)
                VALUES (?, ?, '', ?, ?, ?, ?)
            ''', (resource.url, resource.url, resource.category, int(resource.watch_later and not resource.watched), int(resource.watched),
                  next_resource_order(conn, resource.category)))
            conn.commit()
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "URL ya existe"})
    background_tasks.add_task(do_scrape_and_save, resource.url, resource.category)
    return {"status": "pending", "message": "Recurso añadido, cargando metadatos..."}


@router.get("/api/resources")
def get_resources(category: str = None):
    with get_db() as conn:
        if category:
            rows = conn.execute("SELECT * FROM resources WHERE category=? ORDER BY sort_order DESC, added_at DESC", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM resources ORDER BY sort_order DESC, added_at DESC").fetchall()
    return {"resources": [dict(r) for r in rows]}


@router.get("/api/resources/categories")
def get_resource_categories():
    with get_db() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM resources ORDER BY category").fetchall()
    return {"categories": [r['category'] for r in rows]}


@router.patch("/api/resources/{resource_id}")
def update_resource(resource_id: int, data: ResourceUpdate):
    with get_db() as conn:
        cursor = conn.cursor()
        if data.title is not None:
            cursor.execute("UPDATE resources SET title=? WHERE id=?", (data.title, resource_id))
        if data.description is not None:
            cursor.execute("UPDATE resources SET description=? WHERE id=?", (data.description, resource_id))
        if data.category is not None:
            cursor.execute("UPDATE resources SET category=? WHERE id=?", (data.category, resource_id))
        if data.watch_later is not None:
            cursor.execute("UPDATE resources SET watch_later=? WHERE id=?", (int(data.watch_later), resource_id))
        conn.commit()
    return {"status": "success"}


@router.patch("/api/resources/{resource_id}/watch-later")
def toggle_watch_later(resource_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT watch_later FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Recurso no encontrado"})
        new_value = 0 if row['watch_later'] else 1
        conn.execute("UPDATE resources SET watch_later=? WHERE id=?", (new_value, resource_id))
        conn.commit()
    return {"status": "success", "watch_later": bool(new_value)}


@router.patch("/api/resources/{resource_id}/watched")
def toggle_watched(resource_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT watched FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Recurso no encontrado"})
        new_value = 0 if row['watched'] else 1
        if new_value:
            conn.execute("UPDATE resources SET watched=?, watch_later=0 WHERE id=?", (new_value, resource_id))
        else:
            conn.execute("UPDATE resources SET watched=?, watch_later=1 WHERE id=?", (new_value, resource_id))
        conn.commit()
    return {"status": "success", "watched": bool(new_value)}


@router.delete("/api/resources/{resource_id}")
def delete_resource(resource_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))
        conn.commit()
    return {"status": "success"}
