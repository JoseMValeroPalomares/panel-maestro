"""
Enlaces entre tareas/ideas/rutinas y notas.

En la nota, el enlace es un marcador `[[tarea:123]]` (o `[[idea:123]]`,
`[[rutina:123]]`; el prefijo es solo para leerlo, manda el número). Se pinta como
una ficha con el texto actual del elemento y lleva a él con un clic.
La tabla `item_links (item_id, note_id)` es el índice de esos marcadores y se rehace
desde el .md cada vez que se indexa o guarda la nota (sync_note_links, llamada desde
note_tasks.sync_note_items): igual que con las casillas, el .md manda y la BD nunca
se desincroniza. Enlazar o desenlazar desde una tarea escribe (o quita) el marcador
en la nota y la vuelve a indexar.
"""
import os
import re
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_db

TOKEN_RE = re.compile(r"\[\[(tarea|idea|rutina|item):(\d+)\]\]")
LINK_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+)?(?:🔗\s*)?(?:Enlazad[ao]s?:\s*)?((?:\[\[(?:tarea|idea|rutina|item):\d+\]\]\s*)+)$")

router = APIRouter(prefix="/api")


def linked_ids(content: str | None) -> list[int]:
    seen, out = set(), []
    for m in TOKEN_RE.finditer(content or ""):
        i = int(m.group(2))
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def sync_note_links(conn: sqlite3.Connection, note_id: str, content: str | None) -> None:
    """Deja en item_links exactamente los marcadores que hay en la nota (content=None: ninguno)."""
    ids = linked_ids(content)
    existing = {r["id"] for r in conn.execute(
        f"SELECT id FROM inbox WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    if existing:
        conn.execute(f"DELETE FROM item_links WHERE note_id=? AND item_id NOT IN ({','.join('?' * len(existing))})",
                     (note_id, *existing))
    else:
        conn.execute("DELETE FROM item_links WHERE note_id=?", (note_id,))
    for i in existing:
        conn.execute("INSERT OR IGNORE INTO item_links (item_id, note_id, created_at) VALUES (?, ?, unixepoch())", (i, note_id))


def rebuild_all(conn: sqlite3.Connection) -> None:
    """Todas las notas (al arrancar o tras recuperar elementos de la papelera)."""
    for r in conn.execute("SELECT id, content, encrypted, status FROM notes").fetchall():
        ok = not r["encrypted"] and r["status"] != "indice"
        sync_note_links(conn, r["id"], r["content"] if ok else None)


def links_by_item(conn) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in conn.execute("""SELECT l.item_id, l.note_id, n.title FROM item_links l
                             LEFT JOIN notes n ON n.id = l.note_id ORDER BY n.title"""):
        out.setdefault(r["item_id"], []).append({"note_id": r["note_id"], "title": r["title"] or r["note_id"]})
    return out


# ─────────────────────────────────────────────
# Escribir y quitar el marcador en el .md
# ─────────────────────────────────────────────

def _token(item_row) -> str:
    kind = {"nota": "idea", "rutina": "rutina"}.get(item_row["item_type"], "tarea")
    return f"[[{kind}:{item_row['id']}]]"


def _write_note(note_id: str, fn) -> None:
    from app.indexer import sync_notes_to_db
    from app.items import _note_file
    from app.note_tasks import FRONTMATTER_RE
    from app.versions import snapshot as snapshot_version
    path = _note_file(note_id)  # 404 si no existe; 422 si está cifrada o es índice
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    m = FRONTMATTER_RE.match(raw)
    head = m.group(0) if m else ""
    body = raw[len(head):]
    new_body = fn(body)
    if new_body == body:
        return
    snapshot_version(note_id)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(head + new_body)
    os.utime(path)
    sync_notes_to_db()
    with get_db() as conn:  # por si la caché no vio el cambio (misma marca de tiempo)
        sync_note_links(conn, note_id, new_body)


def add_link(item_id: int, note_id: str) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id, item_type FROM inbox WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")
    token = _token(row)

    def add(body: str) -> str:
        if item_id in linked_ids(body):
            return body
        eol = "\r\n" if "\r\n" in body else "\n"
        return body.rstrip("\r\n") + f"{eol}{eol}🔗 {token}{eol}"
    _write_note(note_id, add)


def remove_link(item_id: int, note_id: str) -> None:
    pattern = re.compile(r"\[\[(?:tarea|idea|rutina|item):%d\]\]" % item_id)

    def drop(body: str) -> str:
        out = []
        for line in body.splitlines(keepends=True):
            if not pattern.search(line):
                out.append(line)
                continue
            if LINK_LINE_RE.match(line.rstrip("\r\n")) and len(TOKEN_RE.findall(line)) == 1:
                continue  # la línea solo era el enlace: fuera entera
            out.append(re.sub(r"\s*" + pattern.pattern, "", line.rstrip("\r\n")) + line[len(line.rstrip("\r\n")):])
        text = "".join(out)
        return re.sub(r"(\r?\n){3,}$", lambda mm: mm.group(1), text)
    _write_note(note_id, drop)


# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────

class LinkIn(BaseModel):
    note_id: str = Field(min_length=1, max_length=200)


@router.post("/items/{item_id}/links")
def api_add_link(item_id: int, data: LinkIn):
    add_link(item_id, data.note_id)
    return {"status": "success"}


@router.delete("/items/{item_id}/links/{note_id}")
def api_remove_link(item_id: int, note_id: str):
    remove_link(item_id, note_id)
    return {"status": "success"}


@router.get("/notes/{note_id}/links")
def api_note_links(note_id: str):
    with get_db() as conn:
        rows = conn.execute("""SELECT i.id, i.content, i.item_type, i.status, i.due_date FROM item_links l
                               JOIN inbox i ON i.id = l.item_id WHERE l.note_id=? ORDER BY i.status, i.id""", (note_id,)).fetchall()
    from app.items import clean_text, item_type
    return {"items": [{"id": r["id"], "text": clean_text(r["content"]), "type": item_type(r),
                       "done": r["status"] == "processed", "due_date": r["due_date"]} for r in rows]}
