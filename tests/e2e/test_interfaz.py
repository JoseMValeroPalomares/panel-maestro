"""Evolución de la interfaz (fases 3 y 4): acciones data-call sin JS en línea, tooltip con teclado, pestañas del
móvil, errores con «Reintentar», simulaciones en /sim y librerías de Notas cargadas solo cuando hacen falta."""
import pytest
from playwright.sync_api import expect

SIM = "```sim\n<!DOCTYPE html><html><body><p id='ok'>listo</p><script>document.getElementById('ok').textContent = 'corre';</script></body></html>\n```"


@pytest.fixture()
def notas(api):
    api.post("/api/notes/interfaz-plana", json={"title": "Interfaz plana", "category": "E2E", "content": "# Interfaz plana\n\nSin nada.", "tags": []})
    api.post("/api/notes/interfaz-rica", json={"title": "Interfaz rica", "category": "E2E", "tags": [],
                                               "content": f"Fórmula $E = mc^2$\n\n```python\nprint('hola')\n```\n\n{SIM}\n"})
    yield
    for slug in ("interfaz-plana", "interfaz-rica"):
        api.delete(f"/api/notes/{slug}")


def _abrir_nota(page, server, slug):
    page.goto(f"{server}/?note={slug}")
    page.locator("#noteTitle").wait_for()
    page.locator("[data-call=setMode][data-args*=read]").click()


def test_acciones_data_call_y_csp_sin_js_en_linea(page, server, api, notas):
    respuesta = page.goto(server + "/")
    assert "'unsafe-inline'" not in respuesta.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    page.goto(f"{server}/?note=interfaz-plana")
    page.locator("[data-call=setMode][data-args*=edit]").click()
    expect(page.locator("#editPane")).to_be_visible()
    page.locator("#noteContent").press("Control+End")
    page.locator("[data-call=wrapSelection][data-args*='**']").click()
    assert page.locator("#noteContent").input_value().endswith("**texto**")  # sin selección pone un ejemplo
    # varias llamadas en un botón (Ajustes → avisos): cierra la hoja y abre los ajustes de avisos
    page.goto(server + "/hoy")
    page.locator(".sidebar-footer [data-open-more]").click()
    page.locator("[data-call='closeModal;Reminders.openSettings']").click()
    expect(page.locator("#moreSheet")).not_to_be_visible()


def test_libs_de_notas_solo_cuando_hacen_falta(page, server, notas):
    libs = "performance.getEntriesByType('resource').filter(r => /katex\\.min\\.js|highlight\\.min\\.js/.test(r.name)).length"
    _abrir_nota(page, server, "interfaz-plana")
    page.wait_for_timeout(300)
    assert page.evaluate(libs) == 0
    assert page.locator("#readContent > h1.title-echo").count() == 1  # el «# Título» no se repite al leer
    _abrir_nota(page, server, "interfaz-rica")
    page.locator("#readContent .katex").first.wait_for()
    page.locator("#readContent pre code.hljs").first.wait_for()
    assert page.evaluate(libs) == 2


def test_simulacion_corre_aislada_en_sim(browser, server, notas):
    # contexto propio: el bloqueo de service workers de Playwright choca con un iframe con sandbox
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errores = []
    page.on("pageerror", lambda e: errores.append(str(e)))
    try:
        _abrir_nota(page, server, "interfaz-rica")
        page.locator("[data-sim-run]").first.click()
        frame = page.frame_locator(".sim-frame-wrap iframe").first
        expect(frame.locator("#ok")).to_have_text("corre")
        assert page.locator(".sim-frame-wrap iframe").get_attribute("sandbox") == "allow-scripts"
        assert not errores
    finally:
        ctx.close()


def test_tooltip_con_el_foco_del_teclado(page, server):
    page.goto(server + "/tareas")
    boton = page.locator(".il-addstep").first
    boton.wait_for()
    boton.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")  # foco «de teclado» (:focus-visible)
    expect(page.locator(".tip.is-on")).to_have_text("Añadir un paso (E)")
    assert boton.get_attribute("title") is None and boton.get_attribute("aria-label")


def test_error_de_carga_con_reintentar(browser, server):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
    page = ctx.new_page()
    fallar = {"si": True}
    page.route("**/api/today*", lambda r: r.fulfill(status=500, content_type="application/json", body='{"error":"x"}')
               if fallar["si"] else r.continue_())
    try:
        page.goto(server + "/hoy")
        estado = page.locator("#hoyAgenda [data-state-kind=error]")
        expect(estado).to_contain_text("No se pudo cargar el día")
        fallar["si"] = False
        page.locator("#hoyAgenda [data-state-retry]").click()
        expect(estado).to_have_count(0)
        page.locator("#hoyAgenda .hoy-list, #hoyAgenda .hoy-empty").first.wait_for()
    finally:
        ctx.close()


def test_pestanas_del_movil_se_eligen_y_se_recuerdan(browser, server):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, service_workers="block")
    page = ctx.new_page()
    visibles = "() => [...document.querySelectorAll('.tabbar a.tab:not([hidden])')].map(t => t.dataset.section)"
    try:
        page.goto(server + "/hoy")
        page.wait_for_load_state("networkidle")
        assert page.evaluate(visibles) == ["hoy", "calendario", "tareas", "notas"]
        page.locator(".tab-more").tap()
        page.locator("[data-tabbar-choice][value=notas]").uncheck()
        page.locator("[data-tabbar-choice][value=comidas]").check()
        assert page.locator("[data-tabbar-choice]:disabled").count() == 14  # con 4 elegidas, el resto bloqueado
        page.wait_for_timeout(600)  # Prefs se guarda en el servidor con un pequeño retardo
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.evaluate(visibles) == ["hoy", "calendario", "tareas", "comidas"]
        page.goto(server + "/inbox")  # sin el Inbox en la barra, «Más» lleva su insignia y se marca si estás en otra
        assert page.locator(".tab-more .tab-badge").count() == 1
    finally:
        page.evaluate("Prefs.set('tabbar', [])")
        page.wait_for_timeout(600)
        ctx.close()


def test_el_contenido_de_una_nota_no_puede_disparar_acciones(page, server, api):
    """DOMPurify quita los data-*: un botón con data-call escrito en una nota no hace nada."""
    api.post("/api/notes/interfaz-trampa", json={"title": "Interfaz trampa", "category": "E2E", "tags": [],
                                                 "content": "<button data-call=\"Palette.open\" data-args='[]'>Pulsa</button>\n"})
    try:
        _abrir_nota(page, server, "interfaz-trampa")
        boton = page.locator("#readContent button", has_text="Pulsa")
        boton.wait_for()
        assert boton.get_attribute("data-call") is None
        boton.click()
        page.wait_for_timeout(200)
        assert not page.locator("dialog.palette[open]").count()
    finally:
        api.delete("/api/notes/interfaz-trampa")
