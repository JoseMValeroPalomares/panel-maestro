# Servir el panel por HTTPS

**Por qué.** Abierto por `http://192.168.x.x:8000`, la contraseña del login, la cookie de sesión (30 días) y los tokens
de la extensión y del escritorio viajan en claro por la wifi. Además el navegador lo trata como un contexto *no seguro*:
no hay cifrado de notas (`crypto.subtle`: «Cifrar» lo explica y enlaza aquí), ni portapapeles moderno, ni service
worker fiable. En el propio portátil (`http://localhost:8000`) no pasa: localhost cuenta como seguro.

Hay dos caminos. **Tailscale es el recomendado**: certificado válido sin instalar nada en el móvil y, de paso, el panel
desde fuera de casa ([fuera-de-casa.md](fuera-de-casa.md)). **mkcert** sirve si solo lo usas en casa y no quieres
Tailscale.

Lo que el panel ya hace solo, elijas lo que elijas:

- **Cookie `Secure`** cuando la petición llega por HTTPS (también se puede forzar con `PANEL_COOKIE_SECURE=true`; no lo
  pongas si sigues entrando por HTTP desde algún sitio: el navegador no guardaría la cookie).
- **HSTS** (`Strict-Transport-Security: max-age=15552000`) solo en las respuestas por HTTPS; por HTTP no se manda.
- `start.sh` arranca uvicorn con `--proxy-headers --forwarded-allow-ips 127.0.0.1`: detrás de `tailscale serve` (que
  habla con el panel desde 127.0.0.1) sabe que la petición original era HTTPS. Nadie más puede hacerse pasar por proxy.

## Opción A (recomendada): Tailscale

`tailscale serve` pone delante del panel un HTTPS con certificado de Let's Encrypt para
`https://<equipo>.<tailnet>.ts.net`. El panel sigue en HTTP, pero **solo en 127.0.0.1**: nadie de la wifi llega a él.

```bash
# 1. Instalar y entrar (una vez; lo haces tú: toca el sistema)
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up                                   # abre el navegador para iniciar sesión
# En https://login.tailscale.com/admin/dns: activa «MagicDNS» y «HTTPS Certificates»

# 2. El panel solo en local (.env del proyecto)
echo 'PANEL_HOST=127.0.0.1' >> .env
systemctl --user restart panel-maestro

# 3. Publicarlo en la tailnet (se queda configurado tras reiniciar)
sudo tailscale serve --bg 8000
tailscale serve status                              # muestra https://<equipo>.<tailnet>.ts.net

# 4. (Opcional) Que http://<equipo>.<tailnet>.ts.net lleve solo a https://
sudo tailscale serve --bg --http=80 8000
```

`tailscale serve` no sabe redirigir: el paso 4 manda también el puerto 80 al panel, y el panel
(`core/errors.HttpsRedirectMiddleware`) contesta 308 a la misma dirección en `https://` cuando la petición llegó por HTTP a
través de Tailscale (sin `X-Forwarded-Proto`, que Tailscale solo pone por TLS, y con un nombre `*.ts.net`; el nombre corto
de MagicDNS, `http://<equipo>`, va al completo, que es el del certificado), antes de pedir la contraseña. El acceso local
`http://127.0.0.1:8000` (Waybar, scripts del escritorio) no se redirige. Comprobarlo:
`curl -sI http://<equipo>.<tailnet>.ts.net/hoy | grep -i -E '^(HTTP|location)'` → `308` y `location: https://…/hoy`.
Quitar solo el paso 4: `sudo tailscale serve --http=80 off`.

En el móvil: la app de Tailscale con la misma cuenta, y el panel en `https://<equipo>.<tailnet>.ts.net`.

**Vuelta atrás**: `sudo tailscale serve reset`, quitar `PANEL_HOST` del `.env` y `systemctl --user restart panel-maestro`.

## Opción B: mkcert (solo red local)

`mkcert` crea una autoridad de certificación **local** y certificados que ella firma (no salen de tu máquina).

```bash
# 1. Instalar (Arch: sudo pacman -S mkcert nss; Debian/Ubuntu: sudo apt install mkcert libnss3-tools)
mkcert -install                                     # crea la CA local y confía en ella en ESTE equipo
mkdir -p ~/.config/panel-maestro/tls && cd ~/.config/panel-maestro/tls
mkcert -cert-file panel.pem -key-file panel-key.pem panel.local 192.168.1.41 localhost 127.0.0.1
chmod 600 panel-key.pem                             # pon la IP o el nombre con que abres el panel

# 2. En el .env del proyecto (start.sh y el servicio lo leen de ahí)
PANEL_SSL_CERT=~/.config/panel-maestro/tls/panel.pem
PANEL_SSL_KEY=~/.config/panel-maestro/tls/panel-key.pem

# 3. Reiniciar
systemctl --user restart panel-maestro              # → https://192.168.1.41:8000
```

**Móvil u otro equipo**: hay que instalar y confiar en la CA local (`rootCA.pem`; la carpeta la da `mkcert -CAROOT`).
Android → Ajustes › Seguridad › Cifrado y credenciales › Instalar un certificado › Certificado de CA; iOS → AirDrop del
`rootCA.pem`, instalar el perfil y activarlo en Ajustes › General › Información › Certificados de confianza. Nunca
compartas `rootCA-key.pem`.

**Vuelta atrás**: quitar `PANEL_SSL_CERT` y `PANEL_SSL_KEY` del `.env` y reiniciar el servicio.

## Lo que guarda la dirección del panel (hay que cambiarlo al pasar a HTTPS)

| Dónde | Qué poner |
|---|---|
| Extensión de Firefox → Opciones | La dirección nueva (`https://…`). Al guardar pide permiso solo para ese origen |
| `~/.config/panel-maestro/url` (rofi `Super+K`, Waybar, abridor `panelmaestro://`) | La dirección nueva. Con mkcert, además la CA en `~/.config/panel-maestro/ca.pem` (`cp "$(mkcert -CAROOT)/rootCA.pem" ~/.config/panel-maestro/ca.pem`); con Tailscale no hace falta, su certificado es público |
| Móvil (PWA instalada) | Abrir la dirección nueva y volver a «Añadir a la pantalla de inicio»: la PWA anterior apunta a la vieja |
| `SERVER_BASE_URL` (`.env`) | Puede quedarse en `http://localhost:8000`: solo la usa el portátil para abrir una nota en su navegador cuando la pide el ESP32. El ESP32 no llama al panel (es el panel quien se conecta a él por websocket), así que no le afecta |

El manifest de la PWA y el service worker usan rutas relativas: no hay que tocarlos. La CSP solo permite `'self'`.

Si un cliente del escritorio no se fía del certificado, no lo confunde con «sin conexión»: avisa de que falta la CA y
guarda la captura en la cola hasta que se arregle.

Para `curl` con la CA local: `curl --cacert "$(mkcert -CAROOT)/rootCA.pem" https://…/healthz`.
