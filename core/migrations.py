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
from dataclasses import dataclass
from typing import Callable

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
            conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                         (m.version, m.name, time.time()))
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
