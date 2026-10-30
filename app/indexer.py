"""
Indexación de las notas .md (fuente de verdad) en la caché SQLite.

Upsert en UNA transacción: solo se reescriben las notas nuevas o modificadas
y solo se eliminan de la caché las que ya no existen en disco. Así se
conservan los datos que viven únicamente en la BD (last_reviewed, posiciones
del grafo...) y un fallo a mitad no deja la caché vacía.
"""
import os

import frontmatter

from app.database import get_db
from app.note_tasks import note_has_items, sync_note_items
from core import config
from core.logging_config import get_logger

log = get_logger("indexer")

NOTES_DIR = str(config.NOTES_DIR)

VALID_STATUSES = {"por-escribir", "en-desarrollo", "consolidado", "indice"}


def valid_category(conn, category_id: int | None) -> int | None:
    """El category_id si esa categoría existe: un .md puede traer uno viejo y la clave foránea no lo admitiría."""
    if category_id is None or not conn.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
        return None
    return category_id


def upsert_note(conn, note: dict) -> None:
    """Crea o actualiza la fila sin borrarla: un INSERT OR REPLACE la borra antes, y la cascada se lleva sus flashcards
    con su progreso. Lo que solo vive en la BD (last_reviewed) se conserva."""
    conn.execute("""
        INSERT INTO notes (id, title, category, category_id, tags, content, status, encrypted, last_modified)
        VALUES (:id, :title, :category, :category_id, :tags, :content, :status, :encrypted, :last_modified)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, category=excluded.category, category_id=excluded.category_id,
            tags=excluded.tags, content=excluded.content, status=excluded.status,
            encrypted=excluded.encrypted, last_modified=excluded.last_modified
    """, note)


def _read_note(filepath: str, note_id: str) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        post = frontmatter.load(f)
    status = post.get("status", "por-escribir")
    if status not in VALID_STATUSES:
        status = "por-escribir"
    tags = post.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    category_id = post.get("category_id")
    return {
        "id": note_id,
        "title": str(post.get("title", note_id)),
        "category": str(post.get("category", "Sin clasificar") or "Sin clasificar"),
        "category_id": category_id if isinstance(category_id, int) else None,
        "tags": ",".join(str(t) for t in tags),
        "content": post.content,
        "status": status,
        "encrypted": 1 if post.get("encrypted") else 0,
        "last_modified": os.path.getmtime(filepath),
    }


def sync_notes_to_db(force: bool = False) -> dict:
    """Sincroniza data/notes -> tabla notes. Devuelve un resumen de cambios."""
    os.makedirs(NOTES_DIR, exist_ok=True)
    on_disk: dict[str, str] = {}
    for filename in os.listdir(NOTES_DIR):
        if filename.endswith(".md") and not filename.startswith("."):
            on_disk[filename[:-3]] = os.path.join(NOTES_DIR, filename)

    stats = {"nuevas": 0, "actualizadas": 0, "eliminadas": 0, "errores": 0}
    with get_db() as conn:
        cached = {r["id"]: r["last_modified"] for r in conn.execute("SELECT id, last_modified FROM notes")}

        for note_id, filepath in on_disk.items():
            mtime = os.path.getmtime(filepath)
            if not force and note_id in cached and cached[note_id] is not None and abs(cached[note_id] - mtime) < 1e-6:
                continue
            try:
                note = _read_note(filepath, note_id)
            except Exception:
                stats["errores"] += 1
                log.exception("No se pudo leer la nota %s", filepath)
                continue
            note["category_id"] = valid_category(conn, note["category_id"])
            upsert_note(conn, note)
            stats["actualizadas" if note_id in cached else "nuevas"] += 1
            # Sus casillas «- [ ]» en la lista única de tareas (app/note_tasks.py)
            sync_note_items(conn, note_id, note["content"] if note_has_items(note) else None)

        removed = [nid for nid in cached if nid not in on_disk]
        for nid in removed:
            conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
            sync_note_items(conn, nid, None)
        stats["eliminadas"] = len(removed)

    log.info("Indexación completada: %s", stats)
    return stats
