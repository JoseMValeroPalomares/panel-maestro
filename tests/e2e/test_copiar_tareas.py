"""Copiar varias tareas (con subtareas) al portapapeles desde Tareas e Inbox, en HTTP de la red local.

Por HTTP (no https ni localhost) el navegador NO da `navigator.clipboard`: aquí se elimina para reproducirlo y se
comprueba que el copiado alternativo (textarea + execCommand('copy') dentro del clic) deja el texto correcto.
"""
import os
from pathlib import Path

import pytest

SHOTS = os.environ.get("PANEL_SHOTS")
SIN_CLIPBOARD = """Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
window.__copiado = [];
document.addEventListener('copy', () => { const a = document.activeElement; const s = String(getSelection());
  window.__copiado.push(s || (a && a.value != null ? a.value.substring(a.selectionStart, a.selectionEnd) : '')); }, true);"""


def _nuevo(api, text, **extra):
    r = api.post("/api/items", json={"text": text, "type": "tarea", **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _limpiar(api):
    top = [i for i in api.get("/api/items").json()["items"] if not i["parent_id"] and i["origin"] != "nota"]
    if top:
        api.post("/api/items/bulk", json={"ids": [i["id"] for i in top], "action": "delete"})


@pytest.fixture()
def datos(api):
    _limpiar(api)
    a = _nuevo(api, "Preparar la entrega", details="Revisar el PDF\nAdjuntar la memoria")
    _nuevo(api, "Imprimir", parent_id=a)
    _nuevo(api, "Firmar", parent_id=a)
    b = _nuevo(api, "Comprar pilas")
    c = _nuevo(api, "Llamar al banco")
    api.patch(f"/api/items/{c}", json={"done": True})
    yield {"a": a, "b": b, "c": c}
    _limpiar(api)


def _abrir(page, server, path="/tareas"):
    page.add_init_script(SIN_CLIPBOARD)
    page.goto(server + path)
    page.wait_for_selector(".il .il-group .il-item")
    page.wait_for_load_state("networkidle")


def _seleccionar_grupo(page):
    page.click('[data-act="select-group"]')
    page.wait_for_selector(".il-bulkbar:not([hidden]) [data-bulk=copy]:not([disabled])")


@pytest.mark.parametrize("w,h", [(1280, 900), (375, 812)])
def test_copiar_markdown_con_subtareas_sin_navigator_clipboard(page, server, api, datos, w, h):
    page.set_viewport_size({"width": w, "height": h})
    _abrir(page, server)
    assert page.evaluate("navigator.clipboard") is None                    # como en http://IP
    _seleccionar_grupo(page)
    page.click("[data-bulk=copy]")
    page.wait_for_selector("#copyPreview")
    esperado_md = ["- [ ] Preparar la entrega", "  - [ ] Imprimir", "  - [ ] Firmar", "- [ ] Comprar pilas"]   # «Llamar al banco» está hecha: el filtro por defecto no la enseña
    orden = page.input_value("#copyPreview").split("\n")
    assert sorted(orden) == sorted(esperado_md)                          # el orden es el que se ve en pantalla
    i = orden.index("- [ ] Preparar la entrega")
    assert orden[i:i + 3] == esperado_md[:3]                              # los pasos van sangrados bajo su tarea
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{SHOTS}/copiar-{w}.png")
    page.click("#copyGo")
    page.wait_for_selector("text=Copiado al portapapeles")
    copiado = page.evaluate("__copiado")
    assert copiado
    assert sorted(copiado[-1].split("\n")) == sorted(esperado_md)


def test_texto_plano_con_notas_y_solo_lo_seleccionado(page, server, api, datos):
    _abrir(page, server)
    # Ctrl + clic activa la selección en la primera; Mayús + clic en la otra hace el rango (incluye lo de en medio)
    page.locator('.il-item[data-id="%d"] > .il-row' % datos["a"]).click(modifiers=["Control"], position={"x": 150, "y": 8})
    page.locator('.il-item[data-id="%d"] > .il-row' % datos["b"]).click(modifiers=["Shift"], position={"x": 150, "y": 8})
    page.click("[data-bulk=copy]")
    page.wait_for_selector("#copyPreview")
    page.click("[data-copy-fmt=text]")
    page.uncheck("#copySteps")
    page.check("#copyNotes")
    texto = page.input_value("#copyPreview")
    assert "Preparar la entrega\n  Revisar el PDF\n  Adjuntar la memoria" in texto and "Comprar pilas" in texto
    assert "Imprimir" not in texto and "- [" not in texto
    page.click("#copyGo")
    page.wait_for_selector("text=Copiado al portapapeles")
    assert page.evaluate("__copiado")[-1] == texto
    # las opciones se recuerdan: al volver a abrir, el formato y las casillas siguen igual
    page.click("[data-bulk=copy]")
    assert page.get_attribute("[data-copy-fmt=text]", "aria-pressed") == "true" and page.is_checked("#copyNotes") and not page.is_checked("#copySteps")


def test_copiar_desde_el_inbox(page, server, api, datos):
    _abrir(page, server, "/inbox")
    page.click('[data-act="select-group"]')
    page.click("[data-bulk=copy]")
    page.wait_for_selector("#copyPreview")
    assert "- [ ] Comprar pilas" in page.input_value("#copyPreview")


def test_formato_puro(page, server):
    page.goto(server + "/tareas")
    page.wait_for_selector(".il .il-group")
    r = page.evaluate("""() => ItemCopy.format([{ text: 'Uno\\nlínea 2', done: false, details: 'nota', children: [{ text: 'Paso', done: true, details: '', children: [] }] }], { format: 'md', notes: true })""")
    assert r == "- [ ] Uno\n  línea 2\n  > nota\n  - [x] Paso"
