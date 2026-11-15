"""P-1: aviso de atrasadas en todas las páginas, la hoja con sus cuatro acciones y el teclado, a 375 y 1280 px."""

from datetime import date, timedelta

import pytest

AYER = (date.today() - timedelta(days=1)).isoformat()
MANANA = (date.today() + timedelta(days=1)).isoformat()


def _nueva(api, text):
    r = api.post("/api/items", json={"text": text, "type": "tarea", "due_date": AYER})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(api, i):
    return next((x for x in api.get("/api/items").json()["items"] if x["id"] == i), None)


def _abrir_hoja(page, server, path="/tareas"):
    page.goto(f"{server}{path}")
    page.locator("[data-late-open]").click()
    page.wait_for_function("document.querySelector('.late-sheet')?.open")
    return page.locator(".late-sheet")


def _foco_en(page, i):
    """Mueve el foco con las flechas hasta la fila `i` (como lo haría alguien con el teclado)."""
    for _ in range(60):
        if page.evaluate("document.activeElement.closest('.late-row')?.dataset.late") == str(i):
            return
        page.keyboard.press("ArrowDown")
    raise AssertionError(f"la fila {i} no se alcanza con las flechas")


@pytest.mark.parametrize("ancho", [375, 1280])
def test_cuatro_acciones_con_el_teclado(page, api, server, ancho):
    page.set_viewport_size({"width": ancho, "height": 820})
    a, b, c, d = (_nueva(api, f"E2E atrasada {x} {ancho}") for x in "ABCD")
    hoja = _abrir_hoja(page, server)
    page.wait_for_function("document.activeElement.classList.contains('late-row')")  # el foco entra en la lista

    _foco_en(page, a)
    page.keyboard.press("c")  # completar (y la C no abre la captura rápida)
    page.wait_for_function(f"!document.querySelector('[data-late=\"{a}\"]')")
    assert _item(api, a)["done"]
    assert not page.evaluate("document.getElementById('captureModal').open")

    _foco_en(page, b)
    page.keyboard.press("p")  # posponer → menú → Mañana
    page.locator(".late-sheet .menu .menu-item").first.wait_for()
    page.keyboard.press("Enter")
    page.wait_for_function(f"!document.querySelector('[data-late=\"{b}\"]')")
    assert _item(api, b)["due_date"] == MANANA

    _foco_en(page, c)
    page.keyboard.press("h")  # hoy no: sigue en la lista, callada
    page.wait_for_function(f"document.querySelector('[data-late=\"{c}\"]')?.classList.contains('is-quiet')")

    _foco_en(page, d)
    page.keyboard.press("Delete")
    page.wait_for_function(f"!document.querySelector('[data-late=\"{d}\"]')")
    assert _item(api, d) is None
    hoja.get_by_role("button", name="Deshacer").click()  # el aviso está dentro de la hoja y responde
    page.wait_for_function(f"!!document.querySelector('[data-late=\"{d}\"]')")
    assert _item(api, d)

    page.keyboard.press("Escape")
    calladas = api.get("/api/items/atrasadas", params={"contexto": "todo"}).json()
    assert next(e for e in calladas["atrasadas"] if e["id"] == c)["callada"]


def test_botones_y_tarjeta_de_hoy(page, api, server):
    t = _nueva(api, "E2E atrasada en Hoy")
    page.goto(f"{server}/hoy")
    fila = page.locator(f'#hoyTareas [data-late="{t}"]')
    fila.wait_for()
    fila.locator('[data-late-act="posponer"]').click()
    page.locator(".menu .menu-item", has_text="Elegir fecha").click()
    fecha = (date.today() + timedelta(days=9)).isoformat()
    page.locator('dialog[open] input[type="date"]').fill(fecha)
    page.locator("dialog[open] [type=submit]").click()
    page.wait_for_function(f"!document.querySelector('#hoyTareas [data-late=\"{t}\"]')")
    assert _item(api, t)["due_date"] == fecha


def test_aviso_en_todas_las_paginas_y_hoy_no_a_todas(page, api, server):
    _nueva(api, "E2E aviso general")
    for path in ("/calendario", "/", "/comidas/"):
        page.goto(f"{server}{path}")
        aviso = page.locator(".late-notice")
        aviso.wait_for()
        assert "atrasada" in aviso.inner_text()
    hoja = _abrir_hoja(page, server, "/rutinas")
    hoja.locator("[data-late-all]").click()
    page.wait_for_function("!document.querySelector('.late-notice')")
    assert api.get("/api/items/atrasadas", params={"contexto": "todo"}).json()["pendientes"] == 0
    page.goto(f"{server}/hoy?atrasadas=1")  # lo que abre la notificación del escritorio
    page.wait_for_function("document.querySelector('.late-sheet')?.open")
