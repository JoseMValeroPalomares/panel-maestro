# Integración con el escritorio (Hyprland + Waybar)

Opcional y pensado para Linux con Hyprland, Waybar, rofi y swaync: captura rápida con un atajo, un centro de mando en
rofi, notificaciones con botones y un módulo de la barra con lo siguiente que tienes. Los atajos de abajo son los que uso yo; ponlos donde prefieras.

Todo vive en `scripts/desktop/` y solo usa la biblioteca estándar de Python, `rofi` y `notify-send`.
La configuración del sistema solo recibe una línea en Hyprland y un módulo en la Waybar.

## Token (una vez)

```bash
python -m scripts.desktop_token          # hash en .env (PANEL_DESKTOP_TOKEN_HASH) y token en ~/.config/panel-maestro/token (600)
systemctl --user restart panel-maestro   # para que el panel lea el hash
```

Es un token aparte del de la extensión de Firefox: crear uno no invalida el otro. La dirección del panel
se puede cambiar en `~/.config/panel-maestro/url` (por defecto `http://127.0.0.1:8000`). Con HTTPS
([HTTPS.md](HTTPS.md)) va la dirección `https://…`; si el certificado es de mkcert, la CA en
`~/.config/panel-maestro/ca.pem` (con Tailscale no hace falta). Sin ella, la captura avisa de que no se fía del
certificado y guarda el texto en la cola, no lo da por «sin conexión».

## Captura rápida — `Super+K`

`scripts/desktop/quick_capture.sh` abre un menú rofi de una línea con el mismo estilo que los menús del
sistema (`scripts/desktop/rofi/panel-captura.rasi` es una copia de `~/.config/rofi/config-search.rasi`).
El atajo va en `Super+K` (libre; `Super+G` ya era «toggle group») en
`~/.config/hypr/UserConfigs/UserKeybinds.lua`. Sin escribir el prefijo: `Alt+1` tarea, `Alt+2` idea, `Alt+3`
rutina, `Alt+4` evento. Una tarea o idea con fecha clara la guarda («t: llamar a Juan el viernes»); todo lo que
lleva algo que interpretar se confirma antes («Corregir el texto» vuelve al menú).

## Qué va en cada sitio (P-11)

Cada cosa vive en un solo sitio, sin duplicar:

| Sitio | Para qué | Qué hay |
|---|---|---|
| **Waybar** | mirar | hora, lo siguiente con cuenta atrás, número de atrasadas, aviso de copias, contador en marcha |
| **rofi** | hacer | `Super+K` captura · `Super+Alt+K` (o clic en la hora) centro de mando |
| **Notificaciones** | lo que llega a su hora | avisos con botones, resumen de la mañana, atrasadas, copias |
| **Calendario `.ics`** | otras aplicaciones | enlace de solo lectura con token |

## Centro de mando — `Super+Alt+K` (o clic en la hora de la Waybar)

`scripts/desktop/panel_mando.py` (el atajo y la Waybar llaman a `panel_agenda.py --menu`, que lo abre). Un menú rofi con
modos; las `Alt+número` cambian de modo en cualquier momento:

| Tecla | Modo | Qué enseña |
|---|---|---|
| `Alt+1` | Hoy (al abrir) | el contador en marcha (o «Empezar el contador…»), Capturar, Nuevo evento, las atrasadas, hoy y mañana |
| `Alt+2` | Semana | los próximos 7 días y «Abrir el calendario» |
| `Alt+3` | Buscar | tareas e ideas pendientes y todas las notas; escribe para filtrar. `Ctrl+Intro` (o Intro sin coincidencias) busca **dentro del texto** (la misma búsqueda que Ctrl+K en el panel). `Alt+3` otra vez vuelve a la lista |
| `Alt+4` | Capturar | abre la captura rápida (`Super+K`) |

Sobre cada línea:

| Tecla | Acción |
|---|---|
| `Intro` | opciones de la línea (las mismas de abajo, más **Borrar**, que pide confirmación y va a la papelera del panel) |
| `Alt+C` | completar (o desmarcar); en la fila del contador, completar lo que está en marcha |
| `Alt+P` | posponer: 1 hora si tiene hora; si está atrasada, la trae a hoy |
| `Alt+M` | a mañana |
| `Alt+E` | empezar el contador con esa tarea o rutina; en la fila del contador, pausar o seguir |
| `Alt+O` | abrir en el panel (una nota se abre también con Intro) |

Tras cada acción el menú vuelve a abrirse en el mismo modo y en la misma fila. Sin conexión es de solo lectura, con la
última agenda guardada; Buscar necesita el panel.

## Notificaciones

Todas salen como la app «Panel» (swaync las agrupa; no hace falta tocar su configuración). Las que se repiten
(copias, confirmaciones, el contador) **sustituyen** a la anterior en vez de amontonarse (pista `synchronous`).

- **Tareas y rutinas con hora**: botones Empezar · Completar (Hecha en las rutinas) · +1 hora (o Mañana si es de todo el
  día). Clic en el aviso: abrirla en el panel.
- **Eventos**: clic para abrirlos en el calendario.
- **Resumen de la mañana** (por defecto a las 08:30, Panel → Avisos): «Hoy, lunes 16 · 3 tareas, 2 clases, 1 entrega ·
  2 atrasadas». Botón «Ver el día» (el centro de mando) y clic para abrir Hoy. Si no hay nada, no sale. Si el portátil
  estaba dormido, sale hasta 3 horas tarde.
- **Atrasadas**: una por tarea con Completar · Mañana · Hoy no · Borrar, a la hora y los días de Avisos (P-1).
- **Sin repetidos**: el navegador y el portátil piden los avisos por su cuenta; antes de enseñar uno lo reclaman en el
  panel (`POST /api/reminders/vistos`) y solo lo enseña el primero.

### Qué se puede escribir en la captura

| Escribes | Se crea |
|---|---|
| `comprar pilas` | tarea en el Inbox, sin clasificar |
| `t: llamar al banco` | tarea |
| `i: app de recetas` | idea |
| `r: gimnasio lunes y jueves a las 19` | rutina (cada día, de lunes a viernes, fines de semana, días sueltos, cada N días; hora opcional) |
| `e: dentista mañana 17:00` · `e: examen de SO 3 nov 9:00 2h` · `e: reunión viernes 10:30` | evento (Europe/Madrid; 1 h por defecto; sin hora, todo el día) |

Un evento muestra antes una vista previa (título, día y hora): Intro guarda, Esc cancela. Si la fecha no
se entiende con seguridad («e: dentista 17:00», sin día) **no se inventa**: va al Inbox con la categoría
«Revisar fecha» y te avisa. Sin conexión, el texto se guarda en `~/.local/state/panel-maestro/cola.jsonl`
y se reenvía en orden en la siguiente captura o en cuanto la Waybar vea el panel.

## Módulo de la Waybar — `custom/panel-agenda`

`scripts/desktop/panel_agenda.py` sustituye al reloj (`clock`) de la barra inferior (`configs/2`):

- **Texto**: la hora, el día y lo próximo: «en 25 min Dentista» si falta menos de una hora, «en 2 h 10 Examen» si es
  hoy y falta menos de 6 horas, si no su hora («17:00», «mañana 07:50», «jue 09:00»); lo que está en curso, con «hasta
  HH:MM». Al final, solo cuando los hay, el número de **atrasadas** en rojo (`⚠ 3`, «20+» si son muchas) y un
  icono de **copias** en melocotón si no están al día. Los colores van en el propio texto: no hace falta CSS.
- **Clases** (`style/Fusion Personalizada.css`, opcionales): `sin-eventos`, `con-eventos`, `proximo`, `ahora`,
  `retrasado` (tareas o rutinas de hoy con la hora pasada), `atrasadas`, `copias-aviso` y `sin-conexion` (atenuado).
- **Tooltip**: el mes con hoy resaltado (los días con algo, en azul) y la agenda de hoy y mañana (eventos, rutinas y
  tareas con fecha), los próximos días, las atrasadas y el estado de las copias si fallan.
- **Clic**: el centro de mando. **Clic derecho**: evento rápido (la captura con «e: » ya escrito). **Rueda**: mes
  anterior o siguiente; **clic central**: volver al mes actual.
- Se actualiza cada 15 s y con `pkill -RTMIN+9 waybar`. Sin conexión usa la última agenda
  (`~/.cache/panel-maestro/agenda.json`) sin errores ni parpadeos.
- De paso, reenvía la cola de capturas y lanza las notificaciones de arriba.

El contador en marcha es otro módulo, `custom/panel-contador` ([waybar-contador.md](waybar-contador.md)): clic
pausa o sigue; clic derecho, su menú.

Recargar: `pkill waybar; setsid -f waybar` (más fiable que SIGUSR2 en esta barra).

## Calendario en otras aplicaciones (`.ics`)

Panel → Calendario → menú «⋯» → **Enlace para otro calendario…** crea una dirección `…/cal/<token>.ics` de solo
lectura para suscribirse desde GNOME Calendar, Thunderbird, el móvil, etc. Añade `?tareas=1` (la casilla del diálogo)
para incluir las tareas con fecha sin hacer; las de notas cifradas o sensibles nunca salen. La dirección se ve una
sola vez (se guarda solo su hash); «Crear otro» invalida la anterior y «Revocar» la apaga. Los clientes la refrescan
cada 30 min. Fuera de casa, el enlace solo funciona si el cliente llega al panel (Tailscale; ver [HTTPS.md](HTTPS.md)).
«Exportar (.ics)» del mismo menú sigue descargando un archivo para importarlo a mano.

## Pruebas

`tests/test_desktop_capture.py` lanza el script real contra el panel de pruebas (con el token Bearer de
verdad) y un rofi y un `notify-send` simulados; `tests/test_waybar.py` cubre estados, tooltip y caché;
`tests/test_mando.py` lanza el centro de mando y los avisos con botones contra el panel de pruebas, con rofi,
`notify-send`, `xdg-open` y `pkill` simulados (nada llega al escritorio de verdad); `tests/test_calendario_ics.py` y
`tests/test_avisos_resumen.py` cubren el enlace `.ics`, el resumen y los avisos sin repetidos.
