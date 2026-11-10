# Inventario funcional del Panel

Fecha: 2026-11-09 · Base: commit `7e841e1` (rama `main`).
Hecho leyendo el código (plantillas, JS, CSS, routers, migraciones y tests), volcando las rutas desde OpenAPI y el
esquema de las BDs creado en un directorio temporal.

Sirve de lista de comprobación: **después de cada fase se repasa punto por punto**. Cada punto lleva un identificador
(`S-…` shell, `P-…` pantalla, `K-…` atajo, `D-…` datos, `F-…` flujo, `E-…` estado o caso límite, `G-…` gráfico) para
poder decir «se conserva» o «cambia» sin ambigüedad.

---

## 1. Estructura, stack y dependencias

```
main.py                 app raíz (Cerebro) + monta /estudio y /comidas; compone los tres lifespan; CSP y GZip
core/                   config (.env), auth (cookie/Bearer), security (scrypt/HMAC), db, files (atomic_write),
                        errors, logging, migrations, undo (papelera), natural_date, tabular (CSV/JSON),
                        templating (nav + icon() + asset()), themes, pwa (manifest + sw.js)
app/                    Cerebro y servicios: notas, ítems (tareas/ideas/rutinas), calendario, rutinas, tableros,
                        baúl, grafo, búsqueda FTS5, repaso, revisión, economía, rendimiento (+ IA), copias,
                        dotfiles, publicar, papelera, prefs, avisos, captura, resumen de Hoy, extensión
comidas/                sub-app FastAPI: ingredientes, platos, plan semanal, generador, compra, objetivos, peso
estudio/                sub-app FastAPI: puente con el ESP32 (WebSocket), iCloud CalDAV, nota a repasar, Spotify
templates/              Jinja: _layout.html (shell común), _items.html (captura) y una plantilla por pantalla
static/css|js           ds.css (sistema de diseño) + themes.css (9 temas) + un CSS/JS por pantalla, sin build
static/vendor           marked, DOMPurify, KaTeX, highlight.js, vis-network, fabric (vendorizadas, sin CDN)
static/icons.svg        sprite Lucide (241 símbolos) generado desde scripts/icons.txt
static/icons/           icono de la app (SVG + PNG 32/180/192/512 + maskable)
EXTENSION PANEL/        extensión de Firefox 2.5.1 (Inbox, Baúl, agenda, cola sin conexión)
scripts/                demo, set_password, desktop_token, build_extension, vendor.mjs, themes, publicar.sh,
                        desktop/ (rofi: captura y agenda; Waybar: panel_agenda.py)
esp32_deskclock/        firmware del reloj de escritorio (C++, fuera del alcance web)
tests/                  ~342 tests pytest (API, lógica, migraciones, seguridad) + 115 E2E con Playwright
```

**Backend**: Python 3.14 · FastAPI 0.141 / Starlette 1.6 · Pydantic 2 · Uvicorn · Jinja2 · APScheduler (copias
03:30, purga de papelera 03:40, miniaturas al arrancar) · SQLite (WAL) · python-frontmatter · httpx · BeautifulSoup +
lxml (scraper del Baúl, con protección SSRF) · ddgs · Pillow · aiohttp (WebSocket ESP32) · caldav + icalendar (iCloud)
· colorthief.

**Frontend**: HTML de servidor (Jinja) + JS clásico sin framework ni build (IIFE con `window.*`), CSS propio con tokens.
Librerías vendorizadas por `npm run build` (Node solo para eso): marked 9.1.6, DOMPurify 3.1.6, KaTeX 0.16.9,
highlight.js 11.9.0, vis-network 9.1.9, fabric 5.3.0 (heredado), lucide-static ^0.460.0, Inter Variable (Fontsource).

**Datos**: `data/notes/*.md` (fuente de verdad de las notas) · `data/brain.db` (caché de notas + todo lo demás) ·
`comidas/data/comidas.db` · `static/uploads/` · `backups/*.zip` · `data/trash/` · `estudio/calendar_sync_v2.json` ·
`data/llm_modelos.json` · `.env` (secretos).

**Despliegue**: servicio de usuario `panel-maestro` (uvicorn :8000). PWA instalable (manifest + service worker).

---

## 2. Shell común (todas las pantallas, `templates/_layout.html` + `static/js/ui.js`)

| ID | Elemento | Qué hace |
|---|---|---|
| S-01 | Barra lateral (≥1024 px) | Marca «Panel» → /hoy; grupos plegables y recordados (`nav-folded`): **Planificar** (Hoy, Calendario, Rutinas, Tareas, Inbox, Revisión), **Conocimiento** (Notas, Grafo, Baúl, Repaso, Buscar), **Vida** (Comidas, Economía, Estudio, Rendimiento), **Sistema** (Gestión, Copias, Papelera). El grupo de la página actual no se pliega. |
| S-02 | Plegar menú a iconos | Botón y `Ctrl+.`; se guarda en servidor (`nav`) y en localStorage (sin parpadeo). Sin preferencia sigue el ancho (<1024 → plegado). |
| S-03 | Contador del Inbox | Insignia en la barra lateral y en la pestaña móvil (`/api/items/counts`), «99+» como tope; se refresca con cada escritura. |
| S-04 | Pie de la barra | Capturar (abre S-07), Conexiones (S-10, con punto de estado), Ajustes (S-06). |
| S-05 | Barra de pestañas (<768 px) | Hoy, Notas, Inbox, Comidas, Más (abre S-06). Carril de iconos en tablet. |
| S-06 | Hoja «Ajustes / Más» | Estado de conexiones, paleta de comandos, lista de todas las secciones, **selector de tema** (9: Mocha por defecto, Latte, Claro, Oscuro, Nord, Dracula, Gruvbox, Tokyo Night, Sistema; grupo de radio con flechas; fundido con View Transitions), Avisos y recordatorios, tecla de la captura (una letra, no G/E/X), Cerrar sesión. |
| S-07 | Captura rápida | Modal global con `capture_form` (tipo tarea / idea / rutina, prefijos `t:` `i:` `r:` `e:` `g:`, fecha en lenguaje natural). FAB «+» en móvil (no en Notas). |
| S-08 | Paleta de comandos | `Ctrl+K`: búsqueda aproximada en acciones, notas, tareas/ideas/rutinas, eventos cercanos y platos; muestra el atajo de cada acción; índice cacheado 2 min. |
| S-09 | Ayuda de atajos | `?` abre la lista de atajos generales + los de la página actual. |
| S-10 | Estado de conexiones | `/api/status`: ESP32, iCloud, copias…; punto de color en la barra. |
| S-11 | Avisos | `reminders.js`: notificaciones del navegador para eventos/tareas con aviso (`/api/reminders`), ajustes en `reminders` (Prefs). |
| S-12 | Toasts | Región `aria-live`; acción opcional («Deshacer», 12 s); errores de API como toast (salvo `quiet`). |
| S-13 | Diálogos del sistema | `openModal/closeModal` sobre `<dialog>` (foco atrapado, Esc, foco devuelto, hoja inferior en móvil, `--vvh` con teclado), `uiConfirm` (con `danger`), `uiAlert`, `uiPrompt` (multilínea con Ctrl+Intro), `uiPick` (selector con búsqueda), `openMenu` (menú contextual con flechas/Esc/Tab). |
| S-14 | Sincronía entre pestañas | `BroadcastChannel('panel-datos')`: cada escritura por `api()` se anuncia; las otras pestañas repintan (`onDataChange`). Al volver el foco se recarga. |
| S-15 | Preferencias (`window.Prefs`) | `/api/prefs` con caché en localStorage, cola de «sucios» sin conexión y migración de claves antiguas. Claves: `nav`, `nav-folded`, `notes-fold`, `items-fold`, `item-notes-hidden`, `capture-key`, `calendar-view`, `inbox-type`, `inbox-sidebar`, `inbox-pane`, `tareas-view`, `tareas-sizes`, `tareas-filters`, `reminders`. |
| S-16 | localStorage directo | `theme`, `nav`, `prefs-cache`, `previewPct` (Notas), `board-*` (tablero), `comidas_tab`, `comidas_mode`. |
| S-17 | Enlace «Saltar al contenido», `main` con `tabindex=-1`, `aria-current` en navegación. |
| S-18 | PWA | `/manifest.webmanifest` (inicio /hoy, accesos Notas/Inbox/Comidas), `/sw.js` (versión = hash del shell; red primero en páginas y API, stale-while-revalidate en recursos, página `offline.html`). Solo se registra en contexto seguro. Toasts «Sin conexión» / «Conexión recuperada». |
| S-19 | Recursos versionados | `asset()` añade `?v=hash` a CSS/JS/sprite para que el SW nunca sirva uno viejo. |
| S-20 | Login | `/login` (contraseña, límite 8 intentos/15 min por IP, `next` sin redirecciones externas), `/logout` GET/POST. Cookie firmada 30 días o `Authorization: Bearer` / `X-API-Token`. Comprobación de `Origin` (CSRF). `auth-guard.js` redirige al login si la sesión caduca. |

---

## 3. Pantallas

Formato: ruta · plantilla · JS/CSS · funciones · estados (carga / vacío / error) · casos límite.

### P-01 Hoy — `/hoy` (`hoy.html`, `hoy.js`, `hoy.css`)
- Subtítulo con fecha y resumen; enlace «lo siguiente que toca» (`hoyNext`).
- Captura compacta en línea.
- Tarjetas: **Agenda** (eventos y bloques del día), **Rutinas** (marcar), **Tareas** (pendientes/vencidas), **Comida del
  día** (plan de Comidas), **Dinero** (gasto día/mes; oculta si no hay datos), **Rendimiento** (4 semáforos), **Repaso**.
- Acciones de cabecera: Calendario, Paleta (Ctrl K). Datos: `GET /api/today`, `/api/rendimiento/panel`.
- Estados: skeleton por tarjeta; vacío por tarjeta (`empty()` propio de hoy.js).

### P-02 Notas — `/` y `/?note=<id>` (`index.html`, `cerebro.js` 1524 l., `cerebro.css`)
- **Cabecera**: Repasar (nota al azar, `/api/notes/recall`), Flashcards (con insignia de pendientes), Salud del cerebro,
  Gestor de notas (tabla rápida + «Copiar para IA»), racha de días.
- **Lista**: búsqueda (`/` enfoca), chips de estado (Todas, Por escribir, En desarrollo, Consolidado, Índices), chips de
  etiquetas, **árbol de categorías** plegable (recordado en `notes-fold`), orden manual por arrastre
  (`/api/notes/{id}/move`), contadores; pie con Anotaciones y Nueva nota.
- **Portada** (sin nota abierta): `GET /api/notes-home` (recientes, por categoría…); `/` es siempre la portada y no se
  reabre la última nota. Atrás/«Notas» vuelve a ella (`setNoteUrl`, `closeNote`).
- **Nota**: migas de categoría, indicador de guardado, modo Lectura/Edición (E), menú (Guardar ahora, Mover selección a
  nota nueva, Copiar enlace, Enlazar tarea o idea, Historial de versiones, Eliminar). Título, categoría con
  autocompletado (combobox), etiquetas, estado (menú), **cifrado en el navegador** (AES-GCM 256, PBKDF2 150 000), enlaces
  a tareas/ideas (`[[tarea:N]]`).
- **Editor Markdown**: barra de formato (negrita, cursiva, subrayado, tachado, código, H1–H3, wikilink `[[…]]` con
  Ctrl+K, enlazar tarea, calendario incrustado, enlace externo, listas, tarea `- [ ]`, cita, separador, tabla, fórmula
  LaTeX, bloque de código, simulación interactiva, flashcard `pregunta >> respuesta`, dividir selección en nota nueva,
  marcas de anotación R / E / ⚠), contador de caracteres, previsualización (solo editor / dividido, `previewPct`),
  previsualización a pantalla completa en móvil. Listas que continúan con Intro; sangría.
- **Lectura**: marked + DOMPurify, KaTeX, highlight.js (claro/oscuro), wikilinks navegables, casillas que se marcan
  (sincronizan con `inbox`), calendarios incrustados (`Calendar.mountEmbeds`), simulaciones en `iframe sandbox`,
  notas relacionadas, backlinks, sugerencias de wikilinks.
- **Guardado**: autoguardado con retardo, `savePending` antes de cerrar; si falla queda pendiente y reintenta a los 5 s.
- **Modales**: Nueva nota (título + categoría «A - B», error en línea), Contraseña de nota privada, Flashcards (SM-2:
  Otra vez / Difícil / Bien / Fácil; Espacio revela), Salud del cerebro, Anotaciones, Gestor, Historial de versiones.
- Estados: skeleton de 9 filas; 9 llamadas a `emptyState`; nota cifrada → pantalla de bloqueo; nota borrada desde otra
  pestaña → recarga (`refreshFromOtherTab`).

### P-03 Inbox — `/inbox` (`inbox.html`, `inbox.js`, `inbox-layout.js`, `board.js` 2226 l., `board.css`, `inbox.css`)
- **Panel lateral** (plegable, `inbox-sidebar`/`inbox-pane`): pestañas Lista · 7 días · Plantilla; lista de ítems
  (componente P-04) filtrada por estado y tipo (`inbox-type`); «Gestionar en Tareas»; calendario de 7 días; formas y
  plantillas del tablero; rutinas («Poner una»).
- **Tablero SVG propio** (formato 2): varios tableros (crear, renombrar, eliminar, vaciar); tablero de una tarea
  (`boards.item_id`, plantillas Proyecto / Plan de ejecución / Estudio de un tema); herramientas seleccionar, mano,
  caja, óvalo, nota adhesiva, texto, conector, lápiz, goma; propiedades (relleno, borde, color, tamaño, trazo, guiones),
  rejilla, capas (traer al frente / enviar al fondo), copiar, borrar, agrupar/desagrupar (Ctrl+G), alinear y
  distribuir, deshacer/rehacer (historial sin límite práctico), zoom −/100 %/+, ajustar, pantalla completa, minimapa.
  Tarjetas enlazadas a ítems del Inbox con sus pasos vivos (`cardSteps`; quitar un paso solo lo oculta). Exportar
  PNG / SVG / JSON, importar JSON, plantillas propias (`/api/board-templates`).
- Estados: tablero vacío, guardado incremental (`/api/boards/{id}/canvas`).

### P-04 Lista de ítems (componente compartido `item-list.js` + `items.js`, `items.css`)
Usado en Inbox, Tareas y (parcialmente) Hoy.
- Grupos: Inbox · Notas (casillas de las notas) · Ideas · Rutinas · Próximos eventos (solo lectura).
- Tarjeta: casilla, texto, prioridad (bandera), fecha/hora, duración, categoría, notas (visibles; ocultar por tarjeta en
  `item-notes-hidden`), pasos (un nivel, plegables con progreso), enlaces a notas, racha (rutinas).
- Acciones (menú): editar en línea, añadir paso (E), prioridad, mover a otro grupo, convertir tarea↔idea↔rutina,
  llevar a una nota, enlazar con nota, ver en calendario, tablero de la tarea, hacer paso a paso (rutinas), eliminar
  (con deshacer). Selección múltiple (X, Mayús+clic) con barra de lote.
- Arrastre (`sortable.js`): reordenar, mover entre grupos, meter como paso («Meter dentro»), sacar; en rejilla usa foto
  fija (`measure`) y espera a que pare el puntero (`SETTLE_MS`). Teclado: ver §4.
- Reglas: un nivel de pasos; padre e hijos del mismo tipo; con pasos no se convierte; en una nota solo tareas.

### P-05 Tareas — `/tareas` (`tareas.html`, `tareas.js`, `tareas-grid.js`)
- Vista Lista / Cuadrícula (R; `tareas-view`; cuadrícula solo ≥768 px) con tarjetas redimensionables (`tareas-sizes`,
  Mayús+flechas). Filtros: estado (Pendientes, Hechas, Todas), tipo (Todo, Tareas, Ideas, Rutinas), categoría,
  búsqueda; recordados (`tareas-filters`). Captura «Nueva tarea o idea». Botón Seleccionar. `?item=<id>` revela una.

### P-06 Calendario — `/calendario` (`calendario.html`, `calendario.js`, `calendar.js`, `calendar.css`)
- Vistas Día · 3 días · Semana · Mes · Agenda (`calendar-view`); Hoy, anterior/siguiente (flechas), mini-mes con puntos.
- Nuevo evento escribiendo en lenguaje natural («dentista mañana 17:00»), editor completo (título, inicio–fin, todo el
  día, aviso, lugar, notas; Ctrl+Intro guarda).
- Tareas con fecha (hora = bloque de tiempo) y rutinas expandidas por bloque; mover/redimensionar un bloque = `PATCH`
  del ítem o «place» de la rutina. Interruptor «Mostrar rutinas». Horario visible configurable (8–22 por defecto).
- Menú: Ir a un día, Rutinas de hoy, Sin fecha, Colores, Horario visible, plantillas de día (guardar/aplicar),
  Sincronizar ahora (iCloud y ESP32), Exportar `.ics`. `?dia=AAAA-MM-DD`.
- Incrustable en notas (bloque ```calendario).

### P-07 Rutinas — `/rutinas` (`rutinas.html`, `rutinas.js`, `routines.js`, `rutinas.css`)
- El día en bloques: selector de día de la semana, línea con hora inicio–fin (24 h, `parseTime`), huecos «Libre»,
  solapes avisados (`clash`), bloques flexibles sin hora al final.
- Por bloque: editar (hora, duración, días L–X–D con `dayPicker`), duplicar, saltar hoy, quitar la hora, subir/bajar
  (Alt+flechas), arrastrar (`/api/routines/{id}/place`, 409 con primer hueco libre), eliminar; tareas asociadas
  (`routine_step`), nueva tarea en el bloque.
- Plantillas de rutina (`/api/routine-templates`, «Mi día»), modo **paso a paso** con temporizador (Intro, S, Espacio).
- Estadísticas y racha (`/api/routines/{id}/stats`, mapa de calor).

### P-08 Revisión semanal — `/revision` (`revision.html`, `revision.js`)
- Semana anterior/siguiente; La semana (gráfico por día), Completadas, Rutinas cumplidas, Registro de cambios
  (`/api/review/log`, «Ver más»).

### P-09 Grafo — `/graph` (`graph.html`, `graph.js`, vis-network)
- Mapa de notas; filtro por estado; colorear por Estado / Repaso / Notas (categoría); chips de etiquetas (atenuar);
  huérfanas resaltables; plegar categorías; panel lateral de la nota; tooltip.
- Modo edición: conectar notas (aristas manuales `/api/graph/edges`), borrar arista, Auto (disposición), Guardar
  disposición (`/api/graph/layout`). Leyenda y estadísticas. Colores del lienzo según tema.

### P-10 Baúl — `/vault` (`vault.html`, `vault.js`, `vault.css`)
- Pestañas Biblioteca · Para más tarde · Vistos (contadores); filtros por tipo (Todo, Vídeos, Web) y categoría;
  búsqueda; agrupado por categoría con orden manual (`/api/resources/{id}/move`).
- Añadir recurso por URL (scraper con miniatura cacheada en local, YouTube con canal), editar, eliminar, marcar para
  más tarde / visto. Pendientes de extraer se reintentan (`checkPendingResources`).

### P-11 Repaso — `/repaso` (`repaso.html`, `repaso.js`)
- Próximas 4 semanas de flashcards (`/api/review/calendar`), días de estudio (mapa), notas que llevan tiempo sin repasar.

### P-12 Buscar — `/buscar` (`buscar.html`, `buscar.js`)
- Texto completo FTS5 (`/api/search`) con resaltado, filtros de estado y área, URL sincronizada, búsquedas recientes y
  guardadas (`/api/saved-filters`).

### P-13 Comidas — `/comidas/` (`comidas.html`, `comidas/static/js/comidas.js` 1176 l., `comidas.css`)
- Pestañas **Plan · Platos · Compra · Ingredientes · Objetivos** (`comidas_tab`).
- **Plan**: semana anterior/siguiente/hoy; 4 comidas o «Comida y cena» (`comidas_mode`); rejilla semanal + panel del
  día con barras de macros, «faltan X kcal», sugerencias; varios platos por comida con gramos editables, papel del
  plato (`rol`), plato doble (primero y segundo), fijar celda, regenerar celda/día, **generador** (tres macros con
  tolerancia, variedad, favoritos), vaciar comida/semana, plantillas de comida, añadir a la compra. Franjas propias con
  días en que se usan.
- **Platos**: buscar, filtro por franja y ★ favoritos, crear/editar (ingredientes en g o unidades, pasos, foto, tags,
  sugerir gramos), avisos Atwater.
- **Compra**: lista manual + desde plato o semana (escalada a la ración), marcar comprado, quitar lo comprado,
  exportar semana (.csv / .txt).
- **Ingredientes**: CRUD con macros por 100 g, validación Atwater, categorías.
- **Objetivos**: perfil (edad, peso, altura, sexo, actividad, objetivo, proteína g/kg, grasa %, ajuste %), vista previa
  TMB/TDEE, **peso y medidas** con gráfico (1 mes / 3 meses / 1 año) y «aplicar ajuste».

### P-14 Economía — `/economia` (`economia.html`, `economia.js`, `economia.css`)
- Mes anterior/siguiente; Tu dinero (cuentas con saldo; añadir cuenta), Quiero comprar (deseos, comprar), resumen y
  categorías, Presupuestos por categoría, Deudas (saldar), Cada mes (recurrentes), Movimientos (buscar, categoría,
  exportar CSV). Captura `g:` desde cualquier sitio.

### P-15 Rendimiento — `/rendimiento` (`rendimiento.html`, `rendimiento.js` 809 l., `rendimiento.css`)
- Día anterior/siguiente; registro rápido del día (sueño, café, luz, entreno, energía, niebla, humor…), bloques de
  estudio por asignatura; pestañas **Hoy** (semáforos) · **Semana/mes** (7/30 días, series SVG) · **Exámenes** (de los
  eventos del calendario) · **Correlaciones** (≥21 días) · **Auditoría** (IA). Ajustes de umbrales. Alertas guardadas
  como tareas. Exportar CSV/JSON. Registrar marca rutinas (entreno, luz, activación).

### P-16 Estudio — `/estudio/` (`estudio.html`, `estudio/static/app.js`, `estudio.css`)
- Estado del ESP32 (Reintentar), Calendario próximos 14 días, Tareas del panel por categorías (crear/editar/borrar,
  enviadas al reloj), Pomodoro (iniciar/pausar, reiniciar, minutos de trabajo y descanso), Notas en el reloj, Fondo del
  panel ESP32 (subir imagen, restaurar). WebSocket directo al ESP32.

### P-17 Gestión — `/gestion` (`gestion.html`, `gestion.js`, `gestion.css`)
- Pestañas Notas / Platos / Ingredientes; tabla con búsqueda sin acentos, filtros rápidos, filtros guardados, orden por
  columna, selección (casillas, Mayús+clic, todo lo visible, Esc), barra flotante: Editar en lote, Duplicar, Exportar,
  Borrar (deshacer). Importar CSV/JSON con previsualización y conflicto (conservar / sobrescribir). Tarjetas en móvil.

### P-18 Copias — `/backups` (`backups.html`, `backups.js`, `repos.js`, `backups.css`)
- Estado, copia manual, lista filtrable por tipo (diaria, semanal, manual, pre-restauración), detalle, descargar,
  borrar, **restaurar** (total o por partes; escribir RESTAURAR; copia previa automática).
- Tarjetas **Dotfiles** y **Publicar el panel** (si existen): Ver (Cambios con diff, Contenido, Historial) y Subir a
  GitHub (sin `--force`, comprobación de secretos).

### P-19 Papelera — `/papelera` (`papelera.html`, `papelera.js`)
- Lista de lo borrado (30 días) por tipo, restaurar, borrar definitivamente, Vaciar.

### P-20 Login (`login.html`) y Sin conexión (`static/offline.html`).

### P-21 Fuera del navegador
- **Extensión de Firefox 2.5.1**: popup Inbox / Baúl / agenda, menús contextuales, `Alt+Mayús+I` / `Alt+Mayús+B`,
  insignia, cola sin conexión, autologin opcional. API: `/api/ext/status`, `/api/inbox`, `/api/capture`, `/api/resources`.
- **Escritorio**: `quick_capture.sh` (rofi, Super+K), `panel_agenda.py` (rofi Super+Alt+K y módulo Waybar).
- **ESP32**: recibe nota a repasar cada 15 min, calendario, tareas, pomodoro.

---

## 4. Atajos de teclado

| ID | Dónde | Atajo | Acción |
|---|---|---|---|
| K-01 | Global | `Ctrl/⌘+K` | Paleta de comandos (en el editor de notas: insertar wikilink) |
| K-02 | Global | `C` (configurable) | Captura rápida |
| K-03 | Global | `/` | Ir a Buscar (en Notas: enfocar la búsqueda de notas) |
| K-04 | Global | `G` + `H C U O I T M D B E R N` | Hoy, Calendario, Rutinas, Notas, Inbox, Tareas, Comidas, Economía, Baúl, Estudio, Revisión, Nota nueva |
| K-05 | Global | `Ctrl+.` | Plegar/desplegar menú |
| K-06 | Global | `?` | Ayuda de atajos |
| K-07 | Diálogos/menús | `Esc`, flechas, `Intro`, `Tab` | Cerrar, moverse, elegir |
| K-08 | Listas de ítems | `Intro` editar · `Espacio` marcar · `Supr/Retroceso` borrar · `E` paso · `X` seleccionar · `↑/↓` foco · `Alt+↑/↓` mover · `Alt+←/→` grupo · `Alt+Mayús+→/←` meter/sacar paso · `Esc` soltar selección · `Ctrl+Intro` guardar edición | |
| K-09 | Tareas | `R` | Lista ↔ cuadrícula; `Mayús+flechas` tamaño de tarjeta |
| K-10 | Notas | `E` editar · `Esc` salir · `Ctrl+S` guardar · en el editor `Ctrl+B` / `Ctrl+I` / `Ctrl+K` (negrita, cursiva, wikilink) · `Intro` continúa la lista · `Intro` en el título pasa al cuerpo · `Espacio` revela la flashcard | |
| K-11 | Calendario | `←/→`, `T`, `D 3 S M A`, `N`, `Ctrl+Intro`, `Espacio` sobre un bloque | Navegar, hoy, vistas, nuevo, guardar, marcar |
| K-12 | Tablero | Herramientas `V H R O S T A P E` · `Espacio` mano temporal · `Supr` borrar · `Esc` soltar · `Intro` editar texto/etiqueta · flechas mover (con `Mayús` a la cuadrícula) · `L` bloquear · `G` ajuste a cuadrícula · `M` minimapa · `F` ajustar · `0` 100 % · `+`/`-` zoom · `Ctrl+Z`/`Ctrl+Mayús+Z`/`Ctrl+Y` · `Ctrl+C/X/V/D/A` · `Ctrl+Alt+C/V` copiar/pegar estilo · `Ctrl+G`/`Ctrl+Mayús+G` agrupar | |
| K-13 | Rutinas | `Ctrl+Intro`, `Alt+↑/↓`; paso a paso `Intro`, `S`, `Espacio` | Guardar, mover, siguiente, saltar, pausa |
| K-14 | Grafo | `Ctrl` (conectar), `Esc` | |
| K-15 | Gestión, Inbox, Rendimiento | flechas en pestañas, `Inicio/Fin`, `Esc` | |
| K-16 | Extensión | `Alt+Mayús+I`, `Alt+Mayús+B` | Inbox, Baúl |

---

## 5. Modelos de datos

### D-01 Notas (`data/notes/**/*.md`, fuente de verdad)
Frontmatter YAML (título, categoría, etiquetas, estado `por-escribir|en-desarrollo|consolidado|indice`, cifrado…) +
cuerpo Markdown. Escritura siempre con `atomic_write`. Historial de versiones (`app/versions.py`).

### D-02 `brain.db` (18 migraciones registradas en `schema_migrations`)
| Área | Tablas |
|---|---|
| Notas (caché) | `notes`, `categories`, `note_order`, `flashcards`, `study_days`, `notes_fts` + `notes_fts_state`, `saved_filters`, `graph_nodes`, `graph_edges` |
| Ítems | `inbox` (tareas/ideas/rutinas y casillas de notas: `note_id`, `note_task`, `note_index`, prioridad, categoría, fecha, hora, duración, `repeat` JSON, aviso, `routine_step`), `item_links`, `item_log`, `routine_checks`, `routine_templates`, `day_templates` |
| Calendario | `events` (hora local Madrid, todo el día con fin exclusivo, `uid`, `source`) |
| Tableros | `boards` (`item_id`), `board_canvas`, `board_templates`, `board_canvas_legacy` |
| Baúl | `resources` |
| Economía | `fin_accounts`, `fin_movements`, `fin_budgets`, `fin_recurring`, `fin_debts`, `fin_wishes` |
| Rendimiento | `rend_dias`, `rend_bloques`, `rend_asignaturas`, `rend_ajustes`, `rend_auditorias`, `rend_alertas`, `llm_uso`, `llm_enfriamiento`, `llm_registro` |
| Sistema | `ui_prefs`, `undo_log`, `schema_migrations`; copias de seguridad de migraciones (`inbox_r2_backup`, `inbox_r3_backup`, `inbox_r3_meta`, `step_times_backup`) |

### D-03 `comidas.db` (3 migraciones)
`ingredients`, `meals`, `meal_ingredients`, `weekly_plan` (`gramos_racion`, `rol`, `is_fixed`), `plan_items`, `franjas`
(`dias`), `meal_templates`, `meal_usage_log`, `shopping_list`, `user_profile`, `body_log`, `undo_log`,
`schema_migrations`.

### D-04 Otros almacenes
`static/uploads/` (imágenes de notas, miniaturas del Baúl, fotos de platos, WebP local) · `data/trash/` ·
`backups/*.zip` (+ `manifest.json` con sha256) · `estudio/calendar_sync_v2.json` · `data/llm_modelos.json` ·
`data/dotfiles_base/` · `.env`.

### D-05 Reglas de integridad que no se pueden romper
- Nunca `INSERT OR REPLACE` en `notes` (cascada a flashcards): `upsert_note`.
- Migraciones aditivas; nunca `DROP` para «arreglar».
- El `.md` manda en texto, estado, orden y anidado de las casillas; la fila guarda id, prioridad, fecha y notas.
- Restaurar el cerebro borra `CALENDAR_STATE` a propósito.

---

## 6. API (agrupada; 250+ rutas)

| Área | Rutas |
|---|---|
| Páginas | `/`, `/hoy`, `/calendario`, `/rutinas`, `/tareas`, `/inbox`, `/revision`, `/graph`, `/vault`, `/repaso`, `/buscar`, `/economia`, `/rendimiento`, `/gestion`, `/backups`, `/papelera`, `/comidas/`, `/estudio/`, `/login` |
| Notas | `GET/POST/DELETE /api/notes/{id}`, `GET /api/notes`, `/recall`, `/rename-category`, `/{id}/status`, `/reviewed`, `/meta`, `/related`, `/wikilink-suggestions`, `/backlinks`, `/links`, `/move`, `/versions[/{vid}[/restore]]`; `/api/categories[/tree|/{id}/notes]`; `/api/annotations`; `/api/notes-home`; `/api/upload-image` |
| Estudio de notas | `/api/flashcards/due|stats|{id}/review`, `/api/streak`, `/api/brain-health`, `/api/review/calendar|week|log` |
| Ítems | `/api/items` (GET/POST), `/counts`, `/bulk`, `/undo`, `/{id}` (PATCH/DELETE), `/{id}/move`, `/{id}/to-note`, `/{id}/links[/{note_id}]`; alias `POST /api/inbox`; `POST /api/capture` |
| Rutinas | `/api/routines/{id}/check|skip|place|stats`, `/api/routines/day`, `/api/routine-templates[/apply|/{tid}]`, `/api/day-templates[/{tid}[/apply]]` |
| Calendario | `/api/calendar/entries|agenda|events[/{id}]|sync|export.ics`, `/api/reminders[/settings]` |
| Tableros | `/api/boards[/{id}[/canvas]]`, `/api/board-templates[/{id}]` |
| Grafo y Baúl | `/api/graph`, `/layout`, `/edges`; `/api/resources[/{id}[/move|/watch-later|/watched]]`, `/categories` |
| Búsqueda | `/api/search`, `/api/saved-filters[/{id}]`, `/api/palette/index` |
| Gestión | `/api/bulk/notes/update|delete|undo/{token}|duplicate|export|import`; `/comidas/api/bulk/{ingredients,meals}/{update,delete,duplicate,export,import}`, `/plan/delete|copy-week`, `/undo/{token}` |
| Economía | `/api/finance/summary|movements|recurring|budgets/{cat}|export.csv|accounts|debts|wishes|{kind}/{id}|debts/{id}/settle|wishes/{id}/buy` |
| Rendimiento | `/api/rendimiento/dia[/{fecha}]|panel|serie|alertas|exportar|examenes|asignaturas/{sigla}|correlaciones|ajustes|ia/estado|ia/auditar|ia/historial` |
| Sistema | `/api/today`, `/api/status`, `/api/prefs[/{key}]`, `/api/trash[/{db}/{token}[/restore]]`, `/api/backups[/status|/run|/{name}[/download|/restore]]`, `/api/dotfiles[/diff|/push]`, `/api/proyecto[/diff|/push]`, `/api/ext/status`, `/healthz`, `/sw.js`, `/manifest.webmanifest`, `/favicon.ico` |
| Comidas | `/comidas/api/ingredients[/validation|/{id}]`, `/meals[/suggest-gramos|/{id}[/favorito]]`, `/shopping-list[/done|/from-meal/{id}|/from-week/{s}|/export/{s}|/{id}]`, `/weekly-plan/{s}[/nutricion|/clear|/full|/sugerencias]`, `/weekly-plan/assign|generate|slots|rol|doble|items/{id}|{plan}/toggle-fixed|regenerate|items|gramos`, `/profile`, `/franjas[/{clave}]`, `/meal-templates[/{tid}[/apply]]`, `/body[/{fecha}|/aplicar-ajuste]` |
| Estudio | `/estudio/config`, `/estudio/api/esp32-status`, `/estudio/api/esp32/retry`; WebSocket directo al ESP32 |

---

## 7. Flujos de datos

| ID | Flujo |
|---|---|
| F-01 | **Captura**: texto → `split_prefix` (`t:` tarea, `i:` idea, `r:` rutina con «cada día/laborables/fines de semana/cada N días/lunes y …», `e:` evento, `g:` gasto) + `natural_date` → ítem/evento/movimiento. Mismo motor en app, extensión y rofi. |
| F-02 | **Nota ↔ casillas**: guardar o indexar un `.md` → `sync_note_items` rehace sus filas en `inbox`; marcar una casilla en la lista reescribe el `.md`. Enlaces `[[tarea:N]]` → `item_links`. |
| F-03 | **Indexado**: al arrancar, `sync_notes_to_db` (incremental por mtime, upsert, solo borra lo que ya no existe); FTS5 como caché de la caché. |
| F-04 | **Calendario en tres vías**: Panel ↔ iCloud (CalDAV) ↔ ESP32 (`estudio/calendar_sync.py`), con guardas contra lecturas vacías; lo borrado por la sincronía va a la papelera. |
| F-05 | **Borrado y deshacer**: todo borrado guarda instantánea en `undo_log` (token) → toast «Deshacer» → `/papelera` 30 días → purga 03:40. |
| F-06 | **Copias**: 03:30 diaria (rotación 7/4/10/5), zip con BDs (API de backup + `integrity_check`), notas, uploads, estado iCloud; restaurar crea antes `pre-restauracion`. |
| F-07 | **Preferencias**: `Prefs.set` → localStorage + PUT con retardo 350 ms; al cargar manda el servidor salvo lo «sucio». |
| F-08 | **Sincronía entre pestañas y dispositivos**: BroadcastChannel + recarga al recuperar el foco. |
| F-09 | **Rutinas**: marcar = `routine_checks` + `item_log` (racha, revisión semanal); pasos con hora propia; `ensure_free` evita solapes (409). |
| F-10 | **Rendimiento**: registro diario → reglas deterministas → semáforos y alertas (tarea por regla) → auditoría IA (OpenRouter `:free` → Groq → Gemini → Ollama, con enfriamiento y cuotas; métricas anonimizadas). |
| F-11 | **Comidas**: catálogo → generador (tres macros, variedad) → plan → compra escalada a la ración → resumen de Hoy. |
| F-12 | **ESP32**: WebSocket cliente; nota a repasar cada 15 min; Spotify vía MPRIS; pomodoro y tareas. |
| F-13 | **Dotfiles / Publicar**: fusión a tres bandas, comprobación de secretos, push sin forzar; `main` nunca se sube. |

---

## 8. Estados y casos límite

| ID | Caso | Comportamiento actual |
|---|---|---|
| E-01 | Carga | Skeletons (`skeletonRows`, `.skeleton-card`) en listas y tarjetas. |
| E-02 | Vacío | `emptyState({iconName, title, text, actionLabel})`: icono Lucide en círculo + título + frase; ~50 usos (Notas 9, Rendimiento 9, Comidas 7, Baúl 6…). Textos por grupo en `GROUP_META` de la lista. |
| E-03 | Error de API | Toast con el mensaje del servidor (JSON en español); 401 → login (`auth-guard.js`); 500 sin detalles. |
| E-04 | Sin conexión | Toast; SW sirve lo visitado; página `offline.html`; Prefs y extensión encolan. |
| E-05 | Guardado de nota fallido | Queda pendiente, reintento a los 5 s; no se cierra la nota. |
| E-06 | Nota cifrada | Pantalla de bloqueo; contraseña incorrecta → error en línea. |
| E-07 | Conflictos | Solape de rutinas (409 + hueco libre), importación con duplicados (conservar/sobrescribir), dotfiles con choques (se quedan fuera). |
| E-08 | Límites | Pydantic con longitudes máximas; subida ≤10 MB verificada con Pillow; scraper ≤2 MB, solo IP pública, 5 redirecciones. |
| E-09 | Login | 8 intentos / 15 min por IP; `next` interno. |
| E-10 | Sin ESP32 / iCloud | Sin `ESP32_HOST` no se intenta conectar; sin credenciales iCloud se desactiva. |
| E-11 | Móvil | Hojas inferiores con teclado (`--vvh`), tablas → tarjetas, sin scroll horizontal, objetivos de 44 px. |
| E-12 | Movimiento reducido | `prefers-reduced-motion` desactiva transiciones y fundidos de tema. |
| E-13 | Papelera | 30 días; restaurar una nota rehace sus casillas (`bulk_undo`). |

---

## 9. Iconos y recursos gráficos (estado actual)

### G-01 Sistema
- **Una sola familia ya**: Lucide (licencia **ISC**), `viewBox 0 0 24 24`, `stroke="currentColor"`, trazo **1,75**,
  extremos redondeados. Sprite `static/icons.svg` (241 símbolos) generado por `scripts/vendor.mjs` desde
  `scripts/icons.txt`; uso con `<use href="…#i-NOMBRE">`.
- Componente: `icon(name, cls)` en Jinja (`core/templating.py`) y en JS (`ui.js`), siempre `aria-hidden="true"`; el
  nombre accesible lo pone el botón (`aria-label`/`title`). Tamaños `.icon` (base) e `.icon-sm`.
- Comprobado: todos los nombres usados de forma literal existen en el sprite; ningún botón `.btn-icon` de las
  plantillas ni del JS carece de `aria-label`.

### G-02 Iconos por significado (principales)
| Icono Lucide | Significado / dónde |
|---|---|
| `sun` Hoy · `calendar` Calendario · `repeat` Rutinas · `list-todo` Tareas · `inbox` Inbox · `history` Revisión | navegación Planificar |
| `notebook-pen` Notas · `waypoints` Grafo · `library` Baúl · `calendar-days` Repaso · `search` Buscar | Conocimiento |
| `utensils-crossed` Comidas · `wallet` Economía · `graduation-cap` Estudio · `activity` Rendimiento | Vida |
| `table-2` Gestión · `database-backup` Copias · `trash-2` Papelera | Sistema |
| `brain` | marca de la app (barra lateral e icono PWA) |
| `square-check` tarea · `lightbulb` idea · `repeat` rutina · `flag` prioridad · `calendar-plus` evento | tipos de ítem |
| `coffee` desayuno · `utensils-crossed` comida · `apple` merienda · `moon` cena · `cookie` extras | franjas de Comidas |
| `plus`, `x`, `pencil`, `trash-2`, `ellipsis`, `chevron-*`, `check`, `copy`, `download`/`upload`, `save` | acciones genéricas |
| `bold`…`sigma`, `scissors`, `play`, `layers` | barra del editor de notas |
| `mouse-pointer-2`, `hand`, `square`, `circle`, `sticky-note`, `type`, `move-right`, `pencil`, `eraser`… | herramientas del tablero |
| `plug-zap`, `wifi-off`, `bell`, `command`, `settings`, `log-out`, `panel-left-*` | shell |
| Categorías de Economía: `bus`, `film`, `house`, `shirt`, `heart-pulse`, `gift`, `receipt`, `banknote`… | (desde `app/finance.py`) |

### G-03 Azulejos de color por sección (firma visual)
28 px, radio 7 px, glifo `--tile-fg`; colores `--tile-*` por tema. **Colores compartidos**: Calendario = Grafo,
Hoy = Baúl, Revisión = Rendimiento = Tareas, Papelera = Copias, Repaso = Estudio.

### G-04 Otros recursos
- Icono de la app: `static/icons/icon.svg` (Lucide `brain` blanco sobre `#5856d6`, radio 112/512) y `maskable.svg`;
  PNG 32 (favicon), 180 (apple-touch), 192, 512, maskable 512. No hay variante clara/oscura ni monocroma.
- Extensión: `EXTENSION PANEL/icons/icon.svg` + su propio `icons.svg`.
- SVG generados en JS: miniaturas de formas y guiones del tablero, gráficos de Rendimiento y del peso (Comidas).
- Estados vacíos: sin ilustraciones; icono en círculo. `offline.html` igual.
- Capturas del README: `docs/img/*.png` (datos inventados, `python -m scripts.demo --capturas`).
- Tipografía: pila del sistema (SF) + Inter Variable autoalojada; KaTeX con sus fuentes.

### G-05 Excepciones a la familia única
- Glifos de texto como icono: `✓ ` en menús de estado (Notas) y prioridad (lista), `★ ` en plantillas y filtro de
  favoritos (Comidas).
- Letras «R» y «E» como icono en la barra del editor (marcar resumir / entender).
- Estudio pinta el fondo del ESP32 con su propio acento.

---

## 10. Tests y línea base

- `python -m pytest --ignore=tests/e2e`: ~342 tests; **1 fallo preexistente**: `tests/test_calendar.py::test_rutina_racha_y_mapa`
  depende del día (hoy es lunes: «ayer» cae en la semana anterior y la revisión semanal no lo incluye). No es una
  regresión de este trabajo.
- E2E (`tests/e2e`, Playwright): 115 tests (tablero, temas AA en todas las páginas, navegación, cuadrícula, rutinas…).
- Verificación manual habitual: puerto 8811 con copia de datos, `PANEL_DISABLE_BRIDGES=1 PANEL_DISABLE_SCHEDULER=1`,
  capturas a 375 / 768 / 1280.

---

## 11. Notas para la Fase 1 (detectado al inventariar, sin tocar nada)

1. 81 manejadores `onclick=` en plantillas (52 en Notas) obligan a mantener `'unsafe-inline'` en `script-src`.
2. Seis secciones repiten el color de azulejo de otra (G-03): la firma visual pierde su función de orientarse.
3. La barra lateral tiene 18 destinos en 4 grupos; la barra móvil solo 4 + Más.
4. Glifos de texto (`✓`, `★`) y letras como iconos (G-05).
5. El icono de la app no tiene versión monocroma ni variante para fondo claro.
6. Test dependiente de la fecha (§10).
