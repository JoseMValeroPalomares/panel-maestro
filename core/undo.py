"""
Papelera y «deshacer» de los borrados.

Antes de borrar algo (suelto o en lote: notas, tareas e ideas, eventos, platos,
ingredientes, comidas del plan) se guarda una instantánea (JSON) en la tabla
`undo_log` de la misma BD y se devuelve un token. Deshacer o «Restaurar» desde la
papelera (app/trash.py) = leer la instantánea y reinsertarla. Las entradas caducan a
los 30 días (vaciado automático; también se puede vaciar a mano).
"""
import json
import secrets
import sqlite3
import time

TTL_S = 30 * 86400


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS undo_log (
            token TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(undo_log)")}
    if "title" not in cols:  # nombre legible para la papelera
        conn.execute("ALTER TABLE undo_log ADD COLUMN title TEXT")
    if "count" not in cols:
        conn.execute("ALTER TABLE undo_log ADD COLUMN count INTEGER")


def purge(conn: sqlite3.Connection, older_than_s: float = TTL_S) -> int:
    ensure_table(conn)
    return conn.execute("DELETE FROM undo_log WHERE created_at < ?", (time.time() - older_than_s,)).rowcount


def save(conn: sqlite3.Connection, kind: str, payload: dict, title: str | None = None, count: int | None = None) -> str:
    ensure_table(conn)
    purge(conn)
    token = secrets.token_urlsafe(12)
    conn.execute("INSERT INTO undo_log (token, kind, payload, created_at, title, count) VALUES (?, ?, ?, ?, ?, ?)",
                 (token, kind, json.dumps(payload, ensure_ascii=False), time.time(), (title or "")[:300] or None, count))
    return token


def entries(conn: sqlite3.Connection) -> list[dict]:
    ensure_table(conn)
    return [dict(r) for r in conn.execute("SELECT token, kind, title, count, created_at FROM undo_log ORDER BY created_at DESC")]


def drop(conn: sqlite3.Connection, token: str) -> bool:
    ensure_table(conn)
    return bool(conn.execute("DELETE FROM undo_log WHERE token=?", (token,)).rowcount)


def pop(conn: sqlite3.Connection, token: str, kind_prefix: str = "") -> tuple[str, dict] | None:
    ensure_table(conn)
    row = conn.execute("SELECT kind, payload FROM undo_log WHERE token=?", (token,)).fetchone()
    if not row or not row["kind"].startswith(kind_prefix):
        return None
    conn.execute("DELETE FROM undo_log WHERE token=?", (token,))
    return row["kind"], json.loads(row["payload"])


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    """Reinserta filas tal cual (con su id original). Ignora las columnas que ya
    no existan en la tabla."""
    if not rows:
        return 0
    cols_exist = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    n = 0
    for row in rows:
        cols = [c for c in row if c in cols_exist]
        conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [row[c] for c in cols])
        n += 1
    return n
