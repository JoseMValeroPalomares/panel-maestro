"""
Búsqueda única (FTS5) en notas, tareas/ideas/rutinas, recursos del Baúl y eventos; enlaces entrantes (backlinks) y
filtros guardados.

Una sola tabla FTS con columna `kind` (y no una por tipo): un único tokenizador y una sola consulta preparada para
todo, un solo refresco y una sola
tabla de estado. Lo propio de cada tipo (estado de una nota, fecha de un evento…) no se copia: se lee con un JOIN a su
tabla, que es la que manda. El índice es una caché de la caché (se puede borrar sin perder nada):

    search_fts        (kind, ref, title, body, meta)   kind ∈ nota | item | recurso | evento; ref = id en su tabla
    search_fts_state  (kind, ref, sig, rid, priv)      firma de lo indexado y rowid de su fila FTS

Antes de cada búsqueda se reindexa solo lo que cambió (la firma no coincide) y se quita lo que ya no existe, así no
hace falta engancharse a cada ruta que escribe. Notas cifradas o sensibles (frontmatter `sensible` o categoría
sensible de Ajustes → IA): solo título, etiquetas y área, nunca el cuerpo; sus casillas tampoco se indexan.
"""

import hashlib
import json
import re
import threading
import time
import unicodedata
from urllib.parse import quote

import frontmatter
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.contextos import matches, resolve_filter
from app.database import get_db
from app.notes_core import note_path
from core import undo
from core.logging_config import get_logger

log = get_logger("search")
router = APIRouter(prefix="/api")

MARK_OPEN, MARK_CLOSE = "\u0002", "\u0003"  # marcadores del snippet; el front los convierte en <mark>
WIKILINK_RE = re.compile(r"\[\[(.+?)\]\]")
SCOPES = {"notas", "platos", "ingredientes", "buscar"}
KINDS = ("nota", "item", "recurso", "evento")
_refresh_lock = threading.Lock()  # dos búsquedas a la vez no deben indexar dos veces lo mismo


def ensure_schema(conn) -> None:
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
        kind UNINDEXED, ref UNINDEXED, title, body, meta, tokenize='unicode61 remove_diacritics 2')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS search_fts_state (
        kind TEXT NOT NULL, ref TEXT NOT NULL, sig TEXT NOT NULL, rid INTEGER, priv INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (kind, ref))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS saved_filters (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, name TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}', created_at REAL DEFAULT (unixepoch()))""")
    # El índice anterior (solo notas, F-3): era una caché, se quita sin más
    conn.execute("DROP TABLE IF EXISTS notes_fts")
    conn.execute("DROP TABLE IF EXISTS notes_fts_state")


def _sig(*parts) -> str:
    h = hashlib.blake2b(digest_size=8)
    for p in parts:
        h.update(str(p if p is not None else "").encode())
        h.update(b"\x1f")
    return h.hexdigest()


def _cats_sensibles() -> list[str]:
    from app import llm_router  # perezoso: el router de IA no hace falta para nada más aquí

    try:
        cats = llm_router.leer_politica().get("categorias_sensibles") or []
    except Exception:  # noqa: BLE001 — sin tabla de ajustes (BD a medio crear): ninguna
        cats = []
    return [c.strip().lower() for c in cats if isinstance(c, str) and c.strip()]


def _cat_sensible(category: str | None, cats: list[str]) -> bool:
    """La misma regla que ia_notas.es_sensible para la categoría."""
    cat = str(category or "").strip().lower()
    return any(cat == c or cat.startswith(c + " - ") for c in cats)


def _fm_sensible(note_id: str) -> bool:
    try:
        with open(note_path(note_id), encoding="utf-8") as f:
            return bool(frontmatter.load(f).get("sensible"))
    except Exception:  # noqa: BLE001 — archivo ilegible: mejor no indexar su cuerpo
        return True


def invalidate(kind: str, ref) -> None:
    """Fuerza a reindexar un elemento en la próxima búsqueda (lo que cambia fuera de lo que mira la firma)."""
    with get_db() as conn:
        ensure_schema(conn)
        conn.execute("UPDATE search_fts_state SET sig='' WHERE kind=? AND ref=?", (kind, str(ref)))


def refresh_index() -> int:
    """Pone al día el índice: solo lo que cambió. Devuelve cuántos elementos tocó."""
    cats = _cats_sensibles()
    with _refresh_lock, get_db() as conn:
        ensure_schema(conn)
        state = {(r["kind"], r["ref"]): r for r in conn.execute("SELECT * FROM search_fts_state")}
        alive: set[tuple[str, str]] = set()
        touched = 0

        def put(kind, ref, sig, doc, priv=0):
            nonlocal touched
            key = (kind, ref)
            alive.add(key)
            old = state.get(key)
            if old is not None and old["sig"] == sig:
                return
            if old is not None and old["rid"] is not None:
                conn.execute("DELETE FROM search_fts WHERE rowid=?", (old["rid"],))
            rid = None
            if doc is not None:
                title, body, meta = doc()
                rid = conn.execute(
                    "INSERT INTO search_fts (kind, ref, title, body, meta) VALUES (?, ?, ?, ?, ?)",
                    (kind, ref, title or "", body or "", meta or ""),
                ).lastrowid
            conn.execute(
                "INSERT INTO search_fts_state (kind, ref, sig, rid, priv) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, ref) DO UPDATE SET sig=excluded.sig, rid=excluded.rid, priv=excluded.priv",
                (kind, ref, sig, rid, priv),
            )
            touched += 1

        # Notas: la firma es su last_modified (el indexador lo mueve con cada cambio del .md) y si su área es sensible
        private: set[str] = set()
        for n in conn.execute("SELECT id, category, encrypted, last_modified FROM notes"):
            cat_s = _cat_sensible(n["category"], cats)
            sig = _sig(n["last_modified"], n["encrypted"], cat_s)
            old = state.get(("nota", n["id"]))
            if old is not None and old["sig"] == sig:
                alive.add(("nota", n["id"]))
                if old["priv"]:
                    private.add(n["id"])
                continue
            full = conn.execute("SELECT title, tags, category, content FROM notes WHERE id=?", (n["id"],)).fetchone()
            priv = bool(n["encrypted"]) or cat_s or _fm_sensible(n["id"])
            if priv:
                private.add(n["id"])
            put(
                "nota",
                n["id"],
                sig,
                lambda full=full, priv=priv: (
                    full["title"],
                    "" if priv else full["content"],
                    " ".join(x for x in [(full["tags"] or "").replace(",", " "), full["category"] or ""] if x),
                ),
                priv=int(priv),
            )

        # Tareas, ideas y rutinas (con sus pasos y las casillas de las notas, salvo las de notas privadas)
        for r in conn.execute("SELECT id, content, details, category, note_id FROM inbox"):
            hidden = r["note_id"] in private
            sig = _sig(r["content"], r["details"], r["category"], hidden)

            def doc(r=r):
                text = re.sub(r"^---\s*", "", r["content"] or "").strip()
                first, _, rest = text.partition("\n")
                return first, "\n".join(x for x in (rest.strip(), r["details"] or "") if x), r["category"]

            put("item", str(r["id"]), sig, None if hidden else doc)

        for r in conn.execute("SELECT id, title, description, channel, category FROM resources"):
            put(
                "recurso",
                str(r["id"]),
                _sig(r["title"], r["description"], r["channel"], r["category"]),
                lambda r=r: (r["title"], r["description"], " ".join(x for x in (r["channel"], r["category"]) if x)),
            )

        for r in conn.execute("SELECT id, title, notes, location FROM events"):
            put(
                "evento",
                str(r["id"]),
                _sig(r["title"], r["notes"], r["location"]),
                lambda r=r: (r["title"], r["notes"], r["location"]),
            )

        for key in set(state) - alive:
            if state[key]["rid"] is not None:
                conn.execute("DELETE FROM search_fts WHERE rowid=?", (state[key]["rid"],))
            conn.execute("DELETE FROM search_fts_state WHERE kind=? AND ref=?", key)
            touched += 1
    return touched


def fts_query(text: str) -> str:
    """Texto libre → consulta FTS5 segura: cada palabra como prefijo, todas obligatorias.
    Las frases entre comillas se buscan literales."""
    parts = []
    for phrase, word in re.findall(r'"([^"]+)"|(\S+)', text):
        term = (phrase or word).replace('"', "").strip()
        term = re.sub(r"[^\w\s\-']", " ", term).strip()
        if not term:
            continue
        parts.append(f'"{term}"' if phrase else f'"{term}"*')
    return " AND ".join(parts)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "").lower()
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s/]+", "-", s.strip())


# ─────────────────────────────────────────────
# Búsqueda
# ─────────────────────────────────────────────

_HL = f"'{MARK_OPEN}', '{MARK_CLOSE}'"
_COMMON = f"""snippet(search_fts, 3, {_HL}, '…', 14) AS snippet, highlight(search_fts, 2, {_HL}) AS title_hl,
    bm25(search_fts, 0, 0, 8.0, 1.0, 3.0) AS rank"""
_SQL = {
    "nota": f"""SELECT n.id, n.title, n.category, n.status, n.tags, n.encrypted, n.last_modified, n.contexto, {_COMMON}
        FROM search_fts f JOIN notes n ON n.id = f.ref
        WHERE search_fts MATCH ? AND f.kind = 'nota' AND n.status != 'indice' {{extra}} ORDER BY rank LIMIT ?""",
    "item": f"""SELECT i.id, i.content, i.item_type, i.status, i.parent_id, i.note_id, i.note_task, i.due_date,
            i.contexto, i.created_at, {_COMMON}
        FROM search_fts f JOIN inbox i ON i.id = CAST(f.ref AS INTEGER)
        WHERE search_fts MATCH ? AND f.kind = 'item' ORDER BY rank LIMIT ?""",
    "recurso": f"""SELECT r.id, r.title, r.url, r.channel, r.category, r.resource_type, r.watched, r.watch_later,
            r.contexto, {_COMMON}
        FROM search_fts f JOIN resources r ON r.id = CAST(f.ref AS INTEGER)
        WHERE search_fts MATCH ? AND f.kind = 'recurso' ORDER BY rank LIMIT ?""",
    "evento": f"""SELECT e.id, e.title, e.start, e."end", e.all_day, e.location, e.repeat, e.contexto, {_COMMON}
        FROM search_fts f JOIN events e ON e.id = CAST(f.ref AS INTEGER)
        WHERE search_fts MATCH ? AND f.kind = 'evento' ORDER BY rank LIMIT ?""",
}
_KEY = {"nota": "notes", "item": "items", "recurso": "resources", "evento": "events"}
_ITEM_TYPE = {"nota": "idea", "rutina": "rutina"}


def _shape(kind: str, r: dict) -> dict:
    if kind == "nota":
        r["tags"] = [t for t in (r["tags"] or "").split(",") if t]
        r["href"] = f"/?note={quote(r['id'])}"
    elif kind == "item":
        text = re.sub(r"^---\s*", "", r.pop("content") or "").strip()
        r["text"] = text.split("\n")[0][:300]
        r["type"] = _ITEM_TYPE.get(r.pop("item_type"), "tarea")
        r["done"] = r["status"] == "processed"
        r["origin"] = "nota" if r.pop("note_task") is not None else None
        r["href"] = f"/tareas?item={r['id']}"
    elif kind == "recurso":
        r["href"] = f"/vault?recurso={r['id']}"
    elif kind == "evento":
        r["href"] = f"/calendario?dia={(r['start'] or '')[:10]}"
    return r


@router.get("/search")
def search(
    q: str = "", limit: int = 30, status: str = "", category: str = "", tipo: str = "", contexto: str | None = None
):
    """Busca en todo a la vez. `tipo` limita a uno (nota, item, recurso, evento); `status`/`category` son de notas,
    así que con ellos solo se buscan notas. `contexto` como en el resto del panel (vacío = el activo)."""
    q = q.strip()[:200]
    ctx = resolve_filter(contexto)
    query = fts_query(q)
    empty = {"q": q, "contexto": ctx, **{k: [] for k in _KEY.values()}, "total": 0, "fuera": 0}
    if not query:
        return {**empty, "marks": [MARK_OPEN, MARK_CLOSE]}
    limit = max(1, min(limit, 100))
    kinds = [tipo] if tipo in KINDS else list(KINDS)
    if status or category:
        kinds = [k for k in kinds if k == "nota"]
    refresh_index()
    out = dict(empty)
    with get_db() as conn:
        for kind in kinds:
            extra = (" AND n.status = ?" if status else "") + (" AND n.category LIKE ?" if category else "")
            sql = _SQL[kind].replace("{extra}", extra)
            params = [query] + ([status] if status else []) + ([f"{category}%"] if category else [])
            # Se piden de más para poder quitar los de otro contexto sin quedarse cortos
            params.append(limit * 4 if ctx != "todo" else limit)
            try:
                rows = [dict(r) for r in conn.execute(sql, params)]
            except Exception as e:  # consulta que FTS no entiende: se trata como vacía
                log.warning("Búsqueda no válida %r: %s", q, e)
                rows = []
            keep = [r for r in rows if matches(r, ctx)]
            out["fuera"] += len(rows) - len(keep)
            keep = keep[:limit]
            for r in keep:
                r.pop("rank", None)
            out[_KEY[kind]] = [_shape(kind, r) for r in keep]
    out["total"] = sum(len(out[k]) for k in _KEY.values())
    out["marks"] = [MARK_OPEN, MARK_CLOSE]
    return out


# ─────────────────────────────────────────────
# Enlaces entrantes
# ─────────────────────────────────────────────


@router.get("/notes/{note_id}/backlinks")
def backlinks(note_id: str):
    note_path(note_id)
    with get_db() as conn:
        me = conn.execute("SELECT id, title FROM notes WHERE id=?", (note_id,)).fetchone()
        if not me:
            raise HTTPException(status_code=404, detail="Nota no encontrada")
        # Los índices automáticos enlazan a todas las notas de su área: no aportan
        others = conn.execute(
            "SELECT id, title, category, content FROM notes WHERE id != ? AND encrypted=0 AND status != 'indice'",
            (note_id,),
        ).fetchall()
    targets = {_norm(me["id"]), _norm(me["title"])}
    out = []
    for n in others:
        hits = []
        for line in (n["content"] or "").splitlines():
            if any(_norm(m) in targets for m in WIKILINK_RE.findall(line)):
                hits.append(line.strip()[:240])
        if hits:
            out.append(
                {"id": n["id"], "title": n["title"], "category": n["category"], "context": hits[:3], "count": len(hits)}
            )
    out.sort(key=lambda x: x["title"].lower())
    return {"backlinks": out}


# ─────────────────────────────────────────────
# Filtros guardados
# ─────────────────────────────────────────────


class SavedFilterIn(BaseModel):
    scope: str = Field(max_length=30)
    name: str = Field(min_length=1, max_length=80)
    params: dict = Field(default_factory=dict)


@router.get("/saved-filters")
def list_saved_filters(scope: str):
    with get_db() as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, scope, name, params FROM saved_filters WHERE scope=? ORDER BY name", (scope,)
        ).fetchall()
    return {"filters": [{**dict(r), "params": json.loads(r["params"])} for r in rows]}


@router.post("/saved-filters")
def create_saved_filter(data: SavedFilterIn):
    if data.scope not in SCOPES:
        raise HTTPException(status_code=422, detail="Ámbito no válido")
    raw = json.dumps(data.params, ensure_ascii=False)
    if len(raw) > 4000:
        raise HTTPException(status_code=422, detail="Filtro demasiado grande")
    with get_db() as conn:
        ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO saved_filters (scope, name, params, created_at) VALUES (?, ?, ?, ?)",
            (data.scope, data.name.strip(), raw, time.time()),
        )
    return {"status": "success", "id": cur.lastrowid}


@router.delete("/saved-filters/{filter_id}")
def delete_saved_filter(filter_id: int):
    with get_db() as conn:
        ensure_schema(conn)
        rows = undo.select(conn, "saved_filters", "id=?", (filter_id,))
        token = undo.save_rows(conn, "rows.filtro", [("saved_filters", rows)], title=rows[0]["name"]) if rows else None
        conn.execute("DELETE FROM saved_filters WHERE id=?", (filter_id,))
    return {"status": "success", "undo_token": token, "undo_db": "brain"}
