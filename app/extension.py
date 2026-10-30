"""Rutas de la extensión de Firefox: el alias POST /api/inbox (versiones 2.x ya instaladas) y su comprobación de estado."""
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.items import ItemIn, _clean_body, counts, create
from app.notes_core import PRIORITIES, normalize_item_type

router = APIRouter()


def _clean_priority(v: str | None, allow_empty: bool = False) -> str | None:
    """Prioridad del Inbox: alta, media o baja; "" (al editar) la quita."""
    if v is None or (v == "" and allow_empty):
        return v
    if v not in PRIORITIES:
        raise ValueError("La prioridad es alta, media o baja")
    return v


class InboxItem(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    item_type: str = Field(default="nota", max_length=20)
    parent_id: int | None = None
    priority: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=60)

    @field_validator("content")
    @classmethod
    def _content(cls, v):
        return _clean_body(v)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v):
        return _clean_priority(v or None)

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        return (v or "").strip() or None


@router.post("/api/inbox")
def add_inbox_item(item: InboxItem):
    """Alias de POST /api/items para la extensión de Firefox 2.x ya instalada (envía content/item_type)."""
    new_id = create(ItemIn(text=item.content, type="idea" if normalize_item_type(item.item_type) == "nota" else "tarea",
                           parent_id=item.parent_id, priority=item.priority, category=item.category))
    return {"status": "success", "id": new_id}


@router.get("/api/ext/status")
def extension_status():
    """Para la extensión de Firefox: comprueba la conexión y el token, y da los pendientes (mismo contador que el panel)."""
    pending = counts()["pendientes"]
    with get_db() as conn:
        cats = [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM inbox WHERE category IS NOT NULL AND category != '' ORDER BY category")]
    return {"ok": True, "pending": pending, "inbox_categories": cats, "api": 2}
