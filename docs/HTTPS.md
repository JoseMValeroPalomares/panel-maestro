# Servir el panel por HTTPS en la red local

**Por qué.** Abierto por `http://192.168.x.x:8000`, el navegador lo trata como un contexto *no seguro*: no existe
`navigator.clipboard` (copiar con la API moderna), ni service workers fiables, ni otras APIs. El panel ya funciona sin
ellos —por ejemplo, **Copiar** usa un `textarea` + `execCommand('copy')` dentro del clic—, pero HTTPS es la solución
definitiva: todo va por la vía normal, y la cookie de sesión puede ser `Secure`.

## Opción A (la más simple): mkcert + el propio servidor del panel

`mkcert` crea una autoridad de certificación **local** y certificados que ella firma (no salen de tu máquina).

```bash
# 1. Instalar mkcert (Arch: sudo pacman -S mkcert nss; Debian/Ubuntu: sudo apt install mkcert libnss3-tools)
mkcert -install                                    # crea y confía en la CA local en ESTE equipo
mkdir -p ~/.config/panel-maestro/tls && cd ~/.config/panel-maestro/tls
mkcert panel.local 192.168.1.41 localhost 127.0.0.1   # pon aquí la IP/nombre con que abres el panel
# genera «panel.local+3.pem» y «panel.local+3-key.pem»

# 2. Arrancar el panel con HTTPS (start.sh ya admite SSL_CERT / SSL_KEY)
cd ~/Projects/panel-maestro
SSL_CERT=~/.config/panel-maestro/tls/panel.local+3.pem SSL_KEY=~/.config/panel-maestro/tls/panel.local+3-key.pem ./start.sh
#    → https://192.168.1.41:8000

# 3. En .env, para que la cookie de sesión sea Secure:
#    PANEL_COOKIE_SECURE=true
```

**Servicio de usuario** (`./install.sh --service`): añade las dos variables al servicio con
`systemctl --user edit panel-maestro` →

```ini
[Service]
Environment=SSL_CERT=/home/TU_USUARIO/.config/panel-maestro/tls/panel.local+3.pem
Environment=SSL_KEY=/home/TU_USUARIO/.config/panel-maestro/tls/panel.local+3-key.pem
```

y `systemctl --user restart panel-maestro`.

**Móvil u otro equipo**: hay que instalar y confiar en la CA local (`rootCA.pem`, la ruta la da `mkcert -CAROOT`):
Android → Ajustes › Seguridad › Cifrado y credenciales › Instalar un certificado › Certificado de CA; iOS → AirDrop del
`rootCA.pem`, instalar el perfil y activarlo en Ajustes › General › Información › Certificados de confianza. Nunca
compartas `rootCA-key.pem`.

## Opción B: un proxy inverso delante (Caddy)

Si prefieres no tocar el arranque del panel (que seguiría en `http://127.0.0.1:8000`):

```caddyfile
# /etc/caddy/Caddyfile
panel.local {
    tls internal                       # CA propia de Caddy (instala su raíz en los dispositivos como arriba)
    reverse_proxy 127.0.0.1:8000
}
```

Con `HOST=127.0.0.1 ./start.sh` el panel solo escucha en local y todo el tráfico de la red pasa por Caddy.
Con nginx es equivalente (`proxy_pass http://127.0.0.1:8000;` y `ssl_certificate` de mkcert).

## Notas

- El panel de la extensión de Firefox (URL con `https://`) y los scripts del escritorio aceptan HTTPS; si usas una CA local en
  el escritorio, `curl` necesita `--cacert "$(mkcert -CAROOT)/rootCA.pem"`.
- La CSP del panel solo permite `'self'`: no hay que cambiar nada para HTTPS.
- Sin esto todo sigue funcionando por HTTP; es una mejora opcional.
