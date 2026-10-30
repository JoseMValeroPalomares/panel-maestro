"""
comidas/seed_data_5.py

Quinta tanda: refuerzo grande de DESAYUNO, MERIENDA y CENA (12 de cada,
36 en total) para que el generador semanal tenga de verdad donde elegir
en esas franjas sin repetir jamon todo el rato. Incluye mas pescado en
cena (sardinas, caballa, pulpo, boquerones, merluza), mas fruta y
frutos secos en desayuno/merienda, y opciones vegetarianas ligeras para
cena (cremas, revueltos, ensaladas).

Idempotente: si un ingrediente o una comida con ese nombre ya existe,
se salta sin tocarlo. Pensado para ejecutarse DESPUES de seed_data_4.py
(reutiliza varios ingredientes que anadio ese script: Miel, Frutos
rojos, Frutos secos variados, Espargagos verdes, Pepino, Pan integral).

SIEMPRE haz una copia antes de ejecutar:
    cp comidas/data/comidas.db comidas/data/comidas.db.bak

Uso: python comidas/seed_data_5.py
"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "comidas.db")

IMGPOOL = [
    "https://images.unsplash.com/photo-1533089860892-a7c6f0a88666?w600",
    "https://images.unsplash.com/photo-1525351484163-7529414344d8?w600",
    "https://images.unsplash.com/photo-1495521821757-a1efb6729352?w600",
    "https://images.unsplash.com/photo-1490474418585-ba9bad8fd0ea?w600",
    "https://images.unsplash.com/photo-1476718406336-bb5a9690ee2a?w600",
    "https://images.unsplash.com/photo-1594212699903-ec8a3eca50f5?w600",
]

# nombre, categoria, kcal_100g, proteinas_100g, carbohidratos_100g,
# grasas_100g, grasas_saturadas_100g, grasas_trans_100g, azucares_100g, sal_100g
NEW_INGREDIENTS = [
    ("Pavo fiambre", "proteina", 104, 17.0, 1.0, 3.5, 1.0, 0, 0.5, 1.8),
    ("Requesón", "lacteo", 98, 11.0, 3.4, 4.0, 2.5, 0, 3.0, 0.3),
    ("Mermelada", "General", 250, 0.3, 62.0, 0, 0, 0, 60.0, 0.02),
    ("Cacao puro en polvo", "General", 228, 20.0, 11.0, 14.0, 8.0, 0, 1.0, 0.02),
    ("Nueces", "grasa", 654, 15.0, 14.0, 65.0, 6.0, 0, 2.6, 0.002),
    ("Almendras", "grasa", 579, 21.0, 22.0, 50.0, 4.0, 0, 4.4, 0.001),
    ("Kiwi", "fruta", 61, 1.1, 15.0, 0.5, 0, 0, 9.0, 0.003),
    ("Manzana", "fruta", 52, 0.3, 14.0, 0.2, 0, 0, 10.0, 0.001),
    ("Pera", "fruta", 57, 0.4, 15.0, 0.1, 0, 0, 10.0, 0.001),
    ("Naranja", "fruta", 47, 0.9, 12.0, 0.1, 0, 0, 9.0, 0.001),
    ("Pan de centeno", "cereal", 259, 8.5, 48.0, 3.3, 0.4, 0, 3.0, 1.3),
    ("Queso curado", "lacteo", 400, 25.0, 1.3, 33.0, 21.0, 0, 0.5, 1.8),
    ("Sardinas en lata", "proteina", 208, 25.0, 0, 11.5, 3.0, 0, 0, 0.65),
    ("Caballa", "proteina", 205, 19.0, 0, 14.0, 3.5, 0, 0, 0.1),
    ("Rúcula", "verdura", 25, 2.6, 3.7, 0.7, 0, 0, 2.0, 0.02),
    ("Pulpo cocido", "proteina", 82, 18.0, 0, 1.0, 0.2, 0, 0, 0.4),
]

# nombre, franja, tags, tiempo_min, gramos_recomendados, es_racion_unica,
# instrucciones(list), ingredientes(list de (nombre_ingrediente, gramos))
NEW_MEALS = [
    # ── DESAYUNOS ──────────────────────────────
    ("Tostada de centeno con requesón y mermelada", "desayuno", "vegetariano,cereal", 8, 180, False,
        ["Tuesta el pan de centeno.",
         "Unta con el requesón y añade la mermelada por encima."],
        [("Pan de centeno", 60), ("Requesón", 80), ("Mermelada", 20)]),

    ("Yogur griego con nueces y plátano", "desayuno", "lacteo,fruta", 5, 0, True,
        ["Corta el plátano en rodajas.",
         "Mezcla con el yogur griego y las nueces."],
        [("Yogur griego natural", 200), ("Nueces", 15), ("Plátano", 80)]),

    ("Tostada con pavo y queso fresco", "desayuno", "proteina", 8, 170, False,
        ["Tuesta el pan.",
         "Añade el pavo fiambre y el queso fresco."],
        [("Pan blanco", 60), ("Pavo fiambre", 60), ("Queso fresco", 40), ("Aceite de oliva", 5)]),

    ("Batido de cacao y plátano", "desayuno", "lacteo,fruta", 5, 0, True,
        ["Bate la leche con el cacao, el plátano y la miel hasta que quede homogéneo."],
        [("Leche entera", 250), ("Cacao puro en polvo", 15), ("Plátano", 100), ("Miel", 10)]),

    ("Tortilla francesa con jamón", "desayuno", "proteina", 10, 210, False,
        ["Bate los huevos con el jamón picado.",
         "Cuaja la tortilla en la sartén con un poco de aceite."],
        [("Huevo", 150), ("Jamón cocido", 50), ("Aceite de oliva", 10)]),

    ("Porridge de avena con manzana y miel", "desayuno", "cereal,fruta,vegetariano", 10, 0, True,
        ["Cuece la avena con la leche a fuego suave 5 minutos.",
         "Sirve con la manzana troceada y un chorrito de miel."],
        [("Avena", 50), ("Leche entera", 200), ("Manzana", 100), ("Miel", 10)]),

    ("Tostada de aguacate y huevo poché", "desayuno", "verdura,proteina,vegetariano", 10, 200, False,
        ["Tuesta el pan integral y machaca el aguacate encima.",
         "Escalfa el huevo y colócalo sobre la tostada."],
        [("Pan integral", 60), ("Aguacate", 80), ("Huevo", 60)]),

    ("Bol de yogur con frutos rojos y almendras", "desayuno", "lacteo,fruta", 5, 0, True,
        ["Mezcla el yogur griego con los frutos rojos y las almendras."],
        [("Yogur griego natural", 200), ("Frutos rojos", 60), ("Almendras", 15)]),

    ("Tostada de centeno con queso curado y tomate", "desayuno", "lacteo,verdura", 8, 170, False,
        ["Tuesta el pan de centeno.",
         "Añade el queso curado en lonchas y el tomate en rodajas."],
        [("Pan de centeno", 60), ("Queso curado", 40), ("Tomate", 60), ("Aceite de oliva", 10)]),

    ("Naranja con tostada de pavo", "desayuno", "fruta,proteina", 8, 260, False,
        ["Pela y trocea la naranja.",
         "Tuesta el pan y añade el pavo fiambre."],
        [("Naranja", 150), ("Pan blanco", 60), ("Pavo fiambre", 50), ("Aceite de oliva", 5)]),

    ("Huevos revueltos con champiñones", "desayuno", "proteina,verdura", 12, 250, False,
        ["Saltea los champiñones laminados en aceite.",
         "Añade los huevos batidos y remueve a fuego suave hasta cuajar."],
        [("Huevo", 150), ("Champiñones", 100), ("Aceite de oliva", 10)]),

    ("Kiwi con requesón y nueces", "desayuno", "fruta,lacteo", 5, 0, True,
        ["Trocea el kiwi.",
         "Sirve con el requesón y las nueces por encima."],
        [("Kiwi", 150), ("Requesón", 150), ("Nueces", 15)]),

    # ── MERIENDAS ──────────────────────────────
    ("Fruta variada con almendras", "merienda", "fruta", 5, 0, True,
        ["Trocea la manzana y la pera.",
         "Sirve junto con las almendras."],
        [("Manzana", 100), ("Pera", 100), ("Almendras", 20)]),

    ("Tostada integral con requesón y miel", "merienda", "vegetariano,cereal", 5, 120, False,
        ["Tuesta el pan integral.",
         "Unta con el requesón y añade la miel."],
        [("Pan integral", 50), ("Requesón", 60), ("Miel", 10)]),

    ("Batido de proteína con frutos rojos", "merienda", "lacteo,fruta", 5, 0, True,
        ["Bate la leche desnatada con el yogur griego y los frutos rojos."],
        [("Leche desnatada", 200), ("Yogur griego natural", 100), ("Frutos rojos", 60)]),

    ("Queso curado con nueces", "merienda", "lacteo,grasa", 3, 0, True,
        ["Sirve el queso curado en dados junto con las nueces."],
        [("Queso curado", 50), ("Nueces", 20)]),

    ("Tostada integral con aguacate", "merienda", "verdura,vegetariano", 5, 110, False,
        ["Tuesta el pan integral y machaca el aguacate por encima."],
        [("Pan integral", 50), ("Aguacate", 60)]),

    ("Naranja con almendras", "merienda", "fruta,grasa", 3, 0, True,
        ["Pela y trocea la naranja.",
         "Sirve junto con las almendras."],
        [("Naranja", 200), ("Almendras", 20)]),

    ("Yogur griego con mermelada", "merienda", "lacteo,fruta", 3, 0, True,
        ["Sirve el yogur griego con la mermelada por encima."],
        [("Yogur griego natural", 200), ("Mermelada", 20)]),

    ("Tostada de pavo y tomate", "merienda", "proteina,verdura", 5, 140, False,
        ["Tuesta el pan de centeno.",
         "Añade el pavo fiambre y el tomate en rodajas."],
        [("Pan de centeno", 50), ("Pavo fiambre", 50), ("Tomate", 40), ("Aceite de oliva", 5)]),

    ("Kiwi con requesón", "merienda", "fruta,lacteo", 3, 0, True,
        ["Trocea el kiwi y sirve junto con el requesón."],
        [("Kiwi", 150), ("Requesón", 120)]),

    ("Puñado de frutos secos con manzana", "merienda", "grasa,fruta", 3, 0, True,
        ["Trocea la manzana y sirve junto con los frutos secos."],
        [("Frutos secos variados", 30), ("Manzana", 100)]),

    ("Batido de plátano y cacao", "merienda", "fruta,lacteo", 5, 0, True,
        ["Bate la leche desnatada con el plátano y el cacao en polvo."],
        [("Leche desnatada", 200), ("Plátano", 100), ("Cacao puro en polvo", 10)]),

    ("Tostada de queso fresco con pepino", "merienda", "lacteo,verdura,vegetariano", 5, 140, False,
        ["Tuesta el pan.",
         "Añade el queso fresco y las rodajas de pepino."],
        [("Pan blanco", 50), ("Queso fresco", 50), ("Pepino", 50)]),

    # ── CENAS ──────────────────────────────────
    ("Ensalada de rúcula con queso curado y nueces", "cena", "verdura,vegetariano", 10, 300, False,
        ["Mezcla la rúcula con el tomate.",
         "Añade el queso curado en virutas y las nueces.",
         "Alíñalo con aceite de oliva."],
        [("Rúcula", 80), ("Queso curado", 40), ("Nueces", 15), ("Tomate", 80), ("Aceite de oliva", 15)]),

    ("Sardinas a la plancha con ensalada", "cena", "pescado", 12, 300, False,
        ["Marca las sardinas a la plancha por ambos lados.",
         "Sirve con la lechuga y el tomate aliñados con aceite."],
        [("Sardinas en lata", 150), ("Lechuga", 80), ("Tomate", 80), ("Aceite de oliva", 15)]),

    ("Caballa al horno con pimientos", "cena", "pescado,verdura", 30, 350, False,
        ["Coloca la caballa con el pimiento y la cebolla en la bandeja.",
         "Hornea 20 minutos a 190°C con un chorrito de aceite."],
        [("Caballa", 250), ("Pimiento rojo", 100), ("Cebolla", 60), ("Aceite de oliva", 10)]),

    ("Pulpo a la gallega", "cena", "pescado", 20, 350, False,
        ["Cuece o calienta el pulpo y córtalo en rodajas.",
         "Sirve sobre la patata cocida con aceite de oliva."],
        [("Pulpo cocido", 250), ("Patata cocida", 200), ("Aceite de oliva", 15)]),

    ("Revuelto de champiñones y espárragos", "cena", "verdura,vegetariano", 15, 300, False,
        ["Saltea los champiñones y los espárragos en aceite.",
         "Añade los huevos batidos y cuaja a fuego suave."],
        [("Huevo", 150), ("Champiñones", 100), ("Espárragos verdes", 100), ("Aceite de oliva", 10)]),

    ("Ensalada de atún y garbanzos", "cena", "pescado,legumbre", 10, 320, False,
        ["Mezcla el atún con los garbanzos, el tomate y la cebolla.",
         "Alíñalo con aceite de oliva."],
        [("Atún al natural", 100), ("Garbanzos cocidos", 150), ("Tomate", 80),
         ("Cebolla", 30), ("Aceite de oliva", 15)]),

    ("Crema de champiñones", "cena", "verdura,vegetariano", 25, 380, False,
        ["Sofríe la cebolla y los champiñones en aceite.",
         "Añade la patata y cubre con agua o caldo, cocina 15 minutos.",
         "Tritura con la nata hasta obtener una crema fina."],
        [("Champiñones", 250), ("Patata cocida", 100), ("Cebolla", 60),
         ("Nata para cocinar", 80), ("Aceite de oliva", 10)]),

    ("Tortilla de espárragos", "cena", "verdura,vegetariano", 15, 280, False,
        ["Saltea los espárragos troceados en aceite.",
         "Añade el huevo batido y cuaja la tortilla por ambos lados."],
        [("Espárragos verdes", 150), ("Huevo", 200), ("Aceite de oliva", 10)]),

    ("Merluza al vapor con verduras", "cena", "pescado,verdura", 20, 350, False,
        ["Cuece la merluza al vapor.",
         "Saltea el calabacín y la zanahoria y sirve junto al pescado."],
        [("Merluza", 250), ("Calabacín", 150), ("Zanahoria", 80), ("Aceite de oliva", 10)]),

    ("Ensalada de rúcula con pavo y queso", "cena", "proteina,verdura", 10, 280, False,
        ["Mezcla la rúcula con el tomate.",
         "Añade el pavo fiambre y el queso curado en virutas.",
         "Alíñalo con aceite de oliva."],
        [("Rúcula", 80), ("Pavo fiambre", 80), ("Queso curado", 30), ("Tomate", 60), ("Aceite de oliva", 15)]),

    ("Sopa juliana de verduras", "cena", "verdura,vegetariano", 25, 380, False,
        ["Corta todas las verduras en juliana fina.",
         "Cocina en agua con la pastilla de caldo 15-20 minutos."],
        [("Zanahoria", 80), ("Calabacín", 100), ("Judía verde", 80), ("Espinacas", 80),
         ("Pastilla de caldo concentrado", 8), ("Aceite de oliva", 10)]),

    ("Boquerones en vinagre con ensalada", "cena", "pescado", 10, 300, False,
        ["Sirve los boquerones con la lechuga y el tomate.",
         "Alíñalo con aceite de oliva."],
        [("Boquerones frescos", 150), ("Lechuga", 80), ("Tomate", 80), ("Aceite de oliva", 15)]),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def seed():
    conn = get_conn()
    c = conn.cursor()

    ing_added = 0
    for row in NEW_INGREDIENTS:
        try:
            c.execute('''
                INSERT INTO ingredients (nombre, categoria, kcal_100g, proteinas_100g, carbohidratos_100g,
                    grasas_100g, grasas_saturadas_100g, grasas_trans_100g, azucares_100g, sal_100g)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', row)
            ing_added += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()

    name_to_id = {r["nombre"]: r["id"] for r in c.execute("SELECT id, nombre FROM ingredients").fetchall()}

    meals_added = 0
    meals_skipped = []
    por_franja = {"desayuno": 0, "merienda": 0, "cena": 0}
    for idx, (nombre, franja, tags, tiempo, gramos_rec, es_unica, instrucciones, ingredientes) in enumerate(NEW_MEALS):
        existing = c.execute("SELECT id FROM meals WHERE nombre=?", (nombre,)).fetchone()
        if existing:
            meals_skipped.append(nombre)
            continue

        image_url = IMGPOOL[idx % len(IMGPOOL)]
        c.execute('''
            INSERT INTO meals (nombre, franja, tags, tiempo_preparacion_min, gramos_recomendados,
                es_racion_unica, instrucciones, image_url, image_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nombre, franja, tags, tiempo, gramos_rec, int(es_unica),
              json.dumps(instrucciones), image_url, "unsplash"))
        meal_id = c.lastrowid

        faltantes = []
        for ing_nombre, gramos in ingredientes:
            ing_id = name_to_id.get(ing_nombre)
            if not ing_id:
                faltantes.append(ing_nombre)
                continue
            c.execute(
                "INSERT INTO meal_ingredients (meal_id, ingredient_id, gramos) VALUES (?, ?, ?)",
                (meal_id, ing_id, gramos)
            )
        if faltantes:
            print(f"⚠ '{nombre}': ingrediente(s) no encontrado(s): {', '.join(faltantes)}")
        meals_added += 1
        if franja in por_franja:
            por_franja[franja] += 1

    conn.commit()
    conn.close()

    print(f"✓ Ingredientes nuevos añadidos: {ing_added} de {len(NEW_INGREDIENTS)} en la lista")
    print(f"✓ Comidas nuevas añadidas: {meals_added} de {len(NEW_MEALS)} en la lista")
    print(f"  Por franja -> desayuno: {por_franja['desayuno']}, merienda: {por_franja['merienda']}, cena: {por_franja['cena']}")
    if meals_skipped:
        print(f"  (ya existían y se han saltado: {', '.join(meals_skipped)})")


if __name__ == "__main__":
    seed()
