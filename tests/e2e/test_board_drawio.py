"""Ronda 2 · fase 3 (corrección draw.io): controles de aceptación del tablero.

1. Paleta «Plantilla»: clic = en el centro de la vista, arrastrar = donde se suelta; «Mis plantillas».
2. Formas nuevas, contenedor que arrastra su contenido y doble clic en vacío = texto.
3. El texto escala al redimensionar; «Ajustar texto a la caja».
4. Lo nuevo sale a tamaño normal en pantalla con cualquier zoom y dentro de lo visible.
5. Conectores: lados fijos, enrutado recto/ortogonal/curvo, puntas, etiqueta y reenganche.
6. Bloquear, guías inteligentes y panel de propiedades.
7. Enlace con el Inbox en los dos sentidos (texto y completar).
Además: deshacer sin límite práctico, exportar PNG/SVG/JSON e importar, rendimiento con 500
formas y capturas a 375/768/1280 (si BOARD_SHOTS apunta a una carpeta).
"""
import json
import os
from pathlib import Path

import pytest

from tests.e2e.test_board import _board, _open, doc, drag, edge_line, saved, screen

SHOTS = os.environ.get("BOARD_SHOTS")


def node_of(page, nid):
    return next(n for n in doc(page)["nodes"] if n["id"] == nid)


def tile_center(page, selector):
    loc = page.locator(selector).first
    loc.scroll_into_view_if_needed()
    b = loc.bounding_box()
    return {"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2}


def view_rect(page):
    """Rectángulo visible del lienzo en coordenadas del mundo."""
    return page.evaluate("""() => { const r = document.querySelector('.board-svg').getBoundingClientRect(), v = __board.state.view;
        return { x: -v.x / v.zoom, y: -v.y / v.zoom, w: r.width / v.zoom, h: r.height / v.zoom }; }""")


def inside(n, v):
    return v["x"] <= n["x"] and v["y"] <= n["y"] and n["x"] + n["w"] <= v["x"] + v["w"] and n["y"] + n["h"] <= v["y"] + v["h"]


def test_1_paleta_clic_arrastrar_y_mis_plantillas(page, server, api):
    bid = _board(api, {"nodes": []})
    _open(page, server, bid)
    page.locator("#paneTabPlantilla").click()
    assert page.locator("#panePlantilla").is_visible()
    assert page.locator("#shapePalette .shape-tile").count() == 9
    # clic: en el centro de la vista
    page.locator(".shape-tile[data-shape=diamond]").click()
    n = doc(page)["nodes"][-1]
    assert n["kind"] == "diamond"
    v = view_rect(page)
    assert abs(n["x"] + n["w"] / 2 - (v["x"] + v["w"] / 2)) < 12 and abs(n["y"] + n["h"] / 2 - (v["y"] + v["h"] / 2)) < 12
    # arrastrar: queda centrado donde se suelta
    target = screen(page, 300, 420)
    drag(page, tile_center(page, ".shape-tile[data-shape=container]"), target, steps=16)
    page.wait_for_timeout(200)
    c = next(x for x in doc(page)["nodes"] if x["kind"] == "container")
    assert abs(c["x"] + c["w"] / 2 - 300) < 2 and abs(c["y"] + c["h"] / 2 - 420) < 2
    # una flecha suelta desde la paleta
    page.locator(".shape-tile[data-shape=arrow]").click()
    e = doc(page)["edges"][-1]
    assert e["p1"] and e["p2"] and not e.get("from") and e["endHead"] == "arrow"
    # una plantilla de la lista, arrastrada al tablero
    before = len(doc(page)["nodes"])
    drag(page, tile_center(page, ".tpl-tile[data-template=b2]"), screen(page, 700, 300), steps=16)
    page.wait_for_timeout(200)
    assert len(doc(page)["nodes"]) == before + 3
    # Mis plantillas: guardar la selección y que aparezca en la lista
    page.locator("#templateSave").click()
    page.locator("dialog[open] input").fill("Mi rombo")
    page.locator("dialog[open] [data-role=ok]").click()
    page.wait_for_selector(".tpl-tile:has-text('Mi rombo')")
    assert any(t["name"] == "Mi rombo" for t in api.get("/api/board-templates").json()["templates"])
    page.wait_for_timeout(900)
    assert len(saved(api, bid)["nodes"]) == before + 3


def test_2_formas_contenedor_y_doble_clic_texto(page, server, api):
    bid = _board(api, {"nodes": [
        {"id": "c", "kind": "container", "x": 100, "y": 100, "w": 400, "h": 300, "text": "Grupo"},
        {"id": "a", "kind": "box", "x": 140, "y": 180, "w": 120, "h": 60, "text": "Dentro"},
        {"id": "z", "kind": "rect", "x": 700, "y": 180, "w": 120, "h": 60, "text": "Fuera"}]})
    _open(page, server, bid)
    # el rectángulo recto no tiene esquinas redondeadas; el contenedor tiene su franja de título
    assert page.locator("[data-id=a] .shape").get_attribute("rx") == "0"
    assert page.locator("[data-id=c] .container-sep").count() == 1
    # arrastrar el contenedor por su título arrastra lo que tiene dentro (y no lo de fuera)
    drag(page, screen(page, 300, 116), screen(page, 380, 196))
    assert (node_of(page, "a")["x"], node_of(page, "a")["y"]) == (220, 260)
    assert node_of(page, "z")["x"] == 700
    # doble clic en vacío: un cuadro de texto (no una caja)
    p = screen(page, 620, 640)
    page.mouse.dblclick(p["x"], p["y"])
    page.keyboard.type("Un texto suelto")
    page.keyboard.press("Escape")
    t = doc(page)["nodes"][-1]
    assert t["kind"] == "text" and t["text"] == "Un texto suelto"
    # doble clic en vacío sin escribir nada: no deja un texto vacío
    page.mouse.dblclick(p["x"], p["y"] + 100)
    page.keyboard.press("Escape")
    assert not any(n["kind"] == "text" and not n["text"] for n in doc(page)["nodes"])


def test_3_texto_escala_y_ajustar_a_la_caja(page, server, api):
    bid = _board(api, {"nodes": [{"id": "a", "kind": "rect", "x": 100, "y": 100, "w": 160, "h": 80, "text": "Escala"}]})
    _open(page, server, bid, props=True)
    page.mouse.click(*screen(page, 180, 140).values())
    drag(page, screen(page, 260, 180), screen(page, 420, 260))  # el doble por la esquina
    a = node_of(page, "a")
    assert a["w"] == 320 and abs(a["fontSize"] - 32) < 0.2
    assert page.locator("[data-id=a] .node-text").evaluate("e => e.style.fontSize") == "32px"
    # «Ajustar texto a la caja»: la letra se calcula para llenar la caja
    page.locator("#boardProps [data-prop=fitText]").check()
    assert node_of(page, "a")["fitText"] is True
    big = page.locator("[data-id=a] .node-text").evaluate("e => parseFloat(e.style.fontSize)")
    assert big > 40
    fits = page.locator("[data-id=a] .node-text").evaluate("e => e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1")
    assert fits
    # por un lado (sin esquina) con ajuste: la letra baja al estrechar
    drag(page, screen(page, 420, 180), screen(page, 260, 180))
    small = page.locator("[data-id=a] .node-text").evaluate("e => parseFloat(e.style.fontSize)")
    assert small < big


@pytest.mark.parametrize("zoom", [0.5, 2])
def test_4_tamano_normal_con_cualquier_zoom(page, server, api, zoom):
    bid = _board(api, {"nodes": []})
    _open(page, server, bid, zoom=zoom)
    page.evaluate("__board.state.view.x = -4000; __board.state.view.y = -2500; __board.applyView()")  # vista lejos del origen
    page.locator("#paneTabPlantilla").click()
    page.locator(".shape-tile[data-shape=rect]").click()
    n = doc(page)["nodes"][-1]
    assert abs(n["w"] * zoom - 180) < 1 and abs(n["fontSize"] * zoom - 16) < 0.2 and abs(n["strokeWidth"] * zoom - 2) < 0.1
    assert inside(n, view_rect(page))
    # en pantalla mide lo mismo que con zoom 100 %
    w = page.locator(f"[data-id={n['id']}] .shape").evaluate("e => e.getBoundingClientRect().width")
    assert abs(w - 180) < 4
    # doble clic junto al borde derecho: el texto se queda dentro de lo visible
    r = page.locator(".board-svg").bounding_box()
    page.mouse.click(r["x"] + 30, r["y"] + 30)  # deselecciona (el panel de propiedades se oculta)
    page.mouse.dblclick(r["x"] + r["width"] - 6, r["y"] + r["height"] / 2)
    page.keyboard.type("Borde")
    page.keyboard.press("Escape")
    t = doc(page)["nodes"][-1]
    assert t["kind"] == "text" and inside(t, view_rect(page))
    # un conector dibujado con este zoom tiene el grosor normal en pantalla
    page.keyboard.press("a")
    a, b = screen(page, n["x"] + n["w"] / 2, n["y"] + n["h"] / 2), screen(page, n["x"] + n["w"] / 2, n["y"] + n["h"] * 3)
    drag(page, a, b)
    e = doc(page)["edges"][-1]
    assert abs(e["width"] * zoom - 2) < 0.1


def test_5_conectores(page, server, api):
    bid = _board(api, {"nodes": [
        {"id": "a", "kind": "rect", "x": 100, "y": 100, "w": 160, "h": 80, "text": "A"},
        {"id": "b", "kind": "rect", "x": 500, "y": 300, "w": 160, "h": 80, "text": "B"},
        {"id": "c", "kind": "ellipse", "x": 100, "y": 450, "w": 160, "h": 90, "text": "C"}]})
    _open(page, server, bid, props=True)
    # del punto de conexión derecho de A al izquierdo de B (lados fijos)
    page.mouse.move(*screen(page, 180, 140).values())
    page.wait_for_selector(".anchor[data-side=e]")
    drag(page, screen(page, 260, 140), screen(page, 502, 340))
    e = doc(page)["edges"][-1]
    assert (e["from"], e["fromSide"], e["to"], e["toSide"]) == ("a", "e", "b", "w")
    eid = e["id"]
    props = page.locator("#boardProps")
    # enrutado ortogonal: tramos horizontales y verticales con esquinas redondeadas
    props.locator("[data-prop=route][data-value=orthogonal]").click()
    d = page.locator(f"[data-id={eid}] .edge-line").get_attribute("d")
    assert d.count("Q") == 2
    x1, y1, x2, y2 = edge_line(page, eid)
    assert abs(y1 - 140) < 1 and abs(y2 - 340) < 1 and x1 > 260 and x2 < 500
    # curvo
    props.locator("[data-prop=route][data-value=curved]").click()
    assert " C" in page.locator(f"[data-id={eid}] .edge-line").get_attribute("d")
    # puntas en los dos extremos
    props.locator("select[data-prop=startHead]").select_option("diamond")
    props.locator("select[data-prop=endHead]").select_option("open")
    line = page.locator(f"[data-id={eid}] .edge-line")
    assert "mk-diamond" in line.get_attribute("marker-start") and "mk-open" in line.get_attribute("marker-end")
    # etiqueta con doble clic en el conector
    props.locator("[data-prop=route][data-value=straight]").click()
    mid = page.evaluate("id => __board.edgeGeom(__board.state.doc.edges.find(e => e.id === id)).mid", eid)
    page.mouse.dblclick(*screen(page, mid["x"], mid["y"]).values())
    page.keyboard.type("depende de")
    page.keyboard.press("Enter")
    assert next(x for x in doc(page)["edges"] if x["id"] == eid)["label"] == "depende de"
    assert page.locator(f"[data-id={eid}] .edge-label-text").text_content() == "depende de"
    # reenganchar el extremo final a C, y luego dejarlo libre
    page.mouse.click(*screen(page, mid["x"], mid["y"]).values())
    geo = page.evaluate("id => __board.edgeGeom(__board.state.doc.edges.find(e => e.id === id))", eid)
    drag(page, screen(page, geo["t"]["x"], geo["t"]["y"]), screen(page, 180, 495))
    e = next(x for x in doc(page)["edges"] if x["id"] == eid)
    assert e["to"] == "c" and "p2" not in e
    geo = page.evaluate("id => __board.edgeGeom(__board.state.doc.edges.find(e => e.id === id))", eid)
    drag(page, screen(page, geo["t"]["x"], geo["t"]["y"]), screen(page, 800, 600))
    e = next(x for x in doc(page)["edges"] if x["id"] == eid)
    assert "to" not in e and abs(e["p2"][0] - 800) < 1
    page.keyboard.press("Control+z")
    assert next(x for x in doc(page)["edges"] if x["id"] == eid)["to"] == "c"
    page.wait_for_timeout(900)
    assert next(x for x in saved(api, bid)["edges"] if x["id"] == eid)["label"] == "depende de"


def test_6_bloquear_guias_y_propiedades(page, server, api):
    bid = _board(api, {"nodes": [
        {"id": "a", "kind": "rect", "x": 113, "y": 97, "w": 160, "h": 80, "text": "Referencia"},
        {"id": "b", "kind": "rect", "x": 500, "y": 400, "w": 160, "h": 80, "text": "Móvil"}]})
    _open(page, server, bid, props=True)
    # guía: al acercar el borde izquierdo de B al de A se alinea exactamente (113, fuera de la cuadrícula)
    seen = {}
    drag(page, screen(page, 580, 440), screen(page, 580 - 384, 440))
    assert node_of(page, "b")["x"] == 113
    page.mouse.move(*screen(page, 196, 440).values())
    page.mouse.down()
    page.mouse.move(*screen(page, 197, 300).values(), steps=6)
    seen["guides"] = page.locator(".board-overlay .guide").count()
    page.mouse.up()
    assert seen["guides"] >= 1 and node_of(page, "b")["x"] == 113
    # panel de propiedades: grosor y línea discontinua
    page.mouse.click(*screen(page, 190, 137).values())
    props = page.locator("#boardProps")
    props.locator("[data-prop=strokeWidth][data-value='4']").click()
    props.locator("[data-prop=dash][data-value=dashed]").click()
    a = node_of(page, "a")
    assert a["strokeWidth"] == 4 and a["dash"] == "dashed"
    assert page.locator("[data-id=a] .shape").get_attribute("stroke-dasharray") == "16 12"
    # tamaño de letra con el campo numérico
    props.locator("input[data-prop=fontSize]").fill("22")
    props.locator("input[data-prop=fontSize]").press("Enter")
    assert node_of(page, "a")["fontSize"] == 22
    # bloquear: no se mueve, no se redimensiona ni se borra
    props.locator("[data-act=lock]").click()
    assert node_of(page, "a")["locked"] is True
    assert page.locator(".board-overlay [data-handle]").count() == 0 and page.locator(".board-overlay .lock-badge").count() == 1
    page.locator(".board-svg").focus()
    drag(page, screen(page, 190, 137), screen(page, 400, 300))
    assert (node_of(page, "a")["x"], node_of(page, "a")["y"]) == (113, 97)
    page.keyboard.press("Delete")
    assert any(n["id"] == "a" for n in doc(page)["nodes"])
    page.keyboard.press("l")  # desbloquear con el atajo
    assert "locked" not in node_of(page, "a")


def test_7_inbox_en_los_dos_sentidos(page, server, api):
    iid = api.post("/api/inbox", json={"content": "Llamar al taller", "item_type": "tarea"}).json()["id"]
    bid = _board(api, {"nodes": [{"id": "t", "kind": "inbox", "inboxId": iid, "itemType": "tarea", "x": 100, "y": 100, "w": 220, "h": 96, "text": "Llamar al taller"}]})
    _open(page, server, bid)
    page.wait_for_selector("[data-id=t] .node-check")
    # editar el texto desde el tablero cambia el elemento del Inbox (y su tarjeta en la lista)
    page.mouse.dblclick(*screen(page, 180, 140).values())
    page.keyboard.press("Control+a")
    page.keyboard.type("Llamar al taller el lunes")
    page.keyboard.press("Escape")
    page.wait_for_load_state("networkidle")
    items = {i["id"]: i for i in api.get("/api/items").json()["items"]}
    assert items[iid]["text"] == "Llamar al taller el lunes"
    page.locator(f'.il-item[data-id="{iid}"] .il-text', has_text="el lunes").wait_for()
    # completar desde la casilla de la tarjeta del tablero
    with page.expect_response(lambda r: "/api/items" in r.url and r.request.method != "GET"):
        page.mouse.click(*screen(page, 100 + 220 - 16, 100 + 16).values())
    assert {i["id"]: i for i in api.get("/api/items").json()["items"]}[iid]["done"] is True
    page.wait_for_selector("[data-id=t].is-done")
    # y de la lista al tablero: reabrirla en la lista se refleja en la tarjeta
    page.locator(".il [data-status=done], .sidebar-tabs [data-status=done]").first.click()
    page.click(f'.il-item[data-id="{iid}"] > .il-row [data-act=done]')
    page.wait_for_selector("[data-id=t]:not(.is-done)")


def test_historial_sin_limite_y_exportar_importar(page, server, api, tmp_path):
    bid = _board(api, {"nodes": [{"id": "a", "kind": "rect", "x": 100, "y": 100, "w": 160, "h": 80, "text": "Exportar"},
                                 {"id": "b", "kind": "diamond", "x": 400, "y": 100, "w": 160, "h": 100, "text": "Rombo"}],
                       "edges": [{"id": "e", "from": "a", "to": "b", "route": "orthogonal", "label": "sí", "color": "#89b4fa", "width": 2, "endHead": "arrow"}]})
    _open(page, server, bid)
    page.mouse.click(*screen(page, 180, 140).values())
    for _ in range(200):  # más que el límite antiguo (120)
        page.keyboard.press("ArrowRight")
    assert node_of(page, "a")["x"] == 500
    for _ in range(200):
        page.keyboard.press("Control+z")
    assert node_of(page, "a")["x"] == 100
    # SVG autónomo: texto como <text>, sin foreignObject
    svg = page.evaluate("__board.exportSvg()")
    assert "<foreignObject" not in svg and "Exportar" in svg and "<text" in svg and "sí" in svg
    page.click("#btnBoardMenu")
    with page.expect_download() as dl:
        page.get_by_role("menuitem", name="Exportar como PNG").click()
    png = Path(dl.value.path()).read_bytes()
    assert dl.value.suggested_filename == "e2e-tablero.png" and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 2000
    page.click("#btnBoardMenu")
    with page.expect_download() as dl:
        page.get_by_role("menuitem", name="Exportar como JSON").click()
    data = json.loads(Path(dl.value.path()).read_text())
    assert data["format"] == 2 and len(data["nodes"]) == 2
    # importar el JSON añade una copia (con identificadores nuevos) y se puede deshacer
    page.click("#btnBoardMenu")
    with page.expect_file_chooser() as fc:
        page.get_by_role("menuitem", name="Importar JSON…").click()
    fc.value.set_files(dl.value.path())
    page.wait_for_function("__board.state.doc.nodes.length === 4")
    d = doc(page)
    assert len(d["edges"]) == 2 and len({n["id"] for n in d["nodes"]}) == 4


def test_rendimiento_500_formas(page, server, api):
    nodes = [{"id": f"n{i}", "kind": "rect", "x": (i % 25) * 220, "y": (i // 25) * 140, "w": 180, "h": 90, "text": f"Caja {i}"} for i in range(500)]
    edges = [{"id": f"e{i}", "from": f"n{i}", "to": f"n{i + 1}", "color": "#89b4fa", "width": 2, "route": ["straight", "orthogonal", "curved"][i % 3]} for i in range(400)]
    bid = _board(api, {"nodes": nodes, "edges": edges})
    _open(page, server, bid, zoom=0.25)
    assert page.locator(".board-world .node").count() == 500
    r = page.evaluate("""() => {
        const t = (f) => { const t0 = performance.now(); f(); return performance.now() - t0; };
        const idle = t(() => __board.renderAll());                       // nada cambió: firmas iguales
        const svg = document.querySelector('.board-svg'), box = svg.getBoundingClientRect(), v = __board.state.view;
        const at = (x, y) => ({ clientX: box.left + v.x + x * v.zoom, clientY: box.top + v.y + y * v.zoom, pointerId: 9, pointerType: 'mouse', button: 0, bubbles: true });
        __board.state.sel = new Set(__board.state.doc.nodes.slice(0, 100).map(n => n.id));
        const p0 = at(90, 45);
        const times = [];
        document.elementFromPoint(p0.clientX, p0.clientY).dispatchEvent(new PointerEvent('pointerdown', p0));
        for (let i = 1; i <= 40; i++) times.push(t(() => svg.dispatchEvent(new PointerEvent('pointermove', at(90 + i * 7, 45 + i * 3)))));
        const up = t(() => svg.dispatchEvent(new PointerEvent('pointerup', at(90 + 280, 45 + 120))));
        return { idle, avg: times.reduce((a, b) => a + b) / times.length, max: Math.max(...times), up };
    }""")
    # 100 formas seleccionadas y sus conectores se mueven por debajo de un fotograma
    assert r["idle"] < 30, r
    assert r["avg"] < 16, r
    assert r["up"] < 400, r
    assert node_of(page, "n0")["x"] != 0


DEMO = {"nodes": [
    {"id": "c", "kind": "container", "x": 0, "y": 0, "w": 420, "h": 300, "text": "Semana", "stroke": "#89b4fa", "fill": "#89b4fa1a"},
    {"id": "s", "kind": "ellipse", "x": 40, "y": 60, "w": 150, "h": 70, "text": "Inicio", "stroke": "#a6e3a1", "fill": "#a6e3a133"},
    {"id": "p", "kind": "box", "x": 230, "y": 60, "w": 160, "h": 70, "text": "Preparar informe"},
    {"id": "d", "kind": "diamond", "x": 140, "y": 170, "w": 170, "h": 110, "text": "¿Listo?", "stroke": "#f9e2af", "fill": "#f9e2af33"},
    {"id": "n", "kind": "sticky", "x": 480, "y": 20, "w": 170, "h": 140, "text": "Recordar adjuntar las cifras"},
    {"id": "t", "kind": "text", "x": 480, "y": 200, "w": 220, "h": 44, "text": "Plan de la semana"}],
    "edges": [{"id": "e1", "from": "s", "to": "p", "route": "straight", "color": "#89b4fa", "width": 2},
              {"id": "e2", "from": "p", "to": "d", "route": "orthogonal", "fromSide": "s", "toSide": "e", "color": "#89b4fa", "width": 2, "label": "revisar"},
              {"id": "e3", "from": "d", "to": "n", "route": "curved", "fromSide": "e", "toSide": "s", "color": "#cba6f7", "width": 2, "dash": "dashed", "label": "sí"}]}


@pytest.mark.parametrize("w,h", [(375, 812), (768, 1024), (1280, 800)])
def test_capturas(browser, server, api, w, h):
    bid = _board(api, DEMO)
    mobile = w < 768
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=mobile, is_mobile=mobile, service_workers="block")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.add_init_script(f"localStorage.setItem('board-current', '{bid}'); localStorage.removeItem('board-view:{bid}'); localStorage.setItem('inbox-sidebar', 'open');")
        page.goto(server + "/inbox")
        page.wait_for_load_state("networkidle")
        page.wait_for_function("window.__board && __board.state.boardId === %d" % bid)
        page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")  # sin desbordamiento horizontal
        page.evaluate("__board.state.sel = new Set(['d', 'e2']); __board.renderAll()")
        page.wait_for_timeout(100)
        if not page.locator("#boardProps").is_visible():  # tablero estrecho: el panel es una hoja que se abre a petición
            assert page.evaluate("document.getElementById('boardArea').clientWidth") < 560
            page.click("#btnProps")
        page.wait_for_timeout(250)
        assert page.locator("#boardProps").is_visible()
        props = page.locator("#boardProps").bounding_box()
        assert props["x"] >= 0 and props["x"] + props["width"] <= w + 0.5
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=f"{SHOTS}/tablero-{w}.png")
            if mobile:  # la hoja con la paleta
                page.click("#btnSidebar")
                page.wait_for_timeout(450)
                page.locator("#colPlantilla").scroll_into_view_if_needed()
                page.screenshot(path=f"{SHOTS}/tablero-{w}-paleta.png")
            else:
                page.locator("#colPlantilla").scroll_into_view_if_needed()
                page.screenshot(path=f"{SHOTS}/tablero-{w}-paleta.png")
        assert not errors, errors
    finally:
        ctx.close()
