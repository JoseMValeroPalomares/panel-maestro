from core import auth
from tests.conftest import TEST_API_TOKEN, TEST_PASSWORD


def test_api_sin_sesion_devuelve_401(anon):
    assert anon.get("/api/notes").status_code == 401
    assert anon.get("/comidas/api/profile").status_code == 401
    assert anon.get("/estudio/config").status_code == 401


def test_pagina_sin_sesion_redirige_a_login(anon):
    r = anon.get("/inbox?x=1", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=/inbox")
    assert anon.get("/comidas/", follow_redirects=False).status_code == 303


def test_recursos_publicos(anon):
    assert anon.get("/login").status_code == 200
    assert anon.get("/static/css/login.css").status_code == 200
    assert anon.get("/healthz").json() == {"status": "ok"}


def test_uploads_no_son_publicos(anon):
    assert anon.get("/static/uploads/x.png", follow_redirects=False).status_code == 303


def test_login_incorrecto(anon):
    r = anon.post("/login", data={"password": "mala"}, follow_redirects=False)
    assert r.status_code == 200 and "set-cookie" not in r.headers
    assert "Contraseña incorrecta" in r.text
    assert anon.get("/api/notes").status_code == 401


def test_login_correcto_y_logout(anon):
    r = anon.post("/login", data={"password": TEST_PASSWORD, "next": "/vault"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/vault"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert anon.get("/api/notes").status_code == 200
    anon.get("/logout")
    assert anon.get("/api/notes").status_code == 401


def test_next_no_permite_redireccion_externa(anon):
    r = anon.post("/login", data={"password": TEST_PASSWORD, "next": "//evil.com"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    assert auth._safe_next("https://evil.com") == "/"
    assert auth._safe_next("/comidas/") == "/comidas/"


def test_token_bearer(anon):
    r = anon.get("/api/notes", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"})
    assert r.status_code == 200
    assert anon.get("/api/notes", headers={"Authorization": "Bearer malo"}).status_code == 401
    assert anon.get("/comidas/api/profile", headers={"X-API-Token": TEST_API_TOKEN}).status_code == 200


def test_csrf_origen_distinto_bloqueado(client):
    r = client.post("/api/inbox", json={"content": "x"}, headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    r = client.post("/api/inbox", json={"content": "desde el panel"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_limite_de_intentos(anon, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_MAX_FAILS", 3)
    auth._failed_logins.clear()
    for _ in range(3):
        anon.post("/login", data={"password": "mala"})
    r = anon.post("/login", data={"password": TEST_PASSWORD})
    assert r.status_code == 429
    auth._failed_logins.clear()


def test_cabeceras_de_seguridad(anon):
    r = anon.get("/login")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_pwa_publica(anon):
    sw = anon.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert "__VERSION__" not in sw.text and "/static/css/ds.css" in sw.text
    assert sw.headers["service-worker-allowed"] == "/"
    man = anon.get("/manifest.webmanifest").json()
    assert man["display"] == "standalone" and any(i["purpose"] == "maskable" for i in man["icons"])
    assert anon.get("/static/icons/icon-192.png").status_code == 200
