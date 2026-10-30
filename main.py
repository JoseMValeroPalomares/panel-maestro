"""
Punto de entrada UNICO para las tres apps del panel personal.

- Cerebro Digital (PKM)               -> raiz "/"
- Panel ESP32 (Estudio/Spotify/Reloj) -> "/estudio"
- Comidas (macros/recetas/compra)     -> "/comidas"

Arranque (desde ~/Documents/panel-maestro/):
    uvicorn main:app --host 0.0.0.0 --port 8000

IMPORTANTE - por que existe este archivo y no basta con app.mount():
Starlette/FastAPI NO propagan los eventos de arranque (lifespan) a las
sub-aplicaciones montadas con app.mount(). Cada una de las tres apps
(cerebro, estudio, comidas) define su propio `lifespan` para inicializar
su base de datos o sus tareas de fondo, pero si solo hacemos mount(),
esos lifespan de "estudio" y "comidas" NUNCA se ejecutan: por eso
aparecia "no such table: plans/recipes/..." (comidas.database.init_db()
no llegaba a correr) y el puente Spotify/iCloud de "estudio" tampoco
arrancaba en silencio.

La solucion es "componer" los tres lifespan en uno solo, y asignarlo
manualmente al router de la app raiz DESPUES del mount.
"""

import contextlib

from core.logging_config import setup_logging

setup_logging()

from core.auth import AuthMiddleware, router as auth_router  # noqa: E402
from core.pwa import router as pwa_router  # noqa: E402
from core.errors import SecurityHeadersMiddleware, install_error_handlers  # noqa: E402
from app.main import app as cerebro_app        # digital-brain/app/main.py, SIN TOCAR
from estudio.main import app as estudio_app  # noqa: E402  # migracion de server.py (aiohttp -> FastAPI)
from comidas.main import app as comidas_app  # noqa: E402  # macros / recetas / lista de la compra

app = cerebro_app

# Login/logout/healthz antes de los mounts para que no los tape ningun StaticFiles.
app.include_router(auth_router)
app.include_router(pwa_router)

for _sub in (cerebro_app, estudio_app, comidas_app):
    install_error_handlers(_sub)

# El ultimo middleware añadido es el mas externo: las cabeceras de seguridad
# envuelven tambien las respuestas 401/redirect del middleware de auth.
# CSP: todo el JS/CSS se sirve desde el propio panel (static/vendor). 'unsafe-inline'
# en script-src sigue siendo necesario por los manejadores onclick del HTML.
# img-src admite https/http por las miniaturas del Baúl y las fotos de platos;
# connect-src admite ws: para el WebSocket directo del navegador al ESP32.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https: http:",
    "font-src 'self' data:",
    "connect-src 'self' ws: wss:",
    "frame-src 'self' blob: data:",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])

app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware, csp=CSP)

app.mount("/estudio", estudio_app)
app.mount("/comidas", comidas_app)

# Guardamos el lifespan original del cerebro digital (init_db + sync_notes)
# para no perderlo al reemplazarlo por el combinado.
_cerebro_lifespan = app.router.lifespan_context


@contextlib.asynccontextmanager
async def combined_lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        # Cada uno de estos "entra" en el lifespan de su app, ejecutando
        # todo el codigo antes del "yield" de esa app (init_db, tareas
        # de fondo, etc.) y dejando pendiente el codigo de cierre hasta
        # que el proceso completo se apague.
        await stack.enter_async_context(_cerebro_lifespan(app))
        await stack.enter_async_context(estudio_app.router.lifespan_context(estudio_app))
        await stack.enter_async_context(comidas_app.router.lifespan_context(comidas_app))
        yield


app.router.lifespan_context = combined_lifespan
