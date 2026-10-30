#!/usr/bin/env bash
# Arranca el panel. Por defecto escucha en toda la red local, para usarlo también desde el móvil, y pide contraseña.
#   PORT=9000 ./start.sh         otro puerto
#   HOST=127.0.0.1 ./start.sh    solo desde este equipo
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
[[ -x venv/bin/uvicorn ]] || { echo "Primero instala: ./install.sh" >&2; exit 1; }
exec venv/bin/uvicorn main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
