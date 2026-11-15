"""
Universidad: asignaturas, temas construidos desde la carpeta de cada asignatura, entregas y
exámenes, horario de clases y la propuesta para pasar a Universidad lo que ya había.

Nada vive aparte (ver app/contextos.py):
  - las entregas son tareas (`inbox.uni_tipo='entrega'`) y los exámenes, eventos (`kind='examen'`)
    o tareas `uni_tipo='examen'`, todos con `asignatura_id`;
  - las clases son eventos que se repiten (`kind='clase'`, `repeat`, `repeat_until`), así salen en
    el calendario, Hoy, Rutinas y la Waybar sin copiar nada;
  - los apuntes de un tema son una nota normal (frontmatter `asignatura`, `tema`).

Carpetas: SOLO LECTURA. Se listan con os.scandir y nunca se escribe, mueve ni borra nada en ellas.
La raíz es un ajuste (app/contextos.py: `uni_raiz`); cada asignatura guarda su carpeta relativa
a la raíz y cada tema, su ruta relativa a la de la asignatura. `safe_path` valida toda ruta:
sin «..», sin rutas absolutas y con realpath dentro de la raíz (un enlace que escape se rechaza).

Regla de temas (según la estructura real, ver AUDITORIA.md): subcarpeta directa = tema; documento
suelto (pdf, docx, pptx, md…) = tema de un archivo; código, binarios y comprimidos sueltos no son temas.
«Sincronizar con carpeta» añade lo nuevo, marca lo que ya no está (`falta_desde`) y no borra nada;
el orden, el estado, el nombre puesto a mano, la nota y los temas añadidos a mano se conservan.
Si la raíz o la carpeta no están disponibles (disco sin montar) no se marca nada como desaparecido.
"""

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import contextos
from app.database import get_db
from app.notes_core import note_path, note_slug
from core import undo
from core.db import update_fields
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("universidad")
router = APIRouter(prefix="/api/uni")
open_router = APIRouter(prefix="/api/abrir")

COLORES = tuple(f"cat-{i}" for i in range(10))
ESTADOS = ("sin-ver", "estudiando", "repasado")
GRUPOS = ("teoria", "practicas", "otros")
DOC_EXT = {".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".odp", ".md", ".txt", ".ipynb", ".epub", ".rtf"}
IGNORAR = {
    "build",
    "bin",
    "obj",
    "out",
    "dist",
    "target",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "cmake-build-debug",
    "cmake-build-release",
    "$recycle.bin",
    "system volume information",
    "logs",
}
PRACTICA_RE = re.compile(r"(pr[aá]ctica|^pr[\s_\-]?\d|entrega|^lab|laboratorio|proyecto)", re.I)
TEORIA_RE = re.compile(
    r"(^tema|lesson|teor[ií]a|chulet|apuntes|transparencias|diapositivas|^[a-z]\s|^\d+[\s._\-])", re.I
)
MAX_RECURSOS = 300


# ─────────────────────────────────────────────
# Rutas seguras (solo lectura)
# ─────────────────────────────────────────────


def clean_rel(rel: str | None) -> str:
    """Ruta relativa limpia o 422: sin absolutas, sin «..», sin «~» ni caracteres de control."""
    rel = (rel or "").strip().replace("\\", "/")
    if rel.startswith("/") or os.path.isabs(rel) or re.match(r"^[a-zA-Z]:", rel):
        raise HTTPException(status_code=422, detail="La ruta tiene que ser relativa a la carpeta raíz")
    rel = rel.strip("/")
    if not rel:
        return ""
    if rel.startswith("~") or "\x00" in rel or any(ord(c) < 32 for c in rel):
        raise HTTPException(status_code=422, detail="Ruta no válida")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or os.path.isabs(rel):
        raise HTTPException(status_code=422, detail="La ruta tiene que estar dentro de la carpeta raíz")
    return "/".join(parts)


def safe_path(root: str | Path, *rels: str) -> Path:
    """root + rels con realpath dentro de root (los enlaces que salen de la raíz se rechazan)."""
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, *[clean_rel(r) for r in rels if r]))
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(status_code=422, detail="La ruta sale de la carpeta raíz")
    return Path(full)


def uni_root() -> Path | None:
    raw = contextos.ajuste("uni_raiz")
    return Path(raw) if raw else None


def root_ready() -> Path:
    root = uni_root()
    if root is None:
        raise HTTPException(status_code=409, detail="Falta la carpeta raíz de la universidad (Universidad → Ajustes)")
    if not root.is_dir():
        raise HTTPException(
            status_code=409,
            detail="La carpeta raíz no está disponible ahora (¿disco sin montar?): no se ha tocado nada",
        )
    return root


def grupo_de(nombre: str) -> str:
    base = os.path.splitext(nombre)[0]
    if PRACTICA_RE.search(base):
        return "practicas"
    if TEORIA_RE.search(base):
        return "teoria"
    return "otros"


def bonito(nombre: str, es_archivo: bool) -> str:
    base = os.path.splitext(nombre)[0] if es_archivo else nombre
    base = re.sub(r"[_]+", " ", base)
    base = re.sub(r"(?<=[a-záéíóú])(?=[A-ZÁÉÍÓÚ])", " ", base)  # GestionProyectos → Gestion Proyectos
    base = re.sub(r"\s+", " ", base).strip(" -")
    return base[:1].upper() + base[1:] if base else nombre


def _visible(entry: os.DirEntry) -> bool:
    n = entry.name
    return not n.startswith((".", "~$")) and n.lower() not in IGNORAR and not entry.is_symlink()


def escanear(carpeta: Path) -> list[dict]:
    """Temas de una carpeta de asignatura (solo lectura)."""
    out = []
    with os.scandir(carpeta) as it:
        for e in it:
            if not _visible(e):
                continue
            if e.is_dir(follow_symlinks=False):
                out.append(
                    {
                        "ruta": e.name,
                        "nombre": e.name,
                        "tipo": "carpeta",
                        "grupo": grupo_de(e.name),
                        "titulo": bonito(e.name, False),
                    }
                )
            elif e.is_file(follow_symlinks=False) and os.path.splitext(e.name)[1].lower() in DOC_EXT:
                out.append(
                    {
                        "ruta": e.name,
                        "nombre": e.name,
                        "tipo": "archivo",
                        "grupo": grupo_de(e.name),
                        "titulo": bonito(e.name, True),
                    }
                )
    return sorted(out, key=lambda t: (GRUPOS.index(t["grupo"]), _natural(t["nombre"])))


def _natural(s: str):
    return [int(x) if x.isdigit() else contextos.fold(x) for x in re.split(r"(\d+)", s)]


def recursos(carpeta: Path, solo_sueltos: bool = False) -> list[dict]:
    """Archivos de una carpeta (un nivel; las subcarpetas se cuentan). solo_sueltos: los que no son tema."""
    out = []
    try:
        with os.scandir(carpeta) as it:
            for e in it:
                if not _visible(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if not solo_sueltos:
                        out.append({"nombre": e.name, "carpeta": True})
                elif e.is_file(follow_symlinks=False):
                    ext = os.path.splitext(e.name)[1].lower()
                    if solo_sueltos and ext in DOC_EXT:
                        continue
                    out.append(
                        {
                            "nombre": e.name,
                            "carpeta": False,
                            "bytes": e.stat(follow_symlinks=False).st_size,
                            "ext": ext.lstrip("."),
                        }
                    )
                if len(out) >= MAX_RECURSOS:
                    break
    except OSError:
        return []
    return sorted(out, key=lambda r: (not r["carpeta"], _natural(r["nombre"])))


# ─────────────────────────────────────────────
# Asignaturas
# ─────────────────────────────────────────────


class Enlace(BaseModel):
    titulo: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=1000)

    @field_validator("url")
    @classmethod
    def v_url(cls, v):
        if not re.match(r"^https?://", v.strip(), re.I):
            raise ValueError("El enlace empieza por http:// o https://")
        return v.strip()


def _clean_codigo(v):
    if v is None:
        return v
    v = re.sub(r"\s+", "", v.strip())
    if not re.fullmatch(r"[\wÁÉÍÓÚÑáéíóúñ.\-]{1,20}", v):
        raise ValueError("El código es una sigla corta sin espacios (GABD, IG…)")
    return v


def _clean_color(v):
    if v in (None, ""):
        return v
    if v not in COLORES:
        raise ValueError("Color no válido")
    return v


class AsignaturaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    codigo: str = Field(min_length=1, max_length=20)
    color: str | None = Field(default=None, max_length=10)
    profesor: str | None = Field(default=None, max_length=200)
    aula: str | None = Field(default=None, max_length=120)
    semestre: str | None = Field(default=None, max_length=40)
    alias: list[str] = Field(default_factory=list, max_length=20)
    carpeta: str | None = Field(default=None, max_length=1000)
    enlaces: list[Enlace] = Field(default_factory=list, max_length=30)

    @field_validator("codigo")
    @classmethod
    def v_codigo(cls, v):
        return _clean_codigo(v)

    @field_validator("color")
    @classmethod
    def v_color(cls, v):
        return _clean_color(v)


class AsignaturaPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    codigo: str | None = Field(default=None, min_length=1, max_length=20)
    color: str | None = Field(default=None, max_length=10)
    profesor: str | None = Field(default=None, max_length=200)
    aula: str | None = Field(default=None, max_length=120)
    semestre: str | None = Field(default=None, max_length=40)
    alias: list[str] | None = Field(default=None, max_length=20)
    carpeta: str | None = Field(default=None, max_length=1000)
    enlaces: list[Enlace] | None = Field(default=None, max_length=30)
    archivada: bool | None = None
    before_id: int | None = None  # reordenar: antes de esta (0 = al final)

    @field_validator("codigo")
    @classmethod
    def v_codigo(cls, v):
        return _clean_codigo(v)

    @field_validator("color")
    @classmethod
    def v_color(cls, v):
        return _clean_color(v)


def _jl(v) -> list:
    try:
        return json.loads(v) if v else []
    except ValueError:
        return []


def _asig_out(r) -> dict:
    return {
        "id": r["id"],
        "nombre": r["nombre"],
        "codigo": r["codigo"],
        "color": r["color"] or "cat-0",
        "profesor": r["profesor"],
        "aula": r["aula"],
        "semestre": r["semestre"],
        "alias": _jl(r["alias"]),
        "carpeta": r["carpeta"],
        "enlaces": _jl(r["enlaces"]),
        "orden": r["orden"],
        "archivada": bool(r["archivada"]),
        "sync_at": r["sync_at"],
    }


def get_asig(conn, asig_id: int):
    row = conn.execute("SELECT * FROM asignaturas WHERE id=?", (asig_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada")
    return row


def _check_unique(conn, codigo: str, alias: list[str], skip_id: int | None = None) -> None:
    """Código y alias no pueden pisar los de otra asignatura (la captura con @ sería ambigua)."""
    mine = {contextos.fold(x).replace(" ", "") for x in [codigo, *alias] if x}
    for r in conn.execute("SELECT id, codigo, alias FROM asignaturas"):
        if r["id"] == skip_id:
            continue
        theirs = {contextos.fold(x).replace(" ", "") for x in [r["codigo"], *_jl(r["alias"])] if x}
        clash = mine & theirs
        if clash:
            raise HTTPException(status_code=409, detail=f"«@{sorted(clash)[0]}» ya es de {r['codigo']}")


def create_asig(data: AsignaturaIn) -> int:
    alias = [a.strip() for a in data.alias if a.strip()]
    carpeta = clean_rel(data.carpeta) if data.carpeta else None
    with get_db() as conn:
        _check_unique(conn, data.codigo, alias)
        n = conn.execute("SELECT COUNT(*), COALESCE(MAX(orden), 0) FROM asignaturas").fetchone()
        color = data.color or COLORES[n[0] % len(COLORES)]
        cur = conn.execute(
            "INSERT INTO asignaturas (nombre, codigo, color, profesor, aula, semestre, alias, carpeta, enlaces, orden) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.nombre.strip(),
                data.codigo,
                color,
                data.profesor,
                data.aula,
                data.semestre,
                json.dumps(alias, ensure_ascii=False),
                carpeta,
                json.dumps([e.model_dump() for e in data.enlaces], ensure_ascii=False),
                n[1] + 1,
            ),
        )
        return cur.lastrowid


def update_asig(asig_id: int, data: AsignaturaPatch) -> None:
    with get_db() as conn:
        row = get_asig(conn, asig_id)
        if data.codigo is not None or data.alias is not None:
            _check_unique(
                conn, data.codigo or row["codigo"], data.alias if data.alias is not None else _jl(row["alias"]), asig_id
            )
        campos = ("nombre", "codigo", "color", "profesor", "aula", "semestre")
        dados = {f: getattr(data, f) for f in campos if getattr(data, f) is not None}
        update_fields(
            conn,
            "asignaturas",
            asig_id,
            {f: (v.strip() if isinstance(v, str) else v) or None for f, v in dados.items()},
            campos,
        )
        if data.alias is not None:
            conn.execute(
                "UPDATE asignaturas SET alias=? WHERE id=?",
                (json.dumps([a.strip() for a in data.alias if a.strip()], ensure_ascii=False), asig_id),
            )
        if data.carpeta is not None:
            conn.execute("UPDATE asignaturas SET carpeta=? WHERE id=?", (clean_rel(data.carpeta) or None, asig_id))
        if data.enlaces is not None:
            conn.execute(
                "UPDATE asignaturas SET enlaces=? WHERE id=?",
                (json.dumps([e.model_dump() for e in data.enlaces], ensure_ascii=False), asig_id),
            )
        if data.archivada is not None:
            conn.execute("UPDATE asignaturas SET archivada=? WHERE id=?", (int(data.archivada), asig_id))
        if data.before_id is not None:
            ids = [
                r["id"] for r in conn.execute("SELECT id FROM asignaturas WHERE id != ? ORDER BY orden, id", (asig_id,))
            ]
            pos = ids.index(data.before_id) if data.before_id in ids else len(ids)
            ids.insert(pos, asig_id)
            for i, x in enumerate(ids):
                conn.execute("UPDATE asignaturas SET orden=? WHERE id=?", (i + 1, x))
        if data.codigo is not None and data.codigo != row["codigo"]:  # las notas dicen el código en su frontmatter
            _renombrar_en_notas(row["codigo"], data.codigo)


def _renombrar_en_notas(viejo: str, nuevo: str) -> None:
    from app.indexer import sync_notes_to_db
    from core import config

    for name in os.listdir(config.NOTES_DIR):
        if not name.endswith(".md"):
            continue
        path = os.path.join(config.NOTES_DIR, name)
        try:
            with open(path, encoding="utf-8") as f:
                post = frontmatter.load(f)
        except (OSError, ValueError):
            continue
        if str(post.get("asignatura") or "") == viejo:
            post["asignatura"] = nuevo
            atomic_write(path, frontmatter.dumps(post) + "\n")
    sync_notes_to_db(force=True)


def delete_asig(asig_id: int) -> str:
    """Solo si no tiene nada: lo que ya cuelga de ella se archiva, no se borra."""
    with get_db() as conn:
        get_asig(conn, asig_id)
        usos = sum(
            conn.execute(q, (asig_id,)).fetchone()[0]
            for q in (
                "SELECT COUNT(*) FROM inbox WHERE asignatura_id=?",
                "SELECT COUNT(*) FROM events WHERE asignatura_id=?",
                "SELECT COUNT(*) FROM notes WHERE asignatura_id=?",
                "SELECT COUNT(*) FROM temas WHERE asignatura_id=? AND (note_id IS NOT NULL OR estado != 'sin-ver' OR tipo='manual')",
            )
        )
        if usos:
            raise HTTPException(
                status_code=409, detail="Tiene tareas, eventos, notas o temas trabajados: archívala en vez de borrarla"
            )
        a = undo.select(conn, "asignaturas", "id=?", (asig_id,))
        token = undo.save_rows(
            conn,
            "rows.asignatura",
            [("asignaturas", a), ("temas", undo.select(conn, "temas", "asignatura_id=?", (asig_id,)))],
            title=a[0]["nombre"],
        )
        conn.execute("DELETE FROM temas WHERE asignatura_id=?", (asig_id,))
        conn.execute("DELETE FROM asignaturas WHERE id=?", (asig_id,))
    return token


# ─────────────────────────────────────────────
# Temas
# ─────────────────────────────────────────────


class TemaIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    grupo: str = Field(default="teoria", max_length=12)


class TemaPatch(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    estado: str | None = Field(default=None, max_length=12)
    grupo: str | None = Field(default=None, max_length=12)
    note_id: str | None = Field(default=None, max_length=200)  # "" la desvincula
    before_id: int | None = None  # 0 = al final del grupo

    @field_validator("estado")
    @classmethod
    def v_estado(cls, v):
        if v is not None and v not in ESTADOS:
            raise ValueError("Estado: sin-ver, estudiando o repasado")
        return v

    @field_validator("grupo")
    @classmethod
    def v_grupo(cls, v):
        if v is not None and v not in GRUPOS:
            raise ValueError("Grupo: teoria, practicas u otros")
        return v


def _tema_out(r, notas: dict | None = None) -> dict:
    nota = (notas or {}).get(r["note_id"]) if r["note_id"] else None
    return {
        "id": r["id"],
        "asignatura_id": r["asignatura_id"],
        "titulo": r["titulo"],
        "nombre": r["nombre_carpeta"],
        "ruta": r["ruta"],
        "tipo": r["tipo"],
        "grupo": r["grupo"],
        "estado": r["estado"],
        "note_id": r["note_id"],
        "note_title": nota,
        "orden": r["orden"],
        "titulo_manual": bool(r["titulo_manual"]),
        "falta": r["falta_desde"] is not None,
    }


def get_tema(conn, tema_id: int):
    row = conn.execute("SELECT * FROM temas WHERE id=?", (tema_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    return row


def _reorder(conn, tema_id: int, asig_id: int, before_id: int | None) -> None:
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM temas WHERE asignatura_id=? AND id != ? ORDER BY orden, id", (asig_id, tema_id)
        )
    ]
    pos = ids.index(before_id) if before_id in ids else len(ids)
    ids.insert(pos, tema_id)
    for i, x in enumerate(ids):
        conn.execute("UPDATE temas SET orden=? WHERE id=?", (i + 1, x))


def update_tema(tema_id: int, data: TemaPatch) -> None:
    with get_db() as conn:
        row = get_tema(conn, tema_id)
        if data.titulo is not None:
            conn.execute("UPDATE temas SET titulo=?, titulo_manual=1 WHERE id=?", (data.titulo.strip(), tema_id))
        campos = ("estado", "grupo")
        update_fields(
            conn, "temas", tema_id, {f: getattr(data, f) for f in campos if getattr(data, f) is not None}, campos
        )
        if data.note_id is not None:
            if data.note_id and not os.path.exists(note_path(data.note_id)):
                raise HTTPException(status_code=422, detail="Esa nota no existe")
            conn.execute("UPDATE temas SET note_id=? WHERE id=?", (data.note_id or None, tema_id))
        if data.before_id is not None:
            _reorder(conn, tema_id, row["asignatura_id"], data.before_id)


def sync_asig(asig_id: int) -> dict:
    """Sincronizar con carpeta: añade, marca lo que falta y nunca borra ni escribe en la carpeta."""
    root = root_ready()
    with get_db() as conn:
        asig = get_asig(conn, asig_id)
    if not asig["carpeta"]:
        raise HTTPException(status_code=409, detail="Elige antes la carpeta de la asignatura")
    carpeta = safe_path(root, asig["carpeta"])
    if not carpeta.is_dir():
        raise HTTPException(
            status_code=409, detail=f"No encuentro «{asig['carpeta']}» dentro de la raíz: no se ha tocado nada"
        )
    try:
        vistos = escanear(carpeta)
    except OSError as e:
        raise HTTPException(status_code=409, detail=f"No se puede leer la carpeta ({e.strerror}): no se ha tocado nada")
    now = time.time()
    res = {"nuevos": 0, "vuelven": 0, "faltan": 0, "iguales": 0}
    with get_db() as conn:
        actuales = {
            r["ruta"]: r
            for r in conn.execute("SELECT * FROM temas WHERE asignatura_id=? AND ruta IS NOT NULL", (asig_id,))
        }
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) FROM temas WHERE asignatura_id=?", (asig_id,)).fetchone()[
            0
        ]
        for t in vistos:
            r = actuales.pop(t["ruta"], None)
            if r is None:
                orden += 1
                conn.execute(
                    "INSERT INTO temas (asignatura_id, titulo, nombre_carpeta, ruta, tipo, grupo, orden) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (asig_id, t["titulo"], t["nombre"], t["ruta"], t["tipo"], t["grupo"], orden),
                )
                res["nuevos"] += 1
                continue
            if r["falta_desde"] is not None:
                res["vuelven"] += 1
            else:
                res["iguales"] += 1
            # lo puesto a mano (título, grupo, estado, orden, nota) no se toca
            conn.execute(
                "UPDATE temas SET falta_desde=NULL, nombre_carpeta=?, titulo=CASE WHEN titulo_manual THEN titulo ELSE ? END WHERE id=?",
                (t["nombre"], t["titulo"], r["id"]),
            )
        for r in actuales.values():  # ya no están en la carpeta: se marcan, no se borran
            if r["tipo"] != "manual" and r["falta_desde"] is None:
                conn.execute("UPDATE temas SET falta_desde=? WHERE id=?", (now, r["id"]))
                res["faltan"] += 1
        conn.execute("UPDATE asignaturas SET sync_at=? WHERE id=?", (now, asig_id))
    log.info("Sincronía de temas de %s: %s", asig["codigo"], res)
    return res


# ─────────────────────────────────────────────
# Notas de apuntes y de clase (plantillas)
# ─────────────────────────────────────────────


def _unique_note_id(base: str) -> str:
    candidate, n = base, 2
    while os.path.exists(note_path(candidate)):
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _new_note(title: str, body: str, codigo: str, extra: dict | None = None) -> str:
    from app.indexer import sync_notes_to_db

    note_id = _unique_note_id(note_slug(title[:180]))
    post = frontmatter.Post(body)
    post["title"], post["category"], post["category_id"] = title, f"Universidad - {codigo}", None
    post["status"], post["tags"], post["encrypted"] = "por-escribir", [], False
    post["contexto"], post["asignatura"] = "universidad", codigo
    for k, v in (extra or {}).items():
        post[k] = v
    atomic_write(note_path(note_id), frontmatter.dumps(post) + "\n")
    sync_notes_to_db()
    return note_id


def nota_de_tema(tema_id: int) -> dict:
    with get_db() as conn:
        t = get_tema(conn, tema_id)
        a = get_asig(conn, t["asignatura_id"])
    if t["note_id"] and os.path.exists(note_path(t["note_id"])):
        return {"note_id": t["note_id"], "creada": False}
    title = f"{a['codigo']} · {t['titulo']}"
    body = (
        f"# {t['titulo']}\n\n"
        "## Ideas clave\n\n- \n\n"
        "## Explicación con mis palabras\n\n\n"
        "## Dudas\n\n- \n\n"
        "## Para el examen\n\n- \n\n"
        "## Ejercicios y prácticas\n\n- [ ] \n\n"
        "_Al editar, marca un bloque como «Duda para el profe», «Entra en examen» o «Importante» (menú de marcas)._\n"
    )
    note_id = _new_note(title, body, a["codigo"], {"tema": t["titulo"]})
    with get_db() as conn:
        conn.execute("UPDATE temas SET note_id=? WHERE id=?", (note_id, tema_id))
    return {"note_id": note_id, "creada": True}


class ClaseNotaIn(BaseModel):
    fecha: str | None = Field(default=None, max_length=10)
    tema_id: int | None = None


def nota_de_clase(asig_id: int, data: ClaseNotaIn) -> dict:
    d = date.fromisoformat(data.fecha) if data.fecha else date.today()
    with get_db() as conn:
        a = get_asig(conn, asig_id)
        t = get_tema(conn, data.tema_id) if data.tema_id else None
    if t is not None and t["asignatura_id"] != asig_id:
        raise HTTPException(status_code=422, detail="Ese tema es de otra asignatura")
    title = f"{a['codigo']} · Clase {d.strftime('%d/%m/%Y')}"
    tema = t["titulo"] if t is not None else ""
    body = (
        f"# Clase del {d.strftime('%d/%m/%Y')}\n\n"
        f"**Fecha:** {d.isoformat()}  \n**Tema:** {tema}\n\n"
        "## Apuntes\n\n\n"
        "## Dudas\n\n- \n\n"
        "## Importante\n\n- \n\n"
        "## Pendiente\n\n- [ ] \n\n"
        "_Al editar, marca un bloque como «Duda para el profe», «Entra en examen» o «Importante» (menú de marcas)._\n"
    )
    return {
        "note_id": _new_note(title, body, a["codigo"], {"clase": d.isoformat(), **({"tema": tema} if tema else {})}),
        "creada": True,
    }


# ─────────────────────────────────────────────
# Entregas, exámenes, clases y resumen
# ─────────────────────────────────────────────


def _entregas(conn, conts: dict, desde: date | None = None, asig_id: int | None = None) -> list[dict]:
    """Entregas y exámenes: tareas con uni_tipo y eventos examen/entrega de una asignatura. Más próximas primero."""
    from app.items import clean_text

    out = []
    q = "SELECT * FROM inbox WHERE asignatura_id IS NOT NULL AND parent_id IS NULL AND (uni_tipo IS NOT NULL OR due_date IS NOT NULL)"
    args: list = []
    if asig_id:
        q += " AND asignatura_id=?"
        args.append(asig_id)
    for r in conn.execute(q, args):
        out.append(
            {
                "origen": "tarea",
                "id": r["id"],
                "titulo": clean_text(r["content"]).split("\n")[0],
                "tipo": r["uni_tipo"] or "tarea",
                "fecha": r["due_date"],
                "hora": r["due_time"],
                "hecho": r["status"] == "processed",
                "peso": r["peso"],
                "nota": r["nota"],
                "temas": _jl(r["temas"]),
                **contextos.label(r, conts),
            }
        )
    q = "SELECT * FROM events WHERE asignatura_id IS NOT NULL AND kind IN ('examen', 'entrega')"
    args = []
    if asig_id:
        q += " AND asignatura_id=?"
        args.append(asig_id)
    for r in conn.execute(q, args):
        out.append(
            {
                "origen": "evento",
                "id": r["id"],
                "titulo": r["title"],
                "tipo": r["kind"],
                "fecha": r["start"][:10],
                "hora": r["start"][11:16] or None,
                "hecho": r["start"][:10] < date.today().isoformat(),
                "peso": r["peso"],
                "nota": r["nota"],
                "temas": _jl(r["temas"]),
                **contextos.label(r, conts),
            }
        )
    if desde:
        out = [e for e in out if e["fecha"] and e["fecha"] >= desde.isoformat()]
    return sorted(out, key=lambda e: (e["fecha"] or "9999", e["hora"] or ""))


def media(entregas: list[dict]) -> dict | None:
    """Media ponderada de lo que ya tiene nota (sobre 10) y el peso que falta por evaluar."""
    con_nota = [e for e in entregas if e["nota"] is not None and e["peso"]]
    if not con_nota:
        return None
    peso = sum(e["peso"] for e in con_nota)
    return {
        "media": round(sum(e["nota"] * e["peso"] for e in con_nota) / peso, 2),
        "peso_evaluado": round(peso, 1),
        "aporta": round(sum(e["nota"] * e["peso"] for e in con_nota) / 100, 2),
    }


def clases(conn, conts: dict) -> list[dict]:
    from app.calendar import event_out

    return [
        event_out(r, conts)
        for r in conn.execute(
            "SELECT * FROM events WHERE repeat IS NOT NULL AND (kind='clase' OR contexto='universidad') ORDER BY start"
        )
    ]


def resumen() -> dict:
    from app.calendar import entries

    hoy = date.today()
    with get_db() as conn:
        conts = contextos.containers(conn)
        prox = _entregas(conn, conts, desde=hoy)
        todas = _entregas(conn, conts)
    clases_hoy = [e for e in entries(hoy, hoy, "universidad") if e["kind"] == "event" and e.get("recurring")]
    for e in prox:
        e["dias"] = (date.fromisoformat(e["fecha"]) - hoy).days
    por_asig: dict = {}
    for e in todas:
        por_asig.setdefault(e["asignatura_id"], []).append(e)
    return {
        "hoy": hoy.isoformat(),
        "clases_hoy": sorted(clases_hoy, key=lambda e: e["start"]),
        "proximas": [e for e in prox if not e["hecho"]][:12],
        "medias": {k: media(v) for k, v in por_asig.items()},
    }


def vista() -> dict:
    """Todo lo de la página Universidad en una petición: asignaturas con temas, próxima entrega y tareas abiertas."""
    hoy = date.today().isoformat()
    with get_db() as conn:
        conts = contextos.containers(conn)
        asigs = [_asig_out(r) for r in conn.execute("SELECT * FROM asignaturas ORDER BY archivada, orden, nombre")]
        notas = {
            r["id"]: r["title"] for r in conn.execute("SELECT id, title FROM notes WHERE asignatura_id IS NOT NULL")
        }
        temas = [_tema_out(r, notas) for r in conn.execute("SELECT * FROM temas ORDER BY orden, id")]
        entregas = _entregas(conn, conts)
        abiertas = dict(
            conn.execute(
                "SELECT asignatura_id, COUNT(*) FROM inbox WHERE asignatura_id IS NOT NULL AND parent_id IS NULL "
                "AND status != 'processed' AND item_type != 'rutina' GROUP BY asignatura_id"
            ).fetchall()
        )
        tareas_tema: dict = {}
        for r in conn.execute("SELECT temas FROM inbox WHERE temas IS NOT NULL AND status != 'processed'"):
            for t in _jl(r["temas"]):
                tareas_tema[t] = tareas_tema.get(t, 0) + 1
        notas_clase = dict(
            conn.execute(
                "SELECT asignatura_id, COUNT(*) FROM notes WHERE asignatura_id IS NOT NULL GROUP BY asignatura_id"
            ).fetchall()
        )
    for t in temas:
        t["tareas"] = tareas_tema.get(t["id"], 0)
    for a in asigs:
        mias = [e for e in entregas if e["asignatura_id"] == a["id"]]
        a["proxima"] = next((e for e in mias if not e["hecho"] and e["fecha"] and e["fecha"] >= hoy), None)
        a["tareas_abiertas"] = abiertas.get(a["id"], 0)
        a["notas"] = notas_clase.get(a["id"], 0)
        a["media"] = media(mias)
    root = uni_root()
    # Ruta absoluta en este equipo (para «Copiar ruta», que copia en el mismo clic): sin tocar el disco
    por_id = {a["id"]: a for a in asigs}
    for a in asigs:
        a["ruta_abs"] = _abs(root, a["carpeta"])
    for t in temas:
        a = por_id.get(t["asignatura_id"])
        t["ruta_abs"] = (
            _abs(root, a["carpeta"], t["ruta"]) if a and a["carpeta"] and t["ruta"] and t["tipo"] != "manual" else None
        )
    return {
        "asignaturas": asigs,
        "temas": temas,
        "raiz": str(root) if root else "",
        "raiz_ok": bool(root and root.is_dir()),
        "prompt": contextos.ajuste("uni_prompt"),
    }


def _abs(root, *rels) -> str | None:
    if not root or not all(rels):
        return None
    try:
        return str(safe_path(root, *rels))
    except HTTPException:
        return None


# ─────────────────────────────────────────────
# Horario: clases como eventos que se repiten
# ─────────────────────────────────────────────


class ClaseIn(BaseModel):
    asignatura_id: int | None = None
    titulo: str | None = Field(default=None, max_length=200)
    dias: list[int] = Field(min_length=1, max_length=7)
    inicio: str = Field(min_length=5, max_length=5)
    fin: str = Field(min_length=5, max_length=5)
    aula: str | None = Field(default=None, max_length=120)
    desde: str | None = Field(default=None, max_length=10)  # primer día del cuatrimestre (hoy si falta)
    hasta: str | None = Field(default=None, max_length=10)  # último día (sin fin si falta)

    @field_validator("inicio", "fin")
    @classmethod
    def v_hora(cls, v):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("La hora va como HH:MM")
        return v

    @field_validator("dias")
    @classmethod
    def v_dias(cls, v):
        d = sorted({x for x in v if 0 <= x <= 6})
        if not d:
            raise ValueError("Elige al menos un día")
        return d


def crear_clase(data: ClaseIn) -> int:
    from app.calendar import EventIn, create_event

    if data.fin <= data.inicio:
        raise HTTPException(status_code=422, detail="La clase acaba después de empezar")
    desde = date.fromisoformat(data.desde) if data.desde else date.today()
    while desde.weekday() not in data.dias:  # el evento empieza el primer día que toca
        desde += timedelta(days=1)
    titulo = (data.titulo or "").strip()
    with get_db() as conn:
        a = get_asig(conn, data.asignatura_id) if data.asignatura_id else None
    if not titulo:
        titulo = f"{a['codigo']} · Clase" if a else "Clases"
    return create_event(
        EventIn(
            title=titulo,
            start=f"{desde.isoformat()}T{data.inicio}",
            end=f"{desde.isoformat()}T{data.fin}",
            kind="clase",
            location=data.aula or (a["aula"] if a else None),
            contexto="universidad",
            asignatura_id=data.asignatura_id or None,
            repeat={"freq": "weekly", "days": data.dias} if len(data.dias) < 7 else {"freq": "daily"},
            repeat_until=data.hasta,
        )
    )


def clase_desde_rutina(item_id: int) -> dict:
    """La rutina (o el paso de una rutina) que hacía de horario pasa a ser una clase del calendario.
    El paso va a la papelera (se puede deshacer); su hora, duración y días se conservan en el evento."""
    from app import routines
    from app.items import clean_text, remove

    with get_db() as conn:
        r = conn.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
        if not r or r["item_type"] != "rutina":
            raise HTTPException(status_code=404, detail="No es una rutina")
        if not r["due_time"]:
            raise HTTPException(status_code=422, detail="Esa rutina no tiene hora: no es un horario")
        parent = (
            conn.execute("SELECT * FROM inbox WHERE id=?", (r["parent_id"],)).fetchone() if r["parent_id"] else None
        )
        if conn.execute("SELECT 1 FROM inbox WHERE parent_id=?", (item_id,)).fetchone():
            raise HTTPException(status_code=422, detail="Tiene pasos: conviértelos uno a uno")
    own = routines.step_rule(r) if parent is not None else routines.parse(r["repeat"])
    rule = own or (routines.parse(parent["repeat"]) if parent is not None else {"freq": "daily"})
    dias = rule.get("days", list(range(7))) if rule.get("freq") == "weekly" else list(range(7))
    ini = datetime.strptime(r["due_time"], "%H:%M")
    fin = (ini + timedelta(minutes=r["duration_min"] or 60)).strftime("%H:%M")
    event_id = crear_clase(
        ClaseIn(
            titulo=clean_text(r["content"]).split("\n")[0],
            dias=dias,
            inicio=r["due_time"],
            fin=fin if fin > r["due_time"] else "23:59",
        )
    )
    token = remove([item_id])
    return {"event_id": event_id, "undo": token}


# ─────────────────────────────────────────────
# Propuesta: pasar a Universidad lo que ya hay (se confirma en bloque)
# ─────────────────────────────────────────────

SIGLA_RE = re.compile(r"^\s*([^·:\-]{1,40}?)\s*(?:·|:|\s-\s)")


def propuesta() -> dict:
    """Tareas y eventos «puntuales» cuya categoría o sigla del principio coincide con una asignatura."""
    from app.items import clean_text

    with get_db() as conn:
        idx = contextos.alias_index(conn)["@"]
        nombres = {
            contextos.fold(r["nombre"]): {"id": r["id"], "codigo": r["codigo"], "nombre": r["nombre"]}
            for r in conn.execute("SELECT id, codigo, nombre FROM asignaturas WHERE archivada=0")
        }

        def match(*textos):
            for t in textos:
                if not t:
                    continue
                k = contextos.fold(t)
                hit = idx.get(k.replace(" ", "")) or nombres.get(k)
                if hit:
                    return hit
                m = SIGLA_RE.match(t)
                if m:
                    k = contextos.fold(m.group(1)).split()[0] if m.group(1).strip() else ""
                    hit = idx.get(k.replace(" ", "")) or nombres.get(contextos.fold(m.group(1)))
                    if hit:
                        return hit
            return None

        items, eventos = [], []
        for r in conn.execute(
            "SELECT * FROM inbox WHERE parent_id IS NULL AND note_task IS NULL AND asignatura_id IS NULL "
            "AND contexto='puntual' AND item_type != 'rutina' ORDER BY due_date IS NULL, due_date"
        ):
            text = clean_text(r["content"]).split("\n")[0]
            hit = match(r["category"], text)
            if hit:
                cuerpo = SIGLA_RE.sub("", text, count=1)
                tipo = (
                    None
                    if re.match(r"\s*(confirmar|preguntar|revisar|mirar|comprobar)\b", cuerpo, re.I)
                    else "examen"
                    if re.search(r"\b(examen|parcial)\b", cuerpo, re.I)
                    else "entrega"
                    if re.search(r"pr[aá]ctica|entrega|trabajo", cuerpo, re.I)
                    else None
                )
                items.append(
                    {
                        "id": r["id"],
                        "titulo": text,
                        "categoria": r["category"],
                        "fecha": r["due_date"],
                        "hecho": r["status"] == "processed",
                        "asignatura": hit,
                        "uni_tipo": tipo,
                    }
                )
        for r in conn.execute("SELECT * FROM events WHERE asignatura_id IS NULL AND contexto='puntual' ORDER BY start"):
            hit = match(r["title"])
            if hit:
                eventos.append(
                    {
                        "id": r["id"],
                        "titulo": r["title"],
                        "fecha": r["start"][:10],
                        "tipo": r["kind"],
                        "asignatura": hit,
                    }
                )
    return {"items": items, "eventos": eventos}


class AplicarIn(BaseModel):
    items: list[dict] = Field(default_factory=list, max_length=2000)  # [{id, asignatura_id, uni_tipo?}]
    eventos: list[dict] = Field(default_factory=list, max_length=2000)  # [{id, asignatura_id}]


def aplicar_propuesta(data: AplicarIn) -> dict:
    """Aplica lo confirmado y guarda cómo estaba para deshacerlo (POST /propuesta/deshacer)."""
    previo = {"items": [], "eventos": []}
    with get_db() as conn:
        validas = {r["id"] for r in conn.execute("SELECT id FROM asignaturas")}
        for x in data.items:
            iid, aid = int(x.get("id", 0)), int(x.get("asignatura_id", 0))
            row = conn.execute(
                "SELECT id, contexto, asignatura_id, proyecto_id, uni_tipo, note_task, parent_id FROM inbox WHERE id=?",
                (iid,),
            ).fetchone()
            if not row or aid not in validas or row["note_task"] is not None or row["parent_id"] is not None:
                continue
            previo["items"].append(dict(row))
            tipo = x.get("uni_tipo") if x.get("uni_tipo") in ("entrega", "examen") else row["uni_tipo"]
            conn.execute(
                "UPDATE inbox SET contexto='universidad', asignatura_id=?, proyecto_id=NULL, uni_tipo=? WHERE id=? OR parent_id=?",
                (aid, tipo, iid, iid),
            )
        for x in data.eventos:
            eid, aid = int(x.get("id", 0)), int(x.get("asignatura_id", 0))
            row = conn.execute(
                "SELECT id, contexto, asignatura_id, proyecto_id FROM events WHERE id=?", (eid,)
            ).fetchone()
            if not row or aid not in validas:
                continue
            previo["eventos"].append(dict(row))
            conn.execute(
                "UPDATE events SET contexto='universidad', asignatura_id=?, proyecto_id=NULL WHERE id=?", (aid, eid)
            )
        conn.execute(
            "INSERT INTO contexto_meta (clave, valor) VALUES ('propuesta_previa', ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (json.dumps(previo),),
        )
    return {"items": len(previo["items"]), "eventos": len(previo["eventos"])}


def deshacer_propuesta() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT valor FROM contexto_meta WHERE clave='propuesta_previa'").fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No hay nada que deshacer")
        previo = json.loads(row["valor"])
        for r in previo["items"]:
            conn.execute(
                "UPDATE inbox SET contexto=?, asignatura_id=?, proyecto_id=?, uni_tipo=? WHERE id=? OR parent_id=?",
                (r["contexto"], r["asignatura_id"], r["proyecto_id"], r["uni_tipo"], r["id"], r["id"]),
            )
        for r in previo["eventos"]:
            conn.execute(
                "UPDATE events SET contexto=?, asignatura_id=?, proyecto_id=? WHERE id=?",
                (r["contexto"], r["asignatura_id"], r["proyecto_id"], r["id"]),
            )
        conn.execute("DELETE FROM contexto_meta WHERE clave='propuesta_previa'")
    return {"items": len(previo["items"]), "eventos": len(previo["eventos"])}


# ─────────────────────────────────────────────
# Carpetas candidatas (para elegir la de cada asignatura)
# ─────────────────────────────────────────────


def carpetas(profundidad: int = 2) -> list[dict]:
    """Subcarpetas de la raíz hasta 2 niveles (Tercero/Grafica…), con cuántos temas saldrían."""
    root = root_ready()
    out = []

    def walk(base: Path, rel: str, nivel: int):
        try:
            with os.scandir(base) as it:
                hijos = sorted(
                    [e for e in it if _visible(e) and e.is_dir(follow_symlinks=False)], key=lambda e: _natural(e.name)
                )
        except OSError:
            return
        for e in hijos:
            r = f"{rel}/{e.name}" if rel else e.name
            try:
                n = len(escanear(Path(e.path)))
            except OSError:
                n = 0
            out.append({"ruta": r, "nombre": e.name, "nivel": nivel, "temas": n, "sugerido": bonito(e.name, False)})
            if nivel < profundidad:
                walk(Path(e.path), r, nivel + 1)

    walk(root, "", 1)
    return out


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────


@router.get("")
def api_vista():
    return vista()


@router.get("/resumen")
def api_resumen():
    return resumen()


@router.get("/carpetas")
def api_carpetas():
    return {"carpetas": carpetas()}


@router.post("/asignaturas")
def api_create_asig(data: AsignaturaIn):
    return {"id": create_asig(data)}


@router.patch("/asignaturas/{asig_id}")
def api_update_asig(asig_id: int, data: AsignaturaPatch):
    update_asig(asig_id, data)
    return {"status": "success"}


@router.delete("/asignaturas/{asig_id}")
def api_delete_asig(asig_id: int):
    token = delete_asig(asig_id)
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


@router.post("/asignaturas/{asig_id}/sync")
def api_sync(asig_id: int):
    return sync_asig(asig_id)


@router.post("/sync")
def api_sync_all():
    """Todas las que tienen carpeta. Si la raíz no está, 409 y nada cambia."""
    root_ready()
    out = {}
    with get_db() as conn:
        ids = [
            (r["id"], r["codigo"])
            for r in conn.execute("SELECT id, codigo FROM asignaturas WHERE carpeta IS NOT NULL AND archivada=0")
        ]
    for aid, cod in ids:
        try:
            out[cod] = sync_asig(aid)
        except HTTPException as e:
            out[cod] = {"error": e.detail}
    return {"resultado": out}


@router.get("/asignaturas/{asig_id}/recursos")
def api_recursos_asig(asig_id: int):
    """Archivos sueltos que no son temas (código, comprimidos…), para verlos sin salir del panel."""
    root = root_ready()
    with get_db() as conn:
        a = get_asig(conn, asig_id)
    if not a["carpeta"]:
        return {"recursos": []}
    return {"recursos": recursos(safe_path(root, a["carpeta"]), solo_sueltos=True)}


@router.get("/asignaturas/{asig_id}/entregas")
def api_entregas_asig(asig_id: int):
    with get_db() as conn:
        get_asig(conn, asig_id)
        lista = _entregas(conn, contextos.containers(conn), asig_id=asig_id)
    return {"entregas": lista, "media": media(lista)}


@router.post("/asignaturas/{asig_id}/temas")
def api_create_tema(asig_id: int, data: TemaIn):
    if data.grupo not in GRUPOS:
        raise HTTPException(status_code=422, detail="Grupo: teoria, practicas u otros")
    with get_db() as conn:
        get_asig(conn, asig_id)
        n = conn.execute("SELECT COALESCE(MAX(orden), 0) FROM temas WHERE asignatura_id=?", (asig_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO temas (asignatura_id, titulo, tipo, grupo, orden, titulo_manual) VALUES (?, ?, 'manual', ?, ?, 1)",
            (asig_id, data.titulo.strip(), data.grupo, n + 1),
        )
    return {"id": cur.lastrowid}


@router.post("/asignaturas/{asig_id}/nota-clase")
def api_nota_clase(asig_id: int, data: ClaseNotaIn):
    return nota_de_clase(asig_id, data)


@router.patch("/temas/{tema_id}")
def api_update_tema(tema_id: int, data: TemaPatch):
    update_tema(tema_id, data)
    return {"status": "success"}


@router.delete("/temas/{tema_id}")
def api_delete_tema(tema_id: int):
    """Solo los añadidos a mano o los que ya no están en la carpeta (sin borrar nunca un archivo)."""
    with get_db() as conn:
        t = get_tema(conn, tema_id)
        if t["tipo"] != "manual" and t["falta_desde"] is None:
            raise HTTPException(status_code=409, detail="Ese tema sigue en la carpeta: volvería al sincronizar")
        token = undo.save_rows(
            conn, "rows.tema", [("temas", undo.select(conn, "temas", "id=?", (tema_id,)))], title=t["titulo"]
        )
        conn.execute("DELETE FROM temas WHERE id=?", (tema_id,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


@router.get("/temas/{tema_id}/recursos")
def api_recursos_tema(tema_id: int):
    root = root_ready()
    with get_db() as conn:
        t = get_tema(conn, tema_id)
        a = get_asig(conn, t["asignatura_id"])
    if t["tipo"] != "carpeta" or not a["carpeta"]:
        return {"recursos": []}
    return {"recursos": recursos(safe_path(root, a["carpeta"], t["ruta"]))}


@router.post("/temas/{tema_id}/nota")
def api_nota_tema(tema_id: int):
    return nota_de_tema(tema_id)


@router.get("/horario")
def api_horario():
    with get_db() as conn:
        return {"clases": clases(conn, contextos.containers(conn))}


@router.post("/clases")
def api_crear_clase(data: ClaseIn):
    return {"id": crear_clase(data)}


@router.get("/horario/rutinas")
def api_rutinas_horario():
    """Rutinas o pasos con hora que parecen horario de clases (para ofrecer convertirlos)."""
    from app.items import clean_text

    with get_db() as conn:
        rows = conn.execute(
            "SELECT r.id, r.content, r.due_time, r.duration_min, p.content AS padre FROM inbox r "
            "LEFT JOIN inbox p ON p.id=r.parent_id WHERE r.item_type='rutina' AND r.due_time IS NOT NULL"
        ).fetchall()
    pat = re.compile(r"universidad|clase|facultad|uni\b|teor[ií]a|pr[aá]cticas", re.I)
    return {
        "rutinas": [
            {
                "id": r["id"],
                "titulo": clean_text(r["content"]).split("\n")[0],
                "hora": r["due_time"],
                "duracion": r["duration_min"],
                "rutina": clean_text(r["padre"]).split("\n")[0] if r["padre"] else None,
            }
            for r in rows
            if pat.search(clean_text(r["content"]))
        ]
    }


@router.post("/clases/desde-rutina/{item_id}")
def api_clase_desde_rutina(item_id: int):
    return clase_desde_rutina(item_id)


@router.get("/propuesta")
def api_propuesta():
    return propuesta()


@router.post("/propuesta/aplicar")
def api_aplicar(data: AplicarIn):
    return aplicar_propuesta(data)


@router.post("/propuesta/deshacer")
def api_deshacer():
    return deshacer_propuesta()


# ─────────────────────────────────────────────
# Abrir carpetas: el script del portátil pide la ruta RELATIVA de un id (nunca recibe rutas)
# ─────────────────────────────────────────────


def ruta_de(tipo: str, ident: int) -> dict:
    """{raiz, ruta} de una asignatura, un tema o un proyecto. `absoluta` es la de este servidor (Copiar ruta)."""
    with get_db() as conn:
        if tipo == "asignatura":
            a = get_asig(conn, ident)
            raiz, rel, nombre = "universidad", a["carpeta"], a["nombre"]
        elif tipo == "tema":
            t = get_tema(conn, ident)
            a = get_asig(conn, t["asignatura_id"])
            if not a["carpeta"]:
                raise HTTPException(status_code=409, detail="La asignatura no tiene carpeta")
            if t["tipo"] == "manual" or not t["ruta"]:
                raise HTTPException(status_code=409, detail="Ese tema no tiene archivo ni carpeta: lo añadiste a mano")
            raiz, rel, nombre = "universidad", f"{a['carpeta']}/{t['ruta']}", t["titulo"]
        elif tipo == "proyecto":
            p = conn.execute("SELECT * FROM proyectos WHERE id=?", (ident,)).fetchone()
            if not p:
                raise HTTPException(status_code=404, detail="Proyecto no encontrado")
            raiz, rel, nombre = "proyectos", p["carpeta"], p["nombre"]
        else:
            raise HTTPException(status_code=404, detail="Tipo: asignatura, tema o proyecto")
    if not rel:
        raise HTTPException(status_code=409, detail="No tiene carpeta asignada")
    rel = clean_rel(rel)
    base = contextos.ajuste("uni_raiz" if raiz == "universidad" else "proyectos_raiz")
    absoluta, existe = None, False
    if base:
        try:
            p = safe_path(base, rel)
            absoluta, existe = str(p), p.exists()
        except HTTPException:
            absoluta = None
    return {
        "tipo": tipo,
        "id": ident,
        "nombre": nombre,
        "raiz": raiz,
        "ruta": rel,
        "absoluta": absoluta,
        "existe": existe,
        "url": f"panelmaestro://abrir/{tipo}/{ident}",
    }


@open_router.get("/{tipo}/{ident}")
def api_ruta(tipo: str, ident: int):
    return ruta_de(tipo, ident)
