import tempfile

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
    assert anon.get("/healthz").json() == {"status": "ok", "app": "panel-maestro"}


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
    # S-7: GET /logout no cierra nada (una <img> en otra web no puede echarte); solo POST
    assert anon.get("/logout", follow_redirects=False).status_code == 405
    assert anon.get("/api/notes").status_code == 200
    # POST desde otra web: bloqueado aunque /logout sea pública
    assert anon.post("/logout", headers={"Origin": "http://evil.com"}, follow_redirects=False).status_code == 403
    assert anon.get("/api/notes").status_code == 200
    r = anon.post("/logout", headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert anon.get("/api/notes").status_code == 401


def test_cerrar_todas_las_sesiones_invalida_las_cookies_anteriores(app, monkeypatch):
    from fastapi.testclient import TestClient

    from core import config

    monkeypatch.setattr(config, "SESSION_GEN", config.SESSION_GEN)  # vuelve a su valor al acabar
    env_antes = config.ENV_FILE.read_text() if config.ENV_FILE.exists() else None
    assert str(config.ENV_FILE).startswith(tempfile.gettempdir())  # nunca el .env real
    with TestClient(app) as movil, TestClient(app) as portatil:
        for c in (movil, portatil):
            assert c.post("/login", data={"password": TEST_PASSWORD}, follow_redirects=False).status_code == 303
        vieja = movil.cookies.get(auth.SESSION_COOKIE)
        assert movil.get("/api/notes").status_code == 200
        r = portatil.post("/api/sesiones/cerrar-todas", headers={"Origin": "http://testserver"})
        assert r.status_code == 200 and auth.SESSION_COOKIE in r.headers["set-cookie"]
        assert movil.get("/api/notes").status_code == 401  # la cookie anterior ya no vale
        assert not auth.session_is_valid(vieja)
        assert portatil.get("/api/notes").status_code == 200  # quien las cierra sigue dentro, con cookie nueva
        assert f"PANEL_SESSION_GEN={config.SESSION_GEN}" in config.ENV_FILE.read_text()
        # el token Bearer de la extensión y del escritorio no cambia
        assert movil.get("/api/notes", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"}).status_code == 200
    if env_antes is None:
        config.ENV_FILE.unlink()
    else:
        config.ENV_FILE.write_text(env_antes)


def test_cerrar_todas_sin_sesion_ni_desde_otra_web(anon, client):
    assert anon.post("/api/sesiones/cerrar-todas").status_code == 401
    assert client.post("/api/sesiones/cerrar-todas", headers={"Origin": "http://evil.com"}).status_code == 403


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


def test_healthz_con_una_bd_inaccesible_da_503(anon, monkeypatch, tmp_path):
    from core import config

    monkeypatch.setattr(config, "COMIDAS_DB", tmp_path / "no-existe" / "comidas.db")
    r = anon.get("/healthz")
    assert r.status_code == 503 and r.json() == {"status": "error", "app": "panel-maestro"}  # no dice cuál ni por qué
    monkeypatch.undo()
    assert anon.get("/healthz").status_code == 200


def test_la_extension_cambia_su_token_por_una_sesion(app, monkeypatch):
    """S-4: POST /api/ext/sesion con el token de la extensión devuelve la cookie (ya no hace falta la contraseña)."""
    from fastapi.testclient import TestClient

    from core import config
    from core.security import hash_api_token

    monkeypatch.setattr(config, "DESKTOP_TOKEN_HASH", hash_api_token("token-del-escritorio"))
    with TestClient(app) as c:
        assert c.post("/api/ext/sesion").status_code == 401  # sin token
        r = c.post("/api/ext/sesion", headers={"Authorization": "Bearer token-del-escritorio"})
        assert r.status_code == 403  # el del escritorio no
        r = c.post("/api/ext/sesion", headers={"Authorization": f"Bearer {TEST_API_TOKEN}"})
        assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
        assert c.get("/api/notes").status_code == 200  # ya con la cookie
    with TestClient(app) as c:  # una sesión abierta con la cookie no puede pedir otra (hace falta el token)
        c.post("/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        assert c.post("/api/ext/sesion", headers={"Origin": "http://testserver"}).status_code == 403
