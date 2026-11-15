"""
Indexación de las notas .md (fuente de verdad) en la caché SQLite.

Upsert en UNA transacción: solo se reescriben las notas nuevas o modificadas
y solo se eliminan de la caché las que ya no existen en disco. Así se
conservan los datos que viven únicamente en la BD (last_reviewed, posiciones
del grafo...) y un fallo a mitad no deja la caché vacía.

Guarda contra lecturas vacías (como la del calendario): si de golpe faltan en disco
más del 30 % de las notas de la caché (habiendo más de 5), no se borra nada —la
cascada se llevaría las flashcards con su progreso—; se registra un aviso y
/api/status lo enseña hasta que la carpeta vuelva a cuadrar. Un disco sin montar o un
PANEL_NOTES_DIR mal puesto se leen así. Borrar desde el panel (suelta o en lote) no
pasa por aquí: bulk_delete quita las filas a la vez que mueve el archivo. Quien borra
de verdad muchas a la vez (restaurar una copia) llama con allow_mass_delete=True.
"""

import logging
import os
import sqlite3
import time

import frontmatter

from app.database import get_db
from app.note_tasks import note_has_items, sync_note_items
from core import config
from core.logging_config import get_logger

log = get_logger("indexer")

NOTES_DIR = str(config.NOTES_DIR)

VALID_STATUSES = {"por-escribir", "en-desarrollo", "consolidado", "indice"}

MASS_DELETE_RATIO = 0.3
MASS_DELETE_MIN_NOTES = 5
_guard: dict | None = None  # último borrado frenado (None = todo en orden)


def notes_guard_status() -> dict | None:
    return _guard


def _mass_delete(removed: int, cached: int) -> bool:
    return cached > MASS_DELETE_MIN_NOTES and removed > MASS_DELETE_RATIO * cached


def valid_category(conn, category_id: int | None) -> int | None:
    """El category_id si esa categoría existe: un .md puede traer uno viejo y la clave foránea no lo admitiría."""
    if category_id is None or not conn.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
        return None
    return category_id


def upsert_note(conn, note: dict) -> None:
    """Crea o actualiza la fila sin borrarla: un INSERT OR REPLACE la borra antes, y la cascada se lleva sus flashcards
    con su progreso. Lo que solo vive en la BD (last_reviewed) se conserva."""
    conn.execute(
        """
        INSERT INTO notes (id, title, category, category_id, tags, content, status, encrypted, last_modified)
        VALUES (:id, :title, :category, :category_id, :tags, :content, :status, :encrypted, :last_modified)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, category=excluded.category, category_id=excluded.category_id,
            tags=excluded.tags, content=excluded.content, status=excluded.status,
            encrypted=excluded.encrypted, last_modified=excluded.last_modified
    """,
        note,
    )
    _note_context(conn, note)


def note_context_fields(post) -> dict:
    """Contexto de una nota según su frontmatter (el .md manda): contexto, asignatura (código) y proyecto (slug)."""
    ctx = str(post.get("contexto") or "").strip().lower()
    return {
        "contexto": ctx if ctx in ("puntual", "universidad", "proyectos") else None,
        "asignatura": str(post.get("asignatura") or "").strip() or None,
        "proyecto": str(post.get("proyecto") or "").strip() or None,
    }


def _note_context(conn, note: dict) -> None:
    if "contexto" not in note:  # quien guarda sin leer el frontmatter (save_note): se lee del archivo
        try:
            with open(os.path.join(NOTES_DIR, f"{note['id']}.md"), encoding="utf-8") as f:
                note = {**note, **note_context_fields(frontmatter.load(f))}
        except (OSError, ValueError):
            return
    try:
        a = (
            conn.execute("SELECT id FROM asignaturas WHERE codigo=?", (note["asignatura"],)).fetchone()
            if note.get("asignatura")
            else None
        )
        p = (
            conn.execute("SELECT id FROM proyectos WHERE slug=?", (note["proyecto"],)).fetchone()
            if note.get("proyecto")
            else None
        )
    except sqlite3.OperationalError:  # BD sin la migración 22
        return
    ctx = "universidad" if a else "proyectos" if p else (note.get("contexto") or "puntual")
    conn.execute(
        "UPDATE notes SET contexto=?, asignatura_id=?, proyecto_id=? WHERE id=?",
        (ctx, a["id"] if a else None, p["id"] if p else None, note["id"]),
    )
    conn.execute(
        "UPDATE inbox SET contexto=?, asignatura_id=?, proyecto_id=? WHERE note_id=? AND note_task IS NOT NULL",
        (ctx, a["id"] if a else None, p["id"] if p else None, note["id"]),
    )


def _read_note(filepath: str, note_id: str) -> dict:
    with open(filepath, encoding="utf-8") as f:
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
        **note_context_fields(post),
    }


def sync_notes_to_db(force: bool = False, allow_mass_delete: bool = False) -> dict:
    """Sincroniza data/notes -> tabla notes. Devuelve un resumen de cambios."""
    global _guard
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
        if removed and not allow_mass_delete and _mass_delete(len(removed), len(cached)):
            if not _guard or _guard["missing"] != len(removed):  # una línea por situación, no una por lectura
                log.warning(
                    "Faltan en %s %d de %d notas: no se borra nada de la caché (¿carpeta sin montar?)",
                    NOTES_DIR,
                    len(removed),
                    len(cached),
                )
            _guard = {
                "at": time.time(),
                "missing": len(removed),
                "cached": len(cached),
                "dir": NOTES_DIR,
                "detail": f"Faltan {len(removed)} de {len(cached)} notas en la carpeta: no se ha borrado nada. "
                "¿Disco sin montar o PANEL_NOTES_DIR mal puesto?",
            }
            stats["frenadas"] = len(removed)
            removed = []
        elif _guard:
            log.info("La carpeta de notas vuelve a cuadrar con la caché")
            _guard = None
        for nid in removed:
            conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
            sync_note_items(conn, nid, None)
        stats["eliminadas"] = len(removed)

    # Se llama en cada lectura de tareas (varias por minuto): sin cambios no merece una línea en el log
    log.log(
        logging.INFO if any(v for k, v in stats.items() if k != "frenadas") else logging.DEBUG,
        "Indexación completada: %s",
        stats,
    )
    return stats
