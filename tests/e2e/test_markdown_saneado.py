"""S-2: el Markdown de Proyectos (registro de cambios y bitácora) pasa por renderMarkdown() de ui.js.

Un <a data-call="closeModal" style="x"> pegado desde fuera no puede llegar al DOM: el despachador data-call de
ui.js ejecuta funciones desde atributos, así que el contenido del usuario nunca lleva data-* ni style.
"""

import re

MALO = 'Antes <a href="#" data-call="closeModal" style="x" id="malo">pulsa</a> después'


def test_bitacora_y_changelog_sin_data_call_ni_style(page, server):
    r = page.request.post(f"{server}/api/proyectos", data={"nombre": "Saneado E2E"})
    assert r.ok, r.text()
    p = r.json()
    pid, slug = p["id"], p["slug"]

    vid = page.request.post(f"{server}/api/proyectos/{pid}/versiones", data={"nombre": "v0.1"}).json()["id"]
    assert page.request.patch(f"{server}/api/proyectos/versiones/{vid}", data={"changelog": MALO}).ok

    note_id = page.request.post(f"{server}/api/proyectos/{pid}/bitacora").json()["note_id"]
    nota = page.request.get(f"{server}/api/notes/{note_id}").json()
    r = page.request.post(
        f"{server}/api/notes/{note_id}",
        data={
            "title": nota["title"],
            "category": nota["category"],
            "status": "en-desarrollo",
            "content": f"# Bitácora\n\n{MALO}\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        },
    )
    assert r.ok, r.text()

    for pestana, caja in (("versiones", ".pj-log"), ("bitacora", ".pj-note")):
        page.goto(f"{server}/proyectos/{slug}?pestana={pestana}")
        enlace = page.locator(f"{caja} a#malo")
        enlace.wait_for()
        html = enlace.evaluate("a => a.outerHTML")
        assert "data-call" not in html and "style" not in html, html
        assert re.search(r'href="#"', html)
    # la tabla de la bitácora sigue pintándose (el saneado no se come el Markdown)
    assert page.locator(".pj-note table td", has_text="2").count() == 1
