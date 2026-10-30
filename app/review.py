"""
Calendario de repaso: días estudiados (mapa de calor), flashcards que vencen
cada día (SM-2, `flashcards.next_review`) y notas que hace tiempo que no se
repasan (`notes.last_reviewed`).
"""
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter

from app.database import get_db

router = APIRouter(prefix="/api/review")

STALE_DAYS = 30


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


@router.get("/calendar")
def review_calendar(past_weeks: int = 16, future_days: int = 28):
    past_weeks = max(1, min(past_weeks, 53))
    future_days = max(1, min(future_days, 120))
    today = date.today()
    now = time.time()
    with get_db() as conn:
        studied = {r["day"] for r in conn.execute("SELECT day FROM study_days")}
        cards = conn.execute("""SELECT f.id, f.note_id, f.question, f.next_review, n.title AS note_title
                                FROM flashcards f LEFT JOIN notes n ON n.id = f.note_id""").fetchall()
        notes = conn.execute("""SELECT id, title, category, status, last_reviewed FROM notes
                                WHERE encrypted=0 AND status != 'indice'""").fetchall()

    # Pasado: desde el lunes de hace N semanas hasta hoy
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=past_weeks - 1)
    heat = []
    d = start
    while d <= today:
        key = d.isoformat()
        heat.append({"date": key, "studied": key in studied})
        d += timedelta(days=1)

    # Futuro: flashcards por día (las vencidas cuentan para hoy)
    due_by_day: dict[str, list] = {}
    overdue = 0
    for c in cards:
        key = _day(c["next_review"] or 0)
        if key < today.isoformat():
            overdue += 1
            key = today.isoformat()
        due_by_day.setdefault(key, []).append(c)
    upcoming = []
    for i in range(future_days):
        key = (today + timedelta(days=i)).isoformat()
        items = due_by_day.get(key, [])
        upcoming.append({"date": key, "flashcards": len(items),
                         "notes": sorted({c["note_title"] or c["note_id"] for c in items if c["note_id"]})[:5]})

    stale = sorted(
        ({"id": n["id"], "title": n["title"], "category": n["category"], "status": n["status"],
          "days": None if not n["last_reviewed"] else int((now - n["last_reviewed"]) // 86400)}
         for n in notes if not n["last_reviewed"] or now - n["last_reviewed"] > STALE_DAYS * 86400),
        key=lambda x: (x["days"] is not None, -(x["days"] or 0)))

    streak, cur = 0, today
    while cur.isoformat() in studied:
        streak += 1
        cur -= timedelta(days=1)
    return {"today": today.isoformat(), "heat": heat, "upcoming": upcoming, "overdue": overdue,
            "due_today": upcoming[0]["flashcards"], "streak": streak,
            "studied_days": sum(1 for h in heat if h["studied"]), "stale_notes": stale[:30], "stale_total": len(stale)}


# ─────────────────────────────────────────────
# Registro de cambios y revisión semanal (item_log, app/routines.py)
# ─────────────────────────────────────────────

@router.get("/week")
def review_week(start: str | None = None):
    """Lo hecho en una semana (de lunes a domingo): tareas e ideas completadas (y reabiertas),
    rutinas cumplidas por día y lo creado; para la vista de revisión semanal."""
    try:
        d0 = date.fromisoformat(start) if start else date.today()
    except ValueError:
        d0 = date.today()
    d0 -= timedelta(days=d0.weekday())
    d1 = d0 + timedelta(days=6)
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM item_log WHERE day >= ? AND day <= ? ORDER BY at", (d0.isoformat(), d1.isoformat()))]
        alive = {r["id"]: r for r in conn.execute("SELECT id, status, item_type FROM inbox")}
    # El último estado del día manda: hecha y reabierta el mismo día no cuenta
    last: dict[tuple, dict] = {}
    for r in rows:
        if r["action"] in ("done", "reopen", "check", "uncheck"):
            last[(r["item_id"], r["day"], r["action"] in ("check", "uncheck"))] = r
    hechas = [r for (_, _, rut), r in last.items() if not rut and r["action"] == "done"]
    rutinas = [r for (_, _, rut), r in last.items() if rut and r["action"] == "check"]
    por_dia = {(d0 + timedelta(days=i)).isoformat(): {"hechas": 0, "rutinas": 0} for i in range(7)}
    for r in hechas:
        por_dia[r["day"]]["hechas"] += 1
    for r in rutinas:
        por_dia[r["day"]]["rutinas"] += 1
    fmt = lambda r: {"item_id": r["item_id"], "text": r["text"], "type": r["type"], "day": r["day"], "at": r["at"],  # noqa: E731
                     "exists": r["item_id"] in alive}
    return {"from": d0.isoformat(), "to": d1.isoformat(),
            "hechas": [fmt(r) for r in sorted(hechas, key=lambda r: r["at"], reverse=True)],
            "rutinas": [fmt(r) for r in sorted(rutinas, key=lambda r: r["at"], reverse=True)],
            "creadas": sum(1 for r in rows if r["action"] == "created"),
            "por_dia": por_dia}


@router.get("/log")
def review_log(limit: int = 100, before: float | None = None):
    """Historial de cambios (más reciente primero), paginado con `before`."""
    limit = max(1, min(limit, 500))
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM item_log WHERE at < ? ORDER BY at DESC LIMIT ?",
                            (before or time.time() + 1, limit)).fetchall()
    return {"entries": [dict(r) for r in rows]}
