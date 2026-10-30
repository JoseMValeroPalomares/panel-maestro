"""
Vistas de conjunto del Panel:
  - GET /api/today          pantalla «Hoy»: eventos, rutinas pendientes, tareas de hoy (y atrasadas),
                             comida del día con sus macros y flashcards por repasar.
  - GET /api/status         estado de las conexiones (ESP32, calendario: iCloud y ESP32, copias) con la
                             hora del último contacto y la acción para reintentar.
  - GET /api/notes-home     portada de Notas sin nota abierta: recientes, por escribir, olvidadas, recuento
                             por estado y flashcards pendientes («/api/notes/home» lo taparía /api/notes/{id}).
  - GET /api/palette/index  índice ligero para la paleta de comandos (Ctrl+K): notas, tareas, ideas,
                             rutinas, platos y eventos cercanos; la búsqueda aproximada se hace en el navegador.
"""
import sqlite3
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter

from app import backup
from app.calendar import TZ, entries
from app.database import get_db
from app.items import clean_text, item_type, origin

router = APIRouter(prefix="/api")
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


# ─────────────────────────────────────────────
# Hoy
# ─────────────────────────────────────────────

def _meals_today(d: date) -> dict | None:
    try:
        from comidas.database import get_db as comidas_db
        from comidas.main import _plan_state
        with comidas_db() as conn:
            st = _plan_state(conn, (d - timedelta(days=d.weekday())).isoformat())
    except Exception:  # noqa: BLE001 — Comidas no debe tumbar la pantalla de inicio
        return None
    dia = st["dias"][DIAS[d.weekday()]]
    nombres = {f["clave"]: f["nombre"] for f in st.get("franjas", [])}
    return {"comidas": [{"franja": k, "nombre": nombres.get(k, k), "platos": [{"nombre": p["nombre"], "gramos": p["gramos"], "rol": p.get("rol"),
                                                                             "kcal": p["macros"]["kcal"]} for p in v["platos"]],
                         "kcal": v["total"]["kcal"]} for k, v in dia["comidas"].items() if v["platos"]],
            "total": dia["total"], "objetivo": st["objetivo_dia"], "restante": dia["restante"]}


def _routines_of(todo: list[dict]) -> list[dict]:
    """Las rutinas de hoy: las que el calendario da por bloques se juntan otra vez en su rutina."""
    out, grouped = [], {}
    for e in todo:
        if e["kind"] != "routine":
            continue
        if not e.get("step"):
            out.append(e)
            continue
        g = grouped.get(e["routine_id"])
        if g is None:
            g = grouped[e["routine_id"]] = {**e, "key": f"r{e['routine_id']}@{e['day']}", "id": e["routine_id"], "item_id": e["routine_id"],
                                            "title": e["routine_title"], "steps": [], "step": False}
            out.append(g)
        g["steps"].append({"id": e["id"], "title": e["title"], "done": e["done"], "at": None if e["all_day"] else e["start"][11:16]})
        g["steps"].sort(key=lambda x: x["at"] or "99:99")
        g["done"] = all(x["done"] for x in g["steps"])
    return sorted(out, key=lambda e: (e["all_day"], e["start"]))


@router.get("/today")
def api_today():
    now = datetime.now(TZ).replace(tzinfo=None)
    d = now.date()
    todo = entries(d, d)
    with get_db() as conn:
        atrasadas = [{"id": r["id"], "title": clean_text(r["content"]).split("\n")[0], "due_date": r["due_date"], "type": item_type(r),
                      "origin": origin(r)} for r in conn.execute(
            "SELECT * FROM inbox WHERE due_date < ? AND status != 'processed' AND item_type != 'rutina' ORDER BY due_date LIMIT 20", (d.isoformat(),))]
        flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE next_review <= ?",
                             (datetime.combine(d + timedelta(days=1), datetime.min.time()).timestamp(),)).fetchone()[0]
        flash_notas = conn.execute("SELECT COUNT(DISTINCT note_id) FROM flashcards WHERE next_review <= ?",
                                   (datetime.combine(d + timedelta(days=1), datetime.min.time()).timestamp(),)).fetchone()[0]
        hechas_hoy = conn.execute("SELECT COUNT(*) FROM item_log WHERE day=? AND action IN ('done', 'check')", (d.isoformat(),)).fetchone()[0]
        dinero = _money_today(conn, d)
    return {
        "date": d.isoformat(), "now": now.strftime("%Y-%m-%dT%H:%M"),
        "eventos": [e for e in todo if e["kind"] == "event"],
        "rutinas": _routines_of(todo),
        "tareas": [e for e in todo if e["kind"] == "task"],
        "atrasadas": atrasadas,
        "comida": _meals_today(d),
        "flashcards": {"pendientes": flash, "notas": flash_notas},
        "hechas_hoy": hechas_hoy,
        "dinero": dinero,
    }


def _money_today(conn, d) -> dict | None:
    """Gasto de hoy y del mes (Economía) para la tarjeta de Hoy; None si aún no se usa Economía."""
    try:
        if not conn.execute("SELECT 1 FROM fin_movements LIMIT 1").fetchone():
            return None
        mes = d.strftime("%Y-%m")
        hoy = conn.execute("SELECT COALESCE(SUM(importe), 0) FROM fin_movements WHERE tipo='gasto' AND fecha=?", (d.isoformat(),)).fetchone()[0]
        en_mes = conn.execute("SELECT COALESCE(SUM(importe), 0) FROM fin_movements WHERE tipo='gasto' AND substr(fecha, 1, 7)=?", (mes,)).fetchone()[0]
        ultimos = [{"concepto": r["concepto"] or r["categoria"] or "Gasto", "importe": r["importe"]} for r in conn.execute(
            "SELECT concepto, categoria, importe FROM fin_movements WHERE tipo='gasto' AND fecha=? ORDER BY id DESC LIMIT 3", (d.isoformat(),))]
    except sqlite3.OperationalError:  # BD sin la migración 13
        return None
    return {"hoy": round(hoy, 2), "mes": round(en_mes, 2), "ultimos": ultimos}


# ─────────────────────────────────────────────
# Estado de las conexiones
# ─────────────────────────────────────────────

STATE_LABEL = {"online": "Conectado", "ok": "Al día", "connecting": "Conectando", "syncing": "Sincronizando", "offline": "Sin conexión",
               "error": "Con errores", "disabled": "Desactivado", "idle": "En espera", "antigua": "Copia antigua", "sin-copias": "Sin copias"}


@router.get("/status")
def api_status():
    from estudio import calendar_sync
    from estudio.esp32_link import LINK
    esp = LINK.status()
    cal = calendar_sync.status()
    bk = backup.status()
    items = [
        {"key": "esp32", "name": "ESP32", "icon": "monitor", "state": esp["state"], "label": STATE_LABEL.get(esp["state"], esp["state"]),
         "last_ok": esp.get("last_ok"), "detail": esp.get("last_error") or (f"Siguiente intento en {esp['retry_in']} s" if esp.get("retry_in") else None),
         "action": {"label": "Reintentar", "method": "POST", "url": "/estudio/api/esp32/retry"} if esp["state"] in ("offline", "connecting", "error") else None},
    ]
    for k, name in (("icloud", "Calendario · iCloud"), ("esp32", "Calendario · ESP32")):
        c = cal.get(k, {})
        items.append({"key": f"cal-{k}", "name": name, "icon": "calendar", "state": c.get("state", "idle"),
                      "label": STATE_LABEL.get(c.get("state", "idle"), c.get("state")), "last_ok": c.get("at"),
                      "detail": c.get("error") or (f"{c['count']} eventos" if c.get("count") is not None else c.get("detail")),
                      "action": {"label": "Sincronizar ahora", "method": "POST", "url": "/api/calendar/sync"}})
    items.append({"key": "backups", "name": "Copias de seguridad", "icon": "database-backup", "state": bk["health"],
                  "label": STATE_LABEL.get(bk["health"], bk["health"]), "last_ok": bk["last"]["created_at"] if bk.get("last") else None,
                  "detail": (bk.get("last_error") or {}).get("message") or (f"{bk['count']} copias" if bk.get("count") else None),
                  "action": {"label": "Copia ahora", "method": "POST", "url": "/api/backups/run"}})
    bad = [i for i in items if i["state"] in ("offline", "error", "sin-copias", "antigua")]
    return {"items": items, "overall": "error" if bad else "ok", "problems": len(bad), "at": time.time()}


# ─────────────────────────────────────────────
# Índice de la paleta de comandos
# ─────────────────────────────────────────────

@router.get("/palette/index")
def api_palette_index():
    d = date.today()
    with get_db() as conn:
        notes = [{"id": r["id"], "title": r["title"] or r["id"], "category": r["category"]}
                 for r in conn.execute("SELECT id, title, category FROM notes WHERE status != 'indice' ORDER BY last_modified DESC")]
        items = [{"id": r["id"], "text": clean_text(r["content"]).split("\n")[0][:200], "type": item_type(r), "done": r["status"] == "processed",
                  "origin": origin(r)} for r in conn.execute("SELECT * FROM inbox WHERE parent_id IS NULL ORDER BY status, created_at DESC LIMIT 2000")]
    meals = []
    try:
        from comidas.database import get_db as comidas_db
        with comidas_db() as conn:
            meals = [{"id": r["id"], "nombre": r["nombre"], "franja": r["franja"]} for r in conn.execute("SELECT id, nombre, franja FROM meals ORDER BY nombre")]
    except Exception:  # noqa: BLE001
        pass
    events = [e for e in entries(d - timedelta(days=7), d + timedelta(days=60)) if e["kind"] == "event"]
    return {"notes": notes, "items": items, "meals": meals,
            "events": [{"id": e["id"], "title": e["title"], "start": e["start"], "type": e["type"]} for e in events]}


# ─────────────────────────────────────────────
# Portada de Notas
# ─────────────────────────────────────────────

@router.get("/notes-home")
def api_notes_home():
    now = time.time()
    tomorrow = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).timestamp()
    pick = lambda r: {"id": r["id"], "title": r["title"] or r["id"], "category": r["category"], "status": r["status"],  # noqa: E731
                      "last_modified": r["last_modified"], "last_reviewed": r["last_reviewed"] or None}
    with get_db() as conn:
        estados = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM notes GROUP BY status")}
        recientes = [pick(r) for r in conn.execute(
            "SELECT * FROM notes WHERE status IN ('en-desarrollo', 'consolidado') ORDER BY status = 'consolidado', last_modified DESC LIMIT 6")]
        por_escribir = [pick(r) for r in conn.execute(
            "SELECT * FROM notes WHERE status = 'por-escribir' ORDER BY last_modified DESC LIMIT 5")]
        # consolidadas que más tiempo llevan sin repasar: lo que antes se olvida
        olvidadas = [pick(r) for r in conn.execute(
            "SELECT * FROM notes WHERE status = 'consolidado' AND encrypted = 0 ORDER BY COALESCE(last_reviewed, 0) ASC, last_modified ASC LIMIT 5")]
        flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE next_review <= ?", (tomorrow,)).fetchone()[0]
    return {"estados": estados, "total": sum(estados.values()), "recientes": recientes, "por_escribir": por_escribir,
            "olvidadas": olvidadas, "flashcards": flash, "now": now}
