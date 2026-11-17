"""
Proyectos: contenedor de tareas, ideas, esquemas y notas (contexto «proyectos») con versiones.

(No confundir con app/proyecto.py, que publica el propio panel en GitHub.)

  - Las tareas e ideas de un proyecto son filas de `inbox` con `proyecto_id` (y, si se quiere,
    `version_id`); el tablero por hacer / en curso / hecho usa `status` y `en_curso`.
  - Una versión tiene fecha objetivo; al cerrarla se genera su registro de cambios con las tareas
    hechas que tenía asignadas (editable después) y las abiertas pueden pasar a otra versión.
  - La bitácora es una nota normal (frontmatter `proyecto: <slug>`, `bitacora: true`).
  - Git, opcional y SOLO LECTURA: si el proyecto tiene carpeta con repositorio se leen el último
    commit y las etiquetas con `git log`/`git tag` (nunca nada que lo modifique).
"""

import json
import os
import re
import subprocess
import time
from datetime import date

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import contextos
from app.database import get_db
from app.notes_core import note_path, note_slug
from app.universidad import COLORES, Enlace, _jl, clean_rel, safe_path
from core import undo
from core.db import update_fields
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("proyectos")
router = APIRouter(prefix="/api/proyectos")

ESTADOS = ("idea", "en-curso", "pausado", "terminado")
PRIORIDADES = ("alta", "media", "baja")
MAX_DESC = 20_000


def _fecha(v):
    if v in (None, ""):
        return v
    return date.fromisoformat(v).isoformat()


def _etiquetas(v):
    if v is None:
        return None
    out, seen = [], set()
    for t in v:
        t = re.sub(r"\s+", " ", str(t)).strip().lstrip("#")[:30]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:20]


def _prioridad(v):
    if v not in (None, "") and v not in PRIORIDADES:
        raise ValueError("Prioridad: alta, media o baja")
    return v


VERSION_RE = re.compile(r"^v?\d+(\.\d+){0,2}([\-+][\w.]+)?$", re.I)


def slugify(nombre: str) -> str:
    s = contextos.fold(nombre)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "proyecto"


class ProyectoIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=60)
    descripcion: str | None = Field(default=None, max_length=MAX_DESC)
    estado: str = Field(default="en-curso", max_length=12)
    color: str | None = Field(default=None, max_length=10)
    repo_url: str | None = Field(default=None, max_length=1000)
    carpeta: str | None = Field(default=None, max_length=1000)
    enlaces: list[Enlace] = Field(default_factory=list, max_length=30)
    prioridad: str | None = Field(default=None, max_length=5)
    fecha_inicio: str | None = Field(default=None, max_length=10)
    fecha_fin: str | None = Field(default=None, max_length=10)
    etiquetas: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("estado")
    @classmethod
    def v_estado(cls, v):
        if v not in ESTADOS:
            raise ValueError("Estado: idea, en-curso, pausado o terminado")
        return v

    _v_prio = field_validator("prioridad")(classmethod(lambda cls, v: _prioridad(v)))
    _v_fechas = field_validator("fecha_inicio", "fecha_fin")(classmethod(lambda cls, v: _fecha(v)))
    _v_tags = field_validator("etiquetas")(classmethod(lambda cls, v: _etiquetas(v)))


class ProyectoPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=MAX_DESC)
    estado: str | None = Field(default=None, max_length=12)
    color: str | None = Field(default=None, max_length=10)
    repo_url: str | None = Field(default=None, max_length=1000)
    carpeta: str | None = Field(default=None, max_length=1000)
    enlaces: list[Enlace] | None = Field(default=None, max_length=30)
    before_id: int | None = None
    prioridad: str | None = Field(default=None, max_length=5)  # "" la quita
    fecha_inicio: str | None = Field(default=None, max_length=10)  # "" la quita
    fecha_fin: str | None = Field(default=None, max_length=10)  # "" la quita
    etiquetas: list[str] | None = Field(default=None, max_length=40)

    @field_validator("estado")
    @classmethod
    def v_estado(cls, v):
        if v is not None and v not in ESTADOS:
            raise ValueError("Estado: idea, en-curso, pausado o terminado")
        return v

    _v_prio = field_validator("prioridad")(classmethod(lambda cls, v: _prioridad(v)))
    _v_fechas = field_validator("fecha_inicio", "fecha_fin")(classmethod(lambda cls, v: _fecha(v)))
    _v_tags = field_validator("etiquetas")(classmethod(lambda cls, v: _etiquetas(v)))


class VersionIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=30)
    fecha_objetivo: str | None = Field(default=None, max_length=10)
    titulo: str | None = Field(default=None, max_length=120)
    descripcion: str | None = Field(default=None, max_length=MAX_DESC)

    @field_validator("nombre")
    @classmethod
    def v_nombre(cls, v):
        v = v.strip()
        if not VERSION_RE.match(v):
            raise ValueError("Nombre de versión como v0.1, v1.2.3 o 0.3")
        return v if v.lower().startswith("v") else "v" + v

    @field_validator("fecha_objetivo")
    @classmethod
    def v_fecha(cls, v):
        if v in (None, ""):
            return None
        return date.fromisoformat(v).isoformat()


class VersionPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=30)
    fecha_objetivo: str | None = Field(default=None, max_length=10)  # "" la quita
    changelog: str | None = Field(default=None, max_length=50_000)
    estado: str | None = Field(default=None, max_length=10)  # abierta (reabrir)
    titulo: str | None = Field(default=None, max_length=120)  # "" lo quita
    descripcion: str | None = Field(default=None, max_length=MAX_DESC)  # "" la quita


class CerrarIn(BaseModel):
    mover_a: int | None = None  # versión a la que pasan las tareas abiertas (None = se quedan sin versión)


def _check_color(v):
    if v and v not in COLORES:
        raise HTTPException(status_code=422, detail="Color no válido")


def _check_url(v):
    if v and not re.match(r"^https?://", v.strip(), re.I):
        raise HTTPException(status_code=422, detail="El repositorio empieza por http:// o https://")


def get_proy(conn, pid: int):
    row = conn.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return row


def by_slug(conn, slug: str):
    row = conn.execute("SELECT * FROM proyectos WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return row


def create(data: ProyectoIn) -> int:
    _check_color(data.color)
    _check_url(data.repo_url)
    slug = slugify(data.slug or data.nombre)
    with get_db() as conn:
        base, n = slug, 2
        while conn.execute("SELECT 1 FROM proyectos WHERE slug=?", (slug,)).fetchone():
            slug, n = f"{base}-{n}", n + 1
        cnt = conn.execute("SELECT COUNT(*), COALESCE(MAX(orden), 0) FROM proyectos").fetchone()
        cur = conn.execute(
            "INSERT INTO proyectos (nombre, slug, descripcion, estado, color, repo_url, carpeta, enlaces, orden, "
            "prioridad, fecha_inicio, fecha_fin, etiquetas) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.nombre.strip(),
                slug,
                data.descripcion,
                data.estado,
                data.color or COLORES[(cnt[0] + 3) % len(COLORES)],
                data.repo_url,
                clean_rel(data.carpeta) or None if data.carpeta else None,
                json.dumps([e.model_dump() for e in data.enlaces], ensure_ascii=False),
                cnt[1] + 1,
                data.prioridad or None,
                data.fecha_inicio or None,
                data.fecha_fin or None,
                json.dumps(data.etiquetas, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def update(pid: int, data: ProyectoPatch) -> None:
    _check_color(data.color)
    _check_url(data.repo_url)
    with get_db() as conn:
        get_proy(conn, pid)
        campos = ("nombre", "descripcion", "estado", "color", "repo_url")
        dados = {f: getattr(data, f) for f in campos if getattr(data, f) is not None}
        update_fields(
            conn,
            "proyectos",
            pid,
            {f: v.strip() or None if isinstance(v, str) else v for f, v in dados.items()},
            campos,
        )
        if data.carpeta is not None:
            conn.execute("UPDATE proyectos SET carpeta=? WHERE id=?", (clean_rel(data.carpeta) or None, pid))
        for campo in ("prioridad", "fecha_inicio", "fecha_fin"):  # "" lo quita
            if getattr(data, campo) is not None:
                conn.execute(f"UPDATE proyectos SET {campo}=? WHERE id=?", (getattr(data, campo) or None, pid))
        if data.etiquetas is not None:
            conn.execute(
                "UPDATE proyectos SET etiquetas=? WHERE id=?", (json.dumps(data.etiquetas, ensure_ascii=False), pid)
            )
        if data.enlaces is not None:
            conn.execute(
                "UPDATE proyectos SET enlaces=? WHERE id=?",
                (json.dumps([e.model_dump() for e in data.enlaces], ensure_ascii=False), pid),
            )
        if data.before_id is not None:
            ids = [r["id"] for r in conn.execute("SELECT id FROM proyectos WHERE id != ? ORDER BY orden, id", (pid,))]
            ids.insert(ids.index(data.before_id) if data.before_id in ids else len(ids), pid)
            for i, x in enumerate(ids):
                conn.execute("UPDATE proyectos SET orden=? WHERE id=?", (i + 1, x))


def _version_out(r, tareas: list[dict]) -> dict:
    mias = [t for t in tareas if t["version_id"] == r["id"]]
    hechas = sum(1 for t in mias if t["hecha"])
    return {
        "id": r["id"],
        "nombre": r["nombre"],
        "titulo": r["titulo"],
        "descripcion": r["descripcion"],
        "fecha_objetivo": r["fecha_objetivo"],
        "estado": r["estado"],
        "changelog": r["changelog"],
        "cerrada_at": r["cerrada_at"],
        "total": len(mias),
        "hechas": hechas,
        "progreso": round(100 * hechas / len(mias)) if mias else 0,
    }


def _tareas(conn, pid: int) -> list[dict]:
    from app.items import clean_text

    return [
        {
            "id": r["id"],
            "titulo": clean_text(r["content"]).split("\n")[0],
            "hecha": r["status"] == "processed",
            "version_id": r["version_id"],
            "tipo": "idea" if r["item_type"] == "nota" else "tarea",
            "en_curso": bool(r["en_curso"]),
        }
        for r in conn.execute(
            "SELECT * FROM inbox WHERE proyecto_id=? AND parent_id IS NULL AND item_type != 'rutina'", (pid,)
        )
    ]


def resumen(conn, r) -> dict:
    tareas = _tareas(conn, r["id"])
    vers = [
        _version_out(v, tareas)
        for v in conn.execute("SELECT * FROM versiones WHERE proyecto_id=? ORDER BY id", (r["id"],))
    ]
    solo = [t for t in tareas if t["tipo"] == "tarea"]
    hechas = sum(1 for t in solo if t["hecha"])
    actual = next((v for v in vers if v["estado"] == "abierta"), None)
    ultima = next((v for v in reversed(vers) if v["estado"] == "cerrada"), None)
    return {
        "id": r["id"],
        "nombre": r["nombre"],
        "slug": r["slug"],
        "descripcion": r["descripcion"],
        "estado": r["estado"],
        "color": r["color"] or "cat-1",
        "repo_url": r["repo_url"],
        "carpeta": r["carpeta"],
        "enlaces": _jl(r["enlaces"]),
        "prioridad": r["prioridad"],
        "fecha_inicio": r["fecha_inicio"],
        "fecha_fin": r["fecha_fin"],
        "etiquetas": _jl(r["etiquetas"]),
        "created_at": r["created_at"],
        "note_id": r["note_id"],
        "orden": r["orden"],
        "tareas_abiertas": len(solo) - hechas,
        "tareas_hechas": hechas,
        "ideas": sum(1 for t in tareas if t["tipo"] == "idea" and not t["hecha"]),
        "progreso": round(100 * hechas / len(solo)) if solo else 0,
        "version_actual": actual,
        "ultima_version": ultima,
        "versiones": vers,
    }


def lista() -> list[dict]:
    with get_db() as conn:
        return [
            resumen(conn, r)
            for r in conn.execute(
                "SELECT * FROM proyectos ORDER BY CASE estado WHEN 'en-curso' THEN 0 WHEN 'idea' THEN 1 WHEN 'pausado' THEN 2 ELSE 3 END, orden, nombre"
            )
        ]


# ─────────────────────────────────────────────
# Versiones
# ─────────────────────────────────────────────


def get_version(conn, vid: int):
    row = conn.execute("SELECT * FROM versiones WHERE id=?", (vid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Versión no encontrada")
    return row


def create_version(pid: int, data: VersionIn) -> int:
    with get_db() as conn:
        get_proy(conn, pid)
        if conn.execute(
            "SELECT 1 FROM versiones WHERE proyecto_id=? AND lower(nombre)=lower(?)", (pid, data.nombre)
        ).fetchone():
            raise HTTPException(status_code=409, detail=f"Ya existe la {data.nombre}")
        return conn.execute(
            "INSERT INTO versiones (proyecto_id, nombre, fecha_objetivo, titulo, descripcion) VALUES (?, ?, ?, ?, ?)",
            (
                pid,
                data.nombre,
                data.fecha_objetivo,
                (data.titulo or "").strip() or None,
                (data.descripcion or "").strip() or None,
            ),
        ).lastrowid


def changelog_de(conn, v) -> str:
    """Registro de cambios en Markdown: tareas hechas de la versión (con sus pasos hechos)."""
    from app.items import clean_text

    hechas = conn.execute(
        "SELECT * FROM inbox WHERE version_id=? AND parent_id IS NULL AND status='processed' AND item_type='tarea' "
        "ORDER BY sort_order DESC",
        (v["id"],),
    ).fetchall()
    titulo = f" · {v['titulo']}" if v["titulo"] else ""
    lines = [f"## {v['nombre']}{titulo} — {date.today().strftime('%d/%m/%Y')}", ""]
    if not hechas:
        lines.append("- (sin tareas completadas)")
    for r in hechas:
        lines.append(f"- {clean_text(r['content']).split(chr(10))[0]}")
        for k in conn.execute(
            "SELECT content FROM inbox WHERE parent_id=? AND status='processed' ORDER BY sort_order DESC", (r["id"],)
        ):
            lines.append(f"  - {clean_text(k['content']).split(chr(10))[0]}")
    return "\n".join(lines) + "\n"


def cerrar(vid: int, data: CerrarIn) -> dict:
    with get_db() as conn:
        v = get_version(conn, vid)
        if v["estado"] == "cerrada":
            raise HTTPException(status_code=409, detail="La versión ya está cerrada")
        if data.mover_a:
            dest = get_version(conn, data.mover_a)
            if dest["proyecto_id"] != v["proyecto_id"] or dest["estado"] != "abierta" or dest["id"] == vid:
                raise HTTPException(
                    status_code=422, detail="Las tareas abiertas solo pasan a otra versión abierta del mismo proyecto"
                )
        texto = changelog_de(conn, v)
        abiertas = conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE version_id=? AND parent_id IS NULL AND status != 'processed'", (vid,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE inbox SET version_id=? WHERE version_id=? AND status != 'processed'", (data.mover_a or None, vid)
        )
        conn.execute(
            "UPDATE versiones SET estado='cerrada', changelog=?, cerrada_at=? WHERE id=?", (texto, time.time(), vid)
        )
    return {
        "changelog": texto,
        "movidas": abiertas if data.mover_a else 0,
        "sin_version": 0 if data.mover_a else abiertas,
    }


def update_version(vid: int, data: VersionPatch) -> None:
    with get_db() as conn:
        v = get_version(conn, vid)
        if data.nombre is not None:
            nombre = VersionIn(nombre=data.nombre).nombre
            if conn.execute(
                "SELECT 1 FROM versiones WHERE proyecto_id=? AND lower(nombre)=lower(?) AND id != ?",
                (v["proyecto_id"], nombre, vid),
            ).fetchone():
                raise HTTPException(status_code=409, detail=f"Ya existe la {nombre}")
            conn.execute("UPDATE versiones SET nombre=? WHERE id=?", (nombre, vid))
        if data.fecha_objetivo is not None:
            conn.execute(
                "UPDATE versiones SET fecha_objetivo=? WHERE id=?",
                (VersionIn(nombre="v0", fecha_objetivo=data.fecha_objetivo).fecha_objetivo, vid),
            )
        if data.changelog is not None:
            conn.execute("UPDATE versiones SET changelog=? WHERE id=?", (data.changelog, vid))
        for campo in ("titulo", "descripcion"):  # "" lo quita
            if getattr(data, campo) is not None:
                conn.execute(f"UPDATE versiones SET {campo}=? WHERE id=?", (getattr(data, campo).strip() or None, vid))
        if data.estado == "abierta":
            conn.execute("UPDATE versiones SET estado='abierta', cerrada_at=NULL WHERE id=?", (vid,))


def delete_version(vid: int) -> str:
    """A la papelera; al restaurarla, sus tareas vuelven a ella (las que no se movieron a otra entretanto)."""
    with get_db() as conn:
        v = get_version(conn, vid)
        tareas = [r["id"] for r in conn.execute("SELECT id FROM inbox WHERE version_id=?", (vid,))]
        token = undo.save_rows(
            conn,
            "rows.version",
            [("versiones", undo.select(conn, "versiones", "id=?", (vid,)))],
            title=v["nombre"],
            relink=[("inbox", "version_id", vid, tareas)],
        )
        conn.execute("UPDATE inbox SET version_id=NULL WHERE version_id=?", (vid,))
        conn.execute("DELETE FROM versiones WHERE id=?", (vid,))
    return token


# ─────────────────────────────────────────────
# Bitácora y Git (solo lectura)
# ─────────────────────────────────────────────


def bitacora(pid: int) -> dict:
    from app.indexer import sync_notes_to_db

    with get_db() as conn:
        p = get_proy(conn, pid)
    if p["note_id"] and os.path.exists(note_path(p["note_id"])):
        return {"note_id": p["note_id"], "creada": False}
    title = f"Bitácora · {p['nombre']}"
    note_id, n = note_slug(title), 2
    base = note_id
    while os.path.exists(note_path(note_id)):
        note_id, n = f"{base}-{n}", n + 1
    hoy = date.today().strftime("%d/%m/%Y")
    body = (
        f"# Bitácora de {p['nombre']}\n\n"
        "Decisiones, cambios y aprendizajes, de lo más nuevo a lo más viejo. Enlaza tareas con [[tarea:N]].\n\n"
        f"## {hoy}\n\n- Empiezo la bitácora.\n"
    )
    post = frontmatter.Post(body)
    post["title"], post["category"], post["category_id"] = title, f"Proyectos - {p['nombre']}", None
    post["status"], post["tags"], post["encrypted"] = "en-desarrollo", [], False
    post["contexto"], post["proyecto"], post["bitacora"] = "proyectos", p["slug"], True
    atomic_write(note_path(note_id), frontmatter.dumps(post) + "\n")
    sync_notes_to_db()
    with get_db() as conn:
        conn.execute("UPDATE proyectos SET note_id=? WHERE id=?", (note_id, pid))
    return {"note_id": note_id, "creada": True}


GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def _git(repo: str, *args: str) -> str:
    # Solo órdenes de lectura, con -C y sin locks opcionales: nunca se modifica el repositorio
    if args[0] not in ("log", "tag", "rev-parse"):
        raise RuntimeError("solo lectura")
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=5, env=GIT_ENV)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return out.stdout


def git_info(pid: int) -> dict:
    with get_db() as conn:
        p = get_proy(conn, pid)
    base = contextos.ajuste("proyectos_raiz")
    if not p["carpeta"] or not base:
        return {"disponible": False, "motivo": "Sin carpeta"}
    try:
        repo = str(safe_path(base, p["carpeta"]))
    except HTTPException as e:
        return {"disponible": False, "motivo": e.detail}
    if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        return {"disponible": False, "motivo": "La carpeta no es un repositorio"}
    try:
        last = _git(repo, "log", "-1", "--format=%H%x1f%s%x1f%an%x1f%cI").strip().split("\x1f")
        tags = [t for t in _git(repo, "tag", "--sort=-creatordate").splitlines() if t][:15]
        rama = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        return {"disponible": False, "motivo": f"No se pudo leer el repositorio ({e})"}
    commit = {"hash": last[0][:10], "mensaje": last[1], "autor": last[2], "fecha": last[3]} if len(last) == 4 else None
    return {"disponible": True, "rama": rama, "ultimo": commit, "etiquetas": tags}


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────


@router.get("")
def api_lista():
    return {"proyectos": lista()}


@router.post("")
def api_create(data: ProyectoIn):
    pid = create(data)
    with get_db() as conn:
        return resumen(conn, get_proy(conn, pid))


@router.get("/{slug}")
def api_get(slug: str):
    from app.item_extras import contar

    with get_db() as conn:
        out = resumen(conn, by_slug(conn, slug))
        ids = [r["id"] for r in conn.execute("SELECT id FROM inbox WHERE proyecto_id=?", (out["id"],))]
        # comentarios y adjuntos de cada tarea, para los contadores de las tarjetas
        out["extras"] = {str(k): v for k, v in contar(conn, ids).items()}
        return out


@router.patch("/{pid}")
def api_update(pid: int, data: ProyectoPatch):
    update(pid, data)
    return {"status": "success"}


@router.delete("/{pid}")
def api_delete(pid: int):
    with get_db() as conn:
        get_proy(conn, pid)
        n = sum(
            conn.execute(q, (pid,)).fetchone()[0]
            for q in (
                "SELECT COUNT(*) FROM inbox WHERE proyecto_id=?",
                "SELECT COUNT(*) FROM boards WHERE proyecto_id=?",
                "SELECT COUNT(*) FROM notes WHERE proyecto_id=?",
                "SELECT COUNT(*) FROM events WHERE proyecto_id=?",
            )
        )
        if n:
            raise HTTPException(
                status_code=409, detail="Tiene tareas, esquemas, notas o eventos: márcalo como terminado"
            )
        p = undo.select(conn, "proyectos", "id=?", (pid,))
        token = undo.save_rows(
            conn,
            "rows.proyecto",
            [("proyectos", p), ("versiones", undo.select(conn, "versiones", "proyecto_id=?", (pid,)))],
            title=p[0]["nombre"],
        )
        conn.execute("DELETE FROM versiones WHERE proyecto_id=?", (pid,))
        conn.execute("DELETE FROM proyectos WHERE id=?", (pid,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


@router.post("/{pid}/versiones")
def api_create_version(pid: int, data: VersionIn):
    return {"id": create_version(pid, data)}


@router.patch("/versiones/{vid}")
def api_update_version(vid: int, data: VersionPatch):
    update_version(vid, data)
    return {"status": "success"}


@router.post("/versiones/{vid}/cerrar")
def api_cerrar(vid: int, data: CerrarIn):
    return cerrar(vid, data)


@router.get("/versiones/{vid}/changelog")
def api_preview_changelog(vid: int):
    """Vista previa del registro de cambios antes de cerrar."""
    with get_db() as conn:
        return {"changelog": changelog_de(conn, get_version(conn, vid))}


@router.delete("/versiones/{vid}")
def api_delete_version(vid: int):
    token = delete_version(vid)
    return {"status": "success", "undo_token": token, "undo_db": "brain"}


@router.post("/{pid}/bitacora")
def api_bitacora(pid: int):
    return bitacora(pid)


@router.get("/{pid}/git")
def api_git(pid: int):
    return git_info(pid)
