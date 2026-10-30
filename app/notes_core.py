"""
Utilidades de las notas sin rutas: límites, identificadores y rutas de archivo, categorías, flashcards del texto e
índices automáticos por área. No depende de ningún router: lo importan todos los que tocan notas.
"""
import os
import re
import time
from datetime import datetime, timezone

import frontmatter
from fastapi import HTTPException

from app.database import get_db
from app.indexer import NOTES_DIR

VALID_STATUSES = {"por-escribir", "en-desarrollo", "consolidado", "indice"}
VALID_ITEM_TYPES = {"nota", "tarea"}
PRIORITIES = ("alta", "media", "baja")

# Límites generosos pero finitos: el contenido cifrado ocupa ~1.4x el original.
MAX_NOTE_CONTENT = 5_000_000
MAX_TITLE = 300
MAX_TAGS = 50


def extract_wiki_links(content: str) -> list[str]:
    # [[tarea:N]] / [[idea:N]] enlazan elementos de la lista, no notas (app/links.py)
    raw = [r for r in re.findall(r'\[\[(.+?)\]\]', content) if not re.fullmatch(r'(?:tarea|idea|rutina|item):\d+', r)]
    return [r.lower().replace(' ', '-').replace('/', '-') for r in raw]

def split_category_path(cat_raw: str) -> list[str]:
    """
    Divide una categoría en partes jerárquicas, soportando tanto el
    formato antiguo con flecha ('Fisica->Electricidad') como el
    formato recomendado con guion y espacios ('Fisica - Electricidad').
    Evita el bug de partir por cualquier '-' suelto (p.ej. en 'Ley-de-Ohm').
    """

    if not cat_raw or not cat_raw.strip():
        return ["Sin categoría"]
    normalized = cat_raw.replace('->', ' - ')
    parts = [p.strip() for p in re.split(r'\s+-\s+', normalized) if p.strip()]
    return parts or ["Sin categoría"]


def normalize_status(status: str) -> str:
    return status if status in VALID_STATUSES else "por-escribir"


def normalize_item_type(item_type: str) -> str:
    return item_type if item_type in VALID_ITEM_TYPES else "nota"


def slugify(name: str) -> str:
    # Nunca debe producir separadores de ruta: el resultado se usa como nombre de archivo.
    slug = re.sub(r"[\\/\x00]+", "-", name.lower().strip()).replace(' ', '-')
    return re.sub(r"\.{2,}", "-", slug).strip(".") or "sin-nombre"


NOTE_ID_RE = re.compile(r"^[^\W_][\w\-]{0,199}$")


def note_path(note_id: str) -> str:
    """Ruta absoluta del .md de una nota, garantizando que queda DENTRO de
    NOTES_DIR (sin '..', separadores ni enlaces simbólicos que escapen)."""
    if not isinstance(note_id, str) or not NOTE_ID_RE.match(note_id):
        raise HTTPException(status_code=400, detail="Identificador de nota no válido")
    base = os.path.realpath(NOTES_DIR)
    candidate = os.path.realpath(os.path.join(base, f"{note_id}.md"))
    if os.path.dirname(candidate) != base:
        raise HTTPException(status_code=400, detail="Identificador de nota no válido")
    return candidate


def today_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d')


def sync_flashcards(note_id: str, content: str):
    """Extrae líneas 'pregunta >> respuesta' del contenido y sincroniza la
    tabla flashcards: crea las nuevas, borra las que ya no existen en el texto."""
    pattern = re.compile(r'^\s*(.+?)\s*>>\s*(.+?)\s*$', re.MULTILINE)
    found = [(q.strip(), a.strip()) for q, a in pattern.findall(content) if q.strip() and a.strip()]

    with get_db() as conn:
        existing = conn.execute("SELECT id, question FROM flashcards WHERE note_id=?", (note_id,)).fetchall()
        existing_questions = {r['question']: r['id'] for r in existing}
        found_questions = {q for q, _ in found}

        for old_q, old_id in existing_questions.items():
            if old_q not in found_questions:
                conn.execute("DELETE FROM flashcards WHERE id=?", (old_id,))

        for q, a in found:
            if q in existing_questions:
                conn.execute("UPDATE flashcards SET answer=? WHERE id=?", (a, existing_questions[q]))
            else:
                conn.execute('''
                    INSERT INTO flashcards (note_id, question, answer, next_review)
                    VALUES (?, ?, ?, ?)
                ''', (note_id, q, a, time.time()))
        conn.commit()


# ─────────────────────────────────────────────
# Índices automáticos: una nota «Índice <área>» con el árbol de sus notas
# ─────────────────────────────────────────────

AUTO_START = "<!-- AUTO:START -->"
AUTO_END = "<!-- AUTO:END -->"

STATUS_ICONS = {
    "por-escribir": "🌱",
    "en-desarrollo": "🚧",
    "consolidado": "✅",
}


def build_category_tree(notes):
    tree = {}
    for n in notes:
        parts = split_category_path(n["category"])
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {"_notes": [], "_children": {}})["_children"]
        leaf = node.setdefault(parts[-1], {"_notes": [], "_children": {}})
        leaf["_notes"].append(n)
    return tree


def render_tree(tree, depth=0):
    lines = []
    indent = "  " * depth
    for name in sorted(tree.keys()):
        content = tree[name]
        lines.append(f"{indent}- **{name}**")
        for note in sorted(content["_notes"], key=lambda n: n["title"] or ""):
            icon = STATUS_ICONS.get(note["status"], "")
            lines.append(f"{indent}  - {icon} [[{note['title']}]]")
        lines.extend(render_tree(content["_children"], depth + 1))
    return lines


def index_note_id(area: str) -> str:
    return "indice-" + re.sub(r"[^\w\-]+", "-", slugify(area)).strip("-_")


def update_index_for_area(area: str):
    if not area or area == "Sin categoría":
        return

    with get_db() as conn:
        rows = conn.execute(
            "SELECT title, category, status FROM notes WHERE status != 'indice' AND encrypted = 0"
        ).fetchall()

    area_notes = [r for r in rows if split_category_path(r["category"])[0] == area]
    if not area_notes:
        return

    auto_block = AUTO_START + "\n" + "\n".join(render_tree(build_category_tree(area_notes))) + "\n" + AUTO_END

    note_id = index_note_id(area)
    filepath = note_path(note_id)

    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
    else:
        post = frontmatter.Post("")
        post["title"] = f"Índice {area}"
        post["category"] = area
        post["category_id"] = None
        post["encrypted"] = False

    post["status"] = "indice"

    content = post.content or ""
    if AUTO_START in content and AUTO_END in content:
        content = re.sub(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END),
                          auto_block, content, flags=re.DOTALL)
    else:
        content = (content.rstrip() + "\n\n" + auto_block) if content.strip() else auto_block
    post.content = content

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    with get_db() as conn:
        last_modified = os.path.getmtime(filepath)
        conn.execute('''
            INSERT OR REPLACE INTO notes (id, title, category, category_id, tags, content, status, last_modified, encrypted, last_reviewed)
            VALUES (?, ?, ?, ?, '', ?, 'indice', ?, 0, COALESCE((SELECT last_reviewed FROM notes WHERE id=?), 0))
        ''', (note_id, post["title"], area, post.get("category_id"), content, last_modified, note_id))
        conn.commit()
