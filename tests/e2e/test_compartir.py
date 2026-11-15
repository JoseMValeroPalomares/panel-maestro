"""F-2: la URL de share_target (/compartir?title=&text=&url=) abre la captura rellena y guardar crea lo correcto.
(El paso por el login sin sesión se prueba en tests/test_compartir.py: aquí la autenticación está desactivada.)"""

from urllib.parse import urlencode


def test_texto_compartido_va_a_la_captura(page, api, server):
    page.set_viewport_size({"width": 375, "height": 800})
    qs = urlencode({"title": "Recado", "text": "Comprar pilas AA para el mando\nY bombillas"})
    page.goto(f"{server}/compartir?{qs}")
    ta = page.locator("#captureForm [data-capture-text]")
    page.wait_for_function("document.getElementById('captureModal').open")
    assert ta.input_value() == "Recado\nComprar pilas AA para el mando\nY bombillas"
    assert page.locator("#shareLinkModal").evaluate("d => d.open") is False
    page.locator('#captureForm [data-capture-type="idea"]').click()
    page.locator("#captureForm [type=submit]").click()
    page.wait_for_url("**/tareas")
    item = next(i for i in api.get("/api/items").json()["items"] if i["text"].startswith("Recado"))
    assert item["type"] == "idea"
    assert "Comprar pilas AA" in item["text"]


def test_prefijo_de_evento(page, api, server):
    qs = urlencode({"text": "e: revisión de la caldera el 20 de diciembre a las 10"})
    page.goto(f"{server}/compartir?{qs}")
    page.wait_for_function("document.getElementById('captureModal').open")
    page.locator("#captureForm [type=submit]").click()
    page.locator("dialog[open] .btn-primary", has_text="Guardar el evento").click()  # vista previa del evento
    page.wait_for_url("**/calendario*")
    assert api.get("/api/search", params={"q": "caldera", "contexto": "todo"}).json()["events"]


def test_enlace_compartido_propone_el_baul(page, api, server):
    page.set_viewport_size({"width": 375, "height": 800})
    # como comparte YouTube o el navegador: el enlace dentro del texto y un título corto
    qs = urlencode({"title": "", "text": "Mira esto http://127.0.0.1:9/compartido-e2e"})
    page.goto(f"{server}/compartir?{qs}")
    page.wait_for_function("document.getElementById('shareLinkModal').open")
    assert page.locator("[data-share-title]").inner_text() == "Mira esto"
    assert page.locator("[data-share-host]").inner_text() == "127.0.0.1"
    page.locator('#shareLinkForm [name="category"]').fill("Lecturas E2E")
    page.locator('#shareLinkForm [name="watch_later"]').check()
    page.locator("#shareLinkForm [type=submit]").click()
    page.wait_for_url("**/vault")
    r = next(x for x in api.get("/api/resources").json()["resources"] if x["url"].endswith("/compartido-e2e"))
    assert r["category"] == "Lecturas E2E" and r["watch_later"] == 1


def test_enlace_como_tarea(page, api, server):
    qs = urlencode({"title": "Artículo largo", "url": "http://127.0.0.1:9/otro-e2e"})
    page.goto(f"{server}/compartir?{qs}")
    page.wait_for_function("document.getElementById('shareLinkModal').open")
    page.locator("[data-share-as-item]").click()
    page.wait_for_function("document.getElementById('captureModal').open")
    ta = page.locator("#captureForm [data-capture-text]")
    assert ta.input_value() == "Artículo largo\nhttp://127.0.0.1:9/otro-e2e"
