# CLAUDE.md

## Qué es

Panel personal en un único proceso FastAPI que agrupa tres apps. Repo git (datos personales, `.env` y BDs excluidos en `.gitignore`); `venv/` y `node_modules/` dentro del proyecto. Seguimiento del trabajo en `PLAN.md` y `PROGRESS.md` (locales, no se publican).

## Comandos

```bash
source venv/bin/activate
./install.sh && ./start.sh                           # instalación completa (--service: servicio de usuario)
python -m scripts.demo                               # panel con datos inventados en un directorio temporal (--capturas: rehace docs/img/)
python -m scripts.set_password                       # contraseña del panel (hash en .env); --api-token para Bearer
uvicorn main:app --host 0.0.0.0 --port 8000          # arranque (añade --reload para desarrollo)
python -m pytest                                     # tests (usan un directorio temporal, nunca los datos reales)

npm install && npm run build                         # vendoriza librerías (static/vendor), iconos (static/icons.svg) y fuente Inter

python -m scripts.desktop_token                      # token de los scripts del escritorio (~/.config/panel-maestro/token, 600)
python -m scripts.build_extension                    # extensión de Firefox → dist/panel-firefox-<versión>.xpi
```

Hay que arrancar siempre desde la raíz: `Jinja2Templates(directory="templates")` y los imports `app.*` / `estudio.*` / `comidas.*` dependen del cwd.

## Arquitectura

- **`core/`**: infraestructura compartida. `config.py` (todo sale de `.env`; rutas de datos sobrescribibles con `PANEL_*`, así los tests usan un tmp), `auth.py` (middleware ASGI de login en la app raíz: cookie firmada o `Authorization: Bearer`; protege también las sub-apps; rutas públicas en `PUBLIC_EXACT`/`PUBLIC_PREFIXES`), `security.py` (scrypt, HMAC), `db.py` (`db_session`: commit/rollback/cierre, WAL, busy_timeout), `files.py` (`atomic_write`: todo `.md` se escribe con ella), `errors.py` (manejadores JSON + cabeceras/CSP), `logging_config.py` (`logs/panel.log`).
- **Acceso a BD**: usar siempre `with get_db() as conn:` (`app.database` / `comidas.database`). No llames desde dentro de un bloque a funciones que abran otra conexión de escritura (se bloquean entre sí): cierra el bloque antes.
- **Tareas e ideas** (una sola lógica): todo vive en la tabla `inbox`; cada casilla `- [ ]` de una nota es una fila más (`note_id` + `note_task` + `note_index`) que `app/note_tasks.py:sync_note_items` rehace desde el `.md` al indexar o guardar (el `.md` manda en texto, estado, orden y anidado; la fila guarda id, prioridad, fecha y notas). Servicio único `app/items.py` (`/api/items`: crear, editar, mover, reordenar, convertir, completar, lote, borrar con deshacer, pasar a nota); `POST /api/inbox` es solo un alias para la extensión 2.1. En el front, almacén `static/js/items.js` (`Items.*`, la única forma de escribir) y componente `static/js/item-list.js` (`ItemList.mount`) que usan Inbox (y su tablero) y Tareas; la captura común está en `templates/_items.html`. Reglas: un nivel de pasos, padre e hijos del mismo tipo (también rutinas), con pasos no se convierte, en una nota solo tareas.
- **Rutinas** (`app/routines.py`): tercer tipo de la lista única (`inbox.item_type = 'rutina'`, grupo «Rutinas»); sus pasos son rutinas hijas sin regla propia (`check_with_steps`: todos hechos = rutina hecha; línea del día con `timeline`), plantillas en `app/routine_templates.py` y front `static/js/routines.js` (plantillas, paso a paso); con `repeat` (JSON: diaria, días de la semana, cada N días; en la interfaz se elige siempre con `dayPicker` de ui.js: L M X J V S D, los 7 = diaria; «cada N días» solo escribiendo), `due_time`/`duration_min`; marcar = hecha ese día (`routine_checks`). Toda marca o completado va a `item_log` (revisión semanal `/revision`, racha).
- **Calendario** (`app/calendar.py`, front `static/js/calendar.js` + `calendario.js`): eventos propios en `events` (hora local de Madrid «AAAA-MM-DDTHH:MM», todo el día con fin exclusivo); las tareas con fecha (y hora = bloque de tiempo) y las rutinas se expanden en `/api/calendar/entries`; mover un bloque es `PATCH /api/items/{id}`. Sincronía en tres vías Panel ↔ iCloud ↔ ESP32 en `estudio/calendar_sync.py` (estado `estudio/calendar_sync_v2.json`, guardas contra lecturas vacías, lo borrado por la sincronía va a la papelera). Bloques ```calendario en notas (`Calendar.mountEmbeds`).
- **Enlaces tarea ↔ nota** (`app/links.py`): marcador `[[tarea:N]]` en el .md (manda) e índice `item_links` rehecho en `note_tasks.sync_note_items`.
- **Dotfiles y Publicar** (tarjeta en `/backups`; detalle en `app/CLAUDE.md`): los dotfiles se prueban siempre contra un clon con remoto local (`PANEL_DOTFILES_DIR`), nunca contra el repo real; `~` no se toca, nada se borra del repo y no hay `--force`. `main` guarda el historial privado y nunca se sube: solo la rama `publico` vía `scripts/publicar.sh`.
- **Papelera** (`app/trash.py`): `undo_log` de cada BD (core/undo.py, 30 días, título). Todo borrado (suelto o en lote) guarda ahí su instantánea; `/papelera` restaura o vacía; purga diaria a las 03:40.
- **Captura con prefijos** (`app/capture.py`, `core/natural_date.py`): `t:`/`i:`/`r:`/`e:`; la usan la app (`Items.capture`), la extensión y `scripts/desktop/quick_capture.sh`. Escritorio: `scripts/desktop/` (rofi, Waybar `panel_agenda.py`); ver README.md.
- **Preferencias de interfaz** (plegados, vista del calendario, avisos, tecla de captura): `ui_prefs` + `/api/prefs` + `window.Prefs` (localStorage solo como caché). Avisos: `app/reminders.py` + `static/js/reminders.js`. Paleta Ctrl+K: `static/js/palette.js`. Conexiones: `/api/status` + `static/js/status.js`. ESP32: estado común de conexión en `estudio/esp32_link.py` (`LINK`, `keep_connected`).
- **Gestión masiva** (`/gestion`): `app/bulk.py` y `comidas/bulk.py` (en Comidas, router incluido al final de `comidas/main.py` porque importa de él). Borrar en lote guarda una instantánea en `undo_log` (`core/undo.py`) y devuelve un token de deshacer; CSV/JSON con `core/tabular.py`.
- **Rutas**: FastAPI empareja en orden; las rutas fijas (`/api/notes/recall`) deben declararse antes que `/api/notes/{note_id}`. Valida cualquier `note_id` con `note_path()` (regex + realpath).
- **Front sin CDNs**: librerías en `static/vendor` (generadas por `scripts/vendor.mjs`). Sistema de diseño propio en `static/css/ds.css` (tokens claro/oscuro, componentes, `.modal` sobre `<dialog>`), JS común en `static/js/ui.js` (`api`, `toast`, `openModal`, `uiConfirm`, `uiPrompt`, `openMenu`, `emptyState`, `icon`). Todas las páginas extienden `templates/_layout.html` (también Comidas y Estudio, vía `core/templating.render`). Iconos: Lucide en `static/icons.svg`; añade nombres a `scripts/icons.txt` y ejecuta `npm run vendor`. La CSP de `main.py` solo permite `'self'`.

- **`main.py` (raíz)** importa `app.main.app` (Cerebro) como app raíz y monta `estudio` y `comidas` con `app.mount(...)`. Starlette **no propaga el lifespan** a las sub-apps montadas, así que `main.py` compone los tres lifespan con `AsyncExitStack` y reemplaza `app.router.lifespan_context`. Si añades otra sub-app con `init_db` o tareas de fondo, hay que registrar su lifespan ahí o nunca se ejecutará (síntoma: `no such table`).
- **Cerebro (`app/`)**: la fuente de verdad son los `.md` de `data/notes/`; `data/brain.db` es una caché reindexable, así que todo campo nuevo de nota va al frontmatter. No importes nada de `app.main` (utilidades en `app/notes_core.py`). Routers, backups y restauración: `app/CLAUDE.md`.
- **Front de sub-apps**: Comidas y Estudio renderizan su página con el layout común y cargan sus propios `/comidas/css|js/comidas.*` y `/estudio/estudio.css|app.js`. Dentro de las sub-apps, el `StaticFiles` montado en `/` va al final del archivo para no tapar las rutas de la API.

Detalle por área en `static/js/CLAUDE.md`, `app/CLAUDE.md`, `comidas/CLAUDE.md` y `estudio/CLAUDE.md` (se cargan al trabajar en esa carpeta).

## Ojo

- Credenciales (iCloud, hash de la contraseña del panel, secreto de sesión) solo en `.env` (ver `.env.example`).
- Nunca `INSERT OR REPLACE` en `notes` ni en otra tabla con hijos en cascada: borra la fila y se lleva a los hijos (el progreso de las flashcards). Usa `app.indexer.upsert_note`.
- Las notas borradas guardan sus casillas en la instantánea (`rows["inbox"]` de `bulk_delete`): un dato nuevo de `inbox` vuelve solo al restaurar. El archivo restaurado conserva su fecha, así que el indexador no lo ve cambiado: las casillas se rehacen en `bulk_undo`.
- En un bucle de asyncio (puentes de `estudio/`) nada de `subprocess`, BD ni disco: `asyncio.to_thread`. Restaurar el cerebro borra `config.CALENDAR_STATE` a propósito: con «última vez» vieja, lo que faltase en el Panel se borraría de iCloud y del ESP32.
- Las IPs del ESP32 y del servidor vienen de `ESP32_HOST` / `SERVER_BASE_URL` en `.env`. Sin `ESP32_HOST` no hay placa: no se intenta conectar y solo queda la sincronía con iCloud.
- Para probar sin efectos externos: `PANEL_DISABLE_BRIDGES=1 PANEL_DISABLE_SCHEDULER=1` (no conecta con el ESP32/iCloud ni programa backups); los tests apuntan `PANEL_DOTFILES_*` a repos temporales.
- El panel real es el servicio de usuario `panel-maestro` (puerto 8000, sin --reload): `systemctl --user restart panel-maestro`. Las migraciones corren al arrancar: copia antes las BDs.
- Configuración del escritorio tocada por el proyecto (con copias `*.bak-panel-*`): `~/.config/hypr/UserConfigs/UserKeybinds.lua` (Super+K captura, Super+Alt+K agenda) y Waybar (`ModulesCustom`, `configs/2`, `style/Fusion Personalizada.css`).
- Idioma del proyecto: código, comentarios y UI en español.
