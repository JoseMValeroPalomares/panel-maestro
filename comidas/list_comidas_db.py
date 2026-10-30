"""
comidas/list_comidas_db.py

Vuelca el contenido completo de la base de datos de Comidas a consola
y a tres CSV (ingredients.csv, meals.csv, meal_ingredients.csv) dentro
de comidas/data/export/, para poder revisarlo o compartirlo facilmente
(por ejemplo, pegandolo en otra conversacion).

No modifica nada, es de solo lectura.

Uso: python comidas/list_comidas_db.py
"""
import sqlite3
import os
import csv
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "comidas.db")
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "data", "export")


def main():
    os.makedirs(EXPORT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ── Ingredientes ─────────────────────────────────────────
    ingredients = c.execute("SELECT * FROM ingredients ORDER BY nombre").fetchall()
    print(f"\n{'='*70}\nINGREDIENTES ({len(ingredients)})\n{'='*70}")
    for ing in ingredients:
        print(f"[{ing['id']:>3}] {ing['nombre']:<35} {ing['categoria']:<10} "
              f"{ing['kcal_100g']:>6.1f} kcal | P:{ing['proteinas_100g']:>5.1f}g "
              f"C:{ing['carbohidratos_100g']:>5.1f}g G:{ing['grasas_100g']:>5.1f}g "
              f"| sal:{ing['sal_100g']}g")

    with open(os.path.join(EXPORT_DIR, "ingredients.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ing.keys()) if ingredients else None
        for ing in ingredients:
            writer.writerow(list(ing))

    # ── Comidas + sus ingredientes ───────────────────────────
    meals = c.execute("SELECT * FROM meals ORDER BY franja, nombre").fetchall()
    print(f"\n{'='*70}\nCOMIDAS ({len(meals)})\n{'='*70}")

    meal_rows_for_csv = []
    meal_ing_rows_for_csv = []

    for meal in meals:
        ing_rows = c.execute("""
            SELECT i.nombre, i.categoria, mi.gramos, i.kcal_100g, i.proteinas_100g,
                   i.carbohidratos_100g, i.grasas_100g
            FROM meal_ingredients mi JOIN ingredients i ON i.id = mi.ingredient_id
            WHERE mi.meal_id = ?
        """, (meal["id"],)).fetchall()

        total_kcal = sum(r["kcal_100g"] * r["gramos"] / 100 for r in ing_rows)
        total_prot = sum(r["proteinas_100g"] * r["gramos"] / 100 for r in ing_rows)
        total_carb = sum(r["carbohidratos_100g"] * r["gramos"] / 100 for r in ing_rows)
        total_fat = sum(r["grasas_100g"] * r["gramos"] / 100 for r in ing_rows)
        total_gramos = sum(r["gramos"] for r in ing_rows)
        raciones = max(1, meal["raciones"])

        print(f"\n[{meal['id']:>3}] {meal['nombre']}  ({meal['franja']}, raciones={meal['raciones']}, "
              f"tiempo={meal['tiempo_preparacion_min']}min, tags='{meal['tags']}')")
        print(f"      Total receta: {total_gramos:.0f}g | {total_kcal:.0f} kcal | "
              f"P:{total_prot:.1f}g C:{total_carb:.1f}g G:{total_fat:.1f}g")
        print(f"      Por ración (÷{raciones}): {total_gramos/raciones:.0f}g | {total_kcal/raciones:.0f} kcal | "
              f"P:{total_prot/raciones:.1f}g C:{total_carb/raciones:.1f}g G:{total_fat/raciones:.1f}g")
        for r in ing_rows:
            print(f"        - {r['nombre']:<30} {r['gramos']:>6.0f} g")
            meal_ing_rows_for_csv.append([meal["id"], meal["nombre"], r["nombre"], r["gramos"]])

        meal_rows_for_csv.append([
            meal["id"], meal["nombre"], meal["franja"], meal["tags"],
            meal["tiempo_preparacion_min"], meal["raciones"], total_gramos,
            round(total_kcal, 1), round(total_prot, 1), round(total_carb, 1), round(total_fat, 1),
            round(total_kcal / raciones, 1), round(total_prot / raciones, 1),
            round(total_carb / raciones, 1), round(total_fat / raciones, 1),
        ])

    with open(os.path.join(EXPORT_DIR, "meals.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "nombre", "franja", "tags", "tiempo_min", "raciones", "gramos_totales",
                          "kcal_total", "prot_total", "carb_total", "fat_total",
                          "kcal_por_racion", "prot_por_racion", "carb_por_racion", "fat_por_racion"])
        writer.writerows(meal_rows_for_csv)

    with open(os.path.join(EXPORT_DIR, "meal_ingredients.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["meal_id", "meal_nombre", "ingrediente", "gramos"])
        writer.writerows(meal_ing_rows_for_csv)

    conn.close()
    print(f"\n{'='*70}")
    print(f"✓ Exportado a: {EXPORT_DIR}")
    print(f"  - ingredients.csv ({len(ingredients)} filas)")
    print(f"  - meals.csv ({len(meals)} filas)")
    print(f"  - meal_ingredients.csv ({len(meal_ing_rows_for_csv)} filas)")


if __name__ == "__main__":
    main()
