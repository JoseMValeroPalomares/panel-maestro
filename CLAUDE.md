# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Panel personal en un único proceso FastAPI que agrupa tres apps. Repo git (datos personales, `.env` y BDs excluidos en `.gitignore`); `venv/` y `node_modules/` dentro del proyecto. Seguimiento del trabajo en `PLAN.md` y `PROGRESS.md` (locales, no se publican).

| Ruta | Carpeta | Qué hace |
|---|---|---|
| `/` | `app/` + `templates/` + `static/` | Cerebro Digital: PKM de notas Markdown, grafo, bandeja, bóveda, tareas/ideas/rutinas, calendario, Hoy, economía, papelera, backups |
| `/estudio` | `estudio/` | Panel ESP32 (reloj/Spotify/estudio), puente con el ESP32, sincronización con iCloud, repaso de notas |
| `/comidas` | `comidas/` | Catálogo de ingredientes y comidas con macros, planificador semanal, generador, lista de la compra |

## Comandos

```bash
source venv/bin/activate
pip install -r requirements-dev.txt                  # requirements.txt fijado + pytest
./install.sh && ./start.sh                           # instalación completa (--service: servicio de usuario)
python -m scripts.demo                               # panel con datos inventados en un directorio temporal (--capturas: rehace docs/img/)
python -m scripts.set_password                       # contraseña del panel (hash en .env); --api-token para Bearer
uvicorn main:app --host 0.0.0.0 --port 8000          # arranque (añade --reload para desarrollo)
python -m pytest                                     # tests (usan un directorio temporal, nunca los datos reales)
python -m pytest tests/test_auth.py::test_token_bearer   # un solo test

npm install && npm run build                         # vendoriza librerías (static/vendor), iconos (static/icons.svg) y fuente Inter

python comidas/bulk_edit_meals.py                    # ediciones masivas (cp comidas/data/comidas.db{,.bak} antes; tiene dry_run)
python comidas/list_comidas_db.py                    # vuelca la BD a comidas/data/export/*.csv
python comidas/seed_data.py                          # siembra ingredientes/comidas nuevos

python -m scripts.desktop_token                      # token de los scripts del escritorio (~/.config/panel-maestro/token, 600)
python -m scripts.build_extension                    # extensión de Firefox → dist/panel-firefox-<versión>.xpi
```

Hay que arrancar siempre desde la raíz: `Jinja2Templates(directory="templates")` y los imports `app.*` / `estudio.*` / `comidas.*` dependen del cwd.

## Arquitectura

- **`core/`**: infraestructura compartida. `config.py` (todo sale de `.env`; rutas de datos sobrescribibles con `PANEL_*`, así los tests usan un tmp), `auth.py` (middleware ASGI de login en la app raíz: cookie firmada o `Authorization: Bearer`; protege también las sub-apps; rutas públicas en `PUBLIC_EXACT`/`PUBLIC_PREFIXES`), `security.py` (scrypt, HMAC), `db.py` (`db_session`: commit/rollback/cierre, WAL, busy_timeout), `errors.py` (manejadores JSON + cabeceras/CSP), `logging_config.py` (`logs/panel.log`).
- **Acceso a BD**: usar siempre `with get_db() as conn:` (`app.database` / `comidas.database`). No llames desde dentro de un bloque a funciones que abran otra conexión de escritura (se bloquean entre sí): cierra el bloque antes.
- **Tareas e ideas** (una sola lógica): todo vive en la tabla `inbox`; cada casilla `- [ ]` de una nota es una fila más (`note_id` + `note_task` + `note_index`) que `app/note_tasks.py:sync_note_items` rehace desde el `.md` al indexar o guardar (el `.md` manda en texto, estado, orden y anidado; la fila guarda id, prioridad, fecha y notas). Servicio único `app/items.py` (`/api/items`: crear, editar, mover, reordenar, convertir, completar, lote, borrar con deshacer, pasar a nota); `POST /api/inbox` es solo un alias para la extensión 2.1. En el front, almacén `static/js/items.js` (`Items.*`, la única forma de escribir) y componente `static/js/item-list.js` (`ItemList.mount`) que usan Inbox (y su tablero) y Tareas; la captura común está en `templates/_items.html`. Reglas: un nivel de pasos, padre e hijos del mismo tipo (también rutinas), con pasos no se convierte, en una nota solo tareas.
- **Rutinas** (`app/routines.py`): tercer tipo de la lista única (`inbox.item_type = 'rutina'`, grupo «Rutinas»); sus pasos son rutinas hijas sin regla propia (`check_with_steps`: todos hechos = rutina hecha; horario con `schedule`), plantillas en `app/routine_templates.py` y front `static/js/routines.js` (plantillas, paso a paso); con `repeat` (JSON: diaria, días de la semana, cada N días; en la interfaz se elige siempre con `dayPicker` de ui.js: L M X J V S D, los 7 = diaria; «cada N días» solo escribiendo), `due_time`/`duration_min`; marcar = hecha ese día (`routine_checks`). Toda marca o completado va a `item_log` (revisión semanal `/revision`, racha).
- **Rutinas como el día en bloques** (`/rutinas`, `static/js/rutinas.js`): cada paso puede tener hora fija (`due_time`) y días propios (`step_days` → `repeat` semanal del paso); `GET /api/routines/day?date=` da la línea del día; una tarea o idea se asocia a una rutina o paso con `inbox.routine_step` (migración 12). En el calendario, una rutina con horario se expande en un evento por bloque (`step_entry`); `/api/today` los vuelve a agrupar.
- **Economía** (`app/finance.py`, `/economia`, migración 13 `fin_accounts|movements|debts|wishes`): saldos por cuenta, resumen del mes y 6 meses, deudas que se saldan con su movimiento, deseos que al comprarse se apuntan; borrados a la papelera («finance.*»). Prefijo de captura `g:` («g: 4,50 café»).
- **Calendario** (`app/calendar.py`, front `static/js/calendar.js` + `calendario.js`): eventos propios en `events` (hora local de Madrid «AAAA-MM-DDTHH:MM», todo el día con fin exclusivo); las tareas con fecha (y hora = bloque de tiempo) y las rutinas se expanden en `/api/calendar/entries`; mover un bloque es `PATCH /api/items/{id}`. Sincronía en tres vías Panel ↔ iCloud ↔ ESP32 en `estudio/calendar_sync.py` (estado `estudio/calendar_sync_v2.json`, guardas contra lecturas vacías, lo borrado por la sincronía va a la papelera). Bloques ```calendario en notas (`Calendar.mountEmbeds`).
- **Enlaces tarea ↔ nota** (`app/links.py`): marcador `[[tarea:N]]` en el .md (manda) e índice `item_links` rehecho en `note_tasks.sync_note_items`.
- **Dotfiles** (`app/dotfiles.py`, tarjeta en `/backups`, `static/js/dotfiles.js`): sube `~/dotfiles` a GitHub con un botón. En este equipo las configuraciones son archivos reales (Stow solo enlaza en una instalación nueva) y el repo es público y está limpio (sin rastro del autor original, archivos renombrados), así que no se copia: se fusiona a tres bandas por archivo con `git merge-file` (antepasado = lo último subido en `data/dotfiles_base/` o, si nunca se subió, el commit `PANEL_DOTFILES_BASE`, opcional). Sin repo, la tarjeta no aparece. `~` no se toca nunca, nada se borra del repo, lo que choca se queda fuera, `scripts/check-secrets.sh` es obligatorio (si falla se deshace lo aplicado) y no hay `--force`. Probar siempre contra un clon con remoto local (`PANEL_DOTFILES_DIR`): nunca contra el repo real.
- **Publicar el panel** (`app/proyecto.py`, misma tarjeta y diálogo que Dotfiles en `static/js/repos.js`): `main` guarda el historial privado y nunca se sube. El botón hace commit de lo pendiente y llama a `scripts/publicar.sh`, que crea una instantánea sin historial en la rama `publico`, comprueba secretos y datos personales y la sube sin forzar. Ese script y `.publicignore` no se publican: en una copia instalada desde GitHub la tarjeta no aparece.
- **Papelera** (`app/trash.py`): `undo_log` de cada BD (core/undo.py, 30 días, título). Todo borrado (suelto o en lote) guarda ahí su instantánea; `/papelera` restaura o vacía; purga diaria a las 03:40.
- **Captura con prefijos** (`app/capture.py`, `core/natural_date.py`): `t:`/`i:`/`r:`/`e:`; la usan la app (`Items.capture`), la extensión y `scripts/desktop/quick_capture.sh`. Escritorio: `scripts/desktop/` (rofi, Waybar `panel_agenda.py`); ver README.md.
- **Comidas**: franjas en la tabla `franjas` (`_sync_franjas()` refresca las constantes del generador; `dias` = en qué días se usa cada una, `franja_en_dia`), papel de cada plato (`rol`), plato doble, plantillas, favoritos y registro corporal en `comidas/planner.py` (router incluido al final de `comidas/main.py`).
- **Preferencias de interfaz** (plegados, vista del calendario, avisos, tecla de captura): `ui_prefs` + `/api/prefs` + `window.Prefs` (localStorage solo como caché). Avisos: `app/reminders.py` + `static/js/reminders.js`. Paleta Ctrl+K: `static/js/palette.js`. Conexiones: `/api/status` + `static/js/status.js`. ESP32: estado común de conexión en `estudio/esp32_link.py` (`LINK`, `keep_connected`).
- **Gestión masiva** (`/gestion`): `app/bulk.py` y `comidas/bulk.py` (en Comidas, router incluido al final de `comidas/main.py` porque importa de él). Borrar en lote guarda una instantánea en `undo_log` (`core/undo.py`) y devuelve un token de deshacer; CSV/JSON con `core/tabular.py`.
- **Rutas**: FastAPI empareja en orden; las rutas fijas (`/api/notes/recall`) deben declararse antes que `/api/notes/{note_id}`. Valida cualquier `note_id` con `note_path()` (regex + realpath).
- **Front sin CDNs**: librerías en `static/vendor` (generadas por `scripts/vendor.mjs`). Sistema de diseño propio en `static/css/ds.css` (tokens claro/oscuro, componentes, `.modal` sobre `<dialog>`), JS común en `static/js/ui.js` (`api`, `toast`, `openModal`, `uiConfirm`, `uiPrompt`, `openMenu`, `emptyState`, `icon`). Todas las páginas extienden `templates/_layout.html` (también Comidas y Estudio, vía `core/templating.render`). Iconos: Lucide en `static/icons.svg`; añade nombres a `scripts/icons.txt` y ejecuta `npm run vendor`. La CSP de `main.py` solo permite `'self'`.

- **`main.py` (raíz)** importa `app.main.app` (Cerebro) como app raíz y monta `estudio` y `comidas` con `app.mount(...)`. Starlette **no propaga el lifespan** a las sub-apps montadas, así que `main.py` compone los tres lifespan con `AsyncExitStack` y reemplaza `app.router.lifespan_context`. Si añades otra sub-app con `init_db` o tareas de fondo, hay que registrar su lifespan ahí o nunca se ejecutará (síntoma: `no such table`).
- **Cerebro (`app/`)**: la fuente de verdad son los `.md` con frontmatter YAML en `data/notes/`. `data/brain.db` (SQLite) es una **caché reindexable**: `app/indexer.py:sync_notes_to_db` la sincroniza al arrancar con upsert incremental (solo borra de la caché las notas que ya no existen en disco). Cualquier campo nuevo de nota debe persistirse en el frontmatter, no solo en la BD. `app/main.py` solo crea la app, arranca, programa tareas e incluye los routers (el orden de la lista importa); cada área tiene su módulo: `pages.py` (páginas Jinja), `notes.py` (notas y categorías), `graph.py`, `vault.py` (baúl), `study.py` (flashcards, racha, salud), `uploads.py`, `extension.py`, `boards.py`, `backups_api.py`… Las utilidades de notas (`note_path`, `slugify`, `split_category_path`, `sync_flashcards`, `update_index_for_area`, límites) están en `app/notes_core.py`, sin dependencias de routers: no importes nada de `app.main`. APScheduler (`app.state.scheduler`) lanza `app/backup.py:run_daily_backup` a las 03:30: zip completo en `backups/` (ambas BDs copiadas con la API de backup de SQLite + `integrity_check`, notas, uploads, estado de iCloud y `manifest.json` con sha256); rotación por tipo (diaria 7, semanal 4, manual 10, pre-restauración 5; las de formato antiguo no se tocan). Restaurar (`/backups`) crea antes una copia `pre-restauracion` y admite partes sueltas. Conserva columnas solo-BD como `last_reviewed`.
- **Estudio (`estudio/`)**: actúa como *cliente* websocket hacia el ESP32 (`ESP32_HOST` en `.env`), lee Spotify vía `playerctl`/MPRIS, y arranca `IcloudSyncBridge` (CalDAV, estado en `calendar_sync_state.json`) y `NoteReviewBridge` (envía una nota cada 15 min, usa `SERVER_BASE_URL` de `.env`). Sirve su front estático en `/` de la sub-app.
- **Comidas (`comidas/`)**: BD propia `comidas/data/comidas.db`, esquema y migraciones ligeras en `comidas/database.py:init_db` (aditivas: nunca borran; si `ingredients` no tiene `nombre`, se renombra a `ingredients_legacy_*`). La lógica del generador/planificador (constantes de franjas, grupos de alimentos, límites semanales, escalado de raciones) está en `comidas/main.py` (Python puro, sin numpy/scipy). Cada celda de `weekly_plan` puede llevar su propio `gramos_racion`; si es NULL se usa la ración estándar del catálogo.
- **Front de sub-apps**: Comidas y Estudio renderizan su página con el layout común y cargan sus propios `/comidas/css|js/comidas.*` y `/estudio/estudio.css|app.js`. Dentro de las sub-apps, el `StaticFiles` montado en `/` va al final del archivo para no tapar las rutas de la API.

## Ojo

- Credenciales (iCloud, hash de la contraseña del panel, secreto de sesión) solo en `.env` (ver `.env.example`).
- Las IPs del ESP32 y del servidor vienen de `ESP32_HOST` / `SERVER_BASE_URL` en `.env`. Sin `ESP32_HOST` no hay placa: no se intenta conectar y solo queda la sincronía con iCloud.
- Para probar sin efectos externos: `PANEL_DISABLE_BRIDGES=1 PANEL_DISABLE_SCHEDULER=1` (no conecta con el ESP32/iCloud ni programa backups); los tests apuntan `PANEL_DOTFILES_*` a repos temporales.
- El panel real es el servicio de usuario `panel-maestro` (puerto 8000, sin --reload): `systemctl --user restart panel-maestro`. Las migraciones corren al arrancar: copia antes las BDs.
- Configuración del escritorio tocada por el proyecto (con copias `*.bak-panel-*`): `~/.config/hypr/UserConfigs/UserKeybinds.lua` (Super+K captura, Super+Alt+K agenda) y Waybar (`ModulesCustom`, `configs/2`, `style/Fusion Personalizada.css`).
- Idioma del proyecto: código, comentarios y UI en español.
