#!/usr/bin/env bash
# Captura rápida del Panel desde el escritorio (Hyprland: Super+K).
#
# Menú rofi de una línea con el mismo estilo que los del sistema (rofi/panel-captura.rasi, copia de
# ~/.config/rofi/config-search.rasi). Se escribe y se pulsa Intro:
#   sin prefijo = Inbox · t: tarea · i: idea · r: rutina · e: evento en lenguaje natural · g: gasto («g: 4,50 café»)
#   o, sin escribir el prefijo, Alt+1 tarea · Alt+2 idea · Alt+3 rutina · Alt+4 evento.
# Tareas e ideas guardan la fecha si la llevan clara («t: llamar a Juan el viernes»). Todo lo que
# lleva algo que interpretar (un evento, una rutina o una tarea con fecha) muestra antes una vista
# previa: Intro guarda, «Corregir el texto» vuelve al primer paso, Esc cancela. Un evento cuya fecha
# no se entiende va al Inbox marcado «Revisar fecha». Sin conexión, el texto queda en una cola local y
# se reenvía en la siguiente captura o cuando la Waybar vea el panel. Token en
# ~/.config/panel-maestro/token (600), nunca en el repositorio.
#
#   quick_capture.sh            abre el menú
#   quick_capture.sh "texto"    sin menú (para atajos y pruebas; solo los eventos piden confirmación)
#   quick_capture.sh --evento   menú con «e: » ya escrito (clic derecho en la Waybar)
# PANEL_ROFI y PANEL_NOTIFY permiten sustituir rofi y notify-send en las pruebas.
set -u
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CLIENT="$DIR/panel_client.py"
ROFI="${PANEL_ROFI:-rofi}"
NOTIFY="${PANEL_NOTIFY:-notify-send}"
PY="${PANEL_PYTHON:-python3}"

notify() {  # urgencia, título, texto
  "$NOTIFY" -a "Panel" -u "$1" -i "${PANEL_ICON:-appointment-new}" "$2" "$3" >/dev/null 2>&1 || true
}
field() { "$PY" -c 'import json,sys; d=json.load(sys.stdin); v=d; [v:=v.get(k) if isinstance(v, dict) else None for k in sys.argv[1].split(".")]; print("" if v is None else v)' "$1"; }
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

# Un solo menú a la vez (como los demás scripts de rofi del sistema)
if [ -z "${PANEL_ROFI:-}" ] && pgrep -x rofi >/dev/null; then pkill -x rofi; fi

# Colores de los tipos (Catppuccin Mocha, los mismos que la agenda de la Waybar)
HELP="<span color='#94e2d5'><b>t:</b> tarea</span>    <span color='#fab387'><b>i:</b> idea</span>    <span color='#cba6f7'><b>r:</b> rutina</span>    <span color='#89b4fa'><b>e:</b> evento</span>    <span color='#89dceb'><b>g:</b> gasto</span>    sin prefijo: al Inbox
<span size='small'><b>Intro</b> guarda · <b>Alt+1</b> tarea · <b>Alt+2</b> idea · <b>Alt+3</b> rutina · <b>Alt+4</b> evento, sin escribir el prefijo</span>
<span size='small' alpha='70%'>«t: llamar a Juan el viernes» · «r: gimnasio lunes y jueves a las 19» · «e: examen 3 nov 9:00 2h»</span>"

ask() {  # $1 = texto inicial; deja el texto en $text (con el prefijo del tipo elegido) o sale
  local out rc
  out="$(printf '' | "$ROFI" -dmenu -config "$DIR/rofi/panel-captura.rasi" -mesg "$HELP" -p '' ${1:+-filter "$1"} \
          -kb-custom-1 'Alt+1' -kb-custom-2 'Alt+2' -kb-custom-3 'Alt+3' -kb-custom-4 'Alt+4')"; rc=$?
  case $rc in
    0) text="$out" ;;
    10|11|12|13)  # Alt+1…4: el tipo elegido, si el texto no lleva ya un prefijo
      local p; p=$(printf 't:\ni:\nr:\ne:' | sed -n "$((rc - 9))p")
      if [[ "$out" =~ ^[[:space:]]*[tireTIRE][[:space:]]*: ]]; then text="$out"; else text="$p $out"; fi ;;
    *) exit 0 ;;
  esac
}

interactive=1
prefill=''
if [ "${1:-}" = "--evento" ]; then prefill='e: '; shift; fi
if [ $# -gt 0 ]; then text="$*"; interactive=0; else ask "$prefill"; fi

while :; do
  [ -z "${text//[[:space:]]/}" ] && exit 0
  is_event=0; [[ "$text" =~ ^[[:space:]]*[eE][[:space:]]*: ]] && is_event=1
  is_typed=0; [[ "$text" =~ ^[[:space:]]*[tirTIR][[:space:]]*: ]] && is_typed=1
  # Vista previa: siempre en los eventos; en el menú, también si una tarea, idea o rutina lleva algo que interpretar
  [ $is_event -eq 0 ] && { [ $interactive -eq 0 ] || [ $is_typed -eq 0 ]; } && break
  prev="$("$PY" "$CLIENT" capture "$text" --dry-run)"; rc=$?
  if [ $rc -eq 0 ]; then
    kind="$(field kind <<<"$prev")"; when="$(field preview.when <<<"$prev")"
    title="$(field preview.title <<<"$prev" | esc)"
    if [ "$kind" = "evento" ]; then
      msg="<span color='#89b4fa'></span>  <b>$title</b>&#10;$(esc <<<"$when")"; opts=$'Guardar el evento\nCorregir el texto\nCancelar'
    elif [ $is_event -eq 1 ]; then
      msg="<span color='#f9e2af'></span>  No entiendo la fecha: $(field reason <<<"$prev" | esc).&#10;Se guardará en el Inbox marcado «Revisar fecha»."
      opts=$'Guardar en el Inbox\nCorregir el texto\nCancelar'
    elif [ -n "$when" ]; then
      icon=$(case "$kind" in rutina) echo "<span color='#cba6f7'></span>  Rutina" ;; idea) echo "<span color='#fab387'></span>  Idea" ;; *) echo "<span color='#94e2d5'></span>  Tarea" ;; esac)
      msg="$icon: <b>$title</b>&#10;$(esc <<<"$when")"; opts=$'Guardar\nCorregir el texto\nCancelar'
    else
      break  # nada que interpretar: se guarda sin preguntar
    fi
  elif [ $rc -eq 3 ]; then
    [ $is_event -eq 0 ] && break  # sin conexión: a la cola sin más
    msg="Sin conexión con el panel: no se puede ver la vista previa.&#10;El texto se guardará en la cola y se enviará después."
    opts=$'Guardar en la cola\nCancelar'
  else
    notify critical "Panel: no se pudo capturar" "$(field message <<<"$prev")"
    exit 1
  fi
  choice="$(printf '%s' "$opts" | "$ROFI" -dmenu -config "$DIR/rofi/panel-confirmar.rasi" -mesg "$msg" -p '' -no-custom -selected-row 0)" || exit 0
  case "$choice" in
    "Corregir el texto") interactive=1; ask "$text" ;;
    ""|"Cancelar") exit 0 ;;
    *) break ;;
  esac
done

res="$("$PY" "$CLIENT" capture "$text")"; rc=$?
message="$(field message <<<"$res")"
case $rc in
  0)
    if [ "$(field revisar <<<"$res")" = "True" ]; then notify normal "Panel: revisar fecha" "$message"
    else notify low "Panel: guardado" "$message"; fi ;;
  3) notify normal "Panel sin conexión" "$message" ;;
  *) notify critical "Panel: no se pudo capturar" "$message"; exit 1 ;;
esac
exit 0
