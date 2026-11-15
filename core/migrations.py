"""
Migraciones versionadas y reversibles.

Cada BD lleva una tabla `schema_migrations(version, name, applied_at)`. Una
migración es una función `up` y otra `down`; se aplican en orden al arrancar
(`apply_pending`) y se pueden revertir con `python -m scripts.migrate down <v>`.
Las que cambian datos guardan antes los valores originales en una tabla propia
(`*_backup`), que es lo que usa `down` para volver atrás sin pérdida.

Las migraciones antiguas (ALTER TABLE ADD COLUMN de app/database.py y
comidas/database.py) siguen donde estaban: son anteriores a este registro.
"""

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.logging_config import get_logger

log = get_logger("migrations")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]
    down: Callable[[sqlite3.Connection], None]


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at REAL NOT NULL)""")


def applied(conn: sqlite3.Connection) -> set[int]:
    _ensure(conn)
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


class MigrationBackupError(RuntimeError):
    """No se pudo copiar la BD antes de migrar: el panel no arranca antes que migrar sin copia."""


def backup_before_migrating(db_path, migrations: list[Migration], backups_dir, label: str) -> Path | None:
    """Si la BD ya existe, tiene migraciones aplicadas y le faltan otras, la copia (API de backup de SQLite +
    integrity_check) a backups/pre-migracion-<versión>-<fecha>/<label>.db antes de tocarla. Una BD nueva o al día
    no copia nada. Si la copia falla, lanza MigrationBackupError y no se migra."""
    db_path = Path(db_path)
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        try:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone():
                return None
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise MigrationBackupError(f"No se pudo leer {db_path} para copiarla antes de migrar: {e}") from e
    pending = sorted(m.version for m in migrations if m.version not in done)
    if not done or not pending:
        return None
    folder = Path(backups_dir) / f"pre-migracion-{pending[-1]}-{datetime.now():%Y%m%d-%H%M%S}"
    target = folder / f"{label}.db"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
            ok = copy.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            copy.close()
            source.close()
        if ok != "ok":
            raise sqlite3.DatabaseError(f"integrity_check: {ok}")
    except (OSError, sqlite3.Error) as e:
        raise MigrationBackupError(
            f"No se pudo copiar {db_path.name} a {folder} antes de aplicar las migraciones {pending}: {e}. "
            "No se ha migrado nada; libera espacio o revisa PANEL_BACKUPS_DIR y vuelve a arrancar."
        ) from e
    log.warning("Copia de %s antes de migrar (%s → %s): %s", db_path.name, max(done), pending[-1], target)
    return target


def apply_pending(conn: sqlite3.Connection, migrations: list[Migration]) -> list[int]:
    """Aplica en orden las que falten, cada una en su transacción."""
    done = applied(conn)
    ran = []
    for m in sorted(migrations, key=lambda m: m.version):
        if m.version in done:
            continue
        try:
            conn.execute("BEGIN")
            m.up(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (m.version, m.name, time.time()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("Falló la migración %s (%s)", m.version, m.name)
            raise
        log.info("Migración aplicada: %s %s", m.version, m.name)
        ran.append(m.version)
    return ran


def revert(conn: sqlite3.Connection, migrations: list[Migration], target: int) -> list[int]:
    """Revierte, de la más nueva a la más antigua, todas las > target."""
    done = applied(conn)
    ran = []
    for m in sorted(migrations, key=lambda m: m.version, reverse=True):
        if m.version <= target or m.version not in done:
            continue
        try:
            conn.execute("BEGIN")
            m.down(conn)
            conn.execute("DELETE FROM schema_migrations WHERE version=?", (m.version,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("Falló revertir la migración %s", m.version)
            raise
        log.warning("Migración revertida: %s %s", m.version, m.name)
        ran.append(m.version)
    return ran


def status(conn: sqlite3.Connection, migrations: list[Migration]) -> list[tuple[int, str, bool]]:
    done = applied(conn)
    return [(m.version, m.name, m.version in done) for m in sorted(migrations, key=lambda m: m.version)]
