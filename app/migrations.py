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
        conn.execute(
            "INSERT OR IGNORE INTO inbox_r2_backup (id, parent_id, item_type, sort_order) VALUES (?, ?, ?, ?)",
            (r["id"], r["parent_id"], r["item_type"], r["sort_order"]),
        )

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
        conn.execute(
            "UPDATE inbox SET parent_id=?, item_type=?, sort_order=? WHERE id=?",
            (r["parent_id"], r["item_type"], r["sort_order"], r["id"]),
        )
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
        conn.execute(
            "INSERT OR REPLACE INTO board_canvas_legacy (board_id, data, report, migrated_at) VALUES (?, ?, ?, ?)",
            (r["board_id"], r["data"], json.dumps(report, ensure_ascii=False), time.time()),
        )
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
        conn.execute(
            "INSERT OR REPLACE INTO inbox_meta_backup (id, priority, category) "
            "SELECT id, priority, category FROM inbox WHERE priority IS NOT NULL OR category IS NOT NULL"
        )
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
    notes = (
        {r["id"]: r["content"] for r in conn.execute("SELECT id, content FROM notes WHERE encrypted=0")}
        if has_notes
        else {}
    )
    linked = has_column(conn, "inbox", "note_task")
    for r in conn.execute(
        f"SELECT id, content, {'note_id, note_task' if linked else 'NULL AS note_id, NULL AS note_task'} FROM inbox"
    ).fetchall():
        content, note_id, note_task = r["content"], r["note_id"], r["note_task"]
        if content and content.startswith("---"):
            content = re.sub(r"^---\s*", "", content)
        if note_task is not None and note_task not in {t["text"] for t in parse_tasks(notes.get(note_id) or "")}:
            note_id, note_task = None, None
        if (content, note_id, note_task) != (r["content"], r["note_id"], r["note_task"]):
            conn.execute(
                "INSERT OR IGNORE INTO inbox_r3_backup (id, content, note_id, note_task) VALUES (?, ?, ?, ?)",
                (r["id"], r["content"], r["note_id"], r["note_task"]),
            )
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
        conn.execute(
            "INSERT OR REPLACE INTO inbox_items_backup (id, due_date, details) "
            "SELECT id, due_date, details FROM inbox WHERE due_date IS NOT NULL OR details IS NOT NULL"
        )
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
    for col, kind in (
        ("due_time", "TEXT"),
        ("duration_min", "INTEGER"),
        ("repeat", "TEXT"),
        ("reminder_min", "INTEGER"),
    ):
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
            conn.execute(
                "INSERT INTO calendar_r6_backup (tabla, datos) VALUES (?, ?)",
                (table, _json.dumps(rows, ensure_ascii=False)),
            )
            conn.execute(f"DROP TABLE {table}")
    rows = (
        [
            dict(r)
            for r in conn.execute(
                "SELECT id, item_type, due_time, duration_min, repeat, reminder_min FROM inbox "
                "WHERE item_type='rutina' OR due_time IS NOT NULL OR duration_min IS NOT NULL OR repeat IS NOT NULL"
            )
        ]
        if has_column(conn, "inbox", "repeat")
        else []
    )
    conn.execute(
        "INSERT INTO calendar_r6_backup (tabla, datos) VALUES ('inbox', ?)", (_json.dumps(rows, ensure_ascii=False),)
    )
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
            conn.execute(
                "INSERT INTO finance_backup (tabla, datos) VALUES (?, ?)",
                (table, _json.dumps(rows, ensure_ascii=False)),
            )
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
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='boards'").fetchone() and has_column(
        conn, "boards", "item_id"
    ):
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
            conn.execute(
                "INSERT INTO finance_backup (tabla, datos) VALUES (?, ?)",
                (table, _json.dumps(rows, ensure_ascii=False)),
            )
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
        steps = conn.execute(
            "SELECT * FROM inbox WHERE parent_id=? ORDER BY sort_order DESC, created_at DESC", (r["id"],)
        ).fetchall()
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


# 17 ─ Auditoría de rendimiento ─────────────────────────────────────────────────
# Un registro por día (la noche anterior + el día), sus bloques de estudio, el objetivo de horas de cada
# asignatura (los exámenes salen del calendario), los umbrales de las reglas y las auditorías de la IA.
# Tablas nuevas: deshacer es borrarlas.


def rendimiento_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS rend_dias (
        fecha TEXT PRIMARY KEY,
        acostarse TEXT, despertar TEXT, calidad_sueno INTEGER, primer_cafe TEXT, pantallas_off TEXT,
        activacion TEXT, luz_solar INTEGER,
        dopamina INTEGER, dopamina_hora TEXT,
        siesta TEXT, comida_tarde TEXT,
        entreno INTEGER, entreno_fin TEXT, entreno_min INTEGER, entreno_intensidad INTEGER,
        energia INTEGER, niebla INTEGER, dolor_cabeza INTEGER, humor INTEGER,
        nota TEXT, creado REAL NOT NULL DEFAULT (unixepoch()), actualizado REAL NOT NULL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS rend_bloques (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL REFERENCES rend_dias(fecha) ON DELETE CASCADE,
        asignatura TEXT NOT NULL, minutos INTEGER NOT NULL, recall INTEGER NOT NULL DEFAULT 0,
        codificacion TEXT NOT NULL, pausas TEXT NOT NULL, caida TEXT, estado TEXT NOT NULL, orden INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rend_bloques_fecha ON rend_bloques(fecha)")
    conn.execute("CREATE TABLE IF NOT EXISTS rend_asignaturas (sigla TEXT PRIMARY KEY, objetivo_h REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS rend_ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    conn.execute("""CREATE TABLE IF NOT EXISTS rend_auditorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, periodo TEXT NOT NULL,
        proveedor TEXT, modelo TEXT, texto TEXT NOT NULL, creado REAL NOT NULL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rend_auditorias ON rend_auditorias(tipo, periodo)")


def rendimiento_down(conn: sqlite3.Connection) -> None:
    for t in ("rend_auditorias", "rend_ajustes", "rend_asignaturas", "rend_bloques", "rend_dias"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")


# 18 ─ Rendimiento: alertas guardadas y estado del router de IA ──────────────────
# Cada alerta que salta queda con su fecha (y la tarea que creó); el router guarda las peticiones de cada día
# por cuota, los modelos en enfriamiento tras un 429 y un registro corto de llamadas (sin contenido).
# La auditoría guarda el hash de lo que se envió, para no repetirla si nada cambió.


def rend_ia_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS rend_alertas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, regla TEXT NOT NULL, nivel TEXT NOT NULL,
        titulo TEXT NOT NULL, texto TEXT NOT NULL, item_id INTEGER, creado REAL NOT NULL DEFAULT (unixepoch()),
        UNIQUE (fecha, regla))""")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_uso (cuota TEXT NOT NULL, dia TEXT NOT NULL, peticiones INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (cuota, dia))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_enfriamiento (modelo TEXT PRIMARY KEY, hasta REAL NOT NULL, motivo TEXT)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS llm_registro (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, modelo TEXT NOT NULL, ok INTEGER NOT NULL,
        latencia_ms INTEGER, error TEXT)""")
    if not has_column(conn, "rend_auditorias", "entrada_hash"):
        conn.execute("ALTER TABLE rend_auditorias ADD COLUMN entrada_hash TEXT")


def rend_ia_down(conn: sqlite3.Connection) -> None:
    for t in ("llm_registro", "llm_enfriamiento", "llm_uso", "rend_alertas"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    if has_column(conn, "rend_auditorias", "entrada_hash"):
        conn.execute("ALTER TABLE rend_auditorias DROP COLUMN entrada_hash")


def yt_vistos_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS yt_vistos (
        video_id TEXT PRIMARY KEY, channel TEXT NOT NULL, title TEXT, seen_at REAL NOT NULL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_yt_vistos_channel ON yt_vistos(channel)")


def yt_vistos_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS yt_vistos")


# 20 ─ IA de las notas: política, catálogo de modelos y registro de correcciones ───
# El registro del router gana tokens, coste y para qué se usó (sin contenido). `ia_correcciones` guarda qué modelo
# corrigió cada nota y qué pasó con la propuesta; la versión previa a aplicarla está en data/versions (deshacer).


def ia_notas_up(conn: sqlite3.Connection) -> None:
    for col, tipo in (
        ("tokens_in", "INTEGER NOT NULL DEFAULT 0"),
        ("tokens_out", "INTEGER NOT NULL DEFAULT 0"),
        ("coste", "REAL NOT NULL DEFAULT 0"),
        ("uso", "TEXT"),
    ):
        if not has_column(conn, "llm_registro", col):
            conn.execute(f"ALTER TABLE llm_registro ADD COLUMN {col} {tipo}")
    conn.execute("CREATE TABLE IF NOT EXISTS ia_ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ia_catalogo (url TEXT PRIMARY KEY, modelos TEXT NOT NULL, at REAL NOT NULL)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS ia_correcciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT NOT NULL, modelo_id TEXT, proveedor TEXT, modelo TEXT,
        estado TEXT NOT NULL, partes INTEGER NOT NULL DEFAULT 0, aceptadas INTEGER NOT NULL DEFAULT 0,
        tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, coste REAL NOT NULL DEFAULT 0,
        version TEXT, creado REAL NOT NULL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ia_correcciones_nota ON ia_correcciones(note_id, creado)")


def ia_notas_down(conn: sqlite3.Connection) -> None:
    for t in ("ia_correcciones", "ia_catalogo", "ia_ajustes"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    for col in ("uso", "coste", "tokens_out", "tokens_in"):
        if has_column(conn, "llm_registro", col):
            conn.execute(f"ALTER TABLE llm_registro DROP COLUMN {col}")


# 21 ─ Grafo: nodos fijados y copia de las posiciones previas al último recolocado automático ─────


def graph_auto_up(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS graph_nodes (id TEXT PRIMARY KEY, x REAL, y REAL)"
    )  # en una BD en blanco aún no existe
    if not has_column(conn, "graph_nodes", "fijado"):
        conn.execute("ALTER TABLE graph_nodes ADD COLUMN fijado INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS graph_prev (id INTEGER PRIMARY KEY CHECK (id = 1), datos TEXT NOT NULL, at REAL NOT NULL)"
    )


def graph_auto_down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS graph_prev")
    if has_column(conn, "graph_nodes", "fijado"):
        conn.execute("ALTER TABLE graph_nodes DROP COLUMN fijado")


# 22 ─ Contextos (puntual / universidad / proyectos), asignaturas con sus temas, proyectos con sus
#      versiones; tareas, eventos y esquemas pueden ir a una asignatura o a un proyecto; las clases
#      son eventos que se repiten. Todo lo que ya había queda como «puntual». ──────────────────────
CTX_COLS = {
    "inbox": (
        ("contexto", "TEXT NOT NULL DEFAULT 'puntual'"),
        ("asignatura_id", "INTEGER"),
        ("proyecto_id", "INTEGER"),
        ("version_id", "INTEGER"),
        ("uni_tipo", "TEXT"),
        ("peso", "REAL"),
        ("nota", "REAL"),
        ("temas", "TEXT"),
        ("en_curso", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "events": (
        ("contexto", "TEXT NOT NULL DEFAULT 'puntual'"),
        ("asignatura_id", "INTEGER"),
        ("proyecto_id", "INTEGER"),
        ("repeat", "TEXT"),
        ("repeat_until", "TEXT"),
        ("peso", "REAL"),
        ("nota", "REAL"),
        ("temas", "TEXT"),
    ),
    "boards": (
        ("contexto", "TEXT NOT NULL DEFAULT 'puntual'"),
        ("proyecto_id", "INTEGER"),
        ("asignatura_id", "INTEGER"),
    ),
    "notes": (
        ("contexto", "TEXT NOT NULL DEFAULT 'puntual'"),
        ("asignatura_id", "INTEGER"),
        ("proyecto_id", "INTEGER"),
    ),
}
CTX_TABLES = ("asignaturas", "temas", "proyectos", "versiones", "contexto_meta")


def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def contexts_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS asignaturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, codigo TEXT NOT NULL UNIQUE COLLATE NOCASE,
        color TEXT, profesor TEXT, aula TEXT, semestre TEXT, alias TEXT NOT NULL DEFAULT '[]', carpeta TEXT,
        enlaces TEXT NOT NULL DEFAULT '[]', orden REAL NOT NULL DEFAULT 0, archivada INTEGER NOT NULL DEFAULT 0,
        sync_at REAL, created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS temas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        titulo TEXT NOT NULL, nombre_carpeta TEXT, ruta TEXT, tipo TEXT NOT NULL DEFAULT 'manual',
        grupo TEXT NOT NULL DEFAULT 'otros', estado TEXT NOT NULL DEFAULT 'sin-ver', note_id TEXT,
        orden REAL NOT NULL DEFAULT 0, titulo_manual INTEGER NOT NULL DEFAULT 0, falta_desde REAL,
        created_at REAL DEFAULT (unixepoch()), UNIQUE (asignatura_id, ruta))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_temas_asig ON temas(asignatura_id, orden)")
    conn.execute("""CREATE TABLE IF NOT EXISTS proyectos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
        descripcion TEXT, estado TEXT NOT NULL DEFAULT 'idea', color TEXT, repo_url TEXT, carpeta TEXT,
        enlaces TEXT NOT NULL DEFAULT '[]', note_id TEXT, orden REAL NOT NULL DEFAULT 0, created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS versiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, proyecto_id INTEGER NOT NULL REFERENCES proyectos(id),
        nombre TEXT NOT NULL, fecha_objetivo TEXT, estado TEXT NOT NULL DEFAULT 'abierta', changelog TEXT,
        cerrada_at REAL, created_at REAL DEFAULT (unixepoch()), UNIQUE (proyecto_id, nombre))""")
    conn.execute("CREATE TABLE IF NOT EXISTS contexto_meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    for table, cols in CTX_COLS.items():
        if not _table_exists(conn, table):
            continue
        for col, kind in cols:
            if not has_column(conn, table, col):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    if _table_exists(conn, "inbox"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_inbox_ctx ON inbox(contexto, asignatura_id, proyecto_id)")
    if _table_exists(conn, "events"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ctx ON events(contexto, asignatura_id)")
    # conteos de partida: el test de integridad y /api/contextos/integridad los comparan
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("inbox", "events", "boards", "notes")
        if _table_exists(conn, t)
    }
    conn.execute(
        "INSERT OR IGNORE INTO contexto_meta (clave, valor) VALUES ('conteos_previos', ?)", (json.dumps(counts),)
    )


def contexts_down(conn: sqlite3.Connection) -> None:
    """Guarda en contexto_backup lo que se quita (tablas nuevas y columnas) para que nada se pierda al deshacer."""
    conn.execute("CREATE TABLE IF NOT EXISTS contexto_backup (tabla TEXT, datos TEXT, at REAL)")
    now = time.time()
    for table in ("asignaturas", "temas", "proyectos", "versiones"):
        if _table_exists(conn, table):
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            conn.execute(
                "INSERT INTO contexto_backup VALUES (?, ?, ?)", (table, json.dumps(rows, ensure_ascii=False), now)
            )
    for table, cols in CTX_COLS.items():
        if not _table_exists(conn, table):
            continue
        names = [c for c, _ in cols if has_column(conn, table, c)]
        if names:
            rows = [dict(r) for r in conn.execute(f"SELECT id, {', '.join(names)} FROM {table}")]
            conn.execute(
                "INSERT INTO contexto_backup VALUES (?, ?, ?)",
                (f"{table}.columnas", json.dumps(rows, ensure_ascii=False), now),
            )
    conn.execute("DROP INDEX IF EXISTS idx_inbox_ctx")
    conn.execute("DROP INDEX IF EXISTS idx_events_ctx")
    for table, cols in CTX_COLS.items():
        if _table_exists(conn, table):
            for col, _ in cols:
                if has_column(conn, table, col):
                    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    for table in ("versiones", "temas", "proyectos", "asignaturas", "contexto_meta"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")


# 23 ─ Baúl: un recurso también puede ser de un contexto, una asignatura o un proyecto ───────────────
RES_CTX_COLS = (
    ("contexto", "TEXT NOT NULL DEFAULT 'puntual'"),
    ("asignatura_id", "INTEGER"),
    ("proyecto_id", "INTEGER"),
)


def resources_ctx_up(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "resources"):
        return
    for col, kind in RES_CTX_COLS:
        if not has_column(conn, "resources", col):
            conn.execute(f"ALTER TABLE resources ADD COLUMN {col} {kind}")


def resources_ctx_down(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "resources"):
        return
    names = [c for c, _ in RES_CTX_COLS if has_column(conn, "resources", c)]
    if names:
        conn.execute("CREATE TABLE IF NOT EXISTS contexto_backup (tabla TEXT, datos TEXT, at REAL)")
        rows = [dict(r) for r in conn.execute(f"SELECT id, {', '.join(names)} FROM resources")]
        conn.execute(
            "INSERT INTO contexto_backup VALUES ('resources.columnas', ?, ?)",
            (json.dumps(rows, ensure_ascii=False), time.time()),
        )
        for c in names:
            conn.execute(f"ALTER TABLE resources DROP COLUMN {c}")


# 24 ─ Tableros: revisión del lienzo (conflictos entre dispositivos) y copia previa para «Deshacer último guardado» ──
def board_rev_up(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "board_canvas") and not has_column(conn, "board_canvas", "rev"):
        conn.execute("ALTER TABLE board_canvas ADD COLUMN rev INTEGER NOT NULL DEFAULT 0")
    if _table_exists(conn, "board_canvas_prev_bak") and not _table_exists(conn, "board_canvas_prev"):
        conn.execute("ALTER TABLE board_canvas_prev_bak RENAME TO board_canvas_prev")  # vuelve lo que guardó la bajada
    conn.execute("""CREATE TABLE IF NOT EXISTS board_canvas_prev (
        board_id INTEGER PRIMARY KEY REFERENCES boards(id) ON DELETE CASCADE,
        data TEXT NOT NULL, rev INTEGER NOT NULL, saved_at REAL NOT NULL)""")


def board_rev_down(conn: sqlite3.Connection) -> None:
    # La copia previa no se tira: queda aparte y la subida la recupera
    if _table_exists(conn, "board_canvas_prev"):
        conn.execute("DROP TABLE IF EXISTS board_canvas_prev_bak")
        conn.execute("ALTER TABLE board_canvas_prev RENAME TO board_canvas_prev_bak")
    if _table_exists(conn, "board_canvas") and has_column(conn, "board_canvas", "rev"):
        conn.execute("ALTER TABLE board_canvas DROP COLUMN rev")


def sesiones_up(conn: sqlite3.Connection) -> None:
    """Contador en marcha (P-2): una sesión por cada vez que se empieza algo, con sus tramos (pausas entre medias).
    `activa` = 1 en la única sesión en marcha o en pausa (NULL en las cerradas): el índice único garantiza que no
    puede haber dos. Si una bajada guardó las tablas aparte, vuelven con sus datos."""
    for t in ("sesiones", "sesion_tramos"):
        if _table_exists(conn, f"{t}_bak") and not _table_exists(conn, t):
            conn.execute(f"ALTER TABLE {t}_bak RENAME TO {t}")
    conn.execute("""CREATE TABLE IF NOT EXISTS sesiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,  -- sin clave foránea: lo borrado vuelve de la papelera con su id y su tiempo
        titulo TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'libre',
        contexto TEXT,
        asignatura_id INTEGER,
        prevista_min INTEGER,
        dia TEXT NOT NULL,
        inicio REAL NOT NULL,
        fin REAL,
        cierre TEXT,
        activa INTEGER,
        latido REAL,
        auto_pausa REAL)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS sesiones_una_activa ON sesiones(activa) WHERE activa IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS sesiones_item ON sesiones(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS sesiones_dia ON sesiones(dia)")
    conn.execute("""CREATE TABLE IF NOT EXISTS sesion_tramos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sesion_id INTEGER NOT NULL REFERENCES sesiones(id) ON DELETE CASCADE,
        inicio REAL NOT NULL,
        fin REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS sesion_tramos_sesion ON sesion_tramos(sesion_id)")


def sesiones_down(conn: sqlite3.Connection) -> None:
    # Nada se tira: las tablas quedan aparte (`*_bak`) y la subida las recupera
    for t in ("sesion_tramos", "sesiones"):
        if _table_exists(conn, t):
            conn.execute(f"DROP TABLE IF EXISTS {t}_bak")
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_bak")
    for idx in ("sesiones_una_activa", "sesiones_item", "sesiones_dia", "sesion_tramos_sesion"):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")


# 26 ─ Universidad: archivos de cada tema (orden propio, «no encontrado», última página leída), temas
#      fusionados, carpetas descartadas en la propuesta y ejercicios asociables a uno o varios temas ─────────
UNI_TABLES = ("uni_archivos", "uni_ejercicios", "uni_ejercicio_temas")
UNI_COLS = {
    "temas": (("fusionado_en", "INTEGER"),),  # un tema fusionado se oculta y sus archivos van al otro
    "asignaturas": (("ignorar", "TEXT NOT NULL DEFAULT '[]'"), ("por_confirmar", "INTEGER NOT NULL DEFAULT 0")),
}


def uni_archivos_up(conn: sqlite3.Connection) -> None:
    """Solo añade: las asignaturas y los temas de siempre no cambian. Si una bajada guardó las tablas aparte
    (`*_bak`), vuelven con sus datos."""
    for t in UNI_TABLES:
        if _table_exists(conn, f"{t}_bak") and not _table_exists(conn, t):
            conn.execute(f"ALTER TABLE {t}_bak RENAME TO {t}")
    for table, cols in UNI_COLS.items():
        if not _table_exists(conn, table):
            continue
        for col, kind in cols:
            if not has_column(conn, table, col):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
        if _table_exists(conn, "contexto_backup"):  # lo que guardó una bajada vuelve a su sitio
            clave = f"{table}.columnas-26"
            row = conn.execute(
                "SELECT rowid, datos FROM contexto_backup WHERE tabla=? ORDER BY at DESC LIMIT 1", (clave,)
            ).fetchone()
            if row:
                for r in json.loads(row[1]):
                    names = [c for c, _ in cols if c in r]
                    conn.execute(
                        f"UPDATE {table} SET {', '.join(f'{c}=?' for c in names)} WHERE id=?",
                        (*[r[c] for c in names], r["id"]),
                    )
                conn.execute("DELETE FROM contexto_backup WHERE tabla=?", (clave,))
    conn.execute("""CREATE TABLE IF NOT EXISTS uni_archivos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL,
        tema_id INTEGER,                 -- NULL: su tema aún no está confirmado (o se quitó); conserva la página
        ruta TEXT NOT NULL,              -- relativa a la carpeta de la asignatura (solo lectura)
        nombre TEXT NOT NULL,
        ext TEXT NOT NULL DEFAULT '',
        bytes INTEGER,
        mtime REAL,
        orden REAL NOT NULL DEFAULT 0,
        tema_manual INTEGER NOT NULL DEFAULT 0,  -- movido a mano a otro tema: la sincronía no lo devuelve
        falta_desde REAL,
        pagina INTEGER,
        paginas INTEGER,
        leido_at REAL,
        created_at REAL DEFAULT (unixepoch()),
        UNIQUE (asignatura_id, ruta))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uni_archivos_tema ON uni_archivos(tema_id, orden)")
    conn.execute("""CREATE TABLE IF NOT EXISTS uni_ejercicios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL,
        titulo TEXT NOT NULL,
        enunciado TEXT,
        notas TEXT,
        estado TEXT NOT NULL DEFAULT 'pendiente',
        dificultad INTEGER,              -- 1 fácil, 2 media, 3 difícil
        archivo_id INTEGER,              -- el PDF donde está (opcional) y su página
        pagina INTEGER,
        orden REAL NOT NULL DEFAULT 0,
        hecho_at REAL,
        created_at REAL DEFAULT (unixepoch()),
        updated_at REAL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uni_ejercicios_asig ON uni_ejercicios(asignatura_id, orden)")
    conn.execute("""CREATE TABLE IF NOT EXISTS uni_ejercicio_temas (
        ejercicio_id INTEGER NOT NULL,
        tema_id INTEGER NOT NULL,
        PRIMARY KEY (ejercicio_id, tema_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uni_ejercicio_temas_tema ON uni_ejercicio_temas(tema_id)")


def uni_archivos_down(conn: sqlite3.Connection) -> None:
    # Nada se tira: las tablas quedan aparte (`*_bak`) y las columnas, en contexto_backup
    for t in UNI_TABLES:
        if _table_exists(conn, t):
            conn.execute(f"DROP TABLE IF EXISTS {t}_bak")
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_bak")
    for idx in (
        "idx_uni_archivos_tema",
        "idx_uni_ejercicios_asig",
        "idx_uni_ejercicio_temas_tema",
    ):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.execute("CREATE TABLE IF NOT EXISTS contexto_backup (tabla TEXT, datos TEXT, at REAL)")
    for table, cols in UNI_COLS.items():
        if not _table_exists(conn, table):
            continue
        names = [c for c, _ in cols if has_column(conn, table, c)]
        if not names:
            continue
        rows = [dict(r) for r in conn.execute(f"SELECT id, {', '.join(names)} FROM {table}")]
        conn.execute(
            "INSERT INTO contexto_backup VALUES (?, ?, ?)",
            (f"{table}.columnas-26", json.dumps(rows, ensure_ascii=False), time.time()),
        )
        for col in names:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


# 27 ─ Proyectos estilo gestor: prioridad, fechas y etiquetas del proyecto; título y descripción de cada versión;
#      comentarios y adjuntos de las tareas. Solo añade. Comentarios y adjuntos van por `item_id` SIN clave foránea
#      en cascada: al borrar una tarea se quedan (huérfanos) y, si se restaura desde la papelera con su mismo id,
#      vuelven solos; la purga diaria quita los huérfanos de más de 31 días (app/item_extras.purge_orphans).
PROY_TABLES = ("item_comentarios", "item_adjuntos")
PROY_COLS = {
    "proyectos": [
        ("prioridad", "TEXT"),  # alta / media / baja / NULL
        ("fecha_inicio", "TEXT"),  # AAAA-MM-DD
        ("fecha_fin", "TEXT"),  # objetivo
        ("etiquetas", "TEXT NOT NULL DEFAULT '[]'"),
    ],
    "versiones": [("titulo", "TEXT"), ("descripcion", "TEXT")],
}


def proyectos_gestor_up(conn: sqlite3.Connection) -> None:
    for t in PROY_TABLES:
        if _table_exists(conn, f"{t}_bak") and not _table_exists(conn, t):
            conn.execute(f"ALTER TABLE {t}_bak RENAME TO {t}")
    for table, cols in PROY_COLS.items():
        if not _table_exists(conn, table):
            continue
        for col, kind in cols:
            if not has_column(conn, table, col):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
        if _table_exists(conn, "contexto_backup"):  # lo que guardó una bajada vuelve a su sitio
            clave = f"{table}.columnas-27"
            row = conn.execute(
                "SELECT rowid, datos FROM contexto_backup WHERE tabla=? ORDER BY at DESC LIMIT 1", (clave,)
            ).fetchone()
            if row:
                for r in json.loads(row[1]):
                    names = [c for c, _ in cols if c in r]
                    conn.execute(
                        f"UPDATE {table} SET {', '.join(f'{c}=?' for c in names)} WHERE id=?",
                        (*[r[c] for c in names], r["id"]),
                    )
                conn.execute("DELETE FROM contexto_backup WHERE tabla=?", (clave,))
    conn.execute("""CREATE TABLE IF NOT EXISTS item_comentarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,        -- fila de inbox (sin cascada: ver arriba)
        texto TEXT NOT NULL,             -- Markdown
        created_at REAL DEFAULT (unixepoch()),
        updated_at REAL,
        huerfano_desde REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_comentarios_item ON item_comentarios(item_id, created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS item_adjuntos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        nombre TEXT NOT NULL,            -- nombre original (solo para mostrar y descargar)
        archivo TEXT NOT NULL UNIQUE,    -- relativo a data/adjuntos: <item>/<uuid>.<ext>
        mime TEXT,
        bytes INTEGER,
        created_at REAL DEFAULT (unixepoch()),
        huerfano_desde REAL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_adjuntos_item ON item_adjuntos(item_id, created_at)")


def proyectos_gestor_down(conn: sqlite3.Connection) -> None:
    # Nada se tira: las tablas quedan aparte (`*_bak`) y las columnas, en contexto_backup (los archivos no se tocan)
    for t in PROY_TABLES:
        if _table_exists(conn, t):
            conn.execute(f"DROP TABLE IF EXISTS {t}_bak")
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_bak")
    for idx in ("idx_item_comentarios_item", "idx_item_adjuntos_item"):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.execute("CREATE TABLE IF NOT EXISTS contexto_backup (tabla TEXT, datos TEXT, at REAL)")
    for table, cols in PROY_COLS.items():
        if not _table_exists(conn, table):
            continue
        names = [c for c, _ in cols if has_column(conn, table, c)]
        if not names:
            continue
        rows = [dict(r) for r in conn.execute(f"SELECT id, {', '.join(names)} FROM {table}")]
        conn.execute(
            "INSERT INTO contexto_backup VALUES (?, ?, ?)",
            (f"{table}.columnas-27", json.dumps(rows, ensure_ascii=False), time.time()),
        )
        for col in names:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


def uni_oculto_up(conn: sqlite3.Connection) -> None:
    """Solo añade: `uni_archivos.oculto` = quitado a mano de su tema (la sincronía no lo vuelve a poner)."""
    if _table_exists(conn, "uni_archivos") and not has_column(conn, "uni_archivos", "oculto"):
        conn.execute("ALTER TABLE uni_archivos ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0")


def uni_oculto_down(conn: sqlite3.Connection) -> None:
    # Lo quitado vuelve a verse en su tema: no se pierde nada que no se pueda rehacer a mano
    if _table_exists(conn, "uni_archivos") and has_column(conn, "uni_archivos", "oculto"):
        conn.execute("ALTER TABLE uni_archivos DROP COLUMN oculto")


def archivada_up(conn: sqlite3.Connection) -> None:
    """Solo añade: `inbox.archivada` = cuándo se mandó una tarea hecha al historial de su proyecto (NULL = a la vista)."""
    if not has_column(conn, "inbox", "archivada"):
        conn.execute("ALTER TABLE inbox ADD COLUMN archivada REAL")


def archivada_down(conn: sqlite3.Connection) -> None:
    # Lo archivado vuelve a verse junto a lo pendiente: no se pierde ninguna tarea
    if has_column(conn, "inbox", "archivada"):
        conn.execute("ALTER TABLE inbox DROP COLUMN archivada")


def facturas_up(conn: sqlite3.Connection) -> None:
    """Facturas de Economía: el archivo vive en data/facturas/<uuid>.<ext>; la fila guarda lo que se ve y se busca."""
    if _table_exists(conn, "fin_facturas_bak") and not _table_exists(conn, "fin_facturas"):
        conn.execute("ALTER TABLE fin_facturas_bak RENAME TO fin_facturas")
    conn.execute("""CREATE TABLE IF NOT EXISTS fin_facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,            -- lo que se lee en la lista (por defecto, el nombre del archivo)
        proveedor TEXT,
        fecha TEXT,                      -- AAAA-MM-DD (la de la factura)
        importe REAL,                    -- euros, opcional
        categoria TEXT,
        notas TEXT,
        movimiento_id INTEGER,           -- gasto al que corresponde (sin clave foránea: borrar el gasto no la toca)
        nombre TEXT NOT NULL,            -- nombre original del archivo (solo para mostrar y descargar)
        archivo TEXT NOT NULL UNIQUE,    -- relativo a data/facturas
        mime TEXT,
        bytes INTEGER,
        created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_facturas_fecha ON fin_facturas(fecha)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_facturas_mov ON fin_facturas(movimiento_id)")


def facturas_down(conn: sqlite3.Connection) -> None:
    # Nada se tira: la tabla queda aparte y los archivos no se tocan
    conn.execute("DROP INDEX IF EXISTS idx_fin_facturas_fecha")
    conn.execute("DROP INDEX IF EXISTS idx_fin_facturas_mov")
    if _table_exists(conn, "fin_facturas"):
        conn.execute("DROP TABLE IF EXISTS fin_facturas_bak")
        conn.execute("ALTER TABLE fin_facturas RENAME TO fin_facturas_bak")


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
    Migration(
        10, "calendario: eventos, rutinas, bloques de tiempo, historial y plantillas de día", calendar_up, calendar_down
    ),
    Migration(11, "plantillas de rutina (routine_templates)", routine_templates_up, routine_templates_down),
    Migration(12, "tareas asociadas a una rutina (inbox.routine_step)", routine_step_up, routine_step_down),
    Migration(13, "economía: cuentas, movimientos, deudas y lista de deseos", finance_up, finance_down),
    Migration(14, "tablero de una tarea (boards.item_id)", board_item_up, board_item_down),
    Migration(
        15, "economía: presupuestos por categoría y movimientos recurrentes", finance_plans_up, finance_plans_down
    ),
    Migration(16, "rutinas: cada paso con su propia hora", step_times_up, step_times_down),
    Migration(
        17,
        "rendimiento: registro diario, bloques de estudio, asignaturas, ajustes y auditorías",
        rendimiento_up,
        rendimiento_down,
    ),
    Migration(18, "rendimiento: alertas guardadas, uso y enfriamiento del router de IA", rend_ia_up, rend_ia_down),
    Migration(
        19, "extensión: vídeos de YouTube vistos de los canales del Baúl (yt_vistos)", yt_vistos_up, yt_vistos_down
    ),
    Migration(20, "IA de las notas: política, catálogo de modelos y correcciones (ia_*)", ia_notas_up, ia_notas_down),
    Migration(21, "grafo: nodos fijados y copia previa al recolocado automático", graph_auto_up, graph_auto_down),
    Migration(
        22, "contextos: asignaturas, temas, proyectos, versiones y clases que se repiten", contexts_up, contexts_down
    ),
    Migration(23, "baúl: contexto, asignatura o proyecto de cada recurso", resources_ctx_up, resources_ctx_down),
    Migration(
        24, "tableros: revisión del lienzo y copia previa (conflictos entre dispositivos)", board_rev_up, board_rev_down
    ),
    Migration(25, "contador en marcha: sesiones y sus tramos (P-2)", sesiones_up, sesiones_down),
    Migration(
        26,
        "universidad: archivos de cada tema, temas fusionados, última página leída y ejercicios",
        uni_archivos_up,
        uni_archivos_down,
    ),
    Migration(
        27,
        "proyectos: prioridad, fechas y etiquetas; versiones con título y descripción; comentarios y adjuntos",
        proyectos_gestor_up,
        proyectos_gestor_down,
    ),
    Migration(
        28,
        "universidad: quitar un archivo de su tema sin tocar el disco (uni_archivos.oculto)",
        uni_oculto_up,
        uni_oculto_down,
    ),
    Migration(29, "proyectos: historial de tareas hechas (inbox.archivada)", archivada_up, archivada_down),
    Migration(30, "economía: facturas guardadas (fin_facturas)", facturas_up, facturas_down),
]
