---
name: Panel
description: Panel personal (notas, inbox, tareas, comidas, estudio) con aspecto de app de sistema de Apple y temas intercambiables (Catppuccin Mocha por defecto).
colors:
  # Tema por defecto: Catppuccin Mocha. Los demás temas (Latte, Claro, Oscuro, Nord, Dracula, Gruvbox, Tokyo Night
  # y «Sistema») redefinen los mismos tokens: core/themes.py → static/css/themes.css.
  bg: "#181825"
  bg-elev: "#1e1e2e"
  bg-elev-2: "#262637"
  bg-sunken: "#11111b"
  text: "#cdd6f4"
  text-2: "#bac2de"
  text-3: "#a6adc8"
  text-on-accent: "#11111b"
  accent: "#89b4fa"
  accent-fill: "#89b4fa"
  accent-hover: "#b4befe"
  danger: "#f38ba8"
  warning: "#fab387"
  success: "#a6e3a1"
  status-draft: "#9399b2"
  status-wip: "#fab387"
  status-done: "#a6e3a1"
  status-index: "#cba6f7"
  tile-fg: "#11111b"
  tile-notas: "#b4befe"
  tile-inbox: "#fab387"
  tile-tareas: "#94e2d5"
  tile-baul: "#f9e2af"
  tile-grafo: "#89b4fa"
  tile-comidas: "#a6e3a1"
  tile-estudio: "#cba6f7"
  tile-gestion: "#9399b2"
  tile-backups: "#7f849c"
  tile-buscar: "#74c7ec"
  board-canvas: "#1e1e2e"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Display, Inter Var, Segoe UI, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Display, Inter Var, Segoe UI, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Inter Var, Segoe UI, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: "-0.006em"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Inter Var, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.3
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, SF Pro Text, Inter Var, Segoe UI, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.3
  mono:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Menlo, Consolas, monospace"
    fontSize: "0.875rem"
rounded:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "22px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
  "10": "40px"
  "12": "48px"
  touch: "44px"
components:
  button:
    backgroundColor: "rgba(118, 118, 128, 0.12)"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: "36px"
    padding: "0 16px"
  button-primary:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.text-on-accent}"
    rounded: "{rounded.sm}"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-tinted:
    backgroundColor: "accent-soft (acento al 10–16 %)"
    textColor: "accent-text (acento mezclado al 60 % con text)"
    rounded: "{rounded.sm}"
  button-danger-solid:
    backgroundColor: "{colors.danger}"
    textColor: "text-on-danger"
    rounded: "{rounded.sm}"
  panel:
    backgroundColor: "{colors.bg-elev}"
    rounded: "{rounded.lg}"
  list-row:
    backgroundColor: "{colors.bg-elev}"
    height: "44px"
    padding: "8px 16px"
  input:
    backgroundColor: "{colors.bg-elev}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    height: "38px"
  chip:
    backgroundColor: "rgba(118, 118, 128, 0.12)"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    height: "30px"
  chip-active:
    backgroundColor: "{colors.text}"
    textColor: "{colors.bg-elev}"
  tile:
    textColor: "{colors.tile-fg}"
    rounded: "7px"
    size: "28px"
  modal:
    backgroundColor: "{colors.bg-elev}"
    rounded: "{rounded.xl}"
    width: "560px"
---

# DESIGN.md — Panel

Fuente normativa: `static/css/ds.css` (tokens de forma, tipografía y movimiento) y `static/css/themes.css` (colores, un
bloque `:root[data-theme="…"]` por tema, generado desde `core/themes.py` con `python -m scripts.themes`). Si este
documento y el CSS discrepan, manda el CSS y hay que actualizar esto.

## Overview

Una herramienta que desaparece en la tarea, como las apps de sistema de Apple (Ajustes, Notas, Recordatorios).
Modo **Operate** en todas las pantallas: escaneo rápido, controles estándar, nada decorativo. El color solo
identifica una sección (azulejo) o un estado; todo lo demás es gris neutro más un único acento azul para acciones
y selección.

La firma del sistema son los **azulejos de color por sección** (28 px, radio 7 px, glifo `tile-fg`: oscuro sobre los
acentos pastel de los temas oscuros, blanco sobre los saturados de los claros): se repiten en la
barra lateral, junto al título grande de cada pantalla, en la hoja «Más» del móvil y en los encabezados de grupo
(p. ej. Tareas agrupadas por Inbox o por nota).

## Colors

- **Temas** (Ajustes → Tema; se guarda en `localStorage` y `theme-init.js` lo aplica antes de pintar): Catppuccin
  Mocha (por defecto), Catppuccin Latte, Claro y Oscuro (los de Apple de la primera ronda), Nord, Dracula, Gruvbox,
  Tokyo Night y Sistema (Claro u Oscuro según el equipo). Todos definen los mismos tokens; los valores que no son de la
  paleta oficial están ajustados para AA y `tests/e2e/test_tema.py` lo comprueba en todas las páginas y temas.
- Capas: `bg-sunken` < `bg` < `bg-elev` < `bg-elev-2` (en Mocha: crust, mantle, base y una intermedia).
- Texto en tres niveles: `text`, `text-2` y `text-3` (mínimo para texto, ≥ 4,5:1 en todos los temas).
- Acento único: `accent` para enlaces, `accent-fill` + `text-on-accent` para el botón primario, `accent-soft` para
  selección y botón «tinted». Texto de color sobre su fondo suave: `accent-text`, `danger-text`, `warning-text`,
  `success-text` (el color mezclado al 60 % con `text`, para pasar AA en cualquier tema).
- Estados de nota: por escribir (gris), en desarrollo (`warning`), consolidado (`success`), índice (morado), siempre
  como punto de 8 px + etiqueta, nunca solo color.
- Categorías (Notas, Baúl, Grafo): `--cat-0…9` del tema activo, solo en puntos y en los nodos del grafo.
- Azulejos: un color por sección (`tile-*`) con su glifo `tile-fg`. El lienzo del tablero (`board-bg`) es la
  superficie del tema en los oscuros y Mocha base en los claros: siempre oscuro, porque las formas son para él.

## Typography

Pila del sistema (SF en Apple) con Inter Variable autoalojada como respaldo (`static/fonts`). Escala fija de Apple:
12 / 13 / 15 / 17 / 20 / 22 / 28 / 34 px (`--fs-*`). Cuerpo 15 px, interlineado 1,45, tracking −0,006em; titulares
700 con −0,02em y `text-wrap: balance`. Cifras en tablas, contadores y fechas con `font-variant-numeric:
tabular-nums` (clase `.tabular`). Monoespaciada solo para código y para mostrar sintaxis (`- [ ]`).

## Layout

- Escritorio (≥1024 px): barra lateral de 232 px translúcida + contenido con cabecera de página (título grande a la
  izquierda, acciones a la derecha) y `page-body` con 24 px de margen. Herramientas con ancho de lectura limitado
  (Tareas y Buscar 820 px, Copias 880 px, Repaso 960 px, Gestión 1180 px).
- Tablet (768–1023 px): carril de iconos en lugar de la barra lateral.
- Móvil (<768 px): barra de pestañas inferior (Notas, Inbox, Comidas, Baúl, Más), `page-body` de 16 px, tablas
  convertidas en tarjetas, modales como hoja inferior que respeta el teclado (`--vvh`). Nunca desplazamiento
  horizontal de página.
- Espaciado en múltiplos de 4 px (`--sp-*`); objetivos táctiles de 44 px (`--touch`, `.check-hit`).

## Elevation & Depth

Tres sombras suaves con desplazamiento (`--shadow-1/2/3`) más un filo de 0,5 px con `--separator`. Paneles y listas:
`shadow-1`. Menús y barra flotante de selección: `shadow-2/3`. La translucidez con `backdrop-filter` se reserva a
elementos fijos sobre contenido que se desplaza (barra lateral, pestañas, menús, barra de selección de Gestión).

## Shapes

Radios `xs 6 · sm 8 · md 12 · lg 16 · xl 22 · pill`. Botones y campos 8 px; listas y tablas 12 px; paneles 16 px;
modales 22 px; chips en píldora; azulejos 7 px (9 px el grande). Iconos Lucide con trazo 1,75 desde
`static/icons.svg` (añadir nombres a `scripts/icons.txt` y `npm run vendor`).

## Components

- **Botones** (`.btn`): neutro, `-primary`, `-tinted`, `-ghost`, `-danger`, `-danger-solid`; tamaños `-sm` (30 px),
  normal (36 px), `-lg` (44 px) e `-icon`. Estado de carga con `.is-loading`; deshabilitado al 45 %.
- **Lista agrupada** (`.list` + `.list-row`, estilo iOS inset grouped): filas de 44 px con separador interior que
  empieza a 16 px. Es el contenedor por defecto de resultados, copias, tareas y notas.
- **Tabla** (`.table-wrap` + `.table`): cabecera fija, filas seleccionadas con `accent-soft`, columnas numéricas
  `.num`. En Gestión, la tabla pasa a tarjetas en móvil y la selección muestra una barra flotante.
- **Control segmentado** y **chips** (`.segmented`, `.chip` con `aria-pressed`) para filtros; el chip activo se
  invierte (texto sobre fondo de texto).
- **Modal único** (`dialog.modal`, `-sm`, `-lg`) con `ui.js:openModal`; centrado en escritorio (el reset global
  anula el `margin: auto` nativo, por eso `dialog.modal` lo vuelve a poner). Confirmaciones con `uiConfirm`; las
  destructivas usan `danger: true`. Restaurar una copia pide escribir RESTAURAR.
- **Toast** con acción opcional («Deshacer» tras borrar en lote, 12 s).
- **Estado vacío** (`emptyState`) con icono en círculo, título y una frase de qué hacer; **skeletons** al cargar.
- **Insignia de estado** (`.status` + `.status-dot[data-status]`) y **etiqueta** (`.tag`).

## Do's and Don'ts

- Do: usar un azulejo de sección solo para identificar la sección; un único color de acento para acciones.
- Do: mostrar el estado con punto + texto; escribir la interfaz en español de España con verbos de acción.
- Do: comprobar 375 / 768 / 1280 en todos los temas (test_tema.py), sin errores de consola ni desbordamientos.
- Don't: emojis como iconos, texto con degradado, bordes laterales de color en tarjetas, glass decorativo.
- Don't: tarjetas de «número grande + etiqueta» como resumen; un resumen va en una línea de texto con las cifras en
  negrita (ver Repaso) o en datos compactos dentro de un panel (ver Copias).
- Don't: abrir un modal para algo que no necesita proteger el foco; animaciones de más de 260 ms o con rebote.
- Do: foco con contorno sólido de 2 px en `accent` (visible en todos los temas); cambiar de sección o de tema con un
  fundido corto (View Transitions) que la barra lateral no sigue; nada de movimiento con «reducir movimiento».
