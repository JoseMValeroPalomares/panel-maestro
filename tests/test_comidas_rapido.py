"""P-3 · Altas rápidas de Comidas: plato con un ingrediente por línea e ingrediente en una línea o con la etiqueta."""

import pytest

from comidas.rapido import leer_cabecera, leer_ingrediente, leer_linea

BASE = "/comidas/api"


@pytest.mark.parametrize(
    "line,out",
    [
        ("3 huevos", ("huevos", 3, None)),
        ("300 g patata", ("patata", 300, "g")),
        ("300g de patata", ("patata", 300, "g")),
        ("patata 300", ("patata", 300, None)),
        ("1 kg tomate", ("tomate", 1000, "g")),
        ("- 15 ml aceite de oliva", ("aceite de oliva", 15, "g")),
        ("huevo 2 uds", ("huevo", 2, "ud")),
        ("sal", ("sal", None, None)),
    ],
)
def test_una_linea_de_ingrediente(line, out):
    r = leer_linea(line)
    assert (r["texto"], r["cantidad"], r["unidad"]) == out


def test_cabecera_del_plato():
    fr = [{"clave": "cena", "nombre": "Cena"}, {"clave": "desayuno", "nombre": "Desayuno"}]
    assert leer_cabecera("Tortilla de patatas cena 30 min +casera", fr) == {
        "nombre": "Tortilla de patatas",
        "franja": "cena",
        "tiempo": 30,
        "tags": ["casera"],
    }
    assert leer_cabecera("Desayuno inglés", fr)["franja"] is None  # una sola palabra al final que es el nombre


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Avena 389 16,9 66,3 6,9", (389, 16.9, 66.3, 6.9)),
        ("Pechuga de pollo 110 kcal p23 g1,2 h0", (110, 23, 0, 1.2)),
        ("Yogur 120 kcal 4 h 6 p 9 g", (120, 6, 4, 9)),
        (
            "Avena\nValor energético 1630 kJ / 389 kcal\nGrasas 6,9 g\nde las cuales saturadas 1,2 g\n"
            "Hidratos de carbono 66,3 g\nde los cuales azúcares 1 g\nProteínas 16,9 g\nSal 0,01 g",
            (389, 16.9, 66.3, 6.9),
        ),
    ],
)
def test_ingrediente_en_una_linea_o_etiqueta(texto, esperado):
    v = leer_ingrediente(texto)["valores"]
    assert (v["kcal_100g"], v["proteinas_100g"], v["carbohidratos_100g"], v["grasas_100g"]) == esperado


def _ings(client):
    for n, k, p, c, g, gpu in (("Huevo", 143, 12.6, 0.7, 9.5, 60), ("Patata", 77, 2, 17, 0.1, None)):
        client.post(
            f"{BASE}/ingredients",
            json={
                "nombre": n,
                "kcal_100g": k,
                "proteinas_100g": p,
                "carbohidratos_100g": c,
                "grasas_100g": g,
                "gramos_por_unidad": gpu,
                "unidad_nombre": "huevo" if gpu else None,
            },
        )


def test_plato_rapido_vista_previa_y_alta(client):
    _ings(client)
    body = {"texto": "Tortilla rápida cena 20 min", "ingredientes": "3 huevos\n300 g patatas", "pasos": "batir\ncuajar"}
    p = client.post(f"{BASE}/meals/rapido", json={**body, "dry_run": True}).json()
    assert p["sin_reconocer"] == [] and p["preview"]["franja"] == "cena"
    filas = p["preview"]["ingredientes"]
    assert [(f["ingrediente"]["nombre"], f["gramos"], f["unidades"]) for f in filas] == [
        ("Huevo", 180, 3),
        ("Patata", 300, None),
    ]
    r = client.post(f"{BASE}/meals/rapido", json=body).json()
    m = client.get(f"{BASE}/meals/{r['id']}").json()
    assert m["franja"] == "cena" and m["tiempo_preparacion_min"] == 20 and m["instrucciones"] == ["batir", "cuajar"]


def test_plato_con_un_ingrediente_desconocido_no_se_crea(client):
    _ings(client)
    body = {"texto": "Raro", "ingredientes": "100 g unicornio"}
    assert client.post(f"{BASE}/meals/rapido", json={**body, "dry_run": True}).json()["sin_reconocer"] == ["unicornio"]
    r = client.post(f"{BASE}/meals/rapido", json=body)
    assert r.status_code == 422 and "unicornio" in r.text


def test_ingrediente_rapido(client):
    r = client.post(f"{BASE}/ingredients/rapido", json={"texto": "Avena prueba 389 16,9 66,3 6,9"}).json()
    ing = next(i for i in client.get(f"{BASE}/ingredients").json()["ingredients"] if i["id"] == r["id"])
    assert ing["categoria"] == "cereal" and ing["kcal_100g"] == 389
    assert client.post(f"{BASE}/ingredients/rapido", json={"texto": "Sin kcal"}).status_code == 422


def test_nombres_que_empiezan_como_una_etiqueta():
    s = leer_ingrediente("Salmón 208 20 0 13")
    assert s["nombre"] == "Salmón" and s["valores"]["kcal_100g"] == 208 and "sal_100g" not in s["valores"]
    c = leer_ingrediente("Espaguetis carbonara 150 6 20 5")
    assert c["nombre"] == "Espaguetis carbonara" and c["valores"]["carbohidratos_100g"] == 20
