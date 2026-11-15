"""
Alta rápida de rutinas (P-3): lo mínimo en una línea y los pasos, uno por línea, con su hora y duración escritas.

    POST /api/routines/rapida      {"text": "gimnasio L X V 18:00", "pasos": "calentar 10m\\npesas 40m", "dry_run": true}
        → vista previa (lo entendido y el horario de cada paso) o, sin dry_run, la rutina creada.
          Los pasos sin hora propia van uno detrás de otro desde la hora de la rutina (como una plantilla);
          `repeat`/`due_time` (de «Más opciones») mandan sobre lo escrito; `dur_defecto` = minutos de un paso sin
          duración (el último que se usó, recordado en el navegador).
    POST /api/routines/{id}/pasos  {"pasos": "ducha 10m\\n18:30 cenar 30m", "dry_run"}
        → añade varios bloques a una rutina que ya existe (pegar una lista). Aquí un bloque sin hora escrita sigue
          siendo flexible, como al añadirlo uno a uno.

Una línea de paso entiende «ducha 10m», «pesas 40 min», «18:10 pesas 40m», «pesas 18:10-18:50» y viñetas o
casillas de Markdown al principio («- », «* », «1. », «- [ ] »), para poder pegar una lista de una nota.
"""

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import routines
from app.capture import _con_menciones, _sin_version, parse_routine
from app.database import get_db
from app.items import ItemIn, ItemPatch, _get, create, item_type, update
from app.routine_templates import crear_con_pasos

router = APIRouter(prefix="/api")

MAX_PASOS = 60
_VINETA = re.compile(r"^\s*(?:[-*•·+]\s*)?(?:\[[ xX]?\]\s*)?(?:\d{1,2}[.)]\s+)?")
_RANGO = re.compile(r"(?<![\d:])([01]?\d|2[0-3])[:.]([0-5]\d)\s*(?:-|–|a)\s*([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:])")
_HORA = re.compile(r"(?<![\d:])(?:a las\s+)?([01]?\d|2[0-3]):([0-5]\d)(?![\d:])", re.I)


def parse_paso(line: str) -> dict | None:
    """Una línea → {"title", "due_time", "duration_min"}; una línea vacía → None."""
    text = _VINETA.sub("", line, count=1).strip()
    if not text:
        return None
    at, dur = None, None
    m = _RANGO.search(text)
    if m:
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        at, dur = f"{int(m.group(1)):02d}:{m.group(2)}", ((b - a) % 1440) or None
    else:
        m = _HORA.search(text)
        if m:
            at = f"{int(m.group(1)):02d}:{m.group(2)}"
    if m:
        text = (text[: m.start()] + " " + text[m.end() :]).strip()
    title, d = routines.split_duration(re.sub(r"\s+", " ", text))
    title = title.strip(" ,.-·")
    if not title:
        return None
    return {"title": (title[:1].upper() + title[1:])[:300], "due_time": at, "duration_min": dur or d}


def parse_pasos(text: str) -> list[dict]:
    pasos = [p for p in (parse_paso(x) for x in (text or "").splitlines()) if p]
    if len(pasos) > MAX_PASOS:
        raise HTTPException(status_code=422, detail=f"Como mucho {MAX_PASOS} pasos de una vez")
    return pasos


def _fmt(m: int) -> str:
    return f"{m // 60} h{f' {m % 60}' if m % 60 else ''}" if m >= 60 else f"{m} min"


class RapidaIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    pasos: str = Field(default="", max_length=20_000)
    dry_run: bool = False
    repeat: dict | None = None  # «Más opciones»: mandan sobre lo escrito
    due_time: str | None = Field(default=None, max_length=5)
    dur_defecto: int | None = Field(default=None, ge=1, le=600)
    contexto: str | None = Field(default=None, max_length=12)
    asignatura_id: int | None = Field(default=None, ge=1)
    proyecto_id: int | None = Field(default=None, ge=1)


@router.post("/routines/rapida")
def api_rapida(data: RapidaIn):
    ctx = {
        k: v
        for k, v in {
            "contexto": data.contexto,
            "asignatura_id": data.asignatura_id,
            "proyecto_id": data.proyecto_id,
        }.items()
        if v
    }
    body, donde = data.text.strip(), ""
    if any(c in body for c in "@#"):  # «@gabd», «#panel-maestro», como en la captura
        leido = _con_menciones(body, ctx)
        if isinstance(leido, dict):
            return leido
        body, ctx, donde = leido
    r = parse_routine(body)
    if data.repeat:
        try:
            r["repeat"] = routines.clean_repeat(data.repeat) or {"freq": "daily"}
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    if data.due_time is not None:
        r["due_time"] = data.due_time or None
    pasos = parse_pasos(data.pasos)
    for p in pasos:
        if not p["duration_min"] and data.dur_defecto:
            p["duration_min"], p["dur_defecto"] = data.dur_defecto, True
    horario = routines.schedule(r["due_time"], pasos)
    total = sum(p["duration_min"] or 0 for p in pasos)
    partes = [routines.describe(r["repeat"])]
    if r["due_time"]:
        partes.append(r["due_time"] + (f"–{horario[-1]['end']}" if horario and horario[-1].get("end") else ""))
    if pasos:
        partes.append(f"{len(pasos)} paso{'s' if len(pasos) > 1 else ''}" + (f" · {_fmt(total)}" if total else ""))
    elif r["duration_min"]:
        partes.append(_fmt(r["duration_min"]))
    if donde:
        partes.append(donde)
    out = {
        "status": "success",
        "preview": {
            "title": r["title"],
            "repeat": r["repeat"],
            "repeat_text": routines.describe(r["repeat"]),
            "due_time": r["due_time"],
            "duration_min": None if pasos else r["duration_min"],
            "when": " · ".join(partes),
            "pasos": [
                {k: p.get(k) for k in ("title", "at", "end", "duration_min", "fixed", "dur_defecto")} for p in horario
            ],
            "donde": donde or None,
        },
    }
    if data.dry_run:
        return out
    item = ItemIn(
        text=r["title"],
        type="rutina",
        repeat=r["repeat"],
        due_time=r["due_time"],
        duration_min=None if pasos else r["duration_min"],
        **_sin_version(ctx),
    )
    # sin «due_time» propio, el paso toma la del encadenado (crear_con_pasos vuelve a calcularla igual)
    steps = [
        {
            "title": p["title"],
            "duration_min": p["duration_min"],
            **({"due_time": p["due_time"]} if p["due_time"] else {}),
        }
        for p in pasos
    ]
    rid, sin_hora = crear_con_pasos(item, steps)
    out.update(id=rid, sin_hora=sin_hora)
    return out


class PasosIn(BaseModel):
    pasos: str = Field(min_length=1, max_length=20_000)
    dry_run: bool = False


@router.post("/routines/{item_id}/pasos")
def api_pasos(item_id: int, data: PasosIn):
    with get_db() as conn:
        row = _get(conn, item_id)
    if item_type(row) != "rutina" or row["parent_id"] is not None:
        raise HTTPException(status_code=422, detail="Solo se añaden bloques a una rutina")
    pasos = parse_pasos(data.pasos)
    if not pasos:
        raise HTTPException(status_code=422, detail="Escribe al menos un bloque")
    out = {"status": "success", "pasos": pasos}
    if data.dry_run:
        return out
    ids, sin_hora = [], []
    for p in pasos:
        sid = create(ItemIn(text=p["title"], parent_id=item_id, duration_min=p["duration_min"]))
        ids.append(sid)
        if p["due_time"]:
            try:
                update(sid, ItemPatch(due_time=p["due_time"]))
            except HTTPException as e:
                if e.status_code != 409:
                    raise
                sin_hora.append(p["title"])
    out.update(ids=ids, sin_hora=sin_hora)
    return out
