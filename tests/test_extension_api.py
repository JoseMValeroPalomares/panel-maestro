"""Ronda 2 · fase 5: lo que usa la extensión de Firefox (token Bearer, estado, Inbox con prioridad y categoría)."""
import sqlite3

from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert
from tests.conftest import TEST_API_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_API_TOKEN}", "Origin": "moz-extension://1234-abcd"}


def test_estado_exige_token_y_cuenta_pendientes(anon):
    assert anon.get("/api/ext/status").status_code == 401
    assert anon.get("/api/ext/status", headers={"Authorization": "Bearer malo"}).status_code == 401
    r = anon.get("/api/ext/status", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True and isinstance(r.json()["pending"], int)


def test_captura_con_prioridad_y_categoria_desde_otro_origen(anon):
    antes = anon.get("/api/ext/status", headers=AUTH).json()["pending"]
    # con token, un origen moz-extension:// no se bloquea (la defensa de Origin es para la cookie de sesión)
    r = anon.post("/api/inbox", headers=AUTH, json={"content": "Leer artículo\n\nhttps://ejemplo.org/a", "item_type": "tarea",
                                                    "priority": "alta", "category": " Lecturas "})
    assert r.status_code == 200
    iid = r.json()["id"]
    item = next(i for i in anon.get("/api/items", headers=AUTH).json()["items"] if i["id"] == iid)
    assert (item["priority"], item["category"], item["type"]) == ("alta", "Lecturas", "tarea")
    st = anon.get("/api/ext/status", headers=AUTH).json()
    assert st["pending"] == antes + 1 and "Lecturas" in st["inbox_categories"]
    # editar y quitar
    assert anon.patch(f"/api/items/{iid}", headers=AUTH, json={"priority": "baja", "category": "Otra"}).status_code == 200
    assert anon.patch(f"/api/items/{iid}", headers=AUTH, json={"priority": "", "category": ""}).status_code == 200
    item = next(i for i in anon.get("/api/items", headers=AUTH).json()["items"] if i["id"] == iid)
    assert item["priority"] is None and item["category"] is None
    assert anon.post("/api/inbox", headers=AUTH, json={"content": "x", "priority": "urgentísima"}).status_code == 422


def test_baul_con_token(anon):
    r = anon.post("/api/resources", headers=AUTH, json={"url": "https://ejemplo.org/extension", "category": "Leer", "watch_later": True})
    assert r.status_code == 200
    assert anon.post("/api/resources", headers=AUTH, json={"url": "https://ejemplo.org/extension"}).status_code == 409
    assert "Leer" in anon.get("/api/resources/categories", headers=AUTH).json()["categories"]


def test_migracion_6_arriba_y_abajo_sin_perder(tmp_path):
    conn = sqlite3.connect(tmp_path / "m6.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending',
                    parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT)""")
    conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL)")
    conn.execute("INSERT INTO inbox (id, content, item_type) VALUES (1, 'a', 'tarea'), (2, 'b', 'nota')")
    apply_pending(conn, MIGRATIONS)
    conn.execute("UPDATE inbox SET priority='alta', category='C' WHERE id=1")
    revert(conn, MIGRATIONS, 5)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(inbox)")]
    assert "priority" not in cols and [tuple(r) for r in conn.execute("SELECT id, content FROM inbox ORDER BY id")] == [(1, "a"), (2, "b")]
    assert tuple(conn.execute("SELECT id, priority, category FROM inbox_meta_backup").fetchone()) == (1, "alta", "C")
    apply_pending(conn, MIGRATIONS)
    assert "priority" in [r[1] for r in conn.execute("PRAGMA table_info(inbox)")]
