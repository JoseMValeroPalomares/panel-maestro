"""
Hoja de muestra de iconos y recursos gráficos (propuesta de la Fase 2).

Genera docs/muestras/iconos.html: una página autocontenida (sprite, CSS y SVG en línea) que enseña cada bloque en
dos temas a la vez, Catppuccin Mocha y Claro, con los tokens reales de static/css/ds.css y themes.css.
No toca la aplicación: es para decidir antes de aplicar.

    python -m scripts.muestra_iconos
"""
import html
import re
from pathlib import Path

from core.templating import NAV_GROUPS

ROOT = Path(__file__).resolve().parent.parent
LUCIDE = ROOT / "node_modules" / "lucide-static" / "icons"
OUT = ROOT / "docs" / "muestras" / "iconos.html"


def _inner(svg_text: str) -> str:
    svg_text = re.sub(r"<!--[\s\S]*?-->", "", svg_text)
    svg_text = re.sub(r"^[\s\S]*?<svg[^>]*>", "", svg_text)
    return re.sub(r"</svg>\s*$", "", svg_text).strip()


def _lucide(name: str) -> str:
    return re.sub(r"\s+", " ", _inner((LUCIDE / f"{name}.svg").read_text(encoding="utf-8")))


# ---------------------------------------------------------------- propuesta
# Cambios de icono: (dónde, icono actual o glifo, icono propuesto, por qué)
CAMBIOS = [
    ("Navegación · Repaso", "calendar-days", "layers",
     "Era casi igual que Calendario. «layers» ya es el icono de Flashcards en Notas: mismo concepto, mismo icono."),
    ("Navegación · Revisión", "history", "clipboard-check",
     "«history» también se usa para «Seguir escribiendo» y el registro de cambios. Revisar la semana = repasar lo hecho."),
    ("Baúl · Para más tarde", "star", "bookmark-plus",
     "La estrella significa «favorito» en Comidas. Guardar para después es un marcador (activo: bookmark-check)."),
    ("Lista · Añadir un paso", "circle-plus", "list-plus",
     "El círculo con + parecía «nueva tarea». «list-plus» dice «añadir a esta lista»."),
    ("Comidas · No usar este día", "eye-off", "calendar-off",
     "No es ocultar: es quitar la franja de ese día."),
    ("Editor · Marcar para resumir", "R", "list-collapse", "Una letra no es un icono; «comprimir» se entiende sin leer."),
    ("Editor · Marcar para entender", "E", "circle-help", "La duda se reconoce al instante y no choca con la tecla E (editar)."),
    ("Menús · Opción elegida", "✓", "check", "El glifo de texto cambia de grosor según la fuente; el icono es el del resto."),
    ("Comidas · Favoritos", "★", "star", "Mismo motivo: icono de la familia en lugar de un carácter."),
    ("Hoy · Paleta de comandos", "command", "search",
     "El botón decía «Ctrl K» (el atajo). Se llama «Buscar» y el atajo pasa al tooltip."),
    ("Marca y app", "brain", "panel",
     "Icono propio: tres azulejos (tus secciones) y un nodo enlazado (tus ideas conectadas). El cerebro genérico de Lucide no distingue la app."),
]
NUEVOS = sorted({c[2] for c in CAMBIOS if c[2] != "panel"} | {"bookmark-check"})

# Azulejos. Opción A: un color por sección sin repeticiones exactas; los tonos parecidos nunca quedan juntos
# (Vida se reordena: Comidas, Estudio, Economía, Rendimiento). Opción B: un color por grupo.
# Valores (Mocha, Claro).
OPCION_A = {
    "hoy": ("#f9e2af", "#946200"), "calendario": ("#89b4fa", "#0071e3"), "rutinas": ("#f5c2e7", "#c2185b"),
    "tareas": ("#94e2d5", "#0e7c86"), "inbox": ("#fab387", "#d0480f"), "revision": ("#f5e0dc", "#8e5a4f"),
    "notas": ("#b4befe", "#5856d6"), "grafo": ("#74c7ec", "#0a6e91"), "baul": ("#f2cdcd", "#a83f6b"),
    "repaso": ("#cba6f7", "#8944ab"), "buscar": ("#bac2de", "#55555c"),
    "comidas": ("#a6e3a1", "#248a3d"), "estudio": ("#f38ba8", "#d70015"), "economia": ("#89dceb", "#00808a"),
    "rendimiento": ("#eba0ac", "#9c3348"),
    "gestion": ("#9399b2", "#5f6368"), "backups": ("#7f849c", "#48484c"), "papelera": ("#6c7086", "#3a3a3c"),
}
OPCION_B_GRUPO = {"planificar": ("#fab387", "#d0480f"), "conocimiento": ("#b4befe", "#5856d6"),
                  "vida": ("#a6e3a1", "#248a3d"), "sistema": ("#9399b2", "#5f6368")}
ICONO_NUEVO = {"repaso": "layers", "revision": "clipboard-check"}
ORDEN_VIDA_A = ["comidas", "estudio", "economia", "rendimiento"]

ESTADOS = [
    ("vacio", "Nada por aquí", "Lo que captures con C aparece en esta lista.", "Capturar", "accent"),
    ("hecho", "Todo hecho por hoy", "No queda nada pendiente. Lo siguiente es mañana a las 08:00.", "", "success"),
    ("sin-resultados", "Nada coincide con «pilas»", "Prueba con otra palabra o quita el filtro de estado.", "Quitar filtros", "accent"),
    ("error", "No se pudo cargar la lista", "El panel no ha respondido. Tus datos están guardados.", "Reintentar", "danger"),
    ("sin-conexion", "Sin conexión con el panel", "Ves lo último que se guardó. Se actualizará al volver a la red de casa.", "Reintentar", "warning"),
]


# ---------------------------------------------------------------- recursos
def build() -> str:
    sprite_txt = (ROOT / "static" / "icons.svg").read_text(encoding="utf-8")
    actuales = re.findall(r'<symbol id="i-([a-z0-9-]+)"', sprite_txt)
    symbols = re.findall(r"<symbol[\s\S]*?</symbol>", sprite_txt)
    for n in NUEVOS:
        if n not in actuales:
            symbols.append(f'<symbol id="i-{n}" viewBox="0 0 24 24">{_lucide(n)}</symbol>')
    for f in sorted((ROOT / "assets" / "icons" / "propios").glob("*.svg")):
        if f.stem in actuales:  # el sprite ya los incluye (scripts/vendor.mjs)
            continue
        symbols.append(f'<symbol id="i-{f.stem}" viewBox="0 0 24 24">{_inner(f.read_text(encoding="utf-8"))}</symbol>')
    for f in sorted((ROOT / "assets" / "ilustraciones").glob("*.svg")):
        symbols.append(f'<symbol id="ill-{f.stem}" viewBox="0 0 120 96"><g fill="none" stroke="currentColor" stroke-width="2" '
                       f'stroke-linecap="round" stroke-linejoin="round">{_inner(f.read_text(encoding="utf-8"))}</g></symbol>')
    sprite = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" stroke-width="1.75" '
              'stroke-linecap="round" stroke-linejoin="round">' + "".join(symbols) + "</svg>")

    themes = (ROOT / "static" / "css" / "themes.css").read_text(encoding="utf-8")
    themes = re.sub(r':root\[data-theme="(\w+)"\]', r".tema-\1", themes)
    ds = (ROOT / "static" / "css" / "ds.css").read_text(encoding="utf-8").replace('url("/static/', 'url("../../static/')
    # Los tokens derivados (accent-text, sombras…) se calculan donde se declaran: se repiten en cada panel para que
    # usen los colores de su tema y no los de :root.
    root_block = re.search(r"^:root \{[\s\S]*?^\}", ds, re.M)
    if root_block:
        ds += "\n.pane" + root_block.group(0)[len(":root"):]
    app_icons = {f.stem: f.read_text(encoding="utf-8") for f in (ROOT / "assets" / "icons" / "app").glob("*.svg")}
    icono_actual = (ROOT / "static" / "icons" / "icon.svg").read_text(encoding="utf-8")
    return page(sprite, ds + "\n" + themes, actuales, app_icons, icono_actual)


def ic(name: str, cls: str = "") -> str:
    return f'<svg class="icon {cls}" aria-hidden="true"><use href="#i-{name}"></use></svg>'


def glyph(x: str, cls: str = "") -> str:
    """Icono del sprite o, si es un glifo o una letra (lo que se sustituye), el carácter tal cual."""
    return ic(x, cls) if re.fullmatch(r"[a-z0-9-]{2,}", x) else f'<span class="glifo">{html.escape(x)}</span>'


def tile_custom(color_m: str, color_l: str, name: str, label: str) -> str:
    return (f'<span class="tile tile-x" style="--m:{color_m};--l:{color_l}" role="img" aria-label="{html.escape(label)}">'
            f"{ic(name)}</span>")


def pane(content: str, tema: str, titulo: str) -> str:
    return f'<div class="pane tema-{tema}"><p class="pane-label">{titulo}</p>{content}</div>'


def par(content_fn) -> str:
    return f'<div class="par">{pane(content_fn("m"), "mocha", "Catppuccin Mocha")}{pane(content_fn("l"), "light", "Claro")}</div>'


def page(sprite: str, css: str, actuales: list[str], app_icons: dict, icono_actual: str) -> str:
    grupos = {g: items for g, _, items in NAV_GROUPS}
    titulos = {g: t for g, t, _ in NAV_GROUPS}

    # 1. Marca
    def marca(_t):
        return f"""<div class="row-wrap">
          <figure><div class="appicon">{icono_actual}</div><figcaption>Actual</figcaption></figure>
          <figure><div class="appicon">{app_icons['icon']}</div><figcaption>Propuesta · oscuro</figcaption></figure>
          <figure><div class="appicon">{app_icons['icon-claro']}</div><figcaption>Propuesta · claro</figcaption></figure>
          <figure><div class="appicon sq">{app_icons['maskable']}</div><figcaption>Enmascarable (PWA)</figcaption></figure>
          <figure><div class="fav">{app_icons['favicon']}</div><figcaption>Favicon 32 px<br>(se adapta al sistema)</figcaption></figure>
          <figure><div class="fav fav16">{app_icons['favicon']}</div><figcaption>16 px</figcaption></figure>
        </div>
        <div class="brand-row"><span class="tile" data-section="notas">{ic('brain')}</span><b>Panel</b><span class="muted small">actual</span>
          <span class="sep"></span><span class="tile tile-mono">{ic('panel')}</span><b>Panel</b><span class="muted small">propuesta</span></div>"""

    # 2. Navegación: actual, opción A, opción B
    def nav(t):
        idx = 0 if t == "m" else 1
        cols = []
        for titulo, mode in (("Actual", "actual"), ("A · por sección", "a"), ("B · por grupo", "b")):
            rows = []
            for g, items in grupos.items():
                lista = items
                if mode == "a" and g == "vida":
                    lista = sorted(items, key=lambda it: ORDEN_VIDA_A.index(it[0]))
                rows.append(f'<li class="nav-group-t">{titulos[g]}</li>')
                for key, label, _href, icono in lista:
                    if mode == "actual":
                        tile = f'<span class="tile" data-section="{key}">{ic(icono)}</span>'
                    else:
                        nuevo = ICONO_NUEVO.get(key, icono)
                        c = OPCION_A[key] if mode == "a" else OPCION_B_GRUPO[g]
                        tile = tile_custom(c[0], c[1], nuevo, label)
                    rows.append(f'<li class="nav-row">{tile}<span>{label}</span></li>')
            cols.append(f'<div class="navcol"><p class="navcol-t">{titulo}</p><ul>{"".join(rows)}</ul></div>')
        return f'<div class="navcols">{"".join(cols)}</div>'

    # 3. Cambios de icono
    def cambios(_t):
        filas = "".join(
            f'<tr><td>{html.escape(d)}</td><td class="c">{glyph(a)}</td><td class="c">{ic("arrow-right", "subtle")}</td>'
            f'<td class="c">{ic(n)}</td><td class="small muted">{html.escape(m)}</td></tr>' for d, a, n, m in CAMBIOS)
        return f'<table class="tabla"><thead><tr><th>Dónde</th><th>Antes</th><th></th><th>Después</th><th>Por qué</th></tr></thead><tbody>{filas}</tbody></table>'

    # 4. Estados con ilustración
    def estados(_t):
        out = []
        for nombre, titulo, texto, accion, tono in ESTADOS:
            boton = (f'<button type="button" class="btn btn-tinted">{ic("rotate-ccw" if accion == "Reintentar" else "plus")}{accion}</button>'
                     if accion else "")
            out.append(f'<div class="estado" style="--ill-accent: var(--{tono})"><svg class="ill" role="img" aria-label="{titulo}">'
                       f'<use href="#ill-{nombre}"></use></svg><h3>{titulo}</h3><p>{texto}</p>{boton}</div>')
        out.append('<div class="estado"><svg class="ill carga" viewBox="0 0 24 24" role="img" aria-label="Cargando">'
                   '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/>'
                   '<circle cx="17.25" cy="17.25" r="3.75"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/></svg>'
                   '<h3>Cargando…</h3><p>Los azulejos se encienden por turnos; con «reducir movimiento» se quedan quietos.</p></div>')
        return f'<div class="estados">{"".join(out)}</div>'

    # 5. Tamaños y botones de icono con tooltip
    def tamanos(_t):
        sizes = "".join(f'<span class="sz">{ic("calendar", "")}<small>{s}</small></span>'.replace('class="icon "', f'class="icon" style="width:{s}px;height:{s}px"')
                        for s in (16, 18, 20, 24))
        return f"""<div class="row-wrap">{sizes}</div>
          <div class="row-wrap">
            <button type="button" class="btn btn-ghost btn-icon" aria-label="Añadir un paso" data-tip="Añadir un paso (E)">{ic('list-plus')}</button>
            <button type="button" class="btn btn-ghost btn-icon" aria-label="Para más tarde" data-tip="Para más tarde">{ic('bookmark-plus')}</button>
            <button type="button" class="btn btn-tinted btn-icon" aria-label="Buscar" data-tip="Buscar (Ctrl K)">{ic('search')}</button>
            <button type="button" class="btn btn-icon" aria-label="Más acciones" data-tip="Más acciones">{ic('ellipsis')}</button>
            <span class="small muted">Pasa el ratón o tabula: el tooltip sale también con el foco del teclado.</span>
          </div>"""

    # 6. Todos los iconos
    def todos(_t):
        celdas = "".join(f'<div class="cell{" nuevo" if n in NUEVOS or n == "panel" else ""}">{ic(n)}<span>{n}</span></div>'
                         for n in sorted(set(actuales) | set(NUEVOS) | {"panel"}))
        return f'<div class="grid">{celdas}</div>'

    bloques = [
        ("marca", "1. Logo e icono de la app", "Icono propio con la gramática de Lucide (rejilla de 24, trazo 1,75, extremos redondeados). "
         "Tres azulejos con los colores de Notas, Inbox y Tareas y un nodo enlazado (Hoy). Variantes para tema oscuro, claro, PWA enmascarable y favicon.", marca),
        ("nav", "2. Azulejos de sección", "Seis secciones repiten color hoy. Con 18 secciones y unos 9 tonos distinguibles por tema no caben "
         "18 colores inconfundibles: la opción A evita repeticiones exactas y separa los parecidos; la B da el color al grupo y deja que el icono distinga. "
         "Repaso y Revisión cambian de icono en ambas.", nav),
        ("cambios", "3. Iconos que cambian", "Solo donde un icono tenía dos significados o no era un icono. La metáfora se mantiene reconocible.", cambios),
        ("estados", "4. Estados: vacío, hecho, sin resultados, error, sin conexión y carga",
         "Ilustraciones propias (rejilla de 120×96, trazo 2) que heredan el color del tema; el acento dice el tono del mensaje.", estados),
        ("tamanos", "5. Tamaños y botones de icono", "Tamaños 16 / 18 (base actual) / 20 / 24. Tooltip propio que funciona con teclado.", tamanos),
        ("todos", f"6. Todos los iconos ({len(set(actuales) | set(NUEVOS)) + 1})",
         "Lucide 0.460 (ISC) + 1 propio. Marcados en color: los que entrarían nuevos.", todos),
    ]
    secciones = "".join(f'<section id="{i}"><h2>{t}</h2><p class="intro">{d}</p>{par(fn)}</section>' for i, t, d, fn in bloques)
    nav_links = " ".join(f'<a href="#{i}">{t.split(". ", 1)[1].split(":")[0]}</a>' for i, t, _d, _f in bloques)

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Muestra de iconos · Panel</title>
<style>{css}
{EXTRA_CSS}</style></head>
<body class="tema-mocha">{sprite}
<main class="hoja">
<header class="hoja-head"><h1>Muestra de iconos y recursos gráficos</h1>
<p>Propuesta de la Fase 2 para el Panel. Nada de esto está aplicado todavía. Cada bloque se ve en Catppuccin Mocha y en Claro con los
tokens reales del panel. Generada con <code>python -m scripts.muestra_iconos</code>.</p>
<nav class="hoja-nav">{nav_links}</nav></header>
{secciones}
</main></body></html>
"""


EXTRA_CSS = """
body { background: var(--bg); color: var(--text); font-family: var(--font-sans); margin: 0; }
.hoja { max-width: 1320px; margin: 0 auto; padding: 32px 16px 64px; }
.hoja-head h1 { font-size: var(--fs-28); margin: 0 0 8px; }
.hoja-head p, .intro { color: var(--text-2); max-width: 78ch; line-height: 1.5; }
.hoja-nav { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 16px 0 8px; font-size: var(--fs-13); }
.hoja-nav a { color: var(--accent); }
section { margin-top: 48px; }
section h2 { font-size: var(--fs-22); margin: 0 0 6px; }
.par { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 900px) { .par { grid-template-columns: 1fr; } }
.pane { background: var(--bg); color: var(--text); border: 1px solid var(--separator); border-radius: 16px; padding: 20px; min-width: 0; overflow: auto; }
.pane-label { margin: 0 0 16px; font-size: var(--fs-13); font-weight: 600; color: var(--text-3); }
.row-wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin-bottom: 16px; }
figure { margin: 0; text-align: center; font-size: var(--fs-12); color: var(--text-3); }
figcaption { margin-top: 6px; }
.appicon svg { width: 72px; height: 72px; display: block; }
.appicon.sq svg { border-radius: 16px; }
.fav { width: 32px; height: 32px; } .fav svg { width: 32px; height: 32px; display: block; } .fav16, .fav16 svg { width: 16px; height: 16px; }
.brand-row { display: flex; align-items: center; gap: 8px; font-size: var(--fs-17); }
.brand-row .sep { width: 24px; }
.tile-mono { background: var(--fill-strong); color: var(--text); }
.tema-mocha .tile-x { background: var(--m); color: #11111b; }
.tema-light .tile-x { background: var(--l); color: #ffffff; }
.navcols { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1100px) { .navcols { grid-template-columns: 1fr; } }
.navcol ul { list-style: none; margin: 0; padding: 0; }
.navcol-t { font-size: var(--fs-13); font-weight: 600; margin: 0 0 8px; }
.nav-group-t { font-size: var(--fs-12); color: var(--text-3); font-weight: 600; margin: 10px 0 4px; }
.nav-row { display: flex; align-items: center; gap: 10px; padding: 3px 0; font-size: var(--fs-15); }
.tabla { width: 100%; border-collapse: collapse; font-size: var(--fs-13); }
.tabla th { text-align: left; color: var(--text-3); font-weight: 600; padding: 6px 8px; border-bottom: 1px solid var(--separator); }
.tabla td { padding: 8px; border-bottom: 1px solid var(--separator); vertical-align: middle; }
.tabla .c { text-align: center; width: 40px; }
.tabla .icon { width: 20px; height: 20px; }
.glifo { font-weight: 700; font-size: 17px; }
.subtle { color: var(--text-3); }
.estados { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.estado { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px; padding: 20px 12px;
  background: var(--bg-elev); border-radius: 12px; color: var(--text-2); }
.estado .ill { width: 120px; height: 96px; color: var(--text-3); }
.estado h3 { font-size: var(--fs-15); color: var(--text); margin: 4px 0 0; }
.estado p { font-size: var(--fs-13); margin: 0; line-height: 1.45; }
.estado .btn { margin-top: 8px; }
.ill.carga { width: 56px; height: 56px; margin: 20px 0; fill: var(--accent); stroke: none; }
.ill.carga > * { animation: encender 1.6s infinite ease-in-out; opacity: .25; }
.ill.carga > :nth-child(2) { animation-delay: .2s; } .ill.carga > :nth-child(3) { animation-delay: .4s; } .ill.carga > :nth-child(4) { animation-delay: .6s; }
@keyframes encender { 0%, 100% { opacity: .25; } 30% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .ill.carga > * { animation: none; opacity: .7; } }
.sz { display: inline-flex; flex-direction: column; align-items: center; gap: 4px; color: var(--text); }
.sz small { color: var(--text-3); font-size: var(--fs-12); }
[data-tip] { position: relative; }
[data-tip]:hover::after, [data-tip]:focus-visible::after {
  content: attr(data-tip); position: absolute; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%); white-space: nowrap;
  background: var(--text); color: var(--bg); font-size: var(--fs-12); font-weight: 500; padding: 4px 8px; border-radius: 6px; pointer-events: none; z-index: 5; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 4px; }
.cell { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 10px 4px; border-radius: 8px; font-size: 12px; color: var(--text-3); text-align: center; word-break: break-word; }
.cell .icon { width: 20px; height: 20px; color: var(--text); }
.cell.nuevo { background: var(--accent-soft); color: var(--text); }
"""


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"Muestra escrita en {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
