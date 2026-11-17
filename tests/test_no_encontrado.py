"""Página 404: el navegador ve una página del panel; la API, los estáticos y fetch siguen recibiendo JSON."""

import pytest

HTML = {"accept": "text/html,application/xhtml+xml"}


@pytest.mark.parametrize("ruta", ["/no-existe", "/comidas/no-existe", "/estudio/no-existe"])
def test_navegacion_a_una_ruta_que_no_existe(client, ruta):
    r = client.get(ruta, headers=HTML)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "Esta página no existe" in r.text and ruta in r.text and 'href="/hoy"' in r.text


def test_el_motivo_del_404_se_ve_y_la_ruta_va_escapada(client):
    r = client.get("/ayuda/nada", headers=HTML)
    assert r.status_code == 404 and "No hay esa guía" in r.text
    r = client.get("/no-existe/<b>x</b>", headers=HTML)
    assert r.status_code == 404 and "<b>x</b>" not in r.text and "&lt;b&gt;" in r.text


@pytest.mark.parametrize("ruta", ["/api/nada", "/comidas/api/nada", "/static/nada.js", "/api/notes/no-existe"])
def test_api_y_estaticos_siguen_en_json(client, ruta):
    r = client.get(ruta, headers=HTML)
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_fetch_sin_html_recibe_json(client):
    r = client.get("/no-existe", headers={"accept": "application/json"})
    assert r.status_code == 404 and r.json()["error"]


def test_sin_sesion_la_404_no_se_ve_antes_del_login(anon):
    r = anon.get("/no-existe", headers=HTML, follow_redirects=False)
    assert r.status_code in (302, 303, 307) and "/login" in r.headers["location"]
