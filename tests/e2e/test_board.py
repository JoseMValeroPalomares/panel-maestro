"""Ronda 2 · fase 3: tablero SVG — encuadre, zoom, flechas ancladas, texto en caja, colores, productividad."""
import json

import pytest

from tests.e2e.helpers import touch_drag  # noqa: F401  (táctil: ver test_tactil_pan_y_mover)


def _board(api, doc):
    bid = api.post("/api/boards", json={"name": "E2E tablero"}).json()["id"]
    assert api.post(f"/api/boards/{bid}/canvas", json={"data": json.dumps({"format": 2, "edges": [], "strokes": [], **doc})}).status_code == 200
    return bid


def _open(page, server, bid, zoom=1, props=False):
    """Abre el Inbox con el tablero `bid`; props=True deja abierto el panel de propiedades."""
    if page.viewport_size["width"] > 900:
        page.set_viewport_size({"width": 1600, "height": 1000})
    page.add_init_script(f"""localStorage.setItem('board-current', '{bid}');
        localStorage.setItem('board-view:{bid}', JSON.stringify({{x: 0, y: 0, zoom: {zoom}}}));
        localStorage.setItem('inbox-sidebar', 'open');
        localStorage.setItem('board-props', '{"open" if props else "closed"}');""")
    page.goto(server + "/inbox")
    page.wait_for_load_state("networkidle")
    page.wait_for_function("window.__board && __board.state.boardId === %d" % bid)


def screen(page, x, y):
    return page.evaluate("""([x, y]) => { const r = document.querySelector('.board-svg').getBoundingClientRect(), v = __board.state.view;
        return { x: r.left + v.x + x * v.zoom, y: r.top + v.y + y * v.zoom }; }""", [x, y])


def doc(page):
    return page.evaluate("JSON.parse(JSON.stringify(__board.state.doc))")


def saved(api, bid):
    return json.loads(api.get(f"/api/boards/{bid}").json()["data"])


def drag(page, a, b, steps=12, mid=None):
    page.mouse.move(a["x"], a["y"])
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(a["x"] + (b["x"] - a["x"]) * i / steps, a["y"] + (b["y"] - a["y"]) * i / steps)
        if mid and i == steps // 2:
            mid()
    page.mouse.up()


def edge_line(page, eid):
    """Primer y último punto del conector tal y como está pintado."""
    return page.evaluate("""id => { const p = document.querySelector(`[data-id="${id}"] .edge-line`);
        const a = p.getPointAtLength(0), b = p.getPointAtLength(p.getTotalLength());
        return [a.x, a.y, b.x, b.y]; }""", eid)


TWO = {"nodes": [{"id": "a", "kind": "rect", "x": 100, "y": 100, "w": 160, "h": 80, "text": "Caja A"},
                 {"id": "b", "kind": "rect", "x": 500, "y": 100, "w": 160, "h": 80, "text": "Caja B"}],
       "edges": [{"id": "e1", "from": "a", "to": "b", "color": "#89b4fa", "width": 2, "head": "arrow"}]}


def test_crear_caja_y_texto_dentro(page, server, api):
    bid = _board(api, {"nodes": []})
    _open(page, server, bid)
    page.keyboard.press("r")
    p = screen(page, 300, 200)
    page.mouse.click(p["x"], p["y"])
    page.keyboard.type("Texto de la caja")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    d = saved(api, bid)
    assert len(d["nodes"]) == 1 and d["nodes"][0]["text"] == "Texto de la caja"
    n = d["nodes"][0]
    # el texto es parte de la caja: va dentro de su foreignObject, que mide la caja menos el margen
    fo = page.evaluate("id => { const f = document.querySelector(`[data-id='${id}'] .node-fo`); return [+f.getAttribute('width'), +f.getAttribute('height')]; }", n["id"])
    assert fo == [n["w"] - 20, n["h"] - 20]
    # doble clic para editar
    c = screen(page, n["x"] + n["w"] / 2, n["y"] + n["h"] / 2)
    page.mouse.dblclick(c["x"], c["y"])
    page.keyboard.press("Control+a")
    page.keyboard.type("Editado\ncon dos líneas y bastante texto para que la caja tenga que crecer sola")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    n2 = saved(api, bid)["nodes"][0]
    assert n2["text"].startswith("Editado\ncon dos") and n2["h"] > n["h"]  # ajuste automático de tamaño


def test_flechas_ancladas_en_tiempo_real(page, server, api):
    bid = _board(api, TWO)
    _open(page, server, bid)
    x1, y1, x2, y2 = edge_line(page, "e1")
    assert abs(x1 - 266) < 1 and abs(x2 - 491) < 1  # bordes de A y B (con margen)
    seen = {}
    drag(page, screen(page, 580, 140), screen(page, 580, 400), mid=lambda: seen.update(mid=edge_line(page, "e1")))
    assert seen["mid"][3] > y2 + 40  # durante el arrastre la flecha ya sigue a la caja
    after = edge_line(page, "e1")
    b = next(n for n in doc(page)["nodes"] if n["id"] == "b")
    assert b["y"] % 20 == 0  # ajuste a la cuadrícula
    assert b["x"] - 10 <= after[2] <= b["x"] + b["w"] + 10 and b["y"] - 10 <= after[3] <= b["y"] + b["h"] + 10
    # selección múltiple (marco) y mover las dos: la flecha se mantiene
    drag(page, screen(page, 60, 60), screen(page, 720, 520))
    assert set(page.evaluate("[...__board.state.sel]")) >= {"a", "b"}
    before = edge_line(page, "e1")
    drag(page, screen(page, 180, 140), screen(page, 280, 240))
    moved = edge_line(page, "e1")
    assert all(abs((m - o) - 100) < 1 for m, o in zip(moved, before))
    # redimensionar B por la esquina: el extremo se recalcula
    page.keyboard.press("Escape")
    nb = next(n for n in doc(page)["nodes"] if n["id"] == "b")
    page.mouse.click(*screen(page, nb["x"] + nb["w"] / 2, nb["y"] + nb["h"] / 2).values())
    antes_resize = edge_line(page, "e1")
    drag(page, screen(page, nb["x"] + nb["w"], nb["y"] + nb["h"]), screen(page, nb["x"] + nb["w"] + 200, nb["y"] + nb["h"] + 100))
    nb2 = next(n for n in doc(page)["nodes"] if n["id"] == "b")
    assert nb2["w"] > nb["w"] + 150
    assert edge_line(page, "e1") != antes_resize
    # con zoom la flecha sigue unida (coordenadas del mundo no cambian)
    page.mouse.move(*screen(page, 300, 300).values())
    page.keyboard.down("Control")
    page.mouse.wheel(0, -400)
    page.keyboard.up("Control")
    assert page.evaluate("__board.state.view.zoom") > 1.2
    # tras el zoom la flecha sigue saliendo del borde de A (sus coordenadas son del mundo)
    a = next(n for n in doc(page)["nodes"] if n["id"] == "a")
    sx, sy = edge_line(page, "e1")[:2]
    assert a["x"] - 8 <= sx <= a["x"] + a["w"] + 8 and a["y"] - 8 <= sy <= a["y"] + a["h"] + 8


def test_zoom_mantiene_el_punto_y_ajustar(page, server, api):
    bid = _board(api, {"nodes": [{"id": "a", "kind": "rect", "x": 0, "y": 0, "w": 100, "h": 60, "text": ""},
                                 {"id": "z", "kind": "rect", "x": 3000, "y": 2000, "w": 100, "h": 60, "text": ""}]})
    _open(page, server, bid)
    p = screen(page, 50, 30)
    page.mouse.move(p["x"], p["y"])
    page.keyboard.down("Control")
    page.mouse.wheel(0, -300)
    page.keyboard.up("Control")
    q = screen(page, 50, 30)
    assert abs(q["x"] - p["x"]) < 2 and abs(q["y"] - p["y"]) < 2  # el punto bajo el cursor no se mueve
    page.click("#btnFit")
    page.wait_for_timeout(400)
    r = page.eval_on_selector(".board-svg", "e => e.getBoundingClientRect().toJSON()")
    for x, y in ((0, 0), (3100, 2060)):
        s = screen(page, x, y)
        assert r["left"] <= s["x"] <= r["right"] and r["top"] <= s["y"] <= r["bottom"]
    assert page.locator(".board-minimap").is_visible()


def test_colores_estilo_y_seleccion(page, server, api):
    bid = _board(api, TWO)
    _open(page, server, bid, props=True)
    page.keyboard.press("Control+a")
    props = page.locator("#boardProps")
    assert props.is_visible()  # panel de propiedades contextual
    props.locator("[data-prop=fill][aria-label=Rojo]").click()
    props.locator("[data-prop=color][aria-label=Amarillo]").click()
    props.locator("[data-prop=stroke][aria-label=Verde]").click()
    d = doc(page)
    assert all(n["fill"] == "#f38ba833" and n["color"] == "#f9e2af" and n["stroke"] == "#a6e3a1" for n in d["nodes"])
    assert d["edges"][0]["color"] == "#a6e3a1"  # el borde también va a los conectores seleccionados
    assert props.locator("[data-prop=fill][aria-label=Rojo]").get_attribute("aria-pressed") == "true"
    page.locator(".board-svg").focus()
    # copiar estilo de A y pegarlo en una caja nueva
    page.keyboard.press("Escape")
    page.mouse.click(*screen(page, 180, 140).values())
    page.keyboard.press("Control+Alt+c")
    page.keyboard.press("o")
    page.mouse.click(*screen(page, 300, 500).values())
    page.keyboard.press("Escape")
    nueva = doc(page)["nodes"][-1]
    page.mouse.click(*screen(page, nueva["x"] + 20, nueva["y"] + 20).values())
    page.keyboard.press("Control+Alt+v")
    assert doc(page)["nodes"][-1]["fill"] == "#f38ba833"


def test_productividad(page, server, api):
    bid = _board(api, {"nodes": [{"id": f"n{i}", "kind": "rect", "x": 100 + i * 200 + (i * 13), "y": 100 + i * 30, "w": 120, "h": 60, "text": str(i)} for i in range(3)]})
    _open(page, server, bid)
    page.keyboard.press("Control+a")
    page.click("#btnArrange")
    page.get_by_role("menuitem", name="Alinear arriba").click()
    assert len({n["y"] for n in doc(page)["nodes"]}) == 1
    page.click("#btnArrange")
    page.get_by_role("menuitem", name="Distribuir en horizontal").click()
    xs = sorted(n["x"] for n in doc(page)["nodes"])
    assert abs((xs[1] - xs[0]) - (xs[2] - xs[1])) < 0.5
    page.keyboard.press("Control+z")
    assert len({round(n["x"]) for n in doc(page)["nodes"]}) == 3
    page.keyboard.press("Control+Shift+z")
    page.keyboard.press("Control+g")
    page.keyboard.press("Escape")
    page.mouse.click(*screen(page, doc(page)["nodes"][0]["x"] + 10, doc(page)["nodes"][0]["y"] + 10).values())
    assert len(page.evaluate("[...__board.state.sel]")) == 3  # clic en uno selecciona el grupo
    page.keyboard.press("Control+d")
    assert len(doc(page)["nodes"]) == 6
    page.keyboard.press("Delete")
    assert len(doc(page)["nodes"]) == 3
    page.keyboard.press("Control+z")
    assert len(doc(page)["nodes"]) == 6
    # plantilla
    page.click("#btnTemplates")
    page.get_by_role("menuitem", name="Decisión").click()
    d = doc(page)
    assert len(d["nodes"]) == 9 and len(d["edges"]) == 2
    page.wait_for_timeout(900)
    assert len(saved(api, bid)["nodes"]) == 9  # se guarda solo


def test_soltar_tarea_donde_se_suelta(page, server, api):
    tid = api.post("/api/inbox", json={"content": "Al tablero nuevo", "item_type": "tarea"}).json()["id"]
    bid = _board(api, {"nodes": []})
    _open(page, server, bid, zoom=0.75)
    page.evaluate("__board.state.view.x = -137; __board.state.view.y = 59")  # vista desplazada a propósito
    card = page.locator(f'.il-item[data-id="{tid}"] .il-text').bounding_box()
    wrap = page.locator("#boardWrap").bounding_box()
    target = {"x": wrap["x"] + 420, "y": wrap["y"] + 260}
    drag(page, {"x": card["x"] + 20, "y": card["y"] + 8}, target, steps=20)
    page.wait_for_timeout(300)
    n = next(n for n in doc(page)["nodes"] if n.get("inboxId") == tid)
    c = screen(page, n["x"] + n["w"] / 2, n["y"] + n["h"] / 2)
    assert abs(c["x"] - target["x"]) < 2 and abs(c["y"] - target["y"]) < 2  # centrada donde se soltó


def test_movil_panel_deslizable_y_tactil(browser, server, api):
    bid = _board(api, TWO)
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, has_touch=True, is_mobile=True, service_workers="block")
    page = ctx.new_page()
    try:
        _open(page, server, bid)
        # en el móvil el Inbox empieza en la lista; tocar fuera la aparta y deja el tablero a la vista
        assert not page.evaluate("document.getElementById('inboxLayout').classList.contains('sidebar-collapsed')")
        page.mouse.click(10, 100)
        page.wait_for_timeout(400)
        assert page.evaluate("document.getElementById('inboxLayout').classList.contains('sidebar-collapsed')")
        page.click("#btnSidebar")
        page.wait_for_timeout(400)
        box = page.locator("#inboxSidebar").bounding_box()
        assert box["y"] < 500  # la hoja sube
        page.mouse.click(10, 100)
        page.wait_for_timeout(400)
        assert page.evaluate("document.getElementById('inboxLayout').classList.contains('sidebar-collapsed')")
        # un dedo en vacío desplaza el lienzo
        cdp = ctx.new_cdp_session(page)
        v0 = page.evaluate("({...__board.state.view})")
        r = page.locator(".board-svg").bounding_box()
        x, y = r["x"] + 40, r["y"] + r["height"] - 60
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for i in range(1, 9):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + i * 10, "y": y - i * 5}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        v1 = page.evaluate("({...__board.state.view})")
        assert abs(v1["x"] - v0["x"] - 80) < 2 and abs(v1["y"] - v0["y"] + 40) < 2
    finally:
        ctx.close()


def _tarea_con_pasos(api, nombre, n=3, **extra):
    tid = api.post("/api/items", json={"text": nombre, "type": "tarea", **extra}).json()["id"]
    pasos = [api.post("/api/items", json={"text": f"Paso {i} de {nombre}", "type": "tarea", "parent_id": tid}).json()["id"] for i in range(n)]
    return tid, pasos


def _soltar(page, tid):
    card = page.locator(f'.il-list > .il-item[data-id="{tid}"] > .il-row .il-text').bounding_box()
    wrap = page.locator("#boardWrap").bounding_box()
    drag(page, {"x": card["x"] + 20, "y": card["y"] + 8}, {"x": wrap["x"] + 460, "y": wrap["y"] + 300}, steps=20)
    page.wait_for_timeout(300)
    return next(n for n in doc(page)["nodes"] if n.get("inboxId") == tid)


def test_una_tarea_llega_al_tablero_con_sus_pasos(page, server, api):
    tid, pasos = _tarea_con_pasos(api, "Bloque entero")
    bid = _board(api, {"nodes": []})
    _open(page, server, bid)
    n = _soltar(page, tid)
    filas = page.locator(".node-inbox .node-step")
    assert filas.count() == 3 and "Paso 0 de Bloque entero" in filas.first.inner_text()
    # cabe entera: nada se recorta
    assert page.locator(".node-inbox .node-fo").evaluate("(f) => f.scrollHeight <= f.clientHeight + 1")
    assert n["h"] > 96
    # el check de un paso marca el paso de verdad, y la tarjeta se entera
    page.locator(f'[data-step-check="{pasos[0]}"]').click()
    expect_done = lambda: next(i for i in api.get("/api/items").json()["items"] if i["id"] == pasos[0])["done"]  # noqa: E731
    page.wait_for_timeout(300)
    assert expect_done() and page.locator(".node-steps-foot").inner_text().startswith("1 de 3")


def test_quitar_pasos_de_la_tarjeta_no_los_borra(page, server, api):
    tid, pasos = _tarea_con_pasos(api, "Con pasos de sobra")
    bid = _board(api, {"nodes": []})
    _open(page, server, bid)
    n = _soltar(page, tid)
    alto = n["h"]
    fila = page.locator(".node-step", has_text="Paso 1 de")
    fila.hover()
    fila.locator("[data-step-hide]").click()
    page.wait_for_timeout(150)
    assert page.locator(".node-step").count() == 2
    assert next(m for m in doc(page)["nodes"] if m["id"] == n["id"])["h"] < alto  # se recoge
    assert sum(1 for i in api.get("/api/items").json()["items"] if i["parent_id"] == tid) == 3  # siguen en la tarea
    # deshacer lo devuelve
    page.locator("#boardWrap").click(position={"x": 30, "y": 400})
    page.keyboard.press("Control+z")
    page.wait_for_timeout(150)
    assert page.locator(".node-step").count() == 3
    # quitarlos todos deja la tarea sola, y se pueden recuperar
    page.get_by_role("button", name="Quitar pasos").click()
    page.wait_for_timeout(150)
    assert page.locator(".node-step").count() == 0
    page.get_by_role("button", name="Mostrar 3 ocultos").click()
    page.wait_for_timeout(150)
    assert page.locator(".node-step").count() == 3
    page.wait_for_timeout(900)
    assert "hiddenSteps" not in next(m for m in saved(api, bid)["nodes"] if m["id"] == n["id"])


def test_un_paso_con_tarjeta_propia_no_se_repite(page, server, api):
    tid, pasos = _tarea_con_pasos(api, "Sin repetir", n=2)
    bid = _board(api, {"nodes": [
        {"id": "a", "kind": "inbox", "x": 0, "y": 0, "w": 260, "h": 96, "text": "Sin repetir", "inboxId": tid, "itemType": "tarea"},
        {"id": "b", "kind": "inbox", "x": 0, "y": 300, "w": 220, "h": 96, "text": "Paso", "inboxId": pasos[0], "itemType": "tarea"}]})
    _open(page, server, bid)
    page.wait_for_timeout(300)
    assert page.locator(".node-step").count() == 1 and "Paso 1 de" in page.locator(".node-step").inner_text()
