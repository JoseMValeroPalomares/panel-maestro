"""U-3: el lienzo del grafo lleva nombre y hay una lista de notas que se recorre con el teclado; elegir una abre su ficha
(con sus conexiones, que también se siguen con el teclado) y Escape devuelve el foco a donde estaba."""


def test_grafo_se_recorre_con_el_teclado(page, api, server):
    for nid, title, content in (
        ("grafo-a11y-alfa", "Grafo A11y Alfa", "Enlaza con [[Grafo A11y Beta]]."),
        ("grafo-a11y-beta", "Grafo A11y Beta", "Sin enlaces propios."),
    ):
        r = api.post(f"/api/notes/{nid}", json={"title": title, "category": "E2E", "content": content})
        assert r.status_code == 200, r.text
    page.goto(f"{server}/graph")
    page.locator("#loadingOverlay").wait_for(state="hidden", timeout=30_000)
    lienzo = page.locator("#graph-container .vis-network")
    assert lienzo.get_attribute("role") == "application"
    assert "Mapa de notas" in lienzo.get_attribute("aria-label")

    boton = page.locator("#btnList")
    boton.focus()
    page.keyboard.press("Enter")
    assert boton.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.activeElement.id") == "node-list-q"
    page.keyboard.type("a11y alfa")
    assert page.locator(".node-list-item").count() == 1
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")

    assert page.locator("#panel-title").inner_text() == "Grafo A11y Alfa"
    assert page.evaluate("document.activeElement.id") == "panel-title"
    assert page.locator(".node-list-item[aria-current='true']").count() == 1
    conexion = page.locator("#panel-links-list button", has_text="Grafo A11y Beta")
    assert "enlaza a" in conexion.inner_text()
    conexion.focus()
    page.keyboard.press("Enter")  # se sigue la conexión
    assert page.locator("#panel-title").inner_text() == "Grafo A11y Beta"
    assert "enlazada desde" in page.locator("#panel-links-list button").first.inner_text()

    page.keyboard.press("Escape")  # la ficha se cierra y el foco vuelve a la fila
    assert page.locator("#node-panel").is_hidden()
    assert page.evaluate("document.activeElement.dataset.node") == "grafo-a11y-alfa"
    page.keyboard.press("Escape")  # y la lista, al botón que la abrió
    assert page.locator("#node-list").is_hidden()
    assert page.evaluate("document.activeElement.id") == "btnList"
    assert boton.get_attribute("aria-expanded") == "false"
