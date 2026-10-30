"""
Genera el token de los scripts del escritorio (captura rápida con rofi y módulo de la Waybar).

    python -m scripts.desktop_token            # token nuevo: hash en .env, token en ~/.config/panel-maestro/token (600)
    python -m scripts.desktop_token --url http://127.0.0.1:8000

El token nunca entra en el repositorio: solo su hash (PANEL_DESKTOP_TOKEN_HASH, en .env). Es
independiente del de la extensión (PANEL_API_TOKEN_HASH). Hay que reiniciar el panel para que lo lea.
"""
import argparse
import os
import secrets
import shutil
import time
from pathlib import Path

from core.security import hash_api_token
from scripts.set_password import ENV_PATH, update_env

CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "panel-maestro"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=None, help="dirección del panel (por defecto http://127.0.0.1:8000)")
    args = ap.parse_args()
    token = secrets.token_urlsafe(32)
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, ENV_PATH.with_name(f".env.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    update_env({"PANEL_DESKTOP_TOKEN_HASH": hash_api_token(token)})
    CONF.mkdir(parents=True, exist_ok=True)
    os.chmod(CONF, 0o700)
    path = CONF / "token"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)
    if args.url:
        (CONF / "url").write_text(args.url.rstrip("/") + "\n")
    print(f"Token guardado en {path} (permisos 600). Reinicia el panel: systemctl --user restart panel-maestro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
