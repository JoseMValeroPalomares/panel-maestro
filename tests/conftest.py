"""
Configuración de tests: TODO apunta a un directorio temporal antes de importar
la app (core.config lee las variables de entorno al importarse), así que los
tests nunca tocan las notas ni las BDs reales.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.security import hash_api_token, hash_password  # noqa: E402  (no importa config)

TEST_PASSWORD = "test-password-123"
TEST_API_TOKEN = "token-de-prueba-abc"
TMP = Path(tempfile.mkdtemp(prefix="panel-tests-"))

os.environ.update({
    "PANEL_DATA_DIR": str(TMP / "data"),
    "PANEL_NOTES_DIR": str(TMP / "data" / "notes"),
    "PANEL_BRAIN_DB": str(TMP / "data" / "brain.db"),
    "PANEL_COMIDAS_DB": str(TMP / "comidas.db"),
    "PANEL_UPLOADS_DIR": str(TMP / "uploads"),
    "PANEL_BACKUPS_DIR": str(TMP / "backups"),
    "PANEL_LOGS_DIR": str(TMP / "logs"),
    "PANEL_TRASH_DIR": str(TMP / "data" / "trash"),
    "PANEL_DOTFILES_DIR": str(TMP / "dotfiles"),
    "PANEL_DOTFILES_HOME": str(TMP / "home"),
    "PANEL_PROJECT_DIR": str(TMP / "proyecto"),
    "PANEL_PASSWORD_HASH": hash_password(TEST_PASSWORD),
    "PANEL_SESSION_SECRET": "secreto-de-sesion-para-tests",
    "PANEL_API_TOKEN_HASH": hash_api_token(TEST_API_TOKEN),
    "PANEL_DISABLE_BRIDGES": "1",
    "PANEL_DISABLE_SCHEDULER": "1",
    "PANEL_AUTH_DISABLED": "0",
    "PANEL_LOG_LEVEL": "WARNING",
})
(TMP / "data" / "notes").mkdir(parents=True, exist_ok=True)
(TMP / "data" / "notes" / "nota-inicial.md").write_text(
    "---\ncategory: Pruebas - Base\nstatus: consolidado\ntags:\n- demo\ntitle: Nota inicial\n---\n\n# Nota inicial\n\nTexto de ejemplo.\n",
    encoding="utf-8",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return main.app


@pytest.fixture(scope="session")
def client(app):
    """Cliente autenticado con sesión de navegador (lifespan activo)."""
    with TestClient(app) as c:
        r = c.post("/login", data={"password": TEST_PASSWORD, "next": "/"}, follow_redirects=False)
        assert r.status_code == 303, r.text
        yield c


@pytest.fixture()
def anon(app):
    """Cliente sin sesión."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def tmp_root():
    return TMP


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)
