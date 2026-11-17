"""
Recordatorios de eventos, tareas con hora, rutinas y repasos de flashcards (las tareas atrasadas, con sus
botones, van aparte: app/atrasadas.py; aquí solo su configuración, «atrasadas»).

GET /api/reminders devuelve los avisos que tocan entre hace 10 min y dentro de `horizon`
minutos, cada uno con una clave estable (para no repetirlo) y la hora a la que debe saltar.
Los muestran el navegador (static/js/reminders.js: notificación del sistema mientras el Panel
está abierto) y el portátil (scripts/desktop/panel_agenda.py con notify-send, cada minuto
desde la Waybar). La configuración por tipo vive en las preferencias (`reminders`, /api/prefs).

Sin repetidos (P-11): el navegador y el portátil piden los avisos por su cuenta, así que antes de enseñar uno lo
«reclaman» con POST /api/reminders/vistos; solo quien lo reclama primero lo enseña (registro en la preferencia privada
`reminders.vistos`, tres días). El resumen de la mañana («Hoy: 3 tareas, 2 clases, 1 entrega · 2 atrasadas») es un aviso
más (`resumen`), a su hora, una vez al día.

Push en la PWA con el navegador cerrado: no es viable aquí (Web Push exige HTTPS y un
servicio de push; el Panel se sirve por HTTP en la red local). Ver AUDITORIA.
"""

import threading
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.calendar import TZ, entries
from app.database import get_db
from app.prefs import get as get_pref
from app.prefs import put as put_pref

router = APIRouter(prefix="/api/reminders")

DEFAULTS = {
    "evento": {"on": True, "min": 15},
    "tarea": {"on": True, "min": 0},
    "rutina": {"on": True, "min": 0},
    "flashcards": {"on": True, "hora": "20:00"},
    # resumen de la mañana: lo que hay hoy en una línea, una vez al día (navegador o escritorio, el primero)
    "resumen": {"on": True, "hora": "08:30"},
    # tareas atrasadas (app/atrasadas.py): notificación con botones en el escritorio, una vez al día por tarea
    "atrasadas": {"on": True, "hora": "09:00", "dias": [0, 1, 2, 3, 4, 5, 6]},
    "escritorio": {"on": True},  # notify-send en el portátil
    "navegador": {"on": True},
}
GRACE_MIN = 10
LATE_H = 3  # un aviso diario (flashcards, resumen) aún sale hasta 3 h tarde (el portátil estaba dormido)
VISTOS = "reminders.vistos"
_vistos_lock = threading.Lock()


def settings() -> dict:
    saved = get_pref("reminders", {}) or {}
    return {k: {**v, **(saved.get(k) or {})} for k, v in DEFAULTS.items()}


def due(now: datetime | None = None, horizon: int = 60) -> list[dict]:
    now = (now or datetime.now(TZ)).replace(tzinfo=None)
    conf = settings()
    lo, hi = now - timedelta(minutes=GRACE_MIN), now + timedelta(minutes=horizon)
    out = []
    for e in entries(now.date(), (now + timedelta(minutes=horizon)).date()):
        kind = {"event": "evento", "task": "tarea", "routine": "rutina"}[e["kind"]]
        c = conf[kind]
        if not c.get("on") or e.get("done") or (e["kind"] == "task" and e["type"] == "idea"):
            continue
        if e["all_day"]:
            if e["kind"] != "event":
                continue  # sin hora: no hay a qué hora avisar
            start = datetime.fromisoformat(e["start"] + "T08:00")
            mins = 0
        else:
            start = datetime.fromisoformat(e["start"])
            mins = e["reminder_min"] if e.get("reminder_min") is not None else int(c.get("min", 0))
        fire = start - timedelta(minutes=mins)
        if not (lo <= fire <= hi):
            continue
        cuando = "todo el día" if e["all_day"] else f"a las {e['start'][11:16]}" + (f" (en {mins} min)" if mins else "")
        out.append(
            {
                "key": f"{e['key']}@{e['start']}@{mins}",
                "kind": kind,
                "title": f"{e['routine_title']}: {e['title']}" if e.get("step") else e["title"],
                "body": f"{ {'evento': 'Evento', 'tarea': 'Tarea', 'rutina': 'Rutina'}[kind] } {cuando}",
                "fire_at": fire.strftime("%Y-%m-%dT%H:%M"),
                "url": f"/calendario?dia={e['start'][:10]}" if kind == "evento" else f"/tareas?item={e.get('item_id')}",
                # para los botones del escritorio (Completar, +1 h, Mañana)
                "item_id": e.get("item_id"),
                "day": e.get("day") or e["start"][:10],
                "start": e["start"],
                "all_day": e["all_day"],
            }
        )
    fc = conf["flashcards"]
    if fc.get("on"):
        fire = _daily(now, fc.get("hora") or "20:00")
        if lo <= fire <= hi or (fire <= now and now - fire <= timedelta(hours=LATE_H)):
            with get_db() as conn:
                n = conn.execute(
                    "SELECT COUNT(*) FROM flashcards WHERE next_review <= ?",
                    (datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).timestamp(),),
                ).fetchone()[0]
            if n:
                out.append(
                    {
                        "key": f"flashcards@{now.date().isoformat()}",
                        "kind": "flashcards",
                        "title": "Repaso de flashcards",
                        "body": f"Tienes {n} tarjeta{'s' if n != 1 else ''} para repasar hoy",
                        "fire_at": fire.strftime("%Y-%m-%dT%H:%M"),
                        "url": "/repaso",
                    }
                )
    rs = conf["resumen"]
    if rs.get("on"):
        fire = _daily(now, rs.get("hora") or "08:30")
        if lo <= fire <= hi or (fire <= now and now - fire <= timedelta(hours=LATE_H)):
            res = resumen(now.date())
            if res["total"]:
                out.append(
                    {
                        "key": f"resumen@{now.date().isoformat()}",
                        "kind": "resumen",
                        "title": res["title"],
                        "body": res["body"],
                        "fire_at": fire.strftime("%Y-%m-%dT%H:%M"),
                        "url": "/hoy",
                    }
                )
    return sorted(out, key=lambda r: r["fire_at"])


def _daily(now: datetime, hora: str) -> datetime:
    h, m = (int(x) for x in hora.split(":"))
    return datetime.combine(now.date(), datetime.min.time()).replace(hour=h, minute=m)


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
# (singular, plural) en el orden en que se cuentan
PIEZAS = [
    ("examen", ("examen", "exámenes")),
    ("entrega", ("entrega", "entregas")),
    ("clase", ("clase", "clases")),
    ("evento", ("evento", "eventos")),
    ("tarea", ("tarea", "tareas")),
    ("rutina", ("rutina", "rutinas")),
]


def resumen(d: date | None = None) -> dict:
    """Lo de hoy en una línea: «3 tareas, 2 clases, 1 entrega · 2 atrasadas» (sin ideas ni lo ya hecho)."""
    from app import atrasadas  # perezoso: atrasadas lee settings() de aquí

    d = d or date.today()
    n = dict.fromkeys((k for k, _ in PIEZAS), 0)
    rutinas = set()
    for e in entries(d, d):
        if e.get("done"):
            continue
        if e["kind"] == "event":
            n[e["type"] if e["type"] in n else "evento"] += 1
        elif e["kind"] == "routine":
            rutinas.add(e.get("routine_id") or e["id"])  # una rutina con bloques cuenta una vez
        elif e["type"] != "idea":
            n["tarea"] += 1
    n["rutina"] = len(rutinas)
    late = sum(1 for e in atrasadas.listar("todo", d) if not e["callada"])
    partes = [f"{n[k]} {pl if n[k] != 1 else sg}" for k, (sg, pl) in PIEZAS if n[k]]
    body = ", ".join(partes) if partes else "Nada en la agenda"
    if late:
        body += f" · {late} atrasada{'s' if late != 1 else ''}"
    return {
        "date": d.isoformat(),
        "title": f"Hoy, {DIAS[d.weekday()]} {d.day}",  # corto: swaync recorta el título a ~22 letras
        "body": body,
        "counts": {**n, "atrasadas": late},
        "total": sum(n.values()) + late,
    }


def _vistos() -> dict:
    v = get_pref(VISTOS, {}) or {}
    return v if isinstance(v, dict) else {}


class VistosIn(BaseModel):
    keys: list[str] = Field(max_length=100)


def claim(keys: list[str]) -> list[str]:
    """Apunta como enseñados los que nadie había enseñado aún y devuelve esos (los demás ya salieron en otro sitio)."""
    keys = [k[:300] for k in dict.fromkeys(keys)]
    with _vistos_lock:
        v = _vistos()
        nuevos = [k for k in keys if k not in v]
        if nuevos:
            ahora = time.time()
            v = {k: t for k, t in v.items() if ahora - t < 3 * 86400}
            v.update(dict.fromkeys(nuevos, ahora))
            put_pref(VISTOS, v, private=True)
    return nuevos


@router.get("")
def api_due(horizon: int = 60):
    rem = due(horizon=max(1, min(horizon, 24 * 60)))
    vistos = _vistos()
    return {
        "now": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"),
        "settings": settings(),
        "reminders": rem,
        "shown": [r["key"] for r in rem if r["key"] in vistos],
    }


@router.post("/vistos")
def api_claim(data: VistosIn):
    return {"claimed": claim(data.keys)}


@router.get("/resumen")
def api_resumen():
    return resumen()


@router.get("/settings")
def api_settings():
    return {"settings": settings(), "defaults": DEFAULTS}
