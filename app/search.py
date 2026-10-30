"""
Búsqueda de texto completo (FTS5), enlaces entrantes (backlinks) y filtros guardados.

El índice FTS es una caché de la caché: `notes_fts` + `notes_fts_state`
(id, last_modified). Antes de cada búsqueda se ponen al día solo las notas
cuyo last_modified cambió, así no hace falta engancharse a cada ruta que
escribe notas. Las notas cifradas solo se indexan por título.
"""
import json
import re
import time
import unicodedata

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db
from app.notes_core import note_path
from core.logging_config import get_logger

log = get_logger("search")
router = APIRouter(prefix="/api")

MARK_OPEN, MARK_CLOSE = "\u0002", "\u0003"  # marcadores del snippet; el front los convierte en <mark>
WIKILINK_RE = re.compile(r"\[\[(.+?)\]\]")
SCOPES = {"notas", "platos", "ingredientes", "buscar"}


def ensure_schema(conn) -> None:
    conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
        id UNINDEXED, title, body, tags, category, tokenize='unicode61 remove_diacritics 2')""")
    conn.execute("CREATE TABLE IF NOT EXISTS notes_fts_state (id TEXT PRIMARY KEY, last_modified REAL)")
    conn.execute("""CREATE TABLE IF NOT EXISTS saved_filters (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, name TEXT NOT NULL,
        params TEXT NOT NULL DEFAULT '{}', created_at REAL DEFAULT (unixepoch()))""")


def refresh_index() -> int:
    """Reindexa en FTS solo lo que cambió. Devuelve cuántas notas tocó."""
    touched = 0
    with get_db() as conn:
        ensure_schema(conn)
        state = {r["id"]: r["last_modified"] for r in conn.execute("SELECT id, last_modified FROM notes_fts_state")}
        notes = conn.execute("SELECT id, title, category, tags, content, encrypted, last_modified FROM notes").fetchall()
        alive = set()
        for n in notes:
            alive.add(n["id"])
            if state.get(n["id"]) == n["last_modified"] and n["id"] in state:
                continue
            conn.execute("DELETE FROM notes_fts WHERE id=?", (n["id"],))
            conn.execute("INSERT INTO notes_fts (id, title, body, tags, category) VALUES (?, ?, ?, ?, ?)",
                         (n["id"], n["title"], "" if n["encrypted"] else n["content"], (n["tags"] or "").replace(",", " "), n["category"]))
            conn.execute("INSERT OR REPLACE INTO notes_fts_state (id, last_modified) VALUES (?, ?)", (n["id"], n["last_modified"]))
            touched += 1
        for gone in set(state) - alive:
            conn.execute("DELETE FROM notes_fts WHERE id=?", (gone,))
            conn.execute("DELETE FROM notes_fts_state WHERE id=?", (gone,))
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

@router.get("/search")
def search(q: str = "", limit: int = 30, status: str = "", category: str = ""):
    q = q.strip()[:200]
    query = fts_query(q)
    if not query:
        return {"q": q, "notes": [], "inbox": [], "total": 0}
    limit = max(1, min(limit, 100))
    refresh_index()
    sql = f"""
        SELECT f.id, n.title, n.category, n.status, n.tags, n.encrypted, n.last_modified,
               snippet(notes_fts, 2, '{MARK_OPEN}', '{MARK_CLOSE}', '…', 14) AS snippet,
               highlight(notes_fts, 1, '{MARK_OPEN}', '{MARK_CLOSE}') AS title_hl,
               bm25(notes_fts, 0, 8.0, 1.0, 4.0, 2.0) AS rank
        FROM notes_fts f JOIN notes n ON n.id = f.id
        WHERE notes_fts MATCH ? AND n.status != 'indice' {"AND n.status = ?" if status else ""} {"AND n.category LIKE ?" if category else ""}
        ORDER BY rank LIMIT ?"""
    params = [query] + ([status] if status else []) + ([f"{category}%"] if category else []) + [limit]
    with get_db() as conn:
        try:
            notes = [dict(r) for r in conn.execute(sql, params)]
        except Exception as e:  # consulta que FTS no entiende: se trata como vacía
            log.warning("Búsqueda no válida %r: %s", q, e)
            notes = []
        words = [w for w in re.findall(r"\w+", q) if len(w) > 1][:5]
        inbox = []
        if words:
            where = " AND ".join("content LIKE ?" for _ in words)
            inbox = [dict(r) for r in conn.execute(
                f"SELECT id, content, item_type, status, created_at FROM inbox WHERE note_task IS NULL AND {where} ORDER BY created_at DESC LIMIT 10",
                [f"%{w}%" for w in words])]
    for n in notes:
        n["tags"] = [t for t in (n["tags"] or "").split(",") if t]
        n.pop("rank", None)
    return {"q": q, "notes": notes, "inbox": inbox, "total": len(notes), "marks": [MARK_OPEN, MARK_CLOSE]}


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
        others = conn.execute("SELECT id, title, category, content FROM notes WHERE id != ? AND encrypted=0 AND status != 'indice'",
                              (note_id,)).fetchall()
    targets = {_norm(me["id"]), _norm(me["title"])}
    out = []
    for n in others:
        hits = []
        for line in (n["content"] or "").splitlines():
            if any(_norm(m) in targets for m in WIKILINK_RE.findall(line)):
                hits.append(line.strip()[:240])
        if hits:
            out.append({"id": n["id"], "title": n["title"], "category": n["category"], "context": hits[:3], "count": len(hits)})
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
        rows = conn.execute("SELECT id, scope, name, params FROM saved_filters WHERE scope=? ORDER BY name", (scope,)).fetchall()
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
        cur = conn.execute("INSERT INTO saved_filters (scope, name, params, created_at) VALUES (?, ?, ?, ?)",
                           (data.scope, data.name.strip(), raw, time.time()))
    return {"status": "success", "id": cur.lastrowid}


@router.delete("/saved-filters/{filter_id}")
def delete_saved_filter(filter_id: int):
    with get_db() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM saved_filters WHERE id=?", (filter_id,))
    return {"status": "success"}
