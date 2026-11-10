"""
Genera docs/ICONOS.md: cada icono del sprite (static/icons.svg), su significado, dónde se usa y su origen/licencia.

    python -m scripts.iconos_doc

Se rehace a partir del código, así que no se queda viejo: el significado de los principales está aquí abajo y,
para el resto, se toma el texto que lo acompaña (label, aria-label, title o el texto del botón).
"""
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "ICONOS.md"
FUENTES = ["templates/*.html", "static/js/*.js", "comidas/static/js/*.js", "estudio/static/*.js", "core/templating.py"]
PROPIOS = {p.stem for p in (ROOT / "assets" / "icons" / "propios").glob("*.svg")}

# Significado fijado (navegación, tipos y los que se cambiaron en la Fase 3 para que no tuvieran dos significados)
SIGNIFICADO = {
    "panel": "Marca del Panel (tres azulejos y un nodo enlazado)",
    "sun": "Hoy", "calendar": "Calendario / fecha", "repeat": "Rutina", "list-todo": "Tareas", "inbox": "Inbox",
    "clipboard-check": "Revisión semanal", "notebook-pen": "Notas", "waypoints": "Grafo", "library": "Baúl",
    "layers": "Repaso y flashcards", "search": "Buscar", "utensils-crossed": "Comidas / franja comida",
    "wallet": "Economía", "graduation-cap": "Estudio", "activity": "Rendimiento", "table-2": "Gestión",
    "database-backup": "Copias de seguridad", "trash-2": "Borrar / Papelera", "square-check": "Tarea",
    "lightbulb": "Idea", "calendar-plus": "Nuevo evento", "flag": "Prioridad", "list-plus": "Añadir un paso",
    "bookmark-plus": "Guardar para más tarde (Baúl)", "bookmark-check": "Guardado para más tarde (Baúl)",
    "star": "Favorito", "calendar-off": "Quitar una comida ese día", "list-collapse": "Marcar para resumir",
    "circle-help": "Marcar para entender mejor", "triangle-alert": "Aviso / marcar como erróneo",
    "check": "Hecho / opción elegida", "history": "Historial (versiones, seguir escribiendo, registro)",
    "plus": "Crear / capturar", "x": "Cerrar / quitar", "ellipsis": "Más acciones", "pencil": "Editar",
    "plug-zap": "Estado de las conexiones", "settings": "Ajustes", "bell": "Avisos", "command": "Atajo Ctrl",
    "rotate-ccw": "Reintentar / restaurar", "wifi-off": "Sin conexión", "flame": "Racha",
    "coffee": "Franja desayuno", "apple": "Franja merienda", "moon": "Franja cena", "cookie": "Franja extras",
}
ETIQUETA = re.compile(r"""(?:label|aria-label|title|data-tip)\s*[:=]\s*["'`]([^"'`$]{3,60})""")
TEXTO = re.compile(r"""\}\}\s*([A-ZÁÉÍÓÚa-záéíóúñ][^<{]{2,40})<|\)\}\s*([A-ZÁÉÍÓÚa-záéíóúñ][^<$`]{2,40})""")


def main() -> None:
    sprite = (ROOT / "static" / "icons.svg").read_text(encoding="utf-8")
    nombres = re.findall(r'<symbol id="i-([a-z0-9-]+)"', sprite)
    usos: dict[str, set[str]] = defaultdict(set)
    textos: dict[str, set[str]] = defaultdict(set)
    files = [f for pat in FUENTES for f in sorted(ROOT.glob(pat))]
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        for line in f.read_text(encoding="utf-8").splitlines():
            pinta = re.search(r"icon|ICON|Icon|repo_card", line)
            for n in nombres:
                # Los nombres con guion solo pueden ser iconos; los de una palabra («panel», «tags»…) también son
                # clases o campos, así que cuentan solo en una línea que pinta un icono o al final de una tupla.
                patron = rf"""(?<!class=)(?<!== )['"]{re.escape(n)}['"]""" + ("" if "-" in n or pinta else r"\s*\]")
                if re.search(patron, line):
                    usos[n].add(rel)
                    for clave, nombre in re.findall(r"([A-ZÁÉÍÓÚ][\wáéíóúñ]+): ?'([a-z0-9-]+)'", line):  # {Transporte: 'bus'}
                        if nombre == n:
                            textos[n].add(clave)
                    for m in ETIQUETA.findall(line):
                        textos[n].add(m.strip())
                    for a, b in TEXTO.findall(line):
                        if (a or b).strip():
                            textos[n].add((a or b).strip())
    filas = []
    for n in sorted(nombres):
        origen = "Propio (MIT del proyecto)" if n in PROPIOS else "Lucide 0.460 (ISC)"
        sig = SIGNIFICADO.get(n) or ", ".join(sorted(textos[n], key=len)[:3]) or "—"
        donde = ", ".join(f"`{u}`" for u in sorted(usos[n])) or "dinámico (nombre construido en el código) o reserva"
        filas.append(f"| `{n}` | {sig} | {donde} | {origen} |")
    OUT.write_text(f"""# Iconos del Panel

Generado por `python -m scripts.iconos_doc` a partir del sprite y del código: no se edita a mano.

## Reglas

- **Una sola familia**: [Lucide](https://lucide.dev) 0.460 (licencia ISC: uso, copia y modificación libres manteniendo
  el aviso) más los iconos propios de `assets/icons/propios/`, dibujados con la misma gramática: rejilla de 24,
  `viewBox="0 0 24 24"`, trazo 1,75, extremos redondeados y `currentColor` (heredan el color del tema).
- **Sprite**: `scripts/icons.txt` (nombres de Lucide) + `assets/icons/propios/` → `npm run vendor` →
  `static/icons.svg`. Uso: `icon('nombre')` en Jinja (`core/templating.py`) y en JS (`static/js/ui.js`).
- **Tamaños**: 16 (`icon-sm`), 18 (base), 22 (`icon-lg`), 32 (`icon-xl`); 17 dentro de botones y azulejos.
- **Accesibilidad**: sin `label` el icono es decorativo (`aria-hidden`) y el control lleva `aria-label`; con
  `icon(nombre, clase, label)` el icono se anuncia por sí solo. Los botones de solo icono muestran un tooltip
  (`data-tip`, también con el foco del teclado).
- **Un significado por icono**: si se sustituye uno, la metáfora tiene que seguir siendo reconocible.
- **Ilustraciones** de los estados (`assets/ilustraciones/` → `static/ilustraciones.svg`, rejilla de 120×96, trazo 2):
  vacío, hecho, sin resultados, error y sin conexión. Las usa `stateView()` de `ui.js`.
- **Icono de la app**: `assets/icons/app/` (oscuro, claro, enmascarable y favicon adaptable) → PNG de la PWA.
- **Muestra** con todos los iconos en tema claro y oscuro: `docs/muestras/iconos.html` (`python -m scripts.muestra_iconos`).

## Inventario ({len(nombres)} iconos)

| Icono | Significado | Dónde | Origen y licencia |
|---|---|---|---|
""" + "\n".join(filas) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(nombres)} iconos")


if __name__ == "__main__":
    main()
