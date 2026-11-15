"""D-6: si la carpeta de notas se lee (casi) vacía, la caché y lo que cuelga de ella no se borran."""

from app import indexer
from app.database import get_db
from core import config


def _note(client, nid):
    r = client.post(f"/api/notes/{nid}", json={"title": nid, "category": "Guarda", "content": "texto"})
    assert r.status_code == 200, r.text


def test_carpeta_vacia_no_borra_notas_ni_flashcards(client, monkeypatch, tmp_path):
    for i in range(8):
        _note(client, f"guarda-{i}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO flashcards (note_id, question, answer, repetitions) VALUES ('guarda-0', '¿P?', 'R', 4)"
        )
        before = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    vacia = tmp_path / "sin-montar"
    vacia.mkdir()
    monkeypatch.setattr(indexer, "NOTES_DIR", str(vacia))
    stats = indexer.sync_notes_to_db()
    assert stats["eliminadas"] == 0 and stats["frenadas"] == before
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == before
        assert conn.execute("SELECT repetitions FROM flashcards WHERE note_id='guarda-0'").fetchone()[0] == 4
    g = indexer.notes_guard_status()
    assert g and g["missing"] == before
    item = next(i for i in client.get("/api/status").json()["items"] if i["key"] == "notes-guard")
    assert item["state"] == "aviso" and "no se ha borrado nada" in item["detail"]

    # La carpeta vuelve: el aviso desaparece
    monkeypatch.setattr(indexer, "NOTES_DIR", str(config.NOTES_DIR))
    indexer.sync_notes_to_db()
    assert indexer.notes_guard_status() is None
    assert not any(i["key"] == "notes-guard" for i in client.get("/api/status").json()["items"])


def test_borrar_una_de_diez_si_funciona(client):
    for i in range(10):
        _note(client, f"diez-{i}")
    (config.NOTES_DIR / "diez-3.md").unlink()  # borrada fuera del panel
    assert indexer.sync_notes_to_db()["eliminadas"] == 1
    assert client.get("/api/notes/diez-3").status_code == 404
    assert indexer.notes_guard_status() is None


def test_borrar_muchas_desde_el_panel_si_funciona(client):
    """En lote (aunque fuesen todas) las filas se quitan al mover los archivos: la guarda no interviene."""
    ids = [f"lote-{i}" for i in range(12)]
    for nid in ids:
        _note(client, nid)
    r = client.post("/api/bulk/notes/delete", json={"ids": ids})
    assert r.json()["deleted"] == len(ids)
    indexer.sync_notes_to_db()
    assert indexer.notes_guard_status() is None
    with get_db() as conn:
        assert not conn.execute(f"SELECT 1 FROM notes WHERE id IN ({','.join('?' * len(ids))})", ids).fetchone()
    assert client.post(f"/api/trash/brain/{r.json()['undo_token']}/restore").json()["restored"] == len(ids)
