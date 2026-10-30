"""
Tableros: conversión al formato 2 al leer, comprobación al guardar y plantillas.

La conversión en lectura cubre tableros que se guardaron en el formato antiguo
después de la migración 4 (p. ej. desde una pestaña vieja): el original se
conserva en board_canvas_legacy, igual que en la migración.
"""
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.board_convert import convert_text
from app.database import get_db

router = APIRouter(prefix="/api/board-templates")
api_router = APIRouter(prefix="/api/boards")  # los tableros (lista, crear, leer, guardar, borrar)


def is_board_v2(raw: str) -> bool:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return False
    return isinstance(data, dict) and (data.get("format") == 2 or data == {})


def upgrade_board(conn, board_id: int, raw: str | None) -> str:
    new, report = convert_text(raw)
    if report is None:
        return raw or "{}"
    conn.execute("""CREATE TABLE IF NOT EXISTS board_canvas_legacy (
        board_id INTEGER PRIMARY KEY, data TEXT NOT NULL, report TEXT, migrated_at REAL NOT NULL)""")
    conn.execute("INSERT OR REPLACE INTO board_canvas_legacy (board_id, data, report, migrated_at) VALUES (?, ?, ?, ?)",
                 (board_id, raw, json.dumps(report, ensure_ascii=False), time.time()))
    conn.execute("UPDATE board_canvas SET data=? WHERE board_id=?", (new, board_id))
    return new


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    data: str = Field(max_length=500_000)


@router.get("")
def list_templates():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, data FROM board_templates ORDER BY name").fetchall()
    return {"templates": [dict(r) for r in rows]}


@router.post("")
def create_template(t: TemplateIn):
    try:
        payload = json.loads(t.data)
        assert isinstance(payload.get("nodes"), list)
    except (ValueError, AssertionError, AttributeError):
        raise HTTPException(status_code=422, detail="Plantilla no válida")
    with get_db() as conn:
        cur = conn.execute("INSERT INTO board_templates (name, data) VALUES (?, ?)", (t.name.strip(), t.data))
    return {"status": "success", "id": cur.lastrowid}


@router.delete("/{template_id}")
def delete_template(template_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM board_templates WHERE id=?", (template_id,))
    return {"status": "success"}


# ─────────────────────────────────────────────
# Tableros: /api/boards
# ─────────────────────────────────────────────

class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    item_id: int | None = None   # tablero de una tarea o idea (uno por elemento)
    data: str | None = Field(default=None, max_length=5_000_000)  # contenido inicial (formato 2)


class BoardRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class BoardCanvasSave(BaseModel):
    data: str = Field(max_length=20_000_000)


@api_router.get("")
def list_boards():
    with get_db() as conn:
        rows = conn.execute("SELECT id, name, item_id, created_at, updated_at FROM boards ORDER BY updated_at DESC").fetchall()
    return {"boards": [dict(r) for r in rows]}


@api_router.post("")
def create_board(board: BoardIn):
    if board.data is not None and not is_board_v2(board.data):
        raise HTTPException(status_code=422, detail="Contenido de tablero no válido")
    with get_db() as conn:
        if board.item_id is not None:
            if not conn.execute("SELECT 1 FROM inbox WHERE id=?", (board.item_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Esa tarea ya no existe")
            old = conn.execute("SELECT id FROM boards WHERE item_id=?", (board.item_id,)).fetchone()
            if old:  # uno por elemento: si ya lo tiene, se devuelve ese
                return {"status": "success", "id": old["id"], "existing": True}
        cursor = conn.cursor()
        cursor.execute("INSERT INTO boards (name, item_id) VALUES (?, ?)", (board.name, board.item_id))
        board_id = cursor.lastrowid
        cursor.execute("INSERT INTO board_canvas (board_id, data) VALUES (?, ?)", (board_id, board.data or "{}"))
        conn.commit()
    return {"status": "success", "id": board_id}


@api_router.get("/{board_id}")
def get_board(board_id: int):
    with get_db() as conn:
        board = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        canvas = conn.execute("SELECT data FROM board_canvas WHERE board_id=?", (board_id,)).fetchone()
        if not board:
            return JSONResponse(status_code=404, content={"error": "Tablero no encontrado"})
        data = upgrade_board(conn, board_id, canvas["data"] if canvas else None)
    return {"id": board_id, "name": board['name'], "item_id": board['item_id'], "updated_at": board['updated_at'], "data": data}


@api_router.patch("/{board_id}")
def rename_board(board_id: int, payload: BoardRename):
    with get_db() as conn:
        conn.execute("UPDATE boards SET name=?, updated_at=unixepoch() WHERE id=?", (payload.name, board_id))
        conn.commit()
    return {"status": "success"}


@api_router.post("/{board_id}/canvas")
def save_board_canvas(board_id: int, payload: BoardCanvasSave):
    # Una pestaña con el tablero antiguo abierta no puede pisar uno ya convertido
    if not is_board_v2(payload.data):
        raise HTTPException(status_code=409, detail="Este tablero se actualizó: recarga la página para seguir editándolo")
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM boards WHERE id=?", (board_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Tablero no encontrado")
        conn.execute("INSERT OR REPLACE INTO board_canvas (board_id, data) VALUES (?, ?)", (board_id, payload.data))
        conn.execute("UPDATE boards SET updated_at=unixepoch() WHERE id=?", (board_id,))
        conn.commit()
    return {"status": "success"}


@api_router.delete("/{board_id}")
def delete_board(board_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
        conn.commit()
    return {"status": "success"}
