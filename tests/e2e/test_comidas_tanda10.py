"""Tanda 10 · Comidas en el navegador, a 375 y 1280 px: vaciar la lista con deshacer (P-6), quitar un solo plato y
chincheta a la vista (P-7, P-8), esenciales (P-9) y el modo cocina con el editor de pasos (P-10). Las capturas van a
$PANEL_E2E_CAPTURAS (si no, a la carpeta temporal del test)."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

BASE = "/comidas/api"
ANCHOS = [375, 1280]


def _captura(page, tmp_path, nombre):
    carpeta = Path(os.environ.get("PANEL_E2E_CAPTURAS") or tmp_path)
    carpeta.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(carpeta / f"{nombre}.png"))


def _abrir(page, server, ancho, tab="plan"):
    page.set_viewport_size({"width": ancho, "height": 900 if ancho > 400 else 812})
    page.goto(f"{server}/comidas/")
    page.wait_for_load_state("networkidle")
    if tab != "plan":
        page.evaluate(f"switchTab('{tab}')")  # en el móvil las pestañas van en otro control
        page.wait_for_load_state("networkidle")


def _ing(api, nombre, **extra):
    r = api.post(
        f"{BASE}/ingredients",
        json={
            "nombre": nombre,
            "categoria": "General",
            "kcal_100g": 100,
            "proteinas_100g": 5,
            "carbohidratos_100g": 10,
            "grasas_100g": 4,
            **extra,
        },
    )
    if r.status_code == 409:
        return next(i["id"] for i in api.get(f"{BASE}/ingredients").json()["ingredients"] if i["nombre"] == nombre)
    return r.json()["id"]


def _plato(api, nombre, ingredientes, instrucciones=(), gramos=200):
    return api.post(
        f"{BASE}/meals",
        json={
            "nombre": nombre,
            "franja": "comida",
            "gramos_recomendados": gramos,
            "ingredientes": ingredientes,
            "instrucciones": list(instrucciones),
        },
    ).json()["id"]


def _comida(api, semana, dia, franja="comida"):
    return api.get(f"{BASE}/weekly-plan/{semana}/full").json()["dias"][dia]["comidas"].get(franja)


def _dos_platos(api, page, sufijo):
    semana, dia = page.evaluate("[semana(), selectedDia]")
    slot = _comida(api, semana, dia)
    if slot:
        api.delete(f"{BASE}/weekly-plan/{slot['plan_id']}")
    i = _ing(api, f"Arroz e2e10 {sufijo}")
    a = _plato(api, f"Ensalada e2e10 {sufijo}", [{"ingredient_id": i, "gramos": 150}], gramos=150)
    b = _plato(api, f"Guiso e2e10 {sufijo}", [{"ingredient_id": i, "gramos": 300}], gramos=300)
    base = {"semana": semana, "dia": dia, "franja": "comida"}
    plan_id = api.post(
        f"{BASE}/weekly-plan/slots", json={**base, "meal_id": a, "gramos": 180, "rol": "primero"}
    ).json()["plan_id"]
    api.post(f"{BASE}/weekly-plan/slots", json={**base, "meal_id": b, "gramos": 320, "rol": "segundo"})
    page.evaluate("loadPlan()")
    page.wait_for_load_state("networkidle")
    return semana, dia, plan_id, b


# ---------- P-6 ----------


@pytest.mark.parametrize("ancho", ANCHOS)
def test_vaciar_la_lista_y_deshacer(page, server, api, ancho, tmp_path):
    api.delete(f"{BASE}/shopping-list")
    i = _ing(api, "Leche e2e10")
    api.post(f"{BASE}/shopping-list", json={"ingredient_id": i, "cantidad_gramos": 1000})
    api.post(f"{BASE}/shopping-list", json={"nombre_libre": "Servilletas e2e10", "cantidad_gramos": 1})
    antes = api.get(f"{BASE}/shopping-list").json()["items"]
    _abrir(page, server, ancho, "compra")
    expect(page.locator("#shopLists [data-shop-check]")).to_have_count(2)

    page.get_by_role("button", name="Más acciones de la lista").click()
    page.get_by_role("menuitem", name="Vaciar todo").click()
    page.locator("dialog[open]").get_by_role("button", name="Vaciar todo").click()
    expect(page.locator("#shopLists [data-shop-check]")).to_have_count(0)
    expect(page.locator("#shopLists")).to_contain_text("La lista está vacía")
    _captura(page, tmp_path, f"p6-vaciada-{ancho}")
    page.get_by_role("button", name="Deshacer").click()
    expect(page.locator("#shopLists [data-shop-check]")).to_have_count(2)
    assert api.get(f"{BASE}/shopping-list").json()["items"] == antes


# ---------- P-7 y P-8 ----------


@pytest.mark.parametrize("ancho", ANCHOS)
def test_quitar_un_plato_y_chincheta(page, server, api, ancho, tmp_path):
    _abrir(page, server, ancho)
    semana, dia, plan_id, segundo = _dos_platos(api, page, ancho)
    zona = page.locator(f'.meal-cell[data-plan="{plan_id}"]') if ancho >= 1280 else page.locator("#dayPanel")

    # Chincheta visible, sin abrir el menú
    pin = zona.locator(f'[data-act=pin][data-plan="{plan_id}"]')
    expect(pin).to_have_attribute("aria-pressed", "false")
    pin.click()
    expect(zona.locator(f'[data-act=pin][data-plan="{plan_id}"]')).to_have_attribute("aria-pressed", "true")
    assert _comida(api, semana, dia)["is_fixed"] is True

    # Quitar el principal: el segundo pasa a principal con sus gramos y su papel; la comida sigue fijada
    if ancho >= 1280:
        zona.locator("li").first.hover()
        zona.locator(".cell-plato-del").first.click()
    else:
        zona.locator(f'[data-act=remove-plato][data-kind=principal][data-plan="{plan_id}"]').click()
    page.wait_for_load_state("networkidle")
    slot = _comida(api, semana, dia)
    assert [(p["meal_id"], p["gramos"], p["rol"], p["kind"]) for p in slot["platos"]] == [
        (segundo, 320, "segundo", "principal")
    ]
    assert slot["is_fixed"] is True
    _captura(page, tmp_path, f"p7-p8-{ancho}")
    # «Vaciar esta comida» sigue en el menú
    if ancho >= 1280:
        page.locator(f'.meal-cell[data-plan="{plan_id}"] [data-act=cell-menu]').click()
        expect(page.get_by_role("menuitem", name="Vaciar esta comida")).to_be_visible()
        page.keyboard.press("Escape")


# ---------- P-9 ----------


@pytest.mark.parametrize("ancho", ANCHOS)
def test_esenciales(page, server, api, ancho, tmp_path):
    api.delete(f"{BASE}/shopping-list")
    pan = _ing(api, "Pan e2e10")
    for e in api.get(f"{BASE}/esenciales").json()["esenciales"]:
        api.delete(f"{BASE}/esenciales/{e['ingredient_id']}")
    api.put(f"{BASE}/esenciales/{_ing(api, 'Huevos e2e10')}", json={"gramos": 600})
    _abrir(page, server, ancho, "compra")
    expect(page.locator(".es-chip")).to_have_count(1)

    page.locator("#esName").fill("Pan e2e10")
    page.locator("#esQty").fill("400")
    page.locator("#esName").press("Enter")
    chip = page.locator(f'.es-chip[data-es="{pan}"]')
    expect(chip).to_have_attribute("aria-pressed", "false")
    chip.click()
    expect(page.locator(f'.es-chip[data-es="{pan}"]')).to_have_attribute("aria-pressed", "true")
    lista = api.get(f"{BASE}/shopping-list").json()["items"]
    assert [(i["ingredient_id"], i["cantidad_gramos"], i["source"]) for i in lista] == [(pan, 400, "esencial")]
    expect(page.locator("#shopLists")).to_contain_text("Pan e2e10")

    # Al lado en escritorio, debajo en el móvil
    lado = page.locator(".esenciales").bounding_box()
    lista_box = page.locator("#shopLists").bounding_box()
    if ancho >= 1280:
        assert lado["x"] >= lista_box["x"] + lista_box["width"]
    else:
        assert lado["y"] >= lista_box["y"] + lista_box["height"] - 1
    assert page.evaluate("document.documentElement.scrollWidth") <= ancho

    # Editar: quitar un esencial
    page.locator("#esEdit").click()
    page.get_by_role("button", name="Quitar Huevos e2e10 de esenciales").click()
    page.locator("#esEdit").click()
    expect(page.locator(".es-chip")).to_have_count(1)
    _captura(page, tmp_path, f"p9-esenciales-{ancho}")


# ---------- P-10 ----------


def test_modo_cocina_en_el_movil(page, server, api, tmp_path):
    _abrir(page, server, 375)
    semana, dia = page.evaluate("[semana(), selectedDia]")
    slot = _comida(api, semana, dia, "cena")
    if slot:
        api.delete(f"{BASE}/weekly-plan/{slot['plan_id']}")
    tomate = _ing(api, "Tomate e2e10")
    huevo = _ing(api, "Huevo e2e10")
    m = _plato(
        api,
        "Huevos con tomate e2e10",
        [{"ingredient_id": tomate, "gramos": 200}, {"ingredient_id": huevo, "gramos": 100}],
        ["Sofríe el tomate 1 minuto.", "Añade el huevo y cuaja.", "Sirve."],
        gramos=300,
    )
    api.post(
        f"{BASE}/weekly-plan/slots", json={"semana": semana, "dia": dia, "franja": "cena", "meal_id": m, "gramos": 150}
    )
    page.evaluate("loadPlan()")
    page.wait_for_load_state("networkidle")

    page.locator("#dayPanel .dp-plato-name", has_text="Huevos con tomate e2e10").click()
    expect(page.locator("#recipeCookBtn")).to_contain_text("Cocinar 150 g")
    page.locator("#recipeCookBtn").click()
    cocina = page.locator("#cookModal")
    expect(cocina).to_be_visible()
    caja = cocina.bounding_box()
    assert caja["width"] >= 375 - 1 and caja["height"] >= 800  # pantalla completa
    expect(page.locator("#cookStage")).to_contain_text("Tomate e2e10")
    expect(page.locator("#cookStage")).to_contain_text("100 g")  # 200 g de receta → mitad para 150 g de 300
    _captura(page, tmp_path, "p10-ingredientes-375")

    page.locator("#cookNext").click()
    expect(page.locator("#cookStage .cook-step")).to_have_text("Sofríe el tomate 1 minuto.")
    expect(page.locator("#cookStage .cook-ings")).to_contain_text("Tomate e2e10")
    expect(page.locator("#cookStage .cook-ings")).not_to_contain_text("Huevo")
    page.get_by_role("button", name="Temporizador 1 min").click()
    expect(page.locator("#cookTimers .cook-pill")).to_have_count(1)
    _captura(page, tmp_path, "p10-paso-375")

    page.keyboard.press("ArrowRight")  # con flechas
    expect(page.locator("#cookStage .cook-ings")).to_contain_text("Huevo e2e10")
    expect(page.locator("#cookTimers .cook-pill")).to_have_count(1)  # el temporizador sigue
    page.keyboard.press("ArrowRight")
    page.locator("#cookNext").click()  # «Terminar»
    page.get_by_role("button", name="Marcar como cocinado").click()
    expect(cocina).to_be_hidden()
    expect(page.locator("#dayPanel .tag-done")).to_have_count(1)
    plato = _comida(api, semana, dia, "cena")["platos"][0]
    assert plato["cocinado"]


def test_editor_de_pasos_parte_lo_pegado(page, server, api):
    # Antes de abrir la página: el formulario solo conoce los ingredientes cargados al entrar
    m = _plato(api, "Tostada e2e10", [{"ingredient_id": _ing(api, "Pan tostado e2e10"), "gramos": 60}], ["Tuesta."])
    _abrir(page, server, 1280, "platos")
    page.evaluate(f"openMealForm({m})")
    expect(page.locator("#mealSteps")).to_have_value("Tuesta.")
    texto = "1. Tuesta el pan 2 minutos. 2. Unta el tomate. 3) Sirve."
    page.locator("#mealSteps").fill("")
    page.locator("#mealSteps").focus()
    page.evaluate(
        """t => { const ta = document.querySelector('#mealSteps'); const dt = new DataTransfer(); dt.setData('text/plain', t);
             ta.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
             ta.value = t; ta.dispatchEvent(new Event('input')); }""",
        texto,
    )
    expect(page.locator("#mealSteps")).to_have_value("Tuesta el pan 2 minutos.\nUnta el tomate.\nSirve.")
    expect(page.locator("#mealStepsPrev li")).to_have_count(3)
    expect(page.locator("#mealStepsPrev li").first).to_contain_text("2 min")
    page.get_by_role("button", name="Guardar plato").click()
    expect(page.locator("#mealFormModal")).to_be_hidden()
    page.wait_for_load_state("networkidle")
    assert api.get(f"{BASE}/meals/{m}").json()["instrucciones"] == [
        "Tuesta el pan 2 minutos.",
        "Unta el tomate.",
        "Sirve.",
    ]
