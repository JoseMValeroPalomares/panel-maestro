"""
Plantillas de rutina: una rutina con sus pasos (y la duración de cada uno) lista para crearse
con un clic. Hay unas cuantas de serie (BUILTIN, en el código) y las que guardes tú desde una
rutina que ya tengas (tabla `routine_templates`, migración 11).

    GET    /api/routine-templates              de serie + tuyas
    POST   /api/routine-templates              guardar una rutina como plantilla ({"item_id": N, "name": ...})
    DELETE /api/routine-templates/{id}         borrar una tuya
    POST   /api/routine-templates/apply        crear la rutina y sus pasos ({"key": "b:manana" | "u:3", ...}); cada
                                               paso se queda con su hora, y sin ella si choca con otro bloque

Formato de `data`: {"title", "due_time", "repeat", "steps": [{"title", "duration_min", "due_time"?, "days"?}]}
(`due_time` = hora del paso; sin ella, cuando acaba el anterior; `days` = sus días si no son los de la rutina, 0 = lunes).
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import routines
from app.database import get_db
from app.items import ItemIn, ItemPatch, _get, clean_text, create, item_type, update

router = APIRouter(prefix="/api")

_S = lambda title, m, at=None, days=None: {"title": title, "duration_min": m, **({"due_time": at} if at else {}), **({"days": days} if days else {})}  # noqa: E731
LV = [0, 1, 2, 3, 4]

BUILTIN = {
    # El día entero en bloques; la universidad solo de lunes a viernes y el gimnasio lunes, miércoles y viernes
    "dia": {"title": "Mi día", "icon": "sun", "due_time": "07:30", "repeat": {"freq": "daily"},
            "steps": [_S("Levantarme", 10), _S("Desayunar", 20), _S("Universidad", 330, "08:30", LV), _S("Tomar el sol", 20, "14:30"),
                      _S("Cocinar / comer", 60), _S("Leer / estudiar / tocar el piano / merendar", 150), _S("Gimnasio", 90, "19:00", [0, 2, 4])]},
    "manana": {"title": "Rutina de mañana", "icon": "sunrise", "due_time": "07:30", "repeat": {"freq": "daily"},
               "steps": [_S("Beber un vaso de agua", 2), _S("Hacer la cama", 3), _S("Ducha", 10), _S("Vestirse", 5),
                         _S("Desayunar", 15), _S("Mirar la agenda del día", 5)]},
    "noche": {"title": "Rutina de noche", "icon": "moon", "due_time": "23:00", "repeat": {"freq": "daily"},
              "steps": [_S("Recoger el escritorio", 5), _S("Preparar la ropa y la mochila", 5), _S("Revisar mañana en el calendario", 5),
                        _S("Lavarse los dientes", 5), _S("Leer sin pantallas", 20)]},
    "estudio": {"title": "Bloque de estudio", "icon": "graduation-cap", "due_time": "17:00", "repeat": {"freq": "weekly", "days": [0, 1, 2, 3, 4]},
                "steps": [_S("Preparar el material", 5), _S("Pomodoro 1", 25), _S("Descanso", 5), _S("Pomodoro 2", 25), _S("Descanso", 5),
                          _S("Pomodoro 3", 25), _S("Repasar flashcards", 10)]},
    "gimnasio": {"title": "Gimnasio", "icon": "dumbbell", "due_time": "19:00", "repeat": {"freq": "weekly", "days": [0, 2, 4]},
                 "steps": [_S("Calentamiento", 10), _S("Fuerza", 45), _S("Estiramientos", 10), _S("Ducha", 10)]},
    "limpieza": {"title": "Limpieza de la casa", "icon": "sparkles", "due_time": "10:00", "repeat": {"freq": "weekly", "days": [5]},
                 "steps": [_S("Cambiar las sábanas", 10), _S("Aspirar", 20), _S("Fregar el suelo", 20), _S("Limpiar el baño", 20),
                           _S("Sacar la basura", 5)]},
    "semanal": {"title": "Revisión semanal", "icon": "calendar-check", "due_time": "19:00", "repeat": {"freq": "weekly", "days": [6]},
                "steps": [_S("Vaciar el Inbox", 15), _S("Repasar la semana en el calendario", 10), _S("Planificar las comidas", 15),
                          _S("Elegir 3 objetivos para la semana", 10)]},
}


def _out(key: str, d: dict, builtin: bool, tid: int | None = None) -> dict:
    steps = d.get("steps") or []
    return {"key": key, "id": tid, "builtin": builtin, "title": d.get("title") or "Rutina", "icon": d.get("icon") or "repeat",
            "due_time": d.get("due_time"), "repeat": routines.parse(d.get("repeat")),
            "repeat_text": routines.describe(routines.parse(d.get("repeat"))),
            "steps": [{**x, "days_text": routines.describe({"freq": "weekly", "days": x["days"]}) if x.get("days") else None}
                      for x in routines.schedule(d.get("due_time"), steps)],
            "total_min": sum(s.get("duration_min") or 0 for s in steps)}


def all_templates() -> list[dict]:
    out = [_out(f"b:{k}", v, True) for k, v in BUILTIN.items()]
    with get_db() as conn:
        for r in conn.execute("SELECT * FROM routine_templates ORDER BY created_at DESC, id DESC"):
            try:
                data = json.loads(r["data"])
            except ValueError:
                continue
            out.insert(0, _out(f"u:{r['id']}", {**data, "title": r["name"]}, False, r["id"]))
    return out


def get_template(key: str) -> dict:
    for t in all_templates():
        if t["key"] == key:
            return t
    raise HTTPException(status_code=404, detail="Esa plantilla no existe")


class SaveIn(BaseModel):
    item_id: int
    name: str | None = Field(default=None, max_length=120)


class ApplyIn(BaseModel):
    key: str = Field(max_length=40)
    title: str | None = Field(default=None, max_length=300)
    due_time: str | None = Field(default=None, max_length=5)
    repeat: dict | None = None
    steps: list[dict] | None = None  # editados en el diálogo antes de crear


@router.get("/routine-templates")
def api_list():
    return {"plantillas": all_templates()}


@router.post("/routine-templates")
def api_save(data: SaveIn):
    with get_db() as conn:
        row = _get(conn, data.item_id)
        if item_type(row) != "rutina" or row["parent_id"] is not None:
            raise HTTPException(status_code=422, detail="Solo una rutina se guarda como plantilla")
        steps = []
        for s in sorted(routines.steps_of(conn, row["id"]), key=lambda x: x["due_time"] or "99:99"):
            own = routines.step_rule(s)
            steps.append({"title": clean_text(s["content"]).split("\n")[0], "duration_min": s["duration_min"],
                          **({"due_time": s["due_time"]} if s["due_time"] else {}), **({"days": own["days"]} if own else {})})
        name = (data.name or "").strip() or clean_text(row["content"]).split("\n")[0][:120]
        payload = {"due_time": row["due_time"], "repeat": routines.parse(row["repeat"]), "steps": steps}
        cur = conn.execute("INSERT INTO routine_templates (name, data) VALUES (?, ?)", (name, json.dumps(payload, ensure_ascii=False)))
    return {"status": "success", "id": cur.lastrowid, "key": f"u:{cur.lastrowid}"}


@router.delete("/routine-templates/{tid}")
def api_delete(tid: int):
    with get_db() as conn:
        if not conn.execute("DELETE FROM routine_templates WHERE id=?", (tid,)).rowcount:
            raise HTTPException(status_code=404, detail="Esa plantilla no existe")
    return {"status": "success"}


@router.post("/routine-templates/apply")
def api_apply(data: ApplyIn):
    t = get_template(data.key)
    steps = data.steps if data.steps is not None else t["steps"]
    try:
        repeat = routines.clean_repeat(data.repeat) if data.repeat else t["repeat"]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    due_time = (data.due_time if data.due_time is not None else t["due_time"]) or None
    rid = create(ItemIn(text=(data.title or t["title"]).strip() or t["title"], type="rutina", repeat=repeat, due_time=due_time))
    # los pasos se crean al final de la lista: en orden, el primero arriba. Primero sus días y luego la hora,
    # porque el choque depende de ellos; si «due_time» viene vacío (quitada en el diálogo), va sin hora
    sin_hora = []
    for s in routines.schedule(due_time, steps):
        title = str(s.get("title") or "").strip()[:300]
        if title:
            dur = s.get("duration_min")
            sid = create(ItemIn(text=title, parent_id=rid, duration_min=int(dur) if dur else None))
            if s.get("days"):
                update(sid, ItemPatch(step_days=[int(x) for x in s["days"]]))
            at = s["due_time"] if "due_time" in s else s["at"]
            if at:
                try:
                    update(sid, ItemPatch(due_time=at))
                except HTTPException as e:
                    if e.status_code != 409:
                        raise
                    sin_hora.append(title)
    return {"status": "success", "id": rid, "sin_hora": sin_hora}
