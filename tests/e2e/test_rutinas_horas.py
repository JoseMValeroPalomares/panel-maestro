"""/rutinas: cada bloque a la hora que quieras, en la propia línea, con huecos y sin solaparse."""
from datetime import datetime, timedelta

from playwright.sync_api import expect

from tests.e2e.test_ronda6 import _items, _nuevo


def _limpiar(api):
    for i in _items(api).values():
        if i["type"] == "rutina" and not i["parent_id"]:
            api.delete(f"/api/items/{i['id']}")


def _dia(page, server, api):
    """Una rutina con dos bloques con hora, separados, y uno flexible."""
    _limpiar(api)
    rid = _nuevo(api, "Mi jornada", "rutina")
    a = _nuevo(api, "Desayunar 20 min", parent_id=rid, due_time="08:00")
    b = _nuevo(api, "Gimnasio 1h", parent_id=rid, due_time="17:30")
    c = _nuevo(api, "Leer 30 min", parent_id=rid)
    page.goto(f"{server}/rutinas")
    page.locator(f"[data-step='{c}']").wait_for()
    return rid, a, b, c


def _hora(page, sid):
    return f"[data-step='{sid}'] [data-time=start]"


def test_poner_hora_en_la_linea_y_ver_los_huecos(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    assert page.locator(_hora(page, a)).input_value() == "08:00"
    assert page.locator(_hora(page, c)).input_value() == ""
    assert page.locator(".rp-gap").inner_text() == "Libre 9 h 10"
    # sin hora va al final; al ponérsela, ocupa su sitio en el reloj y parte el hueco en dos
    page.fill(_hora(page, c), "12:00")
    page.press(_hora(page, c), "Enter")
    expect(page.locator(".rp-gap")).to_have_text(["Libre 3 h 40", "Libre 5 h"])
    assert page.locator(".rp-step").evaluate_all("l => l.map(e => Number(e.dataset.step))") == [a, c, b]
    assert _items(api)[c]["due_time"] == "12:00"
    assert _items(api)[b]["due_time"] == "17:30"  # el resto no se mueve


def test_una_hora_que_choca_se_rechaza_y_vuelve_atras(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    page.fill(_hora(page, a), "17:45")
    page.press(_hora(page, a), "Enter")
    page.locator(".toast", has_text="choca con «Gimnasio» (17:30–18:30)").wait_for()
    page.locator(".toast", has_text="El primer hueco libre es a las 18:30").wait_for()
    assert page.locator(_hora(page, a)).input_value() == "08:00"
    assert _items(api)[a]["due_time"] == "08:00"


def test_tab_pasa_a_la_siguiente_hora_sin_perder_el_foco(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    page.fill(_hora(page, a), "09:00")
    page.locator(_hora(page, b)).focus()  # lo mismo que hace Tab: el campo anterior se guarda al salir
    expect(page.locator(".rp-gap")).to_have_text("Libre 8 h 10")
    expect(page.locator(_hora(page, b))).to_be_focused()
    assert _items(api)[a]["due_time"] == "09:00"


def test_anadir_con_hora_y_quitarla_desde_el_menu(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    page.fill(f"#rp-add-{rid}", "Comer 1h")
    page.fill(f"#rp-add-at-{rid}", "14:00")
    page.press(f"#rp-add-{rid}", "Enter")
    page.locator(".rp-step", has_text="Comer").wait_for()
    nuevo = next(i for i in _items(api).values() if i["text"] == "Comer")
    assert nuevo["due_time"] == "14:00" and nuevo["duration_min"] == 60
    # encima de otro: no se crea y no se pierde lo escrito
    page.fill(f"#rp-add-{rid}", "Siesta 1h")
    page.fill(f"#rp-add-at-{rid}", "14:30")
    page.press(f"#rp-add-{rid}", "Enter")
    page.locator(".toast", has_text="choca con «Comer»").wait_for()
    assert page.input_value(f"#rp-add-{rid}") == "Siesta 1h"
    assert not any(i["text"] == "Siesta" for i in _items(api).values())
    page.click(f"[data-step='{nuevo['id']}'] [data-act=step-menu]")
    page.get_by_role("menuitem", name="Quitar la hora").click()
    expect(page.locator(_hora(page, nuevo["id"]))).to_have_value("")
    assert _items(api)[nuevo["id"]]["due_time"] is None


def test_paso_a_paso_no_empieza_el_siguiente_antes_de_su_hora(page, server, api):
    _limpiar(api)
    ahora = datetime.now()
    if ahora.hour >= 22:
        return  # la hora «de luego» pasaría de medianoche
    luego = (ahora + timedelta(hours=1)).strftime("%H:%M")
    rid = _nuevo(api, "Con hueco", "rutina")
    _nuevo(api, "Primero 10 min", parent_id=rid, due_time="00:00")
    _nuevo(api, "Segundo 25 min", parent_id=rid, due_time=luego)
    page.goto(f"{server}/rutinas")
    page.click(f"[data-rid='{rid}'] [data-act=run]")
    page.locator(".rt-run-title", has_text="Primero").wait_for()
    assert page.locator("[data-left]").count() == 1
    page.click("[data-run-act=done]")
    page.locator(".rt-run-title", has_text="Segundo").wait_for()
    page.locator(".rt-run-now", has_text=f"Libre hasta las {luego}").wait_for()
    assert page.locator("[data-left]").count() == 0  # sin temporizador en marcha
    page.click("[data-run-act=now]")
    page.locator("[data-left]").wait_for()


def test_la_hora_se_escribe_en_24_h_como_venga(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    page.fill(_hora(page, c), "1215")
    page.press(_hora(page, c), "Enter")
    expect(page.locator(_hora(page, c))).to_have_value("12:15")
    assert _items(api)[c]["due_time"] == "12:15"
    # lo que no es una hora no se guarda ni borra la que había
    page.fill(_hora(page, a), "25:00")
    page.press(_hora(page, a), "Enter")
    page.locator(".toast", has_text="Escribe la hora como 17:30").wait_for()
    expect(page.locator(_hora(page, a))).to_have_value("08:00")
    assert _items(api)[a]["due_time"] == "08:00"
    # vaciar el campo le quita la hora
    page.fill(_hora(page, c), "")
    page.press(_hora(page, c), "Enter")
    expect(page.locator(_hora(page, c))).to_have_attribute("title", "Sin hora: ponle una")
    assert _items(api)[c]["due_time"] is None


def test_plantilla_con_horas_editables(page, server, api):
    _limpiar(api)
    page.goto(f"{server}/rutinas")
    page.click("#rtTemplates")
    page.locator(".rt-card", has_text="Rutina de mañana").click()
    # cambiar la hora de la rutina desplaza todos los pasos; uno se puede mover a mano
    page.fill("#rtForm [name=due_time]", "08:00")
    page.locator("#rtForm [name=due_time]").blur()
    expect(page.locator("#rtA1")).to_have_value("08:02")
    page.fill("#rtA5", "1900")
    page.locator("#rtA5").blur()
    expect(page.locator("#rtA5")).to_have_value("19:00")
    page.click("[type=submit][form=rtForm]")
    page.locator(".toast", has_text="creada").wait_for()
    pasos = {i["text"]: i["due_time"] for i in _items(api).values() if i["type"] == "rutina" and i["parent_id"]}
    assert pasos["Beber un vaso de agua"] == "08:00" and pasos["Mirar la agenda del día"] == "19:00"


def _arrastrar_a(page, sid, antes_de):
    """Suelta el bloque por su asa justo encima de otro."""
    a = page.locator(f"[data-step='{sid}'] [data-drag-handle]").bounding_box()
    b = page.locator(f"[data-step='{antes_de}']").bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(a["x"] + a["width"] / 2 + 6, a["y"] - 12, steps=4)
    page.mouse.move(b["x"] + 120, b["y"] + 4, steps=12)
    page.wait_for_timeout(120)
    page.mouse.up()
    page.wait_for_timeout(400)  # sortable.js descarta el clic justo después de soltar


def test_arrastrar_un_bloque_olvidado_a_su_sitio(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    assert page.locator(f"[data-step='{c}'] .rp-grip").count() == 1
    _arrastrar_a(page, c, b)
    page.locator(".toast", has_text="«Leer» a las 08:20").wait_for()
    expect(page.locator(_hora(page, c))).to_have_value("08:20")
    assert page.locator(".rp-step").evaluate_all("l => l.map(e => Number(e.dataset.step))") == [a, c, b]
    assert _items(api)[b]["due_time"] == "17:30"


def test_si_no_cabe_pregunta_antes_de_mover_los_siguientes(page, server, api):
    _limpiar(api)
    rid = _nuevo(api, "Mañana apretada", "rutina")
    a = _nuevo(api, "Desayuno 20 min", parent_id=rid, due_time="08:00")
    b = _nuevo(api, "Clase 1h", parent_id=rid, due_time="08:20")
    c = _nuevo(api, "Ducha 15 min", parent_id=rid)
    page.goto(f"{server}/rutinas")
    page.locator(f"[data-step='{c}']").wait_for()
    _arrastrar_a(page, c, b)
    dlg = page.locator("dialog[open]", has_text="no cabe ahí")
    dlg.wait_for()
    assert "«Clase» empezaría 15 min más tarde" in dlg.inner_text()
    dlg.get_by_role("button", name="Cancelar").click()
    expect(page.locator(_hora(page, c))).to_have_value("")
    assert _items(api)[b]["due_time"] == "08:20"
    page.wait_for_load_state("networkidle")
    _arrastrar_a(page, c, b)
    page.locator("dialog[open]", has_text="no cabe ahí").get_by_role("button", name="Mover").click()
    expect(page.locator(_hora(page, c))).to_have_value("08:20")
    assert _items(api)[b]["due_time"] == "08:35" and _items(api)[a]["due_time"] == "08:00"


def test_el_fin_se_escribe_en_la_linea(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    fin = f"[data-step='{a}'] [data-time=end]"
    expect(page.locator(fin)).to_have_value("08:20")
    assert page.locator(f"[data-step='{c}'] [data-time=end]").count() == 0  # sin inicio no hay fin
    # escribir el fin da la duración
    page.fill(fin, "0915")
    page.press(fin, "Enter")
    expect(page.locator(fin)).to_have_value("09:15")
    assert _items(api)[a]["duration_min"] == 75
    expect(page.locator(f"[data-step='{a}'] .rp-dur")).to_have_text("1 h 15")
    # mover el inicio lleva el fin consigo y conserva la duración
    page.fill(_hora(page, a), "1000")
    page.press(_hora(page, a), "Enter")
    expect(page.locator(fin)).to_have_value("11:15")
    assert _items(api)[a]["duration_min"] == 75
    # un fin que choca se rechaza; vacío quita la duración
    page.fill(fin, "18:00")
    page.press(fin, "Enter")
    page.locator(".toast", has_text="choca con «Gimnasio»").wait_for()
    expect(page.locator(fin)).to_have_value("11:15")
    page.fill(fin, "")
    page.press(fin, "Enter")
    expect(page.locator(fin)).to_have_value("")
    assert _items(api)[a]["duration_min"] is None


def test_anadir_con_inicio_y_fin_y_dialogo_del_bloque(page, server, api):
    rid, a, b, c = _dia(page, server, api)
    page.fill(f"#rp-add-{rid}", "Comer")
    page.fill(f"#rp-add-at-{rid}", "14")
    page.fill(f"#rp-add-end-{rid}", "1530")
    page.press(f"#rp-add-{rid}", "Enter")
    page.locator(".rp-step", has_text="Comer").wait_for()
    nuevo = next(i for i in _items(api).values() if i["text"] == "Comer")
    assert nuevo["due_time"] == "14:00" and nuevo["duration_min"] == 90
    # en el diálogo los tres campos van juntos
    page.locator(f"[data-step='{nuevo['id']}'] .rp-step-title").click()
    page.locator("#rpStepEnd").wait_for()
    assert page.input_value("#rpStepEnd") == "15:30" and page.input_value("#rpStepDur") == "90"
    page.locator("dialog[open] [data-dur='30']").click()
    assert page.input_value("#rpStepEnd") == "14:30"
    page.fill("#rpStepEnd", "15:00")
    page.locator("#rpStepEnd").dispatch_event("change")
    assert page.input_value("#rpStepDur") == "60"
    page.get_by_role("button", name="Guardar").click()
    expect(page.locator(f"[data-step='{nuevo['id']}'] [data-time=end]")).to_have_value("15:00")
