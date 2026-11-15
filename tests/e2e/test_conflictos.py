"""Tanda 1c · D-4: dos dispositivos con la misma nota o el mismo tablero no se pisan sin avisar.

Cada «dispositivo» es un contexto de navegador propio (sin caché ni pestañas compartidas)."""

import json
import uuid

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers import wait_js


@pytest.fixture()
def nota(api):
    nid = "conflicto-" + uuid.uuid4().hex[:6]
    api.post(
        f"/api/notes/{nid}",
        json={
            "title": "Conflicto",
            "category": "E2E",
            "status": "en-desarrollo",
            "content": "Línea común\n\nPrincipio",
            "tags": [],
        },
    )
    yield nid
    api.delete(f"/api/notes/{nid}")


@pytest.fixture()
def dispositivo(browser, server):
    """Abre otro «dispositivo»: contexto nuevo con su página. Recoge errores de consola como la fixture page."""
    ctxs, errors = [], []

    def abrir(width=1280):
        ctx = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
        ctxs.append(ctx)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "status of 409" not in m.text and errors.append(m.text))
        return pg

    yield abrir
    for c in ctxs:
        c.close()
    assert not errors, f"Errores en la consola: {errors}"


def _abrir_nota(pg, server, nid):
    pg.goto(f"{server}/?note={nid}")
    expect(pg.locator("#noteTitle")).to_have_value("Conflicto")
    expect(pg.locator("#noteContent")).to_be_visible()


def _escribir(pg, texto):
    pg.locator("#noteContent").fill(texto)
    expect(pg.locator("#saveIndicator")).to_have_text("Guardado", timeout=5000)


def _versiones(api, nid):
    return [
        api.get(f"/api/notes/{nid}/versions/{v['id']}").json()["content"]
        for v in api.get(f"/api/notes/{nid}/versions").json()["versions"]
    ]


def _conflicto(server, nid, dispositivo, api):
    """A guarda; B, que abrió antes, guarda después → B ve el diálogo."""
    a, b = dispositivo(), dispositivo()
    _abrir_nota(a, server, nid)
    _abrir_nota(b, server, nid)
    _escribir(a, "Línea común\n\nEscrito en A")
    b.locator("#noteContent").fill("Línea común\n\nEscrito en B")
    dlg = b.locator("dialog.conflict-modal")
    expect(dlg).to_be_visible(timeout=5000)
    expect(dlg.get_by_role("heading")).to_have_text("Esta nota cambió en otro dispositivo")
    assert "Escrito en A" in api.get(f"/api/notes/{nid}").json()["content"]  # no se ha pisado
    return a, b, dlg


def test_ver_diferencias_y_quedarme_con_lo_mio(server, api, nota, dispositivo):
    a, b, dlg = _conflicto(server, nota, dispositivo, api)
    dlg.get_by_role("button", name="Ver diferencias").click()
    lines = dlg.locator(".conflict-lines")
    expect(lines.locator(".diff-mine")).to_contain_text("Escrito en B")
    expect(lines.locator(".diff-theirs")).to_contain_text("Escrito en A")
    dlg.get_by_role("button", name="Quedarme con lo mío").click()
    expect(dlg).to_be_hidden()
    expect(b.locator("#saveIndicator")).to_have_text("Guardado", timeout=5000)
    assert "Escrito en B" in api.get(f"/api/notes/{nota}").json()["content"]
    assert any("Escrito en A" in v for v in _versiones(api, nota))  # lo de A, en el historial
    # B sigue escribiendo sin más conflictos
    _escribir(b, "Línea común\n\nEscrito en B y más")
    expect(b.locator("dialog.conflict-modal")).to_have_count(0)


def test_recargar_la_otra_deja_lo_mio_en_el_historial(server, api, nota, dispositivo):
    a, b, dlg = _conflicto(server, nota, dispositivo, api)
    dlg.get_by_role("button", name="Recargar la otra").click()
    expect(b.locator("#noteContent")).to_have_value("Línea común\n\nEscrito en A")
    assert "Escrito en A" in api.get(f"/api/notes/{nota}").json()["content"]
    vers = api.get(f"/api/notes/{nota}/versions").json()["versions"]
    assert any(v["conflict"] for v in vers)
    assert any("Escrito en B" in v for v in _versiones(api, nota))  # lo de B, en el historial
    _escribir(b, "Línea común\n\nEscrito en A, seguido en B")  # y B sigue sin 409
    assert "seguido en B" in api.get(f"/api/notes/{nota}").json()["content"]


def test_decidir_mas_tarde_no_pierde_nada(server, api, nota, dispositivo):
    a, b, dlg = _conflicto(server, nota, dispositivo, api)
    dlg.get_by_role("button", name="Decidir más tarde").click()
    expect(dlg).to_have_count(0)
    ind = b.locator("#saveIndicator")
    expect(ind).to_contain_text("Cambió en otro dispositivo")
    ind = b.locator("#saveIndicator .save-conflict-btn")
    b.locator("#noteContent").press("End")
    b.locator("#noteContent").type(" (más)")
    b.wait_for_timeout(1500)  # el autoguardado espera: no vuelve a saltar ni pisa
    expect(b.locator("dialog.conflict-modal")).to_have_count(0)
    assert "Escrito en A" in api.get(f"/api/notes/{nota}").json()["content"]
    ind.click()
    b.locator("dialog.conflict-modal").get_by_role("button", name="Quedarme con lo mío").click()
    expect(b.locator("#saveIndicator")).to_have_text("Guardado", timeout=5000)
    assert "Escrito en B (más)" in api.get(f"/api/notes/{nota}").json()["content"]


def test_treinta_guardados_seguidos_sin_409(server, api, nota, dispositivo):
    pg = dispositivo()
    conflictos = []
    pg.on("response", lambda r: r.status == 409 and conflictos.append(r.url))
    # Guardados lentos: el siguiente autoguardado llega con el anterior aún en vuelo (la cola los encadena)
    pg.route(
        f"**/api/notes/{nota}",
        lambda route: (pg.wait_for_timeout(700) if route.request.method == "POST" else None, route.continue_()),
    )
    _abrir_nota(pg, server, nota)
    ta = pg.locator("#noteContent")
    for i in range(30):
        ta.press("End")
        ta.type(f" {i}")
        pg.wait_for_timeout(1050)
    expect(pg.locator("#saveIndicator")).to_have_text("Guardado", timeout=10000)
    assert not conflictos
    assert api.get(f"/api/notes/{nota}").json()["content"].endswith(" 29")


def test_casilla_marcada_en_modo_lectura_tras_cambio_ajeno(server, api, dispositivo):
    """Con la nota abierta en lectura, otro dispositivo la cambia: marcar una casilla recoge lo nuevo, sin 409."""
    nid = "casillas-" + uuid.uuid4().hex[:6]
    api.post(
        f"/api/notes/{nid}",
        json={
            "title": "Conflicto",
            "category": "E2E",
            "status": "consolidado",
            "content": "- [ ] uno\n- [ ] dos",
            "tags": [],
        },
    )
    pg = dispositivo()
    pg.goto(f"{server}/?note={nid}")
    box = pg.locator("#readContent li > input[type=checkbox]").first
    expect(box).to_be_enabled()
    api.post(
        f"/api/notes/{nid}",
        json={
            "title": "Conflicto",
            "category": "E2E",
            "status": "consolidado",
            "content": "- [ ] uno\n- [ ] dos\n\nDe fuera",
            "tags": [],
        },
    )
    box.check()
    wait_js(pg, "() => document.querySelector('#readContent').textContent.includes('De fuera')", timeout=8000)
    md = api.get(f"/api/notes/{nid}").json()["content"]
    assert "- [x] uno" in md and "De fuera" in md
    expect(pg.locator("dialog.conflict-modal")).to_have_count(0)
    api.delete(f"/api/notes/{nid}")


def test_dialogo_en_el_movil(server, api, nota, dispositivo, tmp_path):
    a, b = dispositivo(), dispositivo(375)
    _abrir_nota(a, server, nota)
    b.goto(f"{server}/?note={nota}")
    expect(b.locator("#noteTitle")).to_have_value("Conflicto")
    b.evaluate("setMode('edit')")
    _escribir(a, "Línea común\n\nDesde el portátil")
    b.locator("#noteContent").fill("Línea común\n\nDesde el móvil")
    dlg = b.locator("dialog.conflict-modal")
    expect(dlg).to_be_visible(timeout=5000)
    for name in ("Quedarme con lo mío", "Recargar la otra", "Ver diferencias"):
        box = dlg.get_by_role("button", name=name).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 375 and box["height"] >= 40
    dlg.get_by_role("button", name="Recargar la otra").click()
    expect(b.locator("#noteContent")).to_have_value("Línea común\n\nDesde el portátil")


# ── Tableros ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tablero(api):
    bid = api.post("/api/boards", json={"name": "Conflicto E2E"}).json()["id"]
    api.post(
        f"/api/boards/{bid}/canvas",
        json={
            "data": json.dumps(
                {
                    "format": 2,
                    "nodes": [{"id": "n_base", "kind": "rect", "x": 0, "y": 0, "w": 120, "h": 60, "text": "Base"}],
                    "edges": [],
                    "strokes": [],
                }
            )
        },
    )
    yield bid
    api.delete(f"/api/boards/{bid}")


def _abrir_tablero(pg, server, bid):
    pg.add_init_script(
        f"localStorage.setItem('board-current', '{bid}'); localStorage.setItem('board-props', 'closed');"
    )
    pg.goto(server + "/inbox")
    wait_js(pg, f"() => window.__board && __board.state.boardId === {bid} && __board.state.rev !== null")


def _poner(pg, texto):
    """Añade una forma con ese texto y espera a que se guarde."""
    pg.evaluate("t => { const n = __board.insertShape('rect'); n.text = t; __board.renderAll(); }", texto)
    pg.wait_for_timeout(1000)  # el guardado sale a los 700 ms
    wait_js(pg, "() => !__board.state.dirty", timeout=5000)


def _textos(api, bid):
    return {n.get("text") for n in json.loads(api.get(f"/api/boards/{bid}").json()["data"])["nodes"]}


def _conflicto_tablero(server, bid, dispositivo, api):
    a, b = dispositivo(1600), dispositivo(1600)
    _abrir_tablero(a, server, bid)
    _abrir_tablero(b, server, bid)
    _poner(a, "De A")
    b.evaluate("() => { const n = __board.insertShape('rect'); n.text = 'De B'; __board.renderAll(); }")
    dlg = b.locator("dialog.conflict-modal")
    expect(dlg).to_be_visible(timeout=5000)
    assert _textos(api, bid) >= {"Base", "De A"} and "De B" not in _textos(api, bid)
    return a, b, dlg


def test_tablero_quedarme_con_lo_mio(server, api, tablero, dispositivo):
    a, b, dlg = _conflicto_tablero(server, tablero, dispositivo, api)
    dlg.get_by_role("button", name="Ver diferencias").click()
    expect(dlg.locator(".diff-line.diff-mine")).to_contain_text("De B")
    expect(dlg.locator(".diff-line.diff-theirs")).to_contain_text("De A")
    dlg.get_by_role("button", name="Quedarme con lo mío").click()
    wait_js(b, "() => !__board.state.conflict && !__board.state.dirty")
    assert "De B" in _textos(api, tablero)
    # Lo de A vuelve con «Deshacer último guardado»
    prev = api.post(f"/api/boards/{tablero}/canvas/undo-save").json()
    assert "De A" in prev["data"] and "De B" not in prev["data"]


def test_tablero_recargar_el_otro_y_deshacer_ultimo_guardado(server, api, tablero, dispositivo):
    a, b, dlg = _conflicto_tablero(server, tablero, dispositivo, api)
    dlg.get_by_role("button", name="Recargar el otro").click()
    wait_js(b, "() => !__board.state.conflict && __board.state.doc.nodes.some(n => n.text === 'De A')")
    assert not b.evaluate("__board.state.doc.nodes.some(n => n.text === 'De B')")
    assert "De B" not in _textos(api, tablero)
    # Lo de B quedó como copia: el menú del tablero lo trae de vuelta
    b.locator("#btnBoardMenu").click()
    b.get_by_role("menuitem", name="Deshacer último guardado").click()
    b.locator("dialog.modal").get_by_role("button", name="Deshacer guardado").click()
    wait_js(b, "() => __board.state.doc.nodes.some(n => n.text === 'De B')")
    assert "De B" in _textos(api, tablero)


def test_tablero_treinta_guardados_sin_409(server, api, tablero, dispositivo):
    pg = dispositivo(1600)
    conflictos = []
    pg.on("response", lambda r: r.status == 409 and conflictos.append(r.url))
    pg.route(f"**/api/boards/{tablero}/canvas", lambda route: (pg.wait_for_timeout(500), route.continue_()))
    _abrir_tablero(pg, server, tablero)
    for i in range(30):
        pg.evaluate("i => { const n = __board.insertShape('rect'); n.text = 'n' + i; __board.renderAll(); }", i)
        pg.wait_for_timeout(750)
    wait_js(pg, "() => !__board.state.dirty", timeout=10000)
    pg.wait_for_timeout(800)
    assert not conflictos
    assert {f"n{i}" for i in range(30)} <= _textos(api, tablero)
