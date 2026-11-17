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

# Desde el gancho pre-commit, git pasa su repo y su índice por el entorno (con `commit -a`, GIT_INDEX_FILE es un índice
# temporal del commit). Los tests que hacen `git init` en un tmp lo heredarían y escribirían sus archivos en el índice
# del commit de verdad («invalid object … for 'docs/guia.md'»). Cada git de los tests solo debe ver su propio repo.
for _var in (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
):
    os.environ.pop(_var, None)

# Ningún test avisa en el escritorio de verdad: la terminal hereda INVOCATION_ID de la sesión de systemd (el panel lo usa
# para saber que corre como servicio) y los avisos de «el panel no arranca» de los tests salían en swaync. PANEL_NOTIFY
# lo usan el panel y los scripts del escritorio; los tests que comprueban el aviso lo cambian con monkeypatch.
os.environ.pop("INVOCATION_ID", None)
os.environ["PANEL_NOTIFY"] = "true"

os.environ.update(
    {
        # .env propio y vacío: el panel escribe en él («cerrar todas las sesiones») y nunca debe tocar el real
        "PANEL_ENV_FILE": str(TMP / ".env"),
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
    }
)
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


def pytest_configure(config):
    config.addinivalue_line("markers", "permisos_unix: usa permisos Unix (600, ejecutable); se salta en NTFS (P-12)")


def pytest_collection_modifyitems(config, items):
    """scripts/probar_ntfs.sh pasa los tests con los datos en una imagen NTFS: allí no hay permisos Unix (docs/windows.md
    §2.5) y lo que los prueba (token del escritorio, abridor, dotfiles) nunca vive en la partición compartida."""
    from app.datos_compartidos import NTFS, sistema_de_archivos

    base = config.option.basetemp or TMP
    if sistema_de_archivos(TMP) not in NTFS and sistema_de_archivos(Path(base)) not in NTFS:
        return
    salta = pytest.mark.skip(reason="NTFS no tiene permisos Unix (docs/windows.md §2.5)")
    for item in items:
        if "permisos_unix" in item.keywords:
            item.add_marker(salta)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP, ignore_errors=True)
