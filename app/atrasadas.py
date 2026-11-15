"""
Tareas atrasadas (P-1): tareas e ideas con fecha pasada que siguen sin hacer, y sus acciones.

    GET  /api/items/atrasadas?contexto=&avisar=1   la lista (respeta el contexto: vacío = el activo; «waybar» = su
                                                   ajuste). Con avisar=1 dice además a cuáles toca avisar ahora
                                                   desde el escritorio (`avisar`: ids).
    POST /api/items/atrasadas/accion              {ids, action, value}: completar · posponer (value = manana,
                                                   sabado o AAAA-MM-DD) · borrar (papelera, devuelve undo_token)
                                                   · hoy_no (calla su aviso hasta mañana)
    POST /api/items/atrasadas/avisadas            {ids}: el escritorio anota a cuáles ya avisó hoy

Las rutinas no cuentan (se marcan por días); lo hecho tampoco. Completar, posponer y borrar pasan por el servicio
de items (`items.bulk`), así que van a item_log, a las notas (casillas) y a la papelera como siempre.

«Hoy no» y «ya avisada hoy» viven en las preferencias (`atrasadas.estado`, una fecha por id): las lee igual el
navegador que la Waybar, y lo de días pasados se olvida solo. La configuración del aviso (activar, hora y días)
va con los demás avisos: `reminders.settings()["atrasadas"]`.
"""

import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import contextos, items
from app.calendar import TZ, ctx_param
from app.database import get_db
from app.prefs import get as get_pref
from app.prefs import put as put_pref

router = APIRouter(prefix="/api/items/atrasadas")

ESTADO = "atrasadas.estado"
ACCIONES = ("completar", "posponer", "borrar", "hoy_no")
_lock = threading.Lock()


class AccionIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    action: str = Field(max_length=12)
    value: str | None = Field(default=None, max_length=10)


class AvisadasIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


def hoy() -> date:
    return datetime.now(TZ).date()


def opciones(d: date) -> dict:
    """Fechas de «Posponer»: mañana y el próximo sábado (si hoy es sábado, el de la semana que viene)."""
    return {
        "manana": (d + timedelta(days=1)).isoformat(),
        "sabado": (d + timedelta(days=(5 - d.weekday()) % 7 or 7)).isoformat(),
    }


def estado(d: date | None = None) -> dict:
    """{"callar": {id: día}, "avisadas": {id: día}} solo con lo de hoy (lo viejo ya no calla nada)."""
    d = (d or hoy()).isoformat()
    raw = get_pref(ESTADO, {}) or {}
    return {k: {i: v for i, v in (raw.get(k) or {}).items() if v == d} for k in ("callar", "avisadas")}


def _marcar(clave: str, ids: list[int], d: date | None = None) -> None:
    d = d or hoy()
    with _lock:
        st = estado(d)
        st[clave].update({str(i): d.isoformat() for i in ids})
        put_pref(ESTADO, st)


def _quitar(ids: list[int]) -> None:
    """Lo pospuesto deja de estar callado (si vuelve a atrasarse, avisa)."""
    with _lock:
        st = estado()
        for k in st:
            for i in ids:
                st[k].pop(str(i), None)
        put_pref(ESTADO, st)


def listar(ctx: str, d: date | None = None) -> list[dict]:
    d = d or hoy()
    callar = estado(d)["callar"]
    with get_db() as conn:
        conts = contextos.containers(conn)
        rows = conn.execute(
            "SELECT * FROM inbox WHERE item_type != 'rutina' AND due_date < ? AND status != 'processed' "
            "ORDER BY due_date, due_time, id LIMIT 200",
            (d.isoformat(),),
        ).fetchall()
        padres = {
            r["id"]: items.clean_text(r["content"]).split("\n")[0]
            for r in conn.execute(
                f"SELECT id, content FROM inbox WHERE id IN ({','.join('?' * len(rows)) or 'NULL'})",
                [r["parent_id"] for r in rows],
            )
        }
    out = []
    for r in rows:
        e = {
            "id": r["id"],
            "title": items.clean_text(r["content"]).split("\n")[0],
            "type": items.item_type(r),
            "origin": items.origin(r),
            "note_id": r["note_id"],
            "parent": padres.get(r["parent_id"]),
            "due_date": r["due_date"],
            "due_time": r["due_time"],
            "dias": (d - date.fromisoformat(r["due_date"])).days,
            "callada": str(r["id"]) in callar,
            "href": f"/tareas?item={r['id']}",
            **contextos.label(r, conts),
        }
        if contextos.matches(e, ctx):
            out.append(e)
    return out


def a_avisar(lista: list[dict], now: datetime | None = None) -> list[int]:
    """A cuáles toca avisar ahora desde el escritorio: aviso activado, ya es la hora, hoy es uno de sus días, y ni
    callada ni avisada hoy. Una vez al día por tarea como mucho."""
    from app.reminders import settings

    now = (now or datetime.now(TZ)).replace(tzinfo=None)
    conf = settings()["atrasadas"]
    if not conf.get("on") or now.weekday() not in (conf.get("dias") or []):
        return []
    if now.strftime("%H:%M") < (conf.get("hora") or "09:00"):
        return []
    avisadas = estado(now.date())["avisadas"]
    return [e["id"] for e in lista if not e["callada"] and str(e["id"]) not in avisadas]


@router.get("")
def api_list(contexto: str | None = None, avisar: bool = False):
    d = hoy()
    ctx = contextos.resolve_filter(contexto) if contexto in (None, "") else ctx_param(contexto)
    lista = listar(ctx, d)
    out = {
        "date": d.isoformat(),
        "contexto": ctx,
        "atrasadas": lista,
        "pendientes": sum(1 for e in lista if not e["callada"]),
        "opciones": opciones(d),
    }
    if avisar:
        out["avisar"] = a_avisar(lista)
    return out


@router.post("/accion")
def api_accion(data: AccionIn):
    if data.action not in ACCIONES:
        raise HTTPException(status_code=422, detail="Acción: completar, posponer, borrar o hoy_no")
    ids = list(dict.fromkeys(data.ids))
    with get_db() as conn:
        found = {r["id"]: r for r in conn.execute(f"SELECT * FROM inbox WHERE id IN ({','.join('?' * len(ids))})", ids)}
    if not found:
        raise HTTPException(status_code=404, detail="Esa tarea ya no existe")
    if any(items.item_type(r) == "rutina" for r in found.values()):
        raise HTTPException(status_code=422, detail="Una rutina no se atrasa: se marca por días")
    ids = [i for i in ids if i in found]
    if data.action == "hoy_no":
        _marcar("callar", ids)
        return {"count": len(ids), "errors": [], "hasta": (hoy() + timedelta(days=1)).isoformat()}
    if data.action == "borrar":
        res = items.bulk(items.BulkIn(ids=ids, action="delete"))
        return {"count": res["count"], "errors": [], "undo_token": res["undo"], "undo_db": "brain"}
    if data.action == "completar":
        return items.bulk(items.BulkIn(ids=ids, action="done"))
    value = opciones(hoy()).get(data.value or "manana", data.value)
    res = items.bulk(items.BulkIn(ids=ids, action="due", value=value))
    _quitar(ids)
    return {**res, "due_date": value}


@router.post("/avisadas")
def api_avisadas(data: AvisadasIn):
    _marcar("avisadas", list(dict.fromkeys(data.ids)))
    return {"status": "success"}
