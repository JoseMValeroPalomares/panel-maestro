"""Baúl: enlaces web y de YouTube, con metadatos y miniatura que se obtienen en segundo plano (app/scraper.py)."""

import json
import os
import re
import sqlite3
import threading
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app import contextos, prefs
from app.database import get_db
from app.ordering import next_resource_order
from app.scraper import (
    cache_thumbnail,
    canonical_youtube_url,
    fetch_metadata,
    youtube_channel_info,
    youtube_video_id,
)
from core import config, undo
from core.files import atomic_write
from core.logging_config import get_logger

router = APIRouter()
log = get_logger("cerebro")

THUMBS_DIR = os.path.join(str(config.UPLOADS_DIR), "thumbs")


class ResourceIn(BaseModel):
    url: str = Field(max_length=2048)
    category: str = Field(default="General", max_length=120)
    watch_later: bool = False
    watched: bool = False  # lo guarda ya como visto (extensión)
    # Contexto (app/contextos.py): un recurso puede ser de una asignatura o de un proyecto
    contexto: str | None = Field(default=None, max_length=12)
    asignatura_id: int | None = Field(default=None, ge=0)
    proyecto_id: int | None = Field(default=None, ge=0)

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
    contexto: str | None = Field(default=None, max_length=12)
    asignatura_id: int | None = Field(default=None, ge=0)  # 0 la quita
    proyecto_id: int | None = Field(default=None, ge=0)  # 0 lo quita


def do_scrape_and_save(url: str, category: str):
    """Rellena título, descripción e imagen de un recurso recién añadido (tarea de fondo). Pase lo que pase deja un
    título distinto de la URL: es lo que la interfaz usa para saber que ya no está «cargando»."""
    try:
        meta = fetch_metadata(url)
    except Exception as e:  # noqa: BLE001 — una web rara no puede dejar el recurso cargando para siempre
        log.warning("Baúl: no se pudieron leer los metadatos de %s: %s", url, e)
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", url))
        meta = {"title": host or "Sin título", "description": "", "image": "", "resource_type": "web"}
        if youtube_video_id(url):
            meta["resource_type"] = "youtube"
    image = (cache_thumbnail(meta["image"], THUMBS_DIR) or meta["image"]) if meta.get("image") else ""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE resources SET title=?, description=?, image=?, resource_type=?, channel=? WHERE url=?
        """,
            (meta["title"], meta["description"], image, meta["resource_type"], meta.get("channel"), url),
        )


THUMB_RETRY_S = 7 * 86400  # una miniatura que falla no se vuelve a pedir hasta pasada una semana (V-3)
THUMB_REPAIR_S = 600  # «reparar» la miniatura de un recurso a petición del navegador: como mucho cada 10 min
_thumb_repairs: dict[int, float] = {}
_thumb_repair_lock = threading.Lock()


def _thumb_file(image: str) -> str:
    """Ruta en disco de una miniatura local («» si `image` no lo es)."""
    m = re.fullmatch(r"/static/uploads/thumbs/([0-9a-f]{32}\.webp)", image or "")
    return os.path.join(THUMBS_DIR, m.group(1)) if m else ""


def repair_thumbnail(resource_id: int, now: float | None = None) -> dict:
    """La imagen de un recurso no carga en el navegador (el archivo ya no está, nunca se pudo bajar…): se vuelve a
    obtener de su origen y se guarda en local. {"image": ruta local o "", "motivo"}."""
    now = time.time() if now is None else now
    with get_db() as conn:
        row = conn.execute("SELECT id, url, image, resource_type FROM resources WHERE id=?", (resource_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Recurso no encontrado")
    local = _thumb_file(row["image"])
    if local and os.path.isfile(local) and os.path.getsize(local) > 0:
        return {"image": row["image"], "motivo": "ya-estaba"}  # el archivo está bien: fue un fallo de red del navegador
    with _thumb_repair_lock:
        if now - _thumb_repairs.get(resource_id, 0.0) < THUMB_REPAIR_S:
            return {"image": "", "motivo": "espera"}
        _thumb_repairs[resource_id] = now
        if len(_thumb_repairs) > 500:  # no crece sin fin
            for k in sorted(_thumb_repairs, key=_thumb_repairs.get)[:250]:  # type: ignore[arg-type]
                _thumb_repairs.pop(k, None)
    candidatas = []
    if (row["image"] or "").startswith("http"):
        candidatas.append(row["image"])
    vid = youtube_video_id(row["url"])
    try:
        if vid:
            candidatas.append(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
        elif row["resource_type"] == "youtube":
            candidatas.append(youtube_channel_info(row["url"]).get("image", ""))
        else:
            candidatas.append(fetch_metadata(row["url"]).get("image", ""))
    except Exception as e:  # noqa: BLE001 — sin red o web caída: se queda con el respaldo
        log.info("Baúl: no se pudo volver a buscar la imagen de %s: %s", row["url"], e)
    for remota in dict.fromkeys(c for c in candidatas if c):
        nueva = cache_thumbnail(remota, THUMBS_DIR)
        if nueva:
            with get_db() as conn:
                conn.execute("UPDATE resources SET image=? WHERE id=?", (nueva, resource_id))
            log.info("Baúl: miniatura del recurso %d recuperada", resource_id)
            return {"image": nueva, "motivo": "recuperada"}
    return {"image": "", "motivo": "sin-imagen"}


def _thumb_failures_file():
    """Estado de las miniaturas que fallan: {url: {"intentos": n, "fecha": epoch}}. Si se pierde, solo se reintentan."""
    return config.DATA_DIR / "miniaturas_fallidas.json"


def _load_thumb_failures() -> dict:
    try:
        data = json.loads(_thumb_failures_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def backfill_thumbnails(now: float | None = None):
    """Pasa a caché local las miniaturas externas de recursos antiguos (una vez por recurso). Las que fallan se
    recuerdan (intentos y fecha) y no se reintentan hasta pasados 7 días: antes se pedían en cada arranque."""
    now = time.time() if now is None else now
    with get_db() as conn:
        rows = conn.execute("SELECT id, image FROM resources WHERE image LIKE 'http%'").fetchall()
    old = _load_thumb_failures()
    vivas = {row["image"] for row in rows}
    failures = {u: f for u, f in old.items() if u in vivas}  # olvida las de recursos borrados o ya cacheados
    done = tried = 0
    for row in rows:
        prev = failures.get(row["image"])
        if prev and now - float(prev.get("fecha") or 0) < THUMB_RETRY_S:
            continue
        tried += 1
        local = cache_thumbnail(row["image"], THUMBS_DIR)
        if local:  # si falla se conserva la URL original; la interfaz solo pinta imágenes locales
            with get_db() as conn:
                conn.execute("UPDATE resources SET image=? WHERE id=?", (local, row["id"]))
            failures.pop(row["image"], None)
            done += 1
        else:
            failures[row["image"]] = {"intentos": int((prev or {}).get("intentos") or 0) + 1, "fecha": now}
    if failures != old:
        path = _thumb_failures_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(failures, indent=2))
    if tried:
        log.info("Miniaturas cacheadas: %d de %d (%d en espera de reintento)", done, tried, len(rows) - tried)


def backfill_video_metadata():
    """Vídeos de YouTube guardados sin miniatura (los que creaba la extensión al marcarlos vistos): pide sus metadatos."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url, category FROM resources WHERE resource_type='youtube' AND url LIKE '%watch?v=%' "
            "AND (image IS NULL OR image = '')"
        ).fetchall()
    for row in rows:
        do_scrape_and_save(row["url"], row["category"])
    if rows:
        log.info("Metadatos de vídeos sin miniatura: %d", len(rows))


_canales_lock = threading.Lock()
_YT_CANAL = re.compile(r"youtube\.com/(@|channel/|c/|user/)")


def pendientes_de_canal() -> list[dict]:
    with get_db() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, url FROM resources WHERE resource_type='youtube' AND (channel IS NULL OR TRIM(channel)='')"
            ).fetchall()
            if not _YT_CANAL.search(r["url"])
        ]


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


@router.post("/api/resources/{resource_id}/miniatura")
def repair_resource_thumbnail(resource_id: int):
    """Lo llama el Baúl cuando una imagen no carga (una vez por recurso y visita)."""
    return repair_thumbnail(resource_id)


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
        ctx, asig, proy = contextos.resolve(conn, resource.contexto, resource.asignatura_id, resource.proyecto_id)
        try:
            conn.execute(
                """
                INSERT INTO resources (url, title, description, category, watch_later, watched, sort_order, contexto, asignatura_id, proyecto_id)
                VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    resource.url,
                    resource.url,
                    resource.category,
                    int(resource.watch_later and not resource.watched),
                    int(resource.watched),
                    next_resource_order(conn, resource.category),
                    ctx,
                    asig,
                    proy,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "URL ya existe"})
    background_tasks.add_task(do_scrape_and_save, resource.url, resource.category)
    return {"status": "pending", "message": "Recurso añadido, cargando metadatos..."}


@router.get("/api/resources")
def get_resources(category: str = None):
    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM resources WHERE category=? ORDER BY sort_order DESC, added_at DESC", (category,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM resources ORDER BY sort_order DESC, added_at DESC").fetchall()
        conts = contextos.containers(conn)
    return {"resources": [{**dict(r), **(contextos.label(r, conts) if "contexto" in r.keys() else {})} for r in rows]}


CATEGORY_ORDER_PREF = "baul-categorias"  # orden propio de las categorías (lo escribe el Baúl con Prefs, vault.js)


def sort_categories(cats) -> list[str]:
    """Primero las del orden propio, en ese orden; las que no estén en él, detrás y alfabéticas."""
    saved = prefs.get(CATEGORY_ORDER_PREF, [])
    pos = {c: i for i, c in enumerate(saved if isinstance(saved, list) else []) if isinstance(c, str)}
    return sorted(set(cats), key=lambda c: (pos.get(c, len(pos)), c.casefold()))


@router.get("/api/resources/categories")
def get_resource_categories():
    with get_db() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM resources").fetchall()
    return {"categories": sort_categories(r["category"] or "General" for r in rows)}


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
        if any(v is not None for v in (data.contexto, data.asignatura_id, data.proyecto_id)):
            r = conn.execute(
                "SELECT contexto, asignatura_id, proyecto_id FROM resources WHERE id=?", (resource_id,)
            ).fetchone()
            if r is None:
                raise HTTPException(status_code=404, detail="Recurso no encontrado")
            ctx, asig, proy = contextos.resolve(
                conn,
                data.contexto,
                data.asignatura_id,
                data.proyecto_id,
                (r["contexto"] or "puntual", r["asignatura_id"], r["proyecto_id"]),
            )
            cursor.execute(
                "UPDATE resources SET contexto=?, asignatura_id=?, proyecto_id=? WHERE id=?",
                (ctx, asig, proy, resource_id),
            )
        conn.commit()
    return {"status": "success"}


@router.patch("/api/resources/{resource_id}/watch-later")
def toggle_watch_later(resource_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT watch_later FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Recurso no encontrado"})
        new_value = 0 if row["watch_later"] else 1
        conn.execute("UPDATE resources SET watch_later=? WHERE id=?", (new_value, resource_id))
        conn.commit()
    return {"status": "success", "watch_later": bool(new_value)}


@router.patch("/api/resources/{resource_id}/watched")
def toggle_watched(resource_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT watched FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Recurso no encontrado"})
        new_value = 0 if row["watched"] else 1
        if new_value:
            conn.execute("UPDATE resources SET watched=?, watch_later=0 WHERE id=?", (new_value, resource_id))
        else:
            conn.execute("UPDATE resources SET watched=?, watch_later=1 WHERE id=?", (new_value, resource_id))
        conn.commit()
    return {"status": "success", "watched": bool(new_value)}


@router.delete("/api/resources/{resource_id}")
def delete_resource(resource_id: int):
    """Va a la papelera (30 días): «Deshacer» lo devuelve con su id, su orden y lo visto."""
    with get_db() as conn:
        rows = undo.select(conn, "resources", "id=?", (resource_id,))
        if not rows:
            return {"status": "success", "undo_token": None}
        token = undo.save_rows(conn, "rows.recurso", [("resources", rows)], title=rows[0]["title"] or rows[0]["url"])
        conn.execute("DELETE FROM resources WHERE id=?", (resource_id,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}
