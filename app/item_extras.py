"""
Comentarios y adjuntos de una tarea o idea (tablas item_comentarios e item_adjuntos, migración 27).

  - Van por `item_id` sin clave foránea en cascada: al borrar la tarea se quedan como huérfanos y, si se restaura
    desde la papelera (vuelve con su mismo id), reaparecen solos. La purga diaria (`purge_orphans`, desde
    trash.purge_expired) marca los huérfanos y quita los de más de 31 días.
  - Los archivos viven en data/adjuntos/<item>/<uuid>.<ext> (nunca con el nombre que manda el cliente) y entran en
    las copias (backup.TREES). Se descargan siempre como adjunto, salvo imágenes de mapa de bits y PDF, que se ven
    en el navegador; nada de HTML ni SVG en línea (sería ejecutar lo subido en el origen del panel).
  - Borrar un comentario o un adjunto va a la papelera (rows.comentario / rows.adjunto); el archivo se queda en disco
    mientras la papelera lo nombre y la purga lo quita después.
"""

import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.database import get_db
from core import config, undo
from core.logging_config import get_logger

log = get_logger("adjuntos")
router = APIRouter(prefix="/api/items")

MAX_BYTES = 25 * 1024 * 1024
MAX_POR_TAREA = 40
MAX_COMENTARIO = 10_000
ORPHAN_TTL_S = undo.TTL_S + 86400
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}
EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")


def adjuntos_dir() -> Path:
    return Path(config.DATA_DIR) / "adjuntos"


class ComentarioIn(BaseModel):
    texto: str = Field(min_length=1, max_length=MAX_COMENTARIO)


def _item(conn, item_id: int):
    row = conn.execute("SELECT id, content FROM inbox WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return row


def _com_out(r) -> dict:
    return {
        "id": r["id"],
        "item_id": r["item_id"],
        "texto": r["texto"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _adj_out(r) -> dict:
    return {
        "id": r["id"],
        "item_id": r["item_id"],
        "nombre": r["nombre"],
        "mime": r["mime"],
        "bytes": r["bytes"],
        "created_at": r["created_at"],
        "imagen": (r["mime"] or "").startswith("image/") and r["mime"] in INLINE,
        "url": f"/api/items/{r['item_id']}/adjuntos/{r['id']}",
    }


def contar(conn, item_ids: list[int]) -> dict[int, dict]:
    """{item_id: {comentarios, adjuntos}} para pintar los contadores de las tarjetas."""
    if not item_ids:
        return {}
    out: dict[int, dict] = {}
    marks = ",".join("?" * len(item_ids))
    for key, table in (("comentarios", "item_comentarios"), ("adjuntos", "item_adjuntos")):
        for r in conn.execute(
            f"SELECT item_id, COUNT(*) n FROM {table} WHERE item_id IN ({marks}) GROUP BY item_id", item_ids
        ):
            out.setdefault(r["item_id"], {"comentarios": 0, "adjuntos": 0})[key] = r["n"]
    return out


# ─────────────────────────────────────────────
# Comentarios
# ─────────────────────────────────────────────


@router.get("/{item_id}/extras")
def api_extras(item_id: int):
    with get_db() as conn:
        _item(conn, item_id)
        coms = conn.execute(
            "SELECT * FROM item_comentarios WHERE item_id=? ORDER BY created_at, id", (item_id,)
        ).fetchall()
        adjs = conn.execute(
            "SELECT * FROM item_adjuntos WHERE item_id=? ORDER BY created_at, id", (item_id,)
        ).fetchall()
    return {"comentarios": [_com_out(r) for r in coms], "adjuntos": [_adj_out(r) for r in adjs]}


@router.post("/{item_id}/comentarios")
def api_comentar(item_id: int, data: ComentarioIn):
    texto = data.texto.strip()
    if not texto:
        raise HTTPException(status_code=422, detail="El comentario está vacío")
    with get_db() as conn:
        _item(conn, item_id)
        cid = conn.execute(
            "INSERT INTO item_comentarios (item_id, texto, created_at) VALUES (?, ?, ?)", (item_id, texto, time.time())
        ).lastrowid
        return _com_out(conn.execute("SELECT * FROM item_comentarios WHERE id=?", (cid,)).fetchone())


def _comentario(conn, item_id: int, cid: int):
    row = conn.execute("SELECT * FROM item_comentarios WHERE id=? AND item_id=?", (cid, item_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    return row


@router.patch("/{item_id}/comentarios/{cid}")
def api_editar_comentario(item_id: int, cid: int, data: ComentarioIn):
    texto = data.texto.strip()
    if not texto:
        raise HTTPException(status_code=422, detail="El comentario está vacío")
    with get_db() as conn:
        _comentario(conn, item_id, cid)
        conn.execute("UPDATE item_comentarios SET texto=?, updated_at=? WHERE id=?", (texto, time.time(), cid))
        return _com_out(conn.execute("SELECT * FROM item_comentarios WHERE id=?", (cid,)).fetchone())


@router.delete("/{item_id}/comentarios/{cid}")
def api_borrar_comentario(item_id: int, cid: int):
    with get_db() as conn:
        row = _comentario(conn, item_id, cid)
        token = undo.save_rows(
            conn,
            "rows.comentario",
            [("item_comentarios", undo.select(conn, "item_comentarios", "id=?", (cid,)))],
            title=row["texto"].split("\n")[0][:80],
        )
        conn.execute("DELETE FROM item_comentarios WHERE id=?", (cid,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


# ─────────────────────────────────────────────
# Adjuntos
# ─────────────────────────────────────────────


def _nombre_limpio(nombre: str) -> str:
    base = os.path.basename((nombre or "").replace("\\", "/")).strip()
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)[:180]
    return base or "archivo"


@router.post("/{item_id}/adjuntos")
def api_adjuntar(item_id: int, archivo: UploadFile = File(...)):  # def: el disco va en un hilo
    nombre = _nombre_limpio(archivo.filename or "")
    with get_db() as conn:
        _item(conn, item_id)
        if (
            conn.execute("SELECT COUNT(*) FROM item_adjuntos WHERE item_id=?", (item_id,)).fetchone()[0]
            >= MAX_POR_TAREA
        ):
            raise HTTPException(status_code=409, detail=f"Como mucho {MAX_POR_TAREA} adjuntos por tarea")
    ext = os.path.splitext(nombre)[1].lower()
    ext = ext if EXT_RE.match(ext) else ""
    rel = f"{item_id}/{uuid.uuid4().hex}{ext}"
    dest = adjuntos_dir() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with open(dest, "wb") as f:
            while chunk := archivo.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="El archivo supera los 25 MB")
                f.write(chunk)
        if not total:
            raise HTTPException(status_code=400, detail="Archivo vacío")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    mime = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    with get_db() as conn:
        aid = conn.execute(
            "INSERT INTO item_adjuntos (item_id, nombre, archivo, mime, bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, nombre, rel, mime, total, time.time()),
        ).lastrowid
        row = conn.execute("SELECT * FROM item_adjuntos WHERE id=?", (aid,)).fetchone()
    log.info("Adjunto en la tarea %d: %s (%d bytes)", item_id, rel, total)
    return _adj_out(row)


def _adjunto(conn, item_id: int, aid: int):
    row = conn.execute("SELECT * FROM item_adjuntos WHERE id=? AND item_id=?", (aid, item_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    return row


def _ruta(rel: str) -> Path:
    base = adjuntos_dir().resolve()
    path = (base / rel).resolve()
    if base not in path.parents:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")
    return path


@router.get("/{item_id}/adjuntos/{aid}")
def api_descargar(item_id: int, aid: int, descargar: bool = False):
    with get_db() as conn:
        row = _adjunto(conn, item_id, aid)
    path = _ruta(row["archivo"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="El archivo ya no está en el disco")
    inline = row["mime"] in INLINE and not descargar
    disp = "inline" if inline else "attachment"
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", row["nombre"]) or "archivo"
    return FileResponse(
        path,
        media_type=row["mime"] if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row['nombre'])}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=0",
        },
    )


@router.delete("/{item_id}/adjuntos/{aid}")
def api_borrar_adjunto(item_id: int, aid: int):
    with get_db() as conn:
        row = _adjunto(conn, item_id, aid)
        token = undo.save_rows(
            conn,
            "rows.adjunto",
            [("item_adjuntos", undo.select(conn, "item_adjuntos", "id=?", (aid,)))],
            title=row["nombre"],
        )
        conn.execute("DELETE FROM item_adjuntos WHERE id=?", (aid,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


# ─────────────────────────────────────────────
# Purga (una vez al día, desde trash.purge_expired)
# ─────────────────────────────────────────────


def purge_orphans(now: float | None = None) -> int:
    """Marca los comentarios y adjuntos cuya tarea ya no está, quita la marca si volvió y borra los que llevan más
    de 31 días huérfanos. Luego borra los archivos que ya no nombra ninguna fila ni la papelera."""
    now = now or time.time()
    n = 0
    with get_db() as conn:
        for table in ("item_comentarios", "item_adjuntos"):
            conn.execute(
                f"UPDATE {table} SET huerfano_desde=NULL WHERE huerfano_desde IS NOT NULL "
                "AND item_id IN (SELECT id FROM inbox)"
            )
            conn.execute(
                f"UPDATE {table} SET huerfano_desde=? WHERE huerfano_desde IS NULL "
                "AND item_id NOT IN (SELECT id FROM inbox)",
                (now,),
            )
            n += conn.execute(f"DELETE FROM {table} WHERE huerfano_desde < ?", (now - ORPHAN_TTL_S,)).rowcount
        vivos = {r[0] for r in conn.execute("SELECT archivo FROM item_adjuntos")}
        papelera = "\n".join(r[0] for r in conn.execute("SELECT payload FROM undo_log WHERE kind='rows.adjunto'"))
    base = adjuntos_dir()
    if base.is_dir():
        for path in base.glob("*/*"):
            rel = f"{path.parent.name}/{path.name}"
            if rel in vivos or path.name in papelera or not path.is_file():
                continue
            if path.stat().st_mtime > now - 3600:  # recién subido: puede que su fila aún no esté escrita
                continue
            path.unlink(missing_ok=True)
            n += 1
        for d in base.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    if n:
        log.info("Adjuntos y comentarios huérfanos purgados: %d", n)
    return n
