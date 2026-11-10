"""Rutas de PWA: manifest, favicon (y el service worker en la raíz para que su alcance sea "/")."""
import hashlib
import json

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

from core import config

router = APIRouter()
STATIC = config.PROJECT_ROOT / "static"
ICONS = STATIC / "icons"

# Recursos del "shell" que se guardan al instalar la PWA (todo lo necesario para
# pintar cualquier pantalla sin red). Las páginas y la API se cachean al visitarlas.
PRECACHE = [
    "/static/css/ds.css", "/static/js/ui.js", "/static/js/sortable.js", "/static/js/theme-init.js", "/static/js/auth-guard.js",
    "/static/icons.svg", "/static/ilustraciones.svg", "/static/offline.html",
    "/static/fonts/inter-latin-wght-normal.woff2", "/static/fonts/inter-latin-ext-wght-normal.woff2",
    "/static/icons/icon.svg", "/static/icons/icon-192.png",
    "/static/css/cerebro.css", "/static/js/cerebro.js", "/static/css/inbox.css", "/static/js/inbox.js", "/static/css/board.css", "/static/js/board.js", "/static/js/inbox-layout.js",
    "/static/css/vault.css", "/static/js/vault.js", "/static/css/graph.css", "/static/js/graph.js",
    "/static/css/gestion.css", "/static/js/gestion.js", "/static/css/backups.css", "/static/js/backups.js",
    "/static/css/items.css", "/static/js/items.js", "/static/js/item-list.js", "/static/js/tareas.js",
    "/static/css/buscar.css", "/static/js/buscar.js", "/static/css/repaso.css", "/static/js/repaso.js",
    "/static/vendor/marked/marked.min.js", "/static/vendor/dompurify/purify.min.js",
    "/static/vendor/katex/katex.min.js", "/static/vendor/katex/katex.min.css", "/static/vendor/katex/auto-render.min.js",
    "/static/vendor/highlight/highlight.min.js", "/static/vendor/highlight/github.min.css",
    "/static/vendor/highlight/github-dark.min.css",
    "/comidas/css/comidas.css", "/comidas/js/comidas.js", "/estudio/estudio.css", "/estudio/app.js",
]


def _asset_path(url: str):
    if url.startswith("/static/"):
        return STATIC / url[len("/static/"):]
    if url.startswith("/comidas/"):
        return config.PROJECT_ROOT / "comidas" / "static" / url[len("/comidas/"):]
    if url.startswith("/estudio/"):
        return config.PROJECT_ROOT / "estudio" / "static" / url[len("/estudio/"):]
    return None


def _sw_version() -> str:
    """Hash del contenido del shell + del propio sw.js: cambia en cada despliegue."""
    h = hashlib.sha256()
    for url in PRECACHE + ["/static/js/sw.js"]:
        path = _asset_path(url)
        if path and path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:12]


@router.get("/sw.js")
def service_worker():
    src = (STATIC / "js" / "sw.js").read_text(encoding="utf-8")
    src = src.replace("__VERSION__", _sw_version()).replace("__PRECACHE__", json.dumps(PRECACHE))
    return Response(src, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

MANIFEST = {
    "name": "Panel personal",
    "short_name": "Panel",
    "description": "Notas, inbox, comidas y estudio en un solo panel",
    "lang": "es-ES",
    "start_url": "/hoy",  # la pantalla de inicio es «Hoy» (los accesos directos no cambian)
    "scope": "/",
    "display": "standalone",
    "background_color": "#181825",
    "theme_color": "#181825",
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "shortcuts": [
        {"name": "Notas", "url": "/", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
        {"name": "Inbox", "url": "/inbox", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
        {"name": "Comidas", "url": "/comidas/", "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192"}]},
    ],
}


# Simulaciones de las notas: el código lo escribe el usuario y necesita JS en línea, que la CSP del panel ya no
# permite. Corre en este documento aparte, dentro de un iframe con sandbox="allow-scripts" (origen opaco: no ve
# cookies, almacenamiento ni el DOM del panel), con su propia CSP. El código llega por postMessage (cerebro.js).
SIM_HTML = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Simulación</title></head><body><script>
addEventListener('message', function run(e) {
  if (e.source !== parent || !e.data || e.data.type !== 'sim-run' || typeof e.data.code !== 'string') return;
  removeEventListener('message', run);
  document.open(); document.write(e.data.code); document.close();
});
parent.postMessage({ type: 'sim-ready' }, '*');
</script></body></html>"""
SIM_CSP = "; ".join([
    "default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'", "img-src data: blob:",
    "font-src data:", "connect-src 'none'", "form-action 'none'", "base-uri 'none'", "frame-ancestors 'self'",
    "sandbox allow-scripts",
])


@router.get("/sim")
def simulation_frame():
    return Response(SIM_HTML, media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy": SIM_CSP, "Cache-Control": "no-cache"})


@router.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@router.get("/favicon.ico")
def favicon():
    return FileResponse(ICONS / "favicon-32.png", media_type="image/png")
