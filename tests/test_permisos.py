"""S-6: lo que crea el panel solo lo lee su usuario (umask 077 en main.py; atomic_write la respeta)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.files import _umask, atomic_write

# P-12: permisos Unix (600, ejecutables): en NTFS no existen y conftest lo salta allí
pytestmark = pytest.mark.permisos_unix

ROOT = Path(__file__).resolve().parent.parent


def test_main_pone_umask_077_antes_de_importar_nada(tmp_path):
    texto = (ROOT / "main.py").read_text(encoding="utf-8")
    assert texto.index("os.umask(0o077)") < texto.index("from core")
    code = "import main, core.files as f; print(oct(f._umask()))"
    env = {
        **os.environ,
        "PANEL_DATA_DIR": str(tmp_path / "d"),
        "PANEL_LOGS_DIR": str(tmp_path / "l"),
        "PANEL_DISABLE_BRIDGES": "1",
        "PANEL_DISABLE_SCHEDULER": "1",
    }
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip().endswith("0o77")


def test_atomic_write_nuevo_respeta_la_umask_y_conserva_el_de_uno_existente(tmp_path):
    vieja = os.umask(0o077)
    try:
        assert _umask() == 0o077
        nuevo = tmp_path / "n.md"
        atomic_write(nuevo, "hola")
        assert nuevo.stat().st_mode & 0o777 == 0o600
        existente = tmp_path / "e.md"
        existente.write_text("x")
        existente.chmod(0o640)
        atomic_write(existente, "y")
        assert existente.stat().st_mode & 0o777 == 0o640
    finally:
        os.umask(vieja)


def test_install_quita_permisos_de_grupo_y_otros():
    texto = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'chmod -R go-rwx "$d"' in texto
    for d in ("data", "comidas/data", "backups", "logs", "static/uploads"):
        assert d in texto
