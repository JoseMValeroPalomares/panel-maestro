#!/usr/bin/env bash
# Arranca el panel. Por defecto escucha en toda la red local, para usarlo también desde el móvil, y pide contraseña.
# Se configura en .env (o con variables de entorno, que mandan sobre el .env):
#   PANEL_HOST=127.0.0.1     solo desde este equipo; con Tailscale (`tailscale serve`) es lo recomendado (docs/HTTPS.md)
#   PANEL_PORT=9000          otro puerto (por defecto 8000)
#   PANEL_SSL_CERT=… PANEL_SSL_KEY=…   sirve por HTTPS con un certificado propio (mkcert, docs/HTTPS.md)
# También valen los nombres cortos de siempre: HOST=… PORT=… SSL_CERT=… SSL_KEY=… ./start.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
[[ -x venv/bin/uvicorn ]] || { echo "Primero instala: ./install.sh" >&2; exit 1; }

envfile=${PANEL_ENV_FILE:-.env}
# Valor de una clave del .env (la última si se repite), sin comillas y con ~ expandido
leer() {
  [[ -r $envfile ]] || return 0
  local v
  v=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$envfile" | tail -n 1)
  v=${v%\"}; v=${v#\"}; v=${v%\'}; v=${v#\'}
  printf '%s' "${v/#\~/$HOME}"
}
host=${HOST:-${PANEL_HOST:-$(leer PANEL_HOST)}}
port=${PORT:-${PANEL_PORT:-$(leer PANEL_PORT)}}
cert=${SSL_CERT:-${PANEL_SSL_CERT:-$(leer PANEL_SSL_CERT)}}
key=${SSL_KEY:-${PANEL_SSL_KEY:-$(leer PANEL_SSL_KEY)}}

ssl=()
if [[ -n $cert || -n $key ]]; then
  [[ -r $cert && -r $key ]] || { echo "PANEL_SSL_CERT y PANEL_SSL_KEY deben apuntar a archivos legibles (docs/HTTPS.md)" >&2; exit 1; }
  ssl=(--ssl-certfile "$cert" --ssl-keyfile "$key")
fi
# --proxy-headers: detrás de `tailscale serve` (que habla con el panel desde 127.0.0.1) el panel sabe que la petición
# llegó por HTTPS (X-Forwarded-Proto) y pone la cookie Secure y HSTS. Solo se cree a 127.0.0.1, nunca a la red.
exec venv/bin/uvicorn main:app --host "${host:-0.0.0.0}" --port "${port:-8000}" \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 "${ssl[@]}"
