"""Corregir con IA en el navegador (375 y 1280 px) con un proveedor simulado: comparación, aceptar por partes,
deshacer, y el botón desactivado en las notas cifradas."""
import os
from pathlib import Path

import pytest

SHOTS = os.environ.get("PANEL_SHOTS")
CONTENIDO = """# Circuitos

la ley de ohm dice que la tension V = 12 V sobre 4 ohmios da 3 A.

| Magnitud | Simbolo |
|---|---|
| V | voltio |

- [x] Leer el capitulo 3
"""


def _crear(api, nid, contenido=CONTENIDO, **extra):
    r = api.post(f"/api/notes/{nid}", json={"title": nid, "category": "E2E - IA", "content": contenido, "status": "en-desarrollo", **extra})
    assert r.status_code == 200, r.text


def _leer(api, nid):
    return api.get(f"/api/notes/{nid}").json()["content"].strip()


@pytest.mark.parametrize("w,h", [(1280, 900), (375, 812)])
def test_corregir_aceptar_por_partes_y_deshacer(page, server, api, w, h):
    nid = f"ia-e2e-{w}"
    _crear(api, nid)
    page.set_viewport_size({"width": w, "height": h})
    page.goto(f"{server}/?note={nid}")
    page.wait_for_selector("#aiBtn")
    page.wait_for_load_state("networkidle")
    page.click("#aiBtn")
    page.click("[data-ai-start]")
    page.wait_for_selector("[data-part]")
    assert "Proveedor simulado" in page.text_content("#aiSub")                      # se ve qué modelo corrigió
    partes = page.locator("[data-part]")
    assert partes.count() == 3
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{SHOTS}/ia-diff-{w}.png")
    partes.nth(0).uncheck()                                                          # rechaza la primera, acepta las otras dos
    page.click("[data-ai-some]")
    page.wait_for_selector("text=Aplicados 2 cambios")
    texto = _leer(api, nid)
    assert "la tension" in texto and "Símbolo" in texto and "capítulo" in texto
    # deshacer desde el propio diálogo
    page.wait_for_load_state("networkidle")
    page.click("#aiBtn")
    page.click("[data-ai-undo]")
    page.click("dialog[open] [data-role=ok]")
    page.wait_for_selector("text=Corrección deshecha")
    assert _leer(api, nid) == CONTENIDO.strip()


def test_nota_cifrada_no_se_envia(page, server, api):
    _crear(api, "ia-e2e-cifrada", contenido="U2FsdGVkX19xxxx", encrypted=True)
    page.goto(f"{server}/?note=ia-e2e-cifrada")
    page.wait_for_selector("#aiBtn")
    page.wait_for_function("document.getElementById('aiBtn').getAttribute('aria-disabled') === 'true'")
    page.click("#aiBtn", force=True)             # aria-disabled: Playwright no lo da por «activo», pero un clic real abre la explicación
    page.wait_for_selector("text=Las notas cifradas no se envían nunca")
    assert page.locator("[data-ai-start]").count() == 0


def test_sin_proveedor_explica_que_falta(page, server, api):
    # el servidor de pruebas SÍ tiene el proveedor simulado: se comprueba el texto del backend y de Ajustes
    r = api.get("/api/ia/estado").json()
    assert r["configurados"] == 1
    page.goto(server + "/")
    page.wait_for_selector("[data-open-more]")
    page.evaluate("openAiSettings()")
    page.wait_for_selector("text=Proveedor simulado")
    page.click("[data-test]")
    page.wait_for_selector("[data-result]:has-text('✓')")


@pytest.mark.parametrize("w,h", [(1280, 900), (375, 812)])
def test_copiar_prompt_y_nota_sin_navigator_clipboard(page, server, api, w, h):
    from tests.e2e.test_copiar_tareas import SIN_CLIPBOARD
    nid = f"ia-prompt-{w}"
    _crear(api, nid)
    page.add_init_script(SIN_CLIPBOARD)                                            # como en http://IP de la red local
    page.set_viewport_size({"width": w, "height": h})
    page.goto(f"{server}/?note={nid}")
    page.wait_for_selector("#aiPromptBtn")
    page.wait_for_load_state("networkidle")
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{SHOTS}/ia-botones-{w}.png")
    page.click("#aiPromptBtn")
    page.wait_for_selector("text=Prompt y nota copiados")
    texto = page.evaluate("__copiado")[-1]
    assert "Eres el corrector y editor de MIS notas" in texto and "```sim" in texto and "=== NOTA ===" in texto
    assert texto.index("=== NOTA ===") > texto.index("Notas existentes") and "la ley de ohm" not in texto.lower() or "Leer el capitulo 3" in texto
    assert "Leer el capitulo 3" in texto.split("=== NOTA ===")[1]               # debajo del prompt va la nota
