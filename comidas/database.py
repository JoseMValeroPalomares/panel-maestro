"""
comidas/database.py

Esquema para el catalogo de ingredientes, comidas con macros calculados a
partir de sus ingredientes, planificador semanal, lista de la compra
agregada, y perfil de usuario con objetivos nutricionales.

Cada comida del catalogo tiene:
  - gramos_recomendados: racion ESTANDAR de ese plato (editable, con
    sugerencia automatica). Es lo que se ve en la ficha/tarjeta.
  - es_racion_unica: si esta activo, la receta completa (tal cual esta
    escrita) YA ES la racion, sin ningun escalado (batidos, cremas
    individuales...).

Cada celda del planificador semanal (weekly_plan) puede llevar, ADEMAS,
su propia "gramos_racion": los gramos de ESE plato que el generador ha
calculado para esa franja concreta de ese dia concreto, para que la
suma del dia encaje con tu objetivo real de kcal/proteina del perfil.
Si gramos_racion es NULL (asignacion manual, o comida sin pasar por el
generador), se usa la racion estandar del catalogo tal cual.
"""
import time

from core import config
from core.db import connect, db_session, enable_wal

DB_PATH = str(config.COMIDAS_DB)

def get_db_connection():
    """Conexión suelta (con WAL/busy_timeout/foreign_keys). Preferir get_db()."""
    return connect(DB_PATH)

def get_db():
    """Context manager: commit/rollback automático y cierre garantizado."""
    return db_session(DB_PATH)

def _add_columns(c, table: str, columns: dict[str, str]) -> None:
    """Migración aditiva: añade solo las columnas que falten (nunca borra)."""
    c.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in c.fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    enable_wal(DB_PATH)
    conn = get_db_connection()
    c = conn.cursor()

    # ── Migracion de seguridad: si "ingredients" existe con un esquema muy
    # antiguo (sin "nombre"), NO se borra: se renombra para conservar sus
    # datos y se crea la tabla nueva abajo.
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ingredients'")
    if c.fetchone():
        c.execute("PRAGMA table_info(ingredients)")
        existing_cols = {row[1] for row in c.fetchall()}
        if "nombre" not in existing_cols:
            c.execute(f"ALTER TABLE ingredients RENAME TO ingredients_legacy_{int(time.time())}")

    c.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            categoria TEXT DEFAULT 'General',
            kcal_100g REAL DEFAULT 0,
            proteinas_100g REAL DEFAULT 0,
            carbohidratos_100g REAL DEFAULT 0,
            grasas_100g REAL DEFAULT 0,
            grasas_saturadas_100g REAL DEFAULT 0,
            grasas_trans_100g REAL DEFAULT 0,
            azucares_100g REAL DEFAULT 0,
            sal_100g REAL DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            franja TEXT DEFAULT 'comida',
            tags TEXT DEFAULT '',
            tiempo_preparacion_min INTEGER DEFAULT 0,
            gramos_recomendados REAL DEFAULT 300,
            es_racion_unica INTEGER DEFAULT 0,
            instrucciones TEXT DEFAULT '[]',
            image_url TEXT DEFAULT '',
            image_source TEXT DEFAULT 'pexels',
            created_at REAL DEFAULT (unixepoch())
        )
    ''')

    # ── Migracion: comidas creadas con esquemas anteriores ──
    c.execute("PRAGMA table_info(meals)")
    meal_cols = {row[1] for row in c.fetchall()}
    if "gramos_recomendados" not in meal_cols:
        c.execute("ALTER TABLE meals ADD COLUMN gramos_recomendados REAL DEFAULT 300")
    if "es_racion_unica" not in meal_cols:
        c.execute("ALTER TABLE meals ADD COLUMN es_racion_unica INTEGER DEFAULT 0")
    # (La columna antigua "raciones", si existe, se deja tal cual: no se borran datos.)

    c.execute('''
        CREATE TABLE IF NOT EXISTS meal_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            gramos REAL NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER REFERENCES ingredients(id),
            nombre_libre TEXT,
            cantidad_gramos REAL DEFAULT 0,
            comprado INTEGER DEFAULT 0,
            source TEXT DEFAULT 'manual',
            source_meal_id INTEGER REFERENCES meals(id),
            created_at REAL DEFAULT (unixepoch())
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS meal_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
            semana TEXT NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS weekly_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana TEXT NOT NULL,
            dia TEXT NOT NULL,
            franja TEXT NOT NULL,
            meal_id INTEGER REFERENCES meals(id),
            is_fixed INTEGER DEFAULT 0,
            gramos_racion REAL,
            UNIQUE(semana, dia, franja)
        )
    ''')

    # ── Migracion: celdas del planificador creadas antes de tener
    # racion personalizada por celda ──
    c.execute("PRAGMA table_info(weekly_plan)")
    plan_cols = {row[1] for row in c.fetchall()}
    if "gramos_racion" not in plan_cols:
        c.execute("ALTER TABLE weekly_plan ADD COLUMN gramos_racion REAL")

    c.execute('''
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            edad INTEGER DEFAULT 28,
            peso_kg REAL DEFAULT 75,
            altura_cm REAL DEFAULT 175,
            sexo TEXT DEFAULT 'hombre',
            nivel_actividad REAL DEFAULT 1.55,
            objetivo TEXT DEFAULT 'mantener',
            proteina_g_kg REAL DEFAULT 1.6
        )
    ''')
    c.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1)")

    # ── Fase 5: unidades, varios platos por comida y reparto configurable ──
    _add_columns(c, "ingredients", {
        "gramos_por_unidad": "REAL",      # p. ej. 1 huevo = 60 g; NULL si no se mide en unidades
        "unidad_nombre": "TEXT",          # "huevo", "rebanada"...
    })
    _add_columns(c, "meal_ingredients", {"unidades": "REAL"})
    _add_columns(c, "user_profile", {
        "grasa_pct": "REAL DEFAULT 25",   # % de la energía que viene de la grasa
        "ajuste_pct": "REAL",             # NULL = el del objetivo (definición -20, volumen +10)
    })
    # Platos ADICIONALES de una comida del plan. El plato principal sigue en
    # weekly_plan.meal_id (lo rellena el generador); aquí van los demás
    # (ensalada, postre, pan...), cada uno con sus gramos.
    c.execute('''
        CREATE TABLE IF NOT EXISTS plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES weekly_plan(id) ON DELETE CASCADE,
            meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
            gramos_racion REAL,
            orden INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch())
        )
    ''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON plan_items(plan_id)")

    c.execute("CREATE INDEX IF NOT EXISTS idx_meal_ingredients_meal ON meal_ingredients(meal_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shopping_ingredient ON shopping_list(ingredient_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_weekly_plan_semana ON weekly_plan(semana)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_meal_usage_meal ON meal_usage_log(meal_id)")

    conn.commit()
    conn.close()

    # Migraciones versionadas (reversibles): comidas/migrations.py
    from comidas.migrations import MIGRATIONS
    from core.migrations import apply_pending
    mconn = connect(DB_PATH)
    mconn.isolation_level = None
    try:
        apply_pending(mconn, MIGRATIONS)
    finally:
        mconn.close()


if __name__ == "__main__":
    init_db()
    print(f"Base de datos inicializada en {DB_PATH}")
