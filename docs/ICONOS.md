# Iconos del Panel

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

## Inventario (252 iconos)

| Icono | Significado | Dónde | Origen y licencia |
|---|---|---|---|
| `a-large-small` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `activity` | Rendimiento | `static/js/item-list.js`, `templates/hoy.html`, `templates/index.html`, `templates/rendimiento.html` | Lucide 0.460 (ISC) |
| `alarm-clock` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `apple` | Franja merienda | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `archive` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `archive-restore` | — | `static/js/backups.js`, `static/js/papelera.js` | Lucide 0.460 (ISC) |
| `arrow-left` | Sacar de su elemento, Alinear a la izquierda | `static/js/board.js`, `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `arrow-left-right` | Invertir sentido | `static/js/board.js`, `static/js/economia.js`, `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `arrow-right` | Alinear a la derecha | `static/js/board.js` | Lucide 0.460 (ISC) |
| `arrow-up-down` | Distribuir en vertical, Distribuir en horizontal | `static/js/board.js` | Lucide 0.460 (ISC) |
| `banknote` | — | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `bed` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `beef` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `bell` | Avisos | `static/js/calendar.js`, `static/js/calendario.js`, `static/js/palette.js`, `templates/_layout.html` | Lucide 0.460 (ISC) |
| `bell-ring` | Permitir notificaciones | `static/js/reminders.js` | Lucide 0.460 (ISC) |
| `bold` | Negrita, Negrita (Ctrl+B) | `templates/index.html` | Lucide 0.460 (ISC) |
| `book-open` | Abrir nota | `static/js/reminders.js`, `templates/graph.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `bookmark` | Guardar filtro, Guardar búsqueda | `static/js/board.js`, `static/js/buscar.js`, `static/js/gestion.js`, `templates/buscar.html`, `templates/gestion.html` | Lucide 0.460 (ISC) |
| `bookmark-check` | Guardado para más tarde (Baúl) | `static/js/vault.js` | Lucide 0.460 (ISC) |
| `bookmark-plus` | Guardar para más tarde (Baúl) | `static/js/vault.js` | Lucide 0.460 (ISC) |
| `brain` | — | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `bring-to-front` | Al frente, Traer al frente | `static/js/board.js` | Lucide 0.460 (ISC) |
| `bus` | Transporte | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `calendar` | Calendario / fecha | `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/reminders.js`, `static/js/rendimiento.js`, `templates/calendario.html`, `templates/hoy.html`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `calendar-check` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `calendar-clock` | Programar, Programar «, Ver en el calendario | `static/js/calendario.js`, `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `calendar-days` | — | `templates/comidas.html` | Lucide 0.460 (ISC) |
| `calendar-off` | Quitar una comida ese día | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `calendar-plus` | Nuevo evento | `static/js/palette.js` | Lucide 0.460 (ISC) |
| `calendar-range` | — | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `chart-column` | La semana | `templates/revision.html` | Lucide 0.460 (ISC) |
| `chart-line` | Name, Sin registros en este periodo | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `chart-scatter` | Name, Datos insuficientes | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `check` | Hecho / opción elegida | `static/js/board.js`, `static/js/calendar.js`, `static/js/calendario.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/rendimiento.js`, `static/js/routines.js`, `static/js/rutinas.js`, `static/js/ui.js`, `static/js/vault.js` | Lucide 0.460 (ISC) |
| `check-check` | Quitar lo que ya está en el carro | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `chevron-down` | Bajar, Insertar, Alinear abajo | `estudio/static/app.js`, `static/js/board.js`, `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `templates/_layout.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `chevron-left` | Notas, Volver, Anterior | `static/js/calendario.js`, `static/js/routines.js`, `templates/calendario.html`, `templates/comidas.html`, `templates/economia.html`, `templates/index.html`, `templates/rendimiento.html`, `templates/revision.html` | Lucide 0.460 (ISC) |
| `chevron-right` | Siguiente, Día siguiente, Mes siguiente | `static/js/buscar.js`, `static/js/calendario.js`, `static/js/cerebro.js`, `static/js/repaso.js`, `static/js/repos.js`, `static/js/routines.js`, `templates/_layout.html`, `templates/calendario.html`, `templates/comidas.html`, `templates/economia.html`, `templates/rendimiento.html`, `templates/revision.html` | Lucide 0.460 (ISC) |
| `chevron-up` | Subir, Alinear arriba | `static/js/board.js`, `static/js/calendar.js`, `static/js/gestion.js`, `static/js/item-list.js`, `static/js/rutinas.js` | Lucide 0.460 (ISC) |
| `circle` | Óvalo (O) | `static/js/calendar.js`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `circle-check` | Bien, Name, kcal. | `comidas/static/js/comidas.js`, `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/hoy.js`, `static/js/rendimiento.js`, `static/js/repaso.js`, `static/js/routines.js`, `static/js/ui.js`, `static/js/vault.js`, `templates/revision.html` | Lucide 0.460 (ISC) |
| `circle-dashed` | Sin datos | `static/js/hoy.js`, `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `circle-dollar-sign` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `circle-dot` | Notas sin enlaces | `templates/graph.html` | Lucide 0.460 (ISC) |
| `circle-help` | Marcar para entender mejor | `static/js/cerebro.js` | Lucide 0.460 (ISC) |
| `circle-pause` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `circle-play` | — | `static/js/cerebro.js` | Lucide 0.460 (ISC) |
| `circle-plus` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `circle-x` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `clipboard-check` | Revisión semanal | `core/templating.py`, `static/js/palette.js`, `templates/revision.html` | Lucide 0.460 (ISC) |
| `clipboard-list` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `clock` | Name, Empieza a las, Nada pendiente | `comidas/static/js/comidas.js`, `static/js/calendar.js`, `static/js/calendario.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/calendario.html` | Lucide 0.460 (ISC) |
| `clock-3` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `cloud` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `cloud-fog` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `code` | JSON ·, Código en línea, Bloque de código | `static/js/cerebro.js`, `static/js/gestion.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `coffee` | Franja desayuno | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `columns-2` | Centrar en horizontal, Editor y previsualización | `static/js/board.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `columns-3` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `command` | Atajo Ctrl | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `cookie` | Franja extras | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `copy` | Duplicar, Copiar «, Copiar enlace | `static/js/board.js`, `static/js/calendar.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/gestion.html`, `templates/inbox.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `copy-plus` | Primero y segundo, Primero y segundo en, Añadir primero y segundo | `comidas/static/js/comidas.js`, `static/js/calendario.js` | Lucide 0.460 (ISC) |
| `corner-down-right` | Meter como paso de la anterior | `static/js/board.js`, `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `credit-card` | — | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `database-backup` | Copias de seguridad | `core/templating.py`, `static/js/backups.js`, `static/js/palette.js`, `templates/backups.html` | Lucide 0.460 (ISC) |
| `diamond` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `download` | JSON, Tus datos, CSV de días | `comidas/static/js/comidas.js`, `static/js/backups.js`, `static/js/board.js`, `static/js/calendario.js`, `static/js/rendimiento.js`, `templates/economia.html`, `templates/gestion.html` | Lucide 0.460 (ISC) |
| `droplet` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `dumbbell` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `egg` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `ellipsis` | Más acciones | `comidas/static/js/comidas.js`, `static/js/backups.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/_layout.html`, `templates/calendario.html`, `templates/comidas.html`, `templates/inbox.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `ellipsis-vertical` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `eraser` | Borrador (E), Vaciar el tablero | `static/js/board.js`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `external-link` | Abrir, Abrir la nota, Enlace externo | `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/economia.js`, `static/js/item-list.js`, `static/js/repos.js`, `static/js/vault.js`, `templates/estudio.html`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `eye` | Previsualizar | `templates/index.html` | Lucide 0.460 (ISC) |
| `eye-off` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `file-json` | Exportar como JSON | `static/js/board.js` | Lucide 0.460 (ISC) |
| `file-plus` | Nueva nota, Llevar a una nota… | `static/js/item-list.js`, `static/js/palette.js` | Lucide 0.460 (ISC) |
| `file-search` | Buscar « | `static/js/palette.js` | Lucide 0.460 (ISC) |
| `file-text` | Notas | `static/js/calendar.js`, `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `file-up` | Importar JSON… | `static/js/board.js` | Lucide 0.460 (ISC) |
| `files` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `film` | Ocio | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `filter` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `fish` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `flag` | Prioridad | `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `flame` | Racha | `static/js/calendario.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `templates/graph.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `folder` | — | `static/js/item-list.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `folder-tree` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `gauge` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `gift` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `git-branch` | Proyecto | `static/js/board.js`, `templates/backups.html` | Lucide 0.460 (ISC) |
| `globe` | Web, Web y artículos | `static/js/vault.js`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `graduation-cap` | Estudio | `core/templating.py`, `static/js/board.js`, `static/js/economia.js`, `static/js/palette.js`, `static/js/rendimiento.js`, `templates/estudio.html` | Lucide 0.460 (ISC) |
| `grid-3x3` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `grip-vertical` | Mover «, Arrastra para colocarlo: toma la hora de ese sitio | `static/js/calendario.js`, `static/js/item-list.js`, `static/js/rutinas.js` | Lucide 0.460 (ISC) |
| `group` | Agrupar (Ctrl+G) | `static/js/board.js` | Lucide 0.460 (ISC) |
| `hand` | Desplazar (H), Desplazar (H, o Espacio + arrastrar) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `hand-coins` | Deudas | `static/js/economia.js`, `templates/economia.html` | Lucide 0.460 (ISC) |
| `hash` | — | `templates/index.html` | Lucide 0.460 (ISC) |
| `heading-1` | Título 1 | `templates/index.html` | Lucide 0.460 (ISC) |
| `heading-2` | Título 2 | `templates/index.html` | Lucide 0.460 (ISC) |
| `heading-3` | Título 3 | `templates/index.html` | Lucide 0.460 (ISC) |
| `heart-pulse` | Salud | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `highlighter` | Marcar el párrafo | `templates/index.html` | Lucide 0.460 (ISC) |
| `history` | Historial (versiones, seguir escribiendo, registro) | `static/js/buscar.js`, `static/js/cerebro.js`, `static/js/rendimiento.js`, `templates/revision.html` | Lucide 0.460 (ISC) |
| `hourglass` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `house` | Casa | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `image` | Personalizar fondo, Fondo del panel ESP32 | `templates/estudio.html` | Lucide 0.460 (ISC) |
| `image-down` | Exportar como PNG | `static/js/board.js` | Lucide 0.460 (ISC) |
| `inbox` | Inbox | `static/js/buscar.js`, `static/js/inbox.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/ui.js`, `templates/_layout.html`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `info` | Con 3 pesajes en al menos una semana verá | `comidas/static/js/comidas.js`, `static/js/ui.js` | Lucide 0.460 (ISC) |
| `italic` | Cursiva, Cursiva (Ctrl+I) | `templates/index.html` | Lucide 0.460 (ISC) |
| `kanban` | Tablero de la tarea… | `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `key-round` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `keyboard` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `landmark` | — | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `layers` | Repaso y flashcards | `static/js/cerebro.js`, `static/js/hoy.js`, `static/js/palette.js`, `templates/hoy.html`, `templates/inbox.html`, `templates/index.html`, `templates/repaso.html` | Lucide 0.460 (ISC) |
| `layout-dashboard` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `layout-grid` | Organizar, Cuadrícula, Ajustar a la cuadrícula | `static/js/board.js`, `templates/inbox.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `layout-template` | Plantillas, Empezar con «Mi día», Aplicar una plantilla… | `comidas/static/js/comidas.js`, `static/js/calendario.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `templates/rutinas.html` | Lucide 0.460 (ISC) |
| `leaf` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `library` | Baúl | `static/js/vault.js`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `lightbulb` | Idea | `comidas/static/js/comidas.js`, `static/js/buscar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/revision.js`, `static/js/rutinas.js`, `templates/_items.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `link` | En una nota, Enlace a otra nota, Asociar una tarea… | `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `templates/graph.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `link-2` | Enlazar una tarea o idea | `static/js/cerebro.js` | Lucide 0.460 (ISC) |
| `list` | Lista | `templates/index.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `list-checks` | Seleccionar, Pasos hechos, Sin categorías | `estudio/static/app.js`, `static/js/board.js`, `static/js/item-list.js`, `templates/inbox.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `list-collapse` | Marcar para resumir | `static/js/cerebro.js` | Lucide 0.460 (ISC) |
| `list-filter` | Filtros | `templates/tareas.html` | Lucide 0.460 (ISC) |
| `list-ordered` | Lista numerada | `templates/index.html` | Lucide 0.460 (ISC) |
| `list-plus` | Añadir un paso | `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `list-todo` | Tareas | `core/templating.py`, `static/js/palette.js`, `static/js/rutinas.js`, `templates/calendario.html`, `templates/hoy.html`, `templates/inbox.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `lock` | Name, Nota cifrada, Versión cifrada | `static/js/board.js`, `static/js/buscar.js`, `static/js/cerebro.js`, `static/js/gestion.js`, `static/js/graph.js`, `templates/graph.html` | Lucide 0.460 (ISC) |
| `lock-open` | Cifrar nota, Nota privada (cifrada en el navegador) | `static/js/board.js`, `static/js/cerebro.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `log-out` | Cerrar sesión | `templates/_layout.html` | Lucide 0.460 (ISC) |
| `map` | Minimapa, Minimapa (M) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `map-pin` | — | `static/js/calendar.js` | Lucide 0.460 (ISC) |
| `maximize-2` | Pantalla completa | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `menu` | Insertar, Organizar, Plantillas | `comidas/static/js/comidas.js`, `static/js/backups.js`, `static/js/item-list.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/calendario.html`, `templates/comidas.html`, `templates/gestion.html`, `templates/inbox.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `merge` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `milk` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `minimize-2` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `minus` | Separador, Letra más pequeña, Centrar en vertical | `static/js/board.js`, `static/js/cerebro.js`, `templates/estudio.html` | Lucide 0.460 (ISC) |
| `monitor` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `moon` | Franja cena | `comidas/static/js/comidas.js`, `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `moon-star` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `mouse-pointer-2` | Seleccionar (V), Seleccionar y mover (V) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `move` | A Ideas, Al Inbox | `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `move-right` | Conector (A), Conector: arrastra de una forma a otra (A) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `move-vertical` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `music` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `notebook-pen` | Notas | `core/templating.py`, `static/js/cerebro.js`, `static/js/gestion.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/rendimiento.js`, `templates/_layout.html`, `templates/gestion.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `notebook-text` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `octagon-alert` | Alerta | `static/js/hoy.js`, `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `palette` | Colores | `templates/calendario.html` | Lucide 0.460 (ISC) |
| `panel` | Marca del Panel (tres azulejos y un nodo enlazado) | `templates/backups.html` | Propio (MIT del proyecto) |
| `panel-left` | Plegar o desplegar el menú | `static/js/palette.js`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `panel-left-close` | Plegar menú, Plegar menú (Ctrl+.) | `templates/_layout.html` | Lucide 0.460 (ISC) |
| `panel-left-open` | Plegar menú, Plegar menú (Ctrl+.) | `templates/_layout.html` | Lucide 0.460 (ISC) |
| `panel-right` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `pause` | — | `estudio/static/app.js`, `static/js/routines.js` | Lucide 0.460 (ISC) |
| `pencil` | Editar | `comidas/static/js/comidas.js`, `estudio/static/app.js`, `static/js/board.js`, `static/js/cerebro.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/rendimiento.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/comidas.html`, `templates/graph.html`, `templates/inbox.html`, `templates/index.html`, `templates/rendimiento.html` | Lucide 0.460 (ISC) |
| `piggy-bank` | — | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `pin` | Name, Anotaciones, Nada pendiente | `comidas/static/js/comidas.js`, `static/js/cerebro.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `pin-off` | — | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `play` | Iniciar, Empezar, Ejecutar | `estudio/static/app.js`, `static/js/calendario.js`, `static/js/cerebro.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/routines.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/estudio.html` | Lucide 0.460 (ISC) |
| `plug-zap` | Estado de las conexiones | `static/js/palette.js`, `static/js/rendimiento.js`, `templates/_layout.html` | Lucide 0.460 (ISC) |
| `plus` | Crear / capturar | `comidas/static/js/comidas.js`, `static/js/board.js`, `static/js/cerebro.js`, `static/js/economia.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/rendimiento.js`, `static/js/routines.js`, `static/js/rutinas.js`, `static/js/ui.js`, `templates/_layout.html`, `templates/calendario.html`, `templates/comidas.html`, `templates/economia.html`, `templates/estudio.html`, `templates/inbox.html`, `templates/index.html`, `templates/rutinas.html`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `printer` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `quote` | Cita | `templates/index.html` | Lucide 0.460 (ISC) |
| `receipt` | Name | `static/js/economia.js`, `templates/economia.html` | Lucide 0.460 (ISC) |
| `redo-2` | Rehacer, Rehacer (Ctrl+Shift+Z) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `refresh-cw` | Reintentar, Llegó desde, Sincronizar ahora (iCloud y ESP32) | `static/js/calendar.js`, `static/js/calendario.js`, `templates/estudio.html` | Lucide 0.460 (ISC) |
| `repeat` | Rutina | `static/js/board.js`, `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/reminders.js`, `static/js/rendimiento.js`, `static/js/revision.js`, `static/js/rutinas.js`, `templates/_items.html`, `templates/calendario.html`, `templates/economia.html`, `templates/hoy.html`, `templates/inbox.html`, `templates/revision.html`, `templates/rutinas.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `replace` | Pegar estilo | `static/js/board.js` | Lucide 0.460 (ISC) |
| `rotate-ccw` | Reintentar / restaurar | `static/js/backups.js`, `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/rendimiento.js`, `static/js/tareas-grid.js`, `static/js/ui.js`, `templates/estudio.html` | Lucide 0.460 (ISC) |
| `rows-3` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `ruler` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `salad` | Ingredientes | `static/js/gestion.js`, `templates/gestion.html` | Lucide 0.460 (ISC) |
| `save` | Guardar, Guardar ahora, Guardar selección | `static/js/board.js`, `static/js/cerebro.js`, `static/js/rendimiento.js`, `templates/comidas.html`, `templates/graph.html`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `scale` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `scan` | Ajustar a pantalla, Ajustar a pantalla (F) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `scissors` | Dividir en nota nueva, Mover selección a nota nueva, Mover la selección a una nota nueva | `static/js/cerebro.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `search` | Buscar | `comidas/static/js/comidas.js`, `static/js/cerebro.js`, `static/js/palette.js`, `static/js/ui.js`, `static/js/vault.js`, `templates/_layout.html`, `templates/buscar.html`, `templates/comidas.html`, `templates/economia.html`, `templates/gestion.html`, `templates/hoy.html`, `templates/index.html`, `templates/tareas.html`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `send` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `send-to-back` | Al fondo, Enviar al fondo | `static/js/board.js` | Lucide 0.460 (ISC) |
| `settings` | Ajustes | `templates/_layout.html` | Lucide 0.460 (ISC) |
| `shapes` | Plantilla | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `share` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `shield-check` | Name, Nada pendiente, Ninguna regla salta hoy. | `static/js/backups.js`, `static/js/rendimiento.js`, `static/js/repos.js`, `templates/backups.html` | Lucide 0.460 (ISC) |
| `shirt` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `shopping-bag` | Compras, Quiero comprar | `static/js/economia.js`, `templates/economia.html` | Lucide 0.460 (ISC) |
| `shopping-cart` | Name, A la compra, Supermercado | `comidas/static/js/comidas.js`, `static/js/economia.js`, `templates/comidas.html` | Lucide 0.460 (ISC) |
| `shuffle` | Una al azar, Abrir una nota al azar para repasar | `static/js/cerebro.js`, `templates/index.html` | Lucide 0.460 (ISC) |
| `sigma` | Fórmula LaTeX | `static/js/cerebro.js` | Lucide 0.460 (ISC) |
| `skip-back` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `skip-forward` | Saltar | `static/js/routines.js`, `static/js/rutinas.js` | Lucide 0.460 (ISC) |
| `slash` | — | `static/js/board.js` | Lucide 0.460 (ISC) |
| `sliders-horizontal` | Panel de propiedades, Ajustes de Rendimiento, Propiedades: relleno, borde, texto, conector, bloquear (Ctrl | `templates/inbox.html`, `templates/rendimiento.html` | Lucide 0.460 (ISC) |
| `smartphone` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `smile` | Cómo estás | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `sparkles` | Name, Auto, Modelos de IA | `comidas/static/js/comidas.js`, `static/js/rendimiento.js`, `templates/graph.html` | Lucide 0.460 (ISC) |
| `spline` | — | `static/js/board.js` | Lucide 0.460 (ISC) |
| `split` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `square` | Caja (R), Solo editor | `templates/inbox.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `square-check` | Tarea | `static/js/buscar.js`, `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/reminders.js`, `static/js/rendimiento.js`, `static/js/revision.js`, `static/js/rutinas.js`, `templates/_items.html`, `templates/index.html`, `templates/tareas.html` | Lucide 0.460 (ISC) |
| `square-dashed` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `square-pen` | Nueva nota | `static/js/cerebro.js`, `templates/gestion.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `star` | Favorito | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `star-off` | — | `comidas/static/js/comidas.js` | Lucide 0.460 (ISC) |
| `sticky-note` | Nota adhesiva (S) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `strikethrough` | Tachado | `templates/index.html` | Lucide 0.460 (ISC) |
| `sun` | Hoy | `static/js/palette.js`, `templates/hoy.html` | Lucide 0.460 (ISC) |
| `sun-moon` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `sunrise` | Mañana | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `sunset` | Tarde | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `table` | CSV ·, Tabla, Ver como tabla | `static/js/cerebro.js`, `static/js/gestion.js`, `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `table-2` | Gestión | `core/templating.py`, `templates/gestion.html`, `templates/index.html` | Lucide 0.460 (ISC) |
| `tag` | — | `static/js/item-list.js` | Lucide 0.460 (ISC) |
| `tags` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `target` | Presupuestos | `comidas/static/js/comidas.js`, `static/js/rendimiento.js`, `templates/economia.html` | Lucide 0.460 (ISC) |
| `thermometer` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `timer` | Duración | `static/js/item-list.js`, `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `trash` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `trash-2` | Borrar / Papelera | `comidas/static/js/comidas.js`, `core/templating.py`, `estudio/static/app.js`, `static/js/backups.js`, `static/js/board.js`, `static/js/calendar.js`, `static/js/cerebro.js`, `static/js/economia.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/papelera.js`, `static/js/rendimiento.js`, `static/js/routines.js`, `static/js/rutinas.js`, `static/js/vault.js`, `templates/comidas.html`, `templates/gestion.html`, `templates/inbox.html`, `templates/papelera.html` | Lucide 0.460 (ISC) |
| `trending-down` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `trending-up` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `triangle-alert` | Aviso / marcar como erróneo | `comidas/static/js/comidas.js`, `static/js/backups.js`, `static/js/cerebro.js`, `static/js/gestion.js`, `static/js/hoy.js`, `static/js/item-list.js`, `static/js/rendimiento.js`, `static/js/repos.js`, `static/js/ui.js`, `templates/backups.html` | Lucide 0.460 (ISC) |
| `type` | Texto (T) | `static/js/board.js`, `templates/inbox.html` | Lucide 0.460 (ISC) |
| `underline` | Subrayado | `templates/index.html` | Lucide 0.460 (ISC) |
| `undo-2` | Deshacer, Deshacer (Ctrl+Z) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `ungroup` | Desagrupar (Ctrl+Shift+G) | `static/js/board.js` | Lucide 0.460 (ISC) |
| `unlink` | Quitar «, Quitar del bloque, Quitar de la rutina | `static/js/cerebro.js`, `static/js/item-list.js`, `static/js/rutinas.js` | Lucide 0.460 (ISC) |
| `upload` | Name, Elegir imagen, Primera subida | `static/js/repos.js`, `templates/backups.html`, `templates/estudio.html`, `templates/gestion.html` | Lucide 0.460 (ISC) |
| `user` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `utensils` | Comida | `static/js/economia.js` | Lucide 0.460 (ISC) |
| `utensils-crossed` | Comidas / franja comida | `comidas/static/js/comidas.js`, `core/templating.py`, `static/js/gestion.js`, `static/js/palette.js`, `templates/comidas.html`, `templates/gestion.html`, `templates/hoy.html` | Lucide 0.460 (ISC) |
| `volume-2` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `wallet` | Economía | `static/js/economia.js`, `templates/economia.html`, `templates/hoy.html` | Lucide 0.460 (ISC) |
| `wand-sparkles` | Sustituir por la mejor opción | `comidas/static/js/comidas.js`, `templates/comidas.html` | Lucide 0.460 (ISC) |
| `waypoints` | Grafo | `static/js/graph.js`, `templates/graph.html` | Lucide 0.460 (ISC) |
| `wheat` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `wifi` | — | dinámico (nombre construido en el código) o reserva | Lucide 0.460 (ISC) |
| `wifi-off` | Sin conexión | `templates/estudio.html` | Lucide 0.460 (ISC) |
| `workflow` | Plan de ejecución | `static/js/board.js` | Lucide 0.460 (ISC) |
| `x` | Cerrar / quitar | `comidas/static/js/comidas.js`, `static/js/board.js`, `static/js/buscar.js`, `static/js/calendar.js`, `static/js/calendario.js`, `static/js/cerebro.js`, `static/js/economia.js`, `static/js/gestion.js`, `static/js/item-list.js`, `static/js/palette.js`, `static/js/papelera.js`, `static/js/reminders.js`, `static/js/rendimiento.js`, `static/js/routines.js`, `static/js/rutinas.js`, `static/js/status.js`, `templates/_items.html`, `templates/_layout.html`, `templates/backups.html`, `templates/comidas.html`, `templates/estudio.html`, `templates/gestion.html`, `templates/graph.html`, `templates/index.html`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `youtube` | Vídeos | `static/js/vault.js`, `templates/vault.html` | Lucide 0.460 (ISC) |
| `zap` | — | `static/js/rendimiento.js` | Lucide 0.460 (ISC) |
| `zoom-in` | Acercar, Acercar (+) | `templates/inbox.html` | Lucide 0.460 (ISC) |
| `zoom-out` | Alejar, Alejar (-) | `templates/inbox.html` | Lucide 0.460 (ISC) |
