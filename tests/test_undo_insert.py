"""D-7: core/undo.insert_rows nunca borra lo que sigue vivo (sin INSERT OR REPLACE: ON CONFLICT DO NOTHING)."""

from app.database import get_db
from core import undo


def test_restaurar_padre_que_sigue_existiendo_no_borra_sus_pasos(client):
    parent = client.post("/api/items", json={"text": "Padre D7"}).json()
    pid = parent.get("id") or parent["item"]["id"]
    steps = []
    for t in ("Paso 1", "Paso 2"):
        s = client.post("/api/items", json={"text": t, "parent_id": pid}).json()
        steps.append(s.get("id") or s["item"]["id"])
    with get_db() as conn:
        snapshot = undo.rows_to_dicts(conn.execute("SELECT * FROM inbox WHERE id=?", (pid,)))
        snapshot[0]["content"] = "Texto viejo de la instantánea"
        assert undo.insert_rows(conn, "inbox", snapshot) == 0  # ya existe: se salta
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM inbox WHERE parent_id=?", (pid,)).fetchone()[0] == 2
        assert (
            conn.execute("SELECT content FROM inbox WHERE id=?", (pid,)).fetchone()[0]
            != "Texto viejo de la instantánea"
        )


def test_restaurar_pasos_borrados_bajo_un_padre_vivo(client):
    parent = client.post("/api/items", json={"text": "Padre D7 b"}).json()
    pid = parent.get("id") or parent["item"]["id"]
    s = client.post("/api/items", json={"text": "Paso que vuelve", "parent_id": pid}).json()
    sid = s.get("id") or s["item"]["id"]
    with get_db() as conn:
        rows = undo.rows_to_dicts(conn.execute("SELECT * FROM inbox WHERE id IN (?, ?)", (pid, sid)))
        conn.execute("DELETE FROM inbox WHERE id=?", (sid,))
        # padre (vivo) + paso (borrado): entra solo el paso y el padre sigue intacto
        assert undo.insert_rows(conn, "inbox", sorted(rows, key=lambda r: r["parent_id"] is not None)) == 1
        assert conn.execute("SELECT parent_id FROM inbox WHERE id=?", (sid,)).fetchone()[0] == pid
