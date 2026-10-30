import os
import time

from app.database import get_db
from app.indexer import sync_notes_to_db


def _write(tmp_root, name, body):
    path = tmp_root / "data" / "notes" / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_sync_incremental_conserva_last_reviewed(client, tmp_root):
    path = _write(tmp_root, "idx-a", "---\ntitle: Idx A\ncategory: Idx\nstatus: en-desarrollo\ntags: [uno, dos]\n---\nCuerpo\n")
    sync_notes_to_db()
    with get_db() as conn:
        conn.execute("UPDATE notes SET last_reviewed = 12345 WHERE id = 'idx-a'")
    # sin cambios en disco: no se reescribe
    stats = sync_notes_to_db()
    assert stats["nuevas"] == 0 and stats["actualizadas"] == 0
    # cambio en disco: se actualiza el contenido pero se conserva last_reviewed
    path.write_text("---\ntitle: Idx A editada\ncategory: Idx\n---\nNuevo\n", encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    stats = sync_notes_to_db()
    assert stats["actualizadas"] == 1
    with get_db() as conn:
        row = conn.execute("SELECT title, tags, status, last_reviewed FROM notes WHERE id='idx-a'").fetchone()
    assert row["title"] == "Idx A editada" and row["last_reviewed"] == 12345
    assert row["status"] == "por-escribir"


def test_sync_elimina_solo_las_borradas(client, tmp_root):
    path = _write(tmp_root, "idx-b", "---\ntitle: B\n---\nx\n")
    sync_notes_to_db()
    path.unlink()
    stats = sync_notes_to_db()
    assert stats["eliminadas"] == 1
    with get_db() as conn:
        assert conn.execute("SELECT 1 FROM notes WHERE id='idx-b'").fetchone() is None
        assert conn.execute("SELECT 1 FROM notes WHERE id='nota-inicial'").fetchone() is not None


def test_nota_corrupta_no_rompe_el_sync(client, tmp_root):
    path = _write(tmp_root, "idx-rota", "---\ntitle: [sin cerrar\n---\nx\n")
    stats = sync_notes_to_db()
    assert stats["errores"] >= 1
    path.unlink()
    sync_notes_to_db()


def test_wal_activo(client):
    with get_db() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
