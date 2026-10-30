"""Migraciones versionadas: se aplican al arrancar y se revierten sin pérdida."""
import sqlite3

from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert, status


def _db(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending',
                    parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT)""")
    conn.execute("""CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT,
                    channel TEXT, added_at REAL, watch_later INTEGER DEFAULT 0, watched INTEGER DEFAULT 0)""")
    conn.executemany("INSERT INTO resources (id, url, title, category, resource_type, channel, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [(1, "u1", "Web vieja", "A", "web", None, 1), (2, "u2", "Web nueva", "A", "web", None, 2),
                      (3, "u3", "Vídeo", "A", "youtube", "Zeta", 3), (4, "u4", "Vídeo", "A", "youtube", "Alfa", 4)])
    rows = [(25, "Comprar", "nota", None), (26, "Ropa", "nota", 25), (39, "Gestión", "tarea", 25),
            (35, "Cosas", "tarea", 39), (43, "Sol", "tarea", 35), (51, "Vídeos", "tarea", 39)]
    conn.executemany("INSERT INTO inbox (id, content, item_type, parent_id) VALUES (?, ?, ?, ?)", rows)
    return conn


def _snap(conn):
    return conn.execute("SELECT id, content, item_type, parent_id, sort_order FROM inbox ORDER BY id").fetchall()


def test_todas_arriba_y_abajo(tmp_path):
    conn = _db(tmp_path)
    antes = [tuple(r) for r in _snap(conn)]
    assert apply_pending(conn, MIGRATIONS) == [m.version for m in MIGRATIONS]
    tree = {r["id"]: r["parent_id"] for r in _snap(conn)}
    assert tree[39] is None and tree[35] is None  # intermedios con hijos suben
    assert tree[43] == 35 and tree[51] == 39 and tree[26] == 25  # sus hijos siguen con ellos
    nietos = conn.execute("SELECT COUNT(*) FROM inbox c JOIN inbox p ON p.id=c.parent_id WHERE p.parent_id IS NOT NULL").fetchone()[0]
    cruzados = conn.execute("SELECT COUNT(*) FROM inbox c JOIN inbox p ON p.id=c.parent_id WHERE p.item_type != c.item_type").fetchone()[0]
    assert nietos == 0 and cruzados == 0
    assert apply_pending(conn, MIGRATIONS) == []  # idempotente
    orden = {r[0]: r[1] for r in conn.execute("SELECT id, sort_order FROM resources")}
    assert orden[2] > orden[1] and orden[4] > orden[3]  # web: nuevo arriba; vídeos: por canal
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='note_order'").fetchone()
    revert(conn, MIGRATIONS, 0)
    assert not any(r[1] == "sort_order" for r in conn.execute("PRAGMA table_info(resources)"))
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='note_order'").fetchone()
    assert [tuple(r) for r in _snap(conn)] == antes
    assert all(not ok for _, _, ok in status(conn, MIGRATIONS))


def test_cada_paso_se_queda_con_su_hora(tmp_path):
    """Migración 16: la hora que salía del encadenado pasa a ser la del paso; `down` la quita."""
    conn = _db(tmp_path)
    apply_pending(conn, [x for x in MIGRATIONS if x.version <= 15])
    conn.execute("DELETE FROM inbox")
    rows = [(1, "Mi día", None, "07:30", None, '{"freq": "daily"}', 9), (2, "Ducha", 1, None, 10, None, 8), (3, "Uni", 1, "08:30", 60, '{"freq": "weekly", "days": [0]}', 7),
            (4, "Comer", 1, None, 30, None, 6), (5, "Sábado", 1, None, None, '{"freq": "weekly", "days": [5]}', 5),
            (6, "Sin hora", None, None, None, '{"freq": "daily"}', 4), (7, "Paso", 6, None, 5, None, 3)]
    conn.executemany("INSERT INTO inbox (id, content, item_type, parent_id, due_time, duration_min, repeat, sort_order) VALUES (?, ?, 'rutina', ?, ?, ?, ?, ?)", rows)
    assert apply_pending(conn, MIGRATIONS) == [16]
    horas = dict(conn.execute("SELECT id, due_time FROM inbox").fetchall())
    # Comer sale del lunes (tras Uni); Sábado, del único día en que toca; sin hora de partida no se inventa
    assert horas == {1: "07:30", 2: "07:30", 3: "08:30", 4: "09:30", 5: "08:10", 6: None, 7: None}
    revert(conn, MIGRATIONS, 15)
    assert dict(conn.execute("SELECT id, due_time FROM inbox").fetchall()) == {1: "07:30", 2: None, 3: "08:30", 4: None, 5: None, 6: None, 7: None}
