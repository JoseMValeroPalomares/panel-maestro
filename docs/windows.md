# El panel en Windows 11 con los mismos datos (P-12)

Arranque dual Arch + Windows 11 y una partición NTFS compartida, «datos» (`nvme0n1p5`, 20 GB; en Linux `/mnt/datos`
con `ntfs3`, `nofail` y `windows_names` desde `/etc/fstab`). En Windows solo se usa la web: ni captura rápida, ni
avisos del sistema, ni Waybar.

**Condición principal: que Windows no pueda romper los datos.** Todo lo que sigue sale de ahí.

## 1. La idea: una sola carpeta, nada de sincronizar

Los dos sistemas nunca están encendidos a la vez, así que no hay nada que sincronizar: los dos paneles abren **la
misma carpeta** de la partición compartida. Copiar de un lado a otro (sincronizar) tendría conflictos, borrados que
viajan y dos verdades; una carpeta única no.

```
/mnt/datos/panel-maestro/            (en Windows, p. ej. D:\panel-maestro\)
├── data/
│   ├── notes/*.md                   la fuente de verdad
│   ├── brain.db                     tareas, eventos, rendimiento… (y la caché de las notas)
│   ├── trash/  versions/  adjuntos/  dotfiles_base/
│   ├── programador.json  llm_modelos.json  miniaturas_fallidas.json
│   ├── panel-cerrojo.json           quién la abrió por última vez y si cerró bien (§3.3)
│   └── windows-estado.json          lo que vio start.ps1 en Windows (§3.1)
├── comidas/comidas.db
├── uploads/                         imágenes de las notas y los platos
└── estudio/calendar_sync_v2.json    estado de la sincronía con iCloud (va con las BDs: §3.6)
```

Lo que **no** va en la partición, en cada sistema por separado:

| Qué | Linux | Windows |
|---|---|---|
| Código y `venv` | `~/Projects/panel-maestro` y el despliegue (`~/.local/share/panel-maestro`) | `%LOCALAPPDATA%\PanelMaestro\app` |
| `.env` | el de siempre (secretos) + `panel.env` (rutas) | `%LOCALAPPDATA%\PanelMaestro\.env` (mismos secretos, rutas de Windows) |
| Copias (`backups/`) y su espejo (D-2) | `~/Projects/panel-maestro/backups` | `%LOCALAPPDATA%\PanelMaestro\backups` |
| Logs | `logs/` del proyecto | `%LOCALAPPDATA%\PanelMaestro\logs` |

Las copias **nunca** van a la partición compartida: si Windows la estropea, se llevaría también las copias. El panel
avisa en «Conexiones» si las copias o el espejo caen en la misma unidad que los datos compartidos.

Los mismos secretos en los dos `.env` (contraseña, secreto de sesión, token de la extensión, iCloud): así la misma
cookie y el mismo token valen en los dos sistemas. Lo único distinto son las rutas.

## 2. Riesgos, uno por uno

### 2.1 Inicio rápido e hibernación de Windows (la causa nº 1 de particiones dañadas)

El «inicio rápido» de Windows no apaga: hiberna el núcleo con las unidades NTFS **montadas**. Si en ese rato Linux
escribe en la partición, al volver Windows trabaja con su imagen vieja de la unidad y pisa lo que hizo Linux:
archivos perdidos o el sistema de archivos dañado. Con la hibernación pasa lo mismo. Linux, al ver la partición
«sucia», la monta en solo lectura (o se niega a montarla).

Medidas:
1. **Tú**, una vez: inicio rápido e hibernación desactivados (`powercfg /h off`, §5).
2. `install.ps1` se niega a instalar si alguno está activo, y `start.ps1` lo vuelve a comprobar **en cada inicio de
   sesión** (una actualización grande de Windows a veces vuelve a encender el inicio rápido): si está activo, no arranca
   el panel y te lo dice.
3. `start.ps1` deja lo que vio en `data\windows-estado.json`. El panel de Linux lo lee al arrancar y, si Windows dijo
   que el inicio rápido o la hibernación estaban activos, **no escribe nada**.
4. El panel de los dos lados comprueba al arrancar que puede escribir en cada carpeta de datos (archivo de prueba con
   `fsync`) y, en Linux, que la partición no está montada en solo lectura (`statvfs`). Si no, se niega con un mensaje
   que explica la causa probable (Windows hibernado o con inicio rápido) y qué hacer.

### 2.2 SQLite en modo WAL sobre NTFS

- **Desde Linux (`ntfs3`)**: los cerrojos POSIX que usa SQLite son del núcleo y valen en cualquier sistema de archivos
  local, y `ntfs3` admite `mmap`, que es lo que necesita el `-shm` del WAL. **Desde Windows**: NTFS es su sistema de
  archivos nativo; SQLite usa allí sus propios cerrojos. Lo que no se puede es tener los dos a la vez, y eso el arranque
  dual ya lo impide.
- **El WAL que deja el otro sistema** no es peligroso en sí: el primer proceso que abre la BD sin nadie más conectado
  vacía el `-shm` y recupera las transacciones confirmadas del `-wal` (sumas de comprobación por página; mismo orden
  de bytes en los dos sistemas, x86-64). Lo peligroso es un `-wal` a medias por un apagado brusco **y** un NTFS sin
  reparar; de lo segundo se encarga §2.1 y de lo primero el cerrojo (§3.3).
- **Cierre limpio**: al parar el panel, `PRAGMA wal_checkpoint(TRUNCATE)` en las dos BDs (todo pasa al `.db` y el
  `-wal` queda vacío) y el cerrojo se marca «cerrado».
- **Windows no avisa al apagar a un proceso sin ventana** (el panel corre oculto): lo mata sin más. Por eso hay dos
  redes:
  1. el panel abre en Windows una ventana invisible que recibe el aviso de fin de sesión (`WM_ENDSESSION`) y hace el
     cierre limpio en ese momento (Windows da unos segundos);
  2. **checkpoint en reposo**: cada 2 minutos, si el `-wal` tiene algo, se pasa al `.db`. Así, aunque Windows mate el
     proceso, los datos en disco quedan casi siempre «en reposo», y un cerrojo sin cerrar con los datos en reposo no es
     un cierre sucio (§3.3).

### 2.3 Nombres de archivo

Windows no admite `< > : " / \ | ? *`, ni los nombres de dispositivo (`CON`, `NUL`, `AUX`, `PRN`, `COM1`…`LPT9`,
también con extensión), ni un punto o espacio al final, y **no distingue mayúsculas**: `Hola.md` y `hola.md` son el
mismo archivo, así que guardar uno pisaría el otro.

- Comprobado el 2026-11-16 sobre los datos reales: **967 archivos y carpetas** (148 notas, imágenes, papelera,
  historial, BDs) → **0 nombres no válidos, 0 choques de mayúsculas**; la ruta más larga mide 148 caracteres en Linux
  (en Windows, con `D:\panel-maestro\`, menos todavía: lejos del límite de 260).
- Los identificadores de nota ya solo admiten letras, números, `-` y `_` (`NOTE_ID_RE`), las imágenes y adjuntos se
  llaman por un `uuid` y la papelera por un token: nada de eso puede dar un nombre no válido.
- Lo que falta y se añade: un identificador de nota que sea un nombre de dispositivo (`con`, `nul`…) se rechaza (y el
  título «Con» da la nota `con-nota`), y una nota nueva cuyo nombre solo se distingue de otra en mayúsculas se rechaza
  con 409 (en Linux también: es el mismo archivo para Windows).
- `windows_names` en el `fstab` ya impide que Linux cree un nombre que Windows no admite (la escritura falla en vez
  de dejar un archivo que Windows no puede abrir).

### 2.4 Saltos de línea y codificación

- Python en Windows escribe `\r\n` en modo texto. Las notas se escriben siempre con `\n` (`atomic_write`), así el
  `.md` y su huella (la versión de D-4) son iguales en los dos sistemas.
- Python en Windows abre por defecto en `cp1252`: `start.ps1` arranca el panel en modo UTF-8 (`PYTHONUTF8=1`).

### 2.5 Permisos

NTFS no tiene permisos Unix. `ntfs3` muestra todo como del usuario `uid=1000` con los permisos de `umask=022` del
`fstab` (644/755): la `umask` 077 del panel (S-6) **no aplica en la partición**. Es un equipo de un solo usuario, así
que no es grave; si quieres que otros usuarios locales no puedan leer los datos, cambia en el `fstab` `umask=022` por
`umask=077` (lo haces tú). `chmod` en NTFS no hace nada útil: el panel ya no falla si no puede cambiarlos.

En Windows, la carpeta hereda los permisos de la unidad; `install.ps1` no los toca.

### 2.6 Antivirus, OneDrive e indexador de Windows

Abren los archivos para mirarlos justo cuando el panel los está cambiando: en Windows eso hace fallar el cambio
atómico (`os.replace` → «acceso denegado»). Medidas:

- `install.ps1` añade la carpeta a las exclusiones de Microsoft Defender (pide permiso de administrador una vez) y se
  niega si la carpeta está dentro de OneDrive.
- El panel reintenta el cambio atómico durante un segundo si Windows dice «en uso».
- La guía pide quitar la carpeta del indexador de búsqueda de Windows (§5).

### 2.7 Reloj

Linux guarda la hora del reloj del equipo (RTC) en UTC (`timedatectl`: «RTC in local TZ: no») y Windows, por defecto,
en hora local: tras cambiar de sistema, Windows va una hora mal hasta que sincroniza por red. Los datos usan horas UTC,
pero una hora equivocada desordena «la última copia», las fechas de modificación y el contador. `install.ps1` comprueba
`RealTimeIsUniversal` y te propone ponerlo a 1 (Windows en UTC, como Linux).

### 2.8 Zona horaria

En Windows no hay base de datos de zonas horarias del sistema que entienda Python: hace falta el paquete `tzdata`
(añadido a las dependencias solo para Windows).

## 3. Las guardas del panel (código, fase 2)

Viven en `app/datos_compartidos.py` y corren al principio del arranque, **antes de abrir ninguna BD**. Si se niegan,
el panel no arranca (código de salida 3), deja el motivo en `logs/arranque-denegado.json` (lo enseña `start.ps1`; en
Linux también va al registro y, si se puede, a una notificación) y no escribe nada en la carpeta de datos.

### 3.1 Estado de Windows
En Linux, si `data/windows-estado.json` dice que el inicio rápido o la hibernación estaban activos → se niega.

### 3.2 Carpeta escribible
Todas las carpetas de datos (notas, BDs, papelera, subidas, estado del calendario): existe o se puede crear, no está
montada en solo lectura y un archivo de prueba se escribe, se sincroniza y se borra → si no, se niega.

### 3.3 Cerrojo con el nombre del equipo: `data/panel-cerrojo.json`
`{sistema, equipo, pid, arranque, abierto, cerrado}`. «Arranque» identifica el encendido (en Linux el `boot_id`; en
Windows la hora de inicio). Al arrancar:

| Lo que encuentra | Qué hace |
|---|---|
| Nada, o cerrado bien por **este** sistema | Sigue |
| Cerrado bien por el **otro** sistema | Copia completa (zip `cambio-sistema` en las copias de **este** sistema) y sigue |
| Abierto por este mismo proceso | Sigue (reinicio del lifespan) |
| Abierto en este sistema, este encendido, proceso vivo | **Se niega**: ya hay otro panel con estos datos |
| Abierto, pero los datos están en reposo (sin `-wal` pendiente ni temporales a medias) | Sigue como si hubiera cerrado bien (copia si era el otro sistema) |
| Abierto por **este** sistema con `-wal` pendiente (se colgó o se fue la luz) | Copia en bruto (`.db` + `-wal`) a las copias, `integrity_check` sobre la copia: bien → sigue con aviso; mal → **se niega** |
| Abierto por el **otro** sistema con `-wal` pendiente (cierre sucio del otro lado) | Copia en bruto + `integrity_check` y **se niega siempre**, con el resultado. Para seguir: `python -m scripts.datos_compartidos seguir` (Windows: `start.ps1 -Seguir`, o «Sí» en el aviso), que repite la comprobación y solo sigue si sale bien |

La copia de un cierre sucio se hace una sola vez (queda anotada en el cerrojo): reintentar el arranque no llena el
disco de copias. En la unidad de systemd va `RestartPreventExitStatus=3`, para que una negativa no reinicie el
servicio cada 5 s.

### 3.4 Cierre
Al parar: checkpoint `TRUNCATE` de las dos BDs y cerrojo «cerrado» (con el último lifespan del proceso). En Windows,
además, al recibir el fin de sesión. El checkpoint en reposo (cada 2 min) es una tarea del programador: con
`PANEL_DISABLE_SCHEDULER=1` no corre.

### 3.5 Copias fuera
Si la carpeta de datos está en NTFS (o en Windows) y las copias o el espejo están en la misma unidad → aviso en
«Conexiones» (no se niega: la copia sigue valiendo para un fallo del panel, no para uno del disco).

### 3.6 Estado del calendario
`calendar_sync_v2.json` dice qué se sincronizó con iCloud por última vez. Va **con** las BDs: si cada sistema tuviera el
suyo, el que llevara más tiempo sin abrirse borraría de iCloud lo creado desde el otro. Por eso está en la partición.

## 4. Qué es solo de Linux

| Parte | En Windows |
|---|---|
| `playerctl` (música en Estudio) | No hay: la tarjeta queda sin reproductor |
| Dotfiles y «Publicar» (git + ssh, `~/dotfiles`) | Desactivados (`PANEL_PLATFORM=windows`) |
| rofi, Waybar, Hyprland, `notify-send`, `scripts/desktop/` | No se instalan |
| Abridor `panelmaestro://` (`xdg-open`) | No se instala |
| systemd, `scripts/desplegar.sh` | En su lugar, una tarea programada al iniciar sesión |
| ESP32 | Solo si pones `ESP32_HOST` en el `.env` de Windows (por defecto no) |
| iCloud | Igual que en Linux (mismo estado, §3.6) |
| Universidad y Proyectos | Las raíces son rutas de Linux guardadas en la BD: en Windows se fijan en el `.env` (`PANEL_UNI_ROOT=D:\Uja`, `PANEL_PROYECTOS_ROOT=…`), que manda sobre la BD |

`PANEL_PLATFORM` vale `linux` o `windows` (por defecto, el sistema en el que corre).

## 5. Pasos manuales en Windows (una vez)

En una consola de **administrador** (PowerShell):

```powershell
powercfg /h off                     # quita la hibernación y, con ella, el inicio rápido
powercfg /a                         # debe decir que la hibernación «no está disponible»
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f
reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f
```

Y además:
- Panel de control → Opciones de energía → «Elegir el comportamiento de los botones» → «Activar inicio rápido»
  **desmarcado** (es lo mismo que `HiberbootEnabled=0`; comprobarlo a la vista no está de más).
- Explorador → clic derecho en la unidad de datos → Propiedades → desmarcar «Permitir que los archivos de esta unidad
  tengan el contenido indizado».
- Que la unidad no esté en OneDrive ni en «Copia de seguridad de Windows».

## 6. Mover los datos de Linux a la partición (fase 3)

Lo haces tú, con el panel parado, con `scripts/datos_compartidos.py` (lee las rutas del `panel.env` del despliegue;
`--entorno` para otro):

```bash
systemctl --user stop panel-maestro
python -m scripts.datos_compartidos mover --destino /mnt/datos/panel-maestro            # simulacro: qué haría
python -m scripts.datos_compartidos mover --destino /mnt/datos/panel-maestro --hacer    # lo hace
systemctl --user start panel-maestro
```

Qué hace `--hacer`, en orden; si algo falla se para y no cambia `panel.env`:
1. Comprueba: panel parado, destino en una partición escribible y vacío (o inexistente), espacio suficiente.
2. **Copia completa verificada antes**: zip con el mismo formato que las copias del panel en
   `backups/pre-12/` (las dos BDs con la API de backup + `integrity_check`, notas, historial, papelera, subidas,
   adjuntos y estado del calendario, con sha256) **y** la carpeta de datos tal cual.
3. Copia al destino: las BDs con la API de backup (el `-wal` queda dentro), el resto archivo a archivo con sha256
   comprobado en los dos lados.
4. `integrity_check` de las dos BDs en el destino y recuentos iguales: notas `.md`, filas de las tablas principales
   (`notes`, `inbox`, `events`, `boards`, `resources`, `meals`, `ingredients`…), imágenes y adjuntos.
5. Cambia `panel.env` (copia previa `panel.env.antes-12`) con las rutas nuevas y deja en la carpeta vieja
   `data/MOVIDO-A-LA-PARTICION.txt`: un panel que arranque por error con los datos viejos se niega.
6. Los datos viejos **no se borran**: son la vuelta atrás.

### Vuelta atrás

```bash
systemctl --user stop panel-maestro
python -m scripts.datos_compartidos volver              # simulacro
python -m scripts.datos_compartidos volver --hacer
systemctl --user start panel-maestro
```

Copia lo de la partición de vuelta a las carpetas de siempre (con la misma verificación; lo que había allí se guarda
antes en `backups/pre-volver-<fecha>/`), restaura `panel.env.antes-12` y quita la marca. Así no se pierde lo que hayas
escrito después de mover. Si la partición no se puede leer: `volver --sin-copiar` solo restaura `panel.env` y la marca
(vuelves a los datos del momento de mover) y luego restauras la última copia desde `/backups`.

## 7. Windows: instalación (fase 4)

**Llevar el código y los secretos a Windows** (desde Linux, con los datos ya movidos):

```bash
git archive --format=zip -o /mnt/datos/panel-codigo.zip HEAD    # el código del commit actual, sin datos ni .env
cp .env /mnt/datos/linux.env                                     # TEMPORAL: lleva secretos; se borra tras instalar
```

(O descarga el zip de GitHub: es el mismo código.) En Windows, descomprime el zip y haz **doble clic en
`instalar.cmd`**. Busca solo la carpeta de datos (la única unidad con `panel-maestro\data\brain.db`) y el `linux.env`
de al lado, instala, arranca y abre el navegador; pedirá administrador una vez, para la exclusión del antivirus. Luego
borra los secretos: `Remove-Item D:\linux.env` (o en Linux `rm /mnt/datos/linux.env`). Equivale a:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Datos D:\panel-maestro -Secretos D:\linux.env
```

`-ExecutionPolicy Bypass` hace falta porque lo descargado de Internet lleva una marca que `RemoteSigned` no deja
ejecutar. **No lo ejecutes desde una app empaquetada** (MSIX, como la terminal de la app de Claude): Windows desvía `%LOCALAPPDATA%` a la carpeta del paquete y la tarea programada no encuentra la
instalación (falla con `0x8007010B`). Usa el doble clic o una PowerShell abierta desde Inicio.

`install.ps1`:
1. **Se niega** si el inicio rápido (`HiberbootEnabled`) o la hibernación están activos (y dice el comando), si la
   carpeta está en OneDrive o si no tiene datos del panel (`data\brain.db`; para no crear datos vacíos por una letra
   de unidad equivocada; `-Nueva` lo permite). Avisa si el reloj no está en UTC (§2.7) o si las rutas largas están
   desactivadas.
2. Python 3.14 con `winget` si no hay 3.12–3.14; `venv` en `%LOCALAPPDATA%\PanelMaestro\venv` con
   `requirements.lock` (uvloop se queda fuera en Windows; si el lock falla, `requirements.txt` + `tzdata`).
3. Copia el código a `%LOCALAPPDATA%\PanelMaestro\app` (`robocopy`, sin `.git`, datos ni BDs).
4. `%LOCALAPPDATA%\PanelMaestro\.env` (UTF-8 sin BOM): rutas de la partición con `/`, copias y logs en
   `%LOCALAPPDATA%`, `PANEL_PLATFORM=windows`, `PANEL_HOST=127.0.0.1`, la universidad (`-Universidad`, o `X:\Uja` si
   existe) y, de `-Secretos`, la contraseña, el secreto y la generación de sesión, el token de la extensión, iCloud y
   las claves de IA. Sin `-Secretos` pide una contraseña (`scripts.set_password`).
5. Exclusión de Microsoft Defender para la carpeta de datos (UAC; `-SinDefender` lo salta). Solo la primera vez: al
   actualizar no la vuelve a pedir.
6. Tarea programada «Panel Maestro» al iniciar sesión (solo tu usuario, oculta) que lanza `start.ps1`.
7. Accesos directos «Panel Maestro» (a `http://127.0.0.1:8000/`) y «Actualizar Panel Maestro», en el escritorio y en
   Inicio. Arranca y enseña el estado de los datos.

Si ya estaba instalado, antes de copiar el código para el panel con `start.ps1 -Parar` (de la versión nueva): con el
panel en marcha la tarea no se relanza y seguiría el código viejo hasta el siguiente inicio de sesión.

`start.ps1` (lo lanza la tarea): comprueba otra vez inicio rápido e hibernación (si están activos: aviso y no
arranca), escribe `windows-estado.json`, arranca el panel en modo UTF-8 y, si se niega a arrancar, enseña el motivo en
una ventana; tras un cierre sucio de Linux pregunta «¿Comprobar otra vez y seguir?». Reintenta 3 veces si se cae por
otra cosa. Más:

```powershell
& "$env:LOCALAPPDATA\PanelMaestro\app\start.ps1" -Estado    # cerrojo, WAL, integrity_check y recuentos
& "$env:LOCALAPPDATA\PanelMaestro\app\start.ps1" -Parar     # para la tarea y el panel y deja los datos cerrados
& "$env:LOCALAPPDATA\PanelMaestro\app\start.ps1" -Seguir    # confirma un cierre sucio de Linux y arranca
```

`-Parar` detiene primero la tarea: si no, su bucle relanzaría el panel a los 5 s mientras `seguir` cierra los datos.

**Actualizar** en Windows: **doble clic en «Actualizar Panel Maestro»** (escritorio o Inicio). Descarga la última
versión de `main` en GitHub (`scripts/windows/actualizar.ps1`), ejecuta su `install.ps1` con los datos del `.env`, y al
terminar abre el panel; solo se queda esperando si algo falla. Lo publicado en GitHub tiene que ser la versión que ya
corre en Linux (`scripts/desplegar.sh`): si Windows llevara migraciones que Linux no tiene, el panel de Linux se
encontraría una BD más nueva que su código. Desde una carpeta con el código, `instalar.cmd` hace lo mismo.

**Desinstalar**: `.\install.ps1 -Desinstalar` para el panel (y cierra los datos), quita la tarea, los accesos directos
y la exclusión, y pregunta antes de borrar `%LOCALAPPDATA%\PanelMaestro` (código, venv, `.env`, logs **y las copias
de Windows**). **Nunca** toca la carpeta de datos.

## 8. Verificación

### En Linux (antes de mover nada)
1. `scripts/probar_ntfs.sh`: imagen NTFS de 512 MB en una carpeta temporal, montada con `ntfs3` y las mismas
   opciones del `fstab`, y dentro: los tests unitarios (los de permisos Unix se saltan: §2.5), un panel real que guarda
   una nota con acentos y cierra limpio, la imagen en solo lectura (debe negarse) y un cierre sucio simulado de Windows
   (debe negarse sin escribir nada; `seguir` y vuelve a arrancar). Necesita `sudo` y `mkntfs`
   (`sudo pacman -S --needed ntfsprogs`). `--sin-imagen` hace los mismos pasos en una carpeta normal, sin sudo.
2. `tests/test_datos_compartidos.py`: todas las guardas, `mover` y `volver` (simulacro sin cambios, copia verificada,
   marca, lo escrito después vuelve) y `seguir`.
3. `python -m scripts.datos_compartidos estado` sobre los datos reales: integrity_check y recuentos de partida.

### En Windows (lo haces tú, guiado)
1. `powercfg /a` → hibernación «no disponible». `.\install.ps1 -Datos D:\panel-maestro -Secretos D:\linux.env`
   termina sin errores y enseña el estado: **los recuentos deben ser iguales** a los de `estado` en Linux.
2. Cierra sesión y vuelve a entrar: el panel responde en `http://127.0.0.1:8000/` con tus notas (la contraseña es la de
   Linux).
3. Crea una nota «prueba-windows» y una tarea. Apaga **desde Inicio → Apagar**.
4. Arranca Linux: el panel arranca solo y hay una copia «Cambio de sistema» en `/backups`; la nota y la tarea están.
   `python -m scripts.datos_compartidos estado` → «Windows (…), cerrado» (o «SIN CERRAR» con «WAL pendiente: nada»,
   que también es seguro: §3.3). Si dice que el aviso de fin de sesión no llegó, anótalo.
5. Borra la nota de prueba desde Linux, apaga y vuelve a Windows: ya no está. `start.ps1 -Estado` → «Linux (…),
   cerrado».
6. La negativa en Windows: como administrador `powercfg /h on`, cierra sesión y entra → aviso y el panel **no**
   arranca. Arranca Linux → el panel de Linux tampoco (lee `windows-estado.json`). Vuelve a Windows,
   `powercfg /h off`, cierra sesión y entra.
7. Cierre sucio de verdad: en Windows, escribe algo y mata el proceso en los dos minutos siguientes
   (Administrador de tareas → `python.exe`) y apaga. En Linux el panel no arranca, `journalctl --user -u panel-maestro`
   dice por qué y `python -m scripts.datos_compartidos seguir` lo resuelve.
