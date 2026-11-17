"""Tanda 10 · Comidas: vaciar la lista de la compra con deshacer (P-6), quitar un solo plato de una comida (P-7),
esenciales (P-9) y pasos de receta (P-10)."""

import pytest

BASE = "/comidas/api"
SEMANA = "2026-12-14"


@pytest.fixture(scope="module")
def d(client):
    def ing(nombre, k, p, c, g):
        r = client.post(
            f"{BASE}/ingredients",
            json={
                "nombre": nombre,
                "categoria": "General",
                "kcal_100g": k,
                "proteinas_100g": p,
                "carbohidratos_100g": c,
                "grasas_100g": g,
            },
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    ids = {"tomate": ing("Tomate T10", 18, 0.9, 3.9, 0.2), "huevo": ing("Huevo T10", 143, 12.6, 0.7, 9.5)}

    def meal(nombre, franja, ingredientes, gramos):
        r = client.post(
            f"{BASE}/meals",
            json={"nombre": nombre, "franja": franja, "ingredientes": ingredientes, "gramos_recomendados": gramos},
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    ids["ensalada"] = meal("Ensalada T10", "comida", [{"ingredient_id": ids["tomate"], "gramos": 200}], 200)
    ids["tortilla"] = meal("Tortilla T10", "comida", [{"ingredient_id": ids["huevo"], "gramos": 120}], 120)
    return ids


def _lista(client):
    return client.get(f"{BASE}/shopping-list").json()["items"]


# ---------- P-6 ----------


def test_vaciar_la_lista_y_deshacer_la_deja_identica(client, d):
    client.delete(f"{BASE}/shopping-list")
    client.post(f"{BASE}/shopping-list", json={"ingredient_id": d["tomate"], "cantidad_gramos": 300})
    client.post(f"{BASE}/shopping-list", json={"nombre_libre": "Pan T10", "cantidad_gramos": 1})
    client.post(f"{BASE}/shopping-list/from-meal/{d['tortilla']}")
    pan = next(i for i in _lista(client) if i["nombre_libre"] == "Pan T10")
    client.patch(f"{BASE}/shopping-list/{pan['id']}", json={"comprado": True})
    antes = _lista(client)
    assert len(antes) == 3

    r = client.delete(f"{BASE}/shopping-list")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 3 and body["undo_token"] and body["undo_db"] == "comidas"
    assert _lista(client) == []

    # En la papelera, con su etiqueta
    entradas = client.get("/api/trash").json()["entries"]
    e = next(x for x in entradas if x["token"] == body["undo_token"])
    assert e["db"] == "comidas" and "compra" in e["label"]

    r = client.post(f"/api/trash/comidas/{body['undo_token']}/restore")
    assert r.status_code == 200 and r.json()["restored"] == 3
    assert _lista(client) == antes


def test_vaciar_una_lista_vacia_no_deja_nada_en_la_papelera(client):
    client.delete(f"{BASE}/shopping-list")
    r = client.delete(f"{BASE}/shopping-list")
    assert r.json()["deleted"] == 0 and r.json()["undo_token"] is None


# ---------- P-7 ----------


def _comida(client, dia="martes", franja="comida"):
    st = client.get(f"{BASE}/weekly-plan/{SEMANA}/full").json()
    return st["dias"][dia]["comidas"].get(franja)


def _dos_platos(client, d, dia="martes"):
    slot = _comida(client, dia)
    if slot:
        client.delete(f"{BASE}/weekly-plan/{slot['plan_id']}")
    base = {"semana": SEMANA, "dia": dia, "franja": "comida"}
    r1 = client.post(
        f"{BASE}/weekly-plan/slots", json={**base, "meal_id": d["ensalada"], "gramos": 250, "rol": "primero"}
    )
    r2 = client.post(
        f"{BASE}/weekly-plan/slots", json={**base, "meal_id": d["tortilla"], "gramos": 180, "rol": "segundo"}
    )
    assert r1.json()["kind"] == "principal" and r2.json()["kind"] == "extra"
    return r1.json()["plan_id"], r2.json()["item_id"]


def test_quitar_el_adicional_deja_el_principal_con_sus_gramos_y_su_papel(client, d):
    plan_id, item_id = _dos_platos(client, d)
    assert client.delete(f"{BASE}/weekly-plan/items/{item_id}").status_code == 200
    platos = _comida(client)["platos"]
    assert [(p["meal_id"], p["gramos"], p["rol"], p["kind"]) for p in platos] == [
        (d["ensalada"], 250, "primero", "principal")
    ]


def test_quitar_el_principal_promociona_el_siguiente_con_sus_gramos_su_papel_y_la_chincheta(client, d):
    plan_id, _ = _dos_platos(client, d, "miercoles")
    client.patch(f"{BASE}/weekly-plan/{plan_id}/toggle-fixed")
    r = client.delete(f"{BASE}/weekly-plan/{plan_id}/principal")
    assert r.status_code == 200 and r.json()["promovido"] == d["tortilla"]
    slot = _comida(client, "miercoles")
    assert slot["plan_id"] == plan_id and slot["is_fixed"] is True
    assert [(p["meal_id"], p["gramos"], p["rol"], p["kind"], p["personalizado"]) for p in slot["platos"]] == [
        (d["tortilla"], 180, "segundo", "principal", True)
    ]
    # El último: la comida queda vacía y sin chincheta
    client.delete(f"{BASE}/weekly-plan/{plan_id}/principal")
    slot = _comida(client, "miercoles")
    assert slot["platos"] == [] and slot["is_fixed"] is False


def test_quitar_el_principal_de_una_comida_que_no_existe(client):
    assert client.delete(f"{BASE}/weekly-plan/999999/principal").status_code == 404


# ---------- P-9 ----------


def _esenciales(client):
    return {e["ingredient_id"]: e for e in client.get(f"{BASE}/esenciales").json()["esenciales"]}


def test_esenciales_marcar_cantidad_anadir_y_quitar(client, d):
    client.delete(f"{BASE}/shopping-list")
    assert client.put(f"{BASE}/esenciales/{d['tomate']}", json={"gramos": 500}).status_code == 200
    assert client.put(f"{BASE}/esenciales/{d['huevo']}", json={}).status_code == 200
    es = _esenciales(client)
    assert es[d["tomate"]]["gramos"] == 500 and es[d["huevo"]]["gramos"] is None
    assert not es[d["tomate"]]["en_lista"]
    # La ficha del ingrediente lo trae y editarla no lo borra
    ing = next(i for i in client.get(f"{BASE}/ingredients").json()["ingredients"] if i["id"] == d["tomate"])
    assert ing["esencial"] == 1 and ing["esencial_gramos"] == 500
    campos = {
        k: ing[k] for k in ("nombre", "categoria", "kcal_100g", "proteinas_100g", "carbohidratos_100g", "grasas_100g")
    }
    client.patch(f"{BASE}/ingredients/{d['tomate']}", json=campos)
    assert _esenciales(client)[d["tomate"]]["gramos"] == 500

    # Un toque lo pone en la lista con su cantidad habitual; otro no lo duplica
    r = client.post(f"{BASE}/esenciales/{d['tomate']}/lista").json()
    assert r["added"] is True
    assert client.post(f"{BASE}/esenciales/{d['tomate']}/lista").json() == {**r, "added": False}
    lista = _lista(client)
    assert [(i["ingredient_id"], i["cantidad_gramos"], i["source"]) for i in lista] == [(d["tomate"], 500, "esencial")]
    e = _esenciales(client)[d["tomate"]]
    assert e["en_lista"] and e["lista_id"] == r["item_id"] and e["lista_source"] == "esencial"

    # Sin cantidad habitual ni unidad: 0 g para escribirla
    client.post(f"{BASE}/esenciales/{d['huevo']}/lista")
    assert next(i for i in _lista(client) if i["ingredient_id"] == d["huevo"])["cantidad_gramos"] == 0

    # Dejar de ser esencial no toca la lista
    client.delete(f"{BASE}/esenciales/{d['huevo']}")
    assert d["huevo"] not in _esenciales(client) and len(_lista(client)) == 2
    assert client.put(f"{BASE}/esenciales/999999", json={}).status_code == 404
    assert client.put(f"{BASE}/esenciales/{d['tomate']}", json={"gramos": -1}).status_code == 422
    client.delete(f"{BASE}/esenciales/{d['tomate']}")


def test_los_esenciales_no_cambian_la_lista_generada_desde_el_plan(client, d):
    semana = "2027-03-01"
    client.delete(f"{BASE}/shopping-list")
    client.post(
        f"{BASE}/weekly-plan/slots",
        json={"semana": semana, "dia": "lunes", "franja": "comida", "meal_id": d["ensalada"], "gramos": 200},
    )
    client.post(f"{BASE}/shopping-list/from-week/{semana}")
    sin = [(i["ingredient_id"], i["cantidad_gramos"], i["plan_gramos"]) for i in _lista(client)]
    client.delete(f"{BASE}/shopping-list")
    client.put(f"{BASE}/esenciales/{d['huevo']}", json={"gramos": 600})
    client.post(f"{BASE}/esenciales/{d['huevo']}/lista")
    client.post(f"{BASE}/shopping-list/from-week/{semana}")
    con = [(i["ingredient_id"], i["cantidad_gramos"], i["plan_gramos"]) for i in _lista(client)]
    assert sorted(con) == sorted([*sin, (d["huevo"], 600, None)])
    # La exportación de la semana sigue siendo solo el plan
    assert [
        f["ingrediente"] for f in client.get(f"{BASE}/shopping-list/export/{semana}?formato=json").json()["items"]
    ] == ["Tomate T10"]
    client.delete(f"{BASE}/esenciales/{d['huevo']}")


def test_migracion_esenciales_ida_y_vuelta(tmp_path):
    import sqlite3

    from comidas.migrations import MIGRATIONS
    from core.migrations import apply_pending, revert

    conn = sqlite3.connect(tmp_path / "c.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE ingredients (id INTEGER PRIMARY KEY, nombre TEXT)")
    for t in ("plan_items", "weekly_plan", "meals", "shopping_list"):
        conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, meal_id INTEGER, franja TEXT, plan_id INTEGER)")
    conn.executemany("INSERT INTO ingredients (id, nombre) VALUES (?, ?)", [(1, "Leche"), (2, "Pan")])
    apply_pending(conn, MIGRATIONS)
    conn.execute("UPDATE ingredients SET esencial=1, esencial_gramos=1000 WHERE id=1")
    conn.execute("UPDATE ingredients SET esencial=1 WHERE id=2")

    revert(conn, MIGRATIONS, 3)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ingredients)")]
    assert "esencial" not in cols and "esencial_gramos" not in cols
    assert [r[0] for r in conn.execute("SELECT nombre FROM ingredients ORDER BY id")] == ["Leche", "Pan"]

    apply_pending(conn, MIGRATIONS)  # lo marcado vuelve
    assert [tuple(r) for r in conn.execute("SELECT id, esencial, esencial_gramos FROM ingredients ORDER BY id")] == [
        (1, 1, 1000.0),
        (2, 1, None),
    ]
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='esenciales_backup'").fetchone()


# ---------- P-10 ----------
from comidas import pasos as P  # noqa: E402


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Corta el pan\nTuéstalo\n\nUnta el aguacate", ["Corta el pan", "Tuéstalo", "Unta el aguacate"]),
        ("- Corta\n* Fríe\n• Sirve", ["Corta", "Fríe", "Sirve"]),
        ("1. Pica la cebolla. 2. Sofríe. 3) Añade el tomate.", ["Pica la cebolla.", "Sofríe.", "Añade el tomate."]),
        ("1. Pica\n   la cebolla\n2. Sofríe", ["Pica la cebolla", "Sofríe"]),
        ("Paso 1: Lava. Paso 2: Corta.", ["Lava.", "Corta."]),
        ("Mezcla 1.5 kg de harina. Hornea.", ["Mezcla 1.5 kg de harina. Hornea."]),
        ("Cuece 2. Luego escurre", ["Cuece 2. Luego escurre"]),  # un número suelto no parte
        ("", []),
    ],
)
def test_partir_pasos(texto, esperado):
    assert P.partir(texto) == esperado


@pytest.mark.parametrize(
    "paso, segundos",
    [
        ("Sofríe 5 minutos", [300]),
        ("Cuece 3-4 minutos", [240]),
        ("Cuece de 5 a 6 min", [360]),
        ("Hornea 1 h 30 min", [5400]),
        ("Hornea 1 hora y 30 minutos", [5400]),
        ("Deja reposar media hora", [1800]),
        ("Una hora y media al horno", [5400]),
        ("Cocina 10 min y deja reposar 5 min", [600, 300]),
        ("Bate 30 segundos", [30]),
        ("Hornea a 180º 25'", [1500]),
        ("Añade 200 ml de leche y 4 huevos", []),
        ("Pela 1,5 kg de patatas", []),
    ],
)
def test_tiempos_de_un_paso(paso, segundos):
    assert P.tiempos(paso) == segundos


def test_ingredientes_de_un_paso():
    nombres = ["Pechuga de pollo", "Tomates cherry", "Aceite de oliva virgen extra", "Huevo", "Pan integral"]
    assert P.ingredientes_del_paso("Dora el pollo con un chorro de aceite", nombres) == [0, 2]
    assert P.ingredientes_del_paso("Parte el tomate y bate los huevos", nombres) == [1, 3]
    assert P.ingredientes_del_paso("Sirve caliente", nombres) == []


def test_modo_cocina_escala_a_la_racion_y_reparte_ingredientes(client, d):
    m = client.post(
        f"{BASE}/meals",
        json={
            "nombre": "Huevos con tomate T10",
            "franja": "cena",
            "gramos_recomendados": 160,
            "ingredientes": [
                {"ingredient_id": d["huevo"], "gramos": 120},
                {"ingredient_id": d["tomate"], "gramos": 200},
            ],
            "instrucciones": ["Sofríe el tomate 10 minutos.", "Añade los huevos y cuaja 2-3 min.", "Sirve."],
        },
    ).json()["id"]
    # Ración estándar 160 g de una receta de 320 g → la mitad de cada ingrediente
    c = client.get(f"{BASE}/meals/{m}/cocina").json()
    assert c["gramos"] == 160 and c["factor"] == 0.5
    assert [(i["nombre"], i["gramos"]) for i in c["ingredientes"]] == [("Huevo T10", 60), ("Tomate T10", 100)]
    assert [(p["tiempos"], p["ingredientes"]) for p in c["pasos"]] == [([600], [1]), ([180], [0]), ([], [])]
    # Con la ración del plan
    c = client.get(f"{BASE}/meals/{m}/cocina?gramos=480").json()
    assert [i["gramos"] for i in c["ingredientes"]] == [180, 300]
    assert client.get(f"{BASE}/meals/999999/cocina").status_code == 404

    r = client.post(f"{BASE}/meals/pasos/partir", json={"texto": "1. Sofríe 10 min. 2. Sirve."}).json()
    assert r["pasos"] == [{"texto": "Sofríe 10 min.", "tiempos": [600]}, {"texto": "Sirve.", "tiempos": []}]


def test_marcar_como_cocinado_se_ve_en_el_plan(client, d):
    semana = "2027-03-08"
    r = client.post(
        f"{BASE}/weekly-plan/slots",
        json={"semana": semana, "dia": "jueves", "franja": "cena", "meal_id": d["tortilla"], "gramos": 150},
    ).json()

    def plato():
        return client.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"]["jueves"]["comidas"]["cena"]["platos"][0]

    assert plato()["cocinado"] is None
    c = client.post(f"{BASE}/cocinados", json={"meal_id": d["tortilla"], "plan_id": r["plan_id"], "gramos": 150}).json()
    assert plato()["cocinado"] == c["id"]
    client.delete(f"{BASE}/cocinados/{c['id']}")
    assert plato()["cocinado"] is None
    assert client.post(f"{BASE}/cocinados", json={"meal_id": 999999}).status_code == 404


def test_migracion_cocinados_ida_y_vuelta(tmp_path):
    import sqlite3

    from comidas.migrations import MIGRATIONS
    from core.migrations import apply_pending, revert

    conn = sqlite3.connect(tmp_path / "c.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE ingredients (id INTEGER PRIMARY KEY, nombre TEXT)")
    for t in ("plan_items", "weekly_plan", "meals", "shopping_list"):
        conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, meal_id INTEGER, franja TEXT, plan_id INTEGER)")
    apply_pending(conn, MIGRATIONS)
    conn.execute("INSERT INTO cocinados (meal_id, plan_id, gramos, fecha) VALUES (7, 3, 250, '2026-11-15')")
    revert(conn, MIGRATIONS, 4)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='cocinados'").fetchone()
    apply_pending(conn, MIGRATIONS)
    assert [tuple(r)[1:5] for r in conn.execute("SELECT * FROM cocinados")] == [(7, 3, None, 250.0)]
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='cocinados_backup'").fetchone()
