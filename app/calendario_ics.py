"""
Calendario del Panel en formato .ics (P-11).

- `GET /api/calendar/export.ics` (con sesión): descarga para importar a mano.
- `GET /cal/<token>.ics` (sin sesión, solo lectura): suscripción por URL para cualquier cliente (GNOME Calendar,
  Thunderbird, el móvil…). El token es aleatorio (32 bytes) y solo se guarda su sha256 en `ui_prefs`
  (`calendario.ics`, clave privada: `/api/prefs` no la enseña ni deja escribirla). Crear uno nuevo invalida el
  anterior; revocarlo deja la URL en 404. `?tareas=1` añade las tareas con fecha sin hacer (no las de notas
  cifradas o sensibles: la URL viaja fuera del panel).

La ruta pública está en `core/auth.PUBLIC_PREFIXES` («/cal/»): el middleware no pide sesión y es este módulo el que
comprueba el token (comparación en tiempo constante). Un token que no vale responde 404, igual que uno revocado.
"""

import secrets
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import prefs, routines
from app.calendar import TZ
from app.database import get_db
from app.items import clean_text
from core.security import hash_api_token, verify_api_token

router = APIRouter(prefix="/api/calendar")
public_router = APIRouter()

PREF = "calendario.ics"


def build(tareas: bool = False) -> bytes:
    from icalendar import Calendar as ICalendar
    from icalendar import Event as IEvent

    cal = ICalendar()
    cal.add("prodid", "-//Panel//Calendario//ES")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Panel")
    cal.add("x-wr-timezone", "Europe/Madrid")
    cal.add("refresh-interval;value=duration", "PT30M")
    cal.add("x-published-ttl", "PT30M")
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY start").fetchall()
        tasks = _tasks(conn) if tareas else []
    now = datetime.now(TZ)
    for r in rows:
        ev = IEvent()
        ev.add("uid", r["uid"])
        ev.add("summary", r["title"])
        if r["all_day"]:
            ev.add("dtstart", date.fromisoformat(r["start"]))
            ev.add(
                "dtend",
                date.fromisoformat(r["end"]) if r["end"] else date.fromisoformat(r["start"]) + timedelta(days=1),
            )
        else:
            ev.add("dtstart", datetime.fromisoformat(r["start"]).replace(tzinfo=TZ))
            ev.add("dtend", datetime.fromisoformat(r["end"] or r["start"]).replace(tzinfo=TZ))
        if r["notes"]:
            ev.add("description", r["notes"])
        if r["location"]:
            ev.add("location", r["location"])
        ev.add("categories", [r["kind"].upper()])
        if r["repeat"]:  # una clase: regla semanal (o cada N días) hasta el fin del cuatrimestre
            rule = routines.parse(r["repeat"])
            rr = {"freq": "daily"}
            if rule["freq"] == "weekly":
                rr = {
                    "freq": "weekly",
                    "byday": [["MO", "TU", "WE", "TH", "FR", "SA", "SU"][d] for d in rule.get("days", [])],
                }
            elif rule["freq"] == "interval":
                rr = {"freq": "daily", "interval": int(rule.get("every", 1))}
            if r["repeat_until"]:
                rr["until"] = datetime.fromisoformat(r["repeat_until"] + "T23:59").replace(tzinfo=TZ)
            ev.add("rrule", rr)
        ev.add("dtstamp", now)
        cal.add_component(ev)
    for t in tasks:
        ev = IEvent()
        ev.add("uid", f"panel-tarea-{t['id']}@panel")
        ev.add("summary", f"☐ {clean_text(t['content']).splitlines()[0][:200]}")
        d = date.fromisoformat(t["due_date"])
        if t["due_time"]:
            start = datetime.fromisoformat(f"{t['due_date']}T{t['due_time']}").replace(tzinfo=TZ)
            ev.add("dtstart", start)
            ev.add("dtend", start + timedelta(minutes=t["duration_min"] or 30))
        else:
            ev.add("dtstart", d)
            ev.add("dtend", d + timedelta(days=1))
        ev.add("categories", ["TAREA"])
        ev.add("transp", "TRANSPARENT")  # una tarea no ocupa la agenda de quien la mira
        ev.add("dtstamp", now)
        cal.add_component(ev)
    return cal.to_ical()


def _tasks(conn) -> list:
    """Tareas e ideas con fecha y sin hacer, salvo las casillas de notas cifradas o sensibles."""
    from app.search import _cat_sensible, _cats_sensibles, _fm_sensible

    cats = _cats_sensibles()
    rows = conn.execute(
        "SELECT i.*, n.encrypted AS n_enc, n.category AS n_cat FROM inbox i LEFT JOIN notes n ON n.id = i.note_id "
        "WHERE i.item_type != 'rutina' AND i.due_date IS NOT NULL AND i.due_date != '' AND i.status != 'processed' "
        "ORDER BY i.due_date, i.due_time"
    ).fetchall()
    out = []
    for r in rows:
        if r["note_id"] and (r["n_enc"] or _cat_sensible(r["n_cat"], cats) or _fm_sensible(r["note_id"])):
            continue
        out.append(r)
    return out


def _response(body: bytes, download: bool) -> Response:
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="panel.ics"'
    return Response(body, media_type="text/calendar; charset=utf-8", headers=headers)


@router.get("/export.ics")
def api_export_ics(tareas: bool = False):
    return _response(build(tareas), download=True)


# ─────────────────────────────────────────────
# Enlace de suscripción con token
# ─────────────────────────────────────────────


def _state() -> dict:
    return prefs.get(PREF, {}) or {}


@router.get("/ics-enlace")
def api_link_state():
    st = _state()
    return {"activo": bool(st.get("hash")), "creado": st.get("creado"), "ultimo_uso": st.get("ultimo_uso")}


@router.post("/ics-enlace")
def api_link_create(request: Request):
    """Crea un enlace nuevo (el anterior deja de valer). El token solo se ve ahora: se guarda su hash."""
    token = secrets.token_urlsafe(32)
    prefs.put(PREF, {"hash": hash_api_token(token), "creado": time.time()}, private=True)
    path = f"/cal/{token}.ics"
    return {"status": "success", "path": path, "url": str(request.base_url).rstrip("/") + path}


@router.delete("/ics-enlace")
def api_link_revoke():
    prefs.put(PREF, {}, private=True)
    return {"status": "success"}


@public_router.get("/cal/{name}")
def public_feed(name: str, tareas: bool = False):
    token = name[:-4] if name.endswith(".ics") else ""
    st = _state()
    if not token or not verify_api_token(token, st.get("hash") or ""):
        raise HTTPException(status_code=404, detail="No encontrado")
    if time.time() - (st.get("ultimo_uso") or 0) > 3600:  # una escritura por hora como mucho
        prefs.put(PREF, {**st, "ultimo_uso": time.time()}, private=True)
    return _response(build(tareas), download=False)
