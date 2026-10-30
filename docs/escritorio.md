# Integración con el escritorio (Hyprland + Waybar)

Opcional y pensado para Linux con Hyprland, Waybar y rofi: captura rápida con un atajo, agenda en un menú y un módulo
de la barra con lo siguiente que tienes. Los atajos de abajo son los que uso yo; ponlos donde prefieras.

Todo vive en `scripts/desktop/` y solo usa la biblioteca estándar de Python, `rofi` y `notify-send`.
La configuración del sistema solo recibe una línea en Hyprland y un módulo en la Waybar.

## Token (una vez)

```bash
python -m scripts.desktop_token          # hash en .env (PANEL_DESKTOP_TOKEN_HASH) y token en ~/.config/panel-maestro/token (600)
systemctl --user restart panel-maestro   # para que el panel lea el hash
```

Es un token aparte del de la extensión de Firefox: crear uno no invalida el otro. La dirección del panel
se puede cambiar en `~/.config/panel-maestro/url` (por defecto `http://127.0.0.1:8000`).

## Captura rápida — `Super+K`

`scripts/desktop/quick_capture.sh` abre un menú rofi de una línea con el mismo estilo que los menús del
sistema (`scripts/desktop/rofi/panel-captura.rasi` es una copia de `~/.config/rofi/config-search.rasi`).
El atajo va en `Super+K` (libre; `Super+G` ya era «toggle group») en
`~/.config/hypr/UserConfigs/UserKeybinds.lua`. Sin escribir el prefijo: `Alt+1` tarea, `Alt+2` idea, `Alt+3`
rutina, `Alt+4` evento. Una tarea o idea con fecha clara la guarda («t: llamar a Juan el viernes»); todo lo que
lleva algo que interpretar se confirma antes («Corregir el texto» vuelve al menú).

## Agenda — `Super+Alt+K` (o clic en la hora de la Waybar)

Menú rofi con acciones (nuevo evento, capturar, abrir el calendario), las atrasadas y los próximos 7 días por
días. `Intro` abre las opciones; directamente: `Alt+C` completar, `Alt+P` +1 hora, `Alt+M` a mañana, `Alt+O`
abrir. Tras cada acción el menú vuelve a abrirse en la misma fila. (`Super+Ctrl+K` es «Move left into group».)

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

- **Texto**: la hora y lo próximo con hora («17:00 Dentista», o «en 25 min Dentista» si falta menos de una
  hora; lo que está en curso, con «hasta HH:MM»).
- **Clases** (`style/Fusion Personalizada.css`): `sin-eventos` y `con-eventos` (azul, como el reloj), `proximo`
  (melocotón), `ahora` (verde), `retrasado` (rojo: tareas o rutinas de hoy con la hora pasada) y
  `sin-conexion` (atenuado).
- **Tooltip**: el mes con hoy resaltado (los días con algo, subrayados) y la agenda de hoy y mañana
  (eventos, rutinas y tareas con fecha).
- **Clic**: rofi con la agenda de 7 días; al elegir, completar, posponer (1 h o a mañana) o abrir en el Panel.
  **Clic derecho**: evento rápido (la captura con «e: » ya escrito). **Rueda**: mes anterior o siguiente;
  **clic central**: volver al mes actual.
- Se actualiza cada 15 s y con `pkill -RTMIN+9 waybar`. Sin conexión usa la última agenda
  (`~/.cache/panel-maestro/agenda.json`) sin errores ni parpadeos.
- De paso, reenvía la cola de capturas y lanza con `notify-send` los avisos de escritorio (eventos, tareas y
  rutinas con hora, repaso de flashcards) según Panel → Ajustes → Avisos.

Recargar: `pkill waybar; setsid -f waybar` (más fiable que SIGUSR2 en esta barra).

## Pruebas

`tests/test_desktop_capture.py` lanza el script real contra el panel de pruebas (con el token Bearer de
verdad) y un rofi y un `notify-send` simulados; `tests/test_waybar.py` cubre estados, tooltip y caché.
