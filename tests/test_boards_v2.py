"""Ronda 2 · fase 3: tableros en formato 2, conversión del antiguo, guardados viejos bloqueados, plantillas."""
import json
import sqlite3

from app.board_convert import convert
from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert

LEGACY = {"version": "5.3.0", "objects": [
    {"type": "group", "originX": "center", "originY": "center", "left": 100, "top": 100, "width": 122, "height": 72,
     "scaleX": 1, "scaleY": 1, "customType": "shape", "linkId": "obj_a",
     "objects": [{"type": "rect", "fill": "#818cf822", "stroke": "#818cf8", "width": 120, "height": 70},
                 {"type": "i-text", "text": "Sol", "fill": "#818cf8", "fontSize": 24}]},
    {"type": "rect", "originX": "center", "originY": "center", "left": 400, "top": 100, "width": 120, "height": 70,
     "scaleX": 2, "scaleY": 1, "customType": "shape", "linkId": "obj_b", "fill": "#818cf822", "stroke": "#818cf8"},
    {"type": "group", "originX": "left", "originY": "top", "left": 50, "top": 300, "width": 201.5, "height": 91.5, "scaleX": 1, "scaleY": 1,
     "objects": [{"type": "rect", "fill": "#f59e0b22", "stroke": "#f59e0b", "width": 200, "height": 90},
                 {"type": "textbox", "text": "Comprar", "fill": "#ededee", "fontSize": 14}]},
    {"type": "line", "originX": "left", "originY": "top", "left": 0, "top": 0, "width": 10, "height": 10, "stroke": "#818cf8",
     "strokeWidth": 3, "customType": "arrow", "connId": "c1", "startObjId": "obj_a", "endObjId": "obj_b", "x1": 0, "x2": 1, "y1": 0, "y2": 1},
    {"type": "triangle", "customType": "arrowhead", "connId": "c1"},
    {"type": "line", "customType": "arrow", "connId": "c2", "startObjId": "obj_a", "endObjId": "obj_a", "x1": 0, "x2": 0, "y1": 0, "y2": 0},
    {"type": "triangle", "customType": "arrowhead", "connId": "huerfana"},
]}


def test_conversion_del_formato_antiguo():
    doc, rep = convert(LEGACY)
    assert doc["format"] == 2 and rep["nodos"] == 3 and rep["flechas"] == 1
    sol = next(n for n in doc["nodes"] if n.get("text") == "Sol")
    assert (sol["x"], sol["y"], sol["w"], sol["h"]) == (39.0, 64.0, 122.0, 72.0)  # centro → esquina
    ancha = next(n for n in doc["nodes"] if n["kind"] == "rect" and not n["text"])
    assert ancha["w"] == 240.0  # escala aplicada al tamaño
    tarjeta = next(n for n in doc["nodes"] if n["kind"] == "inbox")
    assert tarjeta["text"] == "Comprar" and tarjeta["itemType"] == "nota"
    e = doc["edges"][0]
    assert e["from"] == sol["id"] and e["to"] == ancha["id"] and e["head"] == "arrow"
    assert any("origen igual" in d for d in rep["descartados"]) and any("huerfana" in d for d in rep["descartados"])


def test_lectura_convierte_y_guardado_viejo_se_rechaza(client):
    bid = client.post("/api/boards", json={"name": "Antiguo"}).json()["id"]
    from app.database import get_db
    with get_db() as conn:  # simula un tablero guardado por la versión antigua
        conn.execute("INSERT OR REPLACE INTO board_canvas (board_id, data) VALUES (?, ?)", (bid, json.dumps(LEGACY)))
    data = json.loads(client.get(f"/api/boards/{bid}").json()["data"])
    assert data["format"] == 2 and len(data["nodes"]) == 3
    with get_db() as conn:
        assert json.loads(conn.execute("SELECT data FROM board_canvas_legacy WHERE board_id=?", (bid,)).fetchone()[0]) == LEGACY
    r = client.post(f"/api/boards/{bid}/canvas", json={"data": json.dumps({"objects": []})})
    assert r.status_code == 409
    assert client.post(f"/api/boards/{bid}/canvas", json={"data": json.dumps({"format": 2, "nodes": [], "edges": [], "strokes": []})}).status_code == 200


def test_plantillas(client):
    payload = {"nodes": [{"id": "n1", "kind": "rect", "x": 0, "y": 0, "w": 100, "h": 50, "text": "A"}], "edges": [], "strokes": []}
    tid = client.post("/api/board-templates", json={"name": "Mía", "data": json.dumps(payload)}).json()["id"]
    assert any(t["id"] == tid for t in client.get("/api/board-templates").json()["templates"])
    assert client.post("/api/board-templates", json={"name": "Mala", "data": "[]"}).status_code == 422
    client.delete(f"/api/board-templates/{tid}")
    assert not any(t["id"] == tid for t in client.get("/api/board-templates").json()["templates"])


def test_migracion_tableros_arriba_y_abajo(tmp_path):
    conn = sqlite3.connect(tmp_path / "b.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, parent_id INTEGER, sort_order REAL)")
    conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, category TEXT, resource_type TEXT, channel TEXT, title TEXT, added_at REAL)")
    conn.execute("CREATE TABLE board_canvas (board_id INTEGER PRIMARY KEY, data TEXT)")
    raw = json.dumps(LEGACY)
    conn.execute("INSERT INTO board_canvas VALUES (1, ?), (2, '{}')", (raw,))
    apply_pending(conn, MIGRATIONS)
    assert json.loads(conn.execute("SELECT data FROM board_canvas WHERE board_id=1").fetchone()[0])["format"] == 2
    assert conn.execute("SELECT data FROM board_canvas WHERE board_id=2").fetchone()[0] == "{}"
    revert(conn, MIGRATIONS, 3)
    assert conn.execute("SELECT data FROM board_canvas WHERE board_id=1").fetchone()[0] == raw
