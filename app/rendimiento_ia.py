"""
Auditoría de rendimiento con IA (usa app/llm_router.py). Las reglas deterministas siguen en rendimiento_rules.py: la
IA solo redacta el diagnóstico y la corrección de cada capa a partir de métricas.

Privacidad: se envían SOLO métricas numéricas y categóricas de los últimos 7 días (fechas como «d-6 … d0»,
asignaturas como «A», «B»…). La nota libre queda fuera salvo que se active `ia_incluir_nota`. OpenRouter recibe
`provider.data_collection = "deny"` (en app/llm_modelos.json).

Caché: si lo que se enviaría es idéntico a una auditoría guardada del mismo periodo (mismo hash), se devuelve esa
sin llamar a nadie, salvo con `forzar`.

    GET  /api/rendimiento/ia/estado        modelos (clave, uso, enfriamiento, última llamada), prompt y opciones
    POST /api/rendimiento/ia/auditar       {tipo: dia|semana, fecha?, forzar?}
    GET  /api/rendimiento/ia/historial     auditorías guardadas, la más nueva primero

Integración: la diaria crea (o actualiza) la tarea «Prioridad de mañana»; la semanal se guarda como nota en
«Rendimiento - Auditorías».
"""
import hashlib
import json
import time
from datetime import date, timedelta

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import llm_router
from app import rendimiento_rules as R
from app.database import get_db
from app.rendimiento import _dias, _examenes, ajustes
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("rendimiento.ia")
router = APIRouter(prefix="/api/rendimiento/ia")

PROMPT_DEFECTO = (
    "Actúa como experto en neurobiología del rendimiento y ciclos ultradianos. Audita los datos según cuatro criterios: "
    "(1) balance metabólico (¿se forzó el sistema más allá del fallo de rendimiento?), (2) calidad de codificación "
    "(Active Recall vs ilusión de competencia), (3) sueño y termorregulación, (4) eficiencia de rotación entre "
    "asignaturas y proyectos. Sé específico, cita los datos concretos del usuario, justifica cada corrección con "
    "terminología neurocientífica (acetilcolina, mielinización, corteza prefrontal, sistema glinfático) sin inventar "
    "cifras, no des consejos genéricos y no hagas diagnósticos médicos. Si hay señales persistentes de fatiga, niebla "
    "mental o cefalea, recomienda descanso y valoración médica."
)
# Fijo (no editable): sin esto el esquema dependería de lo que se escriba en Ajustes
FORMATO = (
    "Responde SOLO con un objeto JSON válido, en español de España, sin texto alrededor, con este esquema exacto:\n"
    '{"capas": {"metabolico": {"estado": "verde|ambar|rojo", "diagnostico": "…", "correccion": "…"}, '
    '"codificacion": {…}, "sueno": {…}, "rotacion": {…}}, "prioridad_manana": "…", "alertas": ["…"]}\n'
    "Cada diagnóstico y corrección: 1-3 frases que citen los datos. «prioridad_manana»: una sola acción concreta para "
    "mañana. «alertas»: lista de frases cortas (vacía si no hay). Las fechas van como d-6 … d0 (d0 = el día auditado) y "
    "las asignaturas como letras: respétalo."
)
CAPAS = ("metabolico", "codificacion", "sueno", "rotacion")
AVISO_PRIVACIDAD = ("Se envían solo métricas de los últimos 7 días, sin fechas reales ni nombres de asignaturas"
                    " y sin tu nota (salvo que la incluyas). Aun así, los niveles gratuitos de algunos proveedores pueden"
                    " usar lo que reciben para entrenar sus modelos (Google, fuera de la UE/EEE/UK, lo hace).")


# ── Entrada (lo que sale del equipo) ──────────────────────────────────────────

def construir_entrada(tipo: str, fecha: str, incluir_nota: bool) -> dict:
    desde = (date.fromisoformat(fecha) - timedelta(days=6)).isoformat()
    with get_db() as conn:
        aj = ajustes(conn)
        dias = _dias(conn, (date.fromisoformat(fecha) - timedelta(days=13)).isoformat(), fecha)  # 14 para las reglas de racha
        examenes = _examenes(conn, fecha)
    letras, n = {}, 0

    def letra(asig: str) -> str:
        nonlocal n
        if asig not in letras:
            letras[asig] = chr(ord("A") + n) if n < 26 else f"X{n}"
            n += 1
        return letras[asig]

    filas = []
    for i in range(6, -1, -1):
        f = (date.fromisoformat(fecha) - timedelta(days=i)).isoformat()
        d = dias.get(f)
        etiqueta = f"d-{i}" if i else "d0"
        dia_semana = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")[date.fromisoformat(f).weekday()]
        if not d:
            filas.append({"dia": etiqueta, "dia_semana": dia_semana, "registrado": False})
            continue
        r = R.resumen_bloques(d["bloques"])
        cafe, desp = R.minutos(d["primer_cafe"]), R.minutos(d["despertar"])
        pant, acost = R.noche(d["pantallas_off"]), R.noche(d["acostarse"])
        fila = {
            "dia": etiqueta, "dia_semana": dia_semana, "registrado": True,
            "acostarse": d["acostarse"], "despertar": d["despertar"], "horas_sueno": R.horas_sueno(d), "calidad_sueno_1_5": d["calidad_sueno"],
            "primer_cafe": d["primer_cafe"], "cafe_min_tras_despertar": cafe - desp if cafe is not None and desp is not None else None,
            "pantallas_min_antes_de_dormir": acost - pant if pant is not None and acost is not None else None,
            "activacion_matutina": d["activacion"], "luz_solar": d["luz_solar"],
            "dopamina_antes_19h": d["dopamina"], "dopamina_hora": d["dopamina_hora"],
            "siesta": {"ninguna": "ninguna", "corta": "15-20 min", "larga": "90 min"}.get(d["siesta"], d["siesta"]),
            "comida_valle_tarde": {"baja": "baja en azúcares", "alta": "alta en carbohidratos simples"}.get(d["comida_tarde"], d["comida_tarde"]),
            "entreno": d["entreno"], "entreno_fin": d["entreno_fin"], "entreno_min": d["entreno_min"], "entreno_intensidad_1_5": d["entreno_intensidad"],
            "energia_1_5": d["energia"], "niebla_1_5": d["niebla"], "dolor_cabeza_0_3": d["dolor_cabeza"], "humor_1_5": d["humor"],
            "enfoque_min": r["minutos"],
            "bloques": [{"asignatura": letra(b["asignatura"]), "min": b["minutos"], "active_recall_previo": bool(b["recall"]),
                         "codificacion": b["codificacion"], "pausas_ojos_cerrados": b["pausas"], "caida_rendimiento": b["caida"],
                         "estado": b["estado"]} for b in d["bloques"]],
        }
        if incluir_nota and d.get("nota"):
            fila["nota"] = d["nota"][:1500]
        filas.append(fila)
    hechos = [x for x in filas if x["registrado"]]

    def media(k):
        v = [x[k] for x in hechos if x.get(k) is not None]
        return round(sum(v) / len(v), 2) if v else None

    bl = [b for x in hechos for b in x["bloques"]]
    agregados = {
        "dias_registrados": len(hechos), "horas_sueno_media": media("horas_sueno"), "enfoque_min_medio": media("enfoque_min"),
        "enfoque_min_total": sum(x["enfoque_min"] for x in hechos), "bloques": len(bl),
        "pct_bloques_con_recall": round(100 * sum(b["active_recall_previo"] for b in bl) / len(bl)) if bl else None,
        "pct_min_codificacion_activa": round(100 * sum(b["min"] for b in bl if b["codificacion"] != "lectura") / max(1, sum(b["min"] for b in bl))) if bl else None,
        "pct_bloques_degradados": round(100 * sum(b["estado"] == "degradado" for b in bl) / len(bl)) if bl else None,
        "dias_con_dopamina_antes_19h": sum(1 for x in hechos if x["dopamina_antes_19h"]),
        "energia_media": media("energia_1_5"), "niebla_media": media("niebla_1_5"), "humor_media": media("humor_1_5"), "dolor_cabeza_medio": media("dolor_cabeza_0_3"),
    }
    proximos = {}
    for e in examenes:
        if e["sigla"] in letras and letras[e["sigla"]] not in proximos:
            proximos[letras[e["sigla"]]] = (date.fromisoformat(e["fecha"]) - date.fromisoformat(fecha)).days
    alertas = [{"regla": a["id"], "titulo": a["titulo"], "detalle": a["texto"]} for a in R.alertas(dias, fecha, aj)]
    return {
        "tipo": "auditoría diaria (d0 es el día auditado)" if tipo == "dia" else "auditoría semanal (d-6 … d0)",
        "objetivos": {"acostarse": aj["objetivo_acostarse"], "limite_acostarse": aj["limite_acostarse"], "horas_sueno": aj["objetivo_sueno_h"],
                      "max_enfoque_min_dia": aj["max_enfoque_min"], "min_entre_despertar_y_cafe": aj["cafe_min_tras_despertar"],
                      "entreno_termina_antes_de": aj["limite_entreno"]},
        "dias": filas, "agregados_7_dias": agregados, "dias_hasta_examen_por_asignatura": proximos,
        "alertas_de_las_reglas": alertas,
    }


# ── Salida ────────────────────────────────────────────────────────────────────

def _texto(v, campo: str, maximo: int = 1500) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"falta «{campo}»")
    return v.strip()[:maximo]


def validar(d: dict) -> dict:
    """Comprueba el esquema y lo normaliza (ámbar → ambar…). Lanza ValueError si no vale."""
    capas = d.get("capas")
    if not isinstance(capas, dict):
        raise ValueError("falta «capas»")
    out = {}
    for c in CAPAS:
        x = capas.get(c)
        if not isinstance(x, dict):
            raise ValueError(f"falta la capa «{c}»")
        estado = str(x.get("estado", "")).strip().lower().replace("á", "a")
        if estado not in ("verde", "ambar", "rojo"):
            raise ValueError(f"estado no válido en «{c}»")
        out[c] = {"estado": estado, "diagnostico": _texto(x.get("diagnostico"), f"{c}.diagnostico"), "correccion": _texto(x.get("correccion"), f"{c}.correccion")}
    alertas = d.get("alertas", [])
    if not isinstance(alertas, list):
        raise ValueError("«alertas» no es una lista")
    limpias = []
    for a in alertas[:10]:
        if isinstance(a, dict):
            a = a.get("texto") or a.get("mensaje") or a.get("descripcion") or a.get("titulo")
        if isinstance(a, str) and a.strip():
            limpias.append(a.strip()[:400])
    return {"capas": out, "prioridad_manana": _texto(d.get("prioridad_manana"), "prioridad_manana", 400), "alertas": limpias}


# ── Auditoría ─────────────────────────────────────────────────────────────────

def _periodo(tipo: str, fecha: str) -> str:
    if tipo == "dia":
        return fecha
    y, w, _ = date.fromisoformat(fecha).isocalendar()
    return f"{y}-W{w:02d}"


def _fila(r) -> dict:
    datos = json.loads(r["texto"])
    return {"id": r["id"], "tipo": r["tipo"], "periodo": r["periodo"], "proveedor": r["proveedor"], "modelo": r["modelo"],
            "creado": r["creado"], **datos}


def auditar(tipo: str, fecha: str, forzar: bool = False, **router_kw) -> dict:
    with get_db() as conn:
        aj = ajustes(conn)
    prompt = aj.get("ia_prompt") or PROMPT_DEFECTO
    entrada = construir_entrada(tipo, fecha, bool(aj.get("ia_incluir_nota")))
    if not any(x["registrado"] for x in entrada["dias"]):
        raise HTTPException(status_code=422, detail="No hay registros en esos 7 días: registra algún día antes de auditar")
    huella = hashlib.sha256(json.dumps([tipo, prompt, entrada], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    periodo = _periodo(tipo, fecha)
    if not forzar:
        with get_db() as conn:
            r = conn.execute("SELECT * FROM rend_auditorias WHERE tipo=? AND periodo=? AND entrada_hash=? ORDER BY id DESC LIMIT 1",
                             (tipo, periodo, huella)).fetchone()
        if r:
            return {**_fila(r), "cache": True}
    mensajes = [{"role": "system", "content": f"{prompt}\n\n{FORMATO}"},
                {"role": "user", "content": "Datos (JSON):\n" + json.dumps(entrada, ensure_ascii=False)}]
    try:
        res = llm_router.completar(mensajes, validar, **router_kw)
    except llm_router.LLMError as e:
        raise HTTPException(status_code=503, detail={"mensaje": str(e), "sin_claves": e.sin_claves, "intentos": e.intentos})
    guardado = {"fecha": fecha, "resultado": res.datos, "latencia_ms": res.latencia_ms, "intentos_fallidos": len(res.intentos)}
    if tipo == "dia":
        guardado["tarea_id"] = _tarea_prioridad(fecha, res.datos["prioridad_manana"])
    else:
        guardado["nota_id"] = _nota_semanal(fecha, periodo, res)
    with get_db() as conn:
        cur = conn.execute("INSERT INTO rend_auditorias (tipo, periodo, proveedor, modelo, texto, entrada_hash) VALUES (?, ?, ?, ?, ?, ?)",
                           (tipo, periodo, res.proveedor, res.modelo, json.dumps(guardado, ensure_ascii=False), huella))
        r = conn.execute("SELECT * FROM rend_auditorias WHERE id=?", (cur.lastrowid,)).fetchone()
    return {**_fila(r), "cache": False}


def _tarea_prioridad(fecha: str, texto: str) -> int | None:
    """La prioridad de mañana como tarea con fecha de mañana. Repetir la auditoría actualiza la misma tarea."""
    from app.items import ItemIn, create
    if fecha < (date.today() - timedelta(days=1)).isoformat():
        return None  # auditar un día antiguo no crea tareas
    manana = (date.fromisoformat(fecha) + timedelta(days=1)).isoformat()
    contenido = f"Prioridad de mañana · {texto}"[:500]
    with get_db() as conn:
        viva = conn.execute("""SELECT id FROM inbox WHERE category='Rendimiento' AND due_date=? AND content LIKE 'Prioridad de mañana · %'
                               AND status != 'processed' AND note_id IS NULL ORDER BY id DESC LIMIT 1""", (manana,)).fetchone()
        if viva:
            conn.execute("UPDATE inbox SET content=? WHERE id=?", (contenido, viva["id"]))
            return viva["id"]
    return create(ItemIn(text=contenido, type="tarea", category="Rendimiento", priority="alta", due_date=manana,
                         details=f"De la auditoría del {fecha}: /rendimiento?vista=auditoria"))


def _nota_semanal(fecha: str, periodo: str, res: llm_router.Resultado) -> str:
    """La auditoría semanal como nota .md (la fuente de verdad del cerebro). Repetirla la sobrescribe."""
    from app.indexer import sync_notes_to_db
    from app.notes_core import note_path, update_index_for_area
    from app.versions import snapshot as snapshot_version
    nombres = {"metabolico": "Balance metabólico", "codificacion": "Calidad de codificación", "sueno": "Sueño y termorregulación",
               "rotacion": "Eficiencia de rotación"}
    estados = {"verde": "bien", "ambar": "atención", "rojo": "alerta"}
    desde = (date.fromisoformat(fecha) - timedelta(days=6)).isoformat()
    d = res.datos
    partes = [f"# Auditoría de rendimiento {periodo}", "", f"Del {desde} al {fecha}. Modelo: {res.proveedor} · `{res.modelo}`.", ""]
    for c in CAPAS:
        x = d["capas"][c]
        partes += [f"## {nombres[c]} ({estados[x['estado']]})", "", f"**Diagnóstico.** {x['diagnostico']}", "",
                   f"**Corrección.** {x['correccion']}", ""]
    partes += ["## Prioridad", "", d["prioridad_manana"], ""]
    if d["alertas"]:
        partes += ["## Alertas", "", *[f"* {a}" for a in d["alertas"]], ""]
    note_id = f"auditoria-rendimiento-{periodo.lower()}"
    ruta = note_path(note_id)
    post = frontmatter.Post("\n".join(partes))
    post["title"] = f"Auditoría de rendimiento {periodo}"
    post["category"] = "Rendimiento - Auditorías"
    post["status"] = "consolidado"
    post["tags"] = ["rendimiento", "auditoria"]
    try:
        snapshot_version(note_id)
    except Exception:  # sin versión anterior no hay nada que guardar
        pass
    atomic_write(ruta, frontmatter.dumps(post))
    sync_notes_to_db()
    update_index_for_area("Rendimiento")
    return note_id


# ── Rutas ─────────────────────────────────────────────────────────────────────

class AuditarIn(BaseModel):
    tipo: str = "dia"
    fecha: str | None = None
    forzar: bool = False


@router.get("/estado")
def api_estado():
    with get_db() as conn:
        aj = ajustes(conn)
    return {**llm_router.estado(), "prompt": aj.get("ia_prompt") or PROMPT_DEFECTO, "prompt_defecto": PROMPT_DEFECTO,
            "prompt_propio": bool(aj.get("ia_prompt")), "incluir_nota": bool(aj.get("ia_incluir_nota")), "aviso": AVISO_PRIVACIDAD}


@router.post("/auditar")
def api_auditar(data: AuditarIn):
    if data.tipo not in ("dia", "semana"):
        raise HTTPException(status_code=422, detail="tipo: dia o semana")
    fecha = data.fecha or date.today().isoformat()
    try:
        if date.fromisoformat(fecha) > date.today():
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=422, detail="Fecha no válida")
    t0 = time.time()
    out = auditar(data.tipo, fecha, data.forzar)
    log.info("Auditoría %s %s en %.1f s (caché: %s)", data.tipo, out["periodo"], time.time() - t0, out["cache"])
    return out


@router.get("/historial")
def api_historial(limite: int = 30):
    limite = max(1, min(limite, 200))
    with get_db() as conn:
        filas = conn.execute("SELECT * FROM rend_auditorias ORDER BY creado DESC, id DESC LIMIT ?", (limite,)).fetchall()
        vivas = {r["id"] for r in conn.execute("SELECT id FROM inbox WHERE status != 'processed'")}
    out = []
    for r in filas:
        try:
            x = _fila(r)
        except (ValueError, TypeError):
            continue
        if "resultado" not in x:
            continue
        x["tarea_pendiente"] = x.get("tarea_id") in vivas
        out.append(x)
    return {"auditorias": out}
