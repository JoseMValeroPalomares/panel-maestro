"""
Auditoría de rendimiento (página /rendimiento, tablas rend_*, migración 17).

Un registro por día: la noche anterior (acostarse, pantallas, despertar, calidad), la mañana (café,
activación, luz), los bloques de estudio, la tarde (dopamina, siesta, comida, entreno) y el estado subjetivo.
Las reglas y los semáforos son deterministas (app/rendimiento_rules.py); la IA solo redacta la auditoría.

    GET    /api/rendimiento/dia?fecha=        registro + bloques, o una sugerencia (último registro + rutinas marcadas)
    PUT    /api/rendimiento/dia/{fecha}       guarda el día entero (los bloques se sustituyen)
    DELETE /api/rendimiento/dia/{fecha}       a la papelera («rendimiento.dia»)
    GET    /api/rendimiento/panel?fecha=      semáforos y alertas de ese día
    GET    /api/rendimiento/serie?dias=&hasta= métricas por día (semana / mes)
    GET    /api/rendimiento/examenes          asignaturas: próximos exámenes (del calendario), horas y deuda
    PUT    /api/rendimiento/asignaturas/{sigla} {objetivo_h}
    GET    /api/rendimiento/correlaciones     sueño de la noche anterior vs minutos y estado (≥ N días)
    GET/PUT /api/rendimiento/ajustes          umbrales y qué rutina precarga cada campo
"""
import json
import re
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import rendimiento_rules as R
from app.database import get_db
from core import undo

router = APIRouter(prefix="/api/rendimiento")

HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPCIONES = {
    "activacion": ("si", "parcial", "no"),
    "siesta": ("ninguna", "corta", "larga"),
    "comida_tarde": ("baja", "alta"),
    "codificacion": ("codigo", "esquema", "problemas", "lectura"),
    "pausas": ("sistematico", "ocasional", "no"),
    "estado": ("funcional", "degradado"),
}
# Campos del día que la sugerencia copia del último registro (hábitos que cambian poco)
HABITOS = ("acostarse", "despertar", "primer_cafe", "pantallas_off", "activacion", "luz_solar", "siesta", "comida_tarde")
# Rutinas que precargan un campo si están marcadas ese día (se buscan por nombre si no se eligieron en ajustes)
RUTINA_CAMPOS = {
    "despertar": ("Despertar", r"levant|despert"),
    "luz_solar": ("Luz solar", r"\bsol\b|luz"),
    "activacion": ("Activación matutina", r"activaci|movilidad|estiramient"),
    "entreno": ("Entreno", r"gimnasio|gym|entren|correr|deporte"),
}


def _fecha(f: str | None) -> str:
    if not f:
        return date.today().isoformat()
    if not FECHA.match(f):
        raise HTTPException(status_code=422, detail="Fecha no válida (AAAA-MM-DD)")
    try:
        date.fromisoformat(f)
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida")
    return f


def _hora(v):
    if v in (None, ""):
        return None
    v = str(v).strip()
    if len(v) == 4 and v[1] == ":":
        v = "0" + v
    if not HORA.match(v):
        raise ValueError("Hora no válida (HH:MM)")
    return v


def _opcion(campo):
    def check(v):
        if v in (None, ""):
            return None
        if v not in OPCIONES[campo]:
            raise ValueError(f"Valor no válido: {v}")
        return v
    return check


# ─────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────

class BloqueIn(BaseModel):
    asignatura: str = Field(min_length=1, max_length=60)
    minutos: int = Field(ge=1, le=600)
    recall: bool = False
    codificacion: str = "problemas"
    pausas: str = "ocasional"
    caida: str | None = None
    estado: str = "funcional"

    @field_validator("codificacion", "pausas", "estado")
    @classmethod
    def v_opcion(cls, v, info):
        return _opcion(info.field_name)(v) or BloqueIn.model_fields[info.field_name].default

    @field_validator("caida")
    @classmethod
    def v_caida(cls, v):
        return _hora(v)

    @field_validator("asignatura")
    @classmethod
    def _asig(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Falta la asignatura")
        return v


class DiaIn(BaseModel):
    acostarse: str | None = None
    despertar: str | None = None
    calidad_sueno: int | None = Field(default=None, ge=1, le=5)
    primer_cafe: str | None = None
    pantallas_off: str | None = None
    activacion: str | None = None
    luz_solar: bool | None = None
    dopamina: bool | None = None
    dopamina_hora: str | None = None
    siesta: str | None = None
    comida_tarde: str | None = None
    entreno: bool | None = None
    entreno_fin: str | None = None
    entreno_min: int | None = Field(default=None, ge=0, le=600)
    entreno_intensidad: int | None = Field(default=None, ge=1, le=5)
    energia: int | None = Field(default=None, ge=1, le=5)
    niebla: int | None = Field(default=None, ge=1, le=5)
    dolor_cabeza: int | None = Field(default=None, ge=0, le=3)
    humor: int | None = Field(default=None, ge=1, le=5)
    nota: str | None = Field(default=None, max_length=4000)
    bloques: list[BloqueIn] = Field(default_factory=list, max_length=30)

    @field_validator("acostarse", "despertar", "primer_cafe", "pantallas_off", "dopamina_hora", "entreno_fin")
    @classmethod
    def v_horas(cls, v):
        return _hora(v)

    @field_validator("activacion", "siesta", "comida_tarde")
    @classmethod
    def v_opcion(cls, v, info):
        return _opcion(info.field_name)(v)


COLUMNAS = [f for f in DiaIn.model_fields if f != "bloques"]


class AsignaturaIn(BaseModel):
    objetivo_h: float | None = Field(default=None, ge=0, le=2000)


# ─────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────

def ajustes(conn) -> dict:
    aj = dict(R.DEFAULTS)
    for r in conn.execute("SELECT clave, valor FROM rend_ajustes"):
        try:
            aj[r["clave"]] = json.loads(r["valor"])
        except ValueError:
            pass
    return aj


def _dias(conn, desde: str, hasta: str) -> dict[str, dict]:
    dias = {r["fecha"]: {**dict(r), "bloques": []} for r in
            conn.execute("SELECT * FROM rend_dias WHERE fecha BETWEEN ? AND ?", (desde, hasta))}
    for b in conn.execute("SELECT * FROM rend_bloques WHERE fecha BETWEEN ? AND ? ORDER BY fecha, orden, id", (desde, hasta)):
        if b["fecha"] in dias:
            dias[b["fecha"]]["bloques"].append(dict(b))
    return dias


def _rutinas_mapa(conn, aj: dict) -> dict[str, dict]:
    """campo → rutina (id, título). La elegida en ajustes manda; si no, la primera cuyo nombre encaje."""
    elegidas = aj.get("rutinas") or {}
    filas = conn.execute("SELECT id, content, due_time, duration_min FROM inbox WHERE item_type='rutina' AND status != 'done' ORDER BY id").fetchall()
    por_id = {r["id"]: r for r in filas}
    out = {}
    for campo, (_, patron) in RUTINA_CAMPOS.items():
        rid = elegidas.get(campo)
        if rid == 0:  # «ninguna» a propósito
            continue
        r = por_id.get(rid) if rid else next((f for f in filas if re.search(patron, f["content"] or "", re.I)), None)
        if r:
            out[campo] = dict(r)
    return out


def _sugerencia(conn, fecha: str, aj: dict) -> tuple[dict, dict]:
    """Valores por defecto: hábitos del último registro y, encima, lo que digan las rutinas marcadas ese día."""
    sug, fuentes = {}, {}
    prev = conn.execute("SELECT * FROM rend_dias WHERE fecha < ? ORDER BY fecha DESC LIMIT 1", (fecha,)).fetchone()
    if prev:
        for k in HABITOS:
            if prev[k] is not None:
                sug[k] = prev[k]
                fuentes[k] = "último registro"
    for campo, r in _rutinas_mapa(conn, aj).items():
        chk = conn.execute("SELECT at FROM routine_checks WHERE item_id=? AND day=?", (r["id"], fecha)).fetchone()
        hecho = bool(chk)
        hora = r["due_time"] or (datetime.fromtimestamp(chk["at"]).strftime("%H:%M") if chk else None)
        etiqueta = f"rutina «{r['content']}»"
        if campo == "despertar" and hecho and hora:
            sug["despertar"], fuentes["despertar"] = hora, etiqueta
        elif campo == "luz_solar":
            sug["luz_solar"], fuentes["luz_solar"] = int(hecho), etiqueta
        elif campo == "activacion" and hecho:
            sug["activacion"], fuentes["activacion"] = "si", etiqueta
        elif campo == "entreno":
            sug["entreno"], fuentes["entreno"] = int(hecho), etiqueta
            if hecho and r["due_time"]:
                fin = R.minutos(r["due_time"]) + (r["duration_min"] or 0)
                if r["duration_min"] and r["duration_min"] >= 20:
                    sug["entreno_fin"], sug["entreno_min"] = R.hhmm(fin), r["duration_min"]
                    fuentes["entreno_fin"] = fuentes["entreno_min"] = etiqueta
    return sug, fuentes


def _asignaturas(conn) -> list[str]:
    """Siglas conocidas: exámenes del calendario, objetivos guardados y bloques ya registrados."""
    hoy = date.today()
    desde = (hoy - timedelta(days=180)).isoformat()
    s = set()
    for r in _examenes(conn, desde):
        s.add(r["sigla"])
    s.update(r[0] for r in conn.execute("SELECT sigla FROM rend_asignaturas"))
    usadas = [r[0] for r in conn.execute("SELECT asignatura FROM rend_bloques GROUP BY asignatura ORDER BY MAX(fecha) DESC, COUNT(*) DESC")]
    return usadas + sorted(s - set(usadas), key=str.lower)


def _examenes(conn, desde: str) -> list[dict]:
    out = []
    for r in conn.execute("""SELECT id, title, start FROM events
                             WHERE (kind='examen' OR title LIKE '%xamen%' OR title LIKE '%arcial%') AND substr(start, 1, 10) >= ?
                             ORDER BY start""", (desde,)):
        titulo = r["title"] or ""
        sigla, _, resto = titulo.partition(" · ")
        if not resto:
            sigla, resto = titulo.split(" ")[0], titulo
        out.append({"id": r["id"], "sigla": sigla.strip(), "titulo": resto.strip(), "fecha": r["start"][:10]})
    return out


# ─────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────

@router.get("/dia")
def api_dia(fecha: str | None = None):
    fecha = _fecha(fecha)
    with get_db() as conn:
        aj = ajustes(conn)
        dia = _dias(conn, fecha, fecha).get(fecha)
        sug, fuentes = _sugerencia(conn, fecha, aj)
        return {"fecha": fecha, "registro": dia, "sugerencia": sug, "fuentes": fuentes,
                "asignaturas": _asignaturas(conn), "ajustes": aj}


@router.put("/dia/{fecha}")
def api_guardar(fecha: str, data: DiaIn):
    fecha = _fecha(fecha)
    if fecha > (date.today() + timedelta(days=1)).isoformat():
        raise HTTPException(status_code=422, detail="No se puede registrar un día futuro")
    vals = data.model_dump()
    fila = {k: (int(vals[k]) if isinstance(vals[k], bool) else vals[k]) for k in COLUMNAS}
    if fila["nota"]:
        fila["nota"] = fila["nota"].strip() or None
    if not fila["dopamina"]:
        fila["dopamina_hora"] = None
    if not fila["entreno"]:
        fila["entreno_fin"] = fila["entreno_min"] = fila["entreno_intensidad"] = None
    with get_db() as conn:
        cols = ", ".join(COLUMNAS)
        sets = ", ".join(f"{k}=excluded.{k}" for k in COLUMNAS)
        conn.execute(f"""INSERT INTO rend_dias (fecha, {cols}, actualizado) VALUES (?, {', '.join('?' * len(COLUMNAS))}, ?)
                         ON CONFLICT(fecha) DO UPDATE SET {sets}, actualizado=excluded.actualizado""",
                     [fecha, *fila.values(), time.time()])
        conn.execute("DELETE FROM rend_bloques WHERE fecha=?", (fecha,))
        for i, b in enumerate(data.bloques):
            conn.execute("""INSERT INTO rend_bloques (fecha, asignatura, minutos, recall, codificacion, pausas, caida, estado, orden)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (fecha, b.asignatura, b.minutos, int(b.recall), b.codificacion, b.pausas, b.caida, b.estado, i))
    marcadas = _marcar_rutinas(fecha, fila)  # fuera del bloque: set_done abre su propia conexión de escritura
    out = panel(fecha)
    sincronizar_alertas(fecha, out["alertas"])
    return {"status": "success", "rutinas_marcadas": marcadas, **panel(fecha)}


# ─────────────────────────────────────────────
# Integración: rutinas cumplidas y alertas como tareas
# ─────────────────────────────────────────────

def _marcar_rutinas(fecha: str, fila: dict) -> list[str]:
    """Lo registrado marca su rutina ese día (activación, luz solar, entreno). Solo marca, nunca desmarca."""
    from app.items import set_done
    quiere = {"activacion": fila.get("activacion") == "si", "luz_solar": bool(fila.get("luz_solar")), "entreno": bool(fila.get("entreno"))}
    with get_db() as conn:
        mapa = _rutinas_mapa(conn, ajustes(conn))
        pendientes = [(c, r) for c, r in mapa.items() if quiere.get(c)
                      and not conn.execute("SELECT 1 FROM routine_checks WHERE item_id=? AND day=?", (r["id"], fecha)).fetchone()]
    hechas = []
    for campo, r in pendientes:
        try:
            set_done(r["id"], True, fecha)
            hechas.append(r["content"])
        except HTTPException:  # la rutina se borró entre medias
            continue
    return hechas


def _tarea_alerta(fecha: str, a: dict) -> int | None:
    """Una tarea accionable por regla: si ya hay una pendiente de la misma regla, se reutiliza."""
    from app.items import ItemIn, create
    with get_db() as conn:
        viva = conn.execute("""SELECT a.item_id FROM rend_alertas a JOIN inbox i ON i.id = a.item_id
                              WHERE a.regla=? AND i.status != 'processed' ORDER BY a.fecha DESC LIMIT 1""", (a["id"],)).fetchone()
    if viva:
        return viva["item_id"]
    hoy = date.today().isoformat()
    return create(ItemIn(text=f"Rendimiento · {a['titulo']}", type="tarea", category="Rendimiento",
                         priority="alta" if a["nivel"] == "rojo" else "media", due_date=max(fecha, hoy),
                         details=f"{a['texto']}\n\nDetectado el {fecha}: /rendimiento?fecha={fecha}"))


def sincronizar_alertas(fecha: str, lista: list[dict]) -> None:
    """Guarda las alertas de un día (las que ya no saltan se quitan; su tarea, si la hubo, se queda) y crea las tareas
    de las nuevas. Rellenar días antiguos no crea tareas: solo las de hoy y ayer piden acción."""
    with get_db() as conn:
        prev = {r["regla"]: dict(r) for r in conn.execute("SELECT * FROM rend_alertas WHERE fecha=?", (fecha,))}
        ids = {a["id"] for a in lista}
        for regla in set(prev) - ids:
            conn.execute("DELETE FROM rend_alertas WHERE fecha=? AND regla=?", (fecha, regla))
        nuevas = []
        for a in lista:
            if a["id"] in prev:
                conn.execute("UPDATE rend_alertas SET nivel=?, titulo=?, texto=? WHERE fecha=? AND regla=?", (a["nivel"], a["titulo"], a["texto"], fecha, a["id"]))
            else:
                conn.execute("INSERT INTO rend_alertas (fecha, regla, nivel, titulo, texto) VALUES (?, ?, ?, ?, ?)", (fecha, a["id"], a["nivel"], a["titulo"], a["texto"]))
                nuevas.append(a)
    if fecha < (date.today() - timedelta(days=1)).isoformat():
        return
    for a in nuevas:
        item_id = _tarea_alerta(fecha, a)
        with get_db() as conn:
            conn.execute("UPDATE rend_alertas SET item_id=? WHERE fecha=? AND regla=?", (item_id, fecha, a["id"]))


@router.delete("/dia/{fecha}")
def api_borrar(fecha: str):
    fecha = _fecha(fecha)
    with get_db() as conn:
        dia = _dias(conn, fecha, fecha).get(fecha)
        if not dia:
            raise HTTPException(status_code=404, detail="No hay registro ese día")
        bloques = dia.pop("bloques")
        token = undo.save(conn, "rendimiento.dia", {"dia": dia, "bloques": bloques}, title=f"Registro del {fecha}", count=1)
        conn.execute("DELETE FROM rend_dias WHERE fecha=?", (fecha,))  # los bloques caen en cascada
    return {"status": "success", "trash": token}


def restore(conn, payload: dict) -> int:
    """Papelera: vuelve el día con sus bloques (si ese día se volvió a registrar, gana lo nuevo)."""
    dia = payload["dia"]
    if conn.execute("SELECT 1 FROM rend_dias WHERE fecha=?", (dia["fecha"],)).fetchone():
        return 0
    undo.insert_rows(conn, "rend_dias", [dia])
    undo.insert_rows(conn, "rend_bloques", payload.get("bloques") or [])
    return 1


def panel(fecha: str) -> dict:
    atras = (date.fromisoformat(fecha) - timedelta(days=13)).isoformat()
    with get_db() as conn:
        aj = ajustes(conn)
        dias = _dias(conn, atras, fecha)
        tareas = {r["regla"]: r["item_id"] for r in conn.execute("SELECT regla, item_id FROM rend_alertas WHERE fecha=?", (fecha,))}
    dia = dias.get(fecha)
    alertas = [{**a, "item_id": tareas.get(a["id"])} for a in R.alertas(dias, fecha, aj)]
    return {"fecha": fecha, "registrado": bool(dia), "semaforos": R.semaforos(dia, aj), "alertas": alertas,
            "resumen": R.resumen_bloques((dia or {}).get("bloques") or []), "horas_sueno": R.horas_sueno(dia or {})}


@router.get("/panel")
def api_panel(fecha: str | None = None):
    fecha = _fecha(fecha)
    out = panel(fecha)
    ayer = (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()
    with get_db() as conn:
        out["ayer_registrado"] = bool(conn.execute("SELECT 1 FROM rend_dias WHERE fecha=?", (ayer,)).fetchone())
        out["dias_registrados"] = conn.execute("SELECT COUNT(*) FROM rend_dias").fetchone()[0]
    return out


@router.get("/serie")
def api_serie(dias: int = 7, hasta: str | None = None):
    if not 1 <= dias <= 366:
        raise HTTPException(status_code=422, detail="Entre 1 y 366 días")
    hasta = _fecha(hasta)
    desde = (date.fromisoformat(hasta) - timedelta(days=dias - 1)).isoformat()
    with get_db() as conn:
        aj = ajustes(conn)
        reg = _dias(conn, desde, hasta)
    out = []
    for i in range(dias):
        f = (date.fromisoformat(desde) + timedelta(days=i)).isoformat()
        d = reg.get(f)
        if not d:
            out.append({"fecha": f, "registrado": False})
            continue
        r = R.resumen_bloques(d["bloques"])
        out.append({"fecha": f, "registrado": True, "acostarse": d["acostarse"], "acostarse_min": R.noche(d["acostarse"]),
                    "horas_sueno": R.horas_sueno(d), "minutos": r["minutos"], "bloques": r["n"],
                    "pct_recall": r["pct_recall"], "pct_activa": r["pct_activa"], "dopamina": d["dopamina"],
                    "energia": d["energia"], "niebla": d["niebla"], "humor": d["humor"], "dolor_cabeza": d["dolor_cabeza"]})
    hechos = [x for x in out if x["registrado"]]
    bl = [x for x in hechos if x["bloques"]]

    def media(k, xs):
        v = [x[k] for x in xs if x.get(k) is not None]
        return round(sum(v) / len(v), 1) if v else None

    return {"desde": desde, "hasta": hasta, "dias": out,
            "objetivos": {"acostarse": aj["objetivo_acostarse"], "acostarse_min": R.noche(aj["objetivo_acostarse"]),
                          "limite_acostarse_min": R.noche(aj["limite_acostarse"]), "sueno_h": aj["objetivo_sueno_h"],
                          "max_enfoque_min": aj["max_enfoque_min"]},
            "totales": {"registrados": len(hechos), "minutos": sum(x["minutos"] for x in hechos),
                        "media_sueno": media("horas_sueno", hechos), "media_minutos": media("minutos", hechos),
                        "pct_recall": media("pct_recall", bl), "pct_activa": media("pct_activa", bl),
                        "blindaje": round(100 * sum(1 for x in hechos if not x["dopamina"]) / len(hechos)) if hechos else None,
                        "energia": media("energia", hechos), "niebla": media("niebla", hechos), "humor": media("humor", hechos)}}


@router.get("/alertas")
def api_alertas(dias: int = 30, hasta: str | None = None):
    """Historial de alertas guardadas (cada una con su fecha y la tarea que creó, si sigue existiendo)."""
    if not 1 <= dias <= 366:
        raise HTTPException(status_code=422, detail="Entre 1 y 366 días")
    hasta = _fecha(hasta)
    desde = (date.fromisoformat(hasta) - timedelta(days=dias - 1)).isoformat()
    with get_db() as conn:
        filas = conn.execute("""SELECT a.*, i.status AS tarea_estado FROM rend_alertas a LEFT JOIN inbox i ON i.id = a.item_id
                                WHERE a.fecha BETWEEN ? AND ? ORDER BY a.fecha DESC, a.id DESC""", (desde, hasta)).fetchall()
    return {"alertas": [{**dict(r), "item_id": r["item_id"] if r["tarea_estado"] else None, "tarea_hecha": r["tarea_estado"] == "processed"} for r in filas]}


@router.get("/exportar")
def api_exportar(formato: str = "json", tabla: str = "dias"):
    """Tus registros en CSV (una tabla: días o bloques) o en JSON (todo junto). Nada sale del equipo."""
    from core.tabular import csv_response, json_response
    with get_db() as conn:
        dias = [dict(r) for r in conn.execute("SELECT * FROM rend_dias ORDER BY fecha")]
        bloques = [dict(r) for r in conn.execute("SELECT * FROM rend_bloques ORDER BY fecha, orden, id")]
    hoy = date.today().isoformat()
    if formato == "json":
        por_dia = {}
        for b in bloques:
            por_dia.setdefault(b["fecha"], []).append({k: v for k, v in b.items() if k not in ("id", "fecha")})
        return json_response("dias", [{**d, "bloques": por_dia.get(d["fecha"], [])} for d in dias], f"rendimiento-{hoy}")
    if formato != "csv" or tabla not in ("dias", "bloques"):
        raise HTTPException(status_code=422, detail="formato json o csv; tabla dias o bloques")
    if tabla == "bloques":
        return csv_response(bloques, ["fecha", "orden", "asignatura", "minutos", "recall", "codificacion", "pausas", "caida", "estado"], f"rendimiento-bloques-{hoy}")
    return csv_response(dias, ["fecha", *COLUMNAS], f"rendimiento-dias-{hoy}")


@router.get("/examenes")
def api_examenes():
    hoy = date.today()
    with get_db() as conn:
        futuros = _examenes(conn, hoy.isoformat())
        objetivos = {r["sigla"]: r["objetivo_h"] for r in conn.execute("SELECT * FROM rend_asignaturas")}
        horas = {r["asignatura"]: (r["m"] / 60, r["u"]) for r in conn.execute(
            "SELECT asignatura, SUM(minutos) AS m, MAX(fecha) AS u FROM rend_bloques GROUP BY asignatura")}
        semana = {r["asignatura"]: r["m"] / 60 for r in conn.execute(
            "SELECT asignatura, SUM(minutos) AS m FROM rend_bloques WHERE fecha > ? GROUP BY asignatura", ((hoy - timedelta(days=7)).isoformat(),))}
    siglas = list(dict.fromkeys([e["sigla"] for e in futuros] + list(objetivos) + list(horas)))
    out = []
    for s in siglas:
        exs = [e for e in futuros if e["sigla"] == s]
        prox = exs[0] if exs else None
        hechas, ultima = horas.get(s, (0.0, None))
        obj = objetivos.get(s)
        deuda = round(max(0.0, obj - hechas), 1) if obj else None
        quedan = (date.fromisoformat(prox["fecha"]) - hoy).days if prox else None
        out.append({"sigla": s, "examenes": exs, "proximo": prox, "dias": quedan, "horas": round(hechas, 1),
                    "horas_semana": round(semana.get(s, 0.0), 1), "ultima": ultima, "objetivo_h": obj, "deuda_h": deuda,
                    "ritmo_h_dia": round(deuda / quedan, 1) if deuda and quedan and quedan > 0 else None})
    out.sort(key=lambda x: (x["dias"] is None, x["dias"] if x["dias"] is not None else 0, x["sigla"].lower()))
    return {"asignaturas": out}


@router.put("/asignaturas/{sigla}")
def api_asignatura(sigla: str, data: AsignaturaIn):
    sigla = sigla.strip()
    if not sigla or len(sigla) > 60:
        raise HTTPException(status_code=422, detail="Asignatura no válida")
    with get_db() as conn:
        if data.objetivo_h:
            conn.execute("INSERT INTO rend_asignaturas (sigla, objetivo_h) VALUES (?, ?) ON CONFLICT(sigla) DO UPDATE SET objetivo_h=excluded.objetivo_h",
                         (sigla, data.objetivo_h))
        else:
            conn.execute("DELETE FROM rend_asignaturas WHERE sigla=?", (sigla,))
    return {"status": "success"}


@router.get("/correlaciones")
def api_correlaciones():
    with get_db() as conn:
        aj = ajustes(conn)
        todos = _dias(conn, "0000-01-01", "9999-12-31")
    puntos = []
    for f, d in sorted(todos.items()):
        h = R.horas_sueno(d)
        if h is None:
            continue
        r = R.resumen_bloques(d["bloques"])
        puntos.append({"fecha": f, "horas_sueno": h, "minutos": r["minutos"],
                       "pct_funcional": round(100 * (r["n"] - r["degradados"]) / r["n"]) if r["n"] else None})
    minimo = int(aj["dias_correlacion"])
    out = {"minimo": minimo, "n": len(puntos), "suficiente": len(puntos) >= minimo}
    if out["suficiente"]:
        out["puntos"] = puntos
        out["sueno_minutos"] = R.correlacion([p["horas_sueno"] for p in puntos], [p["minutos"] for p in puntos])
        con = [p for p in puntos if p["pct_funcional"] is not None]
        out["sueno_estado"] = R.correlacion([p["horas_sueno"] for p in con], [p["pct_funcional"] for p in con])
        out["n_estado"] = len(con)
    return out


@router.get("/ajustes")
def api_ajustes():
    with get_db() as conn:
        aj = ajustes(conn)
        rutinas = [dict(r) for r in conn.execute(
            "SELECT id, content FROM inbox WHERE item_type='rutina' AND status != 'done' ORDER BY parent_id IS NOT NULL, content COLLATE NOCASE")]
        mapa = {k: v["id"] for k, v in _rutinas_mapa(conn, aj).items()}
    return {"ajustes": aj, "defaults": R.DEFAULTS,
            "campos": [{"clave": k, "tipo": t, "etiqueta": e, "rango": rg} for k, (t, e, rg) in R.AJUSTES.items()],
            "rutinas": rutinas, "rutinas_campos": [{"clave": k, "etiqueta": e} for k, (e, _) in RUTINA_CAMPOS.items()],
            "rutinas_mapa": mapa}


@router.put("/ajustes")
def api_guardar_ajustes(data: dict):
    limpio = {}
    for k, v in data.items():
        if k == "ia_incluir_nota":
            limpio[k] = bool(v)
            continue
        if k == "ia_prompt":
            if not isinstance(v, str) or len(v) > 6000:
                raise HTTPException(status_code=422, detail="El prompt es un texto de hasta 6000 caracteres")
            limpio[k] = v.strip()
            continue
        if k == "rutinas":
            if not isinstance(v, dict) or any(c not in RUTINA_CAMPOS or not isinstance(i, int) or isinstance(i, bool) for c, i in v.items()):
                raise HTTPException(status_code=422, detail="Rutinas no válidas")
            limpio[k] = v
            continue
        meta = R.AJUSTES.get(k)
        if not meta:
            raise HTTPException(status_code=422, detail=f"Ajuste desconocido: {k}")
        tipo, etiqueta, rango = meta
        try:
            if tipo == "hora":
                v = _hora(v) or R.DEFAULTS[k]
            elif tipo == "int":
                v = int(v)
            else:
                v = round(float(str(v).replace(",", ".")), 2)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{etiqueta}: valor no válido")
        if rango and not rango[0] <= v <= rango[1]:
            raise HTTPException(status_code=422, detail=f"{etiqueta}: entre {rango[0]} y {rango[1]}")
        limpio[k] = v
    with get_db() as conn:
        for k, v in limpio.items():
            if (k in R.DEFAULTS and v == R.DEFAULTS[k]) or (k.startswith("ia_") and v in ("", False)):
                conn.execute("DELETE FROM rend_ajustes WHERE clave=?", (k,))
            else:
                conn.execute("INSERT INTO rend_ajustes (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                             (k, json.dumps(v)))
        return {"status": "success", "ajustes": ajustes(conn)}
