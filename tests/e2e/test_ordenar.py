"""Ronda 2 · fase 2: la misma experiencia de ordenar en el Baúl y en Notas (persistente)."""
from tests.e2e.helpers import mouse_drag

ROWS = "ul.web-list[data-cat='E2E orden'] > .web-row"


def _ids(page, sel, attr="id"):
    return page.eval_on_selector_all(sel, f"els => els.map(e => e.dataset.{attr})")


def test_ordenar_baul_y_cambiar_categoria(page, server, api):
    # .invalid nunca resuelve: el scraper no sale a internet
    for n in "abc":
        assert api.post("/api/resources", json={"url": f"https://orden-{n}.invalid/", "category": "E2E orden"}).status_code == 200
    api.post("/api/resources", json={"url": "https://otra.invalid/", "category": "E2E otra"})
    page.goto(server + "/vault")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(ROWS)
    antes = _ids(page, ROWS)
    assert len(antes) == 3
    mouse_drag(page, f"{ROWS}[data-id='{antes[2]}'] .row-title", f"{ROWS}[data-id='{antes[0]}']", "top")
    assert _ids(page, ROWS) == [antes[2], antes[0], antes[1]]
    page.reload()
    page.wait_for_load_state("networkidle")
    assert _ids(page, ROWS) == [antes[2], antes[0], antes[1]]
    # a otra categoría
    otra = "ul.web-list[data-cat='E2E otra'] > .web-row"
    mouse_drag(page, f"{ROWS}[data-id='{antes[1]}'] .row-title", otra, "top")
    assert antes[1] in _ids(page, otra)
    # el clic tras soltar no abre el enlace
    assert len(page.context.pages) == 1


def test_ordenar_notas_en_su_categoria(page, server, api):
    for nid, t in (("e2e-o1", "Uno"), ("e2e-o2", "Dos"), ("e2e-o3", "Tres")):
        api.post(f"/api/notes/{nid}", json={"title": t, "category": "E2E Orden", "content": "x"})
    page.goto(server + "/")
    page.wait_for_load_state("networkidle")
    rows = "#notesList .note-row[data-id^='e2e-o']"
    page.wait_for_selector(rows)
    assert _ids(page, rows) == ["e2e-o2", "e2e-o3", "e2e-o1"]  # alfabético: Dos, Tres, Uno
    mouse_drag(page, f"{rows}[data-id='e2e-o1'] .note-title", f"{rows}[data-id='e2e-o2']", "top")
    assert _ids(page, rows) == ["e2e-o1", "e2e-o2", "e2e-o3"]
    assert "e2e-o1" not in page.url  # soltar no abrió la nota
    page.reload()
    page.wait_for_load_state("networkidle")
    assert _ids(page, rows) == ["e2e-o1", "e2e-o2", "e2e-o3"]
