"""Comidas · Platos: el botón de cada plato lo saca del generador (se nota en la tarjeta y en la lista para ponerlo a
mano) y lo vuelve a meter; también con «Deshacer»."""

import pytest
from playwright.sync_api import expect

BASE = "/comidas/api"


@pytest.mark.parametrize("ancho", [375, 1280])
def test_sacar_y_volver_a_meter_en_el_generador(page, server, api, ancho):
    ing = api.post(
        f"{BASE}/ingredients",
        json={
            "nombre": f"Arroz FGE {ancho}",
            "categoria": "General",
            "kcal_100g": 130,
            "proteinas_100g": 2.7,
            "carbohidratos_100g": 28,
            "grasas_100g": 0.3,
        },
    ).json()["id"]
    nombre = f"Arroz blanco FGE {ancho}"
    mid = api.post(
        f"{BASE}/meals",
        json={
            "nombre": nombre,
            "franja": "comida",
            "ingredientes": [{"ingredient_id": ing, "gramos": 200}],
            "gramos_recomendados": 200,
        },
    ).json()["id"]
    page.set_viewport_size({"width": ancho, "height": 900})
    page.goto(f"{server}/comidas/")
    page.wait_for_load_state("networkidle")
    page.evaluate("switchTab('platos')")
    page.fill("#mealSearch", nombre)
    item = page.locator(".meal-item", has=page.locator(f"[data-meal='{mid}']"))
    boton = item.locator(".gen-btn")
    expect(boton).to_have_attribute("aria-pressed", "false")
    boton.click()
    expect(item).to_have_class("meal-item is-off")
    expect(item.locator(".gen-off-badge")).to_have_text("Fuera del generador")
    expect(item.locator(".gen-btn")).to_have_attribute("aria-pressed", "true")
    assert next(m for m in api.get(f"{BASE}/meals").json()["meals"] if m["id"] == mid)["fuera_generador"] == 1
    # «Deshacer» del aviso lo devuelve
    page.locator(".toast button", has_text="Deshacer").click()
    expect(page.locator(".meal-item", has=page.locator(f"[data-meal='{mid}']"))).to_have_class("meal-item")
    assert next(m for m in api.get(f"{BASE}/meals").json()["meals"] if m["id"] == mid)["fuera_generador"] == 0
