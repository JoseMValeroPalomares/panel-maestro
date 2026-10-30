"""Migraciones versionadas de comidas.db (ver core/migrations.py)."""
import sqlite3

from core.migrations import Migration, has_column

# Franjas de partida: (clave, nombre, orden, fracción de las kcal del día, hora, platos que la llenan)
FRANJAS_BASE = [
    ("desayuno", "Desayuno", 10, 0.25, "08:00", "desayuno"),
    ("media-manana", "Media mañana", 20, 0.0, "11:00", "merienda"),
    ("comida", "Comida", 30, 0.35, "14:00", "comida"),
    ("merienda", "Merienda", 40, 0.10, "17:30", "merienda"),
    ("cena", "Cena", 50, 0.30, "21:00", "cena"),
    ("extras", "Extras", 60, 0.0, None, "merienda"),
]


# 1 ─ Más comidas al día, platos con papel (primero, segundo…), plantillas y favoritos,
#     registro de peso y medidas, y lista de la compra de la semana sin duplicar ─────────
def ronda6_up(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS franjas (
        clave TEXT PRIMARY KEY, nombre TEXT NOT NULL, orden INTEGER NOT NULL DEFAULT 100,
        fraccion REAL NOT NULL DEFAULT 0, hora TEXT, catalogo TEXT, activa INTEGER NOT NULL DEFAULT 1,
        base INTEGER NOT NULL DEFAULT 0)""")
    for clave, nombre, orden, fraccion, hora, catalogo in FRANJAS_BASE:
        conn.execute("INSERT OR IGNORE INTO franjas (clave, nombre, orden, fraccion, hora, catalogo, activa, base) "
                     "VALUES (?, ?, ?, ?, ?, ?, 1, 1)", (clave, nombre, orden, fraccion, hora, catalogo))
    if not has_column(conn, "plan_items", "rol"):
        conn.execute("ALTER TABLE plan_items ADD COLUMN rol TEXT")
    if not has_column(conn, "weekly_plan", "rol"):
        conn.execute("ALTER TABLE weekly_plan ADD COLUMN rol TEXT")
    if not has_column(conn, "meals", "favorito"):
        conn.execute("ALTER TABLE meals ADD COLUMN favorito INTEGER DEFAULT 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS meal_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, franja TEXT,
        items TEXT NOT NULL DEFAULT '[]', favorito INTEGER DEFAULT 0, created_at REAL DEFAULT (unixepoch()))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS body_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL UNIQUE, peso_kg REAL,
        cintura_cm REAL, cadera_cm REAL, pecho_cm REAL, brazo_cm REAL, muslo_cm REAL, grasa_pct REAL,
        notas TEXT, created_at REAL DEFAULT (unixepoch()))""")
    for col, kind in (("plan_semana", "TEXT"), ("plan_gramos", "REAL")):
        if not has_column(conn, "shopping_list", col):
            conn.execute(f"ALTER TABLE shopping_list ADD COLUMN {col} {kind}")


def ronda6_down(conn: sqlite3.Connection) -> None:
    # Lo escrito en las tablas nuevas se pierde con ellas: se guarda antes
    conn.execute("CREATE TABLE IF NOT EXISTS ronda6_backup (tabla TEXT, datos TEXT)")
    import json
    for table in ("franjas", "meal_templates", "body_log"):
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            conn.execute("INSERT INTO ronda6_backup (tabla, datos) VALUES (?, ?)", (table, json.dumps(rows, ensure_ascii=False)))
            conn.execute(f"DROP TABLE {table}")
    for table, col in (("plan_items", "rol"), ("weekly_plan", "rol"), ("meals", "favorito"),
                       ("shopping_list", "plan_semana"), ("shopping_list", "plan_gramos")):
        if has_column(conn, table, col):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


# 2 ─ Días en que se usa cada franja (p. ej. sin media mañana el fin de semana).
#     NULL = todos los días; si no, lista JSON de días («lunes», …) ───────────────────────
def franja_dias_up(conn: sqlite3.Connection) -> None:
    if not has_column(conn, "franjas", "dias"):
        conn.execute("ALTER TABLE franjas ADD COLUMN dias TEXT")


def franja_dias_down(conn: sqlite3.Connection) -> None:
    if has_column(conn, "franjas", "dias"):
        conn.execute("ALTER TABLE franjas DROP COLUMN dias")


# 3 ─ Sin «media mañana» (el usuario no la usa): se borra la franja y sus huecos vacíos. Si tuviera
#     platos planificados no se pierden: se queda oculta. Se recrea al deshacer ───────────────
def sin_media_manana_up(conn: sqlite3.Connection) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='franjas'").fetchone():
        return
    usada = conn.execute("SELECT 1 FROM weekly_plan w WHERE w.franja='media-manana' AND (w.meal_id IS NOT NULL "
                         "OR EXISTS (SELECT 1 FROM plan_items p WHERE p.plan_id = w.id)) LIMIT 1").fetchone()
    if usada:
        conn.execute("UPDATE franjas SET activa=0 WHERE clave='media-manana'")
        return
    conn.execute("DELETE FROM weekly_plan WHERE franja='media-manana'")
    conn.execute("DELETE FROM franjas WHERE clave='media-manana'")


def sin_media_manana_down(conn: sqlite3.Connection) -> None:
    clave, nombre, orden, fraccion, hora, catalogo = FRANJAS_BASE[1]
    conn.execute("INSERT OR IGNORE INTO franjas (clave, nombre, orden, fraccion, hora, catalogo, activa, base) "
                 "VALUES (?, ?, ?, ?, ?, ?, 1, 1)", (clave, nombre, orden, fraccion, hora, catalogo))


MIGRATIONS = [
    Migration(1, "franjas, papel de los platos, plantillas, favoritos, peso y compra semanal", ronda6_up, ronda6_down),
    Migration(2, "franjas: días en que se usa cada una", franja_dias_up, franja_dias_down),
    Migration(3, "sin la franja «media mañana»", sin_media_manana_up, sin_media_manana_down),
]
