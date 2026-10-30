"""
API de las notas y sus categorías. La fuente de verdad son los .md de data/notes; la BD es una caché.

Rutas fijas ANTES de /api/notes/{note_id}: FastAPI empareja en orden.
"""
import os
import random
import re
import sqlite3
import time

import frontmatter
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.bulk import NotesSelection, bulk_delete
from app.database import get_db
from app.note_tasks import sync_note_items
from app.notes_core import (MAX_NOTE_CONTENT, MAX_TAGS, MAX_TITLE, extract_wiki_links, normalize_status, note_path, slugify,
                            split_category_path, sync_flashcards, update_index_for_area)
from app.ordering import category_key
from app.study import register_study_day
from app.versions import snapshot as snapshot_version

router = APIRouter()


class NoteData(BaseModel):
    title: str = Field(max_length=MAX_TITLE)
    category: str = Field(max_length=MAX_TITLE)
    category_id: int | None = None
    content: str = Field(max_length=MAX_NOTE_CONTENT)
    status: str = Field(default="por-escribir", max_length=30)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    encrypted: bool = False

    @field_validator("tags")
    @classmethod
    def _tags_cortos(cls, v):
        if v is not None and any(len(t) > 80 for t in v):
            raise ValueError("Cada etiqueta debe tener como máximo 80 caracteres")
        return v


class StatusUpdate(BaseModel):
    status: str = Field(max_length=30)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = None


# ─────────────────────────────────────────────
# API de Categorías
# ─────────────────────────────────────────────

@router.post("/api/categories")
def create_category(payload: CategoryIn):
    with get_db() as conn:
        slug = slugify(payload.name)
        if payload.parent_id:
            parent = conn.execute("SELECT slug FROM categories WHERE id=?", (payload.parent_id,)).fetchone()
            if parent:
                slug = f"{parent['slug']}/{slug}"
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO categories (name, parent_id, slug) VALUES (?, ?, ?)",
                (payload.name, payload.parent_id, slug)
            )
            conn.commit()
            new_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return JSONResponse(status_code=409, content={"error": "Categoría ya existe"})
    return {"status": "success", "id": new_id, "slug": slug}


@router.get("/api/categories/tree")
def get_category_tree():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, parent_id, slug FROM categories ORDER BY name").fetchall()
    by_parent = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(dict(r))

    def build(parent_id=None):
        return [
            {**node, "children": build(node["id"])}
            for node in by_parent.get(parent_id, [])
        ]

    return {"tree": build(None)}


@router.get("/api/categories/{category_id}/notes")
def get_notes_in_branch(category_id: int):
    with get_db() as conn:
        rows = conn.execute('''
            WITH RECURSIVE branch(id) AS (
                SELECT id FROM categories WHERE id = ?
                UNION ALL
                SELECT c.id FROM categories c JOIN branch b ON c.parent_id = b.id
            )
            SELECT n.id, n.title, n.category, n.category_id, n.status
            FROM notes n WHERE n.category_id IN (SELECT id FROM branch)
            ORDER BY n.last_modified DESC
        ''', (category_id,)).fetchall()
    return {"notes": [dict(r) for r in rows]}


@router.delete("/api/categories/{category_id}")
def delete_category(category_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
        conn.commit()
    return {"status": "success"}


# ─────────────────────────────────────────────
# API de Notas
# ─────────────────────────────────────────────

@router.get("/api/notes")
def get_all_notes():
    with get_db() as conn:
        notes = [dict(n) for n in conn.execute(
            "SELECT id, title, category, category_id, status, tags, encrypted FROM notes ORDER BY last_modified DESC")]
        order = {r["note_id"]: (r["category_key"], r["position"]) for r in conn.execute("SELECT * FROM note_order")}
    for n in notes:  # orden manual dentro de su categoría (si la nota cambió de categoría, ya no vale)
        key, pos = order.get(n["id"], (None, None))
        n["position"] = pos if key == category_key(n["category"]) else None
    return {"notes": notes}


# Rutas fijas ANTES de /api/notes/{note_id}: FastAPI empareja en orden.
class NoteMetaUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    category: str | None = Field(default=None, max_length=MAX_TITLE)
    category_id: int | None = None

class CategoryRename(BaseModel):
    old_category: str = Field(max_length=MAX_TITLE)
    new_category: str = Field(max_length=MAX_TITLE)


@router.get("/api/notes/recall")
def get_recall_note():
    """Elige una nota al azar ponderando por: tiempo desde el último repaso
    (más tiempo = más peso) y estado (consolidado pesa más porque es lo que
    más fácil se olvida al darlo por aprendido)."""
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, status, last_reviewed FROM notes WHERE encrypted=0").fetchall()
    if not rows:
        return JSONResponse(status_code=404, content={"error": "No hay notas disponibles"})

    now = time.time()
    status_boost = {"consolidado": 3.0, "en-desarrollo": 1.5, "por-escribir": 0.5, "indice": 0.3}
    weighted = []
    for r in rows:
        days_since = (now - (r['last_reviewed'] or 0)) / 86400
        weight = max(days_since, 1) * status_boost.get(r['status'], 1.0)
        weighted.append((r['id'], r['title'], weight))

    total = sum(w for _, _, w in weighted)
    pick = random.uniform(0, total)
    acc = 0
    for note_id, title, w in weighted:
        acc += w
        if acc >= pick:
            return {"note_id": note_id, "title": title}
    return {"note_id": weighted[-1][0], "title": weighted[-1][1]}


@router.post("/api/notes/rename-category")
def rename_category_bulk(data: CategoryRename):
    if not data.old_category.strip() or not data.new_category.strip():
        return JSONResponse(status_code=400, content={"error": "Categorías vacías no permitidas"})

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM notes WHERE category=?", (data.old_category,)
        ).fetchall()

        for row in rows:
            note_id = row['id']
            filepath = note_path(note_id)
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                post['category'] = data.new_category.strip()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(frontmatter.dumps(post))

        conn.execute(
            "UPDATE notes SET category=?, last_modified=? WHERE category=?",
            (data.new_category.strip(), time.time(), data.old_category)
        )
        conn.commit()
    return {"status": "success", "updated": len(rows)}

@router.get("/api/notes/{note_id}")
def get_note(note_id: str):
    note_path(note_id)  # valida el identificador
    with get_db() as conn:
        note = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if note:
        return dict(note)
    return JSONResponse(status_code=404, content={"error": "Nota no encontrada"})


@router.post("/api/notes/{note_id}")
def save_note(note_id: str, note_data: NoteData):
    filepath = note_path(note_id)

    old_area = None
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        old_area = split_category_path(post.get('category', ''))[0]
    else:
        post = frontmatter.Post("")
        post['tags'] = []

    # --- Blindaje: una nota índice no puede perder su status por un guardado normal ---
    with get_db() as conn:
        current = conn.execute("SELECT status FROM notes WHERE id = ?", (note_id,)).fetchone()
    incoming_status = normalize_status(note_data.status)
    if current and current["status"] == "indice" and incoming_status != "indice":
        status = "indice"
    else:
        status = incoming_status

    tags = note_data.tags if note_data.tags is not None else post.get('tags', [])

    post.content = note_data.content
    post['title'] = note_data.title
    post['category'] = note_data.category
    post['category_id'] = note_data.category_id
    post['status'] = status
    post['tags'] = tags
    post['encrypted'] = note_data.encrypted

    snapshot_version(note_id)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(frontmatter.dumps(post))

    with get_db() as conn:
        cursor = conn.cursor()
        last_modified = os.path.getmtime(filepath)

        cursor.execute('''
            INSERT OR REPLACE INTO notes (id, title, category, category_id, tags, content, status, last_modified, encrypted, last_reviewed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT last_reviewed FROM notes WHERE id=?), 0))
        ''', (note_id, note_data.title, note_data.category, note_data.category_id,
              ",".join(tags), note_data.content, status, last_modified, int(note_data.encrypted), note_id))

        if not note_data.encrypted:
            links = extract_wiki_links(note_data.content)
            cursor.execute("DELETE FROM graph_edges WHERE source = ? AND type = 'auto'", (note_id,))
            for target in links:
                cursor.execute('''
                    INSERT OR IGNORE INTO graph_edges (source, target, type)
                    VALUES (?, ?, 'auto')
                ''', (note_id, target))

        conn.commit()

    if not note_data.encrypted:
        sync_flashcards(note_id, note_data.content)
    with get_db() as conn:  # sus casillas en la lista única de tareas (app/note_tasks.py)
        sync_note_items(conn, note_id, note_data.content if not note_data.encrypted and status != "indice" else None)

    register_study_day()

    if status != "indice":
        new_area = split_category_path(note_data.category)[0]
        update_index_for_area(new_area)
        if old_area and old_area != new_area:
            update_index_for_area(old_area)

    return {"status": "success", "message": "Nota guardada"}


@router.patch("/api/notes/{note_id}/status")
def update_note_status(note_id: str, data: StatusUpdate):
    status = normalize_status(data.status)
    filepath = note_path(note_id)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        post['status'] = status
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))

    with get_db() as conn:
        conn.execute("UPDATE notes SET status = ? WHERE id = ?", (status, note_id))
        conn.commit()
    return {"status": "success", "new_status": status}


@router.patch("/api/notes/{note_id}/reviewed")
def mark_note_reviewed(note_id: str):
    """Quick Recall: marca la nota como repasada ahora mismo."""
    note_path(note_id)  # valida el identificador
    with get_db() as conn:
        conn.execute("UPDATE notes SET last_reviewed = ? WHERE id = ?", (time.time(), note_id))
        conn.commit()
    register_study_day()
    return {"status": "success"}


@router.get("/api/notes/{note_id}/related")
def get_related_notes(note_id: str):
    note_path(note_id)  # valida el identificador
    with get_db() as conn:
        current = conn.execute("SELECT category FROM notes WHERE id=?", (note_id,)).fetchone()
        if not current:
            return {"related": []}
        backlinks = conn.execute('''
            SELECT n.id, n.title FROM graph_edges e
            JOIN notes n ON n.id = e.source
            WHERE e.target=? AND n.id!=?
        ''', (note_id, note_id)).fetchall()
        outgoing = conn.execute('''
            SELECT n.id, n.title FROM graph_edges e
            JOIN notes n ON n.id = e.target
            WHERE e.source=? AND n.id!=?
        ''', (note_id, note_id)).fetchall()
        same_category = conn.execute('''
            SELECT id, title FROM notes WHERE category=? AND id!=? LIMIT 8
        ''', (current['category'], note_id)).fetchall()

    seen = set()
    combined = []
    for row in list(backlinks) + list(outgoing) + list(same_category):
        if row['id'] not in seen:
            seen.add(row['id'])
            combined.append(dict(row))
    return {"related": combined[:8]}

@router.get("/api/notes/{note_id}/wikilink-suggestions")
def get_wikilink_suggestions(note_id: str):
    """
    Busca en el contenido de esta nota apariciones literales de títulos
    de OTRAS notas que todavía no están enlazadas con [[...]], y las
    devuelve como sugerencias (nunca las fuerza ni las modifica solo).
    """
    note_path(note_id)  # valida el identificador
    with get_db() as conn:
        note = conn.execute("SELECT content, encrypted FROM notes WHERE id=?", (note_id,)).fetchone()
        if not note:
            return JSONResponse(status_code=404, content={"error": "Nota no encontrada"})

        if note['encrypted']:
            return {"suggestions": []}  # no tiene sentido escanear contenido cifrado

        content = note['content'] or ""
        others = conn.execute(
            "SELECT id, title FROM notes WHERE id != ? AND encrypted=0", (note_id,)
        ).fetchall()

    existing_links = set(extract_wiki_links(content))
    suggestions = []

    for row in others:
        title = (row['title'] or "").strip()
        target_id = row['id']
        if len(title) < 3 or target_id in existing_links:
            continue
        # busca el título como palabra completa, pero ignora si ya está
        # dentro de un [[...]] (evita contar lo que ya es un wikilink)
        pattern = re.compile(
            r'(?<!\[\[)\b' + re.escape(title) + r'\b(?!\]\])',
            re.IGNORECASE
        )
        matches = pattern.findall(content)
        if matches:
            suggestions.append({
                "note_id": target_id,
                "title": row['title'],
                "occurrences": len(matches),
            })

    suggestions.sort(key=lambda s: -s["occurrences"])
    return {"suggestions": suggestions[:10]}  # máximo 10 para no saturar la UI

ANNOTATION_PATTERN = re.compile(r'\{\{(resumir|entender|mal):([\s\S]+?)\}\}')

@router.get("/api/annotations")
def get_all_annotations(tag: str = None):
    """
    Devuelve todos los bloques marcados con {{resumir:...}}, {{entender:...}}
    o {{mal:...}} en todas las notas no cifradas. Filtra opcionalmente por tag.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, content FROM notes WHERE encrypted=0"
        ).fetchall()

    results = []
    for row in rows:
        content = row['content'] or ""
        for match in ANNOTATION_PATTERN.finditer(content):
            found_tag, text = match.group(1), match.group(2).strip()
            if tag and found_tag != tag:
                continue
            results.append({
                "note_id": row['id'],
                "note_title": row['title'],
                "tag": found_tag,
                "text": text[:200],  # recorte para no saturar la respuesta
            })
    return {"annotations": results}

@router.delete("/api/notes/{note_id}")
def delete_note(note_id: str):
    """La nota va a la papelera (data/trash/<token>/): se puede restaurar 30 días."""
    note_path(note_id)  # valida el id
    if not os.path.exists(note_path(note_id)):
        raise HTTPException(status_code=404, detail="La nota no existe")
    snapshot_version(note_id, force=True)  # además, el contenido sigue en data/versions
    res = bulk_delete(NotesSelection(ids=[note_id]))
    with get_db() as conn:
        sync_note_items(conn, note_id, None)
    return {"status": "success", "undo_token": res["undo_token"]}


# Solo título y categoría: POST /api/notes/{id} exige el contenido, y desde el gestor rápido se podría vaciar la nota
# sin querer. Este toca únicamente el frontmatter.
@router.patch("/api/notes/{note_id}/meta")
def update_note_meta(note_id: str, data: NoteMetaUpdate):
    """Actualiza solo título y/o categoría, sin tocar el contenido.
    Pensado para el Gestor de Notas (edición rápida en tabla)."""
    filepath = note_path(note_id)
    if not os.path.exists(filepath):
        return JSONResponse(status_code=404, content={"error": "Nota no encontrada"})

    with open(filepath, 'r', encoding='utf-8') as f:
        post = frontmatter.load(f)

    if data.title is not None and data.title.strip():
        post['title'] = data.title.strip()
    if data.category is not None:
        post['category'] = data.category.strip()
    if data.category_id is not None:
        post['category_id'] = data.category_id

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(frontmatter.dumps(post))

    with get_db() as conn:
        last_modified = os.path.getmtime(filepath)
        updates = []
        params = []
        if data.title is not None and data.title.strip():
            updates.append("title=?")
            params.append(data.title.strip())
        if data.category is not None:
            updates.append("category=?")
            params.append(data.category.strip())
        if data.category_id is not None:
            updates.append("category_id=?")
            params.append(data.category_id)
        if updates:
            updates.append("last_modified=?")
            params.append(last_modified)
            params.append(note_id)
            conn.execute(f"UPDATE notes SET {', '.join(updates)} WHERE id=?", params)
            conn.commit()
    return {"status": "success"}
