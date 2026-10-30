"""Rutinas: los días se eligen marcando L M X J V S D (dayPicker en ui.js), igual en todas partes."""
from tests.e2e.test_ronda6 import CARD, _items, _nuevo, _tareas


def chip(root, day):
    return f"{root} .day-option:has([data-day='{day}'])"


def test_captura_con_dias_y_sin_ninguno(page, server, api):
    _tareas(page, server)
    form = ".capture-panel form"
    page.click(f"{form} [data-capture-type=rutina]")
    assert page.locator(f"{form} [data-day]:checked").count() == 7  # por defecto, cada día
    page.click(chip(form, 5))
    page.click(chip(form, 6))
    page.fill(f"{form} [data-capture-text]", "Rutina entre semana")
    page.click(f"{form} [type=submit]")
    page.locator(".il-item", has_text="Rutina entre semana").first.wait_for()
    it = next(i for i in _items(api).values() if i["text"] == "Rutina entre semana")
    assert it["repeat"] == {"freq": "weekly", "days": [0, 1, 2, 3, 4]}
    assert page.locator(f"{form} [data-day]:checked").count() == 7  # vuelve a todos para la siguiente
    # sin ningún día no se guarda
    for d in range(7):
        page.click(chip(form, d))
    page.fill(f"{form} [data-capture-text]", "Rutina sin dias")
    page.click(f"{form} [type=submit]")
    page.locator(".toast", has_text="Elige al menos un día").wait_for()
    assert not any(i["text"] == "Rutina sin dias" for i in _items(api).values())
    for d in range(7):
        page.click(chip(form, d))
    page.fill(f"{form} [data-capture-text]", "")
    page.click(f"{form} [data-capture-type=tarea]")


def test_editor_de_la_tarjeta_y_borrador(page, server, api):
    rid = _nuevo(api, "Rutina a editar", "rutina")
    _tareas(page, server)
    page.click(f"{CARD.format(rid)} [data-act=menu]")
    page.get_by_role("menuitem", name="Editar", exact=True).click()
    ed = f"{CARD.format(rid)} .il-editor"
    assert page.locator(f"{ed} [data-day]:checked").count() == 7
    page.click(chip(ed, 0))
    page.evaluate("Items.load()")  # un repintado (otra pestaña) no pierde lo marcado
    page.wait_for_timeout(300)
    assert page.locator(f"{ed} [data-day]:checked").count() == 6
    page.click(f"{ed} [type=submit]")
    page.wait_for_timeout(400)
    assert _items(api)[rid]["repeat"] == {"freq": "weekly", "days": [1, 2, 3, 4, 5, 6]}


def test_dialogo_de_rutinas_y_cada_n_dias(page, server, api):
    rid = _nuevo(api, "Regar", "rutina", repeat={"freq": "interval", "every": 2})
    page.goto(server + "/rutinas")
    page.wait_for_load_state("networkidle")
    card = page.locator(f"[data-rid='{rid}']")
    if not card.count():  # cada 2 días: puede que hoy no toque
        page.locator(".rp-days button").nth(1).click()
        page.wait_for_load_state("networkidle")
    if not card.count():
        page.locator(".rp-days button").nth(2).click()
        page.wait_for_load_state("networkidle")
    card.locator("[data-act=routine-menu]").click()
    page.get_by_role("menuitem", name="Editar la rutina…").click()
    dlg = "dialog[open]"
    # «cada 2 días» no se puede marcar: sin días y con la nota; guardar sin tocar nada la conserva
    assert page.locator(f"{dlg} [data-day]:checked").count() == 0
    page.locator(f"{dlg} .day-note", has_text="cada 2 días").wait_for()
    page.click(f"{dlg} [type=submit]")
    page.wait_for_timeout(500)
    assert _items(api)[rid]["repeat"]["freq"] == "interval"
    # marcar los 7 la deja en «cada día»
    card.locator("[data-act=routine-menu]").click()
    page.get_by_role("menuitem", name="Editar la rutina…").click()
    for d in range(7):
        page.click(chip(dlg, d))
    page.click(f"{dlg} [type=submit]")
    page.wait_for_timeout(500)
    assert _items(api)[rid]["repeat"] == {"freq": "daily"}


def test_la_tira_de_dias_de_comidas_no_hereda_el_selector_de_rutinas(context, server):
    """Las dos usaban la clase .day-chip y en el móvil la de rutinas deformaba la de Comidas."""
    page = context.new_page()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server}/comidas/")
    label = page.locator(".day-chip-label").first
    label.wait_for()
    assert label.bounding_box()["height"] < 24
