"""API del grafo: nodos y enlaces de las notas (tags, cifrado, repaso y flashcards pendientes) y su disposición."""
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import graph_layout
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
    fijados: list[str] = Field(default_factory=list, max_length=20_000)  # nodos movidos a mano: «auto» puede respetarlos
    edges: list[EdgeData] = Field(default_factory=list, max_length=50_000)


@router.get("/api/graph")
def get_graph():
    with get_db() as conn:
        notes = conn.execute(
            "SELECT id, title, category, status, tags, encrypted, last_reviewed FROM notes"
        ).fetchall()
        positions = {row['id']: {"x": row['x'], "y": row['y'], "fijado": bool(row['fijado'])} for row in conn.execute("SELECT id, x, y, fijado FROM graph_nodes").fetchall()}
        hay_deshacer = conn.execute("SELECT 1 FROM graph_prev WHERE id=1").fetchone() is not None

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
                "group": parts[0], "x": pos.get("x"), "y": pos.get("y"), "fijado": pos.get("fijado", False),
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
                "x": pos.get("x"), "y": pos.get("y"), "fijado": pos.get("fijado", False),
            })
            edges.append({"id": f"cat-note-{leaf_cat_id}-{note['id']}", "from": leaf_cat_id, "to": note['id'], "type": "category"})

        note_ids = {n["id"] for n in nodes if n.get("type") == "note"}
        raw_edges = conn.execute("SELECT id, source, target, type FROM graph_edges").fetchall()
        for row in raw_edges:
            if row['source'] in note_ids and row['target'] in note_ids:
                edges.append({"id": row['id'], "from": row['source'], "to": row['target'], "type": row['type']})

    return {"nodes": nodes, "edges": edges, "hay_deshacer": hay_deshacer}


@router.post("/api/graph/layout")
def save_graph_layout(layout: GraphLayout):
    with get_db() as conn:
        # UPSERT (no REPLACE): conserva la marca de «fijado» de los nodos que no se tocan
        conn.executemany("""INSERT INTO graph_nodes (id, x, y) VALUES (?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET x=excluded.x, y=excluded.y""", [(n.id, n.x, n.y) for n in layout.nodes])
        if layout.fijados:
            conn.executemany("UPDATE graph_nodes SET fijado=1 WHERE id=?", [(i,) for i in layout.fijados])
    return {"status": "success", "saved": len(layout.nodes)}


class FijarIn(BaseModel):
    id: str = Field(max_length=400)
    fijado: bool


@router.post("/api/graph/fijar")
def fijar_nodo(data: FijarIn):
    with get_db() as conn:
        conn.execute("""INSERT INTO graph_nodes (id, x, y, fijado) VALUES (?, NULL, NULL, ?)
                        ON CONFLICT(id) DO UPDATE SET fijado=excluded.fijado""", (data.id, int(data.fijado)))
    return {"status": "success"}


class AutoIn(BaseModel):
    respetar_fijados: bool = False


@router.post("/api/graph/auto")
def generar_automatico(data: AutoIn):
    """Recoloca TODOS los nodos con el diseño radial, guarda las posiciones y deja copia de las anteriores para deshacer."""
    grafo = get_graph()
    with get_db() as conn:
        previo = [dict(r) for r in conn.execute("SELECT id, x, y, fijado FROM graph_nodes")]
    fijados = {r["id"]: (r["x"], r["y"]) for r in previo if r["fijado"] and r["x"] is not None and r["y"] is not None} if data.respetar_fijados else {}
    pos = graph_layout.disenar(grafo["nodes"], grafo["edges"], fijados)
    with get_db() as conn:
        conn.execute("INSERT INTO graph_prev (id, datos, at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET datos=excluded.datos, at=excluded.at",
                     (json.dumps(previo), time.time()))
        if not data.respetar_fijados:
            conn.execute("UPDATE graph_nodes SET fijado=0")  # el nuevo diseño anula las posiciones manuales
        conn.executemany("""INSERT INTO graph_nodes (id, x, y) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET x=excluded.x, y=excluded.y""",
                         [(i, p[0], p[1]) for i, p in pos.items()])
    return {"posiciones": {i: {"x": p[0], "y": p[1]} for i, p in pos.items()}, "total": len(pos), "fijados": len(fijados), "hay_deshacer": True}


@router.post("/api/graph/auto/deshacer")
def deshacer_automatico():
    with get_db() as conn:
        fila = conn.execute("SELECT datos FROM graph_prev WHERE id=1").fetchone()
        if not fila:
            raise HTTPException(404, "No hay ningún recolocado que deshacer")
        previo = json.loads(fila["datos"])
        conn.execute("DELETE FROM graph_nodes")
        conn.executemany("INSERT INTO graph_nodes (id, x, y, fijado) VALUES (?, ?, ?, ?)", [(r["id"], r["x"], r["y"], r["fijado"]) for r in previo])
        conn.execute("DELETE FROM graph_prev WHERE id=1")
    return {"status": "success", "restauradas": len(previo)}


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
