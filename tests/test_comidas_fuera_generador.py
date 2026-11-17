"""Platos «fuera del generador» (migración 6 de Comidas): el generador semanal, regenerar una comida, el plato doble y
las sugerencias no los eligen; a mano se siguen poniendo."""

import pytest

from comidas import generador as gen

BASE = "/comidas/api"
SEMANA = "2027-01-04"


@pytest.fixture(scope="module")
def d(client):
    r = client.post(
        f"{BASE}/ingredients",
        json={
            "nombre": "Pollo FG",
            "categoria": "General",
            "kcal_100g": 165,
            "proteinas_100g": 31,
            "carbohidratos_100g": 0,
            "grasas_100g": 3.6,
        },
    )
    pollo = r.json()["id"]

    def meal(nombre):
        r = client.post(
            f"{BASE}/meals",
            json={
                "nombre": nombre,
                "franja": "cena",
                "ingredientes": [{"ingredient_id": pollo, "gramos": 200}],
                "gramos_recomendados": 200,
            },
        )
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return {"fuera": meal("Pollo vetado FG"), "dentro": meal("Pollo permitido FG")}


def _platos_de_la_semana(client, semana):
    plan = client.get(f"{BASE}/weekly-plan/{semana}/full").json()
    return {p["meal_id"] for dia in plan["dias"].values() for c in dia["comidas"].values() for p in c.get("platos", [])}


def test_marcar_y_desmarcar(client, d):
    r = client.patch(f"{BASE}/meals/{d['fuera']}/generador", json={"fuera": True})
    assert r.status_code == 200 and r.json()["fuera_generador"] is True
    meals = {m["id"]: m for m in client.get(f"{BASE}/meals").json()["meals"]}
    assert meals[d["fuera"]]["fuera_generador"] == 1 and meals[d["dentro"]]["fuera_generador"] == 0
    assert client.patch(f"{BASE}/meals/999999/generador", json={"fuera": True}).status_code == 404


def test_el_generador_no_lo_elige_pero_a_mano_si(client, d):
    client.patch(f"{BASE}/meals/{d['fuera']}/generador", json={"fuera": True})
    for semana in (SEMANA, "2027-01-11", "2027-01-18"):
        assert (
            client.post(f"{BASE}/weekly-plan/generate", json={"semana": semana, "franjas": ["cena"]}).status_code == 200
        )
        assert d["fuera"] not in _platos_de_la_semana(client, semana)
    sug = client.get(f"{BASE}/weekly-plan/{SEMANA}/sugerencias", params={"dia": "lunes", "franja": "cena", "n": 20})
    assert d["fuera"] not in {p["id"] for p in sug.json()["platos"]}
    # a mano, sí
    r = client.post(
        f"{BASE}/weekly-plan/slots", json={"semana": SEMANA, "dia": "martes", "franja": "cena", "meal_id": d["fuera"]}
    )
    assert r.status_code == 200, r.text
    assert d["fuera"] in _platos_de_la_semana(client, SEMANA)
    # puesto a mano como principal de una semana vacía: regenerar esa comida no vuelve a elegirlo
    otra = "2027-02-01"
    r = client.post(
        f"{BASE}/weekly-plan/slots", json={"semana": otra, "dia": "lunes", "franja": "cena", "meal_id": d["fuera"]}
    )
    assert r.json()["kind"] == "principal"
    r = client.post(f"{BASE}/weekly-plan/{r.json()['plan_id']}/regenerate")
    assert r.status_code == 200 and r.json()["meal_id"] != d["fuera"]


def test_candidatos_sin_los_de_fuera():
    cat = {1: {"id": 1, "franja": "cena", "fuera_generador": True}, 2: {"id": 2, "franja": "cena"}}
    week = {"used_main": set(), "used_side": set()}
    assert [m["id"] for m in gen._candidatos(cat, "cena", week)] == [2]
