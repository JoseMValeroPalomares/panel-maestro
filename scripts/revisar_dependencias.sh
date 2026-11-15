#!/usr/bin/env bash
# Revisión mensual de dependencias (C-3). Solo informa: no instala ni actualiza nada.
#   scripts/revisar_dependencias.sh          vulnerabilidades (pip-audit, npm audit) y versiones nuevas (pip, npm)
#   scripts/revisar_dependencias.sh --lock   además rehace requirements.lock desde requirements.txt (venv temporal,
#                                            mismas versiones que el venv/ actual) y enseña la diferencia
# Sale con 1 si hay vulnerabilidades conocidas, para poder usarlo en un temporizador o en la integración continua.
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." || exit 2
PY=venv/bin/python
[[ -x $PY ]] || { echo "Falta venv/: ejecuta ./install.sh" >&2; exit 2; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
vulnerable=0

if [[ ${1:-} == --lock ]]; then
    say "Rehaciendo requirements.lock"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    "$PY" -m pip freeze --exclude-editable > "$tmp/actual.txt"
    "$PY" -m venv "$tmp/venv"
    # -c: lo que ya está en venv/ se queda en su versión; lo nuevo de requirements.txt entra en la última compatible
    "$tmp/venv/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements.txt -c "$tmp/actual.txt"
    { sed -n '1,3p' requirements.lock; "$tmp/venv/bin/python" -m pip freeze; } > "$tmp/lock"
    diff -u requirements.lock "$tmp/lock" && echo "Sin cambios." || cp "$tmp/lock" requirements.lock
fi

say "Vulnerabilidades en Python (pip-audit sobre requirements.lock)"
if "$PY" -m pip_audit --version >/dev/null 2>&1; then
    "$PY" -m pip_audit --progress-spinner off -r requirements.lock || vulnerable=1
else
    echo "Falta pip-audit: venv/bin/python -m pip install -r requirements-dev.txt"
fi

say "Vulnerabilidades en npm (lo de static/vendor sale de aquí y llega al navegador)"
if command -v npm >/dev/null; then
    npm audit --omit=optional || vulnerable=1
else
    echo "npm no está instalado."
fi

say "Versiones nuevas de Python (venv/)"
"$PY" -m pip list --outdated --disable-pip-version-check 2>/dev/null || true

say "Versiones nuevas de npm"
command -v npm >/dev/null && { npm outdated || true; }

echo
if ((vulnerable)); then
    echo "Hay vulnerabilidades conocidas: mira arriba qué paquete y qué versión las arregla."
else
    echo "Sin vulnerabilidades conocidas."
fi
exit "$vulnerable"
