"""Bloque B: lienzo del Inbox — barra flotante, atajos 1–9/Q/L, trazo a mano, rellenos, lienzo claro y menú de acciones."""

from tests.e2e.test_board import _board, _open, doc, drag, saved, screen

CAJA = {"id": "n_a", "kind": "rect", "x": 100, "y": 100, "w": 180, "h": 90, "text": "Caja"}


def test_atajos_de_numero_y_mantener_herramienta(page, server, api):
    bid = _board(api, {"nodes": []})
    _open(page, server, bid)
    page.locator(".board-svg").click(position={"x": 400, "y": 400})
    for key, tool in [
        ("2", "rect"),
        ("3", "diamond"),
        ("4", "ellipse"),
        ("6", "line"),
        ("9", "sticky"),
        ("1", "select"),
    ]:
        page.keyboard.press(key)
        assert page.evaluate("__board.state.tool") == tool
    # Rombo con Q: tras dibujar sigue la misma herramienta
    page.keyboard.press("d")
    page.keyboard.press("q")
    assert page.locator("#btnLockTool").get_attribute("aria-pressed") == "true"
    drag(page, screen(page, 300, 300), screen(page, 420, 380))
    assert page.evaluate("__board.state.tool") == "diamond"
    kinds = [n["kind"] for n in doc(page)["nodes"]]
    assert kinds == ["diamond"]


def test_linea_sin_puntas_y_trazo_a_mano(page, server, api):
    bid = _board(api, {"nodes": [CAJA]})
    _open(page, server, bid, props=True)
    page.locator(".board-svg").click(position={"x": 520, "y": 320})
    page.keyboard.press("l")  # sin selección: herramienta Línea
    assert page.evaluate("__board.state.tool") == "line"
    drag(page, screen(page, 500, 500), screen(page, 700, 520))
    e = doc(page)["edges"][0]
    assert e["endHead"] == "none" and e["startHead"] == "none"
    # Trazo a mano y relleno rayado en la caja, desde el panel de propiedades
    page.evaluate("__board.state.sel = new Set(['n_a']); __board.renderAll()")
    page.locator("#boardProps [data-prop=sketch][data-value='1']").click()
    page.locator("#boardProps [data-prop=fillStyle][data-value=hachure]").click()
    n = doc(page)["nodes"][0]
    assert n["sketch"] == 1 and n["fillStyle"] == "hachure"
    assert page.locator('[data-id="n_a"] .sketch').count() == 1
    assert "url(#hatch-hachure-" in page.locator('[data-id="n_a"] .shape').get_attribute("fill")
    # El dibujo es estable: repintar no cambia el trazo (la semilla sale del id)
    d1 = page.locator('[data-id="n_a"] .sketch').get_attribute("d")
    page.evaluate("__board.state.sel = new Set(); __board.renderAll()")
    assert page.locator('[data-id="n_a"] .sketch').get_attribute("d") == d1
    # Se guarda en el tablero y lo nuevo sale ya a mano
    page.wait_for_function("!__board.state.dirty", timeout=5000)
    assert saved(api, bid)["nodes"][0]["sketch"] == 1
    assert page.evaluate("__board.insertShape('ellipse').sketch") == 1
    # Ctrl+Z quita el último cambio
    page.keyboard.press("Control+z")
    assert len(doc(page)["nodes"]) == 1


def test_lienzo_claro_y_menu_de_acciones(page, server, api):
    bid = _board(api, {"nodes": [CAJA]})
    _open(page, server, bid)
    page.locator(".board-svg").click(position={"x": 520, "y": 320})
    page.keyboard.press("Alt+Shift+D")
    assert page.locator("#boardWrap").evaluate("e => e.classList.contains('is-light')")
    assert page.evaluate("Prefs.get('tablero.lienzo')") == "claro"
    page.locator("#btnCanvas").click()  # → como el panel (tema oscuro: lienzo oscuro)
    page.locator("#btnCanvas").click()  # → oscuro
    assert page.evaluate("Prefs.get('tablero.lienzo')") == "oscuro"
    assert not page.locator("#boardWrap").evaluate("e => e.classList.contains('is-light')")
    # «/» abre las acciones en el tablero (no la búsqueda del panel) y Enter ejecuta la primera que encaja
    page.locator(".board-svg").click(
        position={"x": 640, "y": 460}
    )  # otro punto: dos clics seguidos en el mismo = texto
    page.keyboard.press("/")
    dlg = page.locator("dialog.board-actions[open]")
    dlg.wait_for()
    assert page.url.endswith("/inbox")
    page.locator("#baInput").fill("rombo")
    assert dlg.locator(".ba-item .ba-label").all_inner_texts() == ["Rombo"]
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('dialog.board-actions[open]') && __board.state.tool === 'diamond'")
    # «?» es la misma lista como ayuda
    page.keyboard.press("?")
    page.locator("dialog.board-actions[open] h2", has_text="Atajos del tablero").wait_for()
