#!/usr/bin/env bash
# P-12: prueba el panel con los datos en NTFS sin tocar la partición real (docs/windows.md §8).
#
#   scripts/probar_ntfs.sh [--tam 512M] [--sin-tests] [--conservar] [--sin-imagen]
#
# Crea una imagen NTFS en una carpeta temporal, la monta con ntfs3 y las MISMAS opciones que /mnt/datos en el fstab
# (uid, gid, umask=022, windows_names) y comprueba:
#   1. los tests unitarios con todos sus datos dentro (los de permisos Unix se saltan: NTFS no los tiene);
#   2. un panel de verdad (uvicorn, puerto 8811) que arranca, guarda una nota y cierra limpio (cerrojo «cerrado»);
#   3. la imagen en solo lectura → el panel se niega (sale con 3, motivo «solo-lectura»);
#   4. un cierre sucio simulado de «Windows» (cerrojo abierto + WAL pendiente) → se niega y no escribe;
#      `seguir` lo confirma y el panel vuelve a arrancar (con su copia «cambio-sistema»).
# Necesita sudo (losetup, mkntfs, mount) y mkntfs: sudo pacman -S --needed ntfsprogs. Al salir lo desmonta y lo borra
# todo (con --conservar deja la carpeta y te dice dónde). --sin-imagen: los mismos pasos en una carpeta normal (solo
# lectura con chmod), sin sudo; sirve para probar el propio script, no NTFS.
set -euo pipefail

REPO=$(git -C "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" rev-parse --show-toplevel)
TAM=512M
TESTS=1
CONSERVAR=0
IMAGEN=1
PUERTO=8811
while (($#)); do
    case $1 in
        --tam) TAM=$2; shift ;;
        --sin-tests) TESTS=0 ;;
        --conservar) CONSERVAR=1 ;;
        --sin-imagen) IMAGEN=0 ;;
        -h|--help) sed -n '2,16p' "$0" | cut -c3-; exit 0 ;;
        *) echo "Opción desconocida: $1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

((IMAGEN)) || say "Sin imagen: carpeta normal (esto NO prueba NTFS)"
((!IMAGEN)) || command -v mkntfs >/dev/null || die "Falta mkntfs: sudo pacman -S --needed ntfsprogs"
PY=$REPO/venv/bin/python
[[ -x $PY ]] || die "No hay $PY: ./install.sh"
ss -ltn "sport = :$PUERTO" 2>/dev/null | grep -q LISTEN && die "El puerto $PUERTO está ocupado"

TRABAJO=$(mktemp -d "${TMPDIR:-/tmp}/panel-ntfs-XXXXXX")
IMG=$TRABAJO/datos.img
MNT=$TRABAJO/mnt
LOOP=""
SERVIDOR=""
limpiar() {
    [[ -n $SERVIDOR ]] && kill "$SERVIDOR" 2>/dev/null && wait "$SERVIDOR" 2>/dev/null || true
    [[ -d $MNT ]] && chmod -R u+w "$MNT" 2>/dev/null || true
    if mountpoint -q "$MNT" 2>/dev/null; then sudo umount "$MNT" || sudo umount -l "$MNT"; fi
    [[ -n $LOOP ]] && sudo losetup -d "$LOOP" 2>/dev/null || true
    if ((CONSERVAR)); then echo "Imagen y registros en $TRABAJO"; else rm -rf "$TRABAJO"; fi
}
trap limpiar EXIT

mkdir -p "$MNT"
if ((IMAGEN)); then
    say "Imagen NTFS de $TAM en $IMG"
    truncate -s "$TAM" "$IMG"
    LOOP=$(sudo losetup --find --show "$IMG")
    sudo mkntfs --quick --force --label datos-prueba "$LOOP" >/dev/null 2>&1  # sus avisos de arranque no aplican
    OPCIONES="uid=$(id -u),gid=$(id -g),umask=022,windows_names"
    sudo mount -t ntfs3 -o "$OPCIONES" "$LOOP" "$MNT"
    findmnt -no FSTYPE,OPTIONS "$MNT"
fi
solo_lectura() {
    if ((IMAGEN)); then sudo mount -o remount,ro "$MNT"; else chmod -R a-w "$MNT/panel-maestro"; fi
}
lectura_escritura() {
    if ((IMAGEN)); then sudo mount -o remount,rw "$MNT"; else chmod -R u+w "$MNT/panel-maestro"; fi
}

# Entorno limpio: nada del panel real llega a las pruebas
# (con exec: el pid que se guarda es el del propio Python, y SIGTERM le llega a él)
limpio() {
    exec env -i HOME="$HOME" PATH="$PATH" LANG="${LANG:-C.UTF-8}" USER="${USER:-}" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" "$@"
}

if ((TESTS)); then
    say "1. Tests unitarios con los datos en NTFS"
    mkdir -p "$MNT/tmp"
    # -rfEs: fallos, errores y saltados en el resumen; el registro entero queda en $TRABAJO/pytest.log
    (cd "$REPO" && limpio TMPDIR="$MNT/tmp" "$PY" -m pytest --ignore=tests/e2e -q -p no:cacheprovider \
        --basetemp="$MNT/pytest" -rfEs > "$TRABAJO/pytest.log" 2>&1) || {
        grep -E "^(FAILED|ERROR) " "$TRABAJO/pytest.log" || tail -n 40 "$TRABAJO/pytest.log"
        CONSERVAR=1
        die "Los tests fallan en NTFS (registro completo: $TRABAJO/pytest.log)"
    }
    grep -E "^SKIPPED|passed|failed" "$TRABAJO/pytest.log" | tail -n 12
    ok "tests en verde en NTFS"
fi

DATOS=$MNT/panel-maestro
mkdir -p "$DATOS" "$TRABAJO/copias" "$TRABAJO/logs"
: > "$TRABAJO/.env"
ENTORNO=(
    PANEL_ENV_FILE="$TRABAJO/.env"
    PANEL_DATA_DIR="$DATOS/data" PANEL_NOTES_DIR="$DATOS/data/notes" PANEL_BRAIN_DB="$DATOS/data/brain.db"
    PANEL_TRASH_DIR="$DATOS/data/trash" PANEL_COMIDAS_DB="$DATOS/comidas/comidas.db" PANEL_UPLOADS_DIR="$DATOS/uploads"
    PANEL_CALENDAR_STATE="$DATOS/estudio/calendar_sync_v2.json"
    PANEL_BACKUPS_DIR="$TRABAJO/copias" PANEL_LOGS_DIR="$TRABAJO/logs" PANEL_PROJECT_DIR="$TRABAJO"
    PANEL_DISABLE_BRIDGES=1 PANEL_DISABLE_SCHEDULER=1 PANEL_AUTH_DISABLED=1
)
panel() { (cd "$REPO" && limpio "${ENTORNO[@]}" "$@"); }
arrancar() {
    # Una sola subshell que hace exec: $! es el pid del propio Python (con «panel … &» habría dos y SIGTERM no le llega)
    { cd "$REPO" && limpio "${ENTORNO[@]}" "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PUERTO"; } \
        > "$TRABAJO/uvicorn-$1.log" 2>&1 &
    SERVIDOR=$!
    for _ in $(seq 60); do
        curl -fs "http://127.0.0.1:$PUERTO/healthz" >/dev/null 2>&1 && return 0
        kill -0 "$SERVIDOR" 2>/dev/null || { wait "$SERVIDOR" || true; SERVIDOR=""; return 1; }
        sleep 0.5
    done
    die "El panel no responde (mira $TRABAJO/uvicorn-$1.log)"
}
parar() { kill -TERM "$SERVIDOR"; wait "$SERVIDOR" || true; SERVIDOR=""; }
debe_negarse() {  # $1 = motivo esperado
    local salida=0
    panel timeout 60 "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PUERTO" > "$TRABAJO/uvicorn-$1.log" 2>&1 || salida=$?
    [[ $salida == 3 ]] || die "Debía negarse ($1) y salió con $salida (mira $TRABAJO/uvicorn-$1.log)"
    grep -q "\"motivo\": \"$1\"" "$TRABAJO/logs/arranque-denegado.json" || die "Motivo distinto de $1"
    ok "se niega: $(sed -n 's/.*"mensaje": "\(.\{0,110\}\).*/\1/p' "$TRABAJO/logs/arranque-denegado.json")…"
}

say "2. Panel de verdad sobre NTFS: arranca, guarda y cierra limpio"
arrancar normal || die "No arranca (mira $TRABAJO/uvicorn-normal.log)"
curl -fs -X POST "http://127.0.0.1:$PUERTO/api/notes/prueba-ntfs" -H 'Content-Type: application/json' \
    -d '{"title":"Prueba NTFS","category":"Pruebas","content":"ñandú áéíóú\nsegunda línea"}' >/dev/null || die "No guarda la nota"
grep -q "ñandú" "$DATOS/data/notes/prueba-ntfs.md" && ! grep -q $'\r' "$DATOS/data/notes/prueba-ntfs.md" \
    || die "La nota no se escribió bien"
curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PUERTO/api/notes/Prueba-NTFS" \
    -H 'Content-Type: application/json' -d '{"title":"x","category":"Pruebas","content":"pisaría la otra"}' \
    | grep -q 409 || die "Una nota que solo cambia en mayúsculas debía dar 409"
parar
grep -q '"cerrado": [0-9]' "$DATOS/data/panel-cerrojo.json" || die "El cerrojo no quedó cerrado"
[[ ! -s $DATOS/data/brain.db-wal ]] || die "Quedó WAL tras cerrar"
ok "nota con acentos y \\n, 409 por mayúsculas, cerrojo cerrado y WAL vacío"

say "3. Imagen en solo lectura"
solo_lectura
debe_negarse solo-lectura
lectura_escritura

say "4. Cierre sucio simulado de Windows (cerrojo abierto y WAL pendiente)"
panel "$PY" - <<'EOF'
import json, os, shutil, sqlite3
from pathlib import Path
db = Path(os.environ["PANEL_BRAIN_DB"])
trabajo = db.with_name("trabajo.db")
shutil.copyfile(db, trabajo)
conn = sqlite3.connect(trabajo)
conn.execute("PRAGMA wal_autocheckpoint=0")
conn.execute("CREATE TABLE IF NOT EXISTS prueba_ntfs (v TEXT)")
conn.execute("INSERT INTO prueba_ntfs VALUES ('escrito en Windows')")
conn.commit()
shutil.copyfile(trabajo, db)
shutil.copyfile(f"{trabajo}-wal", f"{db}-wal")
conn.close()
for p in (trabajo, Path(f"{trabajo}-wal"), Path(f"{trabajo}-shm")):
    p.unlink(missing_ok=True)
cerrojo = db.with_name("panel-cerrojo.json")
c = json.loads(cerrojo.read_text(encoding="utf-8"))
cerrojo.write_text(json.dumps({**c, "sistema": "windows", "equipo": "DESKTOP-PRUEBA", "cerrado": None}), encoding="utf-8")
EOF
antes=$(cd "$DATOS" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
debe_negarse cierre-sucio
despues=$(cd "$DATOS" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
[[ $antes == "$despues" ]] || die "Escribió en la carpeta de datos con un cierre sucio"
ok "no escribió nada en la carpeta de datos"
panel "$PY" -m scripts.datos_compartidos --entorno ninguno seguir || die "seguir falla"
arrancar despues-de-seguir || die "No arranca tras seguir (mira $TRABAJO/uvicorn-despues-de-seguir.log)"
parar
ls "$TRABAJO/copias"/backup_cambio-sistema_*.zip >/dev/null 2>&1 || die "No hizo la copia de cambio de sistema"
panel "$PY" -m scripts.datos_compartidos --entorno ninguno estado
ok "seguir, arranque con copia «cambio-sistema» y cierre limpio"

say "Todo bien: el panel trabaja en NTFS y se niega cuando debe"
