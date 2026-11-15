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

from app import contextos
from app.board_convert import convert_text
from app.database import get_db
from core import undo

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
    conn.execute(
        "INSERT OR REPLACE INTO board_canvas_legacy (board_id, data, report, migrated_at) VALUES (?, ?, ?, ?)",
        (board_id, raw, json.dumps(report, ensure_ascii=False), time.time()),
    )
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
        rows = undo.select(conn, "board_templates", "id=?", (template_id,))
        token = (
            undo.save_rows(conn, "rows.plantilla-tablero", [("board_templates", rows)], title=rows[0]["name"])
            if rows
            else None
        )
        conn.execute("DELETE FROM board_templates WHERE id=?", (template_id,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


# ─────────────────────────────────────────────
# Tableros: /api/boards
# ─────────────────────────────────────────────


class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    item_id: int | None = None  # tablero de una tarea o idea (uno por elemento)
    data: str | None = Field(default=None, max_length=5_000_000)  # contenido inicial (formato 2)
    # Contexto (app/contextos.py): el esquema puede ser de un proyecto o de una asignatura
    contexto: str | None = Field(default=None, max_length=12)
    proyecto_id: int | None = Field(default=None, ge=0)
    asignatura_id: int | None = Field(default=None, ge=0)


class BoardContext(BaseModel):
    contexto: str | None = Field(default=None, max_length=12)
    proyecto_id: int | None = Field(default=None, ge=0)  # 0 lo quita
    asignatura_id: int | None = Field(default=None, ge=0)  # 0 la quita


class BoardRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class BoardCanvasSave(BaseModel):
    data: str = Field(max_length=20_000_000)
    # Revisión con la que se cargó (conflictos entre dispositivos). Sin ella se guarda como siempre (clientes viejos).
    base_rev: int | None = Field(default=None, ge=0)
    # Tras un conflicto, «quedarme con lo mío»: lo del otro dispositivo queda en la copia previa
    force: bool = False


PREV_GAP_S = 10 * 60  # como el historial de notas: una copia previa por tanda de edición, no por autoguardado


def _canvas(conn, board_id: int):
    return conn.execute("SELECT data, rev FROM board_canvas WHERE board_id=?", (board_id,)).fetchone()


def _keep_prev(conn, board_id: int, data: str, rev: int, always: bool) -> None:
    """Guarda el lienzo que se va a sustituir como copia previa (una por tablero)."""
    if not always:
        b = conn.execute("SELECT updated_at FROM boards WHERE id=?", (board_id,)).fetchone()
        prev = conn.execute("SELECT 1 FROM board_canvas_prev WHERE board_id=?", (board_id,)).fetchone()
        if prev and b and b["updated_at"] and time.time() - b["updated_at"] < PREV_GAP_S:
            return
    if not data or data == "{}":
        return
    conn.execute(
        """INSERT INTO board_canvas_prev (board_id, data, rev, saved_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(board_id) DO UPDATE SET data=excluded.data, rev=excluded.rev, saved_at=excluded.saved_at""",
        (board_id, data, rev, time.time()),
    )


def _conflict(conn, board_id: int) -> JSONResponse:
    cur = _canvas(conn, board_id)
    b = conn.execute("SELECT updated_at FROM boards WHERE id=?", (board_id,)).fetchone()
    return JSONResponse(
        status_code=409,
        content={
            "error": "Este tablero cambió en otro dispositivo",
            "conflict": True,
            "current": {
                "data": upgrade_board(conn, board_id, cur["data"] if cur else None),
                "rev": cur["rev"] if cur else 0,
                "updated_at": b["updated_at"] if b else None,
            },
        },
    )


@api_router.get("")
def list_boards():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM boards ORDER BY updated_at DESC").fetchall()
        conts = contextos.containers(conn)
    return {
        "boards": [
            {
                "id": r["id"],
                "name": r["name"],
                "item_id": r["item_id"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                **contextos.label(r, conts),
            }
            for r in rows
        ]
    }


@api_router.post("")
def create_board(board: BoardIn):
    if board.data is not None and not is_board_v2(board.data):
        raise HTTPException(status_code=422, detail="Contenido de tablero no válido")
    with get_db() as conn:
        ctx, asig, proy = contextos.resolve(conn, board.contexto, board.asignatura_id, board.proyecto_id)
        if board.item_id is not None:
            if not conn.execute("SELECT 1 FROM inbox WHERE id=?", (board.item_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Esa tarea ya no existe")
            old = conn.execute("SELECT id FROM boards WHERE item_id=?", (board.item_id,)).fetchone()
            if old:  # uno por elemento: si ya lo tiene, se devuelve ese
                return {"status": "success", "id": old["id"], "existing": True}
        cursor = conn.cursor()
        if board.item_id is not None and board.contexto is None and not board.proyecto_id and not board.asignatura_id:
            it = conn.execute(
                "SELECT contexto, asignatura_id, proyecto_id FROM inbox WHERE id=?", (board.item_id,)
            ).fetchone()
            ctx, asig, proy = it["contexto"] or "puntual", it["asignatura_id"], it["proyecto_id"]  # el de su tarea
        cursor.execute(
            "INSERT INTO boards (name, item_id, contexto, asignatura_id, proyecto_id) VALUES (?, ?, ?, ?, ?)",
            (board.name, board.item_id, ctx, asig, proy),
        )
        board_id = cursor.lastrowid
        cursor.execute("INSERT INTO board_canvas (board_id, data) VALUES (?, ?)", (board_id, board.data or "{}"))
        conn.commit()
    return {"status": "success", "id": board_id}


@api_router.get("/{board_id}")
def get_board(board_id: int):
    with get_db() as conn:
        board = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        canvas = _canvas(conn, board_id)
        if not board:
            return JSONResponse(status_code=404, content={"error": "Tablero no encontrado"})
        data = upgrade_board(conn, board_id, canvas["data"] if canvas else None)
        has_prev = conn.execute("SELECT 1 FROM board_canvas_prev WHERE board_id=?", (board_id,)).fetchone() is not None
    return {
        "id": board_id,
        "name": board["name"],
        "item_id": board["item_id"],
        "updated_at": board["updated_at"],
        "data": data,
        "rev": canvas["rev"] if canvas else 0,
        "has_prev": has_prev,
        "contexto": board["contexto"],
        "proyecto_id": board["proyecto_id"],
        "asignatura_id": board["asignatura_id"],
    }


@api_router.patch("/{board_id}")
def rename_board(board_id: int, payload: BoardRename):
    with get_db() as conn:
        conn.execute("UPDATE boards SET name=?, updated_at=unixepoch() WHERE id=?", (payload.name, board_id))
        conn.commit()
    return {"status": "success"}


@api_router.patch("/{board_id}/contexto")
def set_board_context(board_id: int, payload: BoardContext):
    with get_db() as conn:
        b = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        if not b:
            raise HTTPException(status_code=404, detail="Tablero no encontrado")
        ctx, asig, proy = contextos.resolve(
            conn,
            payload.contexto,
            payload.asignatura_id,
            payload.proyecto_id,
            (b["contexto"] or "puntual", b["asignatura_id"], b["proyecto_id"]),
        )
        conn.execute(
            "UPDATE boards SET contexto=?, asignatura_id=?, proyecto_id=? WHERE id=?", (ctx, asig, proy, board_id)
        )
    return {"status": "success", "contexto": ctx, "asignatura_id": asig, "proyecto_id": proy}


@api_router.post("/{board_id}/canvas")
def save_board_canvas(board_id: int, payload: BoardCanvasSave):
    """Guarda el lienzo. Con base_rev, si otro dispositivo guardó después → 409 con lo actual (nada se pisa sin avisar).
    Mismo lienzo que el guardado = éxito aunque la revisión no cuadre (un reintento cuya respuesta se perdió)."""
    # Una pestaña con el tablero antiguo abierta no puede pisar uno ya convertido
    if not is_board_v2(payload.data):
        raise HTTPException(
            status_code=409, detail="Este tablero se actualizó: recarga la página para seguir editándolo"
        )
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM boards WHERE id=?", (board_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Tablero no encontrado")
        cur = _canvas(conn, board_id)
        cur_data, cur_rev = (cur["data"], cur["rev"]) if cur else ("{}", 0)
        if cur_data == payload.data:
            return {"status": "success", "rev": cur_rev, "unchanged": True}
        if payload.base_rev is not None and payload.base_rev != cur_rev and not payload.force:
            return _conflict(conn, board_id)
        _keep_prev(conn, board_id, cur_data, cur_rev, always=payload.force)
        rev = cur_rev + 1
        conn.execute(
            """INSERT INTO board_canvas (board_id, data, rev) VALUES (?, ?, ?)
                        ON CONFLICT(board_id) DO UPDATE SET data=excluded.data, rev=excluded.rev""",
            (board_id, payload.data, rev),
        )
        conn.execute("UPDATE boards SET updated_at=unixepoch('subsec') WHERE id=?", (board_id,))
        has_prev = conn.execute("SELECT 1 FROM board_canvas_prev WHERE board_id=?", (board_id,)).fetchone() is not None
    return {"status": "success", "rev": rev, "has_prev": has_prev}


class BoardPrevIn(BaseModel):
    data: str = Field(max_length=20_000_000)


@api_router.post("/{board_id}/canvas/prev")
def keep_board_prev(board_id: int, payload: BoardPrevIn):
    """Tras un conflicto, «recargar el otro»: el lienzo propio queda como copia previa (se recupera con Deshacer último guardado)."""
    if not is_board_v2(payload.data):
        raise HTTPException(status_code=422, detail="Contenido de tablero no válido")
    with get_db() as conn:
        cur = _canvas(conn, board_id)
        if not cur:
            raise HTTPException(status_code=404, detail="Tablero no encontrado")
        _keep_prev(conn, board_id, payload.data, cur["rev"], always=True)
    return {"status": "success"}


@api_router.post("/{board_id}/canvas/undo-save")
def undo_board_save(board_id: int):
    """Intercambia el lienzo con su copia previa: deshacerlo es volver a pulsarlo."""
    with get_db() as conn:
        cur = _canvas(conn, board_id)
        prev = conn.execute("SELECT data FROM board_canvas_prev WHERE board_id=?", (board_id,)).fetchone()
        if not cur or not prev:
            raise HTTPException(status_code=404, detail="No hay ningún guardado anterior de este tablero")
        rev = cur["rev"] + 1
        conn.execute(
            "UPDATE board_canvas_prev SET data=?, rev=?, saved_at=? WHERE board_id=?",
            (cur["data"], cur["rev"], time.time(), board_id),
        )
        conn.execute("UPDATE board_canvas SET data=?, rev=? WHERE board_id=?", (prev["data"], rev, board_id))
        conn.execute("UPDATE boards SET updated_at=unixepoch('subsec') WHERE id=?", (board_id,))
        data = upgrade_board(conn, board_id, prev["data"])
    return {"status": "success", "rev": rev, "data": data}


@api_router.delete("/{board_id}")
def delete_board(board_id: int):
    """Va a la papelera con su lienzo y su copia previa (caen en cascada; board_canvas_legacy no se toca)."""
    with get_db() as conn:
        rows = undo.select(conn, "boards", "id=?", (board_id,))
        if not rows:
            return {"status": "success", "undo_token": None}
        token = undo.save_rows(
            conn,
            "rows.tablero",
            [
                ("boards", rows),
                ("board_canvas", undo.select(conn, "board_canvas", "board_id=?", (board_id,))),
                ("board_canvas_prev", undo.select(conn, "board_canvas_prev", "board_id=?", (board_id,))),
            ],
            title=rows[0]["name"],
        )
        conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}
