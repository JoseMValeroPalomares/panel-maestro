"""
Plantillas Jinja compartidas por las tres apps (todas usan templates/_layout.html).

La navegación vive aquí para que la barra lateral, la barra de pestañas móvil
y la hoja "Más" salgan siempre iguales, sea cual sea la app que renderiza.
"""
import hashlib
import os

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from core import config
from core.themes import CHOICE_GROUPS as THEME_GROUPS, CHOICES as THEME_CHOICES, preview as theme_preview

# Menú agrupado por intención: (clave del grupo, título, [(clave, etiqueta, ruta, icono), …])
NAV_GROUPS = [
    ("planificar", "Planificar", [
        ("hoy", "Hoy", "/hoy", "sun"),
        ("calendario", "Calendario", "/calendario", "calendar"),
        ("rutinas", "Rutinas", "/rutinas", "repeat"),
        ("tareas", "Tareas", "/tareas", "list-todo"),
        ("inbox", "Inbox", "/inbox", "inbox"),
        ("revision", "Revisión", "/revision", "clipboard-check"),
    ]),
    ("conocimiento", "Conocimiento", [
        ("notas", "Notas", "/", "notebook-pen"),
        ("grafo", "Grafo", "/graph", "waypoints"),
        ("baul", "Baúl", "/vault", "library"),
        ("repaso", "Repaso", "/repaso", "layers"),
        ("buscar", "Buscar", "/buscar", "search"),
    ]),
    ("vida", "Vida", [
        ("comidas", "Comidas", "/comidas/", "utensils-crossed"),
        ("estudio", "Estudio", "/estudio/", "graduation-cap"),
        ("economia", "Economía", "/economia", "wallet"),
        ("rendimiento", "Rendimiento", "/rendimiento", "activity"),
    ]),
    ("sistema", "Sistema", [
        ("gestion", "Gestión", "/gestion", "table-2"),
        ("backups", "Copias", "/backups", "database-backup"),
        ("papelera", "Papelera", "/papelera", "trash-2"),
    ]),
]
# Destinos por defecto de la barra inferior en móvil, en su orden (el quinto es siempre "Más"). Se pueden elegir
# otros, hasta 4, en Ajustes (Prefs «tabbar», static/js/tabbar-init.js).
TABBAR = ["hoy", "calendario", "tareas", "notas"]  # en el orden del menú, como los que se eligen

templates = Jinja2Templates(directory=str(config.PROJECT_ROOT / "templates"))


def _all_nav():
    return [item for _, _, items in NAV_GROUPS for item in items]


# Carpeta de cada prefijo de URL de recursos estáticos
_ASSET_DIRS = {"/static/": config.PROJECT_ROOT / "static", "/comidas/": config.PROJECT_ROOT / "comidas" / "static",
               "/estudio/": config.PROJECT_ROOT / "estudio" / "static"}
_asset_cache: dict[str, tuple[float, str]] = {}


def asset(url: str) -> str:
    """URL con ?v=<hash del contenido>. Así una página nueva nunca recibe un JS/CSS viejo de la caché del
    service worker (que sirve /static con «stale-while-revalidate»)."""
    for prefix, folder in _ASSET_DIRS.items():
        if url.startswith(prefix):
            path = folder / url[len(prefix):]
            break
    else:
        return url
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return url
    cached = _asset_cache.get(url)
    if not cached or cached[0] != mtime:
        cached = (mtime, hashlib.sha256(path.read_bytes()).hexdigest()[:10])
        _asset_cache[url] = cached
    return f"{url}?v={cached[1]}"


def icon(name: str, cls: str = "", label: str | None = None) -> Markup:
    """Icono del sprite. Sin `label` es decorativo (lo nombra el control); con él, informa por sí solo."""
    a11y = f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"'
    return Markup(
        f'<svg class="icon {escape(cls)}" {a11y}><use href="{asset("/static/icons.svg")}#i-{escape(name)}"></use></svg>'
    )


def brand_mark(cls: str = "") -> Markup:
    """Logo del Panel con los colores del tema activo: tres azulejos (Notas, Inbox, Tareas) y el nodo (Hoy)."""
    return Markup(
        f'<svg class="brand-mark {escape(cls)}" viewBox="0 0 24 24" aria-hidden="true">'
        '<rect x="3" y="3" width="7.5" height="7.5" rx="2" style="fill: var(--tile-notas)"/>'
        '<rect x="13.5" y="3" width="7.5" height="7.5" rx="2" style="fill: var(--tile-inbox)"/>'
        '<rect x="3" y="13.5" width="7.5" height="7.5" rx="2" style="fill: var(--tile-tareas)"/>'
        '<circle cx="17.25" cy="17.25" r="3.75" style="fill: var(--tile-hoy)"/>'
        '<path d="m10.5 10.5 4.1 4.1" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/></svg>'
    )


templates.env.globals.update(
    icon=icon, asset=asset, brand_mark=brand_mark, theme_choices=THEME_CHOICES, theme_groups=THEME_GROUPS, theme_preview=theme_preview,
    nav_groups=NAV_GROUPS,
    tabbar_default=TABBAR,
    nav_all=_all_nav,
)


def render(request: Request, name: str, section: str, title: str, **context):
    return templates.TemplateResponse(
        request=request, name=name, context={"section": section, "page_title": title, **context}
    )
