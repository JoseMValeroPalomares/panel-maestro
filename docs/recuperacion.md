# Recuperar el panel desde cero en otro equipo

Para cuando el portátil muere, te lo roban o estrenas otro. Probado el 2026-11-14 con un clon limpio y un zip
hecho a partir de una copia de los datos reales: notas, versiones, papelera, base de los dotfiles e imágenes
volvieron con los mismos sha256, y las 67 tablas de `brain.db` y las 19 de `comidas.db` con los mismos recuentos.

## Qué necesitas

| Qué | De dónde | Notas |
|---|---|---|
| **El zip más reciente** (`backup_*.zip`) | `backups/` del equipo viejo, la carpeta del **espejo** (`PANEL_BACKUP_MIRROR`, ver [copias.md](copias.md)) o uno que bajaste con «Descargar» en Copias | Lleva las dos BDs, notas, historial de versiones, papelera, imágenes, modelos de IA y base de los dotfiles. Las copias diarias son de las 03:30 |
| **El `.env`** | Tu gestor de contraseñas (guárdalo ahí: **no va en el zip** a propósito, porque el zip puede acabar en otra unidad o en la nube) | Sin él también se puede: pones una contraseña nueva y vuelves a escribir las credenciales de iCloud y las claves de IA |
| **El código** | Tu copia de `main` o, si no la tienes, `git clone` del repo público (rama `publico`) | Que sea **igual o más nuevo** que el panel que hizo la copia: las migraciones solo van hacia delante y se aplican solas al arrancar |

Lo que **no** está en el zip y se rehace a mano: el token del escritorio y la configuración de Waybar/Hyprland
([escritorio.md](escritorio.md)), el abridor `panelmaestro://` ([contextos.md](contextos.md#abrir-carpetas)), la
extensión de Firefox (vuelve a iniciar sesión) y el servicio de systemd.

## Pasos (Linux)

```bash
# 1. Código y entorno
git clone <tu repo> ~/Projects/panel-maestro && cd ~/Projects/panel-maestro
cp /ruta/al/.env.guardado .env && chmod 600 .env    # si lo tienes: conserva tu contraseña, iCloud y claves de IA
./install.sh                                         # venv + dependencias; sin .env, crea uno y te pide la contraseña

# 2. La copia, en su sitio
mkdir -p backups && cp /ruta/a/backup_diaria_AAAAMMDD_HHMMSS.zip backups/

# 3. Arrancar SIN puentes la primera vez: con el panel vacío no conviene hablar todavía con iCloud ni con el ESP32
PANEL_DISABLE_BRIDGES=1 PANEL_DISABLE_SCHEDULER=1 ./start.sh
```

4. Abre `http://localhost:8000/backups`, entra con tu contraseña, pulsa **Restaurar** en la copia, deja marcadas
   **todas** las partes, escribe `RESTAURAR` y confirma. Antes de tocar nada se guarda una copia
   `pre-restauracion` del estado (vacío) actual.
5. Para el panel (Ctrl+C) y arráncalo normal: `./start.sh`, o `./install.sh --service` para que arranque solo.
   Restaurar borra a propósito el estado de la sincronía del calendario: la primera vez une Panel, iCloud y ESP32 sin
   borrar nada en ningún lado.
6. Comprueba: Notas (mismo número), Papelera, Copias («Tus datos están protegidos» tras la próxima copia) y
   Conexiones. Después, lo de escritorio de la tabla de arriba.

Por API, el paso 4 es `POST /api/backups/<zip>/restore` con `{"confirm": "RESTAURAR"}` (todas las partes por defecto).

## Partes de una copia

| Parte | Qué devuelve | Cómo |
|---|---|---|
| `notas` | `data/notes/*.md` | Sustituye: las notas creadas después de la copia se quitan (quedan en la copia `pre-restauracion`) |
| `historial` | `data/versions/` | Solo añade lo que falta; nunca pisa ni borra versiones |
| `cerebro` | `data/brain.db` y `data/trash/` (lo borrado de los últimos 30 días) | La BD se vuelca entera; la papelera solo añade |
| `comidas` | `comidas/data/comidas.db` | Se vuelca entera |
| `imagenes` | `static/uploads/` | Solo añade las que faltan |
| `ajustes` | `data/llm_modelos.json` y `data/dotfiles_base/` | Sustituye esos archivos |

Los zips antiguos siguen valiendo: los de formato 1 (`backup_AAAAMMDD_HHMMSS.zip`, solo notas y `brain.db`) y los de
formato 2 (sin papelera ni ajustes). Lo que una copia no trae no se toca.

## Si el panel no arranca: a mano

El zip es un zip normal. Con el panel **parado**, cada cosa va a su sitio:

| En el zip | En el proyecto |
|---|---|
| `data/brain.db` | `data/brain.db` (borra antes `data/brain.db-wal` y `-shm` si existen) |
| `comidas/comidas.db` | `comidas/data/comidas.db` (ídem con `-wal`/`-shm`) |
| `notes/` | `data/notes/` |
| `versions/` | `data/versions/` |
| `trash/` | `data/trash/` |
| `dotfiles_base/` | `data/dotfiles_base/` |
| `data/llm_modelos.json` | `data/llm_modelos.json` |
| `uploads/` | `static/uploads/` |
| `estudio/*.json` | no lo copies: sin él, la primera sincronía une los tres lados sin borrar nada |

`manifest.json` trae el sha256 de cada archivo para comprobarlos (`sha256sum`).
