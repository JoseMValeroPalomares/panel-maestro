"""Manejadores de errores globales y cabeceras de seguridad comunes a las tres apps."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.logging_config import get_logger

log = get_logger("errors")


def _field_errors(exc: RequestValidationError) -> list[dict]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        out.append({"campo": loc, "mensaje": err.get("msg", "")})
    return out


def _wants_page(request: Request) -> bool:
    """Una navegación del navegador (no la API, ni un estático, ni fetch pidiendo JSON)."""
    path = request.url.path
    if request.method not in ("GET", "HEAD") or "/api/" in path or "/static/" in path:
        return False
    return "text/html" in request.headers.get("accept", "")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Error"
        if exc.status_code == 404 and _wants_page(request):
            from core.templating import render  # aquí: core.templating importa config y temas, que no hacen falta antes

            mensaje = "" if detail in ("Not Found", "No encontrado") else detail
            resp = render(request, "404.html", "", "Página no encontrada", mensaje=mensaje, ruta=request.url.path)
            resp.status_code = 404
            return resp
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail, "detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errores = _field_errors(exc)
        log.info("Validación fallida en %s %s: %s", request.method, request.url.path, errores)
        return JSONResponse(status_code=422, content={"error": "Datos no válidos", "detail": errores})

    @app.exception_handler(OverflowError)
    async def number_out_of_range(request: Request, exc: OverflowError):  # un id más grande de lo que cabe en SQLite
        return JSONResponse(status_code=422, content={"error": "Número fuera de rango"})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        log.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"error": "Error interno del servidor"})


def not_found(msg: str = "No encontrado") -> HTTPException:
    return HTTPException(status_code=404, detail=msg)


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


# 180 días; sin includeSubDomains (un nombre *.ts.net o panel.local no manda sobre otros)
HSTS = b"max-age=15552000"


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad a todas las respuestas (incluidas las sub-apps)."""

    def __init__(self, app, csp: str | None = None):
        self.app = app
        self.csp = csp.encode() if csp else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # ?v=<hash del contenido> (core/templating.asset): esa URL nunca cambia de contenido, no hace falta revalidarla
        versioned = scope.get("query_string", b"").startswith(b"v=")
        # S-1: HSTS solo si la petición llegó por HTTPS (uvicorn con certificado, o tailscale serve con
        # X-Forwarded-Proto desde 127.0.0.1: start.sh usa --proxy-headers). Por HTTP no: el navegador la ignoraría
        # y, en un equipo sin certificado, dejaría el panel inaccesible.
        https = scope.get("scheme") == "https"

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in SECURITY_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if self.csp and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", self.csp))
                if https and b"strict-transport-security" not in present:
                    headers.append((b"strict-transport-security", HSTS))
                if versioned and message["status"] == 200 and b"cache-control" not in present:
                    headers.append((b"cache-control", b"private, max-age=31536000, immutable"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class HttpsRedirectMiddleware:
    """HTTP → HTTPS para lo que llega por la tailnet (`tailscale serve --http=80`, docs/HTTPS.md).

    Lo que manda tailscale serve (ipn/ipnlocal/serve.go): X-Forwarded-Host con el nombre pedido y X-Forwarded-For
    siempre, y X-Forwarded-Proto SOLO si la conexión era TLS («https»). Así que por el puerto 80 llega sin
    X-Forwarded-Proto y uvicorn deja scope["scheme"] en «http». Se redirige si el nombre es de la tailnet:
    - `equipo.tailnet.ts.net` → la misma dirección en https;
    - el nombre corto de MagicDNS (`equipo`) → el nombre completo, que es el que tiene certificado.
    El acceso local por http://127.0.0.1:8000 (scripts del escritorio, Waybar, la extensión en este equipo) sigue igual;
    quien falsee las cabeceras desde este equipo (el panel solo escucha en 127.0.0.1) solo consigue que le manden a https.
    308 y no 301: conserva el método y el cuerpo (un POST de la extensión no se convierte en GET)."""

    def __init__(self, app):
        self.app = app

    async def _destino(self, headers: dict[bytes, bytes]) -> str | None:
        proto = headers.get(b"x-forwarded-proto", b"").split(b",")[0].strip().lower()
        if proto not in (b"", b"http"):
            return None
        reenviado = headers.get(b"x-forwarded-host", b"").split(b",")[0].strip().decode("latin-1")
        host = reenviado or headers.get(b"host", b"").decode("latin-1")
        nombre = (host.rsplit(":", 1)[0] if host.count(":") == 1 else host).strip().lower()
        if nombre.endswith(".ts.net"):
            return nombre
        if reenviado and nombre and "." not in nombre and ":" not in nombre and nombre != "localhost":
            import asyncio

            from core import red  # aquí: core.red importa config y mdns, que no hacen falta para nada más

            completo = str((await asyncio.to_thread(red._tailscale)).get("nombre") or "").lower()
            if completo.split(".")[0] == nombre and completo.endswith(".ts.net"):
                return completo
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("scheme") != "http":
            return await self.app(scope, receive, send)
        destino = await self._destino({k.lower(): v for k, v in scope.get("headers", [])})
        if not destino:
            return await self.app(scope, receive, send)
        path = scope.get("raw_path") or scope.get("path", "/").encode()
        query = scope.get("query_string", b"")
        location = b"https://" + destino.encode("latin-1") + path + (b"?" + query if query else b"")
        await send(
            {
                "type": "http.response.start",
                "status": 308,
                "headers": [(b"location", location), (b"content-length", b"0"), (b"cache-control", b"no-store")],
            }
        )
        await send({"type": "http.response.body", "body": b""})
