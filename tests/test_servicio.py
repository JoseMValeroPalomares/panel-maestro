"""S-5: una sola plantilla de la unidad de systemd (la que instala install.sh --service) y start.sh configurable."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLANTILLA = ROOT / "scripts" / "systemd" / "panel-maestro.service"


def _servicio() -> dict[str, str]:
    seccion, out = None, {}
    for linea in PLANTILLA.read_text(encoding="utf-8").splitlines():
        if linea.startswith("["):
            seccion = linea
        elif seccion == "[Service]" and "=" in linea and not linea.startswith("#"):
            k, v = linea.split("=", 1)
            out[k] = v
    return out


def test_plantilla_con_las_protecciones_probadas():
    s = _servicio()
    assert s["ExecStart"] == "@PANEL_DIR@/start.sh" and s["WorkingDirectory"] == "@PANEL_DIR@"
    assert s["UMask"] == "0077" and s["NoNewPrivileges"] == "yes"
    # En un servicio de usuario activan PrivateUsers y rompen ssh (subida de dotfiles): ver docs/servicio.md
    for fuera in (
        "PrivateTmp",
        "ProtectSystem",
        "ProtectHome",
        "ProtectKernelTunables",
        "PrivateDevices",
        "MemoryDenyWriteExecute",
        "CapabilityBoundingSet",
        "PrivateUsers",
        "RestrictNamespaces",
    ):
        assert fuera not in s, fuera
    texto = PLANTILLA.read_text(encoding="utf-8")
    assert "After=network-online.target" in texto


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="sin systemd")
def test_plantilla_valida_para_systemd(tmp_path):
    unidad = tmp_path / "panel-maestro.service"
    unidad.write_text(PLANTILLA.read_text(encoding="utf-8").replace("@PANEL_DIR@", str(ROOT)))
    r = subprocess.run(["systemd-analyze", "--user", "verify", str(unidad)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_install_usa_la_plantilla():
    texto = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "scripts/systemd/panel-maestro.service" in texto
    assert "<<UNIT" not in texto  # ya no genera otra unidad distinta


def _start_dry(tmp_path, env_text, **env):
    """Ejecuta start.sh con un uvicorn falso que imprime sus argumentos."""
    raiz = tmp_path / "panel"
    (raiz / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "start.sh", raiz / "start.sh")
    falso = raiz / "venv" / "bin" / "uvicorn"
    falso.write_text('#!/bin/sh\necho "$@"\n')
    falso.chmod(0o755)
    (raiz / ".env").write_text(env_text)
    limpio = {
        k: v
        for k, v in os.environ.items()
        if k not in ("HOST", "PORT", "SSL_CERT", "SSL_KEY", "PANEL_ENV_FILE") and not k.startswith("PANEL_")
    }
    r = subprocess.run(["bash", str(raiz / "start.sh")], capture_output=True, text=True, env={**limpio, **env})
    return r


def test_start_lee_host_puerto_y_certificado_del_env(tmp_path):
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("x")
    r = _start_dry(
        tmp_path, f"PANEL_HOST=127.0.0.1\nPANEL_PORT='8443'\nPANEL_SSL_CERT=\"{cert}\"\nPANEL_SSL_KEY={key}\n"
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout.split()
    assert out[out.index("--host") + 1] == "127.0.0.1" and out[out.index("--port") + 1] == "8443"
    assert out[out.index("--ssl-certfile") + 1] == str(cert) and "--proxy-headers" in out
    assert out[out.index("--forwarded-allow-ips") + 1] == "127.0.0.1"
    # el entorno manda sobre el .env (lo que ya hacían HOST=… ./start.sh)
    r = _start_dry(tmp_path, "PANEL_HOST=127.0.0.1\n", HOST="0.0.0.0", PORT="9000")
    out = r.stdout.split()
    assert out[out.index("--host") + 1] == "0.0.0.0" and out[out.index("--port") + 1] == "9000"


def test_start_sin_nada_escucha_en_la_red_y_sin_tls(tmp_path):
    r = _start_dry(tmp_path, "# vacío\n")
    out = r.stdout.split()
    assert out[out.index("--host") + 1] == "0.0.0.0" and out[out.index("--port") + 1] == "8000"
    assert "--ssl-certfile" not in out


def test_start_certificado_ilegible_no_arranca(tmp_path):
    r = _start_dry(tmp_path, "PANEL_SSL_CERT=/no/existe.pem\nPANEL_SSL_KEY=/no/existe.pem\n")
    assert r.returncode == 1 and "PANEL_SSL_CERT" in r.stderr
