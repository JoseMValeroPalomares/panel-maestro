#!/usr/bin/env bash
# Instala el panel: entorno de Python, dependencias, .env y contraseña. Se puede repetir sin miedo.
#   ./install.sh             instala
#   ./install.sh --service   además lo deja arrancando solo con el equipo (servicio de usuario de systemd)
set -euo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

MIN_PYTHON=3.12
PYTHON=${PYTHON:-python3}
service=0
for arg in "$@"; do
    case $arg in
        --service) service=1 ;;
        -h|--help) sed -n 2,4p "$0" | cut -c3-; exit 0 ;;
        *) echo "Opción desconocida: $arg (prueba --help)" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$1"; }

if ! command -v "$PYTHON" >/dev/null; then
    echo "Falta Python $MIN_PYTHON o superior. Instálalo con el gestor de paquetes de tu sistema." >&2
    exit 1
fi
if ! "$PYTHON" -c "import sys; sys.exit(sys.version_info < tuple(map(int, '$MIN_PYTHON'.split('.'))))"; then
    echo "Hace falta Python $MIN_PYTHON o superior y tienes $("$PYTHON" -V 2>&1)." >&2
    exit 1
fi

say "Entorno de Python"
if [[ ! -x venv/bin/python ]]; then
    "$PYTHON" -m venv venv || {
        echo "No he podido crear el entorno. En Debian y Ubuntu falta el paquete python3-venv." >&2
        exit 1
    }
fi
venv/bin/python -m pip install --quiet --upgrade pip
venv/bin/python -m pip install --quiet -r requirements.txt

say "Configuración"
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
fi
if grep -q '^PANEL_PASSWORD_HASH=.' .env; then
    echo "La contraseña ya estaba puesta (para cambiarla: venv/bin/python -m scripts.set_password)."
elif [[ -t 0 ]]; then
    venv/bin/python -m scripts.set_password
else
    venv/bin/python -m scripts.set_password --generate
fi

if ((service)); then
    say "Servicio de usuario"
    unit=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/panel-maestro.service
    mkdir -p "$(dirname "$unit")"
    cat > "$unit" <<UNIT
[Unit]
Description=Panel Maestro
After=network-online.target

[Service]
WorkingDirectory=$PWD
ExecStart=$PWD/start.sh
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now panel-maestro
    echo "Arrancado. Para que siga en marcha sin haber iniciado sesión: loginctl enable-linger $USER"
fi

say "Listo"
((service)) || echo "Arráncalo con ./start.sh"
echo "Ábrelo en http://localhost:8000"
