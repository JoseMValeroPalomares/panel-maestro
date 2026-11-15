"""
Papelera y «deshacer» de los borrados.

Antes de borrar algo (suelto o en lote: notas, tareas e ideas, eventos, platos,
ingredientes, comidas del plan, recursos del Baúl, tableros, plantillas…) se guarda
una instantánea (JSON) en la tabla `undo_log` de la misma BD y se devuelve un token.
Lo que no necesita más que volver a meter sus filas usa save_rows / restore_rows
(tipos «rows.*»: una lista de tablas, padres primero, y los enlaces a rehacer). Deshacer o «Restaurar» desde la
papelera (app/trash.py) = leer la instantánea y reinsertarla. Las entradas caducan a
los 30 días (vaciado automático; también se puede vaciar a mano).
"""

import json
import re
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
    conn.execute(
        "INSERT INTO undo_log (token, kind, payload, created_at, title, count) VALUES (?, ?, ?, ?, ?, ?)",
        (token, kind, json.dumps(payload, ensure_ascii=False), time.time(), (title or "")[:300] or None, count),
    )
    return token


def entries(conn: sqlite3.Connection) -> list[dict]:
    ensure_table(conn)
    return [
        dict(r)
        for r in conn.execute("SELECT token, kind, title, count, created_at FROM undo_log ORDER BY created_at DESC")
    ]


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
    """Reinserta filas tal cual (con su id original) y devuelve cuántas entraron. Ignora las columnas que ya no
    existan en la tabla.

    Nunca INSERT OR REPLACE: si la fila sigue existiendo, REPLACE la borra antes y la cascada se lleva a sus hijos
    (los pasos de una tarea, el lienzo de un tablero, el progreso de las flashcards). Se salta en su lugar
    (ON CONFLICT DO NOTHING) en vez de actualizarla: lo que hay ahora es igual o más nuevo que la instantánea —los
    ids son AUTOINCREMENT y no se reutilizan—, así que restaurar nunca pisa ni borra nada vivo. Lo mismo con un
    choque de UNIQUE (un recurso del Baúl cuya URL se volvió a guardar): se queda el actual."""
    if not rows:
        return 0
    cols_exist = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    n = 0
    for row in rows:
        cols = [c for c in row if c in cols_exist]
        cur = conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) ON CONFLICT DO NOTHING",
            [row[c] for c in cols],
        )
        n += cur.rowcount
    return n


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def select(conn: sqlite3.Connection, table: str, where: str, params=()) -> list[dict]:
    return rows_to_dicts(conn.execute(f"SELECT * FROM {table} WHERE {where}", params))


def save_rows(
    conn: sqlite3.Connection,
    kind: str,
    tables: list[tuple[str, list[dict]]],
    title: str | None = None,
    relink: list[tuple[str, str, object, list]] | None = None,
    count: int | None = None,
) -> str:
    """Instantánea de un borrado de filas sueltas (tipo «rows.<algo>»). `tables`: [(tabla, filas)] en orden de
    reinserción (padres primero). `relink`: [(tabla, columna, valor, ids)] = columnas que el borrado dejó a NULL en
    otras filas y que al restaurar vuelven a apuntar a lo restaurado."""
    assert kind.startswith("rows.")
    for t, _ in tables:
        assert _IDENT.match(t)
    for t, c, _v, _ids in relink or []:
        assert _IDENT.match(t) and _IDENT.match(c)
    first = next((rows for _, rows in tables), [])
    return save(
        conn,
        kind,
        {"tables": [[t, rows] for t, rows in tables if rows], "relink": [list(r) for r in relink or [] if r[3]]},
        title=title,
        count=count if count is not None else len(first),
    )


def restore_rows(conn: sqlite3.Connection, payload: dict) -> int:
    """Deshace un save_rows. Devuelve cuántas filas de la primera tabla volvieron. Los enlaces solo se rehacen donde
    siguen vacíos: lo que se cambió después no se pisa."""
    restored = None
    for table, rows in payload.get("tables", []):
        if not _IDENT.match(table):
            continue
        n = insert_rows(conn, table, rows)
        restored = n if restored is None else restored
    for table, col, value, ids in payload.get("relink", []):
        if _IDENT.match(table) and _IDENT.match(col) and ids:
            conn.execute(
                f"UPDATE {table} SET {col}=? WHERE {col} IS NULL AND id IN ({', '.join('?' * len(ids))})", [value, *ids]
            )
    return restored or 0
