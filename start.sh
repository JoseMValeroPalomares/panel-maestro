#!/usr/bin/env bash
# Arranca el panel. Por defecto escucha en toda la red local, para usarlo también desde el móvil, y pide contraseña.
#   PORT=9000 ./start.sh         otro puerto
#   HOST=127.0.0.1 ./start.sh    solo desde este equipo
#   SSL_CERT=… SSL_KEY=… ./start.sh   sirve por HTTPS (ver docs/HTTPS.md): con https el portapapeles y el resto de APIs
#                                     seguras del navegador funcionan también desde el móvil o el portátil
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
[[ -x venv/bin/uvicorn ]] || { echo "Primero instala: ./install.sh" >&2; exit 1; }
ssl=()
if [[ -n "${SSL_CERT:-}" || -n "${SSL_KEY:-}" ]]; then
  [[ -r "${SSL_CERT:-}" && -r "${SSL_KEY:-}" ]] || { echo "SSL_CERT y SSL_KEY deben apuntar a archivos legibles (docs/HTTPS.md)" >&2; exit 1; }
  ssl=(--ssl-certfile "$SSL_CERT" --ssl-keyfile "$SSL_KEY")
fi
exec venv/bin/uvicorn main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" "${ssl[@]}"
