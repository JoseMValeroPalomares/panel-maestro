"""Notas: de una nota abierta se vuelve siempre a la vista general (botón, Atrás del navegador y menú lateral)."""
import json

import pytest
from playwright.sync_api import expect

PORTADA = "#notesHome .nh-title-main"


@pytest.fixture()
def notas(api):
    for slug, titulo in (("portada-uno", "Portada uno"), ("portada-dos", "Portada dos")):
        api.post(f"/api/notes/{slug}", json={"title": titulo, "category": "Portada", "status": "en-desarrollo", "content": "Texto", "tags": []})
    yield
    for slug in ("portada-uno", "portada-dos"):
        api.delete(f"/api/notes/{slug}")


def _abrir_desde_portada(page, server, titulo="Portada uno"):
    page.goto(server + "/")
    page.locator(PORTADA).wait_for()
    page.locator("#notesList a, #notesList [data-note-id]", has_text=titulo).first.click()
    expect(page.locator("#noteTitle")).to_have_value(titulo)


def test_el_boton_notas_vuelve_a_la_portada(page, server, api, notas):
    _abrir_desde_portada(page, server)
    assert "note=portada-uno" in page.url
    page.get_by_role("button", name="Notas", exact=True).click()
    page.locator(PORTADA).wait_for()
    assert page.locator("#editorArea").is_hidden() and "note=" not in page.url
    assert not page.evaluate("document.body.classList.contains('note-open')")


def test_entrar_en_notas_abre_la_portada_y_no_la_ultima(page, server, api, notas):
    _abrir_desde_portada(page, server)
    page.goto(server + "/hoy")
    page.get_by_role("link", name="Notas").first.click()
    page.locator(PORTADA).wait_for()
    assert page.locator("#editorArea").is_hidden()
    page.reload()
    page.locator(PORTADA).wait_for()
    # una nota sigue teniendo su enlace directo, y sin venir de la portada el botón también vuelve
    page.goto(server + "/?note=portada-dos")
    expect(page.locator("#noteTitle")).to_have_value("Portada dos")
    page.get_by_role("button", name="Notas", exact=True).click()
    page.locator(PORTADA).wait_for()
    assert "note=" not in page.url


def test_atras_del_navegador_vuelve_a_la_portada(page, server, api, notas):
    _abrir_desde_portada(page, server)
    page.locator("#notesList a, #notesList [data-note-id]", has_text="Portada dos").first.click()
    expect(page.locator("#noteTitle")).to_have_value("Portada dos")
    page.go_back()  # de nota a nota no hay paradas intermedias: Atrás es la portada
    page.locator(PORTADA).wait_for()
    assert page.locator("#editorArea").is_hidden()
    page.go_forward()
    expect(page.locator("#noteTitle")).to_have_value("Portada dos")
    assert page.locator("#editorArea").is_visible()


def test_lo_escrito_se_guarda_al_volver(page, server, api, notas):
    _abrir_desde_portada(page, server)
    page.locator("#noteContent").fill("Texto nuevo sin esperar al autoguardado")
    page.get_by_role("button", name="Notas", exact=True).click()
    page.locator(PORTADA).wait_for()
    assert "sin esperar" in api.get("/api/notes/portada-uno").json()["content"]


def test_si_no_se_puede_guardar_la_nota_sigue_abierta(page, server, api, notas):
    _abrir_desde_portada(page, server)
    page.route("**/api/notes/portada-uno", lambda r: r.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "no"}))
               if r.request.method == "POST" else r.continue_())
    page.locator("#noteContent").fill("Esto no se puede perder")
    page.get_by_role("button", name="Notas", exact=True).click()
    page.locator(".toast", has_text="sigue abierta").wait_for()
    assert page.locator("#editorArea").is_visible() and page.input_value("#noteContent") == "Esto no se puede perder"
    page.unroute("**/api/notes/portada-uno")
    page.get_by_role("button", name="Notas", exact=True).click()
    page.locator(PORTADA).wait_for()
    assert "no se puede perder" in api.get("/api/notes/portada-uno").json()["content"]


def test_en_el_movil_vuelve_a_la_lista(page, server, api, notas):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(server + "/")
    page.locator("#notesList a, #notesList [data-note-id]", has_text="Portada uno").first.click()
    expect(page.locator("#noteTitle")).to_have_value("Portada uno")
    assert page.locator("#searchInput").is_hidden()
    page.go_back()
    expect(page.locator("#searchInput")).to_be_visible()
    page.locator("#notesList a, #notesList [data-note-id]", has_text="Portada uno").first.click()
    expect(page.locator("#noteTitle")).to_have_value("Portada uno")
    page.get_by_role("button", name="Notas", exact=True).click()
    expect(page.locator("#searchInput")).to_be_visible()
    page.set_viewport_size({"width": 1280, "height": 900})


def test_un_guardado_fallido_se_reintenta_solo(page, server, api, notas):
    _abrir_desde_portada(page, server)
    fallos = []

    def falla(route):
        if route.request.method != "POST":
            return route.continue_()
        fallos.append(1)
        route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "no"}))
    page.route("**/api/notes/portada-uno", falla)
    page.locator("#noteContent").fill("Vuelve la conexión")
    page.wait_for_timeout(1400)
    assert fallos
    page.unroute("**/api/notes/portada-uno")
    page.wait_for_timeout(5400)
    assert "Vuelve la conexión" in api.get("/api/notes/portada-uno").json()["content"]
