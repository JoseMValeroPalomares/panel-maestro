"""Grafo: plegar una categoría (clic o doble clic) la deja a la vista con «＋» y sus conexiones hacia fuera, y otro
clic la despliega; la vista (centro y zoom) se recuerda al volver a entrar."""


def _abrir(page, server):
    page.goto(f"{server}/graph")
    page.locator("#loadingOverlay").wait_for(state="hidden", timeout=30_000)


def _punto(page, node_id):
    # tras repintar, la física recoloca los nodos sin posición guardada un momento: se espera a que se queden quietos
    page.wait_for_function(
        """(id) => new Promise((ok) => { const a = JSON.stringify(network.getPositions([id]));
                   setTimeout(() => ok(a === JSON.stringify(network.getPositions([id]))), 250); })""",
        arg=node_id,
        timeout=10_000,
    )
    return page.evaluate(
        """(id) => { const p = network.canvasToDOM(network.getPositions([id])[id]);
                     const b = document.getElementById('graph-container').getBoundingClientRect();
                     return { x: b.left + p.x, y: b.top + p.y }; }""",
        node_id,
    )


def _estado(page, node_id):
    return page.evaluate(
        """(id) => ({ label: nodesDS.get(id)?.label || null,
                     plegadas: edgesDS.get().filter(e => String(e.id).startsWith('plegada:')).length })""",
        node_id,
    )


def test_plegar_categoria_no_la_hace_desaparecer(page, api, server):
    for nid, title, cat, content in (
        ("plegar-uno", "Plegar Uno", "E2E Plegar", "Enlaza con [[Plegar Fuera]]."),
        ("plegar-dos", "Plegar Dos", "E2E Plegar", "Nada."),
        ("plegar-fuera", "Plegar Fuera", "E2E Otra", "Nada."),
    ):
        assert (
            api.post(f"/api/notes/{nid}", json={"title": title, "category": cat, "content": content}).status_code == 200
        )
    _abrir(page, server)
    cat = page.evaluate("nodesDS.get().find(n => n.type === 'category' && n.label === 'E2E Plegar').id")
    page.evaluate(f"network.focus({cat!r}, {{ scale: 1, animation: false }})")
    p = _punto(page, cat)
    page.mouse.dblclick(p["x"], p["y"])
    page.wait_for_timeout(800)
    st = _estado(page, cat)
    assert st["label"] == "E2E Plegar ＋"  # sigue ahí, plegada una sola vez
    assert st["plegadas"] >= 1  # su enlace con «Plegar Fuera» sale ahora de la categoría
    assert page.evaluate("nodesDS.get('plegar-uno')") is None
    p = _punto(page, cat)
    page.mouse.click(p["x"], p["y"])
    page.wait_for_timeout(800)
    assert _estado(page, cat)["label"] == "E2E Plegar"
    assert page.evaluate("!!nodesDS.get('plegar-uno')")


def test_la_vista_se_recuerda(page, api, server):
    api.post("/api/notes/vista-uno", json={"title": "Vista Uno", "category": "E2E Vista", "content": "x"})
    _abrir(page, server)
    page.evaluate("network.moveTo({ position: { x: 123, y: -45 }, scale: 0.777, animation: false }); userMovedView()")
    page.wait_for_timeout(1200)  # se guarda con un pequeño retardo
    page.goto(f"{server}/vault")
    _abrir(page, server)
    page.wait_for_timeout(600)
    v = page.evaluate("({ ...network.getViewPosition(), scale: network.getScale() })")
    assert abs(v["x"] - 123) < 1 and abs(v["y"] + 45) < 1 and abs(v["scale"] - 0.777) < 0.002
    # «Encuadrar todo» cambia la vista guardada
    page.click(".graph-fit")
    page.wait_for_timeout(1500)
    assert abs(page.evaluate("Prefs.get('grafo-vista').scale") - 0.777) > 0.001
