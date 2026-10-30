"""Ronda 2 · fase 4: navegación lateral plegable a iconos con botón (y recordada)."""
import os
from pathlib import Path

SHOTS = os.environ.get("BOARD_SHOTS")


def state(page):
    return page.evaluate("""() => ({ collapsed: document.documentElement.classList.contains('nav-collapsed'),
        width: document.querySelector('.sidebar').getBoundingClientRect().width,
        label: getComputedStyle(document.querySelector('.nav-item .nav-label')).display,
        expanded: document.querySelector('[data-nav-toggle]').getAttribute('aria-expanded') })""")


def test_plegar_y_desplegar_recordado(page, server):
    page.goto(server + "/inbox")
    page.wait_for_load_state("networkidle")
    s = state(page)
    assert not s["collapsed"] and s["width"] > 200 and s["label"] != "none" and s["expanded"] == "true"
    # el botón está arriba, en la misma fila que «Panel» y a su derecha
    brand, btn = page.locator(".sidebar-brand").bounding_box(), page.locator("[data-nav-toggle]").bounding_box()
    assert btn["x"] > brand["x"] + 60 and abs((btn["y"] + btn["height"] / 2) - (brand["y"] + brand["height"] / 2)) < 8
    # los JS/CSS llevan su versión: una página nueva nunca recibe un ui.js viejo de la caché del service worker
    assert "?v=" in page.locator("script[src*='/static/js/ui.js']").get_attribute("src")
    assert "?v=" in page.locator("[data-nav-toggle] use").first.get_attribute("href")
    page.click("[data-nav-toggle]")
    page.wait_for_timeout(350)
    s = state(page)
    assert s["collapsed"] and s["width"] <= 72.5 and s["label"] == "none" and s["expanded"] == "false"
    # solo iconos: cada enlace sigue teniendo nombre (title) y el contenido gana el ancho
    assert page.locator(".sidebar .nav-item[title='Notas']").is_visible()
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{SHOTS}/nav-plegada-1280.png")
    # se recuerda al cambiar de página y se aplica antes de pintar (la clase ya está al cargar el HTML)
    page.goto(server + "/tareas")
    assert page.evaluate("document.documentElement.classList.contains('nav-collapsed')")
    # atajo de teclado
    page.keyboard.press("Control+.")
    page.wait_for_timeout(350)
    assert not state(page)["collapsed"] and state(page)["width"] > 200


def test_tablet_por_defecto_plegada_y_se_puede_desplegar(browser, server):
    import httpx
    httpx.put(f"{server}/api/prefs/nav", json={"value": None}, timeout=10)  # sin preferencia guardada (el test anterior la deja)
    ctx = browser.new_context(viewport={"width": 900, "height": 900}, service_workers="block")
    page = ctx.new_page()
    try:
        page.goto(server + "/")
        page.wait_for_load_state("networkidle")
        assert state(page)["collapsed"]  # sin preferencia: como antes, iconos por debajo de 1024 px
        page.click("[data-nav-toggle]")
        page.wait_for_timeout(350)
        s = state(page)
        assert not s["collapsed"] and s["width"] > 200
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if SHOTS:
            page.screenshot(path=f"{SHOTS}/nav-desplegada-900.png")
    finally:
        ctx.close()
