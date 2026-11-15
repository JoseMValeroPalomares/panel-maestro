"""
«Proponer flashcards» con IA en una nota (F-4). Usa el router de modelos (app/llm_router.py) y comparte con «Corregir
con IA» (app/ia_notas.py) la cola de un trabajo, el límite de ritmo, la política de notas cifradas y sensibles, el
registro sin contenido (ia_correcciones) y el deshacer con versiones.

    POST /api/notes/{id}/ia/flashcards         encola la propuesta → {job}
    GET  /api/ia/jobs/{job}                    (ia_notas) estado; con `listo`: tarjetas, descartadas y modelo
    DELETE /api/ia/jobs/{job}                  (ia_notas) cancela o descarta la propuesta
    POST /api/ia/jobs/{job}/flashcards         {tarjetas: [{pregunta, respuesta}]} las elegidas (editadas o no):
                                               guarda versión, las escribe bajo «Flashcards» y se reindexan
    POST /api/notes/{id}/ia/deshacer           (ia_notas) vuelve a la versión de antes

El modelo solo ve la nota y las preguntas que ya tiene; devuelve JSON. Cada respuesta tiene que poder localizarse en
la nota (ia_validacion.respuesta_en_nota), sin repetir preguntas y como mucho 15: lo demás se descarta y se cuenta.
Nada se escribe sin que el usuario elija en el diálogo.
"""

import hashlib
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import ia_notas, ia_validacion, llm_router, versions
from app.database import get_db
from app.notes import NoteData, save_note
from core.logging_config import get_logger

log = get_logger("ia_flashcards")
router = APIRouter()

MAX_SEGUNDOS = 180

PROMPT = """Eres un profesor que prepara flashcards de repaso a partir de los apuntes de un estudiante.
Recibirás una NOTA en Markdown. Propón como mucho {maximo} flashcards sacadas SOLO de lo que dice la nota: no añadas
datos, ejemplos ni conocimientos que no estén escritos en ella.
Reglas:
- Una idea por tarjeta. Pregunta concreta, en español, terminada en «?». Respuesta breve (máximo 25 palabras), con las
  palabras y los números tal y como aparecen en la nota.
- Ni la pregunta ni la respuesta pueden llevar saltos de línea ni «>>».
- No repitas ninguna de las PREGUNTAS QUE YA EXISTEN.
- Si la nota no da para tarjetas útiles, devuelve la lista vacía.
Responde ÚNICAMENTE con JSON: {{"tarjetas": [{{"pregunta": "…", "respuesta": "…"}}]}}"""


def _mensajes(nota: str, existentes: list[str]) -> list[dict]:
    ya = "\n".join(f"- {q}" for q in existentes) or "(ninguna)"
    return [
        {"role": "system", "content": PROMPT.format(maximo=ia_validacion.MAX_FLASHCARDS)},
        {"role": "user", "content": f"=== PREGUNTAS QUE YA EXISTEN ===\n{ya}\n\n=== NOTA ===\n{nota}"},
    ]


def _ejecutar(job: ia_notas.Job, sensible: bool, pol: dict, existentes: list[str]) -> None:
    job.estado = "trabajando"
    limite = job.inicio + MAX_SEGUNDOS
    cancelado = lambda: job.cancelar.is_set() or time.time() > limite  # noqa: E731

    def validar(datos: dict) -> dict:
        validas, descartadas = ia_validacion.validar_flashcards(job.original, datos.get("tarjetas"), existentes)
        if not validas and descartadas:  # todas inventadas o repetidas: que pruebe el siguiente modelo
            raise ValueError("ninguna tarjeta sale de la nota (" + descartadas[0]["motivo"] + ")")
        return {"tarjetas": validas, "descartadas": descartadas}

    transport = ia_notas._transport
    try:
        res = llm_router.completar(
            _mensajes(job.original, existentes),
            validar,
            temperatura=0.2,
            transport=transport,
            formato="json",
            max_salida=2500,
            solo_privados=sensible,
            politica=pol,
            cancelado=cancelado,
            uso="flashcards",
            dormir=lambda s: None if transport else time.sleep(s),
        )
    except llm_router.LLMError as e:
        job.intentos.extend(e.intentos or [])
        if e.cancelado or job.cancelar.is_set():
            job.estado = "cancelado"
            return
        job.estado = "error"
        job.error = (
            "Se agotó el tiempo máximo"
            if time.time() > limite
            else "Ningún modelo propuso flashcards válidas ("
            + ("; ".join(f"{i['modelo']}: {i['error']}" for i in job.intentos[:6]) or str(e))
            + ")."
        )
        return
    job.intentos.extend(res.intentos)
    job.partes = [{"id": i, **t} for i, t in enumerate(res.datos["tarjetas"])]
    job.descartadas = res.datos["descartadas"]
    job.modelo = {"id": res.modelo_id, "proveedor": res.proveedor, "modelo": res.modelo}
    job.tokens, job.coste, job.aviso = (res.tokens_in, res.tokens_out), res.coste, res.aviso
    job.estado = "listo"
    ia_notas._anotar(job, "propuesta")


def _ejecutar_seguro(job, sensible, pol, existentes):
    try:
        _ejecutar(job, sensible, pol, existentes)
    except Exception as e:  # nunca dejar un trabajo colgado
        log.exception("Propuesta de flashcards fallida")
        job.estado, job.error = "error", f"Error interno ({type(e).__name__})"


@router.post("/api/notes/{note_id}/ia/flashcards")
def proponer(note_id: str):
    post = ia_notas._leer(note_id)
    if ia_notas._cifrada(note_id, post):
        raise HTTPException(403, "Las notas cifradas no se envían nunca a ninguna IA.")
    nota = post.content
    if not nota.strip():
        raise HTTPException(400, "La nota está vacía")
    if len(nota) > ia_notas.MAX_CHARS:
        raise HTTPException(413, f"La nota es demasiado larga ({len(nota)} de {ia_notas.MAX_CHARS} caracteres).")
    pol = llm_router.leer_politica()
    sensible = ia_notas.es_sensible(post, pol)
    cad = llm_router.cadena(pol, sensible)
    if not cad:
        raise HTTPException(
            409, "No hay ningún proveedor de IA configurado: añade una clave a .env (ver Ajustes → IA)."
        )
    if all(c["omitido"] for c in cad):
        raise HTTPException(
            409,
            "Tu política no permite ningún proveedor para esta nota: "
            + "; ".join(f"{c['proveedor']}: {c['omitido']}" for c in cad),
        )
    existentes = ia_validacion.preguntas_existentes(nota)
    with ia_notas._lock:
        ahora = time.time()
        while ia_notas._recientes and ahora - ia_notas._recientes[0] > 600:
            ia_notas._recientes.popleft()
        if len(ia_notas._recientes) >= ia_notas.PETICIONES_POR_10MIN:
            raise HTTPException(429, "Demasiadas peticiones a la IA seguidas: espera unos minutos.")
        if any(j.estado in ("cola", "trabajando") for j in ia_notas._jobs.values()):
            raise HTTPException(409, "Ya hay un trabajo de IA en curso; espera a que termine o cancélalo.")
        ia_notas._recientes.append(ahora)
        ia_notas._limpiar()
        job = ia_notas.Job(
            id=uuid.uuid4().hex[:12],
            note_id=note_id,
            original=nota,
            hash=hashlib.sha256(nota.encode()).hexdigest(),
            tipo="flashcards",
        )
        ia_notas._jobs[job.id] = job
    ia_notas._pool.submit(_ejecutar_seguro, job, sensible, pol, existentes)
    return {"job": job.id}


class TarjetaIn(BaseModel):
    pregunta: str = Field(max_length=ia_validacion.MAX_PREGUNTA + 50)
    respuesta: str = Field(max_length=ia_validacion.MAX_RESPUESTA + 50)


class AnadirIn(BaseModel):
    tarjetas: list[TarjetaIn] = Field(max_length=ia_validacion.MAX_FLASHCARDS * 2)


@router.post("/api/ia/jobs/{job_id}/flashcards")
def anadir(job_id: str, data: AnadirIn):
    """Añade a la nota las tarjetas elegidas (el usuario puede haberlas editado: se comprueba el formato, que no se
    repitan y el máximo, no que estén en la nota). Con una lista vacía, la propuesta se da por descartada."""
    j = ia_notas._job(job_id)
    if j.tipo != "flashcards" or j.estado != "listo":
        raise HTTPException(409, "Esta propuesta no está lista o ya se aplicó")
    post = ia_notas._leer(j.note_id)
    if ia_notas._cifrada(j.note_id, post):
        raise HTTPException(403, "Las notas cifradas no se envían nunca a ninguna IA.")
    if hashlib.sha256(post.content.encode()).hexdigest() != j.hash:
        raise HTTPException(409, "La nota cambió mientras se preparaban las flashcards; vuelve a pedirlas.")
    vistas = {ia_validacion.clave_pregunta(q) for q in ia_validacion.preguntas_existentes(post.content)}
    elegidas = []
    for t in data.tarjetas:
        q, a = " ".join(t.pregunta.split()), " ".join(t.respuesta.split())
        if motivo := ia_validacion.tarjeta_mal_formada(q, a):
            raise HTTPException(422, f"«{q[:60]}»: {motivo}")
        clave = ia_validacion.clave_pregunta(q)
        if clave in vistas:
            raise HTTPException(422, f"«{q[:60]}»: esa pregunta ya existe")
        vistas.add(clave)
        elegidas.append({"pregunta": q, "respuesta": a})
    if len(elegidas) > ia_validacion.MAX_FLASHCARDS:
        raise HTTPException(422, f"Como mucho {ia_validacion.MAX_FLASHCARDS} flashcards de una vez")
    if not elegidas:
        j.estado = "cancelado"
        ia_notas._anotar(j, "rechazada")
        return {"status": "success", "anadidas": 0}
    nuevo = ia_validacion.anadir_flashcards(post.content, elegidas)
    # Para deshacer: la versión de justo antes (o la última, si ya era idéntica)
    version = versions.snapshot(j.note_id, force=True) or next((p.stem for p in versions._list(j.note_id)), None)
    with get_db() as conn:
        cat = conn.execute("SELECT category_id FROM notes WHERE id=?", (j.note_id,)).fetchone()
    save_note(
        j.note_id,
        NoteData(
            title=post.get("title") or j.note_id,
            category=post.get("category") or "General",
            category_id=cat["category_id"] if cat else None,
            content=nuevo,
            status=post.get("status") or "por-escribir",
            tags=list(post.get("tags") or []),
            encrypted=False,
        ),
    )
    j.estado = "aplicado"
    ia_notas._anotar(j, "aplicada", len(elegidas), version)
    return {"status": "success", "anadidas": len(elegidas), "version": version}
