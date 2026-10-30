"""Gestos para los tests de navegador: arrastrar con ratón, con el dedo y esperar a la red."""
import time

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout


def mouse_drag(page, source, target, where="top", during=None):
    """Arrastra `source` (selector) hasta `target`; where = top | bottom | center."""
    a = page.locator(source).first.bounding_box()
    b = page.locator(target).first.bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + 12)
    page.mouse.down()
    page.mouse.move(a["x"] + a["width"] / 2 + 8, a["y"] + 24, steps=3)
    y = {"top": b["y"] + 4, "bottom": b["y"] + b["height"] - 4, "center": b["y"] + b["height"] / 2}[where]
    page.mouse.move(b["x"] + b["width"] / 2, y, steps=14)
    result = during() if during else None
    page.mouse.up()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    return result


def touch_drag(page, source, target, where="top", hold_ms=450):
    """Pulsación larga y arrastre con el dedo (eventos táctiles reales por CDP)."""
    cdp = page.context.new_cdp_session(page)
    a = page.locator(source).first.bounding_box()
    b = page.locator(target).first.bounding_box()
    x0, y0 = a["x"] + a["width"] / 2, a["y"] + 14
    y1 = {"top": b["y"] + 4, "bottom": b["y"] + b["height"] - 4, "center": b["y"] + b["height"] / 2}[where]
    x1 = b["x"] + b["width"] / 2
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    page.wait_for_timeout(hold_ms)
    steps = 14
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [
            {"x": x0 + (x1 - x0) * i / steps, "y": y0 + (y1 - y0) * i / steps}]})
        page.wait_for_timeout(16)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)


def ids(page, selector):
    return page.eval_on_selector_all(selector, "els => els.map(e => Number(e.dataset.inboxId))")


def wait_js(page, expression, arg=None, timeout=30_000):
    """Sustituye a page.wait_for_function: esa repite la expresión con eval dentro de la página y la CSP del panel (sin
    'unsafe-eval') lo prohíbe, así que solo pasaba si ya se cumplía a la primera. page.evaluate no está sujeto a la CSP."""
    deadline = time.monotonic() + timeout / 1000
    while True:
        try:
            value = page.evaluate(expression, arg)
            if value:
                return value
        except PlaywrightError as e:
            if "context was destroyed" not in str(e):  # una navegación a medias se reintenta; lo demás es un fallo del test
                raise
        if time.monotonic() > deadline:
            raise PlaywrightTimeout(f"No se cumplió en {timeout} ms: {expression}")
        page.wait_for_timeout(25)
