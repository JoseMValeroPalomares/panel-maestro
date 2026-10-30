"""Baúl: enlaces web y de YouTube, con metadatos y miniatura que se obtienen en segundo plano (app/scraper.py)."""
import os
import re

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.ordering import next_resource_order
from app.scraper import cache_thumbnail, fetch_metadata
from core import config
from core.logging_config import get_logger

router = APIRouter()
log = get_logger("cerebro")

THUMBS_DIR = os.path.join(str(config.UPLOADS_DIR), "thumbs")


class ResourceIn(BaseModel):
    url: str = Field(max_length=2048)
    category: str = Field(default="General", max_length=120)
    watch_later: bool = False

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


@router.post("/api/resources")
async def add_resource(resource: ResourceIn, background_tasks: BackgroundTasks):
    with get_db() as conn:
        try:
            conn.execute('''
                INSERT INTO resources (url, title, description, category, watch_later, sort_order)
                VALUES (?, ?, '', ?, ?, ?)
            ''', (resource.url, resource.url, resource.category, int(resource.watch_later),
                  next_resource_order(conn, resource.category)))
            conn.commit()
        except Exception:
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
