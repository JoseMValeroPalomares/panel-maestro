"""F-4: «Proponer flashcards» en el navegador (375 y 1280 px) con el proveedor simulado de conftest: la inventada se
descarta sola, se edita una, se desmarca otra, se añaden bajo «Flashcards», salen en Repaso y Deshacer las quita.
Con la nota sensible y solo proveedores que entrenan, el botón queda desactivado y explica por qué."""

import os
from pathlib import Path

import pytest

SHOTS = os.environ.get("PANEL_SHOTS")
NOTA = """# Neurona

La bomba de sodio-potasio saca 3 iones de sodio.
La mielina aumenta la velocidad de conducción.
El potencial de reposo es de -70 mV.
"""


def _crear(api, nid):
    r = api.post(
        f"/api/notes/{nid}",
        json={"title": nid, "category": "E2E - IA", "content": NOTA, "status": "en-desarrollo"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("w,h", [(1280, 900), (375, 812)])
def test_proponer_editar_anadir_y_deshacer(page, server, api, w, h):
    nid = f"fc-e2e-{w}"
    _crear(api, nid)
    page.set_viewport_size({"width": w, "height": h})
    page.goto(f"{server}/?note={nid}")
    page.locator("#noteMenuBtn").wait_for()
    page.locator("#noteMenuBtn").click()
    page.get_by_role("menuitem", name="Proponer flashcards con IA").click()
    start = page.locator("[data-fc-start]")
    start.wait_for()
    assert start.is_enabled()
    start.click()
    page.locator(".fcia-card").first.wait_for(timeout=15_000)
    assert page.locator(".fcia-card").count() == 3
    assert "1 descartada" in page.locator(".fcia-modal details summary").inner_text()  # la inventada
    if SHOTS:
        page.screenshot(path=str(Path(SHOTS) / f"f4-flashcards-{w}.png"))
    # edita la primera, desmarca la tercera; un «>>» bloquea el botón
    q0 = page.locator("[data-fcia-q]").first
    q0.fill("¿Cuántos iones de sodio saca la bomba? >> mal")
    assert page.locator("[data-fc-add]").is_disabled()
    assert page.locator("[data-fcia-err]").first.is_visible()
    q0.fill("¿Cuántos iones de sodio saca la bomba?")
    page.locator("[data-fc-drop]").nth(2).click()
    add = page.locator("[data-fc-add]")
    assert add.is_enabled() and "Añadir 2" in add.inner_text()
    add.click()
    page.locator(".toast", has_text="2 flashcards añadidas").wait_for()
    contenido = api.get(f"/api/notes/{nid}").json()["content"]
    assert (
        "## Flashcards\n\n¿Cuántos iones de sodio saca la bomba? >> La bomba de sodio-potasio saca 3 iones de sodio"
        in contenido
    )
    assert contenido.count(" >> ") == 2
    due = [
        c["question"]
        for c in api.get("/api/flashcards/due", params={"limit": 500}).json()["cards"]
        if c.get("note_id") == nid
    ]
    assert len(due) == 2  # ya están en Repaso
    # Deshacer desde el aviso
    page.locator(".toast", has_text="2 flashcards añadidas").get_by_role("button", name="Deshacer").click()
    page.locator(".toast", has_text="Flashcards quitadas").wait_for()
    assert api.get(f"/api/notes/{nid}").json()["content"].strip() == NOTA.strip()


def test_sensible_sin_proveedor_permitido_desactiva_el_boton(page, server, api):
    nid = "fc-e2e-sensible"
    _crear(api, nid)
    api.put(f"/api/notes/{nid}/sensible", json={"sensible": True})
    # El proveedor simulado no entrena, así que la política real sí lo permitiría: la regla de verdad (sensible + solo
    # proveedores que entrenan → ninguno) está en tests/test_ia_flashcards.py; aquí, cómo lo enseña la interfaz.
    page.route(
        f"**/api/notes/{nid}/ia",
        lambda route: route.fulfill(
            json={
                "sensible": True,
                "disponible": False,
                "sin_claves": False,
                "motivo": "Tu política no permite ningún proveedor para esta nota (es sensible: solo locales o que no entrenan). Revísalo en Ajustes → IA.",
                "ultimas": [],
            }
        ),
    )
    page.goto(f"{server}/?note={nid}")
    page.locator("#noteMenuBtn").click()
    page.get_by_role("menuitem", name="Proponer flashcards con IA").click()
    start = page.locator("[data-fc-start]")
    start.wait_for()
    assert start.is_disabled()
    assert start.get_attribute("aria-describedby") == "fcWhy"
    assert "sensible" in page.locator("#fcWhy").inner_text()
