"""
Plantillas del Inbox (P-4): las tres clases (tablero, día y rutina) en un solo sitio.

Las de tablero de serie viven en el front (static/js/plantillas-catalogo.js: son dibujos); las de rutina de serie en
app/routine_templates.py y las de día de serie aquí (DIA). Las tuyas, cada clase en su tabla (board_templates,
day_templates, routine_templates). Borrar una tuya sigue yendo a la papelera por las rutas de siempre.

    GET    /api/day-templates/serie                 las de día de serie (las tuyas siguen en GET /api/day-templates)
    POST   /api/day-templates/aplicar               {"key": "b:clase" | "u:3", "day": "2026-11-20", "comidas_reemplazar"}
    PATCH  /api/plantillas/{clase}/{id}             renombrar / describir (y, en una rutina, sus pasos, hora y días)
    POST   /api/plantillas/{clase}/{id}/duplicar    una copia («… (copia)»)
    POST   /api/plantillas/{clase}/copiar           {"key": "b:…"}: una de serie (día o rutina) pasa a ser tuya para editarla

clase = tablero | dia | rutina. La descripción va dentro de `data` (sin migración).
"""

import json
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import routines
from app.calendar import apply_day
from app.database import get_db
from app.routine_templates import BUILTIN as RUTINA_SERIE
from app.routine_templates import get_template
from app.rutina_rapida import parse_pasos

router = APIRouter(prefix="/api")

TABLAS = {"tablero": "board_templates", "dia": "day_templates", "rutina": "routine_templates"}


def _ev(title: str, start: str, end: str, kind: str = "bloque", notes: str | None = None) -> dict:
    return {"title": title, "kind": kind, "all_day": False, "start": start, "end": end, "notes": notes}


# Días de serie: eventos y bloques con hora (las rutinas ya se repiten solas y las comidas dependen de tus platos)
DIA = {
    "clase": {
        "name": "Día de clase",
        "descripcion": "Clases por la mañana, comer, repaso de lo visto y un bloque de prácticas por la tarde.",
        "events": [
            _ev("Clases", "08:30", "14:00", "clase"),
            _ev("Comer", "14:15", "15:00"),
            _ev("Repasar los apuntes de hoy", "16:00", "17:00"),
            _ev("Prácticas y entregas", "17:00", "18:30"),
            _ev("Preparar la mochila de mañana", "21:30", "21:45"),
        ],
    },
    "estudio": {
        "name": "Día de estudio",
        "descripcion": "Tres bloques de estudio con descansos: tema nuevo, ejercicios y repaso, y flashcards al final.",
        "events": [
            _ev("Preparar el material", "08:30", "09:00"),
            _ev("Bloque 1 · tema nuevo", "09:00", "11:00"),
            _ev("Descanso", "11:00", "11:20"),
            _ev("Bloque 2 · ejercicios", "11:20", "13:00"),
            _ev("Bloque 3 · repaso", "16:00", "17:30"),
            _ev("Flashcards", "17:30", "18:00"),
        ],
    },
    "examen": {
        "name": "Día de examen",
        "descripcion": "Repaso ligero, examen y tarde libre; con tiempo de llegar sin prisa.",
        "events": [
            _ev("Repaso ligero de esquemas", "08:00", "09:00"),
            _ev("Salir hacia el examen", "09:15", "09:45"),
            _ev("Examen", "10:00", "12:00", "examen"),
            _ev("Apuntar dudas y lo que cayó", "12:15", "12:30"),
            _ev("Tarde libre", "16:00", "20:00"),
        ],
    },
    "entrega": {
        "name": "Día de entrega",
        "descripcion": "Revisar, cerrar y entregar con margen antes de la hora límite.",
        "events": [
            _ev("Revisar el enunciado y la rúbrica", "09:00", "09:30"),
            _ev("Terminar lo pendiente", "09:30", "12:30"),
            _ev("Revisión final y formato", "16:00", "17:30"),
            _ev("Entregar", "18:00", "18:15", "entrega"),
        ],
    },
    "finde": {
        "name": "Fin de semana",
        "descripcion": "Mañana tranquila, recados, deporte y planificar la semana por la tarde.",
        "events": [
            _ev("Desayuno tranquilo", "09:30", "10:30"),
            _ev("Recados y compra", "11:00", "12:30"),
            _ev("Deporte al aire libre", "12:30", "14:00"),
            _ev("Planificar la semana", "18:00", "18:45"),
        ],
    },
}


def _dia_serie(key: str, d: dict) -> dict:
    return {
        "key": f"b:{key}",
        "id": None,
        "builtin": True,
        "name": d["name"],
        "descripcion": d["descripcion"],
        "eventos": len(d["events"]),
        "comidas": 0,
        "data": {"events": d["events"], "comidas": {}},
    }


@router.get("/day-templates/serie")
def api_dias_serie():
    return {"plantillas": [_dia_serie(k, v) for k, v in DIA.items()]}


class AplicarDiaIn(BaseModel):
    key: str = Field(max_length=40)
    day: str = Field(min_length=10, max_length=10)
    comidas_reemplazar: bool = False


def _datos_dia(key: str) -> dict:
    if key.startswith("b:") and key[2:] in DIA:
        return {"events": DIA[key[2:]]["events"], "comidas": {}}
    if key.startswith("u:") and key[2:].isdigit():
        with get_db() as conn:
            row = conn.execute("SELECT data FROM day_templates WHERE id=?", (int(key[2:]),)).fetchone()
        if row:
            return json.loads(row["data"] or "{}")
    raise HTTPException(status_code=404, detail="Esa plantilla no existe")


@router.post("/day-templates/aplicar")
def api_aplicar_dia(data: AplicarDiaIn):
    try:
        d = date.fromisoformat(data.day)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida")
    return {"status": "success", **apply_day(_datos_dia(data.key), d, data.comidas_reemplazar)}


# ─────────── Las tuyas: renombrar, describir, editar, duplicar y copiar las de serie ───────────


class PlantillaPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=300)
    # solo rutinas
    pasos: str | None = Field(default=None, max_length=20_000)
    due_time: str | None = Field(default=None, max_length=5)
    repeat: dict | None = None


def _clase(clase: str) -> str:
    if clase not in TABLAS:
        raise HTTPException(status_code=404, detail="Clase de plantilla desconocida")
    return TABLAS[clase]


def _fila(conn, tabla: str, tid: int):
    row = conn.execute(f"SELECT * FROM {tabla} WHERE id=?", (tid,)).fetchone()  # noqa: S608 (tabla de TABLAS)
    if not row:
        raise HTTPException(status_code=404, detail="Esa plantilla no existe")
    return row


@router.patch("/plantillas/{clase}/{tid}")
def api_editar(clase: str, tid: int, data: PlantillaPatch):
    tabla = _clase(clase)
    with get_db() as conn:
        row = _fila(conn, tabla, tid)
        payload = json.loads(row["data"] or "{}")
        if data.descripcion is not None:
            payload["descripcion"] = data.descripcion.strip()
        if clase == "rutina":
            if data.pasos is not None:
                payload["steps"] = [
                    {
                        "title": p["title"],
                        "duration_min": p["duration_min"],
                        **({"due_time": p["due_time"]} if p["due_time"] else {}),
                    }
                    for p in parse_pasos(data.pasos)
                ]
            if data.due_time is not None:
                payload["due_time"] = data.due_time or None
            if data.repeat is not None:
                try:
                    payload["repeat"] = routines.clean_repeat(data.repeat) or {"freq": "daily"}
                except ValueError as e:
                    raise HTTPException(status_code=422, detail=str(e))
        elif data.pasos is not None or data.due_time is not None or data.repeat is not None:
            raise HTTPException(status_code=422, detail="Solo una plantilla de rutina tiene pasos y hora")
        name = data.name.strip() if data.name else row["name"]
        conn.execute(
            f"UPDATE {tabla} SET name=?, data=? WHERE id=?",  # noqa: S608
            (name, json.dumps(payload, ensure_ascii=False), tid),
        )
    return {"status": "success", "id": tid, "name": name}


@router.post("/plantillas/{clase}/{tid}/duplicar")
def api_duplicar(clase: str, tid: int):
    tabla = _clase(clase)
    with get_db() as conn:
        row = _fila(conn, tabla, tid)
        name = f"{row['name']} (copia)"[:120]
        new_id = conn.execute(
            f"INSERT INTO {tabla} (name, data) VALUES (?, ?)",  # noqa: S608
            (name, row["data"]),
        ).lastrowid
    return {"status": "success", "id": new_id, "name": name}


class CopiarIn(BaseModel):
    key: str = Field(max_length=40)
    name: str | None = Field(default=None, max_length=120)


@router.post("/plantillas/{clase}/copiar")
def api_copiar(clase: str, data: CopiarIn):
    """Una de serie pasa a ser tuya (para renombrarla o cambiarle los pasos). Las de tablero se copian desde el
    front con POST /api/board-templates (son dibujos del catálogo del front)."""
    if clase == "dia" and data.key.startswith("b:") and data.key[2:] in DIA:
        d = DIA[data.key[2:]]
        name, payload = d["name"], {"events": d["events"], "comidas": {}, "descripcion": d["descripcion"]}
    elif clase == "rutina" and data.key.startswith("b:") and data.key[2:] in RUTINA_SERIE:
        t = get_template(data.key)
        name = t["title"]
        payload = {
            "due_time": t["due_time"],
            "repeat": t["repeat"],
            "descripcion": t["descripcion"],
            "steps": RUTINA_SERIE[data.key[2:]]["steps"],
        }
    else:
        raise HTTPException(status_code=404, detail="Esa plantilla de serie no existe")
    name = (data.name or "").strip() or f"{name} (mía)"
    with get_db() as conn:
        new_id = conn.execute(
            f"INSERT INTO {TABLAS[clase]} (name, data) VALUES (?, ?)",  # noqa: S608
            (name[:120], json.dumps(payload, ensure_ascii=False)),
        ).lastrowid
    return {"status": "success", "id": new_id, "key": f"u:{new_id}", "name": name}
