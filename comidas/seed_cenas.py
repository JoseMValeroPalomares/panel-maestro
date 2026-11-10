"""
comidas/seed_cenas.py

Tanda de cenas nuevas (ligeras, con ingredientes que ya están en el catálogo).
Idempotente: si ya existe una comida con ese nombre, se salta.

Antes: cp comidas/data/comidas.db comidas/data/comidas.db.bak
Uso:   python comidas/seed_cenas.py
"""
import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "comidas.db")

# nombre, categoria, kcal, prot, hidratos, grasas, saturadas, trans, azucares, sal (por 100 g)
INGREDIENTES = [
    ("Alas de pollo", "proteina", 215, 18.0, 0.0, 15.0, 4.2, 0, 0.0, 0.15),
    ("Lenguado", "proteina", 83, 17.5, 0.0, 1.6, 0.4, 0, 0.0, 0.2),
]

# nombre, tags, tiempo_min, gramos_recomendados, instrucciones, ingredientes
CENAS = [
    ("Revuelto de gambas y espinacas", "proteina,verdura", 15, 300,
     ["Saltea el ajo y las espinacas en aceite.", "Añade las gambas y, al final, el huevo batido."],
     [("Gambas", 120), ("Espinacas", 120), ("Huevo", 100), ("Ajo", 5), ("Aceite de oliva", 10)]),
    ("Ensalada templada de queso de cabra", "vegetariano,verdura", 10, 280,
     ["Mezcla la rúcula, la lechuga y el tomate.", "Añade el queso de cabra y las nueces; alíñalo con aceite."],
     [("Rúcula", 60), ("Lechuga", 60), ("Tomate", 80), ("Queso de cabra", 60), ("Nueces", 15), ("Aceite de oliva", 10)]),
    ("Pechuga de pollo a la plancha con ensalada", "proteina,verdura", 15, 350,
     ["Marca la pechuga a la plancha.", "Sírvela con la lechuga, el tomate y el pepino aliñados."],
     [("Pechuga de pollo", 180), ("Lechuga", 80), ("Tomate", 80), ("Pepino", 60), ("Aceite de oliva", 10)]),
    ("Salmón a la plancha con brócoli", "pescado,verdura", 20, 350,
     ["Cuece el brócoli al vapor.", "Haz el salmón a la plancha y sírvelo con el brócoli."],
     [("Salmón fresco", 160), ("Brócoli", 200), ("Aceite de oliva", 10)]),
    ("Tortilla francesa con champiñones", "vegetariano,verdura", 10, 250,
     ["Saltea los champiñones.", "Añade el huevo batido y cuaja la tortilla."],
     [("Huevo", 150), ("Champiñones", 120), ("Aceite de oliva", 8)]),
    ("Crema de calabacín con queso fresco", "vegetariano,verdura", 25, 380,
     ["Sofríe la cebolla y el calabacín.", "Cubre con agua, cocina 15 minutos y tritura con el queso fresco."],
     [("Calabacín", 300), ("Cebolla", 60), ("Queso fresco", 50), ("Aceite de oliva", 8)]),
    ("Atún a la plancha con pimientos", "pescado,verdura", 20, 330,
     ["Saltea el pimiento y la cebolla.", "Marca el atún a la plancha y sírvelo encima."],
     [("Atún fresco", 160), ("Pimiento rojo", 100), ("Pimiento verde", 60), ("Cebolla", 40), ("Aceite de oliva", 10)]),
    ("Tosta de aguacate y huevo", "vegetariano", 10, 250,
     ["Tuesta el pan y aplasta el aguacate encima.", "Añade el huevo a la plancha."],
     [("Pan integral", 60), ("Aguacate", 80), ("Huevo", 100)]),
    ("Judías verdes con jamón y huevo", "verdura,proteina", 20, 330,
     ["Cuece las judías verdes.", "Saltéalas con el jamón y añade un huevo duro troceado."],
     [("Judía verde", 250), ("Jamón serrano", 30), ("Huevo", 60), ("Aceite de oliva", 8)]),
    ("Alas de pollo", "proteina", 40, 300,
     ["Salpimenta las alas y colócalas en la bandeja.",
      "Hornea 35-40 minutos a 200°C, dándoles la vuelta a mitad."],
     [("Alas de pollo", 300), ("Aceite de oliva", 5)]),
    ("Arroz con habichuelas", "legumbre,cereal integral", 35, 380,
     ["Sofríe la cebolla y el ajo.", "Añade las habichuelas, el arroz y agua o caldo.",
      "Cocina hasta que el arroz esté en su punto."],
     [("Alubias blancas cocidas", 150), ("Arroz blanco cocido", 120), ("Cebolla", 40), ("Ajo", 5), ("Aceite de oliva", 10)]),
    ("Lenguado a la plancha", "pescado", 15, 300,
     ["Salpimenta el lenguado y hazlo a la plancha unos 3 minutos por lado.",
      "Sírvelo con un chorrito de aceite de oliva."],
     [("Lenguado", 250), ("Aceite de oliva", 8)]),
    ("Macarrones integrales con calabacín y atún", "pescado,verdura,cereal integral", 20, 380,
     ["Cuece los macarrones integrales.", "Saltea el calabacín con la cebolla y añade el atún.",
      "Mezcla con la pasta."],
     [("Pasta integral cocida", 150), ("Calabacín", 150), ("Atún al natural", 80), ("Cebolla", 40), ("Aceite de oliva", 10)]),
    ("Macarrones integrales con calabacín", "verdura,vegetariano,cereal integral", 20, 340,
     ["Cuece los macarrones integrales.", "Saltea el calabacín con la cebolla y mézclalo con la pasta."],
     [("Pasta integral cocida", 150), ("Calabacín", 150), ("Cebolla", 40), ("Aceite de oliva", 10)]),
    ("Pucherito blanco", "legumbre,proteina,verdura", 60, 450,
     ["Cuece los garbanzos con el muslo de pollo, la panceta, la zanahoria y la judía verde.",
      "Añade la patata y cocina hasta que todo esté tierno."],
     [("Garbanzos cocidos", 120), ("Muslo de pollo", 100), ("Panceta", 20), ("Zanahoria", 60),
      ("Judía verde", 60), ("Patata cocida", 100)]),
    ("Carne con pimientos", "proteina,verdura", 25, 350,
     ["Saltea la ternera en tiras.", "Añade los pimientos y la cebolla y cocina hasta que estén tiernos."],
     [("Ternera magra", 150), ("Pimiento rojo", 100), ("Pimiento verde", 80), ("Cebolla", 50), ("Aceite de oliva", 10)]),
    ("Ensalada de quinoa con atún", "pescado,cereal integral", 15, 330,
     ["Mezcla la quinoa con el atún, el tomate y el pepino.", "Alíñalo con aceite de oliva."],
     [("Quinoa cocida", 120), ("Atún al natural", 80), ("Tomate", 80), ("Pepino", 60), ("Aceite de oliva", 10)]),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for ing in INGREDIENTES:
        c.execute("INSERT OR IGNORE INTO ingredients (nombre, categoria, kcal_100g, proteinas_100g,"
                  " carbohidratos_100g, grasas_100g, grasas_saturadas_100g, grasas_trans_100g,"
                  " azucares_100g, sal_100g) VALUES (?,?,?,?,?,?,?,?,?,?)", ing)
    ids = dict(c.execute("SELECT nombre, id FROM ingredients").fetchall())
    añadidas = 0
    for nombre, tags, tiempo, gramos, pasos, ings in CENAS:
        if c.execute("SELECT 1 FROM meals WHERE nombre=?", (nombre,)).fetchone():
            continue
        faltan = [n for n, _ in ings if n not in ids]
        if faltan:
            print(f"⚠ '{nombre}' omitida, faltan ingredientes: {', '.join(faltan)}")
            continue
        c.execute(
            "INSERT INTO meals (nombre, franja, tags, tiempo_preparacion_min, gramos_recomendados,"
            " es_racion_unica, instrucciones) VALUES (?, 'cena', ?, ?, ?, 0, ?)",
            (nombre, tags, tiempo, gramos, json.dumps(pasos)))
        mid = c.lastrowid
        c.executemany("INSERT INTO meal_ingredients (meal_id, ingredient_id, gramos) VALUES (?, ?, ?)",
                      [(mid, ids[n], g) for n, g in ings])
        añadidas += 1
    conn.commit()
    conn.close()
    print(f"Cenas añadidas: {añadidas}")


if __name__ == "__main__":
    seed()
