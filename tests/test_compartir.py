"""F-2: «Compartir» desde el móvil (share_target de la PWA) → /compartir con la captura rellena."""

from urllib.parse import parse_qs, quote, urlsplit

from tests.conftest import TEST_PASSWORD


def test_manifest_declara_share_target(client):
    m = client.get("/manifest.webmanifest").json()
    st = m["share_target"]
    assert st["action"] == "/compartir" and st["method"] == "GET"
    assert st["params"] == {"title": "title", "text": "text", "url": "url"}
    # la acción queda dentro del alcance de la PWA (si no, Android no la ofrece)
    assert st["action"].startswith(m["scope"])


def test_pagina_compartir(client):
    r = client.get("/compartir", params={"title": "Hola", "text": "Un texto", "url": "https://example.org"})
    assert r.status_code == 200
    assert "compartir.js" in r.text and 'id="shareLinkModal"' in r.text and 'id="captureModal"' in r.text


def test_sin_sesion_el_login_vuelve_con_los_datos(anon):
    qs = "title=Receta&text=Comprar%20lentejas%20y%20%C3%B1oras&url=https%3A%2F%2Fexample.org%2Fa%3Fb%3D1%26c%3D2"
    r = anon.get(f"/compartir?{qs}", follow_redirects=False)
    assert r.status_code == 303
    nxt = parse_qs(urlsplit(r.headers["location"]).query)["next"][0]
    assert nxt == f"/compartir?{qs}"
    # el formulario de login lleva ese next y, al entrar, se vuelve a /compartir con todo
    page = anon.get(r.headers["location"]).text
    assert "/compartir?" in page
    r = anon.post("/login", data={"password": TEST_PASSWORD, "next": nxt}, follow_redirects=False)
    assert r.status_code == 303
    back = urlsplit(r.headers["location"])
    assert back.path == "/compartir"
    got = parse_qs(back.query)
    assert got["text"] == ["Comprar lentejas y ñoras"] and got["url"] == ["https://example.org/a?b=1&c=2"]
    assert quote("ñ") in r.headers["location"] or "ñ" in r.headers["location"]


def test_guia_del_movil(client):
    r = client.get("/ayuda/movil")
    assert r.status_code == 200 and "iOS" in r.text
