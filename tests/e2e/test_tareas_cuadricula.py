"""Tareas: el botón que pasa de la lista a una cuadrícula con las tareas en filas y sus pasos a la vista."""
import pytest

@pytest.fixture()
def celdas(api):
    ids = [api.post("/api/items", json={"text": f"Celda {n}", "type": "tarea"}).json()["id"] for n in "ABCD"]
    api.post("/api/items", json={"text": "Paso de A", "type": "tarea", "parent_id": ids[0]})
    yield ids
    for i in ids:
        api.delete(f"/api/items/{i}")


def card(page, text):
    return page.locator(".il-list > .il-item", has=page.locator(":scope > .il-row .il-text", has_text=text))


def test_cambia_de_vista_y_se_recuerda(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    card(page, "Celda A").wait_for()
    assert page.get_attribute("[data-view=lista]", "aria-pressed") == "true"
    a, b = card(page, "Celda A").bounding_box(), card(page, "Celda B").bounding_box()
    assert a["x"] == b["x"]  # en lista, una debajo de otra

    page.click("[data-view=matriz]")
    d, c = card(page, "Celda D").bounding_box(), card(page, "Celda C").bounding_box()  # las nuevas van primero
    assert c["x"] > d["x"] + d["width"] - 1 and c["y"] == d["y"]  # en la cuadrícula, una al lado de la otra
    assert page.locator(".il-child", has_text="Paso de A").is_visible()  # con sus pasos a la vista
    assert page.get_attribute("[data-view=matriz]", "aria-pressed") == "true"

    page.reload()
    card(page, "Celda A").wait_for()
    assert page.locator(".tareas.is-matrix").count() == 1
    page.click("[data-view=lista]")
    assert page.locator(".tareas.is-matrix").count() == 0


def test_en_la_cuadricula_todo_sigue_funcionando(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    card(page, "Celda A").wait_for()
    # se edita dentro de la tarjeta: ni cambia de sitio ni de ancho, y el formulario cabe en ella
    target = page.locator(f'.il-item[data-id="{celdas[1]}"]')
    before = target.bounding_box()
    target.locator("[data-act=edit-text]").first.dblclick()
    editor = page.locator(".il-editor")
    editor.wait_for()
    after = target.bounding_box()
    assert (after["x"], after["y"], after["width"]) == (before["x"], before["y"], before["width"])
    box = editor.bounding_box()
    assert box["x"] >= after["x"] and box["x"] + box["width"] <= after["x"] + after["width"]
    assert card(page, "Celda D").bounding_box()["width"] == pytest.approx(after["width"], abs=0.5)
    page.keyboard.press("Escape")
    # marcar como hecha
    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method != "GET"):
        card(page, "Celda C").locator(":scope > .il-row .card-check").click()
    assert {i["id"]: i for i in api.get("/api/items").json()["items"]}[celdas[2]]["done"] is True
    # las flechas pasan a la tarjeta de al lado (la C ya está hecha y no se ve)
    card(page, "Celda D").focus()
    page.keyboard.press("ArrowRight")
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Celda B"


def test_arrastrar_entre_columnas(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    card(page, "Celda D").wait_for()
    order = lambda: [t for t in page.locator(".il-list > .il-item > .il-row .il-text").all_inner_texts() if t.startswith("Celda")]
    before = order()
    with page.expect_response(lambda r: "/move" in r.url):
        src = card(page, before[-1]).locator(":scope > .il-row [data-drag-handle]").bounding_box()
        dst = card(page, before[0]).bounding_box()
        page.mouse.move(src["x"] + src["width"] / 2, src["y"] + src["height"] / 2)
        page.mouse.down()
        page.mouse.move(src["x"] + 12, src["y"] + 12, steps=3)
        page.mouse.move(dst["x"] + 6, dst["y"] + 3, steps=14)
        page.wait_for_timeout(120)
        page.mouse.up()
    page.wait_for_function("(t) => document.querySelector('.il-list > .il-item .il-text').textContent === t", arg=before[-1])
    assert order()[0] == before[-1]


def test_en_el_movil_sigue_la_lista(page, server, api, celdas):
    page.set_viewport_size({"width": 390, "height": 844})
    api.put("/api/prefs/tareas-view", json={"value": "matriz"})
    page.goto(f"{server}/tareas")
    card(page, "Celda A").wait_for()
    assert page.locator(".view-seg").is_hidden()
    a, b = card(page, "Celda A").bounding_box(), card(page, "Celda B").bounding_box()
    assert a["x"] == b["x"]


def matrix(page):
    return page.locator(".tareas.is-matrix").count() == 1


def test_la_tecla_r_cambia_de_vista(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    card(page, "Celda A").wait_for()
    page.keyboard.press("r")
    assert matrix(page) and page.get_attribute("[data-view=matriz]", "aria-pressed") == "true"
    page.keyboard.press("Shift+R")  # con mayúsculas activadas también
    assert not matrix(page) and page.get_attribute("[data-view=lista]", "aria-pressed") == "true"
    card(page, "Celda D").focus()  # con el foco en una tarjeta también, y no lo pierde
    page.keyboard.press("r")
    assert matrix(page) and page.evaluate("document.activeElement.getAttribute('aria-label')").startswith("Celda D")
    page.reload()  # se recuerda igual que con el botón
    card(page, "Celda A").wait_for()
    assert matrix(page)


def test_la_tecla_r_no_molesta(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    card(page, "Celda A").wait_for()
    # escribiendo
    page.click("#taskSearch")
    page.keyboard.type("rr")
    assert not matrix(page) and page.input_value("#taskSearch") == "rr"
    page.fill("#taskSearch", "")
    # en el editor de una tarjeta
    card(page, "Celda B").locator("[data-act=edit-text]").first.dblclick()
    page.locator(".il-editor textarea").first.wait_for()
    page.keyboard.type("r")
    assert not matrix(page)
    page.keyboard.press("Escape")
    # con un diálogo abierto
    page.locator("body").click(position={"x": 700, "y": 880})
    page.keyboard.press("?")
    page.locator(".keys-help", has_text="Cambiar entre lista y cuadrícula").wait_for()
    page.keyboard.press("r")
    assert not matrix(page)
    page.keyboard.press("Escape")
    page.locator(".keys-help").wait_for(state="detached")
    # G + R sigue llevando a Revisión
    page.keyboard.press("g")
    page.keyboard.press("r")
    page.wait_for_url("**/revision")
    assert api.get("/api/prefs").json()["prefs"].get("tareas-view") != "matriz"  # y de paso no ha cambiado la vista


def test_marcar_un_paso_no_mueve_el_scroll_de_la_tarjeta(page, server, api, celdas):
    for n in range(10):
        api.post("/api/items", json={"text": f"Paso largo {n}", "type": "tarea", "parent_id": celdas[1]})
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    steps = card(page, "Celda B").locator(".il-children")
    steps.wait_for()
    top = steps.evaluate("el => (el.scrollTop = el.scrollHeight, el.scrollTop)")
    assert top > 0  # hay de verdad desplazamiento dentro de la tarjeta

    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method != "GET"):
        page.locator(".il-child", has_text="Paso largo 9").locator(".card-check").click()
    page.locator(".il-child.is-done", has_text="Paso largo 9").wait_for()
    page.wait_for_timeout(250)  # por si llega un segundo repintado
    assert card(page, "Celda B").locator(".il-children").evaluate("el => el.scrollTop") == top

    # tampoco al repintar por otro motivo (una tarea nueva), y sí vale seguir desplazando
    page.locator("#tareasCapture [data-capture-text]").fill("Otra tarea")
    page.keyboard.press("Enter")
    card(page, "Otra tarea").wait_for()
    assert card(page, "Celda B").locator(".il-children").evaluate("el => el.scrollTop") == top
    api.delete(f"/api/items/{next(i['id'] for i in api.get('/api/items').json()['items'] if i['text'] == 'Otra tarea')}")


@pytest.mark.parametrize("width", [1280, 1000])
def test_el_editor_cabe_en_la_tarjeta_mas_estrecha(page, server, api, celdas, width):
    """Tarea, paso y rutina: nada se sale ni queda recortado, tampoco con la columna más estrecha."""
    rutina = api.post("/api/items", json={"text": "Rutina de prueba", "type": "rutina", "repeat": {"freq": "daily"}}).json()["id"]
    paso = next(i["id"] for i in api.get("/api/items").json()["items"] if i["text"] == "Paso de A")
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    fits = """(form) => {
        const box = form.closest('.il-item:not(.il-child)').getBoundingClientRect();
        return [...form.querySelectorAll('input:not([type=checkbox]), select, textarea, button, .day-option')].filter((el) => el.offsetParent)
          .every((el) => { const r = el.getBoundingClientRect(); return r.left >= box.left - 1 && r.right <= box.right + 1; });
    }"""
    for item, text in ((celdas[2], "Celda C"), (paso, "Paso de A"), (rutina, "Rutina de prueba")):
        page.locator(f'.il-item[data-id="{item}"] > .il-row [data-act=edit-text]').dblclick()
        form = page.locator(f'.il-editor[data-edit="{item}"]')
        form.wait_for()
        assert form.evaluate(fits), text
        save = form.locator("[type=submit]")
        save.scroll_into_view_if_needed()
        assert save.is_visible() and form.evaluate("(f) => !f.closest('.il-children') || getComputedStyle(f.closest('.il-children')).overflowY === 'visible'")
        page.keyboard.press("Escape")
        form.wait_for(state="detached")
    api.delete(f"/api/items/{rutina}")


def stretch(page, item, handle, dx=0, dy=0):
    """Arrastra un agarre de la tarjeta `item` (e, s o se)."""
    li = page.locator(f'.il-item[data-id="{item}"]')
    li.hover()
    box = li.locator(f':scope > [data-resize="{handle}"]').bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=8)
    return li


def test_redimensionar_como_una_ventana(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    d, c = (page.locator(f'.il-item[data-id="{i}"]') for i in (celdas[3], celdas[2]))
    c.wait_for()
    before, c_before = d.bounding_box(), c.bounding_box()
    tracks = int(page.evaluate("getComputedStyle(document.querySelector('.il-list')).getPropertyValue('--tracks')"))

    # ancho: crece con el ratón y la de al lado se aparta
    stretch(page, celdas[3], "e", dx=170)
    page.mouse.up()
    wider = d.bounding_box()
    assert wider["width"] == pytest.approx(before["width"] + 170, abs=40) and wider["height"] == pytest.approx(before["height"], abs=2)
    assert c.bounding_box()["x"] >= wider["x"] + wider["width"] - 1

    # alto: crece con el ratón y el contenido de las otras no se estira
    stretch(page, celdas[3], "s", dy=200)
    page.mouse.up()
    assert d.bounding_box()["height"] == pytest.approx(before["height"] + 200, abs=8)
    assert c.bounding_box()["height"] == pytest.approx(c_before["height"], abs=2)

    # esquina: las dos cosas a la vez
    shape = d.bounding_box()
    stretch(page, celdas[3], "se", dx=-80, dy=-60)
    page.mouse.up()
    box = d.bounding_box()
    assert box["width"] < shape["width"] - 30 and box["height"] == pytest.approx(shape["height"] - 60, abs=8)

    # se recuerda y nunca pasa del ancho de la lista
    page.wait_for_timeout(600)
    page.reload()
    d.wait_for()
    assert d.bounding_box()["width"] == pytest.approx(box["width"], abs=2)
    stretch(page, celdas[3], "e", dx=3000)
    page.mouse.up()
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    assert int(d.evaluate("el => el.style.getPropertyValue('--card-w')")) == tracks


def test_las_demas_ocupan_el_hueco_de_una_alta(page, server, api, celdas):
    extras = [api.post("/api/items", json={"text": f"Extra {n}", "type": "tarea"}).json()["id"] for n in range(4)]
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    first = page.locator(f'.il-item[data-id="{extras[3]}"]')
    first.wait_for()
    stretch(page, extras[3], "s", dy=260)
    page.mouse.up()
    box = first.bounding_box()
    cards = page.evaluate("[...document.querySelector('.il-list').children].map((el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })")
    # hay tarjetas en filas que empiezan a la altura de la alta, y ninguna se pisa
    assert any(c[1] > box["y"] + 40 and c[1] < box["y"] + box["height"] and c[0] >= box["x"] + box["width"] - 1 for c in cards)
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            assert a[2] <= b[0] + 1 or b[2] <= a[0] + 1 or a[3] <= b[1] + 1 or b[3] <= a[1] + 1
    for i in extras:
        api.delete(f"/api/items/{i}")


def test_tamano_normal_escape_y_teclado(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    d = page.locator(f'.il-item[data-id="{celdas[3]}"]')
    d.wait_for()
    before = d.bounding_box()
    # Esc cancela lo que se estaba arrastrando
    stretch(page, celdas[3], "e", dx=200)
    page.keyboard.press("Escape")
    page.mouse.up()
    assert d.bounding_box()["width"] == pytest.approx(before["width"], abs=1)
    # Mayús + flechas
    d.focus()
    page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    box = d.bounding_box()
    assert box["width"] > before["width"] + 10 and box["height"] == pytest.approx(before["height"] + 24, abs=2)
    assert page.evaluate("document.activeElement.dataset.id") == str(celdas[3])
    # y desde el menú vuelve a la normalidad
    d.hover()
    d.locator(":scope > .il-row [data-act=menu]").click()
    page.get_by_role("menuitem", name="Tamaño normal").click()
    box = d.bounding_box()
    assert box["width"] == pytest.approx(before["width"], abs=1) and box["height"] == pytest.approx(before["height"], abs=1)
    # doble clic en un borde, lo mismo
    stretch(page, celdas[3], "e", dx=120)
    page.mouse.up()
    d.hover()
    d.locator(':scope > [data-resize="e"]').dblclick()
    assert d.bounding_box()["width"] == pytest.approx(before["width"], abs=1)


def test_con_poco_alto_los_pasos_se_desplazan_y_lista_no_cambia(page, server, api, celdas):
    for n in range(8):
        api.post("/api/items", json={"text": f"Paso {n}", "type": "tarea", "parent_id": celdas[3]})
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    d = page.locator(f'.il-item[data-id="{celdas[3]}"]')
    d.wait_for()
    stretch(page, celdas[3], "se", dx=120, dy=-90)
    page.mouse.up()
    steps = d.locator(":scope > .il-children")
    top = steps.evaluate("el => (el.scrollTop = el.scrollHeight, el.scrollTop)")
    assert top > 0
    # marcar un paso no pierde el sitio, tampoco con tamaño propio
    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method != "GET"):
        page.locator(".il-child", has_text="Paso 7").locator(".card-check").click()
    page.wait_for_timeout(250)
    assert steps.evaluate("el => el.scrollTop") == top
    # editar deja sitio al formulario y al cancelar vuelve el tamaño propio
    sized = d.bounding_box()
    d.locator(":scope > .il-row [data-act=edit-text]").first.dblclick()
    page.locator(".il-editor").wait_for()
    assert d.bounding_box()["height"] > sized["height"]
    page.keyboard.press("Escape")
    assert d.bounding_box()["height"] == pytest.approx(sized["height"], abs=2)
    # en la lista, el tamaño no se aplica
    page.click("[data-view=lista]")
    assert page.locator(".il-resize").first.is_hidden()
    assert d.bounding_box()["width"] > sized["width"] and d.bounding_box()["height"] > sized["height"]


@pytest.fixture()
def muchas(api):
    """Tarjetas de alturas distintas: es lo que hacía que recolocarlas entrase en bucle."""
    ids = []
    for n in range(24):
        i = api.post("/api/items", json={"text": f"Mezcla {n:02d}" + (" con un texto largo que ocupa varias líneas en la tarjeta" * (n % 3)), "type": "tarea"}).json()["id"]
        for k in range(n % 4):
            api.post("/api/items", json={"text": f"Paso {k} de {n}", "type": "tarea", "parent_id": i})
        ids.append(i)
    yield ids
    for i in ids:
        api.delete(f"/api/items/{i}")


def _matriz(page, server):
    page.goto(f"{server}/tareas")
    card(page, "Mezcla 00").wait_for()
    page.click("[data-view=matriz]")
    page.wait_for_timeout(200)


def _visibles(page, n=9):
    return page.locator(".il-list > .il-item").evaluate_all(
        "(l, n) => l.map((e) => { const r = e.getBoundingClientRect(); return { id: Number(e.dataset.id), x: r.x, y: r.y, w: r.width, h: r.height }; })"
        ".filter((r) => r.y > 0 && r.y + r.h < 640).slice(0, n)", n)


def _agarrar(page, c):
    page.mouse.move(c["x"] + c["w"] / 2, c["y"] + 12)
    page.mouse.down()
    page.mouse.move(c["x"] + c["w"] / 2 + 8, c["y"] + 20, steps=3)
    # cuenta cada vez que el hueco cambia de sitio
    page.evaluate("""() => {
        window.__huecos = 0;
        new MutationObserver((l) => l.forEach((m) => m.addedNodes.forEach((n) => { if (n.classList?.contains('sortable-placeholder')) window.__huecos++; })))
          .observe(document.getElementById('itemList'), { childList: true, subtree: true });
    }""")


def test_marcar_una_tarea_no_devuelve_arriba(page, server, api, muchas):
    _matriz(page, server)
    page.evaluate("document.querySelector('.page-body').scrollTop = 500")
    objetivo = page.locator(".il-list > .il-item > .il-row .card-check").evaluate_all(
        "(l) => { const b = l.find((x) => { const r = x.getBoundingClientRect(); return r.top > 150 && r.bottom < 800; }); b.id = 'el-check'; return b.getAttribute('aria-label'); }")
    assert objetivo
    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method != "GET"):
        page.click("#el-check")
    page.wait_for_timeout(400)
    assert page.evaluate("document.querySelector('.page-body').scrollTop") == 500


def test_el_hueco_no_tiembla_con_el_puntero_casi_quieto(page, server, api, muchas):
    _matriz(page, server)
    cartas = _visibles(page)
    _agarrar(page, cartas[0])
    for c in cartas[1:]:
        for fx, fy in ((0.15, 0.2), (0.85, 0.8), (0.5, 0.9)):
            x, y = c["x"] + c["w"] * fx, c["y"] + c["h"] * fy
            page.mouse.move(x, y, steps=3)
            page.wait_for_timeout(180)
            page.evaluate("window.__huecos = 0")
            for i in range(14):
                page.mouse.move(x + i % 2, y + i % 3)
                page.wait_for_timeout(16)
            assert page.evaluate("window.__huecos") == 0
    page.keyboard.press("Escape")
    page.mouse.up()


def test_cruzar_la_rejilla_no_revuelve_las_tarjetas(page, server, api, muchas):
    _matriz(page, server)
    cartas = _visibles(page)
    _agarrar(page, cartas[0])
    orden = lambda: page.locator(".il-list > .il-item, .il-list > .sortable-placeholder").evaluate_all("(l) => l.map((e) => e.dataset.id || 'hueco')")  # noqa: E731
    antes = orden()
    page.mouse.move(cartas[-1]["x"] + 8, cartas[-1]["y"] + 8, steps=6)
    assert orden() == antes  # de camino no se mueve nada; al parar, sí
    page.locator(".il-list .sortable-placeholder").first.wait_for()
    page.wait_for_function("(a) => [...document.querySelectorAll('.il-list > .il-item, .il-list > .sortable-placeholder')].map((e) => e.dataset.id || 'hueco').join() !== a", arg=",".join(antes))
    page.keyboard.press("Escape")
    page.mouse.up()


def test_soltar_nada_mas_parar_cae_donde_apunta(page, server, api, muchas):
    _matriz(page, server)
    cartas = _visibles(page, 3)
    assert len(cartas) == 3
    primero, destino = cartas[0], cartas[2]
    _agarrar(page, primero)
    with page.expect_response(lambda r: "/move" in r.url):
        page.mouse.move(destino["x"] + 6, destino["y"] + 6, steps=4)
        page.mouse.up()  # sin esperar a que llegue el hueco
    ids = page.locator(".il-list > .il-item").evaluate_all("(l) => l.map((e) => Number(e.dataset.id))")
    assert ids.index(primero["id"]) == ids.index(destino["id"]) + 1  # ocupa la celda a la que apuntaba


def test_la_pastilla_mete_como_paso_sin_recolocar(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    card(page, "Celda D").wait_for()
    a = card(page, "Celda A").bounding_box()
    d = card(page, "Celda D").bounding_box()
    _agarrar(page, {"x": d["x"], "y": d["y"], "w": d["width"]})
    assert page.locator(".il-item.sortable-can-nest").count() >= 3  # todas enseñan su pastilla
    page.mouse.move(a["x"] + a["width"] - 40, a["y"] + a["height"] - 14, steps=5)
    page.locator(".sortable-nest").wait_for()
    page.wait_for_timeout(200)
    assert page.evaluate("window.__huecos") == 0  # el hueco no entra en la tarjeta: la agrandaría y movería todas
    assert page.locator(".il-children .sortable-placeholder").count() == 0
    with page.expect_response(lambda r: "/move" in r.url):
        page.mouse.up()
    page.wait_for_function("(id) => !!document.querySelector(`.il-children [data-id=\"${id}\"]`)", arg=celdas[3])
    assert next(i for i in api.get("/api/items").json()["items"] if i["id"] == celdas[3])["parent_id"] == celdas[0]
    api.post(f"/api/items/{celdas[3]}/move", json={"target": "inbox"})


def test_una_subtarea_entra_en_cualquier_parte_de_otra_tarjeta(page, server, api, celdas):
    paso = next(i["id"] for i in api.get("/api/items").json()["items"] if i["text"] == "Paso de A")
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    card(page, "Celda D").wait_for()
    grip = page.locator(f'.il-item[data-id="{paso}"] [data-drag-handle]')
    page.locator(f'.il-item[data-id="{paso}"]').hover()
    g = grip.bounding_box()
    c = card(page, "Celda C").bounding_box()
    page.mouse.move(g["x"] + g["width"] / 2, g["y"] + g["height"] / 2)
    page.mouse.down()
    page.mouse.move(g["x"] + 14, g["y"] + 16, steps=3)
    page.mouse.move(c["x"] + 40, c["y"] + 10, steps=6)  # arriba del todo: sin apuntar a la pastilla
    page.locator(".il-list > .il-item.sortable-nest").wait_for()
    with page.expect_response(lambda r: "/move" in r.url):
        page.mouse.up()
    page.wait_for_function("(id) => !!document.querySelector(`.il-children [data-id=\"${id}\"]`)", arg=paso)
    assert next(i for i in api.get("/api/items").json()["items"] if i["id"] == paso)["parent_id"] == celdas[2]
    api.post(f"/api/items/{paso}/move", json={"parent_id": celdas[0]})


def test_se_arrastra_el_bloque_entero_aunque_este_plegado(page, server, api, celdas):
    for n in range(8):
        api.post("/api/items", json={"text": f"Otro paso {n}", "type": "tarea", "parent_id": celdas[0]})
    page.goto(f"{server}/tareas")
    a = card(page, "Celda A")
    a.locator(":scope > .il-row .il-kids-fold").click()  # plegada
    assert page.locator(".il-child", has_text="Paso de A").count() == 0
    box = a.locator(":scope > .il-row").bounding_box()
    page.mouse.move(box["x"] + 120, box["y"] + 12)
    page.mouse.down()
    page.mouse.move(box["x"] + 140, box["y"] + 40, steps=4)
    ghost = page.locator(".sortable-ghost")
    assert ghost.locator(".il-child").count() == 6 and "y 3 más" in ghost.inner_text()
    assert ghost.evaluate("(g) => getComputedStyle(g).backgroundColor") not in ("rgba(0, 0, 0, 0)", "transparent")
    assert ghost.bounding_box()["height"] > 180  # no se queda con el alto de la tarjeta plegada
    page.keyboard.press("Escape")
    page.mouse.up()
    a.locator(":scope > .il-row .il-kids-fold").click()


def test_una_tarjeta_con_pasos_no_se_mete_en_otra_y_se_recoloca(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    page.click("[data-view=matriz]")
    card(page, "Celda D").wait_for()
    a = card(page, "Celda A").bounding_box()  # tiene un paso: no puede ser paso de otra
    c = card(page, "Celda C").locator(":scope > .il-row").bounding_box()
    _agarrar(page, {"x": a["x"], "y": a["y"], "w": a["width"]})
    page.mouse.move(c["x"] + c["width"] / 2, c["y"] + c["height"] / 2, steps=5)
    page.wait_for_timeout(250)
    assert page.locator(".sortable-nest, .sortable-invalid").count() == 0
    assert page.evaluate("window.__huecos") == 1  # ni se quita el hueco ni va y viene: una vez, al sitio
    page.keyboard.press("Escape")
    page.mouse.up()


def test_copiar_desde_al_lado_del_check(page, server, api, celdas):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server)
    page.goto(f"{server}/tareas")
    card(page, "Celda A").wait_for()
    a = card(page, "Celda A")
    a.locator(":scope > .il-row").hover()
    a.locator(":scope > .il-row [data-act=copy]").click()
    page.locator(".toast", has_text="Copiado").wait_for()
    assert page.evaluate("navigator.clipboard.readText()") == "Celda A"
    # el de un paso copia el paso, y sin tocar la tarjeta
    paso = page.locator(".il-child", has_text="Paso de A")
    paso.hover()
    paso.locator("[data-act=copy]").click()
    page.wait_for_timeout(100)
    assert page.evaluate("navigator.clipboard.readText()") == "Paso de A"
    assert not a.locator(".il-editor").count() and not a.evaluate("e => e.classList.contains('is-done')")


def test_el_editor_es_compacto_y_guarda_todo(page, server, api, celdas):
    page.goto(f"{server}/tareas")
    item = celdas[2]
    page.locator(f'.il-item[data-id="{item}"] > .il-row [data-act=edit-text]').dblclick()
    form = page.locator(f'.il-editor[data-edit="{item}"]')
    form.wait_for()
    assert form.bounding_box()["height"] < 190  # antes, 280 largos
    tops = form.locator(".il-ed").evaluate_all("(l) => new Set(l.map((e) => Math.round(e.getBoundingClientRect().top))).size")
    assert tops <= 2
    form.locator("[name=category]").fill("Compacta")
    form.locator("[name=priority]").select_option(index=1)
    form.locator("[name=due_date]").fill("2030-05-06")
    form.locator("[name=due_time]").fill("10:30")
    form.locator("[name=duration_min]").fill("45")
    form.locator("[name=details]").fill("Una nota")
    with page.expect_response(lambda r: f"/api/items/{item}" in r.url and r.request.method == "PATCH"):
        form.locator("[type=submit]").click()
    it = next(i for i in api.get("/api/items").json()["items"] if i["id"] == item)
    assert (it["category"], it["due_date"], it["due_time"], it["duration_min"], it["details"]) == ("Compacta", "2030-05-06", "10:30", 45, "Una nota")
    assert it["priority"]
