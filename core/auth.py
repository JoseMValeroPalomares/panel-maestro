"""
Autenticación del panel.

- Navegador: contraseña -> cookie de sesión firmada (HttpOnly, SameSite=Lax).
- Scripts / atajos: cabecera `Authorization: Bearer <token>` (o `X-API-Token`).
- Funciona desde cualquier equipo de la red local (no se limita a 127.0.0.1).

El middleware es ASGI puro y se instala en la app RAÍZ, así que protege
también las sub-apps montadas (/estudio, /comidas).
"""
import time
from collections import defaultdict, deque
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core import config
from core.logging_config import get_logger
from core.security import create_session_token, verify_api_token, verify_password, verify_session_token

log = get_logger("auth")

SESSION_COOKIE = "panel_session"

# Rutas accesibles sin sesión: login, recursos estáticos sin datos personales y PWA.
PUBLIC_EXACT = {"/login", "/logout", "/healthz", "/sw.js", "/manifest.webmanifest", "/favicon.ico",
                "/static/manifest.json"}
PUBLIC_PREFIXES = ("/static/css/", "/static/js/", "/static/vendor/", "/static/icons/", "/static/fonts/")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Límite de intentos de login por IP (memoria del proceso).
LOGIN_MAX_FAILS = 8
LOGIN_WINDOW_S = 15 * 60
_failed_logins: dict[str, deque] = defaultdict(deque)

templates = Jinja2Templates(directory=str(config.PROJECT_ROOT / "templates"))
templates.env.globals["asset"] = __import__("core.templating", fromlist=["asset"]).asset
router = APIRouter()


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def _wants_json(path: str, headers: dict) -> bool:
    accept = headers.get("accept", "")
    return "/api/" in path or path.endswith("/config") or ("application/json" in accept and "text/html" not in accept)


def _safe_next(target: str | None) -> str:
    """Evita open redirects: solo rutas relativas del propio panel."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def _cookie_from_header(raw_cookie: str) -> str | None:
    for part in raw_cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE:
            return value
    return None


def session_is_valid(token: str | None) -> bool:
    return verify_session_token(
        token or "", config.SESSION_SECRET, config.PASSWORD_HASH, config.SESSION_DAYS * 86400
    )


def _bearer_is_valid(headers: dict) -> bool:
    auth = headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else headers.get("x-api-token", "").strip()
    return bool(token) and any(verify_api_token(token, h) for h in (config.API_TOKEN_HASH, config.DESKTOP_TOKEN_HASH) if h)


def _origin_matches_host(headers: dict) -> bool:
    """Defensa CSRF extra para peticiones con cookie: si el navegador manda
    Origin/Referer, debe coincidir con el Host al que se habla."""
    host = headers.get("host", "")
    source = headers.get("origin") or headers.get("referer")
    if not source or source == "null":
        return source != "null"
    return urlsplit(source).netloc == host


def auth_configured() -> bool:
    return bool(config.PASSWORD_HASH and config.SESSION_SECRET)


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or config.AUTH_DISABLED:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

        if is_public_path(path):
            return await self.app(scope, receive, send)

        if _bearer_is_valid(headers):
            scope.setdefault("state", {})["auth"] = "token"
            return await self.app(scope, receive, send)

        if not auth_configured():
            response = JSONResponse(
                status_code=503,
                content={"error": "Panel sin contraseña configurada. Ejecuta: python -m scripts.set_password"},
            )
            return await response(scope, receive, send)

        if session_is_valid(_cookie_from_header(headers.get("cookie", ""))):
            if scope.get("method") in UNSAFE_METHODS and not _origin_matches_host(headers):
                log.warning("Petición %s %s bloqueada por Origin distinto", scope.get("method"), path)
                response = JSONResponse(status_code=403, content={"error": "Origen no permitido"})
                return await response(scope, receive, send)
            scope.setdefault("state", {})["auth"] = "session"
            return await self.app(scope, receive, send)

        if _wants_json(path, headers):
            response = JSONResponse(status_code=401, content={"error": "No autenticado"})
        else:
            full = path + ("?" + scope["query_string"].decode() if scope.get("query_string") else "")
            response = RedirectResponse(f"/login?next={quote(full)}", status_code=303)
        return await response(scope, receive, send)


# ── Rutas de login ──────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _too_many_attempts(ip: str) -> bool:
    attempts = _failed_logins[ip]
    now = time.time()
    while attempts and now - attempts[0] > LOGIN_WINDOW_S:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_FAILS


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if session_is_valid(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html",
        context={"next": _safe_next(next), "error": None, "configured": auth_configured()},
    )


@router.post("/login")
def login_submit(request: Request, password: str = Form(..., max_length=512), next: str = Form("/")):
    ip = _client_ip(request)
    target = _safe_next(next)
    if _too_many_attempts(ip):
        log.warning("Login bloqueado temporalmente para %s", ip)
        return templates.TemplateResponse(
            request=request, name="login.html", status_code=429,
            context={"next": target, "configured": True,
                     "error": "Demasiados intentos. Espera unos minutos."},
        )
    if not auth_configured() or not verify_password(password, config.PASSWORD_HASH):
        _failed_logins[ip].append(time.time())
        log.warning("Login fallido desde %s", ip)
        # 200 y no 401: es la re-presentación del formulario con su error (el navegador
        # registraría un 401 como error de consola).
        return templates.TemplateResponse(
            request=request, name="login.html", status_code=200,
            context={"next": target, "configured": auth_configured(), "error": "Contraseña incorrecta."},
        )

    _failed_logins.pop(ip, None)
    log.info("Login correcto desde %s", ip)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE, create_session_token(config.SESSION_SECRET, config.PASSWORD_HASH),
        max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=config.COOKIE_SECURE, path="/",
    )
    return response


@router.api_route("/logout", methods=["GET", "POST"])
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/healthz")
def healthz():
    return {"status": "ok"}
