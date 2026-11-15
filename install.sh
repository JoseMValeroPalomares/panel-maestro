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
# C-3: requirements.lock fija también las transitivas a lo probado. Si en este equipo no se puede (otra versión de
# Python sin alguna de esas ruedas), se instalan las directas de requirements.txt y se avisa.
if ! venv/bin/python -m pip install --quiet -r requirements.lock; then
    echo "No se ha podido instalar requirements.lock con $(venv/bin/python -V); instalo requirements.txt." >&2
    venv/bin/python -m pip install --quiet -r requirements.txt
fi

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

say "Permisos de los datos"
# S-6: solo este usuario lee BDs, notas, copias, logs y subidas (lo nuevo ya nace así: main.py pone umask 077).
# Quita los permisos de grupo y otros a lo que ya existía; los permisos del dueño no cambian.
for d in data comidas/data backups logs static/uploads; do
    if [[ -e $d ]]; then chmod -R go-rwx "$d"; fi
done
for f in .env .env.bak*; do
    if [[ -f $f ]]; then chmod 600 "$f"; fi
done

if ((service)); then
    say "Servicio de usuario"
    # C-4: con despliegues, la unidad arranca la versión desplegada; esta la devolvería a la carpeta de desarrollo
    if [[ -e ${PANEL_DEPLOY_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/panel-maestro}/actual ]]; then
        echo "El panel se despliega con scripts/desplegar.sh: la unidad es la de --unidad-propuesta (docs/despliegue.md)." >&2
        exit 1
    fi
    unit=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/panel-maestro.service
    mkdir -p "$(dirname "$unit")"
    # Una sola plantilla, la del repo (S-5): protecciones probadas, ver docs/servicio.md
    if [[ -f $unit ]] && ! cmp -s <(sed "s#@PANEL_DIR@#$PWD#g" scripts/systemd/panel-maestro.service) "$unit"; then
        cp "$unit" "$unit.bak-panel-$(date +%Y%m%d-%H%M%S)"
        echo "La unidad anterior queda en $unit.bak-panel-*"
    fi
    sed "s#@PANEL_DIR@#$PWD#g" scripts/systemd/panel-maestro.service > "$unit"
    systemctl --user daemon-reload
    systemctl --user enable panel-maestro
    systemctl --user restart panel-maestro
    echo "Arrancado. Para que siga en marcha sin haber iniciado sesión: loginctl enable-linger $USER"
fi

say "Listo"
((service)) || echo "Arráncalo con ./start.sh"
echo "Ábrelo en http://localhost:8000 (HTTPS y acceso desde fuera de casa: docs/HTTPS.md y docs/fuera-de-casa.md)"
