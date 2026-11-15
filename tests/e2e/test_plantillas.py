"""P-4 · Galería única de plantillas (tablero · día · rutina): aplicar y guardar cada clase."""

import json

from playwright.sync_api import expect

from tests.e2e.test_ronda6 import _items
from tests.e2e.test_rutinas_horas import _limpiar


def _galeria_en(page, tab):
    page.locator(f".tg [data-tg-tab={tab}]").first.click()
    page.locator(".tg .tg-card").first.wait_for()


def test_tablero_desde_la_galeria_y_guardar_el_tablero_entero(page, server, api):
    page.goto(f"{server}/inbox")
    page.wait_for_load_state("networkidle")
    r = api.post("/api/boards", json={"name": "Plantillas e2e"}).json()
    page.goto(f"{server}/inbox")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("window.__board && window.__board.state.boardId")
    page.locator("#paneTabPlantilla").click()
    tile = page.locator('#templateList .tg-item[data-key="c:matriz"]')
    tile.wait_for()
    expect(tile.locator(".tg-thumb svg")).to_be_visible()  # miniatura
    page.locator("#templateList [data-tg-q]").fill("eisenhower")  # buscar por etiqueta
    expect(page.locator("#templateList .tg-card")).to_have_count(1)
    antes = page.evaluate("window.__board.state.doc.nodes.length")
    tile.click()
    page.wait_for_function(f"window.__board.state.doc.nodes.length === {antes} + 8")
    page.locator("#templateList [data-tg-q]").fill("")
    # el tablero entero como plantilla (menú de plantillas del tablero)
    page.locator("#btnTemplates").click()
    page.get_by_role("menuitem", name="Guardar el tablero entero como plantilla").click()
    page.locator("dialog[open] input").fill("Mi matriz")
    page.locator("dialog[open] [data-role=ok]").click()
    page.locator('#templateList .tg-item:has-text("Mi matriz")').wait_for()
    t = next(t for t in api.get("/api/board-templates").json()["templates"] if t["name"] == "Mi matriz")
    assert len(json.loads(t["data"])["nodes"]) == antes + 8
    # duplicar desde su menú
    page.locator('#templateList .tg-item:has-text("Mi matriz") [data-tg-menu]').click()
    page.get_by_role("menuitem", name="Duplicar").click()
    page.locator('#templateList .tg-item:has-text("Mi matriz (copia)")').wait_for()
    assert r["id"]


def test_dia_de_serie_en_una_fecha(page, server, api):
    page.goto(f"{server}/calendario?dia=2026-12-07")
    page.wait_for_load_state("networkidle")
    page.locator("#calMenuBtn").click()
    page.get_by_role("menuitem", name="Aplicar una plantilla de día").click()
    page.locator('.tg-item[data-key="b:examen"]').wait_for()
    page.locator('.tg-item[data-key="b:examen"]').click()
    inp = page.locator("dialog[open] input").last
    expect(inp).to_have_value("2026-12-07")  # el día que se está viendo
    inp.fill("8/12")
    page.locator("dialog[open] [data-role=ok]").last.click()
    page.locator(".toast", has_text="Día de examen").wait_for()
    evs = api.get("/api/calendar/entries", params={"start": "2026-12-08", "end": "2026-12-08"}).json()["entries"]
    assert any(e["title"] == "Examen" and e["start"] == "2026-12-08T10:00" for e in evs)


def test_rutina_de_serie_copia_editada_y_aplicada(page, server, api):
    _limpiar(api)
    page.goto(f"{server}/rutinas")
    page.locator("#rtTemplates").click()
    card = page.locator('.tg-item[data-key="b:estirar"]')
    card.wait_for()
    card.locator("[data-tg-menu]").click()
    page.get_by_role("menuitem", name="Hacer una copia mía").click()
    mine = page.locator('.tg-item:has-text("Estiramientos (mía)")')
    mine.wait_for()
    mine.locator("[data-tg-menu]").click()
    page.get_by_role("menuitem", name="Editar los pasos").click()
    page.locator("dialog[open] textarea").fill("cuello 2m\nespalda 3m")
    page.locator("dialog[open] [data-role=ok]").last.click()
    page.wait_for_timeout(400)
    page.locator('.tg-item:has-text("Estiramientos (mía)")').click()  # usar: el formulario de siempre, ya relleno
    page.locator("#rtForm").wait_for()
    expect(page.locator("#rtS1")).to_have_value("Espalda")
    page.click("[type=submit][form=rtForm]")
    page.locator(".toast", has_text="creada").wait_for()
    r = next(i for i in _items(api).values() if i["type"] == "rutina" and not i["parent_id"])
    assert sorted(i["text"] for i in _items(api).values() if i["parent_id"] == r["id"]) == ["Cuello", "Espalda"]


def test_tarea_con_pasos_como_plantilla_de_tablero(page, server, api):
    tid = api.post("/api/items", json={"text": "Preparar el viaje"}).json()["id"]
    for t in ("Billetes", "Maleta"):
        api.post("/api/items", json={"text": t, "parent_id": tid})
    page.goto(f"{server}/tareas?item={tid}")
    card = page.locator(f".il-item[data-id='{tid}']").first
    card.wait_for()
    card.locator("> .il-row [data-act=menu]").click()
    page.get_by_role("menuitem", name="Guardar como plantilla de tablero").click()
    page.locator("dialog[open] [data-role=ok]").click()
    page.locator(".toast", has_text="Plantilla guardada").wait_for()
    t = next(t for t in api.get("/api/board-templates").json()["templates"] if t["name"] == "Preparar el viaje")
    assert [n["text"] for n in json.loads(t["data"])["nodes"]] == ["Preparar el viaje", "Billetes", "Maleta"]
