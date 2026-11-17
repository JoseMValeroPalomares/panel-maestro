# Despliegue con vuelta atrás (`scripts/desplegar.sh`)

Hasta ahora el servicio `panel-maestro` servía desde la carpeta donde se programa: una plantilla a medias se veía al
instante en el panel de verdad y cualquier reinicio aplicaba migraciones sin probar. Con `desplegar.sh`, el panel real
ejecuta un **commit concreto**, ya probado, en su propia carpeta; los datos no se mueven.

```bash
scripts/desplegar.sh                  # despliega HEAD (solo lo que está en el commit; avisa si hay cambios sin commit)
scripts/desplegar.sh v2026.11         # o una etiqueta, rama o commit
scripts/desplegar.sh --comprobar      # solo las comprobaciones previas: no prepara, no para ni cambia nada
scripts/desplegar.sh --estado         # versión en marcha, la anterior, las guardadas y los últimos despliegues
scripts/desplegar.sh --volver         # vuelve a la anterior (las BDs no se tocan)
scripts/desplegar.sh --unidad-propuesta   # la unidad de systemd que hace falta y su diferencia con la instalada
```

Opciones: `--raiz DIR` (o `PANEL_DEPLOY_ROOT`; por defecto `~/.local/share/panel-maestro`), `--unidad NOMBRE`
(`panel-maestro`), `--url` de `/healthz` (por defecto la deduce de `PANEL_PORT` y `PANEL_SSL_CERT`), `--espera S` (90),
`--sin-tests`, `--guardar N` (3 versiones).

## Qué hace

0. **Comprobaciones previas** (también sueltas con `--comprobar`, que solo mira): herramientas (git, python3, curl,
   flock, systemctl), que la versión exista, que la unidad arranque `actual/start.sh` y cargue `panel.env`, que se pueda
   leer el `.env` de los secretos, que las dos BDs estén (disco de datos montado) y su carpeta admita escritura, que se
   pueda escribir la copia previa y que queden al menos 300 MB libres. Si algo falla, lo dice con una ✗ y no toca nada.
   **Se puede repetir sin miedo**: desplegar la versión que ya está en marcha no hace nada y sale bien; si esa
   versión estaba parada o no respondía, la arranca y espera (sin tocar las BDs).
1. **Prepara la versión**: `git worktree add --detach` en `<raíz>/releases/<fecha>-<commit>` (una carpeta por commit;
   si ya existe se reutiliza) y le enlaza su entorno de Python.
2. **Tests** de esa versión (unitarios), con sus dependencias y un entorno limpio (`env -i`): ninguna `PANEL_*` del
   panel real llega a los tests (`tests/conftest.py` no fija todas; `PANEL_CALENDAR_STATE` apuntaría al estado de verdad).
   Si fallan, no se toca nada.
3. **Para el servicio y copia** las dos BDs (API de backup + `integrity_check`) y el estado del calendario en
   `PANEL_BACKUPS_DIR/pre-despliegue/<versión>-<hora>/` con un `manifest.json` (huella sha256 del volcado SQL de cada BD).
   Se copia con el servicio **parado**: así nada de lo que se escriba antes se pierde si luego hay que restaurar.
4. **Cambia el enlace** `<raíz>/actual` (cambio atómico) y arranca.
5. **Espera a `/healthz`** (las dos BDs responden; si la unidad queda en «failed» no agota la espera). Bien: `anterior` pasa a ser la que había, se apunta en
   `<raíz>/historial.log` y se borran las versiones y entornos que ya no hacen falta (se guardan 3, más actual y anterior,
   y las 5 últimas copias previas).
6. **Si no responde**: para, restaura BDs y estado del calendario desde la copia (comprobando que la huella es la misma),
   vuelve a la versión anterior, arranca y espera otra vez a `/healthz`. Sale con error y dice dónde está la copia.

El estado del calendario se restaura junto a las BDs a propósito: si la versión rota llegase a sincronizar, la «última
vez» quedaría por delante de la BD y lo que faltase en el Panel se borraría de iCloud y del ESP32 (ver CLAUDE.md, «Ojo»).
Las notas `.md` no se restauran: ningún arranque las escribe (el indexador solo lee).

## Los datos se quedan donde están

La versión desplegada solo trae el código. `<raíz>/panel.env` (lo crea el primer despliegue; la unidad lo carga con
`EnvironmentFile=`) dice dónde están los datos, con **rutas explícitas**: `PANEL_ENV_FILE`, `PANEL_DATA_DIR`,
`PANEL_NOTES_DIR`, `PANEL_BRAIN_DB`, `PANEL_TRASH_DIR`, `PANEL_COMIDAS_DB`, `PANEL_UPLOADS_DIR`, `PANEL_BACKUPS_DIR`,
`PANEL_LOGS_DIR`, `PANEL_CALENDAR_STATE` y `PANEL_PROJECT_DIR`, todas hacia la carpeta de desarrollo.

- **`PANEL_CALENDAR_STATE`** tiene que ir explícita: `core/config.py` la deduce de dónde está el código, y en cuanto
  `PANEL_DATA_DIR` deja de ser `<código>/data` la buscaría en otro sitio y la sincronía empezaría sin «última vez».
- **`PANEL_PROJECT_DIR`**: el botón «Publicar» (`app/proyecto.py`) sigue trabajando sobre el repo de desarrollo (main,
  `scripts/publicar.sh`, la rama `publico`), no sobre la versión desplegada, que es un worktree sin rama.
- **Dotfiles**: `~/dotfiles` y `~` no dependen de dónde esté el código; `data/dotfiles_base` va con `PANEL_DATA_DIR`.
- **Lo que se lee del código** (plantillas, estáticos, `docs/`, `app/llm_modelos.json`): sale de la versión desplegada,
  que es lo que se quiere. `Jinja2Templates` y los imports dependen del cwd: la unidad usa `WorkingDirectory=<raíz>/actual`
  y `start.sh` hace `cd` a su carpeta real.
- **`.env`**: uno solo, el de siempre (`PANEL_ENV_FILE`); el panel escribe en él («Cerrar las demás sesiones»).

Antes de parar nada, el script comprueba que la unidad arranca `<raíz>/actual/start.sh` y carga `panel.env`: si no,
la versión nueva usaría `<código>/data` (vacío) y parecería que se han perdido los datos.

## Entorno de Python: uno por `requirements.lock`, compartido

Cada versión enlaza `venv` a `<raíz>/venvs/<hash de requirements.lock + requirements-dev.txt>`. **Ni el venv de
desarrollo ni uno por versión**:

- El de desarrollo cambia con cada `pip install` mientras se programa: es el mismo problema que con el código.
- Uno por versión serían ~430 MB y un par de minutos por despliegue, casi siempre con las mismas dependencias.
- Con el hash, desplegar sin tocar dependencias reutiliza el entorno (el despliegue tarda lo que los tests, ~30 s) y
  volver atrás a una versión con otras dependencias usa el suyo, que sigue ahí. Lleva también `requirements-dev.txt`
  para que los tests del paso 2 corran con exactamente las dependencias de producción.
- Se crea en su sitio y se marca con `.listo` al acabar: uno a medias (sin red, Ctrl+C) se rehace entero.

## Paso a despliegues (lo haces tú)

```bash
scripts/desplegar.sh --unidad-propuesta   # enseña panel.env y el diff de la unidad (no cambia nada)
```

Aplica el diff en `~/.config/systemd/user/panel-maestro.service` (`WorkingDirectory`, `ExecStart` y `EnvironmentFile`
hacia `~/.local/share/panel-maestro`), `systemctl --user daemon-reload` y `scripts/desplegar.sh`. El primer despliegue
no tiene versión anterior: si fallase, restaura las BDs y deja el servicio parado (para volver a como estaba, deshaz el
diff de la unidad y arranca). Desde entonces, `./install.sh --service` se niega a reinstalar la unidad de la carpeta de
desarrollo.

## Cómo se probó

Con una unidad de prueba en `$XDG_RUNTIME_DIR/systemd/user/` (desaparece al reiniciar) en el puerto 8811 sobre una copia
de los datos, sin puentes ni programador:

- Despliegue de HEAD: correcto; el proceso sirve desde `releases/…` con los datos de la copia (133 notas).
- Commit roto adrede **fuera de main**: una migración 25 que cambia la BD y un `/healthz` que da 503. Con tests, no se
  despliega; con `--sin-tests`, arranca, aplica la migración, `/healthz` no responde → vuelve solo a la anterior, con las
  dos BDs y el estado del calendario con la misma huella que antes (BD otra vez en la migración 24).
- `--volver` dos veces: ida y vuelta entre las dos últimas.
- Con la unidad real sin preparar: se niega antes de parar nada.
