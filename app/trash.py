"""
Papelera única: lo borrado de notas, tareas/ideas/rutinas, eventos, platos, ingredientes y
comidas del plan (suelto o en lote) queda 30 días en el `undo_log` de su BD (core/undo.py),
con las notas movidas a data/trash/<token>/. Desde aquí se lista, se restaura y se vacía
(entrada a entrada o entera). Cada día a las 03:40 se purga lo que pasa de 30 días.
"""
import json
import shutil
import time

from fastapi import APIRouter, HTTPException

from app.database import get_db
from core import config, undo
from core.logging_config import get_logger

log = get_logger("trash")
router = APIRouter(prefix="/api/trash")

KINDS = {
    ("brain", "notes.delete"): ("nota", "notebook-pen"),
    ("brain", "items"): ("tarea", "square-check"),
    ("brain", "event.delete"): ("evento", "calendar"),
    ("comidas", "meals.delete"): ("plato", "utensils-crossed"),
    ("comidas", "ingredients.delete"): ("ingrediente", "salad"),
    ("comidas", "plan.delete"): ("comida del plan", "calendar-days"),
    ("brain", "finance.movements"): ("movimiento", "receipt"),
    ("brain", "finance.accounts"): ("cuenta", "wallet"),
    ("brain", "finance.debts"): ("deuda", "hand-coins"),
    ("brain", "finance.wishes"): ("deseo", "shopping-bag"),
    ("brain", "finance.recurring"): ("recurrente", "repeat"),
}


def _db(name: str):
    if name == "brain":
        return get_db()
    if name == "comidas":
        from comidas.database import get_db as comidas_db
        return comidas_db()
    raise HTTPException(status_code=404, detail="Papelera desconocida")


ITEM_LABELS = {"nota": ("idea", "lightbulb"), "rutina": ("rutina", "repeat"), "tarea": ("tarea", "square-check")}


def _item_label(conn, token: str) -> tuple[str, str] | None:
    row = conn.execute("SELECT payload FROM undo_log WHERE token=?", (token,)).fetchone()
    try:
        rows = json.loads(row["payload"])["rows"]
        types = {r.get("item_type") or "tarea" for r in rows if r.get("parent_id") is None or len(rows) == 1}
    except (TypeError, ValueError, KeyError):
        return None
    return ITEM_LABELS.get(types.pop()) if len(types) == 1 else None


def list_entries() -> list[dict]:
    out = []
    for name in ("brain", "comidas"):
        with _db(name) as conn:
            for e in undo.entries(conn):
                meta = KINDS.get((name, e["kind"]))
                if not meta:
                    continue  # otros «deshacer» internos (ediciones en lote…)
                label, iconn = meta
                if (name, e["kind"]) == ("brain", "items"):  # una idea o una rutina no es «tarea»
                    label, iconn = _item_label(conn, e["token"]) or meta
                out.append({**e, "db": name, "label": label, "icon": iconn,
                            "expires_at": e["created_at"] + undo.TTL_S})
    return sorted(out, key=lambda e: -e["created_at"])


def restore(db: str, token: str) -> dict:
    with _db(db) as conn:
        kind = next((e["kind"] for e in undo.entries(conn) if e["token"] == token), None)
    if kind is None:
        raise HTTPException(status_code=404, detail="Ya no está en la papelera")
    if db == "brain" and kind == "notes.delete":
        from app.bulk import bulk_undo
        return {"restored": bulk_undo(token)["restored"], "kind": kind}
    if db == "brain" and kind == "items":
        from app.items import restore as restore_items
        return {"restored": restore_items(token), "kind": kind}
    if db == "brain" and kind == "event.delete":
        from app.calendar import restore_event
        with get_db() as conn:
            found = undo.pop(conn, token, "event.")
            return {"restored": restore_event(conn, found[1]) if found else 0, "kind": kind}
    if db == "brain" and kind.startswith("finance."):
        from app.finance import restore as restore_finance
        with get_db() as conn:
            found = undo.pop(conn, token, "finance.")
            return {"restored": restore_finance(conn, found[1]) if found else 0, "kind": kind}
    if db == "comidas":
        from comidas.bulk import bulk_undo as comidas_undo
        return {"restored": comidas_undo(token)["restored"], "kind": kind}
    raise HTTPException(status_code=404, detail="No se puede restaurar")


def _drop_files(token: str) -> None:
    folder = config.TRASH_DIR / token
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def remove(db: str, token: str) -> bool:
    with _db(db) as conn:
        ok = undo.drop(conn, token)
    _drop_files(token)
    return ok


def empty() -> int:
    n = 0
    for name in ("brain", "comidas"):
        with _db(name) as conn:
            for e in undo.entries(conn):
                if (name, e["kind"]) in KINDS:
                    undo.drop(conn, e["token"])
                    _drop_files(e["token"])
                    n += 1
    return n


def purge_expired() -> int:
    """Vaciado automático: lo que lleva más de 30 días (y las carpetas de notas huérfanas)."""
    n = 0
    for name in ("brain", "comidas"):
        with _db(name) as conn:
            n += undo.purge(conn)
    if config.TRASH_DIR.exists():
        alive = {e["token"] for e in list_entries()}
        limit = time.time() - undo.TTL_S
        for entry in config.TRASH_DIR.iterdir():
            if entry.is_dir() and entry.name not in alive and entry.stat().st_mtime < limit:
                shutil.rmtree(entry, ignore_errors=True)
    if n:
        log.info("Papelera: %d entradas caducadas eliminadas", n)
    return n


@router.get("")
def api_list():
    entries = list_entries()
    return {"entries": entries, "count": len(entries), "ttl_days": undo.TTL_S // 86400}


@router.post("/{db}/{token}/restore")
def api_restore(db: str, token: str):
    return {"status": "success", **restore(db, token)}


@router.delete("/{db}/{token}")
def api_remove(db: str, token: str):
    if not remove(db, token):
        raise HTTPException(status_code=404, detail="Ya no está en la papelera")
    return {"status": "success"}


@router.delete("")
def api_empty():
    return {"status": "success", "removed": empty()}
