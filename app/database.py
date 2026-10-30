import sqlite3
import os

from core import config
from core.db import connect, db_session, enable_wal

DB_PATH = str(config.BRAIN_DB)


def get_db_connection():
    """Conexión suelta (con WAL/busy_timeout/foreign_keys). Preferir get_db()."""
    return connect(DB_PATH)


def get_db():
    """Context manager: commit/rollback automático y cierre garantizado."""
    return db_session(DB_PATH)


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    enable_wal(DB_PATH)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            slug TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            category_id INTEGER REFERENCES categories(id),
            tags TEXT,
            content TEXT,
            status TEXT DEFAULT 'por-escribir',
            last_modified REAL
        )
    ''')

    cursor.execute("PRAGMA table_info(notes)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if 'status' not in existing_cols:
        cursor.execute("ALTER TABLE notes ADD COLUMN status TEXT DEFAULT 'por-escribir'")
    if 'category_id' not in existing_cols:
        cursor.execute("ALTER TABLE notes ADD COLUMN category_id INTEGER REFERENCES categories(id)")
    if 'tags' not in existing_cols:
        cursor.execute("ALTER TABLE notes ADD COLUMN tags TEXT")
    # ---- Migración: Quick Recall ponderado ----
    if 'last_reviewed' not in existing_cols:
        cursor.execute("ALTER TABLE notes ADD COLUMN last_reviewed REAL DEFAULT 0")
    # ---- Migración: notas privadas/cifradas ----
    if 'encrypted' not in existing_cols:
        cursor.execute("ALTER TABLE notes ADD COLUMN encrypted INTEGER DEFAULT 0")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id TEXT PRIMARY KEY,
            x REAL,
            y REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT DEFAULT 'manual',
            UNIQUE(source, target)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            description TEXT,
            image TEXT,
            resource_type TEXT DEFAULT 'web',
            category TEXT DEFAULT 'General',
            watch_later INTEGER DEFAULT 0,
            added_at REAL DEFAULT (unixepoch())
        )
    ''')

    cursor.execute("PRAGMA table_info(resources)")
    existing_resource_cols = {row[1] for row in cursor.fetchall()}
    if 'channel' not in existing_resource_cols:
        cursor.execute("ALTER TABLE resources ADD COLUMN channel TEXT")
    if 'watched' not in existing_resource_cols:
        cursor.execute("ALTER TABLE resources ADD COLUMN watched INTEGER DEFAULT 0")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            item_type TEXT DEFAULT 'nota',
            status TEXT DEFAULT 'pending',
            parent_id INTEGER REFERENCES inbox(id) ON DELETE CASCADE,
            created_at REAL DEFAULT (unixepoch())
        )
    ''')

    cursor.execute("PRAGMA table_info(inbox)")
    existing_inbox_cols = {row[1] for row in cursor.fetchall()}
    if 'item_type' not in existing_inbox_cols:
        cursor.execute("ALTER TABLE inbox ADD COLUMN item_type TEXT DEFAULT 'nota'")
    if 'parent_id' not in existing_inbox_cols:
        cursor.execute("ALTER TABLE inbox ADD COLUMN parent_id INTEGER REFERENCES inbox(id) ON DELETE CASCADE")
    if 'sort_order' not in existing_inbox_cols:
        cursor.execute("ALTER TABLE inbox ADD COLUMN sort_order REAL DEFAULT 0")
    # Fase 8: enlace con una tarea "- [ ]" de una nota (texto de la línea) para sincronizar el estado
    if 'note_id' not in existing_inbox_cols:
        cursor.execute("ALTER TABLE inbox ADD COLUMN note_id TEXT")
    if 'note_task' not in existing_inbox_cols:
        cursor.execute("ALTER TABLE inbox ADD COLUMN note_task TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at REAL DEFAULT (unixepoch()),
            updated_at REAL DEFAULT (unixepoch())
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS board_canvas (
            board_id INTEGER PRIMARY KEY REFERENCES boards(id) ON DELETE CASCADE,
            data TEXT NOT NULL DEFAULT '{}'
        )
    ''')

    # ---- Flashcards con repetición espaciada (SM-2) ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id TEXT REFERENCES notes(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            ease_factor REAL DEFAULT 2.5,
            interval_days REAL DEFAULT 0,
            repetitions INTEGER DEFAULT 0,
            next_review REAL DEFAULT (unixepoch()),
            created_at REAL DEFAULT (unixepoch())
        )
    ''')

    # ---- Racha de estudio ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS study_days (
            day TEXT PRIMARY KEY
        )
    ''')

    # ---- Índices ----
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_boards_updated ON boards(updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inbox_parent ON inbox(parent_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inbox_note ON inbox(note_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_category_id ON notes(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inbox_status_type ON inbox(status, item_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resources_watch_later ON resources(watch_later)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resources_watched ON resources(watched)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_next_review ON flashcards(next_review)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_note ON flashcards(note_id)")

    conn.commit()
    conn.close()

    # Migraciones versionadas (reversibles): app/migrations.py
    from app.migrations import MIGRATIONS
    from core.migrations import apply_pending
    mconn = connect(DB_PATH)
    mconn.isolation_level = None
    try:
        apply_pending(mconn, MIGRATIONS)
    finally:
        mconn.close()


if __name__ == "__main__":
    init_db()
