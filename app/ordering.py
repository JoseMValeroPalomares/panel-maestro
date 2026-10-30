"""
Orden manual (arrastrar y soltar) del Baúl y de las notas.

El navegador manda «colócalo antes de X» (before_id; None = al final) en vez
de un índice: así funciona aunque la vista esté filtrada o buscando. El
servidor reescribe posiciones enteras de todo el grupo afectado.

- Baúl: grupo = categoría + tipo (vídeos de YouTube o web). Soltar en otra
  categoría del mismo tipo cambia la categoría. sort_order descendente.
- Notas: grupo = su categoría (misma normalización que el árbol del front:
  partes separadas por « - » o «->», sin distinguir mayúsculas). Solo se ordena
  dentro de su categoría; el orden vive en la tabla note_order, nunca en el .md.
"""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db
from app.notes_core import note_path

router = APIRouter(prefix="/api")


def category_key(category: str | None) -> str:
    """Igual que splitCategoryPath() de cerebro.js, en minúsculas."""
    raw = (category or "").replace("->", " - ")
    parts = [p.strip().lower() for p in re.split(r"\s+-\s+", raw) if p.strip()]
    return "/".join(parts) or "sin categoría"


def _place(ids: list, moving, before_id) -> list:
    ids = [i for i in ids if i != moving]
    if before_id is not None and before_id in ids:
        ids.insert(ids.index(before_id), moving)
    else:
        ids.append(moving)
    return ids


# ─────────────────────────────────────────────
# Baúl
# ─────────────────────────────────────────────

class ResourceMove(BaseModel):
    category: str = Field(min_length=1, max_length=120)
    before_id: int | None = None


def _is_yt(row) -> bool:
    return row["resource_type"] == "youtube"


def next_resource_order(conn, category: str) -> float:
    row = conn.execute("SELECT MAX(sort_order) FROM resources WHERE category=?", (category,)).fetchone()
    return (row[0] or 0) + 1


@router.post("/resources/{resource_id}/move")
def move_resource(resource_id: int, data: ResourceMove):
    with get_db() as conn:
        res = conn.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()
        if not res:
            raise HTTPException(status_code=404, detail="Recurso no encontrado")
        category = data.category.strip()
        if data.before_id is not None:
            before = conn.execute("SELECT * FROM resources WHERE id=?", (data.before_id,)).fetchone()
            if not before or (before["category"] or "General") != category:
                raise HTTPException(status_code=422, detail="El destino no está en esa categoría")
            if _is_yt(before) != _is_yt(res):
                raise HTTPException(status_code=422, detail="Los vídeos y las webs van en secciones distintas")
        group = [r for r in conn.execute("SELECT id, resource_type FROM resources WHERE category=? "
                                         "ORDER BY sort_order DESC, added_at DESC", (category,)).fetchall()
                 if _is_yt(r) == _is_yt(res)]
        order = _place([r["id"] for r in group], resource_id, data.before_id)
        n = len(order)
        for pos, rid in enumerate(order):
            conn.execute("UPDATE resources SET sort_order=? WHERE id=?", (float(n - pos), rid))
        conn.execute("UPDATE resources SET category=? WHERE id=?", (category, resource_id))
    return {"status": "success", "order": order}


# ─────────────────────────────────────────────
# Notas
# ─────────────────────────────────────────────

class NoteMove(BaseModel):
    before_id: str | None = Field(default=None, max_length=200)


def note_positions(conn) -> dict[str, float]:
    return {r["note_id"]: r["position"] for r in conn.execute("SELECT note_id, position FROM note_order")}


@router.post("/notes/{note_id}/move")
def move_note(note_id: str, data: NoteMove):
    note_path(note_id)
    with get_db() as conn:
        note = conn.execute("SELECT id, title, category FROM notes WHERE id=?", (note_id,)).fetchone()
        if not note:
            raise HTTPException(status_code=404, detail="Nota no encontrada")
        key = category_key(note["category"])
        siblings = [r for r in conn.execute("SELECT id, title, category FROM notes").fetchall() if category_key(r["category"]) == key]
        if data.before_id is not None and data.before_id not in {r["id"] for r in siblings}:
            raise HTTPException(status_code=422, detail="Solo se puede ordenar dentro de su categoría")
        pos = note_positions(conn)
        # Orden actual que se ve: primero las que ya tienen posición, luego por título
        siblings.sort(key=lambda r: (r["id"] not in pos, pos.get(r["id"], 0), (r["title"] or "").lower()))
        order = _place([r["id"] for r in siblings], note_id, data.before_id)
        conn.execute("DELETE FROM note_order WHERE category_key=?", (key,))
        conn.executemany("INSERT OR REPLACE INTO note_order (note_id, category_key, position) VALUES (?, ?, ?)",
                         [(nid, key, float(i)) for i, nid in enumerate(order)])
    return {"status": "success", "order": order}

