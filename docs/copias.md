# Copias de seguridad

La página **Copias** (`/backups`) lista, crea, descarga, restaura y borra copias. La lógica está en `app/backup.py`.

- **Cuándo**: cada noche a las 03:30 (diaria; una a la semana se marca como semanal) y cuando pulses «Hacer copia
  ahora». Como el portátil suele estar dormido a esa hora, al arrancar el panel y cada hora se comprueba: si la última
  automática pasa de 24 h, se hace en ese momento. Restaurar guarda antes una copia `pre-restauracion`, y cada
  migración pendiente, una de la BD en `backups/pre-migracion-<versión>-<fecha>/`.
- **Avisos**: si la última copia pasa de 36 h, falló o no hay ninguna, lo dicen Hoy (con «Hacer copia ahora»),
  Conexiones y la Waybar (clase `copias-aviso`, ver [escritorio.md](escritorio.md)).
- **Qué**: las dos BDs (copiadas con la API de backup de SQLite y `integrity_check`), notas, historial de versiones,
  papelera, imágenes, lista de modelos de IA, base de los dotfiles y el estado del calendario, con `manifest.json`
  (sha256 de cada archivo). El `.env` no entra: guárdalo en tu gestor de contraseñas.
- **Retención**: diaria 7, semanal 4, manual 10, pre-restauración 5. Las de formato antiguo no se borran solas.
- **Recuperar en otro equipo**: [recuperacion.md](recuperacion.md).

## Espejo: una segunda copia fuera de este disco

Las copias viven en `backups/`, en el mismo disco que los datos: si el SSD muere o te roban el portátil, se pierden
las dos cosas. Con `PANEL_BACKUP_MIRROR` cada copia correcta se copia además a otra carpeta, se comprueba su sha256 y
allí se rota con la misma retención (lo que no sea `backup_*.zip` no se toca).

```bash
# .env
PANEL_BACKUP_MIRROR=/run/media/usuario/USB-COPIAS/panel-copias
systemctl --user restart panel-maestro
```

- **Otra unidad (USB, disco externo, NAS montado)**: apunta a una **subcarpeta** de la unidad, creada a mano
  (`mkdir /run/media/…/panel-copias`). El panel nunca crea la carpeta del espejo: así, con la unidad sin montar, la
  carpeta no existe y lo sabe, en vez de escribir en el punto de montaje vacío del disco interno.
- **Syncthing**: apunta a una carpeta compartida con otro equipo o con el móvil (p. ej. `~/Sync/panel-copias`).
  Está en el mismo disco, así que el estado lo indica («mismo disco»): solo protege si Syncthing la sincroniza fuera.
- **rclone** (Drive, OneDrive, S3…): o bien `rclone mount` y apuntas a una subcarpeta del montaje, o bien apuntas a una
  carpeta local y la subes con una tarea (`rclone copy ~/panel-copias remoto:panel-copias`). Cifra el remoto
  (`rclone crypt`) si va a la nube: el zip lleva todas tus notas sin cifrar.

Si el espejo no está disponible (unidad sin montar, sin espacio, hash distinto), **la copia local sigue siendo correcta**:
la tarjeta de Copias y la ventana de Conexiones muestran «Espejo de las copias · No disponible» con el motivo, y la
siguiente copia lo vuelve a intentar. No se reintenta con las copias que faltan: la próxima diaria ya lleva todo.
