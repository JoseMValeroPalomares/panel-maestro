"""D-8: copia automática de la BD antes de aplicar migraciones pendientes; si la copia falla, no se migra."""

import sqlite3

import pytest

import app.database as brain_db
import comidas.database as comidas_db
from app.migrations import MIGRATIONS as BRAIN_MIGRATIONS
from comidas.migrations import MIGRATIONS as COMIDAS_MIGRATIONS
from core import config
from core.migrations import MigrationBackupError, applied, revert


def _versions(path) -> set[int]:
    conn = sqlite3.connect(path)
    try:
        return applied(conn)
    finally:
        conn.close()


def _one_behind(module, migrations, path):
    """BD con datos en la versión N-1 (creada con su init_db y revertida la última migración)."""
    module.init_db()
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        revert(conn, migrations, max(m.version for m in migrations) - 1)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "module,migrations,label,seed",
    [
        (brain_db, BRAIN_MIGRATIONS, "brain", "INSERT INTO inbox (content) VALUES ('dato de antes')"),
        (
            comidas_db,
            COMIDAS_MIGRATIONS,
            "comidas",
            "INSERT INTO ingredients (nombre, kcal_100g) VALUES ('Dato de antes', 1)",
        ),
    ],
)
def test_copia_antes_de_migrar(monkeypatch, tmp_path, module, migrations, label, seed):
    db = tmp_path / f"{label}.db"
    backups = tmp_path / "backups"
    monkeypatch.setattr(module, "DB_PATH", str(db))
    monkeypatch.setattr(config, "BACKUPS_DIR", backups)

    module.init_db()  # BD nueva: no hay nada que copiar
    assert not backups.exists()

    last = max(m.version for m in migrations)
    _one_behind(module, migrations, db)
    conn = sqlite3.connect(db)
    conn.execute(seed)
    conn.commit()
    conn.close()
    assert last not in _versions(db)

    module.init_db()
    copies = list(backups.glob(f"pre-migracion-{last}-*/{label}.db"))
    assert len(copies) == 1
    assert last not in _versions(copies[0])  # la copia es la de antes de migrar…
    assert last in _versions(db)  # …y la BD ya está al día
    check = sqlite3.connect(copies[0])
    assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()

    module.init_db()  # ya al día: no copia otra vez
    assert len(list(backups.glob("pre-migracion-*"))) == 1


def test_si_la_copia_falla_no_se_migra(monkeypatch, tmp_path):
    db = tmp_path / "brain.db"
    monkeypatch.setattr(brain_db, "DB_PATH", str(db))
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    _one_behind(brain_db, BRAIN_MIGRATIONS, db)
    last = max(m.version for m in BRAIN_MIGRATIONS)
    blocker = tmp_path / "no-es-carpeta"
    blocker.write_text("un archivo donde iría la carpeta de copias")
    monkeypatch.setattr(config, "BACKUPS_DIR", blocker)
    with pytest.raises(MigrationBackupError, match="No se ha migrado nada"):
        brain_db.init_db()
    assert last not in _versions(db)
