"""Sexta ronda: criterios de aceptación en el navegador (1280 px y, donde se indica, 375 px).

1. Subtarea nueva: campo vacío. Recargar (y otro navegador): plegados intactos.
3. Escribir en una nota vacía «por escribir» la pasa a «en desarrollo».
5. E sobre una tarea añade un paso; el botón está a la izquierda de la flecha; nada se dispara al escribir.
6. Enlazar tarea ↔ nota desde los dos lados y navegar con un clic.
Además: notas de una tarea legibles sin editar y marco del texto suelto del tablero.
"""
import pytest

from tests.e2e.test_board import _board, _open, doc, screen

CARD = '.il-item[data-id="{}"]'


def _nuevo(api, text, type="tarea", **extra):
    r = api.post("/api/items", json={"text": text, "type": type, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _items(api):
    return {i["id"]: i for i in api.get("/api/items").json()["items"]}


def _tareas(page, server, path="/tareas"):
    page.goto(server + path)
    page.wait_for_selector(".il .il-group")
    page.wait_for_load_state("networkidle")


@pytest.mark.parametrize("w", [1280, 375])
def test_1_subtarea_con_el_campo_vacio(browser, server, api, w):
    ctx = browser.new_context(viewport={"width": w, "height": 860}, service_workers="block", has_touch=w < 500)
    page = ctx.new_page()
    padre = _nuevo(api, f"Padre {w}")
    _tareas(page, server)
    page.click(f"{CARD.format(padre)} > .il-row [data-act=add-step]")
    campo = page.locator(f"{CARD.format(padre)} .il-addform input")
    assert campo.input_value() == ""
    campo.fill("Primer paso")
    campo.press("Enter")
    page.wait_for_function("() => Items.state.items.some(i => i.text === 'Primer paso')")
    page.wait_for_timeout(200)
    assert page.locator(f"{CARD.format(padre)} .il-addform input").input_value() == ""
    page.locator(f"{CARD.format(padre)} .il-addform input").fill("Segundo paso")
    page.locator(f"{CARD.format(padre)} .il-addform input").press("Enter")
    page.wait_for_function("() => Items.state.items.some(i => i.text === 'Segundo paso')")
    assert page.locator(f"{CARD.format(padre)} .il-addform input").input_value() == ""
    hijos = [i["text"] for i in _items(api).values() if i["parent_id"] == padre]
    assert sorted(hijos) == ["Primer paso", "Segundo paso"]
    ctx.close()


def test_1_plegados_persisten_en_el_servidor(browser, server, api):
    _nuevo(api, "Algo en el Inbox")
    a = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
    pa = a.new_page()
    _tareas(pa, server)
    pa.click('[data-il-fold="page:g:ideas"]')
    pa.wait_for_timeout(700)  # se guarda en el servidor
    pa.reload()
    pa.wait_for_selector(".il .il-group")
    assert pa.get_attribute('[data-il-fold="page:g:ideas"]', "aria-expanded") == "false"
    # otro navegador (sin la caché de localStorage)
    b = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block")
    pb = b.new_page()
    _tareas(pb, server)
    pb.wait_for_function("() => document.querySelector('[data-il-fold=\"page:g:ideas\"]').getAttribute('aria-expanded') === 'false'")
    # árbol de la pestaña Notas
    pb.goto(server + "/")
    pb.wait_for_selector(".tree-row")
    pb.locator(".tree-row").first.click()
    pb.wait_for_timeout(700)
    pc = browser.new_context(viewport={"width": 1280, "height": 900}, service_workers="block").new_page()
    pc.goto(server + "/")
    pc.wait_for_selector(".tree-row")
    pc.wait_for_function("() => document.querySelector('.tree-row').getAttribute('aria-expanded') === 'false'")
    pa.click('[data-il-fold="page:g:ideas"]')  # lo deja como estaba
    pb.locator(".tree-row").first.click()
    pb.wait_for_timeout(700)
    a.close()
    b.close()
    pc.context.close()


def test_3_nota_vacia_pasa_a_en_desarrollo(page, server, api):
    page.goto(server + "/")
    page.wait_for_selector(".tree-row")
    page.evaluate("createNoteDirect('Vacía E2E', 'E2E')")
    page.wait_for_function("() => activeNoteId === 'vacia-e2e'")
    page.wait_for_timeout(1300)
    assert page.evaluate("activeStatus") == "por-escribir"
    page.locator("#noteContent").click()
    page.keyboard.press("Control+End")
    page.keyboard.type("Primera frase.")
    page.wait_for_function("() => activeStatus === 'en-desarrollo'")
    page.wait_for_timeout(1500)  # autoguardado
    assert api.get("/api/notes/vacia-e2e").json()["status"] == "en-desarrollo"
    # solo esa transición: si se vuelve a «por escribir» a mano, se respeta
    page.evaluate("setNoteStatus('por-escribir')")
    page.wait_for_timeout(300)
    page.keyboard.type(" Más.")
    page.wait_for_timeout(300)
    assert page.evaluate("activeStatus") == "por-escribir"
    api.delete("/api/notes/vacia-e2e")


def test_5_tecla_e_y_boton_de_paso(page, server, api):
    padre = _nuevo(api, "Tarea con E")
    _nuevo(api, "Paso previo", parent_id=padre)
    _tareas(page, server)
    fila = f"{CARD.format(padre)} > .il-row"
    # el botón de añadir paso está a la izquierda de la flecha de desplegar (no en el menú «…»)
    add = page.locator(f"{fila} > [data-act=add-step]").bounding_box()
    flecha = page.locator(f"{fila} > .il-kids-fold").bounding_box()
    assert add["x"] + add["width"] <= flecha["x"] + 1
    assert abs(add["y"] - flecha["y"]) < 4
    # con el ratón encima, E abre «Nuevo paso…»
    page.hover(f"{fila} .il-text")
    page.keyboard.press("e")
    campo = page.locator(f"{CARD.format(padre)} .il-addform input")
    campo.wait_for()
    assert campo.evaluate("el => el === document.activeElement")
    # escribir una «e» en el campo no dispara nada más
    campo.type("este paso")
    assert campo.input_value() == "este paso"
    assert page.locator(".il-addform").count() == 1
    campo.press("Escape")
    # escribir en el buscador con el ratón sobre otra tarjeta tampoco
    page.hover(f"{fila} .il-text")
    page.fill("#taskSearch", "")
    page.locator("#taskSearch").type("e")
    page.wait_for_timeout(200)
    assert page.locator(".il-addform").count() == 0
    page.fill("#taskSearch", "")


def test_6_notas_de_la_tarea_legibles_sin_editar(page, server, api):
    tid = _nuevo(api, "Con notas", details="**Importante**: llamar\n\n- uno\n- dos")
    _tareas(page, server)
    # las notas se ven sin pulsar nada; «Notas» las oculta en esa tarea (y se recuerda)
    caja = page.locator(f"{CARD.format(tid)} .il-details-md")
    assert caja.locator("strong").inner_text() == "Importante"
    assert caja.locator("li").count() == 2
    page.click(f"{CARD.format(tid)} [data-act=details]")
    caja.wait_for(state="detached")
    page.reload()
    page.wait_for_selector(CARD.format(tid))
    assert caja.count() == 0
    page.click(f"{CARD.format(tid)} [data-act=details]")
    caja.locator("strong").wait_for()
    assert page.locator(f"{CARD.format(tid)} .il-editor").count() == 0  # sin modo edición
    page.click(f"{CARD.format(tid)} [data-act=edit-details]")
    assert page.locator(f"{CARD.format(tid)} .il-editor textarea[name=details]").evaluate("el => el === document.activeElement")


def test_6_enlazar_tarea_y_nota_desde_los_dos_lados(page, server, api):
    tid = _nuevo(api, "Tarea enlazable")
    # desde la tarea: buscar la nota con autocompletado
    _tareas(page, server)
    page.click(f"{CARD.format(tid)} > .il-row [data-act=menu]")
    page.get_by_role("menuitem", name="Enlazar con una nota…").click()
    page.keyboard.type("plan e2e")
    page.wait_for_selector(".pick-row")
    page.keyboard.press("Enter")
    chip = page.locator(f"{CARD.format(tid)} .card-link", has_text="Plan E2E")
    chip.wait_for()
    assert f"[[tarea:{tid}]]" in api.get("/api/notes/plan-e2e").json()["content"]
    # un clic: a la nota, donde la ficha lleva de vuelta a la tarea
    chip.click()
    page.locator(f'#noteLinks .item-link[data-item-id="{tid}"]').click()
    page.wait_for_url("**/tareas?item=*")
    page.wait_for_selector(f"{CARD.format(tid)}.is-flash")
    # desde la nota: enlazar una idea
    iid = _nuevo(api, "Idea enlazable", type="idea")
    page.goto(server + "/?note=plan-e2e")
    page.wait_for_selector("#noteLinks .item-link")
    page.click('#noteLinks [aria-label="Enlazar otra tarea o idea"]')
    page.keyboard.type("idea enlazable")
    page.wait_for_selector(".pick-row")
    page.keyboard.press("Enter")
    page.wait_for_selector(f'#noteLinks .item-link[data-item-id="{iid}"]')
    assert any(l["note_id"] == "plan-e2e" for l in _items(api)[iid]["links"])
    # limpieza: quitar los enlaces deja la nota como estaba
    api.delete(f"/api/items/{tid}/links/plan-e2e")
    api.delete(f"/api/items/{iid}/links/plan-e2e")
    assert "[[" not in api.get("/api/notes/plan-e2e").json()["content"]


def test_10_marco_del_texto_del_tablero(page, server, api):
    bid = _board(api, {"nodes": [{"id": "t", "kind": "text", "x": 200, "y": 200, "w": 220, "h": 60, "text": "Texto con marco"}]})
    _open(page, server, bid, props=True)
    p = screen(page, 260, 230)
    page.mouse.click(p["x"], p["y"])
    page.wait_for_selector(".props-frames")
    page.click('.props-frames [data-value="ellipse"]')
    n = next(x for x in doc(page)["nodes"] if x["id"] == "t")
    assert n["frame"] == "ellipse" and n["stroke"] != "none" and n["text"] == "Texto con marco"
    assert page.locator('[data-id="t"] ellipse.shape').count() == 1
    page.click('.props-frames [data-value="diamond"]')
    assert page.locator('[data-id="t"] polygon.shape').count() == 1
    page.click('.props-frames [data-value="none"]')
    assert page.locator('[data-id="t"] rect.shape').count() == 1
    assert "frame" not in next(x for x in doc(page)["nodes"] if x["id"] == "t")


def _hoy(n=0):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=n)).isoformat()


def test_8_evento_en_nota_inbox_y_rutina_en_todos(page, server, api):
    api.post("/api/calendar/events", json={"title": "Evento E2E visible", "start": f"{_hoy(1)}T12:00"})
    rid = _nuevo(api, "Rutina E2E", type="rutina")
    # en una nota con un bloque ```calendario
    body = {"title": "Nota con agenda", "category": "E2E", "status": "consolidado", "tags": [], "encrypted": False,
            "content": "# Nota con agenda\n\n```calendario\nvista: agenda\n```\n"}
    api.post("/api/notes/nota-con-agenda", json=body)
    page.goto(server + "/?note=nota-con-agenda")
    page.locator(".cal-embed .cal-chip", has_text="Evento E2E visible").wait_for()
    # en el Inbox (agenda y grupo de próximos eventos)
    page.goto(server + "/inbox")
    page.locator('[data-group="calendario"] .il-evlink', has_text="Evento E2E visible").wait_for()
    page.locator("#paneTabAgenda").click()
    page.locator("#inboxAgenda .cal-chip", has_text="Evento E2E visible").wait_for()
    # completar la rutina desde el calendario → se ve hecha en Tareas y suma a la racha
    page.goto(server + f"/calendario?vista=day&dia={_hoy()}")
    page.locator(f'.cal-chip[data-key="r{rid}@{_hoy()}"] [data-cal-check]').click()
    page.wait_for_function(f"() => document.querySelector('.cal-chip[data-key=\"r{rid}@{_hoy()}\"]')?.classList.contains('is-done')")
    page.wait_for_timeout(400)
    it = _items(api)[rid]
    assert it["done"] and it["streak"]["actual"] == 1
    _tareas(page, server)
    assert page.locator(f'{CARD.format(rid)} > .il-row [data-act=done]').get_attribute("aria-checked") == "true"
    api.delete("/api/notes/nota-con-agenda")


def test_9_arrastrar_tarea_crea_bloque_y_moverlo_la_actualiza(page, server, api):
    tid = _nuevo(api, "Tarea para bloque E2E")
    page.goto(server + f"/calendario?vista=day&dia={_hoy(2)}")
    page.wait_for_selector(".cal-col")
    # el alto de una hora depende del horario visible: se mide con las etiquetas de 10:00 y 11:00
    top = page.evaluate("""t => parseFloat([...document.querySelectorAll('.cal-hour')].find((h) => h.textContent === t).style.top)""", "10:00")
    hour = page.evaluate("""t => parseFloat([...document.querySelectorAll('.cal-hour')].find((h) => h.textContent === t).style.top)""", "11:00") - top
    page.locator(".cal-scroll").evaluate("(el, y) => el.scrollTop = y - 20", top)
    col = page.locator(".cal-col").first.bounding_box()
    sc = page.locator(".cal-scroll").bounding_box()
    page.locator(f'[data-cal-drag-item="{tid}"]').drag_to(page.locator(".cal-col").first,
        target_position={"x": 30, "y": top + 4})  # 10:00 (posición dentro de la columna)
    page.wait_for_function(f"() => !!document.querySelector('.cal-ev[data-key=\"t{tid}\"]')")
    it = _items(api)[tid]
    assert (it["due_date"], it["due_time"], it["duration_min"]) == (_hoy(2), "10:00", 60)
    # mover el bloque una hora abajo actualiza la tarea
    ev = page.locator(f'.cal-ev[data-key="t{tid}"]')
    ev.scroll_into_view_if_needed()
    b = ev.bounding_box()
    page.mouse.move(b["x"] + 30, b["y"] + 10)
    page.mouse.down()
    page.mouse.move(b["x"] + 30, b["y"] + 10 + hour, steps=10)
    page.mouse.up()
    page.wait_for_timeout(800)
    assert _items(api)[tid]["due_time"] == "11:00"
    assert col and sc


def test_14_papelera_borra_y_restaura(page, server, api):
    eid = api.post("/api/calendar/events", json={"title": "Para la papelera E2E", "start": _hoy(3)}).json()["id"]
    api.delete(f"/api/calendar/events/{eid}")
    page.goto(server + "/papelera")
    row = page.locator(".trash-row", has_text="Para la papelera E2E")
    row.wait_for()
    row.locator("[data-restore]").click()
    page.wait_for_function("() => ![...document.querySelectorAll('.trash-row')].some(r => r.textContent.includes('Para la papelera E2E'))")
    titles = [e["title"] for e in api.get(f"/api/calendar/entries?start={_hoy(3)}&end={_hoy(3)}").json()["entries"]]
    assert "Para la papelera E2E" in titles


def test_10_ctrl_k_encuentra_una_nota(page, server, api):
    page.goto(server + "/hoy")
    page.wait_for_selector("#hoyAgenda .hoy-list, #hoyAgenda .hoy-empty")
    page.keyboard.press("Control+k")
    page.wait_for_selector("dialog.palette[open]")
    page.keyboard.type("plan e2")
    page.locator(".palette-row", has_text="Plan E2E").first.wait_for()
    assert page.locator(".palette-row[aria-selected=true]").inner_text().startswith("Plan E2E")
    page.keyboard.press("Enter")
    page.wait_for_url("**/?note=plan-e2e")
    # acciones con su atajo visible
    page.keyboard.press("Control+k")
    page.keyboard.type("calendario")
    row = page.locator(".palette-row", has_text="Ir a Calendario")
    row.wait_for()
    assert "G" in row.locator(".palette-keys").inner_text()


def test_14_hoy_muestra_datos_reales(page, server, api):
    hoy = _hoy()
    api.post("/api/calendar/events", json={"title": "Reunión de Hoy E2E", "start": f"{hoy}T23:30"})
    rid = _nuevo(api, "Rutina de Hoy E2E", type="rutina")
    page.goto(server + "/hoy")
    page.locator("#hoyAgenda .hoy-row", has_text="Reunión de Hoy E2E").wait_for()
    page.locator("#hoyRutinas .hoy-row", has_text="Rutina de Hoy E2E").locator("[data-check]").click()
    page.wait_for_timeout(600)
    assert _items(api)[rid]["done"]
    assert page.locator("#hoyComida").inner_text().strip()
    assert page.locator("#hoyRepaso").inner_text().strip()


def test_4_esp32_desconectado_se_para_con_reintentar(page, server):
    page.goto(server + "/estudio/")
    page.wait_for_function("() => document.querySelector('#connStatus .conn-label').textContent === 'Sin conexión'", timeout=60000)
    assert page.locator("#offlineNotice").is_visible() and page.locator("#btnRetry").is_visible()
    n = []
    page.on("request", lambda r: n.append(r.url) if "esp32" in r.url else None)
    page.wait_for_timeout(5000)
    assert not n  # parado: no sigue intentando solo
    page.click("#btnRetry")
    page.wait_for_timeout(500)
    assert any("esp32/retry" in u for u in n)


def test_7_plato_doble_desde_la_interfaz(page, server, api):
    def ing(nombre, k, p, c, g):
        return api.post("/comidas/api/ingredients", json={"nombre": nombre, "categoria": "General", "kcal_100g": k, "proteinas_100g": p,
                                                          "carbohidratos_100g": c, "grasas_100g": g}).json()["id"]
    a, b = ing("Lechuga E2E", 15, 1.4, 2.9, 0.2), ing("Pollo E2E", 165, 31, 0, 3.6)
    api.post("/comidas/api/meals", json={"nombre": "Ensalada E2E", "franja": "comida", "tags": "primero", "gramos_recomendados": 200,
                                         "ingredientes": [{"ingredient_id": a, "gramos": 200}]})
    api.post("/comidas/api/meals", json={"nombre": "Pollo plancha E2E", "franja": "comida", "tags": "segundo", "gramos_recomendados": 200,
                                         "ingredientes": [{"ingredient_id": b, "gramos": 200}]})
    page.goto(server + "/comidas/")
    page.wait_for_function("() => typeof planState !== 'undefined' && !!planState")
    page.evaluate("switchTab('plan')")
    page.locator("#dayPanel [data-act=doble][data-franja=comida]").click()
    page.locator("#dayPanel .dp-plato-name", has_text="Ensalada E2E").wait_for()
    st = page.evaluate("planState")
    dia = st["dias"][page.evaluate("selectedDia")]["comidas"]["comida"]
    roles = {p["nombre"]: p["rol"] for p in dia["platos"]}
    assert roles["Ensalada E2E"] == "primero" and roles["Pollo plancha E2E"] == "segundo"
    assert abs(dia["total"]["kcal"] - sum(p["macros"]["kcal"] for p in dia["platos"])) < 1.5
