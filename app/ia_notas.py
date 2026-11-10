"""
«Corregir con IA» en las notas. Usa el router de modelos (app/llm_router.py) y el validador (app/ia_validacion.py).

    GET    /api/notes/{id}/ia                 ¿se puede? (cifrada, sin proveedor…), sensible, últimas correcciones
    PUT    /api/notes/{id}/sensible           marca la nota como sensible (frontmatter `sensible`)
    POST   /api/notes/{id}/ia/corregir        encola la corrección → {job}
    GET    /api/ia/jobs/{job}                 estado; con `listo` trae las partes (diff) y el modelo que respondió
    DELETE /api/ia/jobs/{job}                 cancela
    POST   /api/ia/jobs/{job}/aplicar         {aceptadas: [ids] | null = todo}: guarda versión, escribe y reindexa
    POST   /api/notes/{id}/ia/deshacer        restaura la versión guardada antes de la última corrección aplicada
    GET    /api/ia/estado | POST /api/ia/politica | POST /api/ia/probar/{modelo} | POST /api/ia/catalogo   (Ajustes)

Privacidad: las notas cifradas NO se envían (403); las sensibles solo a modelos locales o que no entrenan; el contenido
no se guarda en registros (solo modelo, tokens aproximados, coste y resultado). El texto se lee SIEMPRE del archivo: la
página guarda antes de pedir la corrección. Cola de un solo trabajo a la vez, límite de tamaño, de ritmo y de tiempo.
"""
import difflib
import hashlib
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import ia_validacion, llm_router, versions
from app.database import get_db
from app.notes import NoteData, save_note
from app.notes_core import note_path
from core import config
from core.logging_config import get_logger

log = get_logger("ia_notas")
router = APIRouter()

MAX_CHARS = 40_000          # tamaño máximo de la nota que se envía
MAX_SEGUNDOS = 240          # tiempo máximo de un trabajo
PETICIONES_POR_10MIN = 8    # límite de ritmo del panel (no el de los proveedores)
GUIA = config.PROJECT_ROOT / "docs" / "GUIA_NOTAS.md"
_transport = None           # los tests inyectan un httpx.MockTransport
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ia")
_jobs: dict[str, "Job"] = {}
_recientes: deque = deque()
_lock = threading.Lock()


@dataclass
class Job:
    id: str
    note_id: str
    estado: str = "cola"          # cola | trabajando | listo | error | cancelado | aplicado
    original: str = ""
    corregido: str = ""
    partes: list = field(default_factory=list)
    ops: list = field(default_factory=list)
    modelo: dict | None = None
    error: str | None = None
    intentos: list = field(default_factory=list)
    aviso: str | None = None
    hash: str = ""
    cancelar: threading.Event = field(default_factory=threading.Event)
    inicio: float = field(default_factory=time.time)
    tokens: tuple = (0, 0)
    coste: float = 0.0
    sin_claves: bool = False


# ── Lectura de la nota y reglas ───────────────────────────────────────────────

def _leer(note_id: str) -> frontmatter.Post:
    path = note_path(note_id)
    if not Path(path).is_file():
        raise HTTPException(404, "Nota no encontrada")
    with open(path, encoding="utf-8") as f:
        return frontmatter.load(f)


def _cifrada(note_id: str, post: frontmatter.Post) -> bool:
    if post.get("encrypted"):
        return True
    with get_db() as conn:
        r = conn.execute("SELECT encrypted FROM notes WHERE id=?", (note_id,)).fetchone()
    return bool(r and r["encrypted"])


def es_sensible(post: frontmatter.Post, pol: dict) -> bool:
    if post.get("sensible"):
        return True
    cat = str(post.get("category") or "").strip().lower()
    return any(cat == c.strip().lower() or cat.startswith(c.strip().lower() + " - ") for c in pol.get("categorias_sensibles") or [] if c.strip())


def _guia() -> str:
    try:
        t = GUIA.read_text(encoding="utf-8")
    except OSError:
        return ""
    return re.sub(r"<!--.*?-->", "", t, flags=re.S).strip()  # los comentarios son para ti, no para la IA


def _titulos() -> dict[str, str]:
    with get_db() as conn:
        return {r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM notes WHERE status != 'indice'").fetchall()}


PROMPT_SISTEMA = """Eres el corrector de notas personales de un estudiante. Recibirás una nota en Markdown y debes devolverla corregida siguiendo la GUÍA.
Corriges SOLO forma: ortografía, redacción, claridad, estructura de títulos, fórmulas LaTeX, tablas y enlaces entre notas.
NO inventes datos ni cambies el significado. Si dudas de un dato, déjalo igual y añade justo debajo un comentario `<!-- REVISAR: motivo breve -->`.
NO añadas etiquetas (#algo, tags:), ni metadatos (---), ni texto fuera de la nota. Conserva exactamente: bloques de código, bloques ```sim y ```calendario,
fórmulas ($…$, $$…$$), flashcards (`pregunta >> respuesta`), casillas `- [ ]`/`- [x]`, anotaciones `{{resumir|entender|mal: …}}` y marcadores `[[tarea:N]]`.
Solo enlaza con [[Título]] notas de la lista de TÍTULOS EXISTENTES, con el título exacto. Responde ÚNICAMENTE con el texto Markdown de la nota corregida, sin comentarios previos ni ``` envolventes."""

ESTRICTO = """

LA RESPUESTA ANTERIOR FUE RECHAZADA por estos problemas: {problemas}.
Esta vez sé más conservador: cambia solo lo imprescindible, copia tal cual todo bloque, fórmula, tabla, número y enlace que no esté claramente roto, y no añadas nada nuevo."""


def _mensajes(nota: str, titulos: dict[str, str], problemas: str | None = None) -> list[dict]:
    lista = "\n".join(f"- {t}" for t in sorted(titulos.values(), key=str.lower))[:12_000]
    sistema = PROMPT_SISTEMA + ("\n\n=== GUÍA ===\n" + _guia() if _guia() else "") + (ESTRICTO.format(problemas=problemas) if problemas else "")
    return [{"role": "system", "content": sistema},
            {"role": "user", "content": f"=== TÍTULOS EXISTENTES ===\n{lista}\n\n=== NOTA ===\n{nota}"}]


# ── Partes (diff) ─────────────────────────────────────────────────────────────

def calcular_partes(original: str, corregido: str) -> tuple[list[dict], list]:
    a, b = original.split("\n"), corregido.split("\n")
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    partes = []
    for i, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag != "equal":
            partes.append({"id": i, "antes": a[i1:i2], "despues": b[j1:j2], "linea": i1 + 1})
    return partes, ops


def componer(original: str, corregido: str, ops: list, aceptadas: set[int] | None) -> str:
    a, b = original.split("\n"), corregido.split("\n")
    out = []
    for i, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal" or (aceptadas is not None and i not in aceptadas):
            out.extend(a[i1:i2])
        else:
            out.extend(b[j1:j2])
    return "\n".join(out)


# ── Trabajo ───────────────────────────────────────────────────────────────────

def dividir(texto: str, max_tokens: int) -> list[str]:
    """Parte una nota en trozos de ≈ `max_tokens`, cortando en encabezados o líneas en blanco y nunca dentro de un bloque ```.
    Sirve para los modelos gratuitos de contexto pequeño (Groq, GitHub Models): se corrige trozo a trozo y se une."""
    tope = int(max_tokens * 3.5)
    if len(texto) <= tope:
        return [texto]
    trozos, actual, n, valla = [], [], 0, False
    for l in texto.split("\n"):
        era_valla = valla
        abre = re.match(r"^\s*(```|~~~)", l) is not None
        if abre:
            valla = not valla
        corte = not era_valla and (abre or re.match(r"^#{1,6}\s", l) is not None or l.strip() in ("", "---"))
        if actual and not era_valla and n + len(l) + 1 > tope and (corte or n + len(l) + 1 > tope * 1.3):
            trozos.append("\n".join(actual))
            actual, n = [], 0
        actual.append(l)
        n += len(l) + 1
    if actual:
        trozos.append("\n".join(actual))
    return trozos


def _ejecutar(job: Job, titulos: dict[str, str], sensible: bool, pol: dict) -> None:
    job.estado = "trabajando"
    limite = job.inicio + MAX_SEGUNDOS
    cancelado = lambda: job.cancelar.is_set() or time.time() > limite  # noqa: E731
    usables = [c for c in llm_router.cadena(pol, sensible) if not c["omitido"]]
    if not usables:
        job.estado, job.error = "error", "Ningún proveedor puede usarse con tu política: " + "; ".join(f"{c['proveedor']}: {c['omitido']}" for c in llm_router.cadena(pol, sensible))
        return
    cfg = {m["id"]: m for m in llm_router.cargar_config()["modelos"]}
    ultimo: list[str] = []
    gasto = " ".join(m["content"] for m in _mensajes("", titulos))
    sobrecarga = llm_router.estimar_tokens(gasto)        # sistema + guía + títulos: va en CADA petición

    def validador(original: str):
        def validar(datos: dict) -> dict:
            texto = ia_validacion.quitar_envoltorio(datos["texto"])
            problemas = ia_validacion.validar(original, texto, titulos)
            ultimo[:] = problemas
            if problemas:
                raise ValueError("; ".join(problemas[:4]))
            return {"texto": texto}
        return validar

    try:
        llm_router.descubrir(_transport, solo_si_antiguo_s=24 * 3600) if _transport is None else None
    except Exception:  # el catálogo es opcional
        pass

    def parar() -> bool:
        if cancelado():
            job.estado = "cancelado" if job.cancelar.is_set() else "error"
            job.error = None if job.cancelar.is_set() else "Se agotó el tiempo máximo"
            return True
        return False

    for c in usables:
        m = cfg[c["id"]]
        espacio = (m.get("max_entrada_tokens") or 30_000) - sobrecarga - 100   # lo que queda para el texto de cada petición
        if espacio < 500:
            job.intentos.append({"modelo": c["id"], "error": f"contexto demasiado pequeño ({m.get('max_entrada_tokens')} tokens) para la guía y la lista de títulos"})
            continue
        trozos = dividir(job.original, espacio)
        if len(trozos) > 12:
            job.intentos.append({"modelo": c["id"], "error": f"la nota necesitaría {len(trozos)} peticiones: demasiadas para este modelo"})
            continue
        salida, res, tin_t, tout_t, coste_t, aviso, fallo = [], None, 0, 0, 0.0, None, False
        for trozo in trozos:
            ttok = llm_router.estimar_tokens(trozo)
            tout = min(int(ttok * 1.4) + 1200, 16_000)   # +margen: los modelos que razonan gastan tokens antes de responder
            if m.get("max_tokens_total"):                  # p. ej. Groq: 8 000 tokens por minuto entre entrada y salida
                tout = max(int(ttok * 1.15), min(tout, m["max_tokens_total"] - sobrecarga - ttok))
            res = None
            for estricto in (False, True):
                if parar():
                    return
                try:
                    res = llm_router.completar(_mensajes(trozo, titulos, "; ".join(ultimo[:6]) if estricto else None), validador(trozo), temperatura=0.2,
                                               transport=_transport, formato="texto", max_salida=tout, solo_privados=sensible, politica=pol,
                                               cancelado=cancelado, uso="notas", solo=c["id"], dormir=lambda s: None if _transport else time.sleep(s))
                    break
                except llm_router.LLMError as e:
                    job.intentos.extend(e.intentos or [{"modelo": c["id"], "error": str(e)}])
                    if e.cancelado:
                        job.estado = "cancelado"
                        return
                    if not (e.intentos and e.intentos[-1]["error"].startswith("esquema no válido") and not estricto):
                        break  # un reintento con instrucciones más estrictas solo si la validación falló
            if res is None:
                fallo = True
                break
            salida.append(res.datos["texto"])
            tin_t += res.tokens_in
            tout_t += res.tokens_out
            coste_t += res.coste
            aviso = res.aviso or aviso
        if fallo:
            continue
        corregido = "\n".join(x.rstrip("\n") for x in salida)
        if len(trozos) > 1:  # cada trozo ya pasó; el conjunto también debe pasar
            problemas = ia_validacion.validar(job.original, corregido, titulos)
            if problemas:
                job.intentos.append({"modelo": c["id"], "error": "esquema no válido al unir los trozos: " + "; ".join(problemas[:2])})
                continue
        job.intentos.extend(res.intentos)
        job.corregido, job.modelo = corregido, {"id": res.modelo_id, "proveedor": res.proveedor, "modelo": res.modelo}
        job.tokens, job.coste, job.aviso = (tin_t, tout_t), coste_t, aviso
        job.partes, job.ops = calcular_partes(job.original, job.corregido)
        job.estado = "listo"
        _anotar(job, "propuesta")
        return
    job.estado = "error"
    motivos = []
    for i in job.intentos:
        t = f"{i['modelo']}: {i['error']}"
        if t not in motivos:
            motivos.append(t)
    job.error = "Ningún modelo dio una corrección válida (" + ("; ".join(motivos[:6]) or (ultimo[0] if ultimo else "todos fallaron")) + ")."


def _anotar(job: Job, estado: str, aceptadas: int = 0, version: str | None = None) -> int:
    with get_db() as conn:
        if estado == "propuesta":
            cur = conn.execute("""INSERT INTO ia_correcciones (note_id, modelo_id, proveedor, modelo, estado, partes, tokens_in, tokens_out, coste)
                                  VALUES (?,?,?,?,?,?,?,?,?)""", (job.note_id, job.modelo["id"], job.modelo["proveedor"], job.modelo["modelo"], estado,
                                                                   len(job.partes), job.tokens[0], job.tokens[1], job.coste))
            job.__dict__["fila"] = cur.lastrowid
        else:
            conn.execute("UPDATE ia_correcciones SET estado=?, aceptadas=?, version=COALESCE(?, version) WHERE id=?", (estado, aceptadas, version, job.__dict__.get("fila")))
    return job.__dict__.get("fila", 0)


def _limpiar() -> None:
    for k in [k for k, j in _jobs.items() if time.time() - j.inicio > 3600]:
        _jobs.pop(k, None)


# ── Rutas de la nota ──────────────────────────────────────────────────────────

@router.get("/api/notes/{note_id}/ia")
def disponibilidad(note_id: str):
    post = _leer(note_id)
    pol = llm_router.leer_politica()
    sensible = es_sensible(post, pol)
    out = {"sensible": sensible, "disponible": True, "motivo": None, "sin_claves": False}
    if _cifrada(note_id, post):
        out.update(disponible=False, motivo="Las notas cifradas no se envían nunca a ninguna IA.")
    else:
        cad = llm_router.cadena(pol, sensible)
        if not cad:
            out.update(disponible=False, sin_claves=True, motivo="No hay ningún proveedor de IA configurado. Añade una clave (GROQ_API_KEY, OPENROUTER_API_KEY…) "
                                                                    "o OLLAMA_URL a .env y reinicia el panel; los detalles están en Ajustes → IA.")
        elif all(c["omitido"] for c in cad):
            out.update(disponible=False, motivo="Tu política no permite ningún proveedor para esta nota" + (" (es sensible: solo locales o que no entrenan)" if sensible else "") + ". Revísalo en Ajustes → IA.")
    with get_db() as conn:
        out["ultimas"] = [dict(r) for r in conn.execute("SELECT id, modelo_id, proveedor, modelo, estado, partes, aceptadas, creado, version FROM ia_correcciones WHERE note_id=? ORDER BY id DESC LIMIT 5", (note_id,))]
    return out


class SensibleIn(BaseModel):
    sensible: bool


@router.put("/api/notes/{note_id}/sensible")
def marcar_sensible(note_id: str, data: SensibleIn):
    from core.files import atomic_write
    post = _leer(note_id)
    if data.sensible:
        post["sensible"] = True
    else:
        post.metadata.pop("sensible", None)
    atomic_write(note_path(note_id), frontmatter.dumps(post))
    return {"sensible": data.sensible}


@router.post("/api/notes/{note_id}/ia/corregir")
def corregir(note_id: str):
    post = _leer(note_id)
    if _cifrada(note_id, post):
        raise HTTPException(403, "Las notas cifradas no se envían nunca a ninguna IA.")
    original = post.content
    if not original.strip():
        raise HTTPException(400, "La nota está vacía")
    if len(original) > MAX_CHARS:
        raise HTTPException(413, f"La nota es demasiado larga para corregirla de una vez ({len(original)} de {MAX_CHARS} caracteres). Divídela.")
    pol = llm_router.leer_politica()
    sensible = es_sensible(post, pol)
    cad = llm_router.cadena(pol, sensible)
    if not cad:
        raise HTTPException(409, "No hay ningún proveedor de IA configurado: añade una clave a .env (ver Ajustes → IA).")
    if all(c["omitido"] for c in cad):
        raise HTTPException(409, "Tu política no permite ningún proveedor para esta nota: " + "; ".join(f"{c['proveedor']}: {c['omitido']}" for c in cad))
    with _lock:
        ahora = time.time()
        while _recientes and ahora - _recientes[0] > 600:
            _recientes.popleft()
        if len(_recientes) >= PETICIONES_POR_10MIN:
            raise HTTPException(429, "Demasiadas correcciones seguidas: espera unos minutos.")
        if any(j.estado in ("cola", "trabajando") for j in _jobs.values()):
            raise HTTPException(409, "Ya hay una corrección en curso; espera a que termine o cancélala.")
        _recientes.append(ahora)
        _limpiar()
        job = Job(id=uuid.uuid4().hex[:12], note_id=note_id, original=original, hash=hashlib.sha256(original.encode()).hexdigest())
        _jobs[job.id] = job
    _pool.submit(_ejecutar_seguro, job, _titulos(), sensible, pol)
    return {"job": job.id}


def _ejecutar_seguro(job, titulos, sensible, pol):
    try:
        _ejecutar(job, titulos, sensible, pol)
    except Exception as e:  # nunca dejar un trabajo colgado
        log.exception("Corrección de IA fallida")
        job.estado, job.error = "error", f"Error interno ({type(e).__name__})"


def _job(job_id: str) -> Job:
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Esa corrección ya no existe")
    return j


@router.get("/api/ia/jobs/{job_id}")
def ver_job(job_id: str):
    j = _job(job_id)
    out = {"estado": j.estado, "error": j.error, "aviso": j.aviso, "intentos": [{"modelo": i["modelo"], "error": i["error"]} for i in j.intentos]}
    if j.estado in ("listo", "aplicado"):
        out.update(modelo=j.modelo, partes=j.partes, sin_cambios=not j.partes, tokens=list(j.tokens), coste=round(j.coste, 5))
    return out


@router.delete("/api/ia/jobs/{job_id}")
def cancelar(job_id: str):
    j = _job(job_id)
    j.cancelar.set()
    if j.estado == "cola":
        j.estado = "cancelado"
    elif j.estado == "listo":
        j.estado = "cancelado"
        _anotar(j, "rechazada")
    return {"estado": j.estado}


class AplicarIn(BaseModel):
    aceptadas: list[int] | None = Field(default=None, max_length=5000)


@router.post("/api/ia/jobs/{job_id}/aplicar")
def aplicar(job_id: str, data: AplicarIn):
    j = _job(job_id)
    if j.estado != "listo":
        raise HTTPException(409, "Esta corrección no está lista o ya se aplicó")
    post = _leer(j.note_id)
    if _cifrada(j.note_id, post):
        raise HTTPException(403, "Las notas cifradas no se envían nunca a ninguna IA.")
    if hashlib.sha256(post.content.encode()).hexdigest() != j.hash:
        raise HTTPException(409, "La nota cambió mientras se corregía; vuelve a pedir la corrección.")
    validas = {p["id"] for p in j.partes}
    elegidas = validas if data.aceptadas is None else set(data.aceptadas) & validas
    if not elegidas:
        j.estado = "cancelado"
        _anotar(j, "rechazada")
        return {"status": "success", "aplicadas": 0}
    nuevo = componer(j.original, j.corregido, j.ops, None if elegidas == validas else elegidas)
    if elegidas != validas and (problemas := ia_validacion.validar_estructura(nuevo)):
        raise HTTPException(422, "Esa combinación de partes rompería la nota (" + problemas[0] + "). Acepta también las partes relacionadas.")
    # Para deshacer. snapshot() devuelve None si la última versión ya es idéntica a la actual: entonces vale esa.
    version = versions.snapshot(j.note_id, force=True) or next((p.stem for p in versions._list(j.note_id)), None)
    with get_db() as conn:
        cat = conn.execute("SELECT category_id FROM notes WHERE id=?", (j.note_id,)).fetchone()
    save_note(j.note_id, NoteData(title=post.get("title") or j.note_id, category=post.get("category") or "General", category_id=cat["category_id"] if cat else None,
                                  content=nuevo, status=post.get("status") or "por-escribir", tags=list(post.get("tags") or []), encrypted=False))
    j.estado = "aplicado"
    _anotar(j, "aplicada" if elegidas == validas else "parcial", len(elegidas), version)
    return {"status": "success", "aplicadas": len(elegidas), "version": version}


@router.post("/api/notes/{note_id}/ia/deshacer")
def deshacer(note_id: str):
    with get_db() as conn:
        r = conn.execute("SELECT id, version FROM ia_correcciones WHERE note_id=? AND estado IN ('aplicada','parcial') AND version IS NOT NULL ORDER BY id DESC LIMIT 1",
                         (note_id,)).fetchone()
    if not r:
        raise HTTPException(404, "No hay ninguna corrección de IA que deshacer en esta nota")
    versions.restore_version(note_id, r["version"])
    with get_db() as conn:
        conn.execute("UPDATE ia_correcciones SET estado='deshecha' WHERE id=?", (r["id"],))
    return {"status": "success"}


# ── Ajustes → IA ──────────────────────────────────────────────────────────────

@router.get("/api/ia/estado")
def estado():
    return llm_router.estado()


class PoliticaIn(BaseModel):
    permitir_entrenan: bool | None = None
    permitir_pago: bool | None = None
    presupuesto_mes: float | None = Field(default=None, ge=0, le=10_000)
    categorias_sensibles: list[str] | None = Field(default=None, max_length=100)


@router.post("/api/ia/politica")
def politica(data: PoliticaIn):
    cambios = {k: v for k, v in data.model_dump().items() if v is not None}
    if "categorias_sensibles" in cambios:
        cambios["categorias_sensibles"] = [c.strip()[:300] for c in cambios["categorias_sensibles"] if c.strip()]
    llm_router.guardar_politica(cambios)
    return llm_router.estado()


@router.post("/api/ia/probar/{modelo_id}")
def probar(modelo_id: str):
    try:
        return llm_router.probar(modelo_id, _transport)
    except llm_router.LLMError as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/ia/catalogo")
def catalogo():
    return {"catalogo": llm_router.descubrir(_transport), "estado": llm_router.estado()}


@router.get("/api/ia/historial")
def historial(limit: int = 30):
    with get_db() as conn:
        rows = conn.execute("""SELECT c.id, c.note_id, n.title, c.proveedor, c.modelo, c.estado, c.partes, c.aceptadas, c.creado
                               FROM ia_correcciones c LEFT JOIN notes n ON n.id = c.note_id ORDER BY c.id DESC LIMIT ?""", (max(1, min(limit, 200)),)).fetchall()
    return {"correcciones": [dict(r) for r in rows]}


# ── Prompt para pegar en un chat de IA (ChatGPT, Claude, Gemini…) ─────────────────────────────────────────────────

PROMPT_CONTEXTO = """Eres el corrector y editor de MIS notas personales de estudio. Te paso la nota al final de este mensaje.

# Qué es la aplicación
Es mi panel personal («Panel»): un cuaderno de notas en Markdown con enlaces entre notas (un «segundo cerebro»), repaso con flashcards, tareas, calendario y más. Las notas son archivos .md; lo que escribo se muestra tal cual con el formato de abajo. Estudio ciencias e ingeniería y escribo en español de España.

# Formato que admite el editor (úsalo exactamente así)
- Markdown normal: `# Título`, `## Sección`, `### Subsección`, **negrita**, *cursiva*, listas, citas con `>`, tablas, código en línea y bloques de código con ``` y lenguaje.
- Enlaces a otras notas: `[[Título exacto]]`. NO hay etiquetas: no uses #etiquetas ni `tags:`; las conexiones se hacen con enlaces. Solo enlaza notas de la lista «Notas existentes» de abajo, con el título exacto; si no existe, déjalo como texto normal.
- Fórmulas LaTeX (KaTeX): en línea `$I = V/R$`; en bloque `$$P = V \\cdot I$$` en su propio párrafo. Cierra siempre `$` y llaves.
- Tablas Markdown con fila de cabecera y separador `|---|---|`, mismo número de columnas en todas las filas.
- Flashcards: una línea `Pregunta >> Respuesta` crea una tarjeta de repaso. Una por línea. Conserva todas.
- Casillas `- [ ]` / `- [x]`: son tareas reales del panel. No las añadas, quites ni cambies de estado.
- Anotaciones mías: `{{resumir: …}}`, `{{entender: …}}`, `{{mal: …}}`. No las borres ni las resuelvas.
- Enlaces a tareas `[[tarea:12]]`: déjalos exactamente igual.
- Calendario incrustado: un bloque ```calendario con líneas `vista: agenda|semana|mes|día` y `días: 7`.

# Simulaciones interactivas (bloque ```sim)
Un bloque ```sim contiene UNA página HTML completa (`<!DOCTYPE html>…`) que se ejecuta en un recuadro aislado (iframe con sandbox). Reglas para escribirlas o corregirlas:
- Todo en un solo documento: HTML + `<style>` + `<script>` en línea. NO hay red: nada de CDN, librerías externas, `fetch`, imágenes remotas ni fuentes externas. Solo JavaScript y CSS puros (canvas 2D, SVG, DOM).
- Sin almacenamiento (localStorage/cookies) ni acceso a la página que la contiene.
- Fondo oscuro para que encaje (p. ej. `body{margin:0;background:#0a0a0b;color:#ededee;font-family:sans-serif}`), tamaño razonable (≈ 400×300 px o adaptable al ancho), controles sencillos (sliders, botones) y animación con `requestAnimationFrame`.
- Etiquetas y textos en español; incluye las unidades y los valores que muestre.
- Si el bloque ya existe, NO lo reescribas: como mucho arregla una errata evidente o una etiqueta sin cerrar. Si te pido una simulación nueva, hazla completa y funcional, dentro de un bloque ```sim.

# Cómo quiero que trabajes (muy importante)
1. RESPETA lo que he escrito: corrige ortografía, tildes, puntuación, redacción poco clara, estructura de títulos, fórmulas, tablas y enlaces, pero SIN cambiar mi forma de explicar, mi tono ni mis palabras salvo que estén mal o confusas.
2. NO añadas información nueva (ejemplos, secciones, conclusiones, datos) que no esté en la nota, a no ser que te lo pida yo expresamente. No alargues ni resumas.
3. NO inventes ni cambies datos, cifras, fechas, nombres ni el significado. Si dudas de un dato, déjalo y añade debajo `<!-- REVISAR: motivo breve -->`.
4. Mantén intactos los bloques de código, `sim`, `calendario`, fórmulas, flashcards, casillas, anotaciones y enlaces `[[tarea:N]]`.
5. Estructura: un único `# Título`, párrafo breve inicial que defina el concepto, secciones `##`, y al final `## Ver también` con enlaces `[[…]]` separados por « · » si procede. Párrafos cortos, una idea cada uno, **negrita** en el término clave la primera vez.

# Cómo quiero la respuesta
- Primero la nota COMPLETA corregida, en Markdown, dentro de UN solo bloque de código con cuatro comillas invertidas (````markdown … ````) para que pueda copiarla entera (la nota puede contener bloques de tres comillas dentro).
- Después, una lista breve (máx. 8 puntos) con los cambios importantes y cualquier duda que hayas marcado.
- Si te pido otra cosa en el chat (explicar, ampliar, hacer una simulación…), hazlo, pero sigue respetando este formato.
"""


@router.get("/api/ia/prompt")
def prompt_para_chat():
    """Texto de contexto (app + formato + reglas + títulos de notas) para pegar antes de la nota en un chat de IA."""
    titulos = sorted(_titulos().values(), key=str.lower)[:400]
    guia = _guia()
    partes = [PROMPT_CONTEXTO.strip()]
    if guia:
        partes.append("# Mis reglas de estilo (guía personal)\n" + guia)
    partes.append("# Notas existentes (para enlazar con [[Título]])\n" + ("\n".join(f"- {t}" for t in titulos) or "(todavía no hay otras notas)"))
    return {"prompt": "\n\n".join(partes), "titulos": len(titulos)}
