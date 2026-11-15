"""P-3 · Formularios rápidos, solo con el teclado: lo mínimo en una línea, lo entendido debajo, Intro guarda,
Ctrl+Intro guarda y deja otro listo, Esc cancela y un campo se cambia en el sitio."""

from playwright.sync_api import expect

from tests.e2e.test_ronda6 import _items
from tests.e2e.test_rutinas_horas import _limpiar


def _rutina(api, title):
    return next(i for i in _items(api).values() if i["type"] == "rutina" and not i["parent_id"] and i["text"] == title)


def _pasos(api, rid):
    kids = [i for i in _items(api).values() if i["parent_id"] == rid]
    return sorted(((k["text"], k["due_time"], k["duration_min"]) for k in kids), key=lambda k: k[1] or "99")


def test_rutina_con_pasos_solo_con_teclado(page, server, api):
    _limpiar(api)
    page.goto(f"{server}/rutinas?dia=2026-11-16")  # un lunes
    page.wait_for_selector("#rtPage:not(:has(.skeleton))")
    page.keyboard.press("n")
    expect(page.locator("#rtqLine")).to_be_focused()
    page.keyboard.type("Gimnasio lxv 18h")
    expect(page.locator("#rtqPrev")).to_contain_text("Los lunes, miércoles, viernes")
    page.keyboard.press("Tab")
    expect(page.locator("#rtqSteps")).to_be_focused()
    for line in ("calentar 10m", "pesas 40m", "estiramientos 10m"):
        page.keyboard.type(line)
        page.keyboard.press("Enter")
    expect(page.locator("#rtqStepsPrev li")).to_have_count(3)
    expect(page.locator("#rtqStepsPrev li").nth(1)).to_contain_text("18:10–18:50")
    page.keyboard.press("Enter")  # Intro en la línea vacía: crea
    expect(page.locator("#rtQuick")).to_be_hidden()
    page.locator(".rp-card", has_text="Gimnasio").wait_for()
    r = _rutina(api, "Gimnasio")
    assert r["repeat"] == {"freq": "weekly", "days": [0, 2, 4]} and r["due_time"] == "18:00"
    assert _pasos(api, r["id"]) == [("Calentar", "18:00", 10), ("Pesas", "18:10", 40), ("Estiramientos", "18:50", 10)]


def test_ctrl_intro_crea_y_deja_otra_lista_y_esc_cierra(page, server, api):
    _limpiar(api)
    page.goto(f"{server}/rutinas?dia=2026-11-16")
    page.wait_for_selector("#rtPage:not(:has(.skeleton))")
    page.keyboard.press("n")
    page.keyboard.type("Leer L-V 22:30 30m")
    page.keyboard.press("Control+Enter")
    expect(page.locator("#rtqLine")).to_have_value("")
    expect(page.locator("#rtqLine")).to_be_focused()
    page.locator(".rp-card", has_text="Leer").wait_for()
    assert _rutina(api, "Leer")["duration_min"] == 30
    page.keyboard.type("Lo que no se crea")
    page.keyboard.press("Escape")
    expect(page.locator("#rtQuick")).to_be_hidden()
    assert not any(i["text"] == "Lo que no se crea" for i in _items(api).values())


def test_mas_opciones_se_recuerda_y_manda(page, server, api):
    _limpiar(api)
    page.goto(f"{server}/rutinas?dia=2026-11-21")  # un sábado
    page.wait_for_selector("#rtPage:not(:has(.skeleton))")
    page.keyboard.press("n")
    page.keyboard.type("Limpieza L 10:00")
    page.locator("#rtqMore summary").click()
    expect(page.locator("#rtqDays [data-day='1']")).not_to_be_checked()  # lo escrito («L») se refleja
    expect(page.locator("#rtqDays [data-day='0']")).to_be_checked()
    page.locator("#rtqDays label:has([data-day='0'])").click()
    page.locator("#rtqDays label:has([data-day='5'])").click()
    page.locator("#rtqLine").focus()
    page.keyboard.press("Enter")
    page.locator(".rp-card", has_text="Limpieza").wait_for()
    assert _rutina(api, "Limpieza")["repeat"] == {"freq": "weekly", "days": [5]}
    page.reload()
    page.wait_for_selector("#rtPage:not(:has(.skeleton))")
    page.keyboard.press("n")
    expect(page.locator("#rtqMore")).to_have_attribute("open", "")


def test_nombre_y_dias_en_el_sitio_y_pegar_bloques(page, server, api):
    _limpiar(api)
    rid = api.post("/api/routines/rapida", json={"text": "Tarde L 16:00", "pasos": "merendar 15m"}).json()["id"]
    page.goto(f"{server}/rutinas?dia=2026-11-16")
    card = page.locator(f"[data-rid='{rid}']")
    card.wait_for()
    card.locator("[data-act=rename]").focus()
    page.keyboard.press("Enter")
    page.keyboard.type("Tarde tranquila")
    page.keyboard.press("Enter")
    expect(card.locator(".rp-title")).to_have_text("Tarde tranquila")
    card.locator("[data-act=when]").click()
    page.keyboard.type("L X 17:00")
    page.keyboard.press("Enter")
    expect(card.locator(".rp-meta")).to_contain_text("Los lunes, miércoles")
    r = _items(api)[rid]
    assert r["text"] == "Tarde tranquila" and r["repeat"]["days"] == [0, 2] and r["due_time"] == "17:00"
    # el nombre de un bloque, también en el sitio
    step = card.locator(".rp-step", has_text="Merendar")
    step.locator(".rp-step-title").click()
    page.keyboard.type("Merienda")
    page.keyboard.press("Enter")
    expect(card.locator(".rp-step-title", has_text="Merienda")).to_be_visible()
    # pegar una lista en «Nuevo bloque» crea uno por línea
    add = page.locator(f"#rp-add-{rid}")
    add.focus()
    page.evaluate(
        """([sel, text]) => { const el = document.querySelector(sel); const dt = new DataTransfer(); dt.setData('text', text);
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }""",
        [f"#rp-add-{rid}", "- 17:00 piano 30m\n- leer 20m"],
    )
    card.locator(".rp-step", has_text="Leer").wait_for()
    assert ("Piano", "17:00", 30) in _pasos(api, rid)
    # y una línea con su hora escrita
    add.fill("18:00 cena 30m")
    page.keyboard.press("Enter")
    card.locator(".rp-step", has_text="Cena").wait_for()
    assert ("Cena", "18:00", 30) in _pasos(api, rid)


# ---------- Tareas y eventos ----------


def _item(api, text):
    return next(i for i in _items(api).values() if i["text"] == text)


def test_tarea_en_una_linea_con_vista_previa(page, server, api):
    page.goto(f"{server}/tareas")
    page.wait_for_selector(".il .il-group")
    page.locator("h1").click()
    page.keyboard.press("c")  # la captura rápida
    expect(page.locator("#captureForm-text")).to_be_focused()
    page.keyboard.type("Pedir cita médico viernes 10:00 30m !alta +Salud")
    prev = page.locator("#captureForm [data-capture-preview]")
    expect(prev).to_contain_text("10:00–10:30")
    expect(prev).to_contain_text("Prioridad alta")
    expect(prev).to_contain_text("Salud")
    page.keyboard.press("Enter")
    expect(page.locator("#captureModal")).not_to_have_attribute("open", "")
    it = _item(api, "Pedir cita médico")
    assert (it["due_time"], it["duration_min"], it["priority"], it["category"]) == ("10:00", 30, "alta", "Salud")


def test_ctrl_intro_deja_la_captura_abierta_y_no_es_una_fecha(page, server, api):
    page.goto(f"{server}/tareas")
    page.wait_for_selector(".il .il-group")
    page.locator("h1").click()
    page.keyboard.press("c")
    expect(page.locator("#captureForm-text")).to_be_focused()
    page.keyboard.type("Primera de dos")
    page.keyboard.press("Control+Enter")
    expect(page.locator("#captureForm-text")).to_have_value("")
    expect(page.locator("#captureModal")).to_have_attribute("open", "")
    # «Leer el capítulo 3 de mayo»: la fecha leída se puede descartar desde la vista previa
    page.keyboard.type("Leer el capítulo del 3 de mayo")
    lit = page.locator("#captureForm [data-capture-literal]")
    lit.wait_for()
    lit.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#captureForm [data-capture-preview]")).to_contain_text("Sin leer la fecha")
    page.locator("#captureForm-text").focus()
    page.keyboard.press("Enter")
    assert _item(api, "Primera de dos")
    it = _item(api, "Leer el capítulo del 3 de mayo")
    assert it["due_date"] is None


def test_mas_opciones_de_la_tarea_con_el_teclado(page, server, api):
    page.goto(f"{server}/tareas")
    page.wait_for_selector(".il .il-group")
    page.locator("#tareasCapture-text").focus()
    page.keyboard.type("Preparar la mochila")
    more = page.locator("#tareasCapture [data-capture-more]")
    if not more.evaluate("d => d.open"):
        more.locator("summary").focus()
        page.keyboard.press("Enter")
    page.locator("#tareasCapture [data-opt-day]").first.focus()  # «Hoy»
    page.keyboard.press("Space")
    page.locator("#tareasCapture [data-opt-prio='media']").focus()
    page.keyboard.press("Space")
    page.locator("#tareasCapture [data-opt-time]").focus()
    page.keyboard.type("1830")
    expect(page.locator("#tareasCapture [data-capture-preview]")).to_contain_text("18:30")
    page.keyboard.press("Enter")
    page.locator(".il-item", has_text="Preparar la mochila").first.wait_for()
    it = _item(api, "Preparar la mochila")
    assert it["due_time"] == "18:30" and it["priority"] == "media" and it["due_date"]
    page.reload()
    page.wait_for_selector(".il .il-group")
    expect(page.locator("#tareasCapture [data-capture-more]")).to_have_attribute("open", "")  # recordado


def test_fecha_y_prioridad_en_el_sitio(page, server, api):
    tid = api.post(
        "/api/items", json={"text": "Revisar la caldera", "due_date": "2026-12-01", "due_time": "10:00"}
    ).json()["id"]
    api.patch(f"/api/items/{tid}", json={"priority": "baja"})
    page.goto(f"{server}/tareas?item={tid}")
    card = page.locator(f".il-item[data-id='{tid}']").first
    card.wait_for()
    card.locator("[data-act=edit-when]").focus()
    page.keyboard.press("Enter")
    expect(page.locator(".qf-inline")).to_be_focused()
    page.keyboard.type("11")  # solo la hora
    page.keyboard.press("Enter")
    expect(card.locator(".il-due")).to_contain_text("11:00")
    assert _items(api)[tid]["due_date"] == "2026-12-01"
    card.locator("[data-act=edit-when]").focus()
    page.keyboard.press("Enter")
    page.keyboard.type("3/12 9:00 45m")
    page.keyboard.press("Enter")
    expect(card.locator(".il-due")).to_contain_text("9:00")
    it = _items(api)[tid]
    assert (it["due_date"], it["due_time"], it["duration_min"]) == ("2026-12-03", "09:00", 45)
    card.locator("[data-act=prio]").focus()
    page.keyboard.press("Enter")
    page.get_by_role("menuitemradio", name="Prioridad alta").click()
    expect(card.locator("[data-act=prio]")).to_contain_text("alta")
    assert _items(api)[tid]["priority"] == "alta"


def test_evento_mas_opciones_sin_crear_antes(page, server, api):
    page.goto(f"{server}/calendario?dia=2026-11-20")
    page.wait_for_load_state("networkidle")
    page.locator("#calQuickText").focus()
    expect(page.locator("#calQuickText")).to_be_focused()
    page.keyboard.type("Fisio 20/11 12:00 45m")
    expect(page.locator("#calQuickHint")).to_contain_text("12:00–12:45")
    page.keyboard.press("Alt+Enter")
    expect(page.locator("#calEdLoc")).to_be_focused()
    page.keyboard.type("Centro Norte")
    page.keyboard.press("Control+Enter")
    page.wait_for_selector("dialog[open]", state="detached")
    # y el lugar en la propia línea: el foco ha vuelto a la línea rápida y lo escrito entra
    expect(page.locator("#calQuickText")).to_be_focused()
    page.keyboard.type("Revisión 20/11 17:00 30m en Clínica Sur")
    expect(page.locator("#calQuickHint")).to_contain_text("Clínica Sur")
    page.keyboard.press("Enter")
    page.keyboard.type("algo que no quiero")
    page.keyboard.press("Escape")
    expect(page.locator("#calQuickText")).to_have_value("")
    evs = api.get("/api/calendar/entries", params={"start": "2026-11-20", "end": "2026-11-21"}).json()["entries"]
    got = {(e["title"], e["start"], e["end"], e.get("location")) for e in evs if e["kind"] == "event"}
    assert ("Fisio", "2026-11-20T12:00", "2026-11-20T12:45", "Centro Norte") in got
    assert ("Revisión", "2026-11-20T17:00", "2026-11-20T17:30", "Clínica Sur") in got


# ---------- Comidas ----------


def _comidas(page, server, tab):
    page.goto(f"{server}/comidas/")
    page.wait_for_load_state("networkidle")
    page.locator(f"[role=tab][data-tab={tab}]").first.click()


def test_ingrediente_y_plato_rapidos_con_el_teclado(page, server, api):
    _comidas(page, server, "ingredientes")
    page.locator("#qiOpen").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#qiLine")).to_be_focused()
    page.keyboard.type("Garbanzo e2e 364 19,3 61 6")
    expect(page.locator("#qiPrev")).to_contain_text("Legumbre")
    page.keyboard.press("Enter")
    page.locator(".toast", has_text="Garbanzo e2e").wait_for()
    ing = next(i for i in api.get("/comidas/api/ingredients").json()["ingredients"] if i["nombre"] == "Garbanzo e2e")
    assert (ing["categoria"], ing["kcal_100g"], ing["proteinas_100g"]) == ("legumbre", 364, 19.3)
    # un valor de la tabla, en el sitio
    page.locator("#ingSearch").fill("Garbanzo e2e")
    cell = page.locator(f"[data-ing-cell=grasas_100g][data-ing='{ing['id']}']")
    cell.focus()
    page.keyboard.press("Enter")
    page.keyboard.type("6,5")
    page.keyboard.press("Enter")
    expect(page.locator(f"[data-ing-cell=grasas_100g][data-ing='{ing['id']}']")).to_have_text("6,5")

    _comidas(page, server, "platos")
    page.locator("#qmOpen").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#qmLine")).to_be_focused()
    page.keyboard.type("Hummus e2e merienda 10 min")
    page.keyboard.press("Tab")
    page.keyboard.type("200 g garbanzo e2e")
    page.keyboard.press("Enter")
    page.keyboard.type("50 dientes de dragón")
    expect(page.locator("#qmIngsPrev li.is-warn")).to_have_count(1)  # lo que no existe se avisa
    page.keyboard.press("Shift+Home")
    page.keyboard.press("Backspace")
    page.keyboard.press("Backspace")
    expect(page.locator("#qmIngsPrev li")).to_have_count(1)
    page.keyboard.press("Tab")
    page.keyboard.type("Triturar todo")
    page.keyboard.press("Control+Enter")  # crea y deja otro listo
    page.locator(".toast", has_text="Hummus e2e").wait_for()
    expect(page.locator("#qmLine")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#qmPanel")).to_be_hidden()
    meals = api.get("/comidas/api/meals").json()
    m = next(x for x in meals.get("meals", meals) if x["nombre"] == "Hummus e2e")
    d = api.get(f"/comidas/api/meals/{m['id']}").json()
    assert d["franja"] == "merienda" and [i["gramos"] for i in d["ingredientes"]] == [200]
