"""
Gestión masiva de notas: edición en lote, borrado con deshacer, duplicado e
importación/exportación CSV y JSON.

Los .md siguen siendo la fuente de verdad: toda operación escribe el
frontmatter (mismo formato que el editor) y después actualiza la caché.
Las notas borradas no se eliminan: se mueven a data/trash/<token>/ y el
token permite deshacer.
"""
import os
import re
import shutil
import time
import unicodedata

import frontmatter
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.database import get_db
from app.indexer import sync_notes_to_db
from app.versions import snapshot as snapshot_version
from app.notes_core import (MAX_NOTE_CONTENT, MAX_TITLE, VALID_STATUSES, extract_wiki_links, note_path,
                            normalize_status, split_category_path, sync_flashcards, update_index_for_area)
from core import config, tabular, undo
from core.logging_config import get_logger

log = get_logger("bulk")
router = APIRouter(prefix="/api/bulk/notes")

MAX_IDS = 2000
EXPORT_FIELDS = ["id", "title", "category", "status", "tags", "content"]


class NotesSelection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=MAX_IDS)


class NotesUpdate(NotesSelection):
    category: str | None = Field(default=None, max_length=MAX_TITLE)
    status: str | None = Field(default=None, max_length=30)
    tags_add: list[str] = Field(default_factory=list, max_length=50)
    tags_remove: list[str] = Field(default_factory=list, max_length=50)


def _load(note_id: str):
    path = note_path(note_id)
    if not os.path.exists(path):
        return path, None
    with open(path, "r", encoding="utf-8") as f:
        return path, frontmatter.load(f)


def _write(path: str, post) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


def _area(category: str | None) -> str:
    return split_category_path(category or "")[0]


def _refresh_indexes(areas: set[str]) -> None:
    for area in areas:
        try:
            update_index_for_area(area)
        except Exception:
            log.exception("No se pudo actualizar el índice de %s", area)


def _clean_tags(tags) -> list[str]:
    out = []
    for t in tags or []:
        t = str(t).strip()
        if t and len(t) <= 80 and t not in out:
            out.append(t)
    return out


@router.post("/update")
def bulk_update(data: NotesUpdate):
    if data.status is not None and data.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="Estado no válido")
    add, remove = _clean_tags(data.tags_add), set(_clean_tags(data.tags_remove))
    updated, skipped, areas = 0, [], set()
    for note_id in data.ids:
        path, post = _load(note_id)
        if post is None:
            skipped.append(note_id)
            continue
        old_area = _area(post.get("category"))
        is_index = post.get("status") == "indice"
        if data.category is not None and not is_index:
            post["category"] = data.category.strip()
        if data.status is not None and not is_index:  # los índices automáticos conservan su estado
            post["status"] = normalize_status(data.status)
        if add or remove:
            tags = [t for t in _clean_tags(post.get("tags")) if t not in remove]
            tags += [t for t in add if t not in tags]
            post["tags"] = tags
        snapshot_version(note_id)
        _write(path, post)
        updated += 1
        if not is_index:
            areas |= {old_area, _area(post.get("category"))}
    sync_notes_to_db()
    _refresh_indexes(areas)
    return {"status": "success", "updated": updated, "skipped": skipped}


def _purge_trash() -> None:
    """Borra de la papelera lo que ya no se puede deshacer (caducado en undo_log)."""
    if not config.TRASH_DIR.exists():
        return
    limit = time.time() - undo.TTL_S
    for entry in config.TRASH_DIR.iterdir():
        if entry.is_dir() and entry.stat().st_mtime < limit:
            shutil.rmtree(entry, ignore_errors=True)


@router.post("/delete")
def bulk_delete(data: NotesSelection):
    trash_name = None
    moved, rows, areas = [], {"notes": [], "graph_edges": [], "graph_nodes": [], "flashcards": []}, set()
    with get_db() as conn:
        for note_id in dict.fromkeys(data.ids):
            path = note_path(note_id)
            if not os.path.exists(path):
                continue
            rows["notes"] += undo.rows_to_dicts(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)))
            rows["graph_edges"] += undo.rows_to_dicts(conn.execute("SELECT * FROM graph_edges WHERE source=? OR target=?", (note_id, note_id)))
            rows["graph_nodes"] += undo.rows_to_dicts(conn.execute("SELECT * FROM graph_nodes WHERE id=?", (note_id,)))
            rows["flashcards"] += undo.rows_to_dicts(conn.execute("SELECT * FROM flashcards WHERE note_id=?", (note_id,)))
            moved.append(note_id)
        if not moved:
            return {"status": "success", "deleted": 0, "undo_token": None}
        titles = [r["title"] or r["id"] for r in rows["notes"]]
        token = undo.save(conn, "notes.delete", {"ids": moved, "rows": rows},
                          title=titles[0] if len(titles) == 1 else f"{len(titles)} notas: " + ", ".join(titles[:3]), count=len(moved))
        trash_name = token
        trash = config.TRASH_DIR / trash_name
        trash.mkdir(parents=True, exist_ok=True)
        for note_id in moved:
            path = note_path(note_id)
            for r in rows["notes"]:
                if r["id"] == note_id and r.get("status") != "indice":
                    areas.add(_area(r.get("category")))
            shutil.move(path, trash / f"{note_id}.md")
            conn.execute("DELETE FROM flashcards WHERE note_id=?", (note_id,))
            conn.execute("DELETE FROM graph_edges WHERE source=? OR target=?", (note_id, note_id))
            conn.execute("DELETE FROM graph_nodes WHERE id=?", (note_id,))
            conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    _refresh_indexes(areas)
    _purge_trash()
    log.info("Borrado en lote de %d notas (papelera %s)", len(moved), trash_name)
    return {"status": "success", "deleted": len(moved), "undo_token": token}


@router.post("/undo/{token}")
def bulk_undo(token: str):
    with get_db() as conn:
        entry = undo.pop(conn, token, "notes.")
        if not entry:
            raise HTTPException(status_code=404, detail="No hay nada que deshacer (o ha caducado)")
        _, payload = entry
        trash = config.TRASH_DIR / token
        restored, areas = [], set()
        for note_id in payload["ids"]:
            src = trash / f"{note_id}.md"
            dst = note_path(note_id)
            if src.exists() and not os.path.exists(dst):
                shutil.move(str(src), dst)
                restored.append(note_id)
        rows = payload["rows"]
        undo.insert_rows(conn, "notes", [r for r in rows["notes"] if r["id"] in restored])
        undo.insert_rows(conn, "graph_nodes", [r for r in rows["graph_nodes"] if r["id"] in restored])
        undo.insert_rows(conn, "graph_edges", [r for r in rows["graph_edges"] if r["source"] in restored or r["target"] in restored])
        undo.insert_rows(conn, "flashcards", [r for r in rows["flashcards"] if r["note_id"] in restored])
        for r in rows["notes"]:
            if r["id"] in restored and r.get("status") != "indice":
                areas.add(_area(r.get("category")))
    if trash.exists() and not any(trash.iterdir()):
        trash.rmdir()
    sync_notes_to_db()
    _refresh_indexes(areas)
    return {"status": "success", "restored": len(restored)}


def _unique_id(base: str) -> str:
    candidate = base
    n = 2
    while os.path.exists(note_path(candidate)):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


@router.post("/duplicate")
def bulk_duplicate(data: NotesSelection):
    created, areas = [], set()
    for note_id in data.ids:
        path, post = _load(note_id)
        if post is None or post.get("status") == "indice":
            continue
        new_id = _unique_id(f"{note_id}-copia"[:190])
        copy = frontmatter.Post(post.content, **dict(post.metadata))
        copy["title"] = f"{post.get('title', note_id)} (copia)"
        _write(note_path(new_id), copy)
        created.append(new_id)
        areas.add(_area(post.get("category")))
    sync_notes_to_db()
    for new_id in created:
        _, post = _load(new_id)
        if not post.get("encrypted"):
            sync_flashcards(new_id, post.content)
            _store_auto_links(new_id, post.content)
    _refresh_indexes(areas)
    return {"status": "success", "created": created}


def _store_auto_links(note_id: str, content: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM graph_edges WHERE source=? AND type='auto'", (note_id,))
        for target in extract_wiki_links(content):
            conn.execute("INSERT OR IGNORE INTO graph_edges (source, target, type) VALUES (?, ?, 'auto')", (note_id, target))


@router.get("/export")
def bulk_export(format: str = "json", ids: str = ""):
    wanted = set(i for i in ids.split(",") if i) if ids else None
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, category, status, tags, content FROM notes ORDER BY category, title").fetchall()
    notes = [dict(r) for r in rows if wanted is None or r["id"] in wanted]
    for n in notes:
        n["tags"] = [t for t in (n["tags"] or "").split(",") if t]
    if format == "csv":
        return tabular.csv_response([{**n, "tags": ", ".join(n["tags"])} for n in notes], EXPORT_FIELDS, "notas")
    return tabular.json_response("notes", notes, "notas")


@router.post("/import")
async def bulk_import(file: UploadFile = File(...), mode: str = Form("skip"), dry_run: bool = Form(False)):
    """mode=skip conserva las notas existentes; mode=overwrite las sustituye."""
    items = await tabular.read_upload(file, "notes")

    def make_id(title: str) -> str:
        s = unicodedata.normalize("NFD", title.lower())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:190]

    result = {"crear": [], "sobrescribir": [], "omitir": [], "errores": []}
    plan = []
    for n, item in enumerate(items, start=1):
        title = str(item.get("title") or "").strip()
        if not title:
            result["errores"].append({"fila": n, "error": "Falta el título"})
            continue
        note_id = str(item.get("id") or "").strip() or make_id(title)
        try:
            path = note_path(note_id)
        except HTTPException:
            result["errores"].append({"fila": n, "error": f"Identificador no válido: {note_id}"})
            continue
        content = str(item.get("content") or "")
        if len(title) > MAX_TITLE or len(content) > MAX_NOTE_CONTENT:
            result["errores"].append({"fila": n, "error": "Título o contenido demasiado largos"})
            continue
        tags = tabular.split_list(item.get("tags"))
        exists = os.path.exists(path)
        if exists and mode != "overwrite":
            result["omitir"].append(note_id)
            continue
        result["sobrescribir" if exists else "crear"].append(note_id)
        plan.append((note_id, path, title, str(item.get("category") or "General")[:MAX_TITLE],
                     normalize_status(str(item.get("status") or "por-escribir")), _clean_tags(tags), content))

    if dry_run:
        return {"status": "preview", **result}

    areas = set()
    for note_id, path, title, category, status, tags, content in plan:
        post = frontmatter.Post(content)
        post["title"], post["category"], post["category_id"] = title, category, None
        post["status"], post["tags"], post["encrypted"] = status, tags, False
        snapshot_version(note_id)
        _write(path, post)
        areas.add(_area(category))
    sync_notes_to_db()
    for note_id, *_rest in plan:
        content = _rest[-1]
        sync_flashcards(note_id, content)
        _store_auto_links(note_id, content)
    _refresh_indexes(areas)
    log.info("Importación de notas: %d creadas, %d sobrescritas", len(result["crear"]), len(result["sobrescribir"]))
    return {"status": "success", **result}
