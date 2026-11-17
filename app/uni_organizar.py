"""
Universidad · repartir los documentos en sus temas: solo, por el número del nombre, y a mano. Solo lectura sobre el
disco (como app/universidad.py y app/uni_archivos.py): se lista y se lee, nunca se escribe ni se mueve nada.

  - `detectar(ruta)`: («teoria» | «practicas», número) por el nombre del archivo o, si no dice nada, por sus
    carpetas: «Chuletario_Tema3», «Relación 4», «tema3 - primera parte», «lesson3», «IGV_Practica2_pr2a»,
    «Practica 3/guion.pdf»… Los temas tienen la misma clave por su título («Tema 3 · …», «Práctica 2»).
  - Al sincronizar (`sync_archivos`), un archivo NUEVO que cae en una carpeta-tema sin número («Teoria») o en
    ninguna va solo al tema que ya existe con su número. Los temas nuevos no se crean solos.
  - Organizar (`GET/POST /asignaturas/{id}/organizar`): todos los documentos de la carpeta con su tema y la
    sugerencia; se aplican de golpe (creando «Tema N» / «Práctica N» si faltan) o uno a uno, y se puede quitar
    un documento de su tema (`uni_archivos.oculto`: la sincronía no lo vuelve a poner).
  - Explorador de la raíz (`GET /explorar`) y vincular a mano cualquier documento de la raíz a un tema
    (`POST /temas/{id}/vincular`), también uno suelto o de fuera de la carpeta de la asignatura: entonces la ruta
    se guarda relativa a la raíz con «/» delante (ver `uni_archivos.ruta_en_disco`).
"""

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import contextos
from app.database import get_db
from app.uni_archivos import MAX_PROF, VISOR_EXT, _siguiente_orden, carpeta_de
from app.universidad import (
    DOC_EXT,
    IGNORAR,
    _jl,
    _natural,
    _visible,
    clean_rel,
    get_asig,
    get_tema,
    root_ready,
    safe_path,
)
from core.logging_config import get_logger

log = get_logger("universidad")
router = APIRouter(prefix="/api/uni")

MAX_DOCS = 1500  # documentos de una asignatura que se miran para organizar
MAX_ENTRADAS = 600  # entradas de una carpeta en el explorador

# ─────────────────────────────────────────────
# Número de tema o de práctica por el nombre
# ─────────────────────────────────────────────

_B = r"(?:^|[^a-z0-9])"  # inicio de palabra (los números pegados a letras también valen: «tema3», «pr2a»)
_N = r"\s?0*(\d{1,2})(?!\d)"
PRACTICA_RES = (
    re.compile(_B + r"(?:practicas?|practice|pract|laboratorio|lab|pr)" + _N),
    re.compile(_B + r"p0*(\d{1,2})(?![\da-z])"),  # «P2», «p03» (no «p2a» ni «mp3»)
)
TEMA_RES = (
    re.compile(
        _B + r"(?:temas?|lesson|leccion|unidad|capitulo|chapter|bloque|"
        r"relacion(?:\s+de\s+ejercicios)?|boletin(?:\s+de\s+ejercicios)?|hoja\s+de\s+ejercicios)" + _N
    ),
    re.compile(_B + r"(?:t|ud)" + r"\s?0*(\d{1,2})(?![\da-z])"),  # «T3», «t 03», «UD2»
)
TITULO = {"teoria": "Tema", "practicas": "Práctica"}


def _limpio(s: str) -> str:
    """minúsculas, sin tildes y con los separadores como espacios: «IGV_Practica2-pr2a» → «igv practica2 pr2a»."""
    return re.sub(r"\s+", " ", re.sub(r"[_\-.+()\[\]{},;]+", " ", contextos.fold(s))).strip()


def clave_de_nombre(nombre: str) -> tuple[str, int] | None:
    """(grupo, número) de un nombre suelto; si nombra tema y práctica, manda lo que aparece antes."""
    s = _limpio(nombre)
    mejor: tuple[int, str, int] | None = None
    for grupo, res in (("practicas", PRACTICA_RES), ("teoria", TEMA_RES)):
        for rx in res:
            m = rx.search(s)
            if m and (mejor is None or m.start() < mejor[0]):
                mejor = (m.start(), grupo, int(m.group(1)))
    return (mejor[1], mejor[2]) if mejor else None


def detectar(ruta: str) -> tuple[str, int] | None:
    """Por el nombre del archivo y, si no dice nada, por su carpeta más cercana que sí lo diga."""
    partes = [p for p in ruta.strip("/").split("/") if p]
    if not partes:
        return None
    nombres = [os.path.splitext(partes[-1])[0], *reversed(partes[:-1])]
    for n in nombres:
        k = clave_de_nombre(n)
        if k:
            return k
    return None


def clave_de_tema(t) -> tuple[str, int] | None:
    """La clave de un tema por su título y, si no, por el nombre de su carpeta o archivo."""
    for n in (t["titulo"], t["nombre_carpeta"] or ""):
        k = clave_de_nombre(n) if n else None
        if k:
            return k
    return None


def nombre_clave(k: tuple[str, int]) -> str:
    return f"{k[0]}:{k[1]}"


def temas_con_clave(conn, asig_id: int) -> tuple[list[dict], dict[tuple[str, int], int]]:
    """Temas visibles de la asignatura con su clave y el mapa clave → tema (el primero por orden)."""
    temas = [
        {"id": r["id"], "titulo": r["titulo"], "grupo": r["grupo"], "orden": r["orden"], "clave": clave_de_tema(r)}
        for r in conn.execute(
            "SELECT * FROM temas WHERE asignatura_id=? AND fusionado_en IS NULL ORDER BY orden, id", (asig_id,)
        )
    ]
    mapa: dict[tuple[str, int], int] = {}
    for t in temas:
        if t["clave"] and t["clave"] not in mapa:
            mapa[t["clave"]] = t["id"]
    return temas, mapa


def destino_por_numero(
    ruta: str, tema_carpeta: int | None, claves_tema: dict[int, tuple | None], mapa: dict
) -> int | None:
    """El tema al que va un archivo por su número, solo si su tema por carpeta no tiene número propio («Teoria») o
    no tiene ninguno: un PDF de la Práctica 1 guardado dentro de «Practica 5» se queda en la 5."""
    if tema_carpeta is not None and claves_tema.get(tema_carpeta):
        return None
    k = detectar(ruta)
    destino = mapa.get(k) if k else None
    return destino if destino != tema_carpeta else None


# ─────────────────────────────────────────────
# Documentos de la carpeta de una asignatura (solo lectura)
# ─────────────────────────────────────────────


def _doc_ok(nombre: str) -> bool:
    return os.path.splitext(nombre)[1].lower() in DOC_EXT and nombre.lower() not in IGNORAR


def docs_carpeta(carpeta: Path, ignorar: set[str]) -> list[dict]:
    """Todos los documentos de la carpeta (subcarpetas hasta MAX_PROF + 1), sin lo descartado como tema."""
    out: list[dict] = []

    def walk(base: Path, rel: str, nivel: int):
        with os.scandir(base) as it:
            entries = sorted(it, key=lambda e: _natural(e.name))
        for e in entries:
            if len(out) >= MAX_DOCS:
                return
            if not _visible(e):
                continue
            r = f"{rel}/{e.name}" if rel else e.name
            if not rel and r in ignorar:
                continue
            if e.is_dir(follow_symlinks=False):
                if nivel <= MAX_PROF:
                    try:
                        walk(Path(e.path), r, nivel + 1)
                    except OSError:
                        continue
            elif e.is_file(follow_symlinks=False) and _doc_ok(e.name):
                st = e.stat(follow_symlinks=False)
                out.append(
                    {
                        "ruta": r,
                        "nombre": e.name,
                        "ext": os.path.splitext(e.name)[1].lower().lstrip("."),
                        "bytes": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )

    walk(carpeta, "", 0)
    return out


def _fila_doc(path: Path, ruta: str) -> dict:
    if not path.is_file() or os.path.islink(path) or not _doc_ok(path.name):
        raise HTTPException(status_code=422, detail=f"«{ruta.lstrip('/')}» no es un documento (PDF, Word, apuntes…)")
    st = os.stat(path, follow_symlinks=False)
    return {
        "ruta": ruta,
        "nombre": path.name,
        "ext": path.suffix.lower().lstrip("."),
        "bytes": st.st_size,
        "mtime": st.st_mtime,
    }


def _ruta_guardada(root: Path, asig, rel_raiz: str) -> str:
    """Ruta relativa a la raíz → la que se guarda: relativa a la carpeta de la asignatura si está dentro;
    si no, relativa a la raíz y con «/» delante."""
    rel_raiz = clean_rel(rel_raiz)
    carpeta = asig["carpeta"]
    if carpeta and (rel_raiz == carpeta or rel_raiz.startswith(carpeta + "/")):
        return rel_raiz[len(carpeta) + 1 :]
    return "/" + rel_raiz


def _ruta_en_raiz(asig, ruta: str) -> str:
    return ruta[1:] if ruta.startswith("/") else f"{asig['carpeta']}/{ruta}"


def asignar(conn, asig_id: int, doc: dict, tema_id: int) -> str:
    """Pone un documento en un tema a mano (fila nueva o la que ya había): «nuevo», «movido» o «igual»."""
    r = conn.execute("SELECT * FROM uni_archivos WHERE asignatura_id=? AND ruta=?", (asig_id, doc["ruta"])).fetchone()
    if r is None:
        conn.execute(
            "INSERT INTO uni_archivos (asignatura_id, tema_id, ruta, nombre, ext, bytes, mtime, orden, tema_manual) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                asig_id,
                tema_id,
                doc["ruta"],
                doc["nombre"],
                doc["ext"],
                doc["bytes"],
                doc["mtime"],
                _siguiente_orden(conn, tema_id),
            ),
        )
        return "nuevo"
    if r["tema_id"] == tema_id and not r["oculto"]:
        return "igual"
    conn.execute(
        "UPDATE uni_archivos SET tema_id=?, tema_manual=1, oculto=0, falta_desde=NULL, orden=? WHERE id=?",
        (tema_id, _siguiente_orden(conn, tema_id), r["id"]),
    )
    return "movido"


def _tema_destino(conn, asig_id: int, tema_id: int) -> int:
    t = get_tema(conn, tema_id)
    if t["asignatura_id"] != asig_id:
        raise HTTPException(status_code=422, detail="Ese tema es de otra asignatura")
    return t["fusionado_en"] or t["id"]


# ─────────────────────────────────────────────
# Organizar: plan con sugerencias y aplicarlo
# ─────────────────────────────────────────────


def plan(asig_id: int) -> dict:
    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
        temas, mapa = temas_con_clave(conn, asig_id)
        filas = {r["ruta"]: r for r in conn.execute("SELECT * FROM uni_archivos WHERE asignatura_id=?", (asig_id,))}
    claves_tema = {t["id"]: t["clave"] for t in temas}
    visibles = {t["id"] for t in temas}
    docs: list[dict] = []
    if asig["carpeta"]:
        carpeta = carpeta_de(root, asig)
        try:
            docs = docs_carpeta(carpeta, set(_jl(asig["ignorar"])))
        except OSError as e:
            raise HTTPException(status_code=409, detail=f"No se puede leer la carpeta ({e.strerror})") from e
    en_disco = {d["ruta"] for d in docs}
    # Los vinculados a mano de fuera de la carpeta (o que están más hondo de lo que se mira) también salen
    for ruta, r in filas.items():
        if ruta not in en_disco and r["tema_manual"] and r["falta_desde"] is None:
            docs.append({"ruta": ruta, "nombre": r["nombre"], "ext": r["ext"], "bytes": r["bytes"]})
    nuevos: dict[str, dict] = {}
    out = []
    for d in docs:
        r = filas.get(d["ruta"])
        actual = r["tema_id"] if r is not None and not r["oculto"] and r["tema_id"] in visibles else None
        sugerido = None
        k = detectar(d["ruta"])
        if k and (actual is None or not claves_tema.get(actual)):
            if k in mapa:
                if mapa[k] != actual:
                    sugerido = f"tema:{mapa[k]}"
            else:
                sugerido = f"nuevo:{nombre_clave(k)}"
                nuevos.setdefault(nombre_clave(k), {"titulo": f"{TITULO[k[0]]} {k[1]}", "grupo": k[0], "n": k[1]})
        out.append(
            {
                "ruta": d["ruta"],
                "nombre": d["nombre"],
                "ext": d["ext"],
                "carpeta": os.path.dirname(d["ruta"].lstrip("/")) if not d["ruta"].startswith("/") else "(fuera)",
                "fuera": d["ruta"].startswith("/"),
                "tema_id": actual,
                "quitado": bool(r is not None and r["oculto"]),
                "sugerido": sugerido,
            }
        )
    return {
        "temas": [{k: t[k] for k in ("id", "titulo", "grupo")} for t in temas],
        "archivos": out,
        "nuevos": dict(sorted(nuevos.items(), key=lambda kv: (kv[1]["grupo"] != "teoria", kv[1]["n"]))),
        "sugerencias": sum(1 for x in out if x["sugerido"]),
        "sin_tema": sum(1 for x in out if x["tema_id"] is None and not x["quitado"]),
    }


class Cambio(BaseModel):
    ruta: str = Field(min_length=1, max_length=1000)
    destino: str = Field(min_length=1, max_length=40)  # «tema:<id>», «nuevo:teoria:3» o «quitar»


class OrganizarIn(BaseModel):
    cambios: list[Cambio] = Field(default_factory=list, max_length=MAX_DOCS)
    titulos: dict[str, str] = Field(default_factory=dict)  # «teoria:3» → título del tema nuevo (si se cambia)


def _crear_tema_por_clave(conn, asig_id: int, clave: str, titulo: str | None) -> int:
    grupo, _, n = clave.partition(":")
    if grupo not in TITULO or not n.isdigit():
        raise HTTPException(status_code=422, detail=f"Tema nuevo no válido: {clave}")
    num = int(n)
    titulo = (titulo or "").strip()[:200] or f"{TITULO[grupo]} {num}"
    # Detrás del último tema de su grupo con número menor (Tema 3 antes que Tema 4), o al final
    temas, _ = temas_con_clave(conn, asig_id)
    antes = [t for t in temas if t["clave"] and t["clave"][0] == grupo and t["clave"][1] < num]
    despues = [t for t in temas if t["clave"] and t["clave"][0] == grupo and t["clave"][1] > num]
    if antes:
        orden = max(t["orden"] for t in antes) + 0.5
    elif despues:
        orden = min(t["orden"] for t in despues) - 0.5
    else:
        orden = max([t["orden"] for t in temas] or [0]) + 1
    cur = conn.execute(
        "INSERT INTO temas (asignatura_id, titulo, tipo, grupo, orden, titulo_manual) VALUES (?, ?, 'manual', ?, ?, 1)",
        (asig_id, titulo, grupo, orden),
    )
    return cur.lastrowid


def aplicar(asig_id: int, data: OrganizarIn) -> dict:
    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
    carpeta = carpeta_de(root, asig) if asig["carpeta"] else None
    res = {"temas_creados": 0, "movidos": 0, "quitados": 0}
    docs: list[tuple[Cambio, dict | None]] = []
    for c in data.cambios:  # todo se comprueba en el disco antes de escribir nada
        if c.destino == "quitar":
            docs.append((c, None))
            continue
        if c.ruta.startswith("/"):
            path = safe_path(root, c.ruta[1:])
        elif carpeta is not None:
            path = safe_path(carpeta, c.ruta)
        else:
            raise HTTPException(status_code=409, detail="La asignatura no tiene carpeta")
        docs.append((c, _fila_doc(path, c.ruta)))
    with get_db() as conn:
        creados: dict[str, int] = {}
        for c, doc in docs:
            if doc is None:
                n = conn.execute(
                    "UPDATE uni_archivos SET oculto=1 WHERE asignatura_id=? AND ruta=? AND oculto=0", (asig_id, c.ruta)
                ).rowcount
                res["quitados"] += n
                continue
            if c.destino.startswith("tema:"):
                try:
                    tema_id = _tema_destino(conn, asig_id, int(c.destino[5:]))
                except ValueError as e:
                    raise HTTPException(status_code=422, detail="Tema no válido") from e
            elif c.destino.startswith("nuevo:"):
                clave = c.destino[6:]
                if clave not in creados:
                    creados[clave] = _crear_tema_por_clave(conn, asig_id, clave, data.titulos.get(clave))
                    res["temas_creados"] += 1
                tema_id = creados[clave]
            else:
                raise HTTPException(status_code=422, detail=f"Destino no válido: {c.destino}")
            if asignar(conn, asig_id, doc, tema_id) != "igual":
                res["movidos"] += 1
    log.info("Organizar %s: %s", asig["codigo"], res)
    return res


# ─────────────────────────────────────────────
# Explorador de la raíz y vincular a mano
# ─────────────────────────────────────────────


def explorar(ruta: str, asig_id: int | None) -> dict:
    root = root_ready()
    rel = clean_rel(ruta)
    base = safe_path(root, rel) if rel else Path(os.path.realpath(root))
    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"No existe la carpeta «{rel}» dentro de la raíz")
    vinculados: dict[str, dict] = {}
    inicio = ""
    if asig_id:
        with get_db() as conn:
            asig = get_asig(conn, asig_id)
            inicio = asig["carpeta"] or ""
            titulos = {
                r["id"]: r["titulo"]
                for r in conn.execute("SELECT id, titulo FROM temas WHERE asignatura_id=?", (asig_id,))
            }
            for r in conn.execute(
                "SELECT ruta, tema_id FROM uni_archivos WHERE asignatura_id=? AND oculto=0 AND tema_id IS NOT NULL",
                (asig_id,),
            ):
                if r["ruta"].startswith("/") or asig["carpeta"]:
                    vinculados[_ruta_en_raiz(asig, r["ruta"])] = {
                        "tema_id": r["tema_id"],
                        "titulo": titulos.get(r["tema_id"]),
                    }
    carpetas, archivos = [], []
    try:
        with os.scandir(base) as it:
            entries = sorted(it, key=lambda e: _natural(e.name))
    except OSError as e:
        raise HTTPException(status_code=409, detail=f"No se puede leer la carpeta ({e.strerror})") from e
    for e in entries[:MAX_ENTRADAS]:
        if not _visible(e):
            continue
        r = f"{rel}/{e.name}" if rel else e.name
        if e.is_dir(follow_symlinks=False):
            carpetas.append({"nombre": e.name, "ruta": r})
        elif e.is_file(follow_symlinks=False) and _doc_ok(e.name):
            ext = os.path.splitext(e.name)[1].lower().lstrip(".")
            archivos.append(
                {
                    "nombre": e.name,
                    "ruta": r,
                    "ext": ext,
                    "bytes": e.stat(follow_symlinks=False).st_size,
                    "visor": ext in VISOR_EXT,
                    "vinculado": vinculados.get(r),
                }
            )
    partes = rel.split("/") if rel else []
    return {
        "ruta": rel,
        "raiz": str(root),
        "inicio": inicio,
        "migas": [{"nombre": p, "ruta": "/".join(partes[: i + 1])} for i, p in enumerate(partes)],
        "carpetas": carpetas,
        "archivos": archivos,
        "truncado": len(entries) > MAX_ENTRADAS,
    }


class VincularIn(BaseModel):
    rutas: list[str] = Field(default_factory=list, max_length=500)  # relativas a la raíz
    carpetas: list[str] = Field(default_factory=list, max_length=50)  # todo lo de dentro (hasta MAX_PROF niveles)


def vincular(tema_id: int, data: VincularIn) -> dict:
    if not data.rutas and not data.carpetas:
        raise HTTPException(status_code=422, detail="Elige al menos un documento o una carpeta")
    root = root_ready()
    with get_db() as conn:
        t = get_tema(conn, tema_id)
        asig = get_asig(conn, t["asignatura_id"])
        destino = t["fusionado_en"] or t["id"]
    docs = []
    for rel in data.rutas:
        rel = clean_rel(rel)
        docs.append(_fila_doc(safe_path(root, rel), _ruta_guardada(root, asig, rel)))
    for rel in data.carpetas:
        rel = clean_rel(rel)
        base = safe_path(root, rel)
        if not base.is_dir():
            raise HTTPException(status_code=404, detail=f"No existe la carpeta «{rel}»")
        for d in docs_carpeta(base, set()):
            r = f"{rel}/{d['ruta']}" if rel else d["ruta"]
            docs.append({**d, "ruta": _ruta_guardada(root, asig, r)})
    res = {"nuevos": 0, "movidos": 0, "iguales": 0}
    with get_db() as conn:
        for d in {d["ruta"]: d for d in docs}.values():
            r = asignar(conn, asig["id"], d, destino)
            res[{"nuevo": "nuevos", "movido": "movidos", "igual": "iguales"}[r]] += 1
    log.info("Vinculados a %s/%s: %s", asig["codigo"], t["titulo"], res)
    return res


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────


@router.get("/explorar")
def api_explorar(ruta: str = Query(default="", max_length=1000), asignatura: int | None = None):
    return explorar(ruta, asignatura)


@router.get("/asignaturas/{asig_id}/organizar")
def api_plan(asig_id: int):
    return plan(asig_id)


@router.post("/asignaturas/{asig_id}/organizar")
def api_aplicar(asig_id: int, data: OrganizarIn):
    return aplicar(asig_id, data)


@router.post("/temas/{tema_id}/vincular")
def api_vincular(tema_id: int, data: VincularIn):
    return vincular(tema_id, data)
