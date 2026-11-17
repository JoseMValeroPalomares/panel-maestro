"""
Universidad · archivos de cada tema, temas propuestos desde la carpeta, fusionar temas y lector de PDF.

Todo en SOLO LECTURA sobre el disco (como app/universidad.py): se lista con os.scandir y se sirve un archivo
para leerlo; nunca se escribe, mueve ni borra nada en las carpetas. Toda ruta pasa por `safe_path`.

  - Propuesta de temas (`GET/POST /asignaturas/{id}/escaneo`): cada subcarpeta o documento suelto es un
    candidato con título sugerido («T2 - Procesos» → «Tema 2 · Procesos»). Se confirma, renombra, reordena,
    fusiona con otro tema o se descarta (`asignaturas.ignorar`, no vuelve a proponerse). La sincronía ya no
    crea temas sola: cuenta los nuevos en `asignaturas.por_confirmar`.
  - Archivos (`uni_archivos`): los documentos de cada tema confirmado (el propio archivo o los de su carpeta,
    hasta 4 niveles), con orden propio, «no encontrado» (`falta_desde`, nunca se borran solos) y la última
    página leída. Un archivo movido a mano a otro tema (`tema_manual`) se queda allí al sincronizar.
  - Fusionar: el tema fusionado se oculta (`temas.fusionado_en`) y sus archivos, ejercicios y tareas pasan
    al otro; la sincronía no lo vuelve a crear porque su ruta sigue siendo suya. «Separar» lo deshace.
"""

import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.database import get_db
from app.universidad import (
    DOC_EXT,
    GRUPOS,
    IGNORAR,
    _jl,
    _natural,
    _visible,
    bonito,
    clean_rel,
    escanear,
    get_asig,
    get_tema,
    root_ready,
    safe_path,
    uni_root,
)
from core.logging_config import get_logger

log = get_logger("universidad")
router = APIRouter(prefix="/api/uni")

MAX_PROF = 4  # niveles de subcarpetas dentro de un tema
MAX_ARCHIVOS_TEMA = 400
VISOR_EXT = {"pdf"}
INLINE = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8"}

# ─────────────────────────────────────────────
# Títulos sugeridos
# ─────────────────────────────────────────────

_SEP = r"\s*[-_.]?\s*0*(\d{1,3})(?!\d)\s*[-_.:·)\]]*\s*(.*)$"
PRACTICA_NUM_RE = re.compile(r"^(?:pr[aá]cticas?|pract|pr|p|lab|laboratorio)" + _SEP, re.I)
TEMA_NUM_RE = re.compile(r"^(?:temas?|t|unidad|ud|u|lecci[oó]n|cap[ií]tulo|cap|lesson|chapter|bloque)" + _SEP, re.I)
SOLO_NUM_RE = re.compile(r"^0*(\d{1,3})(?!\d)\s*[-_.:·)\]]+\s*(.+)$")


def sugerir_titulo(nombre: str, es_archivo: bool) -> str:
    """«T2 - Procesos» → «Tema 2 · Procesos», «tema1.pdf» → «Tema 1», «P3_hilos» → «Práctica 3 · Hilos»,
    «01 - Introducción» → «Tema 1 · Introducción». Lo demás, como siempre (`bonito`)."""
    base = os.path.splitext(nombre)[0] if es_archivo else nombre
    base = re.sub(r"_+", " ", base).strip()
    for rx, label in ((PRACTICA_NUM_RE, "Práctica"), (TEMA_NUM_RE, "Tema"), (SOLO_NUM_RE, "Tema")):
        m = rx.match(base)
        if m:
            resto = m.group(2).strip(" -_.·:")
            resto = bonito(resto, False) if resto else ""
            return f"{label} {int(m.group(1))}" + (f" · {resto}" if resto else "")
    return bonito(nombre, es_archivo)


# ─────────────────────────────────────────────
# Carpetas y documentos (solo lectura)
# ─────────────────────────────────────────────


def estado_carpeta(root: Path | None, carpeta: str | None) -> str:
    """sin-carpeta · vinculada · rota (no está o sale de la raíz) · no-disponible (raíz sin montar: no es culpa suya)."""
    if not carpeta:
        return "sin-carpeta"
    if root is None or not root.is_dir():
        return "no-disponible"
    try:
        return "vinculada" if safe_path(root, carpeta).is_dir() else "rota"
    except HTTPException:
        return "rota"


def normalizar_carpeta(raw: str | None) -> str | None:
    """La carpeta de una asignatura, siempre relativa a la raíz. Se admite pegar la ruta absoluta si está dentro
    de la raíz. Con la raíz montada, además tiene que existir (si no, 422 y no se guarda nada)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    root = uni_root()
    if raw.startswith("~") or os.path.isabs(raw):
        if root is None:
            raise HTTPException(status_code=422, detail="Elige antes la carpeta raíz (Universidad → Ajustes)")
        base = os.path.realpath(root)
        full = os.path.realpath(os.path.expanduser(raw))
        if full != base and not full.startswith(base + os.sep):
            raise HTTPException(
                status_code=422,
                detail=f"Esa carpeta no está dentro de la raíz ({root}). Cambia la raíz en Ajustes si hace falta",
            )
        rel = clean_rel(os.path.relpath(full, base)) if full != base else ""
    else:
        rel = clean_rel(raw)
    if not rel:
        raise HTTPException(status_code=422, detail="La carpeta de una asignatura no puede ser la raíz entera")
    if root is not None and root.is_dir() and not safe_path(root, rel).is_dir():
        raise HTTPException(status_code=422, detail=f"No existe «{rel}» dentro de la raíz")
    return rel


def carpeta_de(root: Path, asig) -> Path:
    if not asig["carpeta"]:
        raise HTTPException(status_code=409, detail="Elige antes la carpeta de la asignatura")
    carpeta = safe_path(root, asig["carpeta"])
    if not carpeta.is_dir():
        raise HTTPException(
            status_code=409, detail=f"No encuentro «{asig['carpeta']}» dentro de la raíz: no se ha tocado nada"
        )
    return carpeta


def ruta_en_disco(root: Path, asig, ruta: str) -> Path:
    """Dónde está un archivo: las rutas con «/» delante (vinculados a mano de fuera de la carpeta de la asignatura)
    son relativas a la raíz; las demás, a la carpeta de la asignatura. Siempre dentro de la raíz (`safe_path`)."""
    if ruta.startswith("/"):
        return safe_path(root, ruta[1:])
    return safe_path(carpeta_de(root, asig), ruta)


def _doc(path: str, rel: str, nombre: str, st) -> dict:
    return {
        "ruta": rel,
        "nombre": nombre,
        "ext": os.path.splitext(nombre)[1].lower().lstrip("."),
        "bytes": st.st_size,
        "mtime": st.st_mtime,
    }


def docs_de(carpeta: Path, ruta: str, tipo: str) -> list[dict]:
    """Documentos de un tema: el propio archivo o los de su carpeta (subcarpetas hasta MAX_PROF), en orden natural.
    Lanza OSError si no se puede leer (quien llama decide no marcar nada)."""
    if tipo == "archivo":
        p = carpeta / ruta
        st = os.stat(p, follow_symlinks=False)
        if not os.path.isfile(p) or os.path.islink(p):
            raise FileNotFoundError(ruta)
        return [_doc(str(p), ruta, os.path.basename(ruta), st)]
    out: list[dict] = []

    def walk(base: Path, rel: str, nivel: int):
        with os.scandir(base) as it:
            entries = sorted(it, key=lambda e: _natural(e.name))
        for e in entries:
            if len(out) >= MAX_ARCHIVOS_TEMA:
                return
            if not _visible(e):
                continue
            r = f"{rel}/{e.name}"
            if e.is_dir(follow_symlinks=False):
                if nivel < MAX_PROF:
                    try:
                        walk(Path(e.path), r, nivel + 1)
                    except OSError:
                        continue
            elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in DOC_EXT:
                out.append(_doc(e.path, r, e.name, e.stat(follow_symlinks=False)))

    walk(carpeta / ruta, ruta, 1)
    return out


def _mapa_temas(conn, asig_id: int) -> dict[str, int]:
    """ruta de la carpeta/archivo del tema → id del tema donde van sus archivos (siguiendo las fusiones)."""
    filas = {r["id"]: r for r in conn.execute("SELECT * FROM temas WHERE asignatura_id=?", (asig_id,))}

    def final(tid: int) -> int:
        vistos = set()
        while filas.get(tid) is not None and filas[tid]["fusionado_en"] and tid not in vistos:
            vistos.add(tid)
            sig = filas[tid]["fusionado_en"]
            if sig not in filas:
                break
            tid = sig
        return tid

    return {r["ruta"]: final(r["id"]) for r in filas.values() if r["ruta"] and r["tipo"] != "manual"}


def _tema_de_ruta(ruta: str) -> str:
    return ruta.split("/", 1)[0]


def _siguiente_orden(conn, tema_id: int | None) -> float:
    if tema_id is None:
        return 0
    return (
        conn.execute("SELECT COALESCE(MAX(orden), 0) FROM uni_archivos WHERE tema_id=?", (tema_id,)).fetchone()[0] + 1
    )


def reasignar(conn, asig_id: int) -> int:
    """Pone cada archivo (los no movidos a mano) en el tema que le toca por su carpeta. Devuelve cuántos cambian."""
    mapa = _mapa_temas(conn, asig_id)
    validos = {r["id"] for r in conn.execute("SELECT id FROM temas WHERE asignatura_id=?", (asig_id,))}
    n = 0
    for r in conn.execute(
        "SELECT id, ruta, tema_id, tema_manual FROM uni_archivos WHERE asignatura_id=? ORDER BY orden, id", (asig_id,)
    ).fetchall():
        if r["tema_manual"] and r["tema_id"] in validos:
            continue
        destino = mapa.get(_tema_de_ruta(r["ruta"]))
        if destino != r["tema_id"] or r["tema_manual"]:
            conn.execute(
                "UPDATE uni_archivos SET tema_id=?, tema_manual=0, orden=? WHERE id=?",
                (destino, _siguiente_orden(conn, destino), r["id"]),
            )
            n += 1
    return n


def sync_archivos(asig_id: int) -> dict:
    """Pone al día los archivos de los temas confirmados: añade, marca lo que falta y nunca borra. Un archivo nuevo
    en una carpeta-tema sin número («Teoria») va solo al tema que ya tiene su número (app/uni_organizar.py); lo
    vinculado a mano se comprueba donde esté y lo quitado de su tema (`oculto`) sigue quitado."""
    from app.uni_organizar import clave_de_tema, destino_por_numero, temas_con_clave

    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
        temas = conn.execute(
            "SELECT ruta, tipo FROM temas WHERE asignatura_id=? AND ruta IS NOT NULL AND tipo != 'manual' "
            "AND falta_desde IS NULL",
            (asig_id,),
        ).fetchall()
    carpeta = carpeta_de(root, asig)
    vistos: dict[str, dict] = {}
    ilegibles: set[str] = set()  # temas que no se han podido leer: sus archivos no se marcan
    for t in temas:
        try:
            for d in docs_de(carpeta, t["ruta"], t["tipo"]):
                vistos[d["ruta"]] = d
        except OSError:
            ilegibles.add(t["ruta"])
    now = time.time()
    res = {"nuevos": 0, "faltan": 0, "vuelven": 0, "repartidos": 0}
    with get_db() as conn:
        mapa = _mapa_temas(conn, asig_id)
        _, por_numero = temas_con_clave(conn, asig_id)
        claves = {
            r["id"]: clave_de_tema(r) for r in conn.execute("SELECT * FROM temas WHERE asignatura_id=?", (asig_id,))
        }
        actuales = {r["ruta"]: r for r in conn.execute("SELECT * FROM uni_archivos WHERE asignatura_id=?", (asig_id,))}
        for ruta in sorted(vistos, key=_natural):
            d = vistos[ruta]
            r = actuales.pop(ruta, None)
            destino = mapa.get(_tema_de_ruta(ruta))
            if r is None:
                manual = destino_por_numero(ruta, destino, claves, por_numero)
                if manual is not None:
                    destino = manual
                    res["repartidos"] += 1
                conn.execute(
                    "INSERT INTO uni_archivos (asignatura_id, tema_id, ruta, nombre, ext, bytes, mtime, orden, "
                    "tema_manual) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        asig_id,
                        destino,
                        ruta,
                        d["nombre"],
                        d["ext"],
                        d["bytes"],
                        d["mtime"],
                        _siguiente_orden(conn, destino),
                        int(manual is not None),
                    ),
                )
                res["nuevos"] += 1
                continue
            if r["falta_desde"] is not None:
                res["vuelven"] += 1
            conn.execute(
                "UPDATE uni_archivos SET nombre=?, ext=?, bytes=?, mtime=?, falta_desde=NULL WHERE id=?",
                (d["nombre"], d["ext"], d["bytes"], d["mtime"], r["id"]),
            )
            if not r["tema_manual"] and r["tema_id"] != destino:
                conn.execute(
                    "UPDATE uni_archivos SET tema_id=?, orden=? WHERE id=?",
                    (destino, _siguiente_orden(conn, destino), r["id"]),
                )
        for r in actuales.values():  # ya no están en un tema-carpeta: se marcan, no se borran (la página se conserva)
            if r["nombre"].lower() in IGNORAR:  # ruido que antes se contaba (CMakeLists.txt): se quita sin marcarlo
                if not r["oculto"]:
                    conn.execute("UPDATE uni_archivos SET oculto=1 WHERE id=?", (r["id"],))
                continue
            if r["tema_id"] is None or _tema_de_ruta(r["ruta"]) in ilegibles:
                continue
            if r["tema_manual"]:  # vinculado a mano: puede estar en cualquier sitio de la raíz
                try:
                    existe = ruta_en_disco(root, asig, r["ruta"]).is_file()
                except HTTPException:
                    existe = False
                if existe:
                    if r["falta_desde"] is not None:
                        conn.execute("UPDATE uni_archivos SET falta_desde=NULL WHERE id=?", (r["id"],))
                        res["vuelven"] += 1
                    continue
            if r["falta_desde"] is None:
                conn.execute("UPDATE uni_archivos SET falta_desde=? WHERE id=?", (now, r["id"]))
                res["faltan"] += 1
    return res


# ─────────────────────────────────────────────
# Propuesta de temas (se confirma: crear, renombrar, reordenar, fusionar, descartar)
# ─────────────────────────────────────────────


def _contar_docs(carpeta: Path, t: dict) -> tuple[int, int]:
    try:
        docs = docs_de(carpeta, t["ruta"], t["tipo"])
    except OSError:
        return 0, 0
    return len(docs), sum(1 for d in docs if d["ext"] in VISOR_EXT)


def candidatos(conn, asig, carpeta: Path) -> tuple[list[dict], list[dict]]:
    """(nuevos, descartados) de la carpeta: lo que aún no es tema. Lanza OSError si la carpeta no se lee."""
    vistos = escanear(carpeta)
    ignorar = set(_jl(asig["ignorar"]))
    actuales = {
        r["ruta"]
        for r in conn.execute("SELECT ruta FROM temas WHERE asignatura_id=? AND ruta IS NOT NULL", (asig["id"],))
    }
    nuevos, descartados = [], []
    for t in vistos:
        if t["ruta"] in actuales:
            continue
        titulo = sugerir_titulo(t["nombre"], t["tipo"] == "archivo")
        t = {**t, "titulo": titulo, "grupo": _grupo_por_titulo(titulo, t["grupo"])}
        (descartados if t["ruta"] in ignorar else nuevos).append(t)
    return sorted(nuevos, key=_orden_sugerido), descartados


def _grupo_por_titulo(titulo: str, grupo: str) -> str:
    """«Tema 2 · …» es teoría y «Práctica 1» prácticas aunque la carpeta se llame «T2 - Procesos» o «P1»."""
    if titulo.startswith("Práctica "):
        return "practicas"
    if titulo.startswith("Tema ") and grupo == "otros":
        return "teoria"
    return grupo


def _orden_sugerido(t: dict):
    """Por grupo y, dentro, por el número del título (Tema 2 antes que Tema 10) y luego el nombre."""
    m = re.match(r"^(?:Tema|Práctica) (\d+)", t["titulo"])
    return (GRUPOS.index(t["grupo"]), 0 if m else 1, int(m.group(1)) if m else 0, _natural(t["nombre"]))


def propuesta_temas(asig_id: int) -> dict:
    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
    carpeta = carpeta_de(root, asig)
    try:
        with get_db() as conn:
            nuevos, descartados = candidatos(conn, asig, carpeta)
    except OSError as e:
        raise HTTPException(status_code=409, detail=f"No se puede leer la carpeta ({e.strerror}): no se ha tocado nada")
    for t in nuevos + descartados:
        t["archivos"], t["pdfs"] = _contar_docs(carpeta, t)
    with get_db() as conn:
        _proponer_fusiones(conn, asig_id, nuevos)
        conn.execute("UPDATE asignaturas SET por_confirmar=? WHERE id=?", (len(nuevos), asig_id))
        existentes = [
            {"id": r["id"], "titulo": r["titulo"], "grupo": r["grupo"]}
            for r in conn.execute(
                "SELECT id, titulo, grupo FROM temas WHERE asignatura_id=? AND fusionado_en IS NULL ORDER BY orden, id",
                (asig_id,),
            )
        ]
        faltan = [
            {"id": r["id"], "titulo": r["titulo"], "ruta": r["ruta"]}
            for r in conn.execute(
                "SELECT id, titulo, ruta FROM temas WHERE asignatura_id=? AND falta_desde IS NOT NULL AND fusionado_en IS NULL",
                (asig_id,),
            )
        ]
    return {"nuevos": nuevos, "descartados": descartados, "existentes": existentes, "faltan": faltan}


def _proponer_fusiones(conn, asig_id: int, nuevos: list[dict]) -> None:
    """Lo que tiene el mismo número va junto: «tema3 - primera parte» y «tema3 - segunda parte» (y «lesson3»)
    salen como un solo «Tema 3» y lo que ya tiene tema con ese número se propone fusionado con él. Solo es la
    propuesta por defecto (`accion`, `destino`): en el diálogo se cambia."""
    from app.uni_organizar import TITULO, clave_de_nombre, temas_con_clave

    _, existentes = temas_con_clave(conn, asig_id)
    primero: dict[tuple, dict] = {}
    grupos: dict[tuple, int] = {}
    for t in nuevos:
        k = clave_de_nombre(t["titulo"]) or clave_de_nombre(os.path.splitext(t["nombre"])[0])
        t["accion"], t["destino"] = "crear", None
        if not k:
            continue
        grupos[k] = grupos.get(k, 0) + 1
        if k in existentes:
            t["accion"], t["destino"] = "fusionar", f"tema:{existentes[k]}"
        elif k in primero:
            t["accion"], t["destino"] = "fusionar", primero[k]["ruta"]
        else:
            primero[k] = t
    for k, t in primero.items():  # varias partes del mismo tema: el título, sin la «primera parte»
        if grupos[k] > 1:
            t["titulo"] = f"{TITULO[k[0]]} {k[1]}"
            t["grupo"] = k[0]


class TemaPropuesto(BaseModel):
    ruta: str = Field(min_length=1, max_length=1000)
    titulo: str | None = Field(default=None, max_length=200)
    grupo: str | None = Field(default=None, max_length=12)
    accion: Literal["crear", "fusionar", "descartar", "luego"] = "crear"
    destino: str | None = Field(default=None, max_length=1010)  # «tema:<id>» o la ruta de otro propuesto


class PropuestaIn(BaseModel):
    temas: list[TemaPropuesto] = Field(default_factory=list, max_length=1000)
    recuperar: list[str] = Field(default_factory=list, max_length=1000)  # descartados que vuelven a proponerse


def aplicar_temas(asig_id: int, data: PropuestaIn) -> dict:
    """Crea los temas confirmados en el orden dado, fusiona y descarta. Solo vale lo que está en la carpeta ahora."""
    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
    carpeta = carpeta_de(root, asig)
    try:
        vistos = {t["ruta"]: t for t in escanear(carpeta)}
    except OSError as e:
        raise HTTPException(status_code=409, detail=f"No se puede leer la carpeta ({e.strerror}): no se ha tocado nada")
    res = {"creados": 0, "fusionados": 0, "descartados": 0, "recuperados": 0}
    with get_db() as conn:
        actuales = {
            r["ruta"]
            for r in conn.execute("SELECT ruta FROM temas WHERE asignatura_id=? AND ruta IS NOT NULL", (asig_id,))
        }
        ignorar = list(_jl(asig["ignorar"]))
        for ruta in data.recuperar:
            if ruta in ignorar:
                ignorar.remove(ruta)
                res["recuperados"] += 1
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) FROM temas WHERE asignatura_id=?", (asig_id,)).fetchone()[
            0
        ]
        creados: dict[str, int] = {}
        validos = [t for t in data.temas if t.ruta in vistos and t.ruta not in actuales]
        for t in validos:
            if t.accion != "crear":
                continue
            v = vistos[t.ruta]
            sugerido = sugerir_titulo(v["nombre"], v["tipo"] == "archivo")
            titulo = (t.titulo or "").strip() or sugerido
            grupo = t.grupo if t.grupo in GRUPOS else v["grupo"]
            orden += 1
            cur = conn.execute(
                "INSERT INTO temas (asignatura_id, titulo, nombre_carpeta, ruta, tipo, grupo, orden, titulo_manual) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (asig_id, titulo, v["nombre"], t.ruta, v["tipo"], grupo, orden, int(titulo != sugerido)),
            )
            creados[t.ruta] = cur.lastrowid
            res["creados"] += 1
        for t in validos:
            v = vistos[t.ruta]
            if t.accion == "descartar":
                if t.ruta not in ignorar:
                    ignorar.append(t.ruta)
                res["descartados"] += 1
            elif t.accion == "fusionar":
                destino = _destino(conn, asig_id, t.destino, creados)
                if destino is None:
                    continue
                d = conn.execute("SELECT grupo FROM temas WHERE id=?", (destino,)).fetchone()
                conn.execute(
                    "INSERT INTO temas (asignatura_id, titulo, nombre_carpeta, ruta, tipo, grupo, orden, fusionado_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        asig_id,
                        sugerir_titulo(v["nombre"], v["tipo"] == "archivo"),
                        v["nombre"],
                        t.ruta,
                        v["tipo"],
                        d["grupo"],
                        orden + 1,
                        destino,
                    ),
                )
                res["fusionados"] += 1
        conn.execute("UPDATE asignaturas SET ignorar=? WHERE id=?", (json.dumps(ignorar, ensure_ascii=False), asig_id))
    res["archivos"] = sync_archivos(asig_id)
    with get_db() as conn:  # lo que queda por confirmar (lo dejado «para luego»)
        try:
            nuevos, _ = candidatos(conn, get_asig(conn, asig_id), carpeta)
            conn.execute("UPDATE asignaturas SET por_confirmar=? WHERE id=?", (len(nuevos), asig_id))
            res["por_confirmar"] = len(nuevos)
        except OSError:
            res["por_confirmar"] = None
    log.info("Temas confirmados en %s: %s", asig["codigo"], res)
    return res


def _destino(conn, asig_id: int, destino: str | None, creados: dict[str, int]) -> int | None:
    if not destino:
        return None
    if destino.startswith("tema:"):
        try:
            tid = int(destino[5:])
        except ValueError:
            return None
        r = conn.execute(
            "SELECT id FROM temas WHERE id=? AND asignatura_id=? AND fusionado_en IS NULL", (tid, asig_id)
        ).fetchone()
        return r["id"] if r else None
    return creados.get(destino)


# ─────────────────────────────────────────────
# Fusionar y separar temas
# ─────────────────────────────────────────────


def _cambiar_tema_en_listas(conn, viejo: int, nuevo: int) -> None:
    """Tareas y eventos que citan el tema fusionado pasan a citar el otro (columna JSON `temas`)."""
    for tabla in ("inbox", "events"):
        for r in conn.execute(
            f"SELECT id, temas FROM {tabla} WHERE temas IS NOT NULL AND temas LIKE ?", (f"%{viejo}%",)
        ).fetchall():
            lista = _jl(r["temas"])
            if viejo not in lista:
                continue
            nueva = list(dict.fromkeys(nuevo if x == viejo else x for x in lista))
            conn.execute(f"UPDATE {tabla} SET temas=? WHERE id=?", (json.dumps(nueva), r["id"]))


def fusionar(tema_id: int, destino_id: int) -> dict:
    with get_db() as conn:
        t, d = get_tema(conn, tema_id), get_tema(conn, destino_id)
        if t["id"] == d["id"]:
            raise HTTPException(status_code=422, detail="Elige otro tema")
        if t["asignatura_id"] != d["asignatura_id"]:
            raise HTTPException(status_code=422, detail="Solo se fusionan temas de la misma asignatura")
        if t["fusionado_en"] or d["fusionado_en"]:
            raise HTTPException(status_code=409, detail="Ese tema ya está fusionado con otro")
        conn.execute("UPDATE temas SET fusionado_en=? WHERE fusionado_en=?", (d["id"], t["id"]))
        conn.execute("UPDATE temas SET fusionado_en=? WHERE id=?", (d["id"], t["id"]))
        base = _siguiente_orden(conn, d["id"])
        for i, r in enumerate(
            conn.execute("SELECT id FROM uni_archivos WHERE tema_id=? ORDER BY orden, id", (t["id"],)).fetchall()
        ):
            conn.execute("UPDATE uni_archivos SET tema_id=?, orden=? WHERE id=?", (d["id"], base + i, r["id"]))
        conn.execute(
            "INSERT OR IGNORE INTO uni_ejercicio_temas (ejercicio_id, tema_id) "
            "SELECT ejercicio_id, ? FROM uni_ejercicio_temas WHERE tema_id=?",
            (d["id"], t["id"]),
        )
        conn.execute("DELETE FROM uni_ejercicio_temas WHERE tema_id=?", (t["id"],))
        _cambiar_tema_en_listas(conn, t["id"], d["id"])
        if not d["note_id"] and t["note_id"]:
            conn.execute("UPDATE temas SET note_id=? WHERE id=?", (t["note_id"], d["id"]))
    return {"tema_id": d["id"]}


def separar(tema_id: int) -> dict:
    """Deshace una fusión: el tema vuelve a verse y recupera los archivos de su carpeta (los movidos a mano no).
    Los ejercicios y tareas que pasaron al otro se quedan allí."""
    with get_db() as conn:
        t = get_tema(conn, tema_id)
        if not t["fusionado_en"]:
            raise HTTPException(status_code=409, detail="Ese tema no está fusionado")
        conn.execute("UPDATE temas SET fusionado_en=NULL WHERE id=?", (tema_id,))
        n = reasignar(conn, t["asignatura_id"])
    return {"archivos": n}


# ─────────────────────────────────────────────
# Archivos de un tema
# ─────────────────────────────────────────────


def archivo_out(r) -> dict:
    return {
        "id": r["id"],
        "tema_id": r["tema_id"],
        "ruta": r["ruta"],
        "nombre": r["nombre"],
        "ext": r["ext"],
        "bytes": r["bytes"],
        "falta": r["falta_desde"] is not None,
        "pagina": r["pagina"],
        "paginas": r["paginas"],
        "leido_at": r["leido_at"],
        "tema_manual": bool(r["tema_manual"]),
        "fuera": r["ruta"].startswith("/"),  # vinculado a mano desde fuera de la carpeta de la asignatura
        "visor": r["ext"] in VISOR_EXT,
    }


def get_archivo(conn, archivo_id: int):
    r = conn.execute("SELECT * FROM uni_archivos WHERE id=?", (archivo_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return r


def archivos_de_tema(tema_id: int) -> dict:
    from app.universidad import _tema_out

    with get_db() as conn:
        t = get_tema(conn, tema_id)
        if t["fusionado_en"]:
            t = get_tema(conn, t["fusionado_en"])
        archivos = [
            archivo_out(r)
            for r in conn.execute(
                "SELECT * FROM uni_archivos WHERE tema_id=? AND oculto=0 ORDER BY falta_desde IS NOT NULL, orden, id",
                (t["id"],),
            )
        ]
        fusionados = [
            {"id": r["id"], "titulo": r["titulo"], "ruta": r["ruta"]}
            for r in conn.execute(
                "SELECT id, titulo, ruta FROM temas WHERE fusionado_en=? ORDER BY orden, id", (t["id"],)
            )
        ]
        tema = _tema_out(t)
    return {"tema": tema, "archivos": archivos, "fusionados": fusionados}


class ArchivoPatch(BaseModel):
    pagina: int | None = Field(default=None, ge=1, le=100000)
    paginas: int | None = Field(default=None, ge=1, le=100000)
    tema_id: int | None = None  # 0 = devolverlo al tema de su carpeta
    before_id: int | None = None  # 0 = al final
    oculto: bool | None = None  # quitarlo de su tema (o devolverlo): el disco no se toca


def update_archivo(archivo_id: int, data: ArchivoPatch) -> dict:
    with get_db() as conn:
        a = get_archivo(conn, archivo_id)
        if data.pagina is not None:
            paginas = data.paginas or a["paginas"]
            pagina = min(data.pagina, paginas) if paginas else data.pagina
            conn.execute(
                "UPDATE uni_archivos SET pagina=?, paginas=?, leido_at=? WHERE id=?",
                (pagina, paginas, time.time(), archivo_id),
            )
        elif data.paginas is not None:
            conn.execute("UPDATE uni_archivos SET paginas=? WHERE id=?", (data.paginas, archivo_id))
        if data.tema_id is not None:
            if data.tema_id == 0:
                conn.execute("UPDATE uni_archivos SET tema_manual=0 WHERE id=?", (archivo_id,))
                reasignar(conn, a["asignatura_id"])
            else:
                t = get_tema(conn, data.tema_id)
                if t["asignatura_id"] != a["asignatura_id"]:
                    raise HTTPException(status_code=422, detail="Un archivo se queda en su asignatura")
                destino = t["fusionado_en"] or t["id"]
                if destino != a["tema_id"] or a["oculto"]:
                    conn.execute(
                        "UPDATE uni_archivos SET tema_id=?, tema_manual=1, oculto=0, orden=? WHERE id=?",
                        (destino, _siguiente_orden(conn, destino), archivo_id),
                    )
            a = get_archivo(conn, archivo_id)
        if data.oculto is not None:
            conn.execute("UPDATE uni_archivos SET oculto=? WHERE id=?", (int(data.oculto), archivo_id))
            a = get_archivo(conn, archivo_id)
        if data.before_id is not None and a["tema_id"] is not None:
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM uni_archivos WHERE tema_id=? AND id != ? AND oculto=0 ORDER BY orden, id",
                    (a["tema_id"], archivo_id),
                )
            ]
            pos = ids.index(data.before_id) if data.before_id in ids else len(ids)
            ids.insert(pos, archivo_id)
            for i, x in enumerate(ids):
                conn.execute("UPDATE uni_archivos SET orden=? WHERE id=?", (i + 1, x))
        return archivo_out(get_archivo(conn, archivo_id))


def ruta_archivo(archivo_id: int) -> tuple[Path, dict]:
    """La ruta en disco de un archivo, con todas las comprobaciones. Si el disco está y el archivo no, lo marca
    como no encontrado (y si vuelve a estar, lo desmarca)."""
    with get_db() as conn:
        a = get_archivo(conn, archivo_id)
        asig = get_asig(conn, a["asignatura_id"])
    if a["ext"] and f".{a['ext']}" not in DOC_EXT:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    root = root_ready()
    path = ruta_en_disco(root, asig, a["ruta"])  # 409 si la carpeta de la asignatura no está: no se marca nada
    existe = path.is_file() and not os.path.islink(path)
    with get_db() as conn:
        if not existe and a["falta_desde"] is None:
            conn.execute("UPDATE uni_archivos SET falta_desde=? WHERE id=?", (time.time(), archivo_id))
        elif existe and a["falta_desde"] is not None:
            conn.execute("UPDATE uni_archivos SET falta_desde=NULL WHERE id=?", (archivo_id,))
    if not existe:
        raise HTTPException(status_code=404, detail=f"No encontrado: «{a['nombre']}» ya no está en la carpeta")
    return path, archivo_out(a)


def borrar_archivo(archivo_id: int) -> None:
    """Quitar de la lista un archivo que ya no está (en el disco no se toca nada)."""
    with get_db() as conn:
        a = get_archivo(conn, archivo_id)
        if a["falta_desde"] is None:
            raise HTTPException(status_code=409, detail="Ese archivo sigue en la carpeta: volvería al sincronizar")
        conn.execute("DELETE FROM uni_archivos WHERE id=?", (archivo_id,))
        conn.execute("UPDATE uni_ejercicios SET archivo_id=NULL, pagina=NULL WHERE archivo_id=?", (archivo_id,))


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────


@router.get("/carpeta-estado")
def api_carpeta_estado(ruta: str = Query(default="", max_length=1000)):
    """Para el diálogo de la asignatura: ¿vale esta carpeta? Nunca escribe nada."""
    root = uni_root()
    try:
        rel = normalizar_carpeta(ruta)
    except HTTPException as e:
        return {"ruta": None, "estado": "invalida", "mensaje": e.detail}
    estado = estado_carpeta(root, rel)
    out = {"ruta": rel, "estado": estado, "mensaje": "", "temas": None}
    if estado == "vinculada":
        try:
            out["temas"] = len(escanear(safe_path(root, rel)))
        except OSError:
            pass
    elif estado == "no-disponible":
        out["mensaje"] = "La carpeta raíz no está disponible ahora (¿disco sin montar?): se comprobará al sincronizar"
    return out


@router.get("/asignaturas/{asig_id}/escaneo")
def api_propuesta_temas(asig_id: int):
    return propuesta_temas(asig_id)


@router.post("/asignaturas/{asig_id}/escaneo")
def api_aplicar_temas(asig_id: int, data: PropuestaIn):
    return aplicar_temas(asig_id, data)


class FusionarIn(BaseModel):
    destino_id: int = Field(ge=1)


@router.post("/temas/{tema_id}/fusionar")
def api_fusionar(tema_id: int, data: FusionarIn):
    return fusionar(tema_id, data.destino_id)


@router.post("/temas/{tema_id}/separar")
def api_separar(tema_id: int):
    return separar(tema_id)


@router.get("/temas/{tema_id}/archivos")
def api_archivos_tema(tema_id: int):
    return archivos_de_tema(tema_id)


@router.get("/asignaturas/{asig_id}/archivos")
def api_archivos_asig(asig_id: int):
    """Todos los archivos de la asignatura (para elegir dónde está un ejercicio), por tema."""
    with get_db() as conn:
        get_asig(conn, asig_id)
        rows = conn.execute(
            "SELECT a.*, t.titulo AS tema_titulo FROM uni_archivos a JOIN temas t ON t.id=a.tema_id "
            "WHERE a.asignatura_id=? AND a.oculto=0 ORDER BY t.orden, t.id, a.falta_desde IS NOT NULL, a.orden, a.id",
            (asig_id,),
        ).fetchall()
    return {"archivos": [{**archivo_out(r), "tema_titulo": r["tema_titulo"]} for r in rows]}


@router.patch("/archivos/{archivo_id}")
def api_update_archivo(archivo_id: int, data: ArchivoPatch):
    return update_archivo(archivo_id, data)


@router.delete("/archivos/{archivo_id}")
def api_borrar_archivo(archivo_id: int):
    borrar_archivo(archivo_id)
    return {"status": "success"}


@router.get("/archivos/{archivo_id}/info")
def api_info_archivo(archivo_id: int):
    with get_db() as conn:
        return archivo_out(get_archivo(conn, archivo_id))


@router.get("/archivos/{archivo_id}/contenido")
def api_contenido(archivo_id: int):
    """El archivo para leerlo (PDF en el lector o en otra pestaña). Solo lectura; con Range para PDFs grandes."""
    path, a = ruta_archivo(archivo_id)
    ext = a["ext"]
    media = INLINE.get(ext) or mimetypes.guess_type(a["nombre"])[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=a["nombre"],
        content_disposition_type="inline" if ext in INLINE else "attachment",
        headers={"Cache-Control": "private, no-cache"},
    )
