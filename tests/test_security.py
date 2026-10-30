import time

from core import security
from tests.conftest import TEST_API_TOKEN, TEST_PASSWORD


def test_hash_y_verificacion_de_contrasena():
    h = security.hash_password("una-clave-larga")
    assert h.startswith("scrypt:") and "$" not in h
    assert security.verify_password("una-clave-larga", h)
    assert not security.verify_password("otra", h)
    assert not security.verify_password("x", "basura")


def test_token_de_sesion_firmado_y_caduca(monkeypatch):
    tok = security.create_session_token("s", "hash")
    assert security.verify_session_token(tok, "s", "hash", 60)
    assert not security.verify_session_token(tok + "x", "s", "hash", 60)
    assert not security.verify_session_token(tok, "otro-secreto", "hash", 60)
    # cambiar la contraseña (hash) invalida la sesión
    assert not security.verify_session_token(tok, "s", "hash-nuevo", 60)
    real_time = time.time
    monkeypatch.setattr(security.time, "time", lambda: real_time() + 120)
    assert not security.verify_session_token(tok, "s", "hash", 60)


def test_token_api():
    h = security.hash_api_token("abc")
    assert security.verify_api_token("abc", h)
    assert not security.verify_api_token("abd", h)
    assert not security.verify_api_token("", h)
