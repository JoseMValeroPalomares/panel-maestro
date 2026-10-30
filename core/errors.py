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


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Error"
        return JSONResponse(status_code=exc.status_code, content={"error": detail, "detail": exc.detail},
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errores = _field_errors(exc)
        log.info("Validación fallida en %s %s: %s", request.method, request.url.path, errores)
        return JSONResponse(status_code=422, content={"error": "Datos no válidos", "detail": errores})

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


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad a todas las respuestas (incluidas las sub-apps)."""

    def __init__(self, app, csp: str | None = None):
        self.app = app
        self.csp = csp.encode() if csp else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in SECURITY_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if self.csp and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", self.csp))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
