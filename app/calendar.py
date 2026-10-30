"""
Calendario unificado del Panel.

Una sola fuente de verdad por cosa:
  - **Eventos** (`events`): los del Panel y los que llegan de iCloud o del ESP32 (estudio/calendar_sync.py).
    Hora local de Madrid: «AAAA-MM-DDTHH:MM»; los de todo el día, «AAAA-MM-DD» con fin exclusivo.
  - **Tareas con fecha** (inbox.due_date [+ due_time + duration_min]): sin hora se ven todo el día; con
    hora son un **bloque de tiempo**. Mover o estirar el bloque cambia la tarea (PATCH /api/items) y
    cambiar la fecha de la tarea mueve el bloque: es el mismo dato.
  - **Rutinas** (app/routines.py): se expanden en cada día que tocan; marcarlas desde el calendario
    es marcar ese día.

GET /api/calendar?from=&to= devuelve todo junto con el mismo formato (`entries`).
"""
import json
import secrets
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from app import routines
from app.database import get_db
from app.items import clean_text, item_type, origin

TZ = ZoneInfo("Europe/Madrid")
KINDS = ("evento", "examen", "entrega", "bloque")
router = APIRouter(prefix="/api")


# ─────────────────────────────────────────────
# Fechas
# ─────────────────────────────────────────────

def parse_when(v: str) -> tuple[date, str | None]:
    """«AAAA-MM-DD» o «AAAA-MM-DDTHH:MM» → (fecha, «HH:MM» o None)."""
    try:
        if "T" in v:
            dt = datetime.fromisoformat(v[:16])
            return dt.date(), dt.strftime("%H:%M")
        return date.fromisoformat(v[:10]), None
    except ValueError:
        raise ValueError("Fecha no válida (AAAA-MM-DD o AAAA-MM-DDTHH:MM)")


def new_uid() -> str:
    return f"{int(time.time())}-{secrets.token_hex(6)}@panel"


def _clip(v: str | None) -> str | None:
    return v[:16] if v else v


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: str = Field(min_length=10, max_length=16)
    end: str | None = Field(default=None, max_length=16)
    all_day: bool = False
    kind: str = Field(default="evento", max_length=10)
    notes: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=300)
    reminder_min: int | None = Field(default=None, ge=0, le=10080)

    @field_validator("start", "end")
    @classmethod
    def v_when(cls, v):
        if v is None:
            return v
        parse_when(v)
        return v[:16]

    @field_validator("kind")
    @classmethod
    def v_kind(cls, v):
        if v not in KINDS:
            raise ValueError("Tipo: evento, examen, entrega o bloque")
        return v


class EventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    start: str | None = Field(default=None, min_length=10, max_length=16)
    end: str | None = Field(default=None, max_length=16)
    all_day: bool | None = None
    kind: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=300)
    reminder_min: int | None = Field(default=None, ge=-1, le=10080)

    @field_validator("start", "end")
    @classmethod
    def v_when(cls, v):
        if v in (None, ""):
            return v
        parse_when(v)
        return v[:16]

    @field_validator("kind")
    @classmethod
    def v_kind(cls, v):
        if v is not None and v not in KINDS:
            raise ValueError("Tipo: evento, examen, entrega o bloque")
        return v


def _normalize(start: str, end: str | None, all_day: bool) -> tuple[str, str]:
    """Todo el día: fechas (fin exclusivo). Con hora: fin posterior al inicio (1 h por defecto)."""
    d0, t0 = parse_when(start)
    if all_day or t0 is None:
        d1 = parse_when(end)[0] if end else d0 + timedelta(days=1)
        if d1 <= d0:
            d1 = d0 + timedelta(days=1)
        return d0.isoformat(), d1.isoformat()
    s = datetime.fromisoformat(f"{d0.isoformat()}T{t0}")
    e = datetime.fromisoformat(end[:16]) if end and "T" in end else s + timedelta(hours=1)
    if e <= s:
        e = s + timedelta(minutes=30)
    return s.strftime("%Y-%m-%dT%H:%M"), e.strftime("%Y-%m-%dT%H:%M")


def event_out(r) -> dict:
    return {"key": f"e{r['id']}", "kind": "event", "id": r["id"], "uid": r["uid"], "title": r["title"],
            "start": r["start"], "end": r["end"], "all_day": bool(r["all_day"]), "type": r["kind"],
            "notes": r["notes"], "location": r["location"], "reminder_min": r["reminder_min"],
            "source": r["source"], "done": False, "editable": True}


# ─────────────────────────────────────────────
# Eventos
# ─────────────────────────────────────────────

def create_event(data: EventIn, uid: str | None = None, source: str = "panel") -> int:
    start, end = _normalize(data.start, data.end, data.all_day)
    all_day = "T" not in start
    with get_db() as conn:
        cur = conn.execute("INSERT INTO events (uid, title, start, end, all_day, kind, notes, location, reminder_min, source, updated_at) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (uid or new_uid(), data.title.strip(), start, end, int(all_day), data.kind, data.notes,
                            data.location, data.reminder_min, source, time.time()))
        return cur.lastrowid


def get_event(conn, event_id: int):
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return row


def update_event(event_id: int, data: EventPatch) -> None:
    with get_db() as conn:
        row = get_event(conn, event_id)
        all_day = bool(row["all_day"]) if data.all_day is None else data.all_day
        start = data.start or row["start"]
        end = row["end"] if data.end is None else (data.end or None)
        if data.start and data.end is None:  # mover sin decir el fin: conserva la duración
            d0, t0 = parse_when(row["start"])
            n0, nt = parse_when(data.start)
            if row["end"]:
                if t0 and nt:
                    dur = datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])
                    end = (datetime.fromisoformat(data.start) + dur).strftime("%Y-%m-%dT%H:%M")
                elif not t0 and not nt:
                    end = (n0 + (parse_when(row["end"])[0] - d0)).isoformat()
                else:
                    end = None
        # Cambiar «todo el día» sin dar un inicio nuevo (p. ej. arrastrar): 09:00 o el día entero.
        # Si el inicio viene con la forma correcta (el editor), se respeta.
        if data.all_day is not None and data.all_day != bool(row["all_day"]) and (data.start is None or ("T" in data.start) == all_day):
            d0 = parse_when(start)[0]
            start, end = (d0.isoformat(), None) if all_day else (f"{d0.isoformat()}T09:00", None)
        start, end = _normalize(start, end, all_day)
        conn.execute("UPDATE events SET start=?, end=?, all_day=?, updated_at=? WHERE id=?",
                     (start, end, int("T" not in start), time.time(), event_id))
        for field in ("title", "kind", "notes", "location"):
            v = getattr(data, field)
            if v is not None:
                conn.execute(f"UPDATE events SET {field}=? WHERE id=?", (v.strip() if field == "title" else (v or None), event_id))
        if data.reminder_min is not None:
            conn.execute("UPDATE events SET reminder_min=? WHERE id=?", (None if data.reminder_min < 0 else data.reminder_min, event_id))


def delete_event(event_id: int) -> str:
    """Borra el evento y devuelve el token de la papelera (app/trash.py) para recuperarlo."""
    from core import undo
    with get_db() as conn:
        row = get_event(conn, event_id)
        token = undo.save(conn, "event.delete", {"row": dict(row)}, title=row["title"], count=1)
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    return token


def restore_event(conn, payload: dict) -> int:
    from core import undo
    row = payload["row"]
    if conn.execute("SELECT 1 FROM events WHERE uid=?", (row["uid"],)).fetchone():
        return 0  # ya volvió (p. ej. lo trajo la sincronía): no se duplica
    return undo.insert_rows(conn, "events", [row])


# ─────────────────────────────────────────────
# Vista unificada
# ─────────────────────────────────────────────

def _days(d0: date, d1: date):
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


def entries(d0: date, d1: date) -> list[dict]:
    """Todo lo que cae entre d0 y d1 (ambos incluidos)."""
    out = []
    lo, hi = d0.isoformat(), (d1 + timedelta(days=1)).isoformat()
    with get_db() as conn:
        # El fin es exclusivo (un evento de todo el día del 24 acaba el «25»): solo entra si acaba después del rango
        for r in conn.execute("SELECT * FROM events WHERE start < ? AND ((end IS NULL AND start >= ?) OR end > ?) ORDER BY start", (hi, lo, lo)):
            out.append(event_out(r))
        # tareas e ideas con fecha (también las casillas de las notas), de primer nivel o pasos
        for r in conn.execute("SELECT * FROM inbox WHERE item_type != 'rutina' AND due_date >= ? AND due_date <= ?",
                              (lo, d1.isoformat())):
            out.append(task_entry(r))
        for r in conn.execute("SELECT * FROM inbox WHERE item_type='rutina' AND parent_id IS NULL").fetchall():
            rule = routines.parse(r["repeat"])
            done = routines.checks(conn, r["id"], since=d0)
            since = routines.created_day(r) - timedelta(days=36500)  # una rutina vale también hacia atrás
            steps = [(s, routines.checks(conn, s["id"], since=d0)) for s in routines.steps_of(conn, r["id"])]
            for d in _days(d0, d1):
                if routines.occurs_on(rule, d, since):
                    e = routine_entry(r, d, d.isoformat() in done, rule, steps)
                    timed_steps = [p for p in e["steps"] if p["at"]]
                    if timed_steps:  # con horario: cada bloque en su hora (es lo que se ve en /rutinas)
                        out.extend(step_entry(r, p, d, e) for p in e["steps"])
                    else:
                        out.append(e)
    return out


def task_entry(r) -> dict:
    timed = bool(r["due_time"])
    start = f"{r['due_date']}T{r['due_time']}" if timed else r["due_date"]
    end = None
    if timed:
        end = (datetime.fromisoformat(start) + timedelta(minutes=r["duration_min"] or 60)).strftime("%Y-%m-%dT%H:%M")
    return {"key": f"t{r['id']}", "kind": "task", "id": r["id"], "item_id": r["id"], "title": clean_text(r["content"]).split("\n")[0],
            "start": start, "end": end, "all_day": not timed, "type": item_type(r), "origin": origin(r),
            "done": r["status"] == "processed", "duration_min": r["duration_min"], "note_id": r["note_id"],
            "reminder_min": r["reminder_min"], "editable": True}


def routine_entry(r, d: date, done: bool, rule: dict, steps: list | None = None) -> dict:
    timed = bool(r["due_time"])
    start = f"{d.isoformat()}T{r['due_time']}" if timed else d.isoformat()
    plan = routines.schedule(r["due_time"], [{"id": s["id"], "title": clean_text(s["content"]).split("\n")[0], "due_time": s["due_time"],
                                              "duration_min": s["duration_min"], "done": d.isoformat() in ch}
                                             for s, ch in (steps or []) if routines.step_on(s, d)])
    # sin duración propia, la rutina dura hasta que acaba su último paso (horas fijas incluidas)
    end = None
    if timed:
        last = plan[-1] if plan else None
        if not r["duration_min"] and last and (last["end"] or last["at"]) and (last["end"] or last["at"]) > r["due_time"]:
            end = f"{d.isoformat()}T{last['end'] or last['at']}"
        else:
            end = (datetime.fromisoformat(start) + timedelta(minutes=r["duration_min"] or sum(p["duration_min"] or 0 for p in plan) or 30)).strftime("%Y-%m-%dT%H:%M")
    return {"key": f"r{r['id']}@{d.isoformat()}", "kind": "routine", "id": r["id"], "item_id": r["id"],
            "title": clean_text(r["content"]).split("\n")[0], "start": start, "end": end, "all_day": not timed,
            "type": "rutina", "done": done, "day": d.isoformat(), "repeat_text": routines.describe(rule), "steps": plan,
            "reminder_min": r["reminder_min"], "editable": True}


def step_entry(r, p: dict, d: date, routine: dict) -> dict:
    """Un bloque de una rutina como entrada propia del calendario (marcar = hecho ese día; moverlo le pone hora fija)."""
    base = {"key": f"r{p['id']}@{d.isoformat()}", "kind": "routine", "id": p["id"], "item_id": p["id"], "title": p["title"],
            "type": "rutina", "done": p["done"], "day": d.isoformat(), "repeat_text": routine["repeat_text"],
            "routine_id": r["id"], "routine_title": routine["title"], "reminder_min": None, "editable": True, "step": True}
    if not p["at"]:
        return {**base, "start": d.isoformat(), "end": None, "all_day": True}
    start = datetime.fromisoformat(f"{d.isoformat()}T{p['at']}")
    end = start + timedelta(minutes=p["duration_min"] or 15)
    return {**base, "start": start.strftime("%Y-%m-%dT%H:%M"), "end": end.strftime("%Y-%m-%dT%H:%M"), "all_day": False}


def _range(frm: str | None, to: str | None, default_days=7) -> tuple[date, date]:
    try:
        d0 = date.fromisoformat(frm) if frm else date.today()
        d1 = date.fromisoformat(to) if to else d0 + timedelta(days=default_days - 1)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fechas como AAAA-MM-DD")
    if d1 < d0 or (d1 - d0).days > 400:
        raise HTTPException(status_code=422, detail="Rango de fechas no válido (máximo 400 días)")
    return d0, d1


@router.get("/calendar/entries")
def api_entries(start: str | None = None, end: str | None = None):
    d0, d1 = _range(start, end)
    return {"from": d0.isoformat(), "to": d1.isoformat(), "entries": entries(d0, d1)}


@router.get("/calendar/agenda")
def api_agenda(days: int = 7, start: str | None = None):
    """Agenda de los próximos días (Waybar, extensión, Hoy): ordenada y sin hechos de días pasados."""
    days = max(1, min(days, 60))
    d0 = date.fromisoformat(start) if start else date.today()
    items = sorted(entries(d0, d0 + timedelta(days=days - 1)), key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))
    # tareas e ideas con fecha pasada sin hacer (la Waybar y su menú las ponen arriba)
    with get_db() as conn:
        overdue = [task_entry(r) for r in conn.execute(
            "SELECT * FROM inbox WHERE item_type != 'rutina' AND due_date < ? AND status != 'processed' ORDER BY due_date, due_time LIMIT 20",
            (date.today().isoformat(),))]
    return {"from": d0.isoformat(), "days": days, "now": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"), "entries": items, "overdue": overdue}


@router.post("/calendar/events")
def api_create_event(data: EventIn):
    return {"status": "success", "id": create_event(data)}


@router.post("/calendar/sync")
def api_sync_now():
    """Pide un ciclo de sincronía con iCloud y el ESP32 ya (estudio/calendar_sync.py)."""
    from estudio import calendar_sync
    calendar_sync.request_sync()
    return {"status": "success", "estado": calendar_sync.status()}


@router.get("/calendar/events/{event_id}")
def api_get_event(event_id: int):
    with get_db() as conn:
        return event_out(get_event(conn, event_id))


@router.patch("/calendar/events/{event_id}")
def api_update_event(event_id: int, data: EventPatch):
    update_event(event_id, data)
    return {"status": "success"}


@router.delete("/calendar/events/{event_id}")
def api_delete_event(event_id: int):
    return {"status": "success", "trash": delete_event(event_id)}


# ─────────────────────────────────────────────
# Rutinas: marcar un día, estadísticas
# ─────────────────────────────────────────────

class CheckIn(BaseModel):
    day: str | None = Field(default=None, max_length=10)
    done: bool = True


@router.post("/routines/{item_id}/check")
def api_check(item_id: int, data: CheckIn):
    from app.items import set_done
    set_done(item_id, data.done, data.day or date.today().isoformat())
    return {"status": "success"}


class SkipIn(BaseModel):
    day: str | None = Field(default=None, max_length=10)
    skip: bool = True


@router.post("/routines/{item_id}/skip")
def api_skip(item_id: int, data: SkipIn):
    """Saltar hoy un bloque de una rutina: cuenta como resuelto (la rutina puede completarse) pero queda
    anotado como saltado (item_log «skip»), no como hecho. skip=false lo deshace."""
    try:
        d = date.fromisoformat(data.day) if data.day else date.today()
    except ValueError:
        raise HTTPException(status_code=422, detail="El día va como AAAA-MM-DD")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=? AND item_type='rutina' AND parent_id IS NOT NULL", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ese bloque no existe")
        routines.check_with_steps(conn, row, d, data.skip)
        conn.execute("DELETE FROM item_log WHERE item_id=? AND day=? AND action='skip'", (item_id, d.isoformat()))
        if data.skip:
            routines.log(conn, row, "skip", d)
    return {"status": "success"}


@router.get("/routines/day")
def api_routines_day(date_: str | None = Query(default=None, alias="date")):
    """Las rutinas de un día como línea del tiempo: sus pasos de ese día con hora, hecho o no y las
    tareas asociadas (pendientes, o hechas ese día). Las que no tocan, aparte."""
    d = _range(date_, date_)[0]
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM inbox WHERE item_type='rutina' AND parent_id IS NULL ORDER BY COALESCE(due_time, '99:99'), sort_order DESC").fetchall()
        done_that_day = {r["item_id"] for r in conn.execute("SELECT item_id FROM item_log WHERE action='done' AND day=?", (d.isoformat(),))}
        skipped = {r["item_id"] for r in conn.execute("SELECT item_id FROM item_log WHERE action='skip' AND day=?", (d.isoformat(),))}
        attached = {}
        for t in conn.execute("SELECT * FROM inbox WHERE routine_step IS NOT NULL AND item_type != 'rutina' ORDER BY sort_order DESC"):
            if t["status"] != "processed" or t["id"] in done_that_day:
                attached.setdefault(t["routine_step"], []).append({"id": t["id"], "text": clean_text(t["content"]).split("\n")[0], "type": item_type(t),
                                                                   "done": t["status"] == "processed", "due_date": t["due_date"]})
        out, otros = [], []
        for r in rows:
            rule = routines.parse(r["repeat"])
            if not routines.occurs_on(rule, d, routines.created_day(r) - timedelta(days=36500)):
                otros.append({"id": r["id"], "title": clean_text(r["content"]).split("\n")[0], "repeat_text": routines.describe(rule)})
                continue
            done = routines.checks(conn, r["id"], since=d - timedelta(days=400))
            steps = []
            for s in routines.steps_of(conn, r["id"]):
                own = routines.step_rule(s)
                steps.append({"id": s["id"], "title": clean_text(s["content"]).split("\n")[0], "due_time": s["due_time"],
                              "duration_min": s["duration_min"], "on": routines.step_on(s, d),
                              "days": own["days"] if own else None, "days_text": routines.describe(own) if own else None,
                              "done": d.isoformat() in routines.checks(conn, s["id"], since=d), "tasks": attached.get(s["id"], [])})
                steps[-1]["skipped"] = steps[-1]["done"] and s["id"] in skipped
            plan = routines.schedule(r["due_time"], [x for x in steps if x["on"]])
            since = routines.created_day(r)
            if done:
                since = min(since, date.fromisoformat(min(done)))
            out.append({"id": r["id"], "title": clean_text(r["content"]).split("\n")[0], "due_time": r["due_time"],
                        "repeat": rule, "repeat_text": routines.describe(rule), "done": d.isoformat() in done,
                        "streak": routines.streak(rule, done, date.today(), since), "steps": plan,
                        "otros_dias": [x for x in steps if not x["on"]], "tasks": attached.get(r["id"], [])})
    return {"date": d.isoformat(), "weekday": d.weekday(), "today": date.today().isoformat(),
            "now": datetime.now(TZ).strftime("%H:%M"), "rutinas": out, "otras": otros}


@router.get("/routines/{item_id}/stats")
def api_routine_stats(item_id: int, weeks: int = 12):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM inbox WHERE id=? AND item_type='rutina'", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rutina no encontrada")
        from app.items import routine_info
        info = routine_info(conn, row)
        rule = routines.parse(row["repeat"])
        done = routines.checks(conn, item_id)
    since = min([routines.created_day(row)] + [date.fromisoformat(d) for d in done])
    info["heatmap"] = routines.heatmap(rule, done, date.today(), since, weeks=max(1, min(weeks, 53)))
    info["total"] = len(done)
    return info


# ─────────────────────────────────────────────
# Exportar (.ics) para cualquier calendario
# ─────────────────────────────────────────────

@router.get("/calendar/export.ics")
def api_export_ics():
    from icalendar import Calendar as ICalendar, Event as IEvent
    cal = ICalendar()
    cal.add("prodid", "-//Panel//Calendario//ES")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Panel")
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY start").fetchall()
    for r in rows:
        ev = IEvent()
        ev.add("uid", r["uid"])
        ev.add("summary", r["title"])
        if r["all_day"]:
            ev.add("dtstart", date.fromisoformat(r["start"]))
            ev.add("dtend", date.fromisoformat(r["end"]) if r["end"] else date.fromisoformat(r["start"]) + timedelta(days=1))
        else:
            ev.add("dtstart", datetime.fromisoformat(r["start"]).replace(tzinfo=TZ))
            ev.add("dtend", datetime.fromisoformat(r["end"] or r["start"]).replace(tzinfo=TZ))
        if r["notes"]:
            ev.add("description", r["notes"])
        if r["location"]:
            ev.add("location", r["location"])
        ev.add("categories", [r["kind"].upper()])
        ev.add("dtstamp", datetime.now(TZ))
        cal.add_component(ev)
    return Response(cal.to_ical(), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="panel.ics"'})


# ─────────────────────────────────────────────
# Plantillas de día: eventos, bloques y comidas de un día tipo
# ─────────────────────────────────────────────

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _semana_dia(d: date) -> tuple[str, str]:
    return (d - timedelta(days=d.weekday())).isoformat(), DIAS[d.weekday()]


class DayTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    day: str = Field(min_length=10, max_length=10)            # el día que se guarda como plantilla
    comidas: bool = True


class ApplyDayIn(BaseModel):
    day: str = Field(min_length=10, max_length=10)
    comidas_reemplazar: bool = False


def snapshot_day(d: date, with_meals: bool = True) -> dict:
    data = {"events": [], "comidas": {}}
    for e in entries(d, d):
        if e["kind"] == "event" and e["start"][:10] == d.isoformat():
            data["events"].append({"title": e["title"], "kind": e["type"], "all_day": e["all_day"],
                                   "start": None if e["all_day"] else e["start"][11:], "end": None if e["all_day"] else (e["end"] or "")[11:],
                                   "notes": e.get("notes")})
        elif e["kind"] == "task" and not e["all_day"]:  # bloque de una tarea: queda como bloque de tiempo
            data["events"].append({"title": e["title"], "kind": "bloque", "all_day": False, "start": e["start"][11:], "end": e["end"][11:]})
    if with_meals:
        from comidas.database import get_db as comidas_db
        semana, dia = _semana_dia(d)
        with comidas_db() as conn:
            for s in conn.execute("SELECT * FROM weekly_plan WHERE semana=? AND dia=?", (semana, dia)).fetchall():
                platos = []
                if s["meal_id"]:
                    platos.append({"meal_id": s["meal_id"], "gramos": s["gramos_racion"], "rol": s["rol"] if "rol" in s.keys() else None})
                platos += [{"meal_id": p["meal_id"], "gramos": p["gramos_racion"], "rol": p["rol"] if "rol" in p.keys() else None}
                           for p in conn.execute("SELECT * FROM plan_items WHERE plan_id=? ORDER BY orden, id", (s["id"],))]
                if platos:
                    data["comidas"][s["franja"]] = platos
    return data


def apply_day(data: dict, d: date, replace_meals: bool = False) -> dict:
    n_ev = 0
    for e in data.get("events", []):
        start = d.isoformat() if e["all_day"] else f"{d.isoformat()}T{e['start']}"
        end = None if e["all_day"] or not e.get("end") else f"{d.isoformat()}T{e['end']}"
        create_event(EventIn(title=e["title"], start=start, end=end, all_day=e["all_day"], kind=e.get("kind") or "evento", notes=e.get("notes")))
        n_ev += 1
    n_pl = 0
    if data.get("comidas"):
        from comidas.database import get_db as comidas_db
        from comidas.main import PlanSlotAdd, _slot_id, add_plato_to_slot
        semana, dia = _semana_dia(d)
        for franja, platos in data["comidas"].items():
            if replace_meals:
                with comidas_db() as conn:
                    pid = _slot_id(conn, semana, dia, franja)
                    conn.execute("DELETE FROM plan_items WHERE plan_id=?", (pid,))
                    conn.execute("UPDATE weekly_plan SET meal_id=NULL, gramos_racion=NULL, rol=NULL WHERE id=?", (pid,))
            for p in platos:
                try:
                    add_plato_to_slot(PlanSlotAdd(semana=semana, dia=dia, franja=franja, meal_id=p["meal_id"], gramos=p.get("gramos"), rol=p.get("rol")))
                    n_pl += 1
                except HTTPException:
                    continue  # plato o franja que ya no existen
    return {"eventos": n_ev, "platos": n_pl}


@router.get("/day-templates")
def api_day_templates():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM day_templates ORDER BY name").fetchall()
    out = []
    for r in rows:
        data = json.loads(r["data"] or "{}")
        out.append({"id": r["id"], "name": r["name"], "eventos": len(data.get("events", [])),
                    "comidas": sum(len(v) for v in data.get("comidas", {}).values()), "data": data})
    return {"plantillas": out}


@router.post("/day-templates")
def api_save_day_template(data: DayTemplateIn):
    try:
        d = date.fromisoformat(data.day)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida")
    snap = snapshot_day(d, data.comidas)
    if not snap["events"] and not snap["comidas"]:
        raise HTTPException(status_code=422, detail="Ese día no tiene eventos, bloques ni comidas que guardar")
    with get_db() as conn:
        new_id = conn.execute("INSERT INTO day_templates (name, data) VALUES (?, ?)", (data.name.strip(), json.dumps(snap))).lastrowid
    return {"status": "success", "id": new_id, "eventos": len(snap["events"]), "comidas": sum(len(v) for v in snap["comidas"].values())}


@router.post("/day-templates/{tid}/apply")
def api_apply_day_template(tid: int, data: ApplyDayIn):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM day_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    try:
        d = date.fromisoformat(data.day)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida")
    return {"status": "success", **apply_day(json.loads(row["data"]), d, data.comidas_reemplazar)}


@router.delete("/day-templates/{tid}")
def api_delete_day_template(tid: int):
    with get_db() as conn:
        conn.execute("DELETE FROM day_templates WHERE id=?", (tid,))
    return {"status": "success"}
