"""
Contador en marcha (P-2): «empezar» una tarea, un paso, una rutina o una actividad libre y medir su tiempo.

    GET  /api/contador                      la sesión activa (o null) + `ahora` (hora del servidor) + `reciente`
                                            (la que se cerró sola a medianoche, para avisar una vez)
    POST /api/contador/empezar              {item_id} o {titulo}; con `prevista_min` opcional. Si había otra activa
                                            se cierra («cambio»); si es la misma y está en pausa, sigue
    POST /api/contador/pausar | seguir | quitar | completar     (completar marca el elemento hecho)
    POST /api/contador/recuperar            tras una pausa automática (sin señal): cuenta también ese hueco
    POST /api/contador/latido               «sigo aquí» de los clientes (navegador cada minuto, Waybar)
    GET  /api/contador/tiempos?desde=&hasta=   tiempo por día y por elemento (Revisión)

Una sola sesión activa (en marcha o en pausa): `sesiones.activa` = 1 con índice único. El tiempo son los tramos
(`sesion_tramos`): uno abierto = en marcha. Los clientes no preguntan cada segundo: calculan
`segundos + (ahora - tramo_inicio)` con la hora del servidor.

Reglas que se aplican de forma perezosa en cada lectura o escritura (`normalizar`), sin programador:
- Medianoche: una sesión de un día anterior se cierra a las 00:00 de ese día siguiente (`cierre='medianoche'`).
- Sin señal: el servidor corre en el portátil, así que si este se apaga o se suspende el reloj sigue corriendo. Si
  al leer (o en un latido) hay un tramo abierto y el último latido es de hace más de SIN_SENAL, el tramo se cierra en
  ese latido y la sesión queda en pausa (`auto_pausa`); «recuperar» reabre el tramo si sí se estaba haciendo. Una
  acción (pausar, completar…) no la aplica: quien pulsa estaba ahí.
"""

import threading
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import contextos, items
from app.calendar import TZ
from app.database import get_db

router = APIRouter(prefix="/api/contador")

SIN_SENAL = 45 * 60
_lock = threading.Lock()


class EmpezarIn(BaseModel):
    item_id: int | None = None
    titulo: str | None = Field(default=None, max_length=200)
    prevista_min: int | None = Field(default=None, ge=1, le=1440)


class CompletarIn(BaseModel):
    marcar: bool = True  # False: solo cierra la sesión (el paso a paso ya marca el paso por su cuenta)


# ─────────────────────────────────────────────
# Fechas
# ─────────────────────────────────────────────


def dia_de(ts: float) -> str:
    return datetime.fromtimestamp(ts, TZ).date().isoformat()


def medianoche_tras(dia: str) -> float:
    """Las 00:00 (hora de Madrid) del día siguiente a `dia`."""
    return datetime.combine(date.fromisoformat(dia) + timedelta(days=1), dtime.min, tzinfo=TZ).timestamp()


def trocear(inicio: float, fin: float):
    """(día, segundos) de un tramo, partido por las medianoches que cruce."""
    while inicio < fin:
        d = dia_de(inicio)
        corte = min(fin, medianoche_tras(d))
        yield d, corte - inicio
        inicio = corte


# ─────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────


def _activa(conn):
    return conn.execute("SELECT * FROM sesiones WHERE activa = 1").fetchone()


def _tramo_abierto(conn, sid: int):
    return conn.execute("SELECT * FROM sesion_tramos WHERE sesion_id=? AND fin IS NULL", (sid,)).fetchone()


def _cerrar(conn, s, cuando: float, cierre: str) -> None:
    conn.execute("UPDATE sesion_tramos SET fin=? WHERE sesion_id=? AND fin IS NULL", (cuando, s["id"]))
    conn.execute("UPDATE sesiones SET fin=?, cierre=?, activa=NULL WHERE id=?", (cuando, cierre, s["id"]))


def normalizar(conn, now: float, senal: bool = True) -> None:
    """Aplica «sin señal» (solo en lecturas y latidos: una acción del usuario ya dice que estaba ahí) y «medianoche»
    a la sesión activa (si la hay)."""
    s = _activa(conn)
    if not s:
        return
    t = _tramo_abierto(conn, s["id"]) if senal else None
    if t:
        visto = max(s["latido"] or 0, t["inicio"])
        if now - visto > SIN_SENAL:
            # sin señal: se para donde se la vio por última vez (si el corte de medianoche es antes, ya lo hará él)
            conn.execute("UPDATE sesion_tramos SET fin=? WHERE id=?", (visto, t["id"]))
            conn.execute("UPDATE sesiones SET auto_pausa=? WHERE id=?", (visto, s["id"]))
    lim = medianoche_tras(s["dia"])
    if now >= lim:
        _cerrar(conn, s, lim, "medianoche")  # el tramo abierto (si lo hay) acaba a las 00:00


def _segundos(conn, sid: int, now: float) -> tuple[float, float | None]:
    """(segundos de los tramos cerrados, inicio del tramo abierto o None)."""
    cerrado, abierto = 0.0, None
    for t in conn.execute("SELECT inicio, fin FROM sesion_tramos WHERE sesion_id=?", (sid,)):
        if t["fin"] is None:
            abierto = t["inicio"]
        else:
            cerrado += t["fin"] - t["inicio"]
    return cerrado, abierto


def _padre(conn, item_id: int | None) -> str | None:
    if not item_id:
        return None
    r = conn.execute(
        "SELECT p.content FROM inbox i JOIN inbox p ON p.id = i.parent_id WHERE i.id=?", (item_id,)
    ).fetchone()
    return items.clean_text(r["content"]).split("\n")[0] if r else None


def serializar(conn, s, now: float) -> dict:
    cerrado, abierto = _segundos(conn, s["id"], now)
    total = cerrado + (now - abierto if abierto else 0)
    return {
        "id": s["id"],
        "item_id": s["item_id"],
        "titulo": s["titulo"],
        "padre": _padre(conn, s["item_id"]),
        "tipo": s["tipo"],
        "contexto": s["contexto"] or "puntual",
        "prevista_min": s["prevista_min"],
        "estado": "cerrada" if s["activa"] is None else ("marcha" if abierto else "pausa"),
        "inicio": s["inicio"],
        "segundos": round(cerrado, 3),
        "tramo_inicio": abierto,
        "transcurrido": round(total),
        "pasada": bool(s["prevista_min"] and total > s["prevista_min"] * 60),
        "auto_pausa": s["auto_pausa"],
        "cierre": s["cierre"],
        "href": f"/tareas?item={s['item_id']}" if s["item_id"] else None,
    }


def estado(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock, get_db() as conn:
        normalizar(conn, now)
        s = _activa(conn)
        reciente = conn.execute(
            "SELECT * FROM sesiones WHERE cierre='medianoche' AND fin > ? ORDER BY fin DESC LIMIT 1",
            (now - 12 * 3600,),
        ).fetchone()
        return {
            "ahora": now,
            "activa": serializar(conn, s, now) if s else None,
            "reciente": serializar(conn, reciente, now) if reciente and not s else None,
        }


# ─────────────────────────────────────────────
# Acciones
# ─────────────────────────────────────────────


def _de_item(conn, item_id: int) -> dict:
    r = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Esa tarea ya no existe")
    tipo = items.item_type(r)
    if tipo == "rutina" and r["parent_id"]:
        tipo = "paso"
    lab = contextos.label(r, contextos.containers(conn))
    return {
        "item_id": r["id"],
        "titulo": items.clean_text(r["content"]).split("\n")[0][:200],
        "tipo": tipo,
        "contexto": lab.get("contexto"),
        "asignatura_id": lab.get("asignatura_id"),
        "prevista_min": r["duration_min"] or None,
    }


def empezar(data: EmpezarIn, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    titulo = (data.titulo or "").strip()
    if not data.item_id and not titulo:
        raise HTTPException(status_code=422, detail="Di qué empiezas: una tarea o un título")
    with _lock, get_db() as conn:
        normalizar(conn, now, senal=False)
        nueva = (
            _de_item(conn, data.item_id)
            if data.item_id
            else {
                "item_id": None,
                "titulo": titulo,
                "tipo": "libre",
                "contexto": None,
                "asignatura_id": None,
                "prevista_min": None,
            }
        )
        if data.prevista_min:
            nueva["prevista_min"] = data.prevista_min
        s = _activa(conn)
        if s and data.item_id and s["item_id"] == data.item_id:  # la misma: sigue (si estaba en pausa)
            if not _tramo_abierto(conn, s["id"]):
                conn.execute("INSERT INTO sesion_tramos (sesion_id, inicio) VALUES (?, ?)", (s["id"], now))
            conn.execute("UPDATE sesiones SET latido=?, auto_pausa=NULL WHERE id=?", (now, s["id"]))
            return serializar(conn, _activa(conn), now)
        if s:
            _cerrar(conn, s, now, "cambio")
        cur = conn.execute(
            """INSERT INTO sesiones (item_id, titulo, tipo, contexto, asignatura_id, prevista_min, dia, inicio, activa,
                                     latido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                nueva["item_id"],
                nueva["titulo"],
                nueva["tipo"],
                nueva["contexto"],
                nueva["asignatura_id"],
                nueva["prevista_min"],
                dia_de(now),
                now,
                now,
            ),
        )
        conn.execute("INSERT INTO sesion_tramos (sesion_id, inicio) VALUES (?, ?)", (cur.lastrowid, now))
        return serializar(conn, _activa(conn), now)


def _con_activa(now: float, fn) -> dict | None:
    with _lock, get_db() as conn:
        normalizar(conn, now, senal=False)
        s = _activa(conn)
        if not s:
            raise HTTPException(status_code=409, detail="No hay nada en marcha")
        out = fn(conn, s)
        s2 = conn.execute("SELECT * FROM sesiones WHERE id=?", (s["id"],)).fetchone()
        return out if out is not None else serializar(conn, s2, now)


def pausar(now: float | None = None) -> dict:
    now = time.time() if now is None else now

    def fn(conn, s):
        conn.execute("UPDATE sesion_tramos SET fin=? WHERE sesion_id=? AND fin IS NULL", (now, s["id"]))
        conn.execute("UPDATE sesiones SET latido=? WHERE id=?", (now, s["id"]))

    return _con_activa(now, fn)


def seguir(now: float | None = None) -> dict:
    now = time.time() if now is None else now

    def fn(conn, s):
        if not _tramo_abierto(conn, s["id"]):
            conn.execute("INSERT INTO sesion_tramos (sesion_id, inicio) VALUES (?, ?)", (s["id"], now))
        conn.execute("UPDATE sesiones SET latido=?, auto_pausa=NULL WHERE id=?", (now, s["id"]))

    return _con_activa(now, fn)


def recuperar(now: float | None = None) -> dict:
    """Tras una pausa automática: el hueco sin señal sí contaba (se reabre el último tramo)."""
    now = time.time() if now is None else now

    def fn(conn, s):
        if not s["auto_pausa"] or _tramo_abierto(conn, s["id"]):
            raise HTTPException(status_code=409, detail="No hay ningún hueco que recuperar")
        t = conn.execute(
            "SELECT id FROM sesion_tramos WHERE sesion_id=? ORDER BY fin DESC LIMIT 1", (s["id"],)
        ).fetchone()
        conn.execute("UPDATE sesion_tramos SET fin=NULL WHERE id=?", (t["id"],))
        conn.execute("UPDATE sesiones SET latido=?, auto_pausa=NULL WHERE id=?", (now, s["id"]))

    return _con_activa(now, fn)


def cerrar(cierre: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return _con_activa(now, lambda conn, s: _cerrar(conn, s, now, cierre))


def completar(data: CompletarIn, now: float | None = None) -> dict:
    out = cerrar("completada", now)
    if data.marcar and out["item_id"] and out["tipo"] != "libre":
        try:
            items.set_done(out["item_id"], True)  # fuera del bloque de BD: abre su propia conexión de escritura
        except HTTPException as e:
            if e.status_code != 404:
                raise
    return out


def latido(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock, get_db() as conn:
        normalizar(conn, now)  # antes de anotar el latido: si hubo un hueco, se ve con el latido viejo
        conn.execute("UPDATE sesiones SET latido=? WHERE activa = 1", (now,))
    return estado(now)


# ─────────────────────────────────────────────
# Tiempo registrado
# ─────────────────────────────────────────────


def tiempo_por_item(conn, now: float | None = None) -> dict[int, int]:
    """Segundos por elemento (todas sus sesiones, también la que está en marcha)."""
    now = time.time() if now is None else now
    out: dict[int, float] = {}
    for r in conn.execute(
        """SELECT s.item_id, SUM(COALESCE(t.fin, ?) - t.inicio) AS seg FROM sesiones s
           JOIN sesion_tramos t ON t.sesion_id = s.id WHERE s.item_id IS NOT NULL GROUP BY s.item_id""",
        (now,),
    ):
        out[r["item_id"]] = r["seg"]
    return {k: int(v) for k, v in out.items() if v >= 1}


def tiempos(desde: str, hasta: str, now: float | None = None) -> dict:
    """Por día (de `desde` a `hasta`, ambos incluidos) y por elemento, partiendo los tramos por medianoche."""
    now = time.time() if now is None else now
    d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    lo = datetime.combine(d0, dtime.min, tzinfo=TZ).timestamp()
    hi = medianoche_tras(d1.isoformat())
    por_dia = {(d0 + timedelta(days=i)).isoformat(): 0.0 for i in range((d1 - d0).days + 1)}
    por_item: dict[tuple, dict] = {}
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.item_id, s.titulo, s.tipo, s.contexto, s.asignatura_id, t.inicio,
                      COALESCE(t.fin, ?) AS fin
               FROM sesion_tramos t JOIN sesiones s ON s.id = t.sesion_id
               WHERE t.inicio < ? AND COALESCE(t.fin, ?) > ?""",
            (now, hi, now, lo),
        ).fetchall()
        vivos = {r["id"] for r in conn.execute("SELECT id FROM inbox")}
    for r in rows:
        for d, seg in trocear(max(r["inicio"], lo), min(r["fin"], hi)):
            if d not in por_dia:
                continue
            por_dia[d] += seg
            k = ("item", r["item_id"]) if r["item_id"] else ("libre", r["titulo"].lower())
            e = por_item.setdefault(
                k,
                {
                    "item_id": r["item_id"],
                    "titulo": r["titulo"],
                    "tipo": r["tipo"],
                    "contexto": r["contexto"] or "puntual",
                    "asignatura_id": r["asignatura_id"],
                    "existe": r["item_id"] in vivos if r["item_id"] else None,
                    "segundos": 0.0,
                    "dias": {},
                },
            )
            e["segundos"] += seg
            e["dias"][d] = e["dias"].get(d, 0) + seg
    lista = sorted(por_item.values(), key=lambda e: -e["segundos"])
    for e in lista:
        e["segundos"] = int(e["segundos"])
        e["dias"] = {d: int(v) for d, v in e["dias"].items()}
    return {
        "desde": desde,
        "hasta": hasta,
        "por_dia": {d: int(v) for d, v in por_dia.items()},
        "total": int(sum(por_dia.values())),
        "elementos": [e for e in lista if e["segundos"] >= 60],
    }


def bloques_de_estudio(fecha: str) -> list[dict]:
    """Rendimiento: lo cronometrado ese día en Universidad, por asignatura (sigla = código), como bloques propuestos.
    Menos de 10 minutos no es un bloque."""
    t = tiempos(fecha, fecha)
    with get_db() as conn:
        siglas = {r["id"]: r["codigo"] for r in conn.execute("SELECT id, codigo FROM asignaturas")}
    por: dict[str, dict] = {}
    for e in t["elementos"]:
        if e["contexto"] != "universidad" and not e["asignatura_id"]:
            continue
        sigla = siglas.get(e["asignatura_id"]) or "UNI"
        b = por.setdefault(sigla, {"asignatura": sigla, "minutos": 0, "de": []})
        b["minutos"] += round(e["segundos"] / 60)
        b["de"].append(e["titulo"])
    return [b for b in por.values() if b["minutos"] >= 10]


# ─────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────


@router.get("")
def api_estado():
    return estado()


@router.post("/empezar")
def api_empezar(data: EmpezarIn):
    return {"activa": empezar(data), "ahora": time.time()}


@router.post("/pausar")
def api_pausar():
    return {"activa": pausar(), "ahora": time.time()}


@router.post("/seguir")
def api_seguir():
    return {"activa": seguir(), "ahora": time.time()}


@router.post("/recuperar")
def api_recuperar():
    return {"activa": recuperar(), "ahora": time.time()}


@router.post("/quitar")
def api_quitar():
    return {"cerrada": cerrar("quitada"), "activa": None, "ahora": time.time()}


@router.post("/completar")
def api_completar(data: CompletarIn | None = None):
    return {"cerrada": completar(data or CompletarIn()), "activa": None, "ahora": time.time()}


@router.post("/latido")
def api_latido():
    return latido()


@router.get("/tiempos")
def api_tiempos(desde: str | None = None, hasta: str | None = None):
    hoy = datetime.now(TZ).date()
    try:
        d0 = date.fromisoformat(desde) if desde else hoy - timedelta(days=hoy.weekday())
        d1 = date.fromisoformat(hasta) if hasta else d0 + timedelta(days=6)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Fechas como AAAA-MM-DD") from e
    if d1 < d0 or (d1 - d0).days > 366:
        raise HTTPException(status_code=422, detail="Rango de fechas no válido")
    return tiempos(d0.isoformat(), d1.isoformat())
