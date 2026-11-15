# El panel desde fuera de casa (Tailscale)

El panel vive en el portátil. Fuera de casa el móvil no lo ve, y abrir un puerto en el router lo dejaría expuesto a
internet. **Tailscale** crea una red privada entre tus dispositivos (la «tailnet»): el móvil llega al portátil esté
donde esté, sin abrir puertos, y con `tailscale serve` el panel tiene HTTPS con un certificado válido.

## Qué hace falta

1. Tailscale en el portátil y el panel publicado con `tailscale serve`: pasos en [HTTPS.md](HTTPS.md), opción A.
2. La app de Tailscale en el móvil (Android o iOS), con la misma cuenta. Actívala.
3. El portátil encendido, despierto y con conexión a internet.

## Qué dirección usar

| Desde | Dirección |
|---|---|
| El móvil, en casa o fuera | `https://<equipo>.<tailnet>.ts.net` (la da `tailscale serve status`) |
| El propio portátil | `http://localhost:8000` (o la de arriba) |
| Extensión de Firefox | La de `ts.net`, en Opciones → Guardar (pide permiso solo para ella) |
| rofi, Waybar, abridor | `~/.config/panel-maestro/url` con la de `ts.net` o `http://127.0.0.1:8000` (sin red, más rápido) |

Instala la PWA en el móvil desde la dirección `ts.net` («Añadir a la pantalla de inicio»): con HTTPS funcionan el
service worker, el cifrado de notas y el portapapeles.

## Qué no funciona fuera de casa

- **Con el portátil dormido o apagado no hay panel.** Tailscale no lo despierta. Si lo necesitas a menudo, evita la
  suspensión mientras está enchufado.
- **ESP32**: la placa está en la red de casa y el panel se conecta a ella por la wifi local (`ESP32_HOST`). Si el
  portátil sale de casa, la página Estudio la verá desconectada. La sincronía con iCloud sigue funcionando.
- **Abrir carpetas** (`panelmaestro://`, Universidad y Proyectos): abre la carpeta en el **portátil**, no en el móvil.
  Desde el móvil no hace nada.
- **Carpeta de la universidad** (`/run/media/...`): solo se ve si el disco está conectado al portátil.
- **Avisos del escritorio** (`notify-send`, Waybar): salen en el portátil, no en el móvil.

## Seguridad

- Solo tus dispositivos de la tailnet llegan al panel; sigue pidiendo la contraseña (o la cookie de 30 días).
- No uses `tailscale funnel`: publicaría el panel en internet.
- Con `PANEL_HOST=127.0.0.1` el panel no escucha en la wifi: tampoco se puede entrar por `http://192.168.x.x:8000`.
  Si alguna vez lo necesitas, quita esa línea del `.env` y reinicia el servicio.
- Si pierdes el móvil: en Ajustes del panel, «Cerrar las demás sesiones», y quita el dispositivo en
  <https://login.tailscale.com/admin/machines>.
