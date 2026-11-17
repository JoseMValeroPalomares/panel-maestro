"""Bloque C · Proyectos: lista con búsqueda, filtros y vistas; tareas en tablero/lista/cronología; ficha con
checklist, subtareas, comentarios y adjuntos; versiones con título; registro de cambios; atajos."""

import uuid

import pytest


@pytest.fixture()
def proyecto(api):
    for key in (
        "proyectos.vista",
        "proyectos.orden",
        "proyecto.agrupar",
        "proyecto.orden-tareas",
        "proyecto.subtareas-abiertas",
        "proyecto.versiones-plegadas",
    ):
        api.put(f"/api/prefs/{key}", json={"value": None})
    # Estas pruebas son del tablero; la vista «Por versión» (la de por defecto) tiene la suya abajo
    api.put("/api/prefs/proyecto.vista-tareas", json={"value": "columnas"})
    nombre = f"Gestor E2E {uuid.uuid4().hex[:5]}"
    p = api.post(
        "/api/proyectos",
        json={
            "nombre": nombre,
            "prioridad": "alta",
            "fecha_inicio": "2026-11-01",
            "fecha_fin": "2026-12-15",
            "etiquetas": ["e2e", "web"],
            "descripcion": "## Objetivo\n\nUn **tablero** como los buenos.",
        },
    ).json()
    v = api.post(
        f"/api/proyectos/{p['id']}/versiones",
        json={"nombre": "v0.1", "titulo": "Primer hito", "fecha_objetivo": "2026-11-30"},
    ).json()
    ids = [
        api.post("/api/items", json={"text": t, "type": "tarea", "proyecto_id": p["id"], **extra}).json()["id"]
        for t, extra in (("Diseñar columnas", {"priority": "alta", "due_date": "2026-11-20"}), ("Escribir docs", {}))
    ]
    api.patch(f"/api/items/{ids[0]}", json={"version_id": v["id"]})
    return {**p, "version": v["id"], "tareas": ids}


def test_lista_busqueda_filtros_y_vistas(page, server, proyecto):
    page.goto(f"{server}/proyectos")
    card = page.locator(".pj-card", has_text=proyecto["nombre"])
    card.wait_for()
    assert "Alta" in card.inner_text() and "#e2e" in card.inner_text()
    # «/» busca en la página (no salta a /buscar)
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "pjSearch"
    page.keyboard.type("no-existe-zzz")
    page.get_by_text("Nada coincide").wait_for()
    page.keyboard.press("Escape")  # vacía la búsqueda
    card.wait_for()
    page.select_option("#pjFTag", "e2e")
    assert page.locator(".pj-card").count() == 1
    # V cambia de vista: tablero por estado y cronología
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("v")
    page.locator(".pj-kanban-4 .pj-col-list[data-estado='en-curso'] .pj-card").first.wait_for()
    page.keyboard.press("v")
    page.locator(".pjg-bar", has_text=proyecto["nombre"]).wait_for()
    assert page.evaluate("Prefs.get('proyectos.vista')") == "cronologia"


def test_ficha_checklist_subtareas_comentarios_y_adjuntos(page, server, api, proyecto, tmp_path):
    page.goto(f"{server}/proyectos/{proyecto['slug']}")
    page.locator(".pj-head-desc strong", has_text="tablero").wait_for()  # descripción en Markdown
    t1 = proyecto["tareas"][0]
    page.locator(f".pj-task-title[data-open='{t1}']").click()
    dlg = page.locator("dialog.pj-ficha[open]")
    dlg.wait_for()
    assert dlg.locator("[data-f=version_id]").input_value() == str(proyecto["version"])
    # Checklist: se añade y se marca sin abrir el editor
    dlg.locator("#pfCheckIn").fill("Probar en el móvil")
    dlg.locator("#pfCheckIn").press("Enter")
    dlg.locator("#pfDesc input[type=checkbox]").first.wait_for()
    dlg.locator("#pfDesc input[type=checkbox]").first.check()
    page.wait_for_function(f"Items.get({t1}).details === '- [x] Probar en el móvil'")
    # Subtarea
    dlg.locator("#pfStepIn").fill("Columna de hechas")
    dlg.locator("#pfStepIn").press("Enter")
    dlg.locator(".pf-step", has_text="Columna de hechas").wait_for()
    # Estado
    dlg.locator("[data-estado=doing]").click()
    page.wait_for_function(f"Items.get({t1}).en_curso === true")
    # Comentario (Ctrl+Enter) y adjunto
    dlg.locator("#pfComIn").fill("Mira **esto**")
    dlg.locator("#pfComIn").press("Control+Enter")
    dlg.locator(".pf-com strong", has_text="esto").wait_for()
    f = tmp_path / "boceto.pdf"
    f.write_bytes(b"%PDF-1.4 boceto")
    dlg.locator("[data-file]").set_input_files(str(f))
    dlg.locator(".pf-file-name", has_text="boceto.pdf").wait_for()
    ex = api.get(f"/api/items/{t1}/extras").json()
    assert len(ex["comentarios"]) == 1 and ex["adjuntos"][0]["nombre"] == "boceto.pdf"
    # Al cerrar, la tarjeta enseña los contadores
    page.keyboard.press("Escape")
    task = page.locator(f".pj-task[data-id='{t1}']")
    task.locator("[title=Comentarios]").wait_for()
    meta = task.inner_text()
    assert "1/1" in meta and "En curso" not in meta  # en el tablero por estado no se repite «En curso»
    assert page.locator(".pj-col[data-col=doing]").locator(f"[data-id='{t1}']").count() == 1


def test_lista_ordenable_cronologia_y_registro(page, server, api, proyecto):
    page.goto(f"{server}/proyectos/{proyecto['slug']}")
    page.locator(".pj-task").first.wait_for()
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("v")  # lista
    page.locator(".pjt").wait_for()
    page.locator(".pjt-sort[data-sort=prioridad]").click()
    assert page.locator(".pjt tbody tr").first.inner_text().strip().startswith("Diseñar columnas")
    assert page.locator(".pjt th[aria-sort=ascending]").inner_text().strip() == "Prioridad"
    page.keyboard.press("v")  # cronología: la tarea con fecha y la versión como hito
    page.locator(".pjg-bar", has_text="Diseñar columnas").wait_for()
    assert page.locator(".pjg-marker-label", has_text="v0.1").count() == 1
    assert "1 sin fecha" in page.locator(".pjg-undated").inner_text()
    # Cerrar la versión con su tarea hecha y verla en el registro de cambios (tecla 3)
    api.patch(f"/api/items/{proyecto['tareas'][0]}", json={"done": True})
    api.post(f"/api/proyectos/versiones/{proyecto['version']}/cerrar", json={})
    page.reload()
    page.locator(".pj-tabs").wait_for()
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("3")
    cl = page.locator(".pj-cl", has_text="v0.1")
    cl.wait_for()
    assert "Primer hito" in cl.inner_text() and "Diseñar columnas" in cl.inner_text()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.locator("[data-copy-log]").click()
    md = page.evaluate("navigator.clipboard.readText()")
    assert (
        md.startswith(f"# Registro de cambios · {proyecto['nombre']}")
        and "## [v0.1] - " in md
        and "· Primer hito" in md
    )


def test_movil_ficha_como_hoja(browser, server, proyecto):
    ctx = browser.new_context(
        viewport={"width": 375, "height": 760}, service_workers="block", has_touch=True, is_mobile=True
    )
    page = ctx.new_page()
    try:
        page.goto(f"{server}/proyectos/{proyecto['slug']}")
        page.locator(".pj-task-title").first.click()
        dlg = page.locator("dialog.pj-ficha[open]")
        dlg.wait_for()
        box = dlg.bounding_box()
        assert box["width"] == 375 and box["y"] > 0  # hoja inferior a todo lo ancho
        assert page.evaluate("document.documentElement.scrollWidth") <= 375
    finally:
        ctx.close()


def test_por_version_con_subtareas_a_la_vista(page, server, api, proyecto):
    api.put("/api/prefs/proyecto.vista-tareas", json={"value": None})  # la de por defecto
    pid = proyecto["id"]
    v2 = api.post(f"/api/proyectos/{pid}/versiones", json={"nombre": "v0.2"}).json()["id"]
    t = api.post(
        "/api/items", json={"text": "Con pasos", "type": "tarea", "proyecto_id": pid, "version_id": v2}
    ).json()["id"]
    api.post("/api/items", json={"text": "Paso uno", "type": "tarea", "parent_id": t})
    page.goto(f"{server}/proyectos/{proyecto['slug']}")
    sec = page.locator(f".pj-vsec[data-vkey='v{v2}']")
    sec.wait_for()
    # una sección por versión, con la tarea y su subtarea a la vista (sin abrir nada)
    assert page.locator(".pj-vsec").count() >= 2
    tarea = sec.locator(f".pj-vtask[data-id='{t}']")
    assert tarea.locator(".pj-sub-text").all_inner_texts() == ["Paso uno"]
    # añadir una subtarea desde la lista y seguir escribiendo otra
    tarea.locator("[data-add-sub]").click()
    page.keyboard.type("Paso dos")
    page.keyboard.press("Enter")
    page.wait_for_function(f"document.querySelectorAll('#pjs-{t} .pj-sub').length === 2")
    page.wait_for_function(f"document.activeElement?.id === 'pjsa-{t}'")  # se puede seguir escribiendo
    page.keyboard.press("Escape")
    # marcar una subtarea aquí mismo
    page.locator(f"#pjs-{t} .pj-sub", has_text="Paso uno").locator("input").check()
    page.wait_for_function(f"document.querySelector('#pjs-{t} .pj-sub.is-done')")
    # plegar se guarda
    page.locator(f"[data-fold-task='{t}']").click()
    page.wait_for_timeout(400)
    page.reload()
    page.locator(f"[data-fold-task='{t}']").wait_for()
    assert page.locator(f"[data-fold-task='{t}']").get_attribute("aria-expanded") == "false"
    assert page.locator(f"#pjs-{t}").is_hidden()
    # el título abre los detalles en una ventana centrada
    page.locator(f".pj-task-title[data-open='{t}']").click()
    box = page.locator("dialog.pj-ficha[open]").bounding_box()
    vw = page.viewport_size["width"]
    assert abs((box["x"] + box["width"] / 2) - vw / 2) < 4
