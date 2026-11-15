#!/usr/bin/env bash
# Despliegue con vuelta atrás (C-4): el panel de verdad deja de servirse desde la carpeta donde se programa.
#
#   scripts/desplegar.sh [REF]       despliega REF (etiqueta, rama o commit; por defecto HEAD)
#   scripts/desplegar.sh --estado    qué versión está en marcha, la anterior y las que se guardan
#   scripts/desplegar.sh --volver    vuelve a la versión anterior (no toca las BDs)
#   scripts/desplegar.sh --unidad-propuesta   la unidad de systemd que hace falta, y su diferencia con la instalada
# Opciones: --raiz DIR (PANEL_DEPLOY_ROOT; por defecto ~/.local/share/panel-maestro) · --unidad NOMBRE (panel-maestro)
#           --url URL de /healthz · --espera S (90) · --sin-tests · --guardar N versiones (3)
#
# Pasos: tests de esa versión con sus dependencias → para el servicio → copia de las dos BDs y del estado del
# calendario (API de backup) → cambia el enlace «actual» → arranca → espera a /healthz. Si no responde: para,
# restaura BDs y estado, vuelve al enlace anterior y arranca. Detalle y decisiones: docs/despliegue.md
set -euo pipefail

REPO=$(git -C "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" rev-parse --show-toplevel)
RAIZ=${PANEL_DEPLOY_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/panel-maestro}
UNIDAD=panel-maestro
URL=""
ESPERA=90
TESTS=1
GUARDAR=3
accion=desplegar
ref=HEAD

while (($#)); do
    case $1 in
        --raiz) RAIZ=$2; shift ;;
        --unidad) UNIDAD=$2; shift ;;
        --url) URL=$2; shift ;;
        --espera) ESPERA=$2; shift ;;
        --guardar) GUARDAR=$2; shift ;;
        --sin-tests) TESTS=0 ;;
        --estado) accion=estado ;;
        --volver) accion=volver ;;
        --unidad-propuesta) accion=unidad ;;
        -h|--help) sed -n '2,13p' "$0" | cut -c3-; exit 0 ;;
        -*) echo "Opción desconocida: $1 (prueba --help)" >&2; exit 2 ;;
        *) ref=$1 ;;
    esac
    shift
done

RAIZ=$(realpath -m "$RAIZ")
ENTORNO=$RAIZ/panel.env
ACTUAL=$RAIZ/actual
ANTERIOR=$RAIZ/anterior
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
sc() { systemctl --user "$@"; }

# ── Entorno de datos: los datos se quedan donde están; la versión desplegada solo trae el código ──────────────
# Se escribe una vez (lo que ya esté en el entorno manda: así se prueba contra una copia). Rutas explícitas, sin
# derivar nada: la del calendario cambiaría de sitio en cuanto PANEL_DATA_DIR deja de ser <código>/data.
contenido_entorno() {
    local data=${PANEL_DATA_DIR:-$REPO/data}
    cat <<EOF
# Datos del panel desplegado (scripts/desplegar.sh). La unidad de systemd lo carga con EnvironmentFile=.
# El código está en $RAIZ/actual; los datos, donde siempre. No pongas aquí secretos: van en PANEL_ENV_FILE.
PANEL_ENV_FILE=${PANEL_ENV_FILE:-$REPO/.env}
PANEL_DATA_DIR=$data
PANEL_NOTES_DIR=${PANEL_NOTES_DIR:-$data/notes}
PANEL_BRAIN_DB=${PANEL_BRAIN_DB:-$data/brain.db}
PANEL_TRASH_DIR=${PANEL_TRASH_DIR:-$data/trash}
PANEL_COMIDAS_DB=${PANEL_COMIDAS_DB:-$REPO/comidas/data/comidas.db}
PANEL_UPLOADS_DIR=${PANEL_UPLOADS_DIR:-$REPO/static/uploads}
PANEL_BACKUPS_DIR=${PANEL_BACKUPS_DIR:-$REPO/backups}
PANEL_LOGS_DIR=${PANEL_LOGS_DIR:-$REPO/logs}
PANEL_CALENDAR_STATE=${PANEL_CALENDAR_STATE:-$REPO/estudio/calendar_sync_v2.json}
# El botón «Publicar» trabaja sobre el repo de desarrollo (main y la rama publico), no sobre la versión desplegada
PANEL_PROJECT_DIR=${PANEL_PROJECT_DIR:-$REPO}
EOF
    # Extras para una instancia de prueba (puerto, sin puentes…): solo si vienen en el entorno
    for v in PANEL_HOST PANEL_PORT PANEL_DISABLE_BRIDGES PANEL_DISABLE_SCHEDULER PANEL_AUTH_DISABLED; do
        [[ -n ${!v:-} ]] && echo "$v=${!v}"
    done
    return 0
}

crear_entorno() {
    [[ -f $ENTORNO ]] && return 0
    mkdir -p "$RAIZ"
    (umask 077 && contenido_entorno > "$ENTORNO")
    echo "Creado $ENTORNO (revísalo: es el que dice dónde están los datos)." >&2
}

# Valor de una clave de un archivo KEY=valor (la última si se repite), como start.sh
leer() {
    [[ -r $2 ]] || return 0
    local v
    v=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$2" | tail -n 1)
    v=${v%\"}; v=${v#\"}; v=${v%\'}; v=${v#\'}
    printf '%s' "${v/#\~/$HOME}"
}
dato() { leer "$1" "$ENTORNO"; }

url_salud() {
    [[ -n $URL ]] && { echo "$URL"; return; }
    local envf port cert
    envf=$(dato PANEL_ENV_FILE)
    port=$(dato PANEL_PORT); port=${port:-$(leer PANEL_PORT "$envf")}
    cert=$(dato PANEL_SSL_CERT); cert=${cert:-$(leer PANEL_SSL_CERT "$envf")}
    echo "$([[ -n $cert ]] && echo https || echo http)://127.0.0.1:${port:-8000}/healthz"
}

espera_salud() {
    local url fin
    url=$(url_salud)
    fin=$((SECONDS + ESPERA))
    while ((SECONDS < fin)); do
        if curl -fsSk --max-time 3 "$url" 2>/dev/null | grep -q '"ok"'; then
            echo "  $url responde ok"
            return 0
        fi
        sleep 1
    done
    echo "  $url no responde tras ${ESPERA} s"
    return 1
}

unidad_propuesta() {
    # La misma plantilla que ./install.sh --service, con el enlace «actual» en vez de la carpeta del código
    sed "/^[^#]/s#@PANEL_DIR@#$ACTUAL#g" "$REPO/scripts/systemd/panel-maestro.service" | awk -v env="$ENTORNO" '
        /^WorkingDirectory=/ { print; print "# Dónde están los datos: el código desplegado no trae ninguno (scripts/desplegar.sh, docs/despliegue.md)"; print "EnvironmentFile=" env; next }
        { print }'
}

# La unidad tiene que arrancar el enlace «actual» y cargar panel.env: si no, la versión nueva usaría <código>/data
# (vacío) y parecería que se han perdido los datos.
comprobar_unidad() {
    local exec envs
    sc cat "$UNIDAD" >/dev/null 2>&1 || die "No existe la unidad $UNIDAD. Mira --unidad-propuesta y docs/despliegue.md"
    exec=$(sc show -p ExecStart --value "$UNIDAD")
    envs=$(sc show -p EnvironmentFiles --value "$UNIDAD")
    [[ $exec == *"$ACTUAL/start.sh"* ]] || die "La unidad $UNIDAD no arranca $ACTUAL/start.sh. Aplica antes: scripts/desplegar.sh --unidad-propuesta"
    [[ $envs == *"$ENTORNO"* ]] || die "La unidad $UNIDAD no carga $ENTORNO. Aplica antes: scripts/desplegar.sh --unidad-propuesta"
}

estado() {
    echo "Raíz:     $RAIZ"
    local a p
    a=$(readlink "$ACTUAL" 2>/dev/null || true)
    p=$(readlink "$ANTERIOR" 2>/dev/null || true)
    echo "Actual:   $([[ -n $a ]] && basename "$a" || echo —)"
    echo "Anterior: $([[ -n $p ]] && basename "$p" || echo —)"
    echo "Versiones guardadas:"
    ls -1t "$RAIZ/releases" 2>/dev/null | sed 's/^/  /' || true
    [[ -f $RAIZ/historial.log ]] && { echo "Últimos despliegues:"; tail -n 5 "$RAIZ/historial.log" | sed 's/^/  /'; }
    echo "Servicio $UNIDAD: $(sc is-active "$UNIDAD" 2>/dev/null || true)"
}

# Cambio atómico de un enlace (rename sobre el anterior)
enlazar() { ln -sfn "$1" "$2.nuevo" && mv -Tf "$2.nuevo" "$2"; }

# ── venv por requirements.lock: compartido entre las versiones con las mismas dependencias ────────────────────
preparar_venv() {
    local rel=$1 clave dir
    clave=$(cat "$rel/requirements.lock" "$rel/requirements-dev.txt" | sha256sum | cut -c1-12)
    dir=$RAIZ/venvs/$clave
    # .listo se escribe al final: un venv a medias (sin red, Ctrl+C) se rehace entero la próxima vez
    if [[ ! -f $dir/.listo ]]; then
        say "Entorno de Python nuevo ($clave): requirements.lock + requirements-dev.txt"
        rm -rf "$dir"
        mkdir -p "$RAIZ/venvs"
        python3 -m venv "$dir"
        "$dir/bin/python" -m pip install --quiet --disable-pip-version-check \
            -r "$rel/requirements.lock" -r "$rel/requirements-dev.txt"
        touch "$dir/.listo"
    fi
    enlazar "$dir" "$rel/venv"
}

limpiar() {
    local keep=() rel
    keep+=("$(readlink -f "$ACTUAL" 2>/dev/null || true)" "$(readlink -f "$ANTERIOR" 2>/dev/null || true)")
    mapfile -t todas < <(ls -1dt "$RAIZ"/releases/*/ 2>/dev/null | sed 's#/$##')
    local n=0
    for rel in "${todas[@]}"; do
        n=$((n + 1))
        if ((n <= GUARDAR)) || [[ " ${keep[*]} " == *" $rel "* ]]; then continue; fi
        git -C "$REPO" worktree remove --force "$rel" && echo "  fuera $(basename "$rel")"
    done
    git -C "$REPO" worktree prune
    # venvs que ya no usa ninguna versión guardada
    local usados
    usados=$(for rel in "$RAIZ"/releases/*/; do readlink -f "$rel/venv" 2>/dev/null; done)
    for v in "$RAIZ"/venvs/*/; do
        v=${v%/}
        grep -qxF "$v" <<<"$usados" || { rm -rf "$v"; echo "  fuera el entorno $(basename "$v")"; }
    done
    # copias previas de despliegues: las 5 últimas
    ls -1dt "$(dato PANEL_BACKUPS_DIR)"/pre-despliegue/*/ 2>/dev/null | tail -n +6 | xargs -r rm -rf
}

case $accion in
    unidad)  # solo enseña: no crea ni cambia nada
        if [[ ! -f $ENTORNO ]]; then
            echo "# $ENTORNO no existe; el primer despliegue lo creará así:"
            contenido_entorno | sed 's/^/#   /'
            echo
        fi
        nueva=$(mktemp)
        unidad_propuesta > "$nueva"
        instalada=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIDAD.service
        echo "# Unidad propuesta para $instalada:"
        cat "$nueva"
        if [[ -f $instalada ]]; then
            echo; echo "# Diferencia con la instalada:"
            diff -u "$instalada" "$nueva" || true
        fi
        rm -f "$nueva"
        exit 0 ;;
    estado) estado; exit 0 ;;
esac

mkdir -p "$RAIZ/releases"
exec 9>"$RAIZ/.cerrojo"
flock -n 9 || die "Ya hay un despliegue en marcha"
crear_entorno
comprobar_unidad

BRAIN=$(dato PANEL_BRAIN_DB)
COMIDAS=$(dato PANEL_COMIDAS_DB)
CALENDARIO=$(dato PANEL_CALENDAR_STATE)
COPIAS=$(dato PANEL_BACKUPS_DIR)/pre-despliegue
[[ -f $BRAIN && -f $COMIDAS ]] || die "No encuentro las BDs de $ENTORNO ($BRAIN, $COMIDAS): revisa ese archivo"

if [[ $accion == volver ]]; then
    [[ -L $ANTERIOR ]] || die "No hay versión anterior"
    previa=$(readlink "$ANTERIOR")
    actual=$(readlink "$ACTUAL" || true)
    say "Volviendo a $(basename "$previa")"
    enlazar "$previa" "$ACTUAL"
    [[ -n $actual ]] && enlazar "$actual" "$ANTERIOR"
    sc restart "$UNIDAD"
    espera_salud || die "La versión anterior tampoco responde: mira journalctl --user -u $UNIDAD"
    echo "$(date '+%F %T') vuelta a $(basename "$previa")" >> "$RAIZ/historial.log"
    exit 0
fi

sha=$(git -C "$REPO" rev-parse --verify "$ref^{commit}") || die "No existe $ref"
# Una carpeta por commit: si ya se preparó (un intento anterior), se reutiliza
existente=$(ls -1d "$RAIZ"/releases/*-"${sha:0:12}" 2>/dev/null | head -n 1 || true)
if [[ -n $existente ]]; then
    etiqueta=$(basename "$existente")
else
    etiqueta=$(git -C "$REPO" describe --tags --exact-match "$sha" 2>/dev/null | tr '/' '-' || true)
    etiqueta=${etiqueta:-$(date +%Y%m%d-%H%M%S)}-${sha:0:12}
fi
REL=$RAIZ/releases/$etiqueta
[[ -n $(git -C "$REPO" status --porcelain --untracked-files=no) && $ref == HEAD ]] \
    && echo "Aviso: hay cambios sin commit en $REPO; se despliega solo lo que está en el commit ${sha:0:7}."

say "Versión $etiqueta"
[[ -e $REL ]] || git -C "$REPO" worktree add --detach --quiet "$REL" "$sha"
preparar_venv "$REL"

if ((TESTS)); then
    say "Tests de esta versión (unitarios, con sus dependencias)"
    # Entorno limpio: ninguna PANEL_* del panel real llega a los tests (conftest no fija todas)
    (cd "$REL" && env -i HOME="$HOME" PATH="$PATH" LANG="${LANG:-C.UTF-8}" USER="${USER:-}" \
        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" venv/bin/python -m pytest \
        --ignore=tests/e2e -x -q -p no:cacheprovider) || die "Los tests fallan: no se despliega (el servicio sigue como estaba)"
fi

previa=$(readlink "$ACTUAL" 2>/dev/null || true)
[[ $previa == "$REL" ]] && die "$etiqueta ya es la versión en marcha"
copia=$COPIAS/$etiqueta-$(date +%H%M%S)

say "Parando $UNIDAD y copiando BDs y estado del calendario"
sc stop "$UNIDAD"
if ! python3 -I "$REPO/scripts/despliegue_bd.py" copiar "$copia" "$BRAIN" "$COMIDAS" "$CALENDARIO"; then
    sc start "$UNIDAD"
    die "No se ha podido copiar: no se despliega (el servicio vuelve a arrancar como estaba)"
fi

say "Cambiando a $etiqueta y arrancando"
enlazar "$REL" "$ACTUAL"
sc start "$UNIDAD" || true
if espera_salud; then
    [[ -n $previa ]] && enlazar "$previa" "$ANTERIOR"
    echo "$(date '+%F %T') $etiqueta ok (copia previa: $copia)" >> "$RAIZ/historial.log"
    say "Desplegado $etiqueta"
    limpiar
    exit 0
fi

say "La versión nueva no arranca: vuelta atrás"
sc status "$UNIDAD" --no-pager -n 20 2>/dev/null | tail -n 20 || true
sc stop "$UNIDAD" || true
python3 -I "$REPO/scripts/despliegue_bd.py" restaurar "$copia" \
    || die "No se han podido restaurar las BDs desde $copia: el servicio queda PARADO. Mira docs/despliegue.md"
if [[ -z $previa ]]; then
    rm -f "$ACTUAL"
    echo "$(date '+%F %T') $etiqueta FALLA; sin versión anterior, BDs restauradas" >> "$RAIZ/historial.log"
    die "No había versión anterior: BDs restauradas y servicio parado. Arréglalo y vuelve a desplegar."
fi
enlazar "$previa" "$ACTUAL"
sc reset-failed "$UNIDAD" 2>/dev/null || true
sc start "$UNIDAD"
espera_salud || die "Tampoco responde la anterior ($(basename "$previa")): mira journalctl --user -u $UNIDAD"
echo "$(date '+%F %T') $etiqueta FALLA; vuelta a $(basename "$previa"), BDs restauradas" >> "$RAIZ/historial.log"
die "$etiqueta no arrancaba: sigue $(basename "$previa") con las BDs como antes (copia en $copia)"
