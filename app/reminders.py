"""
Recordatorios de eventos, tareas con hora, rutinas y repasos de flashcards.

GET /api/reminders devuelve los avisos que tocan entre hace 10 min y dentro de `horizon`
minutos, cada uno con una clave estable (para no repetirlo) y la hora a la que debe saltar.
Los muestran el navegador (static/js/reminders.js: notificación del sistema mientras el Panel
está abierto) y el portátil (scripts/desktop/panel_agenda.py con notify-send, cada minuto
desde la Waybar). La configuración por tipo vive en las preferencias (`reminders`, /api/prefs).

Push en la PWA con el navegador cerrado: no es viable aquí (Web Push exige HTTPS y un
servicio de push; el Panel se sirve por HTTP en la red local). Ver AUDITORIA.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter

from app.calendar import TZ, entries
from app.database import get_db
from app.prefs import get as get_pref

router = APIRouter(prefix="/api/reminders")

DEFAULTS = {
    "evento": {"on": True, "min": 15},
    "tarea": {"on": True, "min": 0},
    "rutina": {"on": True, "min": 0},
    "flashcards": {"on": True, "hora": "20:00"},
    "escritorio": {"on": True},   # notify-send en el portátil
    "navegador": {"on": True},
}
GRACE_MIN = 10


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
        out.append({"key": f"{e['key']}@{e['start']}@{mins}", "kind": kind,
                    "title": f"{e['routine_title']}: {e['title']}" if e.get("step") else e["title"],
                    "body": f"{ {'evento': 'Evento', 'tarea': 'Tarea', 'rutina': 'Rutina'}[kind] } {cuando}",
                    "fire_at": fire.strftime("%Y-%m-%dT%H:%M"),
                    "url": f"/calendario?dia={e['start'][:10]}" if kind == "evento" else f"/tareas?item={e.get('item_id')}"})
    fc = conf["flashcards"]
    if fc.get("on"):
        h, m = (int(x) for x in (fc.get("hora") or "20:00").split(":"))
        fire = datetime.combine(now.date(), datetime.min.time()).replace(hour=h, minute=m)
        if lo <= fire <= hi or (fire <= now and fire.date() == now.date() and now - fire <= timedelta(hours=3)):
            with get_db() as conn:
                n = conn.execute("SELECT COUNT(*) FROM flashcards WHERE next_review <= ?",
                                 (datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).timestamp(),)).fetchone()[0]
            if n:
                out.append({"key": f"flashcards@{now.date().isoformat()}", "kind": "flashcards", "title": "Repaso de flashcards",
                            "body": f"Tienes {n} tarjeta{'s' if n != 1 else ''} para repasar hoy", "fire_at": fire.strftime("%Y-%m-%dT%H:%M"),
                            "url": "/repaso"})
    return sorted(out, key=lambda r: r["fire_at"])


@router.get("")
def api_due(horizon: int = 60):
    return {"now": datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"), "settings": settings(),
            "reminders": due(horizon=max(1, min(horizon, 24 * 60)))}


@router.get("/settings")
def api_settings():
    return {"settings": settings(), "defaults": DEFAULTS}
