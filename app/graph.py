"""API del grafo: nodos y enlaces de las notas (tags, cifrado, repaso y flashcards pendientes) y su disposición."""
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.database import get_db
from app.notes_core import split_category_path

router = APIRouter()


class NodePosition(BaseModel):
    id: str = Field(max_length=400)
    x: float
    y: float


class EdgeData(BaseModel):
    source: str = Field(max_length=400)
    target: str = Field(max_length=400)


class GraphLayout(BaseModel):
    nodes: list[NodePosition] = Field(max_length=20_000)
    edges: list[EdgeData] = Field(default_factory=list, max_length=50_000)


@router.get("/api/graph")
def get_graph():
    with get_db() as conn:
        notes = conn.execute(
            "SELECT id, title, category, status, tags, encrypted, last_reviewed FROM notes"
        ).fetchall()
        positions = {row['id']: {"x": row['x'], "y": row['y']} for row in conn.execute("SELECT id, x, y FROM graph_nodes").fetchall()}

        due_counts = {}
        for row in conn.execute(
            "SELECT note_id, COUNT(*) as n FROM flashcards WHERE next_review <= ? GROUP BY note_id",
            (time.time(),)
        ).fetchall():
            due_counts[row['note_id']] = row['n']

        nodes = []
        edges = []
        category_ids = {}

        def get_or_create_category(parts):
            path_key = "/".join(p.lower() for p in parts)
            if path_key in category_ids:
                return category_ids[path_key]
            cat_id = f"cat:{path_key}"
            depth = len(parts) - 1
            pos = positions.get(cat_id, {})
            nodes.append({
                "id": cat_id, "label": parts[-1], "type": "category", "depth": depth,
                "group": parts[0], "x": pos.get("x"), "y": pos.get("y"),
            })
            category_ids[path_key] = cat_id
            if len(parts) > 1:
                parent_id = get_or_create_category(parts[:-1])
                edges.append({"id": f"cat-edge-{parent_id}-{cat_id}", "from": parent_id, "to": cat_id, "type": "category"})
            return cat_id

        for note in notes:
            pos = positions.get(note['id'], {})
            cat_raw = note['category'] or "Sin categoría"
            parts = [p.strip() for p in split_category_path(cat_raw) if p.strip()] or ["Sin categoría"]
            leaf_cat_id = get_or_create_category(parts)
            nodes.append({
                "id": note['id'], "label": note['title'], "type": "note", "group": parts[0],
                "status": note['status'],
                "tags": note['tags'] or "",
                "encrypted": bool(note['encrypted']),
                "last_reviewed": note['last_reviewed'] or 0,
                "due_flashcards": due_counts.get(note['id'], 0),
                "x": pos.get("x"), "y": pos.get("y"),
            })
            edges.append({"id": f"cat-note-{leaf_cat_id}-{note['id']}", "from": leaf_cat_id, "to": note['id'], "type": "category"})

        note_ids = {n["id"] for n in nodes if n.get("type") == "note"}
        raw_edges = conn.execute("SELECT id, source, target, type FROM graph_edges").fetchall()
        for row in raw_edges:
            if row['source'] in note_ids and row['target'] in note_ids:
                edges.append({"id": row['id'], "from": row['source'], "to": row['target'], "type": row['type']})

    return {"nodes": nodes, "edges": edges}


@router.post("/api/graph/layout")
def save_graph_layout(layout: GraphLayout):
    with get_db() as conn:
        cursor = conn.cursor()
        for node in layout.nodes:
            cursor.execute('''
                INSERT OR REPLACE INTO graph_nodes (id, x, y) VALUES (?, ?, ?)
            ''', (node.id, node.x, node.y))
        conn.commit()
    return {"status": "success", "saved": len(layout.nodes)}


@router.post("/api/graph/edges")
def add_manual_edge(edge: EdgeData):
    with get_db() as conn:
        conn.execute('''
            INSERT OR IGNORE INTO graph_edges (source, target, type) VALUES (?, ?, 'manual')
        ''', (edge.source, edge.target))
    return {"status": "success"}


@router.delete("/api/graph/edges")
def delete_edge(edge: EdgeData):
    with get_db() as conn:
        conn.execute("DELETE FROM graph_edges WHERE source = ? AND target = ?", (edge.source, edge.target))
        conn.commit()
    return {"status": "success"}
