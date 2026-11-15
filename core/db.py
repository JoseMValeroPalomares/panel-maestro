"""
Acceso a SQLite común a Cerebro y Comidas.

    with db_session(path) as conn:
        conn.execute(...)

- Hace COMMIT al salir sin errores, ROLLBACK si hay excepción y SIEMPRE cierra
  la conexión (antes una excepción dejaba la conexión abierta con el bloqueo de
  escritura y el resto de peticiones fallaban con "database is locked").
- WAL: lectores y escritor no se bloquean entre sí.
- busy_timeout: si otra conexión está escribiendo, espera en vez de fallar.
"""

import contextlib
import os
import re
import sqlite3

BUSY_TIMEOUT_MS = 5000


def connect(path: str | os.PathLike) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(os.fspath(path), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def enable_wal(path: str | os.PathLike) -> None:
    """journal_mode es persistente en el archivo: basta con fijarlo al iniciar."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()


@contextlib.contextmanager
def db_session(path: str | os.PathLike):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def update_fields(conn: sqlite3.Connection, tabla: str, id_, valores: dict, permitidos, columna_id: str = "id") -> int:
    """`UPDATE tabla SET campo=?, … WHERE columna_id=?` con los `valores` ya normalizados ({columna: valor}). Las columnas
    van en el SQL, así que solo valen las de `permitidos` (una tupla fija o los campos de un modelo Pydantic: nunca
    lo que mande el cliente); cualquier otra es un error de programación. Sin valores no hace nada. Devuelve rowcount."""
    permitidos = set(permitidos)
    malas = [c for c in valores if c not in permitidos or not _IDENT.match(c)]
    if malas or not _IDENT.match(tabla) or not _IDENT.match(columna_id):
        raise ValueError(f"Columnas no permitidas en {tabla}: {malas or [tabla, columna_id]}")
    if not valores:
        return 0
    sets = ", ".join(f"{c}=?" for c in valores)
    return conn.execute(f"UPDATE {tabla} SET {sets} WHERE {columna_id}=?", [*valores.values(), id_]).rowcount
