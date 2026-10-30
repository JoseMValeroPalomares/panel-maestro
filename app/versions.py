"""
Historial de versiones de las notas.

Antes de sobrescribir un .md se guarda su contenido anterior (el archivo tal
cual, frontmatter incluido) en data/versions/<nota>/<milisegundos>.md. Las
ediciones seguidas se agrupan: si la última versión tiene menos de
SESSION_GAP_S, no se crea otra (el autoguardado escribe cada segundo). Se
conservan MAX_VERSIONS por nota.
"""
import os
import re
import time
from pathlib import Path

import frontmatter
from fastapi import APIRouter, HTTPException

from app.indexer import sync_notes_to_db
from app.notes_core import note_path, sync_flashcards
from core import config
from core.logging_config import get_logger

log = get_logger("versions")
router = APIRouter(prefix="/api/notes")

SESSION_GAP_S = 10 * 60
MAX_VERSIONS = 50
VERSION_RE = re.compile(r"^\d{10,16}$")


def _dir(note_id: str) -> Path:
    note_path(note_id)  # valida el identificador
    return Path(config.DATA_DIR) / "versions" / note_id


def _list(note_id: str) -> list[Path]:
    d = _dir(note_id)
    if not d.is_dir():
        return []
    return sorted((p for p in d.glob("*.md") if VERSION_RE.match(p.stem)), key=lambda p: int(p.stem), reverse=True)


def snapshot(note_id: str, force: bool = False) -> str | None:
    """Guarda el archivo actual como versión (antes de sobrescribirlo).
    Devuelve el id de la versión o None si no hacía falta."""
    path = note_path(note_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    versions = _list(note_id)
    if versions:
        last = versions[0]
        if not force and time.time() - int(last.stem) / 1000 < SESSION_GAP_S:
            return None
        if last.read_text(encoding="utf-8") == raw:
            return None
    d = _dir(note_id)
    d.mkdir(parents=True, exist_ok=True)
    vid = str(int(time.time() * 1000))
    (d / f"{vid}.md").write_text(raw, encoding="utf-8", newline="")
    for old in _list(note_id)[MAX_VERSIONS:]:
        old.unlink(missing_ok=True)
    return vid


def _version_path(note_id: str, vid: str) -> Path:
    if not VERSION_RE.match(vid):
        raise HTTPException(status_code=400, detail="Versión no válida")
    p = _dir(note_id) / f"{vid}.md"
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Esa versión no existe")
    return p


@router.get("/{note_id}/versions")
def list_versions(note_id: str):
    out = []
    for p in _list(note_id):
        try:
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            title, encrypted, words = post.get("title"), bool(post.get("encrypted")), len(post.content.split())
        except Exception:
            title, encrypted, words = None, False, 0
        out.append({"id": p.stem, "saved_at": int(p.stem) / 1000, "size": p.stat().st_size, "title": title,
                    "encrypted": encrypted, "words": words})
    return {"versions": out}


@router.get("/{note_id}/versions/{vid}")
def get_version(note_id: str, vid: str):
    post = frontmatter.loads(_version_path(note_id, vid).read_text(encoding="utf-8"))
    return {"id": vid, "saved_at": int(vid) / 1000, "title": post.get("title"), "category": post.get("category"),
            "encrypted": bool(post.get("encrypted")), "content": post.content}


@router.post("/{note_id}/versions/{vid}/restore")
def restore_version(note_id: str, vid: str):
    src = _version_path(note_id, vid)
    current = snapshot(note_id, force=True)  # lo actual también queda en el historial
    with open(note_path(note_id), "w", encoding="utf-8", newline="") as f:
        f.write(src.read_text(encoding="utf-8"))
    sync_notes_to_db()  # también rehace las filas de sus casillas
    restored = frontmatter.loads(src.read_text(encoding="utf-8"))
    if not restored.get("encrypted"):
        sync_flashcards(note_id, restored.content)
    log.info("Nota %s restaurada a la versión %s", note_id, vid)
    return {"status": "success", "previous_version": current}
