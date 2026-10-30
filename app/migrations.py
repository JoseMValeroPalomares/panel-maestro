"""
Migraciones versionadas de brain.db (ver core/migrations.py).

Cada una guarda lo que cambia en una tabla *_backup para que `down` lo deje
exactamente como estaba.
"""
import json
import re
import sqlite3
import time
from datetime import date, timedelta

from app import routines
from app.board_convert import convert_text
from core.migrations import Migration, has_column


# 1 ─ Inbox con un solo nivel de subelementos y tipo coherente con el padre ─────
# Antes se podía soltar una tarea dentro de una idea y anidar sin límite; el
# Inbox solo dibuja dos niveles, así que los nietos no se veían. Un elemento
# intermedio con hijos sube a primer nivel (con sus hijos), y un subelemento
# de distinto tipo que su padre también sube, conservando su tipo y contenido.

def _inbox_one_level_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS inbox_r2_backup (
        id INTEGER PRIMARY KEY, parent_id INTEGER, item_type TEXT, sort_order REAL)""")
    rows = {r["id"]: r for r in conn.execute("SELECT id, parent_id, item_type, sort_order FROM inbox")}
    has_kids = {r["parent_id"] for r in rows.values() if r["parent_id"] is not None}

    def save(r):
        conn.execute("INSERT OR IGNORE INTO inbox_r2_backup (id, parent_id, item_type, sort_order) VALUES (?, ?, ?, ?)",
                     (r["id"], r["parent_id"], r["item_type"], r["sort_order"]))

    top = max([r["sort_order"] or 0 for r in rows.values()] + [0])
    for r in rows.values():
        if r["parent_id"] is not None and r["id"] in has_kids:  # intermedio con hijos
            save(r)
            top += 1
            conn.execute("UPDATE inbox SET parent_id=NULL, sort_order=? WHERE id=?", (top, r["id"]))
    for r in conn.execute("""SELECT c.id, c.parent_id, c.item_type, c.sort_order FROM inbox c JOIN inbox p ON p.id = c.parent_id
                             WHERE c.item_type != p.item_type""").fetchall():
        save(r)
        top += 1
        conn.execute("UPDATE inbox SET parent_id=NULL, sort_order=? WHERE id=?", (top, r["id"]))


def _inbox_one_level_down(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT id, parent_id, item_type, sort_order FROM inbox_r2_backup").fetchall():
        conn.execute("UPDATE inbox SET parent_id=?, item_type=?, sort_order=? WHERE id=?",
                     (r["parent_id"], r["item_type"], r["sort_order"], r["id"]))
    conn.execute("DROP TABLE inbox_r2_backup")


# 2 ─ Orden manual del Baúl ─────────────────────────────────────────────────────
def resources_order_up(conn: sqlite3.Connection) -> None:
    if not has_column(conn, "resources", "sort_order"):
        conn.execute("ALTER TABLE resources ADD COLUMN sort_order REAL")
    # Orden inicial = el que se veía: vídeos por canal, web por fecha (más nuevo arriba)
    rows = conn.execute("SELECT id, category, resource_type, channel, title, added_at FROM resources").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r["category"] or "General", r["resource_type"] == "youtube"), []).append(r)
    for (_, is_yt), items in groups.items():
        if is_yt:
            items.sort(key=lambda r: (r["channel"] or r["title"] or "").lower())
        else:
            items.sort(key=lambda r: -(r["added_at"] or 0))
        n = len(items)
        for pos, r in enumerate(items):
            conn.execute("UPDATE resources SET sort_order=? WHERE id=?", (float(n - pos), r["id"]))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resources_order ON resources(category, sort_order)")


def resources_order_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_resources_order")
    if has_column(conn, "resources", "sort_order"):
        conn.execute("ALTER TABLE resources DROP COLUMN sort_order")  # solo era el orden manual



# 3 ─ Orden manual de las notas dentro de su categoría ─────────────────────────
def note_order_up(conn: sqlite3.Connection) -> None:
    # Fuera de los .md a propósito: el formato de las notas no cambia
    conn.execute("""CREATE TABLE IF NOT EXISTS note_order (
        note_id TEXT PRIMARY KEY, category_key TEXT NOT NULL, position REAL NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_order_cat ON note_order(category_key)")


def note_order_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS note_order")


# 4 ─ Tableros al formato 2 (SVG propio); el JSON de fabric.js queda en board_canvas_legacy ──
def boards_v2_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS board_canvas_legacy (
        board_id INTEGER PRIMARY KEY, data TEXT NOT NULL, report TEXT, migrated_at REAL NOT NULL)""")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='board_canvas'").fetchone():
        return
    for r in conn.execute("SELECT board_id, data FROM board_canvas").fetchall():
        new, report = convert_text(r["data"])
        if report is None:
            continue
        conn.execute("INSERT OR REPLACE INTO board_canvas_legacy (board_id, data, report, migrated_at) VALUES (?, ?, ?, ?)",
                     (r["board_id"], r["data"], json.dumps(report, ensure_ascii=False), time.time()))
        conn.execute("UPDATE board_canvas SET data=? WHERE board_id=?", (new, r["board_id"]))


def boards_v2_down(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT board_id, data FROM board_canvas_legacy").fetchall():
        conn.execute("UPDATE board_canvas SET data=? WHERE board_id=?", (r["data"], r["board_id"]))
    conn.execute("DROP TABLE board_canvas_legacy")



# 5 ─ Plantillas del tablero ───────────────────────────────────────────────────
def board_templates_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS board_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, data TEXT NOT NULL,
        created_at REAL DEFAULT (unixepoch()))""")


def board_templates_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS board_templates")


# 6 ─ Inbox: prioridad y categoría (capturas desde la extensión de Firefox) ──
def inbox_meta_up(conn: sqlite3.Connection) -> None:
    for col in ("priority", "category"):
        if not has_column(conn, "inbox", col):
            conn.execute(f"ALTER TABLE inbox ADD COLUMN {col} TEXT")


def inbox_meta_down(conn: sqlite3.Connection) -> None:
    # Lo que se hubiera puesto se guarda antes de quitar las columnas
    conn.execute("CREATE TABLE IF NOT EXISTS inbox_meta_backup (id INTEGER PRIMARY KEY, priority TEXT, category TEXT)")
    if has_column(conn, "inbox", "priority"):
        conn.execute("INSERT OR REPLACE INTO inbox_meta_backup (id, priority, category) "
                     "SELECT id, priority, category FROM inbox WHERE priority IS NOT NULL OR category IS NOT NULL")
        conn.execute("ALTER TABLE inbox DROP COLUMN priority")
        conn.execute("ALTER TABLE inbox DROP COLUMN category")


# 7 ─ Lista única de tareas e ideas: fecha, notas y posición de las casillas de las notas ──
# Las casillas «- [ ]» pasan a tener fila propia (las crea app/note_tasks.py al indexar).
# Aquí: columnas nuevas, se quita la marca antigua «--- » que /process ponía al texto y
# las copias enlazadas cuya casilla ya no está en su nota vuelven a ser del Inbox (si no,
# la sincronía las borraría). Todo lo cambiado queda en inbox_r3_backup.
def items_up(conn: sqlite3.Connection) -> None:
    for col, kind in (("due_date", "TEXT"), ("details", "TEXT"), ("note_index", "INTEGER")):
        if not has_column(conn, "inbox", col):
            conn.execute(f"ALTER TABLE inbox ADD COLUMN {col} {kind}")
    conn.execute("""CREATE TABLE IF NOT EXISTS inbox_r3_backup (
        id INTEGER PRIMARY KEY, content TEXT, note_id TEXT, note_task TEXT)""")
    conn.execute("CREATE TABLE IF NOT EXISTS inbox_r3_meta (key TEXT PRIMARY KEY, value TEXT)")
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM inbox").fetchone()[0]
    conn.execute("INSERT OR REPLACE INTO inbox_r3_meta (key, value) VALUES ('max_id', ?)", (str(max_id),))
    from app.note_tasks import parse_tasks
    has_notes = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes'").fetchone()
    notes = {r["id"]: r["content"] for r in conn.execute("SELECT id, content FROM notes WHERE encrypted=0")} if has_notes else {}
    linked = has_column(conn, "inbox", "note_task")
    for r in conn.execute(f"SELECT id, content, {'note_id, note_task' if linked else 'NULL AS note_id, NULL AS note_task'} FROM inbox").fetchall():
        content, note_id, note_task = r["content"], r["note_id"], r["note_task"]
        if content and content.startswith("---"):
            content = re.sub(r"^---\s*", "", content)
        if note_task is not None and note_task not in {t["text"] for t in parse_tasks(notes.get(note_id) or "")}:
            note_id, note_task = None, None
        if (content, note_id, note_task) != (r["content"], r["note_id"], r["note_task"]):
            conn.execute("INSERT OR IGNORE INTO inbox_r3_backup (id, content, note_id, note_task) VALUES (?, ?, ?, ?)",
                         (r["id"], r["content"], r["note_id"], r["note_task"]))
            conn.execute("UPDATE inbox SET content=? WHERE id=?", (content, r["id"]))
            if linked:
                conn.execute("UPDATE inbox SET note_id=?, note_task=? WHERE id=?", (note_id, note_task, r["id"]))
    if linked:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_note_index ON inbox(note_id, note_index)")


def items_down(conn: sqlite3.Connection) -> None:
    # Las filas que creó la sincronía para las casillas de las notas no existían antes
    row = conn.execute("SELECT value FROM inbox_r3_meta WHERE key='max_id'").fetchone()
    max_id = int(row[0]) if row else 0
    linked = has_column(conn, "inbox", "note_task")
    if linked:
        conn.execute("DELETE FROM inbox WHERE id > ? AND note_task IS NOT NULL", (max_id,))
    for r in conn.execute("SELECT id, content, note_id, note_task FROM inbox_r3_backup").fetchall():
        conn.execute("UPDATE inbox SET content=? WHERE id=?", (r["content"], r["id"]))
        if linked:
            conn.execute("UPDATE inbox SET note_id=?, note_task=? WHERE id=?", (r["note_id"], r["note_task"], r["id"]))
    # Fechas y notas escritas desde entonces se guardan antes de quitar las columnas
    conn.execute("CREATE TABLE IF NOT EXISTS inbox_items_backup (id INTEGER PRIMARY KEY, due_date TEXT, details TEXT)")
    if has_column(conn, "inbox", "due_date"):
        conn.execute("INSERT OR REPLACE INTO inbox_items_backup (id, due_date, details) "
                     "SELECT id, due_date, details FROM inbox WHERE due_date IS NOT NULL OR details IS NOT NULL")
    conn.execute("DROP INDEX IF EXISTS idx_inbox_note_index")
    for col in ("due_date", "details", "note_index"):
        if has_column(conn, "inbox", col):
            conn.execute(f"ALTER TABLE inbox DROP COLUMN {col}")
    conn.execute("DROP TABLE IF EXISTS inbox_r3_backup")
    conn.execute("DROP TABLE IF EXISTS inbox_r3_meta")


# 8 ─ Preferencias de interfaz en el servidor (plegados de notas y categorías, etc.) ──
def ui_prefs_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS ui_prefs (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)""")


def ui_prefs_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS ui_prefs")


# 9 ─ Enlaces tarea/idea ↔ nota: índice de los marcadores [[tarea:N]] de las notas ──
def item_links_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS item_links (
        item_id INTEGER NOT NULL REFERENCES inbox(id) ON DELETE CASCADE,
        note_id TEXT NOT NULL, created_at REAL, PRIMARY KEY (item_id, note_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_links_note ON item_links(note_id)")


def item_links_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS item_links")  # se rehace desde los .md


# 10 ─ Calendario: eventos propios, rutinas (tipo nuevo de la lista única) con su registro de
#      días hechos, hora y duración de las tareas (bloques de tiempo), historial de completados y
#      plantillas de día ───────────────────────────────────────────────────────────────────
def calendar_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
        start TEXT NOT NULL, end TEXT, all_day INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'evento',
        notes TEXT, location TEXT, reminder_min INTEGER, source TEXT NOT NULL DEFAULT 'panel',
        created_at REAL DEFAULT (unixepoch()), updated_at REAL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_start ON events(start)")
    for col, kind in (("due_time", "TEXT"), ("duration_min", "INTEGER"), ("repeat", "TEXT"), ("reminder_min", "INTEGER")):
        if not has_column(conn, "inbox", col):
            conn.execute(f"ALTER TABLE inbox ADD COLUMN {col} {kind}")
    conn.execute("""CREATE TABLE IF NOT EXISTS routine_checks (
        item_id INTEGER NOT NULL REFERENCES inbox(id) ON DELETE CASCADE, day TEXT NOT NULL, at REAL NOT NULL,
        PRIMARY KEY (item_id, day))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS item_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, action TEXT NOT NULL, day TEXT NOT NULL,
        text TEXT, type TEXT, at REAL NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_log_at ON item_log(at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS day_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
        created_at REAL DEFAULT (unixepoch()))""")


def calendar_down(conn: sqlite3.Connection) -> None:
    import json as _json
    conn.execute("CREATE TABLE IF NOT EXISTS calendar_r6_backup (tabla TEXT, datos TEXT)")
    for table in ("events", "routine_checks", "item_log", "day_templates"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            conn.execute("INSERT INTO calendar_r6_backup (tabla, datos) VALUES (?, ?)", (table, _json.dumps(rows, ensure_ascii=False)))
            conn.execute(f"DROP TABLE {table}")
    rows = [dict(r) for r in conn.execute("SELECT id, item_type, due_time, duration_min, repeat, reminder_min FROM inbox "
                                          "WHERE item_type='rutina' OR due_time IS NOT NULL OR duration_min IS NOT NULL OR repeat IS NOT NULL")] \
        if has_column(conn, "inbox", "repeat") else []
    conn.execute("INSERT INTO calendar_r6_backup (tabla, datos) VALUES ('inbox', ?)", (_json.dumps(rows, ensure_ascii=False),))
    conn.execute("UPDATE inbox SET item_type='tarea' WHERE item_type='rutina'")
    for col in ("due_time", "duration_min", "repeat", "reminder_min"):
        if has_column(conn, "inbox", col):
            conn.execute(f"ALTER TABLE inbox DROP COLUMN {col}")


# 11 ─ Plantillas de rutina (rutinas con pasos guardadas para reutilizarlas) ──────────────
def routine_templates_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS routine_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
        created_at REAL DEFAULT (unixepoch()))""")


def routine_templates_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS routine_templates")


# 12 ─ Tareas e ideas asociadas a una rutina o a uno de sus pasos (bloques del día) ─────────
def routine_step_up(conn: sqlite3.Connection) -> None:
    if not has_column(conn, "inbox", "routine_step"):
        conn.execute("ALTER TABLE inbox ADD COLUMN routine_step INTEGER")


def routine_step_down(conn: sqlite3.Connection) -> None:
    if has_column(conn, "inbox", "routine_step"):
        conn.execute("ALTER TABLE inbox DROP COLUMN routine_step")


# 13 ─ Economía: cuentas (lo que tienes), movimientos (gastos, ingresos y transferencias), deudas
#      (lo que te deben y lo que debes) y lista de deseos (lo que quieres comprar) ───────────────
FIN_TABLES = ("fin_accounts", "fin_movements", "fin_debts", "fin_wishes")


def finance_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, tipo TEXT NOT NULL DEFAULT 'banco',
        saldo_inicial REAL NOT NULL DEFAULT 0, orden INTEGER NOT NULL DEFAULT 0, archivada INTEGER NOT NULL DEFAULT 0,
        created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, importe REAL NOT NULL, tipo TEXT NOT NULL DEFAULT 'gasto',
        categoria TEXT, concepto TEXT, cuenta_id INTEGER, cuenta_destino INTEGER, notas TEXT,
        created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_movements_fecha ON fin_movements(fecha)")
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, persona TEXT NOT NULL, importe REAL NOT NULL, direccion TEXT NOT NULL DEFAULT 'me-deben',
        concepto TEXT, fecha TEXT, vence TEXT, saldada_at REAL, notas TEXT, created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_wishes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, precio REAL, url TEXT, prioridad TEXT, notas TEXT,
        comprado_at REAL, orden INTEGER NOT NULL DEFAULT 0, created_at REAL DEFAULT (unixepoch()))""")


def finance_down(conn: sqlite3.Connection) -> None:
    import json as _json
    conn.execute("CREATE TABLE IF NOT EXISTS finance_backup (tabla TEXT, datos TEXT)")  # nada se pierde al deshacer
    for table in FIN_TABLES:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            conn.execute("INSERT INTO finance_backup (tabla, datos) VALUES (?, ?)", (table, _json.dumps(rows, ensure_ascii=False)))
            conn.execute(f"DROP TABLE {table}")


# 14 ─ Tablero de una tarea: un tablero puede pertenecer a una tarea o idea (boards.item_id) ────────
def board_item_up(conn: sqlite3.Connection) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='boards'").fetchone():
        return  # sin la tabla no hay nada que cambiar (en la app, init_db la crea antes de migrar)
    if not has_column(conn, "boards", "item_id"):
        conn.execute("ALTER TABLE boards ADD COLUMN item_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_boards_item ON boards(item_id)")


def board_item_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_boards_item")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='boards'").fetchone() and has_column(conn, "boards", "item_id"):
        conn.execute("ALTER TABLE boards DROP COLUMN item_id")


# 15 ─ Economía: presupuesto mensual por categoría y movimientos que se repiten cada mes ───────────
def finance_plans_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_budgets (
        categoria TEXT PRIMARY KEY, importe REAL NOT NULL, created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_recurring (
        id INTEGER PRIMARY KEY AUTOINCREMENT, concepto TEXT NOT NULL, importe REAL NOT NULL, tipo TEXT NOT NULL DEFAULT 'gasto',
        categoria TEXT, cuenta_id INTEGER, dia INTEGER NOT NULL DEFAULT 1, activo INTEGER NOT NULL DEFAULT 1,
        desde TEXT NOT NULL, ultimo TEXT, created_at REAL DEFAULT (unixepoch()))""")


def finance_plans_down(conn: sqlite3.Connection) -> None:
    import json as _json
    conn.execute("CREATE TABLE IF NOT EXISTS finance_backup (tabla TEXT, datos TEXT)")
    for table in ("fin_budgets", "fin_recurring"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            conn.execute("INSERT INTO finance_backup (tabla, datos) VALUES (?, ?)", (table, _json.dumps(rows, ensure_ascii=False)))
            conn.execute(f"DROP TABLE {table}")


# 16 ─ Cada paso de rutina con su propia hora ─────────────────────────────────────────────────────
# Antes, un paso sin hora empezaba cuando acababa el anterior. Ya no hay encadenado: cada paso se queda
# con la hora que tenía, la del primer día de la semana en que toca (podía cambiar de un día a otro).

def step_times_up(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS step_times_backup (id INTEGER PRIMARY KEY)")
    hours = {}
    lunes = date(2026, 10, 26)
    for r in conn.execute("SELECT * FROM inbox WHERE item_type='rutina' AND parent_id IS NULL").fetchall():
        rule = routines.parse(r["repeat"])
        steps = conn.execute("SELECT * FROM inbox WHERE parent_id=? ORDER BY sort_order DESC, created_at DESC", (r["id"],)).fetchall()
        for d in (lunes + timedelta(days=i) for i in range(7)):
            if rule["freq"] != "weekly" or d.weekday() in rule["days"]:
                for s in routines.schedule(r["due_time"], [dict(x) for x in steps if routines.step_on(x, d)]):
                    if s["at"] and not s["due_time"]:
                        hours.setdefault(s["id"], s["at"])
    for sid, at in hours.items():
        conn.execute("INSERT INTO step_times_backup (id) VALUES (?)", (sid,))
        conn.execute("UPDATE inbox SET due_time=? WHERE id=?", (at, sid))


def step_times_down(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='step_times_backup'").fetchone():
        conn.execute("UPDATE inbox SET due_time=NULL WHERE id IN (SELECT id FROM step_times_backup)")
        conn.execute("DROP TABLE step_times_backup")


MIGRATIONS = [
    Migration(1, "inbox: un nivel de subelementos y tipo del padre", _inbox_one_level_up, _inbox_one_level_down),
    Migration(2, "baúl: orden manual (resources.sort_order)", resources_order_up, resources_order_down),
    Migration(3, "notas: orden manual dentro de su categoría (note_order)", note_order_up, note_order_down),
    Migration(4, "tableros: formato 2 (original en board_canvas_legacy)", boards_v2_up, boards_v2_down),
    Migration(5, "tableros: plantillas (board_templates)", board_templates_up, board_templates_down),
    Migration(6, "inbox: prioridad y categoría", inbox_meta_up, inbox_meta_down),
    Migration(7, "lista única: fecha, notas y casillas de las notas", items_up, items_down),
    Migration(8, "preferencias de interfaz (ui_prefs)", ui_prefs_up, ui_prefs_down),
    Migration(9, "enlaces tarea/idea ↔ nota (item_links)", item_links_up, item_links_down),
    Migration(10, "calendario: eventos, rutinas, bloques de tiempo, historial y plantillas de día", calendar_up, calendar_down),
    Migration(11, "plantillas de rutina (routine_templates)", routine_templates_up, routine_templates_down),
    Migration(12, "tareas asociadas a una rutina (inbox.routine_step)", routine_step_up, routine_step_down),
    Migration(13, "economía: cuentas, movimientos, deudas y lista de deseos", finance_up, finance_down),
    Migration(14, "tablero de una tarea (boards.item_id)", board_item_up, board_item_down),
    Migration(15, "economía: presupuestos por categoría y movimientos recurrentes", finance_plans_up, finance_plans_down),
    Migration(16, "rutinas: cada paso con su propia hora", step_times_up, step_times_down),
]
