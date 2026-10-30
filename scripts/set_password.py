"""
Fija (o cambia) la contraseña del panel y, opcionalmente, un token de API.

    python -m scripts.set_password              # pide la contraseña por teclado
    python -m scripts.set_password --generate   # genera una aleatoria y la muestra una vez
    python -m scripts.set_password --api-token  # genera además un token Bearer
    python -m scripts.set_password --solo-token # solo un token nuevo (no toca la contraseña ni las sesiones)

Escribe PANEL_PASSWORD_HASH (scrypt), PANEL_SESSION_SECRET y, si se pide,
PANEL_API_TOKEN_HASH en .env. Cambiar la contraseña cierra todas las sesiones.
"""
import argparse
import getpass
import secrets
import sys

from core.config import PROJECT_ROOT
from core.security import hash_api_token, hash_password

ENV_PATH = PROJECT_ROOT / ".env"


def update_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pending = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in pending.items())
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    ENV_PATH.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--generate", action="store_true", help="genera una contraseña aleatoria")
    parser.add_argument("--api-token", action="store_true", help="genera también un token de API")
    parser.add_argument("--solo-token", action="store_true",
                        help="genera solo un token de API nuevo (p. ej. para la extensión de Firefox); el anterior deja de valer")
    args = parser.parse_args()

    if args.solo_token:
        token = secrets.token_urlsafe(32)
        update_env({"PANEL_API_TOKEN_HASH": hash_api_token(token)})
        print(f"Guardado en {ENV_PATH}. Reinicia uvicorn para aplicarlo (el token anterior deja de valer).")
        print(f"Token de API (pégalo en las opciones de la extensión; no se vuelve a mostrar): {token}")
        return 0

    if args.generate:
        password = secrets.token_urlsafe(12)
    else:
        password = getpass.getpass("Nueva contraseña del panel: ")
        if len(password) < 8:
            print("La contraseña debe tener al menos 8 caracteres.", file=sys.stderr)
            return 1
        if getpass.getpass("Repítela: ") != password:
            print("No coinciden.", file=sys.stderr)
            return 1

    values = {"PANEL_PASSWORD_HASH": hash_password(password), "PANEL_SESSION_SECRET": secrets.token_urlsafe(32)}
    token = None
    if args.api_token:
        token = secrets.token_urlsafe(32)
        values["PANEL_API_TOKEN_HASH"] = hash_api_token(token)
    update_env(values)

    print(f"Guardado en {ENV_PATH}. Reinicia uvicorn para aplicarlo.")
    if args.generate:
        print(f"Contraseña generada (apúntala, no se vuelve a mostrar): {password}")
    if token:
        print(f"Token de API (cabecera 'Authorization: Bearer ...'): {token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
