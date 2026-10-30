"""
Primitivas de seguridad sin dependencias externas:

- Hash de contraseña con scrypt (stdlib). Formato: scrypt:N:r:p:salt:hash
  (sin '$' para que python-dotenv no intente interpolarlo).
- Cookie de sesión firmada con HMAC-SHA256. La clave deriva del secreto de
  sesión Y del hash de la contraseña: cambiar la contraseña invalida todas
  las sesiones abiertas.
- Token de API: se guarda solo su SHA-256 en .env.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── Contraseña ──────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{_b64e(salt)}:{_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split(":")
        if algo != "scrypt":
            return False
        expected = _b64d(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64d(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# ── Sesión ──────────────────────────────────────────────────────
def _session_key(secret: str, password_hash: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), password_hash.encode("utf-8"), hashlib.sha256).digest()


def create_session_token(secret: str, password_hash: str) -> str:
    payload = _b64e(json.dumps({"iat": int(time.time()), "n": secrets.token_hex(8)}).encode())
    sig = _b64e(hmac.new(_session_key(secret, password_hash), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_session_token(token: str, secret: str, password_hash: str, max_age_s: int) -> bool:
    if not token or "." not in token or not secret or not password_hash:
        return False
    payload, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(_session_key(secret, password_hash), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(_b64d(payload))
        return 0 <= time.time() - int(data["iat"]) <= max_age_s
    except (ValueError, KeyError, TypeError):
        return False


# ── Token de API ────────────────────────────────────────────────
def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_api_token(token: str, stored_hash: str) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_token(token), stored_hash)
