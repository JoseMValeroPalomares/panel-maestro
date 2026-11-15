#!/usr/bin/env bash
# Instala en ESTE equipo (el portátil) el abridor de panelmaestro:// (ver abrir.py).
# Lo que toca, siempre con copia previa *.bak-panel-<fecha> si ya existía:
#   ~/.local/share/applications/panelmaestro-abrir.desktop   (el manejador del esquema)
#   ~/.config/mimeapps.list                                  (xdg-mime default … x-scheme-handler/panelmaestro)
#   ~/.config/panel-maestro/abrir.conf                       (raíces permitidas, 600; solo si no existe)
#
#   instalar.sh                 instala
#   instalar.sh --desinstalar   quita el .desktop y la asociación (abrir.conf se queda)
# No lo ejecutes en el sobremesa: allí no están tus carpetas de la universidad.
set -euo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
CONFD="${XDG_CONFIG_HOME:-$HOME/.config}"
DESKTOP="$APPS/panelmaestro-abrir.desktop"
MIMEAPPS="$CONFD/mimeapps.list"
CONF="$CONFD/panel-maestro/abrir.conf"
STAMP="$(date +%Y%m%d-%H%M%S)"

backup() { [ -e "$1" ] && cp -p -- "$1" "$1.bak-panel-$STAMP" && echo "  copia: $1.bak-panel-$STAMP"; return 0; }

if [ "${1:-}" = "--desinstalar" ]; then
  backup "$DESKTOP"; backup "$MIMEAPPS"
  rm -f -- "$DESKTOP"
  [ -f "$MIMEAPPS" ] && sed -i '/^x-scheme-handler\/panelmaestro=/d' "$MIMEAPPS"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
  echo "Abridor desinstalado ($CONF se conserva)."
  exit 0
fi

mkdir -p "$APPS" "$(dirname "$CONF")"
chmod +x "$DIR/abrir.py"
backup "$DESKTOP"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Panel · abrir carpeta
Comment=Abre carpetas y archivos de la universidad y de los proyectos desde el Panel (panelmaestro://)
Exec=$DIR/abrir.py %u
Icon=folder-open
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/panelmaestro;
EOF
backup "$MIMEAPPS"
xdg-mime default panelmaestro-abrir.desktop x-scheme-handler/panelmaestro
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

if [ ! -f "$CONF" ]; then
  # Las raíces del panel como punto de partida (ajústalas a mano si en este equipo están en otro sitio)
  uni=""; proy="$HOME/Projects"
  if aj="$(python3 "$DIR/../panel_client.py" get /api/contextos/ajustes 2>/dev/null)"; then
    uni="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("uni_raiz",""))' "$aj" 2>/dev/null || true)"
    p="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("proyectos_raiz",""))' "$aj" 2>/dev/null || true)"
    [ -n "$p" ] && proy="$p"
  fi
  umask 077
  cat > "$CONF" <<EOF
# Carpetas que el abridor puede abrir (panelmaestro://). Nada fuera de ellas se abre nunca.
[raices]
universidad = $uni
proyectos = $proy
EOF
  chmod 600 "$CONF"
  echo "Creado $CONF (600). Revisa las raíces."
else
  chmod 600 "$CONF"
  echo "Se conserva $CONF."
fi
echo "Asociado: $(xdg-mime query default x-scheme-handler/panelmaestro)"
echo "Prueba: $DIR/abrir.py --dry-run panelmaestro://abrir/asignatura/1"
