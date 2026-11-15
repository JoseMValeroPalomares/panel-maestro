"""
Contextos: Puntual, Universidad y Proyectos.

No hay listas aparte: cada tarea, idea, rutina, evento, esquema y nota es una sola fila
(o un solo .md) con su `contexto` y, si quiere, un contenedor:
  - `asignatura_id` (tabla asignaturas) → contexto «universidad»
  - `proyecto_id`   (tabla proyectos)   → contexto «proyectos»
El contenedor manda sobre el contexto (las dos cosas nunca se contradicen) y los pasos
heredan los de su elemento, como heredan el tipo. En las notas lo dice su frontmatter
(`contexto`, `asignatura: <código>`, `proyecto: <slug>`) y sus casillas lo copian.

Todas las vistas filtran con lo mismo: `matches()` en Python (calendario, Hoy, agenda de
la Waybar, extensión, paleta) y `Ctx.match` en static/js/contexto.js con la misma regla.
El contexto activo es la preferencia `contexto` (ui_prefs), así que es el mismo en el
navegador, la Waybar y la extensión.
"""

import json
import os
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db

router = APIRouter(prefix="/api/contextos")

CONTEXTOS = ("puntual", "universidad", "proyectos")
ETIQUETAS = {"puntual": "Puntual", "universidad": "Universidad", "proyectos": "Proyectos", "todo": "Todo"}
PREF_KEY = "contexto"

# Ajustes (tabla contexto_meta); la variable de entorno, si está, manda (útil en pruebas)
AJUSTES = {
    "uni_raiz": ("PANEL_UNI_ROOT", ""),
    "proyectos_raiz": ("PANEL_PROYECTOS_ROOT", str(Path.home() / "Projects")),
    "waybar_contexto": ("PANEL_WAYBAR_CONTEXTO", "activo"),
    # Prompt para pedir a una IA que explique un tema (Universidad → «Copiar prompt»): {asignatura} y {tema}
    "uni_prompt": (
        "",
        "Ayúdame a entender y aprenderme este tema de mi asignatura de «{asignatura}»: «{tema}». Vamos poco a poco, "
        "paso tras paso; a mí me gusta entenderlo todo, sobre todo gracias a la lógica, que tenga sentido. Ten en "
        "cuenta que las diapositivas no están hechas como apuntes sino como guía para explicar en clase, así que hay "
        "cosas que les faltan o que necesitan más desarrollo: desarróllalo tú.",
    ),
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def norm_ctx(v: str | None, allow_all: bool = False) -> str | None:
    v = (v or "").strip().lower()
    if v in CONTEXTOS or (allow_all and v == "todo"):
        return v
    return None


# ─────────────────────────────────────────────
# Ajustes y contexto activo
# ─────────────────────────────────────────────


def ajuste(clave: str) -> str:
    env, default = AJUSTES[clave]
    if env and os.environ.get(env):
        return os.environ[env].strip()
    with get_db() as conn:
        row = conn.execute("SELECT valor FROM contexto_meta WHERE clave=?", (clave,)).fetchone()
    return row["valor"] if row else default


def set_ajuste(clave: str, valor: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO contexto_meta (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, valor),
        )


def activo() -> str:
    """El contexto elegido en la interfaz (preferencia del servidor); «todo» si no hay ninguno."""
    with get_db() as conn:
        row = conn.execute("SELECT value FROM ui_prefs WHERE key=?", (PREF_KEY,)).fetchone()
    try:
        v = json.loads(row["value"]) if row else "todo"
    except ValueError:
        v = "todo"
    return norm_ctx(v, allow_all=True) or "todo"


def resolve_filter(v: str | None) -> str:
    """?contexto= de una petición: vacío o «activo» = el de la interfaz; «todo» = sin filtro."""
    if v in (None, "", "activo"):
        return activo()
    ctx = norm_ctx(v, allow_all=True)
    if not ctx:
        raise HTTPException(status_code=422, detail="Contexto: puntual, universidad, proyectos, todo o activo")
    return ctx


def matches(entry: dict, ctx: str) -> bool:
    """La única regla de filtrado: «todo» lo deja pasar todo; si no, el contexto del elemento."""
    return ctx == "todo" or (entry.get("contexto") or "puntual") == ctx


# ─────────────────────────────────────────────
# Contenedores
# ─────────────────────────────────────────────


def containers(conn) -> dict:
    """Asignaturas y proyectos con lo necesario para pintar (color, código, nombre)."""
    asig = {
        r["id"]: {"id": r["id"], "codigo": r["codigo"], "nombre": r["nombre"], "color": r["color"]}
        for r in conn.execute("SELECT id, codigo, nombre, color FROM asignaturas")
    }
    proy = {
        r["id"]: {"id": r["id"], "slug": r["slug"], "nombre": r["nombre"], "color": r["color"]}
        for r in conn.execute("SELECT id, slug, nombre, color FROM proyectos")
    }
    return {"asignaturas": asig, "proyectos": proy}


def label(row, conts: dict) -> dict:
    """Campos de contexto que llevan todas las salidas (tareas, entradas del calendario…)."""

    def col(name):
        try:
            return row[name]
        except (IndexError, KeyError):
            return None

    a, p = col("asignatura_id"), col("proyecto_id")
    out = {"contexto": col("contexto") or "puntual", "asignatura_id": a, "proyecto_id": p}
    if a and a in conts["asignaturas"]:
        x = conts["asignaturas"][a]
        out.update(asignatura=x["codigo"], asignatura_nombre=x["nombre"], color=x["color"])
    if p and p in conts["proyectos"]:
        x = conts["proyectos"][p]
        out.update(proyecto=x["slug"], proyecto_nombre=x["nombre"], color=x["color"])
    return out


def resolve(
    conn,
    contexto: str | None,
    asignatura_id: int | None,
    proyecto_id: int | None,
    current: tuple[str, int | None, int | None] = ("puntual", None, None),
) -> tuple[str, int | None, int | None]:
    """Contexto y contenedor finales a partir de un cambio parcial (None = no cambia, 0 = quitar).
    El contenedor manda: con asignatura es «universidad», con proyecto es «proyectos»."""
    ctx, a, p = current
    if asignatura_id is not None:
        a = asignatura_id or None
        if a:
            if not conn.execute("SELECT 1 FROM asignaturas WHERE id=?", (a,)).fetchone():
                raise HTTPException(status_code=422, detail="Esa asignatura no existe")
            ctx, p = "universidad", None
    if proyecto_id is not None:
        p = proyecto_id or None
        if p:
            if not conn.execute("SELECT 1 FROM proyectos WHERE id=?", (p,)).fetchone():
                raise HTTPException(status_code=422, detail="Ese proyecto no existe")
            if asignatura_id:
                raise HTTPException(status_code=422, detail="Va a una asignatura o a un proyecto, no a los dos")
            ctx, a = "proyectos", None
    if contexto is not None:
        c = norm_ctx(contexto)
        if not c:
            raise HTTPException(status_code=422, detail="Contexto: puntual, universidad o proyectos")
        if c != ctx:
            ctx = c
            if c != "universidad":
                a = None
            if c != "proyectos":
                p = None
    if a:
        ctx = "universidad"
    elif p:
        ctx = "proyectos"
    return ctx, a, p


# ─────────────────────────────────────────────
# Menciones de la captura: @asignatura y #proyecto
# ─────────────────────────────────────────────

MENTION_RE = re.compile(r"(?<![\w@#])([@#])([\w][\w.\-]*)", re.UNICODE)
VERSION_RE = re.compile(r"(?<![\w.])v(\d+(?:\.\d+){0,2})(?![\w.])", re.I)


def alias_index(conn) -> dict:
    """alias plegado → asignatura o proyecto (código, alias, slug y nombre sin espacios)."""
    out = {"@": {}, "#": {}}
    for r in conn.execute("SELECT id, codigo, nombre, alias FROM asignaturas WHERE archivada=0"):
        try:
            extra = json.loads(r["alias"] or "[]")
        except ValueError:
            extra = []
        for k in [r["codigo"], r["nombre"], *extra]:
            if k:
                out["@"].setdefault(
                    fold(k).replace(" ", ""), {"id": r["id"], "codigo": r["codigo"], "nombre": r["nombre"]}
                )
    for r in conn.execute("SELECT id, slug, nombre FROM proyectos"):
        for k in (r["slug"], r["nombre"]):
            out["#"].setdefault(fold(k).replace(" ", "-"), {"id": r["id"], "slug": r["slug"], "nombre": r["nombre"]})
            out["#"].setdefault(fold(k).replace(" ", ""), {"id": r["id"], "slug": r["slug"], "nombre": r["nombre"]})
    return out


def parse_mentions(text: str) -> dict:
    """Quita del texto «@gabd», «#panel-maestro» y, con proyecto, «v0.3». Devuelve lo encontrado y
    los errores (mención que no existe): no se crea nada en silencio."""
    with get_db() as conn:
        idx = alias_index(conn)
        out = {"text": text, "asignatura": None, "proyecto": None, "version": None, "errores": []}
        spans = []
        for m in MENTION_RE.finditer(text):
            sigil, name = m.group(1), m.group(2).rstrip(".-")
            key = fold(name)
            hit = idx[sigil].get(key)
            if hit is None:  # no se crea en silencio: se avisa, con la más parecida si la hay
                import difflib

                cerca = difflib.get_close_matches(key.replace(" ", ""), list(idx[sigil]), n=1, cutoff=0.6)
                pista = f". ¿Querías decir «{sigil}{cerca[0]}»?" if cerca else ""
                out["errores"].append(
                    f"No existe {'la asignatura' if sigil == '@' else 'el proyecto'} «{sigil}{name}»{pista}"
                )
                continue
            if sigil == "@":
                out["asignatura"] = hit
            else:
                out["proyecto"] = hit
            spans.append(m.span())
        if out["asignatura"] and out["proyecto"]:
            out["errores"].append("Va a una asignatura o a un proyecto, no a los dos")
        if out["proyecto"]:
            vm = VERSION_RE.search(text)
            if vm:
                nombre = "v" + vm.group(1)
                row = conn.execute(
                    "SELECT id, nombre, estado FROM versiones WHERE proyecto_id=? AND lower(nombre)=lower(?)",
                    (out["proyecto"]["id"], nombre),
                ).fetchone()
                if row is None:
                    out["errores"].append(f"El proyecto «{out['proyecto']['slug']}» no tiene la versión {nombre}")
                else:
                    out["version"] = {"id": row["id"], "nombre": row["nombre"]}
                    spans.append(vm.span())
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    out["text"] = re.sub(r"\s+", " ", "".join(chars)).strip(" ,·-")
    return out


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────


class AjustesIn(BaseModel):
    uni_raiz: str | None = Field(default=None, max_length=1000)
    proyectos_raiz: str | None = Field(default=None, max_length=1000)
    waybar_contexto: str | None = Field(default=None, max_length=20)
    uni_prompt: str | None = Field(default=None, max_length=5000)


@router.get("")
def api_contextos():
    with get_db() as conn:
        asig = [
            dict(r)
            for r in conn.execute(
                "SELECT id, codigo, nombre, color, alias FROM asignaturas WHERE archivada=0 ORDER BY orden, nombre"
            )
        ]
        proy = [
            dict(r)
            for r in conn.execute("SELECT id, slug, nombre, color, estado FROM proyectos ORDER BY orden, nombre")
        ]
        vers = [dict(r) for r in conn.execute("SELECT id, proyecto_id, nombre, estado FROM versiones ORDER BY id")]
    for a in asig:
        try:
            a["alias"] = json.loads(a["alias"] or "[]")
        except ValueError:
            a["alias"] = []
    return {
        "activo": activo(),
        "contextos": [{"id": c, "nombre": ETIQUETAS[c]} for c in (*CONTEXTOS, "todo")],
        "asignaturas": asig,
        "proyectos": proy,
        "versiones": vers,
    }


@router.get("/menciones")
def api_menciones():
    """Lista para autocompletar (rofi, extensión, captura de la app)."""
    with get_db() as conn:
        asig = [
            {"mencion": "@" + fold(r["codigo"]).replace(" ", ""), "nombre": r["nombre"], "color": r["color"]}
            for r in conn.execute(
                "SELECT codigo, nombre, color FROM asignaturas WHERE archivada=0 ORDER BY orden, nombre"
            )
        ]
        proy = [
            {"mencion": "#" + r["slug"], "nombre": r["nombre"], "color": r["color"]}
            for r in conn.execute(
                "SELECT slug, nombre, color FROM proyectos WHERE estado != 'terminado' ORDER BY orden, nombre"
            )
        ]
    return {"menciones": asig + proy}


@router.get("/ajustes")
def api_ajustes():
    return {k: ajuste(k) for k in AJUSTES}


@router.put("/ajustes")
def api_set_ajustes(data: AjustesIn):
    for k in AJUSTES:
        v = getattr(data, k)
        if v is None:
            continue
        v = v.strip()
        if k == "waybar_contexto" and v not in ("activo", "todo", *CONTEXTOS):
            raise HTTPException(status_code=422, detail="Waybar: activo, todo, puntual, universidad o proyectos")
        if k.endswith("_raiz") and v and not os.path.isabs(os.path.expanduser(v)):
            raise HTTPException(status_code=422, detail="La carpeta raíz va como ruta absoluta")
        if k == "uni_prompt" and not v:
            with get_db() as conn:  # vacío = volver al de siempre
                conn.execute("DELETE FROM contexto_meta WHERE clave='uni_prompt'")
            continue
        set_ajuste(k, os.path.expanduser(v) if k.endswith("_raiz") else v)
    return api_ajustes()


@router.get("/integridad")
def api_integridad():
    """Conteos de antes de la migración frente a los de ahora (criterio: nada se pierde)."""
    with get_db() as conn:
        row = conn.execute("SELECT valor FROM contexto_meta WHERE clave='conteos_previos'").fetchone()
        antes = json.loads(row["valor"]) if row else {}
        ahora = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in antes}
        por_ctx = {
            t: dict(conn.execute(f"SELECT contexto, COUNT(*) FROM {t} GROUP BY contexto").fetchall())
            for t in ("inbox", "events", "boards", "notes")
        }
    return {"antes": antes, "ahora": ahora, "por_contexto": por_ctx}
