"""
comidas/bulk_edit_meals.py

Herramienta generica para aplicar cambios masivos a todas las comidas
ya guardadas en la base de datos. Pensado como plantilla: cada funcion
de mas abajo es una operacion independiente que puedes activar o no
desde el bloque main() al final.

SIEMPRE haz una copia de comidas/data/comidas.db antes de ejecutar esto,
por si quieres revertir:
    cp comidas/data/comidas.db comidas/data/comidas.db.bak

Uso: python comidas/bulk_edit_meals.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "comidas.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_raciones_to_one(conn, dry_run=True):
    """Pone raciones=1 en TODAS las comidas. Preparacion para eliminar
    el concepto de 'raciones' del sistema: al quedar todas en 1, el
    total de la receta y el 'por racion' coinciden, y no cambia ningun
    numero que ya estuviera mostrandose 'por racion' en la app."""
    rows = conn.execute("SELECT id, nombre, raciones FROM meals WHERE raciones != 1").fetchall()
    print(f"Comidas con raciones != 1: {len(rows)}")
    for r in rows:
        print(f"  [{r['id']}] {r['nombre']}: raciones {r['raciones']} -> 1")
    if not dry_run:
        conn.execute("UPDATE meals SET raciones = 1")
        conn.commit()
        print(f"✓ Actualizado: {len(rows)} comidas puestas a raciones=1")
    else:
        print("(dry_run=True, no se ha escrito nada. Cambia a dry_run=False para aplicar)")


def bulk_update_field(conn, table, field, new_value, where_sql="", where_params=(), dry_run=True):
    """Generico: cambia 'field' a 'new_value' en 'table', opcionalmente
    filtrando con where_sql (ej. "WHERE franja = ?", ("cena",)).
    Ejemplo de uso:
        bulk_update_field(conn, "meals", "image_source", "unsplash", dry_run=False)
    """
    query = f"SELECT id FROM {table} {where_sql}"
    rows = conn.execute(query, where_params).fetchall()
    print(f"Filas afectadas en {table}.{field}: {len(rows)}")
    if not dry_run:
        conn.execute(f"UPDATE {table} SET {field} = ? {where_sql}", (new_value, *where_params))
        conn.commit()
        print(f"✓ Actualizado {table}.{field} = {new_value!r} en {len(rows)} filas")
    else:
        print("(dry_run=True, no se ha escrito nada)")


def scale_ingredient_quantity_in_all_meals(conn, ingredient_name, factor, dry_run=True):
    """Multiplica por 'factor' la cantidad en gramos de un ingrediente
    concreto en TODAS las recetas donde aparezca. Util si, por ejemplo,
    decides que todas las raciones de 'Arroz blanco cocido' deben pesar
    un 10% menos: factor=0.9."""
    ing = conn.execute("SELECT id FROM ingredients WHERE nombre = ?", (ingredient_name,)).fetchone()
    if not ing:
        print(f"⚠ Ingrediente '{ingredient_name}' no encontrado")
        return
    rows = conn.execute("""
        SELECT mi.id, mi.gramos, m.nombre as meal_nombre
        FROM meal_ingredients mi JOIN meals m ON m.id = mi.meal_id
        WHERE mi.ingredient_id = ?
    """, (ing["id"],)).fetchall()
    print(f"'{ingredient_name}' aparece en {len(rows)} recetas:")
    for r in rows:
        new_gramos = round(r["gramos"] * factor, 1)
        print(f"  {r['meal_nombre']}: {r['gramos']}g -> {new_gramos}g")
        if not dry_run:
            conn.execute("UPDATE meal_ingredients SET gramos = ? WHERE id = ?", (new_gramos, r["id"]))
    if not dry_run:
        conn.commit()
        print("✓ Actualizado")
    else:
        print("(dry_run=True, no se ha escrito nada)")


def add_default_grams_column_preview(conn):
    """Solo lectura: muestra cuántos gramos pesa hoy cada receta completa
    y por ración, para que decidas manualmente los gramos recomendados
    de cada plato antes de migrar a la nueva columna en el chat nuevo."""
    meals = conn.execute("SELECT * FROM meals ORDER BY franja, nombre").fetchall()
    for meal in meals:
        total = conn.execute("""
            SELECT SUM(gramos) as g FROM meal_ingredients WHERE meal_id = ?
        """, (meal["id"],)).fetchone()["g"] or 0
        raciones = max(1, meal["raciones"])
        print(f"[{meal['id']:>3}] {meal['nombre']:<45} total={total:>6.0f}g  "
              f"por_racion={total/raciones:>6.0f}g")


if __name__ == "__main__":
    conn = get_conn()

    # 1) Vista previa de gramos por receta y por ración (solo lectura,
    #    util para decidir a mano los "gramos recomendados" de cada plato
    #    antes de la migracion que harás en el chat nuevo).
    print("\n--- Vista previa de gramos por receta ---")
    add_default_grams_column_preview(conn)

    # 2) Poner raciones=1 en todas las comidas (preparación para
    #    eliminar el concepto de "raciones"). Cambia a dry_run=False
    #    cuando quieras aplicarlo de verdad.
    print("\n--- Normalizar raciones a 1 ---")
    normalize_raciones_to_one(conn, dry_run=True)

    conn.close()
