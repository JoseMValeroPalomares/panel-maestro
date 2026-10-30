"""
Tareas e ideas: un único servicio para crearlas, editarlas, moverlas, ordenarlas,
convertirlas, completarlas y borrarlas, lo use quien lo use (Inbox, tablero,
pestaña Tareas, captura rápida, casillas de las notas, extensión de Firefox).

Todo vive en la tabla `inbox` (un elemento = una fila). Cada elemento tiene un
origen, que es el grupo en el que se ve:
  - «nota»:  una casilla «- [ ]» de una nota (note_task no nulo). El .md manda
             sobre su texto, estado, orden y anidado; aquí se escribe la línea y
             se vuelve a indexar (app/note_tasks.py).
  - «ideas»: una idea (item_type = 'nota', nombre heredado).
  - «inbox»: una tarea suelta.

Reglas (las mismas en el navegador, static/js/items.js):
  1. Un solo nivel de pasos: el padre es siempre de primer nivel y un elemento con
     pasos no puede pasar a ser paso de otro.
  2. Padre y pasos son del mismo tipo: una subtarea nunca cuelga de una idea.
  3. Un elemento con pasos no cambia de tipo (ni de grupo si eso cambia el tipo).
  4. En una nota solo hay tareas: llevar una idea sin pasos a una nota la convierte.
Orden: `sort_order` descendente (el mayor arriba) en Inbox e Ideas; en una nota,
el orden de las líneas.
"""
import json
import os
import re
from datetime import date, timedelta

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.database import get_db
from app.indexer import sync_notes_to_db
from app import routines
from app.links import links_by_item, rebuild_all as rebuild_links
from app.notes_core import MAX_TITLE, PRIORITIES, note_path, note_slug, split_category_path, update_index_for_area
from app.note_tasks import INDENT, NoteDoc, TaskMissing, sync_note_items, task_line
from app.versions import snapshot as snapshot_version
from core import undo
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("items")
router = APIRouter(prefix="/api/items")

TARGETS = ("inbox", "nota", "ideas", "rutinas")
TYPE_DB = {"tarea": "tarea", "idea": "nota", "nota": "nota", "rutina": "rutina"}  # 'nota' = idea (nombre antiguo)
TARGET_TYPE = {"inbox": "tarea", "nota": "tarea", "ideas": "idea", "rutinas": "rutina"}
TYPE_TARGET = {"tarea": "inbox", "idea": "ideas", "rutina": "rutinas"}
MAX_TEXT = 20_000
LEGACY_DONE = re.compile(r"^---\s*")


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────

def _clean_type(v):
    if v is None:
        return v
    if v not in TYPE_DB:
        raise ValueError("El tipo es tarea, idea o rutina")
    return {"nota": "idea", "rutina": "rutina"}.get(TYPE_DB[v], "tarea")


def _clean_time(v):
    if v in (None, ""):
        return v
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError("La hora va como HH:MM")
    return v


def _clean_repeat_field(v):
    from app.routines import clean_repeat
    return clean_repeat(v)


def _clean_priority(v):
    if v in (None, ""):
        return v
    if v not in PRIORITIES:
        raise ValueError("La prioridad es alta, media o baja")
    return v


def _clean_date(v):
    if v in (None, ""):
        return v
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError("La fecha va como AAAA-MM-DD")


def _clean_body(v):
    if v is not None and not v.strip():
        raise ValueError("Falta el texto")
    return v


class ItemIn(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    type: str = Field(default="tarea", max_length=10)
    parent_id: int | None = None
    note_id: str | None = Field(default=None, max_length=200)   # crearla como casilla de esa nota
    priority: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=60)
    due_date: str | None = Field(default=None, max_length=10)
    details: str | None = Field(default=None, max_length=MAX_TEXT)
    due_time: str | None = Field(default=None, max_length=5)
    duration_min: int | None = Field(default=None, ge=0, le=1440)  # 0 = sin duración
    repeat: dict | None = None                                    # solo rutinas (app/routines.py)
    reminder_min: int | None = Field(default=None, ge=0, le=10080)

    @field_validator("text")
    @classmethod
    def v_text(cls, v):
        return _clean_body(v)

    @field_validator("type")
    @classmethod
    def v_type(cls, v):
        return _clean_type(v)

    @field_validator("due_time")
    @classmethod
    def v_time(cls, v):
        return _clean_time(v) or None

    @field_validator("repeat")
    @classmethod
    def v_repeat(cls, v):
        return _clean_repeat_field(v)

    @field_validator("priority")
    @classmethod
    def v_priority(cls, v):
        return _clean_priority(v) or None

    @field_validator("due_date")
    @classmethod
    def v_date(cls, v):
        return _clean_date(v) or None


class ItemPatch(BaseModel):
    """None = no cambia; "" quita prioridad, categoría, fecha o notas."""
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)
    type: str | None = Field(default=None, max_length=10)
    done: bool | None = None
    priority: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=60)
    due_date: str | None = Field(default=None, max_length=10)
    details: str | None = Field(default=None, max_length=MAX_TEXT)
    due_time: str | None = Field(default=None, max_length=5)        # "" la quita
    duration_min: int | None = Field(default=None, ge=0, le=1440)    # 0 la quita
    repeat: dict | None = None
    reminder_min: int | None = Field(default=None, ge=-1, le=10080)  # -1 lo quita
    day: str | None = Field(default=None, max_length=10)               # rutina: el día que se marca (hoy por defecto)
    step_days: list[int] | None = None   # paso de rutina: sus días (0 = lunes); [] = los de su rutina
    routine_step: int | None = Field(default=None, ge=0)  # tarea o idea: rutina o paso al que va asociada; 0 la suelta

    @field_validator("text")
    @classmethod
    def v_text(cls, v):
        return _clean_body(v)

    @field_validator("type")
    @classmethod
    def v_type(cls, v):
        return _clean_type(v)

    @field_validator("due_time")
    @classmethod
    def v_time(cls, v):
        return _clean_time(v)

    @field_validator("repeat")
    @classmethod
    def v_repeat(cls, v):
        return _clean_repeat_field(v)

    @field_validator("priority")
    @classmethod
    def v_priority(cls, v):
        return _clean_priority(v)

    @field_validator("due_date", "day")
    @classmethod
    def v_date(cls, v):
        return _clean_date(v)


class MoveIn(BaseModel):
    target: str | None = Field(default=None, max_length=10)     # inbox | nota | ideas (lo da el padre si hay)
    note_id: str | None = Field(default=None, max_length=200)
    parent_id: int | None = None                                  # None = primer nivel
    before_id: int | None = None                                  # colocarlo antes de este; None = al final


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    action: str = Field(max_length=20)                            # done | reopen | delete | category | priority | move
    value: str | None = Field(default=None, max_length=60)
    target: str | None = Field(default=None, max_length=10)
    note_id: str | None = Field(default=None, max_length=200)


class UndoIn(BaseModel):
    token: str = Field(min_length=4, max_length=64)


class ToNoteIn(BaseModel):
    note_id: str | None = Field(default=None, max_length=200)     # a una nota existente
    title: str | None = Field(default=None, max_length=MAX_TITLE)  # o a una nueva
    category: str = Field(default="Inbox", max_length=MAX_TITLE)


# ─────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────

def origin(row) -> str:
    if row["note_task"] is not None:
        return "nota"
    return {"nota": "ideas", "rutina": "rutinas"}.get(row["item_type"], "inbox")


def item_type(row) -> str:
    return {"nota": "idea", "rutina": "rutina"}.get(row["item_type"], "tarea")


def clean_text(content: str | None) -> str:
    return LEGACY_DONE.sub("", content or "").strip()


def _get(conn, item_id: int):
    row = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    return row


def _children(conn, item_id: int) -> list:
    return conn.execute("SELECT * FROM inbox WHERE parent_id=? ORDER BY sort_order DESC, created_at DESC", (item_id,)).fetchall()


def counts_of(rows) -> dict:
    """Mismo criterio en todas partes (Inbox, Tareas, menú, extensión): elementos de primer nivel.
    Las rutinas tienen su contador pero no suman al total (se repiten: siempre habría pendientes)."""
    out = {g: {"pendientes": 0, "hechas": 0} for g in TARGETS}
    for r in rows:
        if r["parent_id"] is None:
            out[origin(r)]["hechas" if r["status"] == "processed" else "pendientes"] += 1
    grupos = [g for g in TARGETS if g != "rutinas"]
    out["pendientes"] = sum(out[g]["pendientes"] for g in grupos)
    out["hechas"] = sum(out[g]["hechas"] for g in grupos)
    return out


def _visible_rows(conn) -> list:
    # Las casillas de notas cifradas o índice no se muestran (sync_note_items no las crea)
    return conn.execute("SELECT * FROM inbox ORDER BY sort_order DESC, created_at DESC").fetchall()


def serialize(r, notes: dict, links: dict | None = None, routine: dict | None = None, labels: dict | None = None) -> dict:
    note = notes.get(r["note_id"]) if r["note_id"] else None
    extra = {}
    if routine is not None:  # rutina: la casilla es «hecha hoy»
        extra = routine
    rs = _col(r, "routine_step")
    if rs:  # tarea o idea asociada a una rutina (o a un paso suyo)
        extra = {**extra, "routine_step": rs, "routine_label": (labels or {}).get(rs)}
    return {
        "links": (links or {}).get(r["id"], []),
        "due_time": r["due_time"], "duration_min": r["duration_min"], "reminder_min": r["reminder_min"],
        "id": r["id"], "text": clean_text(r["content"]), "type": item_type(r), "origin": origin(r),
        "done": r["status"] == "processed", "parent_id": r["parent_id"], "sort_order": r["sort_order"],
        "priority": r["priority"], "category": r["category"], "due_date": r["due_date"], "details": r["details"],
        "created_at": r["created_at"], "note_id": r["note_id"], "note_index": r["note_index"],
        "note_title": note["title"] if note else None, "note_category": note["category"] if note else None,
        "note_position": note["position"] if note else None,
        **extra,
    }


def list_items() -> dict:
    sync_notes_to_db()  # incremental: recoge notas editadas fuera del panel
    with get_db() as conn:
        rows = _visible_rows(conn)
        # note_position: el orden manual de la pestaña Notas (tabla note_order), para agrupar igual
        notes = {n["id"]: n for n in conn.execute(
            "SELECT n.id, n.title, n.category, o.position FROM notes n LEFT JOIN note_order o ON o.note_id = n.id")}
        links = links_by_item(conn)
        by_id = {r["id"]: r for r in rows}
        routines = {r["id"]: routine_info(conn, r) if r["parent_id"] is None else step_info(conn, r, by_id.get(r["parent_id"]))
                    for r in rows if r["item_type"] == "rutina"}
        labels = routine_labels(rows)
    return {"items": [serialize(r, notes, links, routines.get(r["id"]), labels) for r in rows], "counts": counts_of(rows)}


def _col(r, name):
    try:
        return r[name]
    except (IndexError, KeyError):
        return None


def routine_labels(rows) -> dict[int, str]:
    """«Mi día › Estudiar» para cada rutina y paso (lo que se ve en una tarea asociada)."""
    rut = {r["id"]: r for r in rows if r["item_type"] == "rutina"}
    first = lambda r: clean_text(r["content"]).split("\n")[0]  # noqa: E731
    return {i: (f"{first(rut[r['parent_id']])} › {first(r)}" if r["parent_id"] in rut else first(r)) for i, r in rut.items()}


def routine_info(conn, r, today: date | None = None) -> dict:
    """Estado de una rutina para la lista: hecha hoy, si toca hoy, regla, racha y mapa de 12 semanas."""
    today = today or date.today()
    rule = routines.parse(r["repeat"])
    since = routines.created_day(r)
    done = routines.checks(conn, r["id"])
    if done:
        since = min(since, date.fromisoformat(min(done)))
    return {"done": today.isoformat() in done, "repeat": rule, "repeat_text": routines.describe(rule),
            "today": routines.occurs_on(rule, today, since), "streak": routines.streak(rule, done, today, since),
            "heatmap": routines.heatmap(rule, done, today, since)}


def step_info(conn, r, parent, today: date | None = None) -> dict:
    """Paso de una rutina: hecho hoy y si toca hoy (lo que diga su rutina)."""
    today = today or date.today()
    if parent is None:
        return {"done": False, "today": True}
    rule = routines.parse(parent["repeat"])
    own = routines.step_rule(r)
    return {"done": today.isoformat() in routines.checks(conn, r["id"], since=today),
            "today": routines.occurs_on(rule, today, routines.created_day(parent) - timedelta(days=3650)) and routines.step_on(r, today),
            "step_days": own["days"] if own else None, "days_text": routines.describe(own) if own else None}


def counts() -> dict:
    sync_notes_to_db()
    with get_db() as conn:
        return counts_of(conn.execute("SELECT parent_id, status, note_task, item_type FROM inbox").fetchall())


# ─────────────────────────────────────────────
# Notas
# ─────────────────────────────────────────────

def _note_file(note_id: str) -> str:
    path = note_path(note_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="La nota no existe")
    with get_db() as conn:
        row = conn.execute("SELECT encrypted, status FROM notes WHERE id=?", (note_id,)).fetchone()
    if row and row["encrypted"]:
        raise HTTPException(status_code=422, detail="La nota está cifrada: sus tareas se editan dentro de la nota")
    if row and row["status"] == "indice":
        raise HTTPException(status_code=422, detail="Una nota índice se genera sola: no admite tareas")
    return path


class Docs:
    """Notas abiertas durante una operación; al final se guardan (con versión) y se reindexan."""

    def __init__(self):
        self.docs: dict[str, NoteDoc] = {}
        self.pins: dict[str, dict[int, int]] = {}

    def pin(self, note_id: str, ks: list[int], ids: list[int]) -> None:
        """Las casillas recién escritas en las posiciones ks son estas filas."""
        self.pins.setdefault(note_id, {}).update(dict(zip(ks, ids)))

    def get(self, note_id: str) -> NoteDoc:
        if note_id not in self.docs:
            self.docs[note_id] = NoteDoc(_note_file(note_id))
        return self.docs[note_id]

    def task(self, row) -> dict:
        try:
            return self.get(row["note_id"]).task(row["note_index"], row["note_task"])
        except TaskMissing:
            raise HTTPException(status_code=409, detail="La nota ha cambiado: recarga la lista")

    def save(self) -> None:
        for note_id, doc in self.docs.items():
            snapshot_version(note_id)
            doc.save()
        with get_db() as conn:
            for note_id, doc in self.docs.items():
                sync_note_items(conn, note_id, doc.text(), self.pins.get(note_id))
        sync_notes_to_db()  # caché de las notas (vuelve a sincronizar sus casillas: ya cuadran)


def _single_line(text: str) -> tuple[str, str]:
    """Una casilla es una línea: el resto del texto pasa a las notas del elemento."""
    lines = [ln.strip() for ln in clean_text(text).splitlines()]
    first = next((ln for ln in lines if ln), "")
    rest = "\n".join(lines[lines.index(first) + 1:]).strip() if first else ""
    return first, rest


# ─────────────────────────────────────────────
# Reglas y orden
# ─────────────────────────────────────────────

def move_error(item, n_children: int, target: str, parent, note_id: str | None) -> str | None:
    if target not in TARGETS:
        return "Destino no válido"
    if target == "nota" and not note_id:
        return "Falta la nota de destino"
    new_type = TARGET_TYPE[target]
    if parent is not None:
        if parent["id"] == item["id"]:
            return "No se puede meter dentro de sí mismo"
        if parent["parent_id"] is not None:
            return "Solo hay un nivel de pasos"
        if n_children:
            return "Tiene pasos: no puede pasar a ser paso de otro"
        if item_type(parent) != item_type(item):
            if "rutina" in (item_type(parent), item_type(item)):
                return "Una rutina solo tiene rutinas como pasos"
            return "Una subtarea no puede pasar a ser subidea" if item_type(item) == "tarea" else "Una subidea no puede pasar a ser subtarea"
        return None
    if new_type != item_type(item) and n_children:
        return f"Tiene pasos: no se puede convertir en {new_type}"
    return None


def _siblings(conn, target: str, parent_id: int | None, exclude: int | None = None) -> list[int]:
    if parent_id is not None:
        rows = conn.execute("SELECT id FROM inbox WHERE parent_id=? AND id IS NOT ? ORDER BY sort_order DESC, created_at DESC",
                            (parent_id, exclude)).fetchall()
    else:
        rows = conn.execute("SELECT id FROM inbox WHERE parent_id IS NULL AND note_task IS NULL AND item_type=? AND id IS NOT ? "
                            "ORDER BY sort_order DESC, created_at DESC", (TYPE_DB[TARGET_TYPE[target]], exclude)).fetchall()
    return [r["id"] for r in rows]


def _place(conn, item_id: int, target: str, parent_id: int | None, before_id: int | None, top: bool = False) -> None:
    """Reescribe posiciones enteras de la lista (Inbox, Ideas o pasos de un elemento)."""
    ids = _siblings(conn, target, parent_id, exclude=item_id)
    if before_id in ids:
        ids.insert(ids.index(before_id), item_id)
    elif top:
        ids.insert(0, item_id)
    else:
        ids.append(item_id)
    n = len(ids)
    for pos, sid in enumerate(ids):
        conn.execute("UPDATE inbox SET sort_order=? WHERE id=?", (float(n - pos), sid))


# ─────────────────────────────────────────────
# Operaciones
# ─────────────────────────────────────────────

def create(data: ItemIn) -> int:
    with get_db() as conn:
        parent = _get(conn, data.parent_id) if data.parent_id is not None else None
    if parent is not None and parent["parent_id"] is not None:
        raise HTTPException(status_code=422, detail="Solo hay un nivel de pasos")
    type_ = item_type(parent) if parent is not None else data.type   # un paso es del tipo de su padre
    text_in, duration = data.text, data.duration_min
    if parent is not None and type_ == "rutina" and duration is None:  # «Ducha 10 min» → paso de 10 min
        text_in, duration = routines.split_duration(data.text)
    note_id = parent["note_id"] if parent is not None and origin(parent) == "nota" else (None if parent is not None else data.note_id)
    category = (data.category or "").strip() or None

    if note_id:  # casilla nueva en la nota
        if type_ != "tarea":
            raise HTTPException(status_code=422, detail="En una nota solo hay tareas")
        text, rest = _single_line(data.text)
        if not text:
            raise HTTPException(status_code=422, detail="Falta el texto")
        docs = Docs()
        doc = docs.get(note_id)
        at, indent = doc.anchor(parent=docs.task(parent) if parent is not None else None)
        ks = doc.insert(at, [task_line(text)], indent, base=0)
        with get_db() as conn:
            cur = conn.execute("INSERT INTO inbox (content, item_type, status, note_id, note_task, priority, due_date, details) "
                               "VALUES (?, 'tarea', 'pending', ?, ?, ?, ?, ?)",
                               (text, note_id, text, data.priority, data.due_date, "\n\n".join(x for x in (rest, data.details) if x) or None))
            new_id = cur.lastrowid
        docs.pin(note_id, ks, [new_id])
        docs.save()
        return new_id

    target = TYPE_TARGET[type_]
    if parent is not None and type_ == "rutina" and data.due_time:
        with get_db() as conn:
            routines.ensure_free(conn, {"id": None, "item_type": "rutina", "parent_id": data.parent_id, "content": text_in,
                                        "due_time": data.due_time, "duration_min": duration, "repeat": None})
    # Una rutina se repite (cada día si no se dice otra cosa); sus pasos siguen su regla
    repeat = (data.repeat or {"freq": "daily"}) if type_ == "rutina" and parent is None else None
    with get_db() as conn:
        cur = conn.execute("INSERT INTO inbox (content, item_type, parent_id, priority, category, due_date, details, due_time, "
                           "duration_min, repeat, reminder_min) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (text_in.strip(), TYPE_DB[type_], data.parent_id, data.priority, category,
                            None if type_ == "rutina" else data.due_date, data.details, data.due_time, duration or None,
                            json.dumps(repeat) if repeat else None, data.reminder_min))
        new_id = cur.lastrowid
        routines.log(conn, _get(conn, new_id), "created")
        # Lo nuevo arriba del todo; un paso nuevo, al final de los pasos
        _place(conn, new_id, target, data.parent_id, None, top=parent is None)
    return new_id


def set_done(item_id: int, done: bool, day: str | None = None) -> None:
    with get_db() as conn:
        row = _get(conn, item_id)
        if item_type(row) == "rutina":  # una rutina (o un paso suyo) se marca por días (hoy, si no se dice otro)
            routines.check_with_steps(conn, row, date.fromisoformat(day) if day else date.today(), done)
            return
        if (row["status"] == "processed") != done and origin(row) != "nota":  # las de notas las anota la sincronía del .md
            routines.log(conn, row, "done" if done else "reopen")
    if origin(row) == "nota":
        docs = Docs()
        t = docs.task(row)
        if t["done"] != done:
            docs.get(row["note_id"]).set_done(t, done)
            docs.pin(row["note_id"], [t["k"]], [item_id])
            docs.save()
        return
    with get_db() as conn:
        conn.execute("UPDATE inbox SET status=?, content=? WHERE id=?", ("processed" if done else "pending", clean_text(row["content"]), item_id))


def update(item_id: int, data: ItemPatch) -> None:
    with get_db() as conn:
        row = _get(conn, item_id)
    is_note = origin(row) == "nota"
    if data.type is not None and data.type != item_type(row):
        if row["parent_id"] is not None:
            raise HTTPException(status_code=422, detail="Un paso tiene siempre el tipo de su elemento")
        move(item_id, MoveIn(target=TYPE_TARGET[data.type]))
        with get_db() as conn:
            row = _get(conn, item_id)
        is_note = False
    if any(v is not None for v in (data.due_time, data.duration_min, data.step_days, data.repeat)):
        with get_db() as conn:  # antes de escribir nada: lo que choca no se guarda a medias
            routines.ensure_free(conn, row, due_time=data.due_time, duration_min=data.duration_min,
                                 step_days=data.step_days, repeat=data.repeat)
    if data.category is not None and is_note and data.category.strip():
        raise HTTPException(status_code=422, detail="Una tarea de una nota lleva la categoría de su nota")
    if data.text is not None:
        if is_note:
            text, rest = _single_line(data.text)
            if not text:
                raise HTTPException(status_code=422, detail="Falta el texto")
            docs = Docs()
            t = docs.task(row)
            docs.get(row["note_id"]).set_text(t, text)
            docs.pin(row["note_id"], [t["k"]], [item_id])
            with get_db() as conn:
                conn.execute("UPDATE inbox SET content=?, note_task=? WHERE id=?", (text, text, item_id))
                if rest:
                    conn.execute("UPDATE inbox SET details=TRIM(COALESCE(details, '') || char(10) || char(10) || ?) WHERE id=?", (rest, item_id))
            docs.save()
        else:
            with get_db() as conn:
                conn.execute("UPDATE inbox SET content=? WHERE id=?", (data.text.strip(), item_id))
    with get_db() as conn:
        for field in ("priority", "category", "due_date", "details", "due_time"):
            value = getattr(data, field)
            if value is not None:
                conn.execute(f"UPDATE inbox SET {field}=? WHERE id=?", ((value.strip() if isinstance(value, str) else value) or None, item_id))
        if data.duration_min is not None:
            conn.execute("UPDATE inbox SET duration_min=? WHERE id=?", (data.duration_min or None, item_id))
        if data.reminder_min is not None:
            conn.execute("UPDATE inbox SET reminder_min=? WHERE id=?", (None if data.reminder_min < 0 else data.reminder_min, item_id))
        if data.repeat is not None:
            cur = _get(conn, item_id)
            if item_type(cur) != "rutina":
                raise HTTPException(status_code=422, detail="Solo una rutina se repite")
            if cur["parent_id"] is not None:
                raise HTTPException(status_code=422, detail="Un paso sigue los días de su rutina: dale días propios con step_days")
            conn.execute("UPDATE inbox SET repeat=? WHERE id=?", (json.dumps(data.repeat), item_id))
    if data.step_days is not None:
        with get_db() as conn:
            cur = _get(conn, item_id)
            if item_type(cur) != "rutina" or cur["parent_id"] is None:
                raise HTTPException(status_code=422, detail="Solo un paso de una rutina tiene días propios")
            days = sorted({d for d in data.step_days if 0 <= d <= 6})
            conn.execute("UPDATE inbox SET repeat=? WHERE id=?",
                         (json.dumps({"freq": "weekly", "days": days}) if days and len(days) < 7 else None, item_id))
    if data.routine_step is not None:
        with get_db() as conn:
            cur = _get(conn, item_id)
            if item_type(cur) == "rutina":
                raise HTTPException(status_code=422, detail="Una rutina no se asocia a otra: sus bloques son sus pasos")
            if data.routine_step:
                target = conn.execute("SELECT item_type FROM inbox WHERE id=?", (data.routine_step,)).fetchone()
                if not target or target["item_type"] != "rutina":
                    raise HTTPException(status_code=422, detail="Solo se asocia a una rutina o a uno de sus pasos")
            conn.execute("UPDATE inbox SET routine_step=? WHERE id=?", (data.routine_step or None, item_id))
    if data.done is not None:
        set_done(item_id, data.done, data.day or None)


def move(item_id: int, data: MoveIn) -> None:
    """Reordenar, anidar, sacar de un padre o cambiar de grupo (Inbox, una nota, Ideas)."""
    with get_db() as conn:
        item = _get(conn, item_id)
        kids = _children(conn, item_id)
        parent = _get(conn, data.parent_id) if data.parent_id is not None else None
        before = conn.execute("SELECT * FROM inbox WHERE id=?", (data.before_id,)).fetchone() if data.before_id is not None else None
    if parent is not None:  # el destino lo da el padre
        target, note_id = origin(parent), parent["note_id"] if origin(parent) == "nota" else None
    else:
        target, note_id = data.target or origin(item), data.note_id if (data.target or origin(item)) == "nota" else None
        if target == "nota" and not note_id and origin(item) == "nota":
            note_id = item["note_id"]
    error = move_error(item, len(kids), target, parent, note_id)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if before is not None and (before["id"] == item_id or before["parent_id"] != (parent["id"] if parent is not None else None)
                               or origin(before) != target or (target == "nota" and before["note_id"] != note_id)):
        raise HTTPException(status_code=422, detail="El destino no está en esa lista")
    new_type = TARGET_TYPE[target]
    src_note = item["note_id"] if origin(item) == "nota" else None

    docs = Docs()
    block = None
    if src_note:
        src_t = docs.task(item)
        if target == "nota" and note_id == src_note:
            # misma nota: el destino se calcula antes de quitar las líneas
            doc = docs.get(note_id)
            at, indent = doc.anchor(before=docs.task(before) if before is not None else None,
                                    parent=docs.task(parent) if parent is not None else None)
            a, b = doc.block(src_t)
            if a < at < b:
                raise HTTPException(status_code=422, detail="No se puede meter dentro de sí mismo")
            _, block = doc.take(src_t)
            docs.pin(note_id, doc.insert(at - (b - a) if at >= b else at, block, indent), [item_id] + [k["id"] for k in kids])
            block = None
        else:
            _, block = docs.get(src_note).take(src_t)
    if target == "nota" and (src_note != note_id):
        doc = docs.get(note_id)
        at, indent = doc.anchor(before=docs.task(before) if before is not None else None,
                                parent=docs.task(parent) if parent is not None else None)
        if block is None:  # viene del Inbox o de Ideas: sus pasos van debajo, sangrados
            lines = [task_line(_single_line(item["content"])[0], item["status"] == "processed")]
            kept = [k for k in kids if _single_line(k["content"])[0]]
            lines += [INDENT + task_line(_single_line(k["content"])[0], k["status"] == "processed") for k in kept]
            docs.pin(note_id, doc.insert(at, lines, indent, base=0), [item_id] + [k["id"] for k in kept])
        else:
            docs.pin(note_id, doc.insert(at, block, indent), [item_id] + [k["id"] for k in kids])

    with get_db() as conn:
        # Filas: el .md ya dice dónde está cada casilla; aquí, a qué grupo pertenecen ahora
        if target == "nota":
            text, rest = _single_line(item["content"])
            conn.execute("UPDATE inbox SET note_id=?, note_task=?, content=?, item_type='tarea', category=NULL, parent_id=?, "
                         "details=COALESCE(details, ?) WHERE id=?",
                         (note_id, text, text, parent["id"] if parent is not None else None, rest or None, item_id))
            for k in kids:
                ktext = _single_line(k["content"])[0]
                conn.execute("UPDATE inbox SET note_id=?, note_task=?, content=?, item_type='tarea' WHERE id=?", (note_id, ktext, ktext, k["id"]))
        else:
            if src_note:
                conn.execute("UPDATE inbox SET note_id=NULL, note_task=NULL, note_index=NULL WHERE id=? OR parent_id=?", (item_id, item_id))
            conn.execute("UPDATE inbox SET item_type=?, parent_id=? WHERE id=?",
                         (TYPE_DB[new_type], parent["id"] if parent is not None else None, item_id))
            if new_type == "rutina" and parent is None:  # una rutina nueva se repite cada día (sus pasos siguen la suya)
                conn.execute("UPDATE inbox SET repeat=COALESCE(repeat, ?), due_date=NULL, status='pending' WHERE id=?",
                             (json.dumps({"freq": "daily"}), item_id))
            _place(conn, item_id, target, parent["id"] if parent is not None else None, data.before_id)
    if docs.docs:
        docs.save()


def _subtree(conn, ids: list[int]) -> list:
    rows, seen = [], set()
    for i in ids:
        for r in [_get(conn, i)] + _children(conn, i):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
    return rows


def remove(ids: list[int]) -> str:
    """Borra (con sus pasos) y devuelve un token para deshacer. Las casillas se quitan de su nota."""
    with get_db() as conn:
        rows = _subtree(conn, ids)
    chosen = {r["id"] for r in rows}
    tops = [r for r in rows if r["id"] in ids and r["parent_id"] not in chosen]
    docs, blocks = Docs(), []
    for r in sorted((r for r in tops if origin(r) == "nota"), key=lambda r: (r["note_id"], -(r["note_index"] or 0))):
        at, lines = docs.get(r["note_id"]).take(docs.task(r))
        blocks.append({"note_id": r["note_id"], "line": at, "lines": lines})
    with get_db() as conn:
        title = clean_text(tops[0]["content"]).split("\n")[0] if len(tops) == 1 else f"{len(tops)} tareas e ideas"
        token = undo.save(conn, "items", {"rows": undo.rows_to_dicts(rows), "blocks": blocks}, title=title, count=len(tops))
        for r in rows:
            conn.execute("DELETE FROM inbox WHERE id=?", (r["id"],))
        # las tareas asociadas a una rutina (o paso) que se borra quedan sueltas
        conn.execute(f"UPDATE inbox SET routine_step=NULL WHERE routine_step IN ({','.join('?' * len(rows))})", [r["id"] for r in rows])
    if docs.docs:
        docs.save()
    return token


def restore(token: str) -> int:
    with get_db() as conn:
        found = undo.pop(conn, token, "items")
        if not found:
            raise HTTPException(status_code=404, detail="Ya no se puede deshacer")
        payload = found[1]
        # Padres antes que pasos (la clave foránea lo exige)
        rows = sorted(payload["rows"], key=lambda r: r["parent_id"] is not None)
        n = undo.insert_rows(conn, "inbox", rows)
        rebuild_links(conn)  # los marcadores [[tarea:N]] de las notas vuelven a apuntar a ellas
    docs = Docs()
    for b in sorted(payload["blocks"], key=lambda b: (b["note_id"], b["line"])):
        try:
            doc = docs.get(b["note_id"])
        except HTTPException:
            continue  # la nota ya no está: las filas quedan, la sincronía decidirá
        doc.insert(min(b["line"], len(doc.lines)), b["lines"], 0, base=0)
    if docs.docs:
        docs.save()
    return n


BULK_ACTIONS = ("done", "reopen", "delete", "category", "priority", "move")


def bulk(data: BulkIn) -> dict:
    """Varias a la vez. Lo que una regla no permite se salta y se cuenta en errors."""
    if data.action not in BULK_ACTIONS:
        raise HTTPException(status_code=422, detail="Acción no válida")
    ids = list(dict.fromkeys(data.ids))
    if data.action == "priority" and data.value and data.value not in PRIORITIES:
        raise HTTPException(status_code=422, detail="La prioridad es alta, media o baja")
    if data.action == "delete":
        return {"undo": remove(ids), "count": len(ids), "errors": []}
    with get_db() as conn:
        rows = {r["id"]: r for r in conn.execute(f"SELECT * FROM inbox WHERE id IN ({','.join('?' * len(ids))})", ids)}
    errors, done = [], 0
    for i in ids:
        r = rows.get(i)
        if r is None:
            continue
        try:
            if data.action in ("done", "reopen"):
                set_done(i, data.action == "done")
            elif data.action == "category":
                if origin(r) == "nota":
                    raise HTTPException(status_code=422, detail="Una tarea de una nota lleva la categoría de su nota")
                update(i, ItemPatch(category=data.value or ""))
            elif data.action == "priority":
                update(i, ItemPatch(priority=data.value or ""))
            elif data.action == "move":
                if r["parent_id"] in rows:
                    continue  # va con su padre
                move(i, MoveIn(target=data.target, note_id=data.note_id))
            done += 1
        except HTTPException as e:
            errors.append({"id": i, "detail": e.detail})
    return {"count": done, "errors": errors}


def _unique_note_id(base: str) -> str:
    candidate, n = base, 2
    while os.path.exists(note_path(candidate)):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def to_note(item_id: int, data: ToNoteIn) -> str:
    """Pasa un elemento a una nota nueva o existente. Una tarea se mueve a la nota como
    casilla (con sus pasos); una idea queda como texto de la nota y se marca hecha."""
    with get_db() as conn:
        item = _get(conn, item_id)
        kids = _children(conn, item_id)
    text = clean_text(item["content"])
    if item["parent_id"] is not None:
        raise HTTPException(status_code=422, detail="Un paso va con su elemento: convierte el elemento entero")
    is_task = item_type(item) == "tarea"
    if data.note_id:
        note_id = data.note_id
        if not is_task:
            doc = NoteDoc(_note_file(note_id))
            doc.insert(len(doc.lines), [""] + text.splitlines() + [f"- {clean_text(k['content'])}" for k in kids], 0, base=0)
            snapshot_version(note_id)
            doc.save()
    else:
        title = (data.title or text.splitlines()[0])[:MAX_TITLE].strip()
        if not title:
            raise HTTPException(status_code=422, detail="Falta el título")
        note_id = _unique_note_id(note_slug(title[:180]))
        body = f"# {title}\n\n" + ("" if is_task else f"{text}\n\n" + "".join(f"- {clean_text(k['content'])}\n" for k in kids))
        post = frontmatter.Post(body)
        post["title"], post["category"], post["category_id"] = title, data.category.strip() or "Inbox", None
        post["status"], post["tags"], post["encrypted"] = "por-escribir", [], False
        atomic_write(note_path(note_id), frontmatter.dumps(post) + "\n")
    sync_notes_to_db()
    if is_task:
        move(item_id, MoveIn(target="nota", note_id=note_id))
    else:
        with get_db() as conn:
            conn.execute("UPDATE inbox SET status='processed', note_id=? WHERE id=? OR parent_id=?", (note_id, item_id, item_id))
    with get_db() as conn:
        row = conn.execute("SELECT category, status FROM notes WHERE id=?", (note_id,)).fetchone()
    if row and row["status"] != "indice":
        try:
            update_index_for_area(split_category_path(row["category"])[0])
        except Exception:
            log.exception("No se pudo actualizar el índice tras convertir")
    return note_id


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────

@router.get("")
def api_list():
    return list_items()


@router.get("/counts")
def api_counts():
    return counts()


@router.post("")
def api_create(data: ItemIn):
    return {"status": "success", "id": create(data)}


@router.post("/bulk")
def api_bulk(data: BulkIn):
    return {"status": "success", **bulk(data)}


@router.post("/undo")
def api_undo(data: UndoIn):
    return {"status": "success", "restored": restore(data.token)}


@router.patch("/{item_id}")
def api_update(item_id: int, data: ItemPatch):
    update(item_id, data)
    return {"status": "success"}


@router.post("/{item_id}/move")
def api_move(item_id: int, data: MoveIn):
    move(item_id, data)
    return {"status": "success"}


@router.delete("/{item_id}")
def api_delete(item_id: int):
    return {"status": "success", "undo": remove([item_id])}


@router.post("/{item_id}/to-note")
def api_to_note(item_id: int, data: ToNoteIn):
    return {"status": "success", "note_id": to_note(item_id, data)}
