# Contador en marcha en la Waybar (P-2) — instalado el 2026-11-15

El módulo es `scripts/desktop/panel_contador.py` (solo biblioteca estándar, usa el token del escritorio como
`panel_agenda.py`). Es un proceso **continuo**: la Waybar lo arranca una vez (`exec` sin `interval`) y el script escribe
una línea JSON por segundo mientras algo está en marcha, calculada en local con la hora de inicio. Al Panel solo le
pregunta cada 30 s (con un latido: «el portátil sigue encendido»; si el portátil se duerme más de 45 min, el Panel pausa
el contador solo y ofrece «Contar ese tiempo») o al instante cuando el clic o el menú cambian algo (SIGUSR1).

- **Clic:** pausar / seguir (sin nada en marcha, abre el menú).
- **Clic derecho:** rofi con Pausar/Seguir, Completar, Cambiar a otra (tareas y rutinas de hoy, atrasadas, o escribir una
  actividad libre), Quitar (el tiempo se guarda) y Abrir en el Panel.
- **Notificaciones:** al empezar algo (desde donde sea: panel, móvil, rofi) y al pasar la duración prevista; una vez por
  sesión (estado en `~/.local/state/panel-maestro/contador.json`).
- **Clases:** `marcha`, `pausa`, `pasado`, `vacio` (texto vacío: la Waybar lo oculta) y `sin-conexion`.
- En el rofi de la agenda (Super+Alt+K) cada tarea o rutina tiene además **Empezar contador** (Alt+E).

## Cambios en `~/.config/waybar` (aplicados el 2026-11-15)

Copias previas: `*.bak-panel-20261115-110057` de los tres archivos. Para deshacer, cópialas encima y `pkill -SIGUSR2 waybar`.
Con dos monitores hay una instancia por barra: cada una se apunta en `~/.local/state/panel-maestro/contador.pids/` y
`--toggle`/`--menu` avisan a todas (solo a pids que de verdad son el módulo).

### `ModulesCustom` (después de `custom/panel-agenda`)

```diff
 	"on-scroll-down": "$HOME/Projects/panel-maestro/scripts/desktop/panel_agenda.py --mes +1",
 },
 
+// Contador en marcha del Panel (P-2): tiempo de lo que estás haciendo. Clic: pausar/seguir · clic derecho: menú.
+// Proceso continuo (sin interval): pinta cada segundo en local y pregunta al Panel cada 30 s o al cambiar algo.
+"custom/panel-contador": {
+	"format": "{}",
+	"return-type": "json",
+	"escape": false,
+	"tooltip": true,
+	"exec": "$HOME/Projects/panel-maestro/scripts/desktop/panel_contador.py",
+	"restart-interval": 10,
+	"on-click": "$HOME/Projects/panel-maestro/scripts/desktop/panel_contador.py --toggle",
+	"on-click-right": "$HOME/Projects/panel-maestro/scripts/desktop/panel_contador.py --menu",
+},
+
 "custom/hyprpicker": {
```

### `configs/2` (al lado de la agenda, en el centro)

```diff
     "custom/panel-agenda", // antes "clock": la agenda del Panel lleva la hora
+    "custom/panel-contador", // contador en marcha (vacío y oculto si no hay nada)
     "custom/separator#line",
```

### `style/Fusion Personalizada.css`

```diff
-#custom-updater, #custom-hyprpicker, #custom-weather, #custom-panel-agenda {
+#custom-updater, #custom-hyprpicker, #custom-weather, #custom-panel-agenda, #custom-panel-contador {
     padding-top: 4px;
@@
 #custom-panel-agenda.sin-conexion { opacity: 0.6; }        /* datos de la caché */
+#custom-panel-contador { color: @mocha-teal; }
+#custom-panel-contador.pausa { color: @mocha-subtext0; }   /* en pausa */
+#custom-panel-contador.pasado { color: @mocha-peach; }     /* más tiempo del previsto */
+#custom-panel-contador.sin-conexion { opacity: 0.6; }
```

Para recargar después: `pkill -SIGUSR2 waybar` (recarga la configuración) o cerrar sesión. Si el despliegue (C-4) sirve
el panel desde `~/.local/share/panel-maestro/actual`, las rutas `$HOME/Projects/...` de arriba siguen valiendo para los
scripts del escritorio (no dependen del servidor).
