# Propuesta de diseño — Fase 2

Fecha: 2026-11-09 · Base: auditoría `docs/AUDITORIA-UX.md` (39 problemas) · Sin cambios en la aplicación.
Muestra visual: **`docs/muestras/iconos.html`** (ábrela en el navegador; se regenera con `python -m scripts.muestra_iconos`).

## 0. Punto de partida

La identidad se mantiene: herramienta tipo app de sistema de Apple, temas intercambiables con Catppuccin Mocha por
defecto, azulejos de color por sección, Lucide con trazo 1,75 y un solo acento para acciones. No se propone otra
estética: se **refina** lo que hay para que cada señal signifique una sola cosa.

Tres principios guían todos los cambios (salen de la auditoría):

1. **Un sitio para cada cosa.** Lo duplicado pasa a ser un acceso al sitio principal, no una segunda versión.
2. **Lo de hoy, a un pulgar.** En el móvil, lo diario está en la barra inferior y nada tapa el contenido.
3. **Cada señal, un significado.** Un color = una sección; un icono = una idea; el rojo solo para errores y lo urgente.

*Revisión contra lo genérico:* la paleta, la tipografía y el layout vienen fijados por el encargo y por `DESIGN.md`, no
por un estilo por defecto. Lo único nuevo con carácter propio es el logo (azulejos + nodo) y las ilustraciones, que
reutilizan la gramática de los iconos en lugar de importar un estilo de ilustración ajeno.

---

## 1. Paleta

Los 9 temas y sus tokens se conservan. Cambios:

| Token / uso | Ahora | Propuesta |
|---|---|---|
| Azulejos de sección | 12 tokens `--tile-*`; 6 secciones toman prestado el de otra | 18 tokens, uno por sección (nuevos: `--tile-hoy`, `-calendario`, `-revision`, `-repaso`, `-rendimiento`, `-papelera`), generados por tema en `core/themes.py`. **Opción A o B, a elegir** (§7, D-1) |
| Prioridad en tarjetas | Alta y media con fondo de color (casi todo naranja) | **Alta**: bandera y texto en `danger-text` sobre `danger-soft`. **Media**: solo la bandera, en gris. **Baja**: nada |
| Insignia del Inbox | `danger` (rojo) con todo lo pendiente | `accent-fill` y solo lo que está por procesar en el grupo Inbox (§7, D-5) |
| Ilustraciones | — | `--ill-accent`: `accent` (vacío, sin resultados), `success` (hecho), `danger` (error), `warning` (sin conexión) |

Contraste: los azulejos nuevos se comprueban como gráfico (≥ 3:1 entre glifo y fondo) y `test_tema.py` se amplía a los
18 tokens en los 9 temas.

## 2. Tipografía

Sin fuentes nuevas: pila del sistema (SF) + Inter Variable autoalojada, escala Apple 12/13/15/17/20/22/28/34.

- **Mínimo de 12 px en todo** (hoy hay 11 px en la barra inferior, la rejilla del calendario y el mapa de Repaso).
- Etiquetas de la barra inferior: 12 px, peso 600.
- Metadatos de tarjeta (fecha, categoría, pasos): 13 px `text-2`; título de tarea: 15 px `text`.
- Cifras siempre `tabular-nums` (contadores, horas, importes).

## 3. Espaciado y tamaños

- Base de 4 px sin cambios.
- **Objetivos táctiles de 44 px solo con puntero grueso** (`@media (pointer: coarse)`): chips, controles segmentados,
  `btn-sm` y `btn-icon` crecen en el móvil y el escritorio conserva su densidad.
- Nuevo token `--fab-space`: hueco al final de `.page-body` para que el FAB nunca tape el último elemento.
- Barra lateral: filas de 34 px (ahora 38) y pie fijo: Capturar, Conexiones y Ajustes siempre visibles.

## 4. Componentes

| Componente | Qué cambia | Problemas que resuelve |
|---|---|---|
| **Icon** (`icon()` en Jinja y JS) | Parámetro opcional `label` (`role="img"` + `aria-label`; sin él sigue `aria-hidden`). Tamaños con nombre: `sm` 16, base 18, `md` 20, `lg` 24. El sprite incluye los iconos propios (`assets/icons/propios/`) | I-1, I-3, accesibilidad |
| **Tooltip** (`data-tip`) | Sustituye a `title` en los botones de solo icono: sale también con el foco del teclado y no se duplica con el del navegador. En táctil, el texto va visible o en el menú | C-4, A-4 |
| **StateView** (`stateView({kind, title, text, action})`) | Un componente para vacío, hecho, sin resultados, error (con «Reintentar») y sin conexión, con su ilustración. `emptyState()` se conserva como alias: ninguna llamada actual se rompe | E-1, E-2, J-6, J-8 |
| **FilterBar** | Una sola fila: estado (segmentado) · tipo (chips) · categoría · búsqueda · «⋯». En móvil: estado + botón «Filtros (n)» que abre una hoja | J-2, R-2 |
| **TaskCard** | Jerarquía en dos líneas; prioridad según §1; «hace 5 días» solo al pasar el ratón; «Añadir un paso» como `list-plus` con tooltip (siempre visible en táctil) | J-3, C-4 |
| **FAB** | Solo por debajo de 1024 px; reserva `--fab-space` | C-1, R-1 |
| **Barra inferior** | Destinos configurables en Ajustes (Prefs `tabbar`, sin cambio de esquema); por defecto Hoy · Tareas · Calendario · Notas · Más (§7, D-4) | N-3 |
| **Barra lateral** | La navegación se desplaza y el pie queda fijo | N-4 |
| **Barra del editor** | Formato básico visible; «Insertar ▾» (tabla, fórmula, código, calendario, simulación, flashcard, separador, enlace externo, enlazar tarea) y «Marcar ▾» (resumir, entender, está mal). Mismos atajos | C-2, K-4 |
| **Tarjetas de Hoy** | Las vacías se juntan en una línea («También hoy: sin eventos · sin comida planificada · nada que repasar») con sus enlaces | J-9 |

## 5. Layout (wireframes)

**Escritorio, shell y Tareas**

```
┌───────────────┬──────────────────────────────────────────────────────────────┐
│ ▣ Panel     ⇤ │ ▣ Tareas                              [Lista|Cuadrícula] [+]│
│ Planificar    │──────────────────────────────────────────────────────────────│
│  ▣ Hoy        │ [Pendientes 16|Hechas 5|Todas] (Todo)(Tareas)(Ideas)(Rutinas)│
│  ▣ Calendario │ [Categoría ▾] [⌕ Buscar en tareas, ideas y notas…]       [⋯] │
│  ▣ Rutinas    │                                                              │
│  ▣ Tareas     │ ▾ ▣ Inbox 16                                                 │
│  ▣ Inbox   3  │ ┌──────────────────────────────────────────────────────────┐ │
│  ▣ Revisión   │ │ ○  IG · Práctica 2                        13 nov    ⚑   │ │
│ Conocimiento  │ │    Informática Gráfica · ▸ 2 pasos · ↗ Tengo que hacer  │ │
│  …  (desplaza)│ └──────────────────────────────────────────────────────────┘ │
│───────────────│                                                              │
│ + Capturar  C │   (sin FAB en escritorio: la captura está en el pie y con C) │
│ ⚡ Conexiones ●│                                                              │
│ ⚙ Ajustes     │                                                              │
└───────────────┴──────────────────────────────────────────────────────────────┘
```

**Tarjeta de tarea: antes → después**

```
ANTES                                             DESPUÉS
○ IG · Práctica 2                           ⊕     ○ IG · Práctica 2                    13 nov   ⚑
  ▢13 nov [⚑ Prioridad alta] [⌂ Inf. Gráfica]       Informática Gráfica · ▸ 2 pasos · ↗ nota
  ↗ Tengo que hacer   hace 5 días                   (⚑ rojo solo si es alta; ≡+ al pasar o con E)
```

**Móvil, Tareas e Inbox**

```
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│ Tareas           ⌕   ⋯   │   │ Inbox     [Lista|Tablero]│   │ Filtros              ✕   │
│ [Pendientes|Hechas|Todas]│   │ [+ Una tarea o idea…   ] │   │ Tipo  (Todo)(Tareas)…    │
│ [Filtros · 2]            │   │ ○ Ordenar el cuarto      │   │ Categoría  [Todas ▾]     │
│ ▾ Inbox 16               │   │ ○ Mejorar el bot  ⚑      │   │ Buscar  [⌕ …         ]   │
│ ○ GABD · Práctica 4  Hoy │   │ …                        │   │                          │
│   GABD · ↗ nota       ⚑  │   │                          │   │ [Quitar filtros] [Ver 12]│
│ …                        │   │                     (+)  │   └──────────────────────────┘
│                     (+)  │   │                          │      hoja inferior de filtros
│ (hueco: el + no tapa)    │   │                          │
├──────────────────────────┤   ├──────────────────────────┤
│ Hoy  Tareas  Cal.  Notas ⋯│   │ Hoy  Tareas  Cal.  Notas ⋯│
└──────────────────────────┘   └──────────────────────────┘
```

**Hoy en un día tranquilo**

```
Lunes, 9 de noviembre                                       [▢ Calendario] [⌕ Buscar]
2 cosas por hacer hoy · 1 hecha
┌ A continuación: Gimnasio · 19:30 · en 37 min ─────────────────────────────────────┐
[ + Una tarea o idea (e: para eventos)                 ] [Tarea|Idea|Rutina] [Guardar]
┌ Rutinas ─────────────────────┐ ┌ Tareas ──────────────────────┐
│ ○ Lunes 0/12   07:50  🔥1  ▷ │ │ ○ GABD · Práctica 4          │
└──────────────────────────────┘ └──────────────────────────────┘
┌ Rendimiento ─────────────────┐
│ Aún no has registrado el día │ [✎ Registrar]
└──────────────────────────────┘
También hoy: sin eventos · sin comida planificada (Planificar) · nada que repasar
```

**Barra del editor de notas**

```
B I U S </> │ H1 H2 H3 │ 🔗 ☑ • 1. ❝ │ [Insertar ▾] [Marcar ▾] │ ✂ │   1 234 car.  [▢|◫]
```

Alineación: todo a la izquierda (títulos, listas, formularios); solo los estados vacíos van centrados.

## 6. Iconos y recursos gráficos

### Elección de la familia: seguir con Lucide

| Opción | Licencia | Por qué sí / no |
|---|---|---|
| **Lucide** (actual) | ISC | Ya es la base de los 241 iconos del sprite, con trazo 1,75 ajustado al sistema, más de 1 500 iconos (todos los sustitutos necesarios existen), sprite propio sin dependencias en tiempo de ejecución. Cambiar de familia no resuelve ningún problema de la auditoría |
| Phosphor | MIT | Bonita y con pesos, pero obligaría a rehacer los 241 iconos y revisar cada uso y su trazo por defecto no casa con SF |
| Tabler | MIT | Muy parecida a Lucide (trazo 2): cambio sin beneficio |
| Material Symbols | Apache 2.0 | Estética Google, choca con la identidad Apple |

Licencia ISC confirmada en `node_modules/lucide-static/LICENSE` (uso, copia y modificación libres manteniendo el aviso).

### Cambios (11, ver bloque 3 de la muestra)

Repaso `calendar-days` → `layers` · Revisión `history` → `clipboard-check` · Baúl «Para más tarde» `star` →
`bookmark-plus` / `bookmark-check` · «Añadir un paso» `circle-plus` → `list-plus` · Comidas «No usar este día»
`eye-off` → `calendar-off` · Editor «R» → `list-collapse`, «E» → `circle-help` · menús `✓` → icono `check` · Comidas `★`
→ icono `star` · Hoy «Ctrl K» → `search` con el texto «Buscar» · marca `brain` → `panel` (propio).

### Propios (en `assets/`, mismas reglas que Lucide)

- `assets/icons/propios/panel.svg`: logo. Rejilla de 24, trazo 1,75, `currentColor`.
- `assets/icons/app/`: `icon.svg` (oscuro), `icon-claro.svg`, `maskable.svg` (zona segura), `favicon.svg` (cambia con
  `prefers-color-scheme`). En la Fase 3 se rasterizan a los PNG de la PWA (32/180/192/512) con el Chromium de Playwright
  y se copian a la extensión.
- `assets/ilustraciones/`: vacío, hecho, sin resultados, error y sin conexión. Rejilla de 120×96, trazo 2,
  `currentColor` + `--ill-accent`; 0,5–0,75 KB cada una. La carga es el logo con los azulejos encendiéndose por turnos
  (quieto con «reducir movimiento»).

### Organización y reglas

- Fuentes en `assets/`; `scripts/vendor.mjs` construye `static/icons.svg` (Lucide + propios) y
  `static/ilustraciones.svg`. Nada se edita a mano en `static/`.
- `docs/ICONOS.md` se **genera** (nombre, dónde se usa, significado, origen y licencia) para que no se desactualice.
- Todo botón de solo icono lleva `aria-label` y `data-tip`; un icono que transmite información por sí solo lleva `label`.
- Un icono no cambia de significado entre pantallas; si se sustituye, la metáfora sigue siendo reconocible.

## 7. Decisiones que necesito

| ID | Pregunta | Recomendación |
|---|---|---|
| D-1 | Azulejos: **A** (un color por sección; Vida se reordena: Comidas, Estudio, Economía, Rendimiento) o **B** (un color por grupo, el icono distingue) | **A**: mantiene la firma que te gusta y quita las repeticiones exactas |
| D-2 | Inbox frente a Tareas | **Inbox = bandeja + tablero**: su panel muestra solo el grupo Inbox («por procesar») con enlace a Tareas. **Tareas = la lista completa.** No se pierde nada: el selector de grupos del panel del Inbox se conserva, solo cambia el valor por defecto |
| D-3 | Búsquedas | **Ctrl+K (y el botón «Buscar» de Hoy) es la entrada única**; la paleta ofrece «Buscar en el texto de las notas» y abre `/buscar`, que queda como búsqueda avanzada. La búsqueda de la lista de Notas pasa a llamarse «Filtrar notas» (filtra, no busca) |
| D-4 | Barra inferior del móvil por defecto | **Hoy · Tareas · Calendario · Notas · Más**, personalizable en Ajustes. Comidas e Inbox quedan a un toque en Más (con su insignia) |
| D-5 | Insignia del Inbox | **Solo lo pendiente del grupo Inbox**, en color de acento |
| D-6 | Nombre «Inbox» | **Mantenerlo**: ya lo usan la extensión, rofi y la documentación |

## 8. Funciones opcionales (no se implementan sin tu OK)

| # | Idea | Por qué completaría la app |
|---|---|---|
| O-1 | **Procesar el Inbox** uno a uno (convertir, poner fecha, llevar a nota, borrar) con atajos | El Inbox crece porque no hay un ritual para vaciarlo |
| O-2 | **Vistas guardadas en Tareas** (como los filtros de Buscar y Gestión) | «Prácticas de esta semana», «Ideas de la uni»… sin rehacer filtros |
| O-3 | **Etiquetas comunes** a notas y tareas (hoy: etiquetas en notas, categoría en tareas) | Ver juntas la nota y las tareas de una asignatura |
| O-4 | **Texto completo en la paleta** (FTS de las notas, no solo títulos) | Haría innecesaria la página Buscar para el 90 % de los casos |
| O-5 | **Plantillas de nota** (apunte de clase, resumen de tema, práctica) | Empezar una nota con su estructura y sus flashcards |
| O-6 | **Revisión semanal guiada** (vaciar el Inbox, mirar la semana, elegir 3 prioridades) | Convierte la página Revisión en un hábito |
| O-7 | **Modo concentración**: pomodoro web enlazado a una tarea que apunta el bloque en Rendimiento | Une Estudio, Tareas y Rendimiento sin depender del ESP32 |
| O-8 | **Atajos editables** en Ajustes | Hoy solo la tecla de captura es configurable |
| O-9 | **Exportar una nota** a PDF/HTML con LaTeX renderizado | Entregar o imprimir apuntes |

## 9. Plan de la Fase 3 (pasos pequeños, uno o varios commits cada uno)

1. **Tokens y base**: 18 azulejos por tema, mínimo de 12 px, 44 px con puntero grueso, prioridad, `--fab-space`.
2. **Iconos**: el sprite une Lucide y los propios; `icon(…, label)`; `data-tip`; los 11 cambios, área por área;
   `docs/ICONOS.md` generado.
3. **Icono de la app**: PNG de la PWA, favicon, `apple-touch-icon` y extensión.
4. **Shell**: FAB, pie fijo de la barra lateral, barra inferior configurable, insignia.
5. **Estados**: `stateView` con ilustraciones y «Reintentar» en Hoy, lista, portada de Notas, Comidas, Economía…
6. **Lista**: FilterBar y TaskCard (Inbox, Tareas y Hoy a la vez, porque comparten componente).
7. **Pantallas**: Inbox móvil empieza en la lista, título sin repetir y portada en móvil (Notas), barra del editor,
   rutinas plegadas en la Agenda, Rendimiento (solape y explicaciones), Hoy compacto.
8. **Decisiones D-2 y D-3** según lo que elijas.

Cada paso: `pytest`, E2E del área, capturas a 375 y 1280 en Mocha y Claro, y repaso del inventario punto por punto.
**Ningún paso cambia el esquema de la BD**: lo nuevo que hay que recordar (barra inferior, estado de filtros) va en
`ui_prefs`, que es clave-valor.
