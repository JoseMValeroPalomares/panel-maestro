# Fase 3 — comprobación del inventario

Fecha: 2026-11-09 · Rama `interfaz-fase3` (9 commits sobre `d82f264`) · Referencia: `docs/INVENTARIO.md`.

**Resultado: no se ha perdido ninguna función.** Lo que cambia son decisiones aprobadas (D-1…D-6 y la propuesta de
la Fase 2): sitio, aspecto o valor por defecto, nunca la posibilidad de hacer algo. Sin cambios de esquema de BD:
la única preferencia nueva (`tabbar`) va en `ui_prefs`, que es clave-valor.

## Pruebas

| Batería | Resultado |
|---|---|
| `python -m pytest --ignore=tests/e2e` | 412 pasan (incluye `test_themes.py` y `test_iconos.py`, nuevos) |
| `python -m pytest tests/e2e` | 142 pasan, 2 omitidos por diseño (capturas sin `PANEL_SHOTS`) |
| 19 pantallas × Mocha/Claro × 1280/375 táctil | 0 errores de consola, 0 desbordamientos, 0 textos < 12 px |
| Detector de impeccable (páginas renderizadas) | Sin avisos; en el CSS solo orientativos (radios y colores que ya existían) |
| Guía de interfaces web (Vercel) sobre lo cambiado | Un hallazgo (placeholder sin «…»), corregido |

E2E adaptados a una conducta acordada (no a un fallo): captura en escritorio desde el pie de la barra lateral (no
hay FAB), contador del menú = pendientes del Inbox (D-5) e Inbox móvil que empieza en la lista (N-2).

## Shell

| ID | Estado | Detalle |
|---|---|---|
| S-01 | Se conserva · cambia | Mismos grupos y destinos. Vida en otro orden (Comidas, Estudio, Economía, Rendimiento); Repaso y Revisión con icono nuevo; filas de 34 px |
| S-02 | Se conserva | Plegar con botón y `Ctrl+.`, recordado |
| S-03 | Cambia (D-5) | La insignia cuenta lo pendiente del Inbox (antes Inbox + notas + ideas) y va en el color de acento |
| S-04 | Se conserva · mejora | Capturar, Conexiones y Ajustes, ahora siempre visibles |
| S-05 | Cambia (D-4) | Barra móvil por defecto Hoy · Calendario · Tareas · Notas · Más; elegible en Ajustes. Inbox y Comidas, a un toque en «Más» (con la insignia) |
| S-06 | Se conserva · añade | Todo lo de Ajustes sigue; nuevo «Pestañas del móvil»; «Paleta de comandos» se llama «Buscar en todo el panel» |
| S-07 | Se conserva · cambia | Captura igual (tipos, prefijos, fechas). El FAB solo por debajo de 1024 px; en escritorio, pie de la barra y tecla C |
| S-08 | Se conserva · añade | Paleta igual; al final de cada búsqueda, «Buscar … dentro de las notas» (D-3) |
| S-09 – S-14 | Se conservan | Ayuda de atajos, conexiones, avisos, toasts, diálogos (los menús de opción marcan la elegida con icono), sincronía entre pestañas |
| S-15 | Se conserva · añade | Todas las claves de Prefs siguen; nueva `tabbar` |
| S-16 – S-20 | Se conservan | localStorage, enlace de salto, PWA (precachea también las ilustraciones), recursos versionados, login (favicon nuevo) |

## Pantallas

| ID | Estado | Detalle |
|---|---|---|
| P-01 Hoy | Se conserva · cambia | Mismas tarjetas y acciones; Tareas, Comida y Repaso vacías se resumen en una línea con sus enlaces; botón «Buscar»; error con «Reintentar» |
| P-02 Notas | Se conserva · cambia | Todas las acciones del editor siguen, las menos usadas en «Insertar» y «Marcar»; el `# Título` inicial no se repite al leer (el `.md` no cambia); «Seguir escribiendo» en móvil; el filtro de la lista se llama «Filtrar por título o categoría…» |
| P-03 Inbox | Cambia (D-2, N-2) | Abre en «Por procesar» (Todo, Tareas, Ideas y Rutinas siguen); en móvil empieza en la lista (con `?tablero=` empieza en el tablero); tablero intacto |
| P-04 Lista | Se conserva · cambia | Mismas acciones; «Añadir un paso» con `list-plus` y tooltip; prioridad media y baja sin color; «hace…» al pasar el ratón; error con «Reintentar» |
| P-05 Tareas | Se conserva · cambia | Mismos filtros en una barra; en móvil tipo y categoría tras «Filtros (n)» |
| P-06 Calendario | Se conserva · cambia | En Agenda, los bloques de cada rutina plegados en una línea que se despliega; mismas acciones |
| P-07 – P-12 | Se conservan | Rutinas, Revisión, Grafo, Baúl («Para más tarde» con marcador en vez de estrella), Repaso, Buscar («sin resultados» ilustrado) |
| P-13 Comidas | Se conserva · añade | Aviso de semana vacía con «Generar semana»; «quitar franja» con `calendar-off`; favoritos con icono |
| P-14 Economía | Se conserva · añade | Gráfico vacío con su mensaje |
| P-15 Rendimiento | Se conserva · mejora | Insignia sin solaparse con el título; cada semáforo dice qué mide |
| P-16 – P-21 | Se conservan | Estudio, Gestión, Copias (tarjeta del proyecto con el logo), Papelera, login/offline, extensión (icono nuevo), escritorio |

## Atajos, datos, flujos y estados

| ID | Estado |
|---|---|
| K-01 – K-16 | Se conservan todos (comprobados por los E2E de lista, tablero, calendario, paleta y rutinas) |
| D-01 – D-05 | Sin cambios de esquema ni de formato de las notas |
| F-01 – F-13 | Se conservan |
| E-01 – E-13 | Se conservan; E-03 (error) mejora: ilustración, «sin conexión» si no hay red y «Reintentar» en Hoy, lista, Notas, Baúl, Economía, Comidas, Papelera, Grafo, Rendimiento, Rutinas y Calendario |

## Iconos y recursos

| ID | Estado |
|---|---|
| G-01 | Una familia (Lucide ISC) + 1 propio (`panel`), 252 en el sprite; `icon(…, label)`; tooltip; `docs/ICONOS.md` generado |
| G-02 | 11 cambios de la propuesta + «Guardar como plantilla» (★ → `layout-template`), «Repasar» de Hoy (→ `layers`) y los nuevos `list-filter`, `highlighter` y `file-search` |
| G-03 | Un azulejo por sección en los 9 temas |
| G-04 | Icono de la app, favicon adaptable, PWA y extensión nuevos; ilustraciones de estado |
| G-05 | Sin glifos de texto como icono |

## Pendiente fuera de esta fase

- En el calendario, a 375 px con pantalla táctil, el interruptor de rutinas baja a su propia línea (ya pasaba antes:
  los botones miden 44 px en táctil). Se puede compactar en la Fase 4.
