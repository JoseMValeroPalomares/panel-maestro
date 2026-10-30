#!/usr/bin/env python3
"""
Módulo de la Waybar con la agenda del Panel (sustituye al reloj nativo). Solo biblioteca estándar.

    panel_agenda.py              JSON para Waybar: texto, tooltip (mes con hoy resaltado + agenda de hoy
                                 y mañana) y clase (sin-eventos, proximo, ahora, retrasado, sin-conexion)
    panel_agenda.py --mes +1|-1|0   cambia el mes del tooltip (rueda; 0 = el actual) y refresca
    panel_agenda.py --menu       rofi con la agenda de los próximos días; al elegir: completar, posponer
                                 o abrir en la app (clic izquierdo)

Cada vez que se ejecuta además: reenvía la cola de capturas pendientes y muestra con notify-send los
avisos de escritorio que toquen (si están activados en el Panel → Avisos). Sin conexión usa la última
agenda guardada (~/.cache/panel-maestro/agenda.json) y marca la clase «sin-conexion», sin errores.
Señal de refresco: RTMIN+9 (`pkill -RTMIN+9 waybar`).
"""
import calendar
import html
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_client as pc  # noqa: E402

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "panel-maestro"
AGENDA = CACHE / "agenda.json"
MONTH = CACHE / "mes"
SEEN = pc.STATE / "avisos.json"
SIGNAL = 9
DIR = Path(__file__).resolve().parent

# Catppuccin Mocha, igual que la barra (style/Fusion Personalizada.css) y el tooltip del reloj anterior
C = {"mauve": "#cba6f7", "text": "#cdd6f4", "sub": "#9399b2", "dim": "#6c7086", "base": "#1e1e2e", "red": "#f38ba8",
     "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1", "blue": "#89b4fa", "teal": "#94e2d5"}
KIND_COLOR = {"examen": C["red"], "entrega": C["peach"], "evento": C["blue"], "bloque": C["teal"], "tarea": C["teal"],
              "idea": C["peach"], "rutina": C["mauve"]}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
I_CAL, I_OFF, I_CHECK, I_DOT = "\U000F00ED", "\U000F0E7A", "", "•"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def span(text, color=None, bold=False) -> str:
    attrs = f" color='{color}'" if color else ""
    t = esc(text)
    return f"<span{attrs}>{'<b>' + t + '</b>' if bold else t}</span>"


# ─────────────────────────────────────────────
# Datos (con caché)
# ─────────────────────────────────────────────

def fetch(days: int = 7) -> tuple[dict | None, bool]:
    """(agenda, online). Sin conexión, la última guardada."""
    try:
        data = pc.request("GET", f"/api/calendar/agenda?days={days}")
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = AGENDA.with_suffix(".tmp")
        tmp.write_text(json.dumps({**data, "saved_at": time.time()}, ensure_ascii=False))
        tmp.replace(AGENDA)
        return data, True
    except (pc.Offline, pc.AuthError, RuntimeError):
        try:
            return json.loads(AGENDA.read_text()), False
        except (OSError, ValueError):
            return None, False


def side_jobs() -> None:
    """Cola de capturas y avisos de escritorio (no deben romper nunca el módulo)."""
    try:
        if pc.queued():
            res = pc.flush()
            if res["sent"]:
                notify("low", "Panel: cola enviada", f"{res['sent']} captura{'s' if res['sent'] != 1 else ''} pendiente{'s' if res['sent'] != 1 else ''} enviada{'s' if res['sent'] != 1 else ''}")
    except Exception:  # noqa: BLE001
        pass
    try:
        data = pc.request("GET", "/api/reminders?horizon=1")
    except Exception:  # noqa: BLE001
        return
    if not data.get("settings", {}).get("escritorio", {}).get("on", True):
        return
    try:
        seen = json.loads(SEEN.read_text())
    except (OSError, ValueError):
        seen = {}
    now = data["now"]
    changed = False
    for r in data.get("reminders", []):
        if r["fire_at"] <= now and r["key"] not in seen:
            seen[r["key"]] = time.time()
            changed = True
            notify("normal" if r["kind"] != "evento" else "critical", r["title"], r["body"])
    if changed:
        week = time.time() - 7 * 86400
        seen = {k: v for k, v in seen.items() if v > week}
        pc.STATE.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(seen))


def notify(urgency: str, title: str, body: str) -> None:
    subprocess.run([os.environ.get("PANEL_NOTIFY", "notify-send"), "-a", "Panel", "-u", urgency, "-i", "appointment-soon", title, body],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


# ─────────────────────────────────────────────
# Estado de la barra
# ─────────────────────────────────────────────

# Iconos (Nerd Font, la de la barra) y color de cada tipo
ICON = {"evento": "\uf073", "examen": "\uf02d", "entrega": "\uf15c", "bloque": "\uf017", "tarea": "\uf096", "idea": "\uf0eb",
        "rutina": "\uf021"}
I_DONE, I_LATE, I_PLUS, I_EDIT, I_OPEN = "\uf14a", "\uf071", "\uf067", "\uf044", "\uf35d"
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def short(t: str, n: int = 26) -> str:
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s if len(s) > 10 else s + "T00:00")


def kind_of(e: dict) -> str:
    return e["type"] if e["kind"] == "event" else ("rutina" if e["kind"] == "routine" else e.get("type") or "tarea")


def status(data: dict | None, now: datetime) -> dict:
    """Texto y clase: lo que está pasando, lo próximo con hora (cuenta atrás si falta menos de una hora)
    o lo atrasado de hoy (tareas y rutinas con hora pasada sin hacer). `label` es lo que va tras la hora."""
    hora = now.strftime("%H:%M")
    out = lambda label, cls, nxt=None, **kw: {"text": f"{hora}  {I_DOT} {label}" if label else hora, "label": label,  # noqa: E731
                                             "class": cls, "next": nxt, **kw}
    if not data:
        return out("", "sin-eventos")
    today = now.date().isoformat()
    timed = [e for e in data["entries"] if not e["all_day"] and not e.get("done")]
    ahora = [e for e in timed if e["kind"] == "event" and parse(e["start"]) <= now < parse(e["end"] or e["start"])]
    late = [e for e in timed if e["kind"] != "event" and e["start"][:10] == today and parse(e["start"]) <= now]
    nxt = sorted((e for e in timed if parse(e["start"]) > now), key=lambda e: e["start"])
    if ahora:
        e = ahora[0]
        return out(f"{short(e['title'])} (hasta {e['end'][11:16]})", "ahora", e)
    if nxt:
        e = nxt[0]
        mins = int((parse(e["start"]) - now).total_seconds() // 60)
        when = f"en {mins} min" if mins < 60 else (e["start"][11:16] if e["start"][:10] == today else
                                                   ("mañana " if e["start"][:10] == (now.date() + timedelta(days=1)).isoformat() else DIAS[parse(e['start']).weekday()][:3] + " ") + e["start"][11:16])
        cls = "proximo" if mins < 60 else ("retrasado" if late else "con-eventos")
        return out(f"{when} {short(e['title'])}", cls, e, late=len(late))
    if late:
        return out(f"{len(late)} pendiente{'s' if len(late) != 1 else ''}", "retrasado")
    return out("", "sin-eventos")


def bar_text(st: dict, now: datetime) -> str:
    """Hora en negrita, el día en gris y lo próximo con el color del estado (CSS de la barra)."""
    dia = f"{DIAS[now.weekday()][:3]} {now.day}"
    txt = f"<span color='{C['blue']}'>{I_CAL}</span> <b>{now:%H:%M}</b> <span color='{C['sub']}'>{dia}</span>"
    return txt + (f"  <span size='small'>{I_DOT}</span> {esc(st['label'])}" if st.get("label") else "")


def month_block(ref: date, today: date, marked: set[str]) -> list[str]:
    """Mes en monoespaciada: hoy con fondo, los días con algo en azul y negrita, el fin de semana en gris."""
    cal = calendar.Calendar(firstweekday=0)
    head = f"{MESES[ref.month - 1].capitalize()} {ref.year}"
    lines = [f"<tt>{span(head.center(20), C['mauve'], bold=True)}</tt>",
             f"<tt>{span(' L  M  X  J  V ', C['sub'])}{span(' S  D', C['dim'])}</tt>"]
    for week in cal.monthdatescalendar(ref.year, ref.month):
        cells = []
        for d in week:
            t = f"{d.day:2d}"
            if d.month != ref.month:
                cells.append(span(t, C["dim"]))
            elif d == today:
                cells.append(f"<span background='{C['mauve']}' color='{C['base']}'><b>{t}</b></span>")
            elif d.isoformat() in marked:
                cells.append(f"<span color='{C['blue']}'><b>{t}</b></span>")
            else:
                cells.append(span(t, C["sub"] if d.weekday() >= 5 else C["text"]))
        lines.append("<tt>" + " ".join(cells) + "</tt>")
    return lines


def entry_line(e: dict, show_day: bool = False) -> str:
    k = kind_of(e)
    icon = I_DONE if e.get("done") else ICON.get(k, ICON["evento"])
    color = C["dim"] if e.get("done") else KIND_COLOR.get(k, C["blue"])
    when = "  —  " if e["all_day"] else e["start"][11:16]
    if show_day:
        d = parse(e["start"])
        when = f"{DIAS[d.weekday()][:3]} {d.day:>2}"
    title = esc(e["title"][:46])
    title = f"<s>{title}</s>" if e.get("done") else title
    extra = []
    if e.get("steps"):
        extra.append(f"{sum(1 for s in e['steps'] if s.get('done'))}/{len(e['steps'])} pasos")
    if e.get("location"):
        extra.append(esc(e["location"][:24]))
    tail = f"  <span color='{C['dim']}'>{' · '.join(extra)}</span>" if extra else ""
    return (f"  <span color='{color}'>{icon}</span>  <tt><span color='{C['sub']}'>{when}</span></tt>  "
            f"<span color='{C['dim'] if e.get('done') else C['text']}'>{title}</span>{tail}")


def on_day(e: dict, day: date) -> bool:
    d = day.isoformat()
    return e["start"][:10] == d or (e["all_day"] and e["start"][:10] <= d < (e["end"] or e["start"])[:10])


def agenda_lines(data: dict, day: date, label: str) -> list[str]:
    items = sorted((e for e in data["entries"] if on_day(e, day)), key=lambda e: (not e["all_day"], e["start"]))
    pend = [e for e in items if e["kind"] != "event"]
    resumen = f"  <span color='{C['sub']}' size='small'>{sum(1 for e in pend if e.get('done'))} de {len(pend)} hechas</span>" if pend else ""
    out = [span(f"{label} · {DIAS[day.weekday()]} {day.day}", C["mauve"], bold=True) + resumen]
    if not items:
        return out + [f"  <span color='{C['dim']}'>Nada</span>"]
    return out + [entry_line(e) for e in items]


def tooltip(data: dict | None, now: datetime, online: bool, offset: int) -> str:
    today = now.date()
    ref = date(today.year, today.month, 1)
    m = ref.month - 1 + offset
    ref = date(ref.year + m // 12, m % 12 + 1, 1)
    marked = {e["start"][:10] for e in (data or {}).get("entries", [])}
    titulo = f"{DIAS[today.weekday()].capitalize()}, {today.day} de {MESES[today.month - 1]}"
    parts = [f"<span size='large' color='{C['text']}'><b>{titulo}</b></span>  <span color='{C['sub']}'>{now:%H:%M} · semana {today.isocalendar().week}</span>", ""]
    parts += month_block(ref, today, marked)
    if data:
        parts += [""] + agenda_lines(data, today, "Hoy") + [""] + agenda_lines(data, today + timedelta(days=1), "Mañana")
        later = [e for e in data["entries"] if e["start"][:10] > (today + timedelta(days=1)).isoformat() and not e.get("done")]
        if later:
            parts += ["", span("Próximos días", C["mauve"], bold=True)] + [entry_line(e, show_day=True) for e in later[:6]]
            if len(later) > 6:
                parts.append(f"  <span color='{C['dim']}'>y {len(later) - 6} más…</span>")
        if data.get("overdue"):
            parts += ["", span(f"{I_LATE}  Atrasadas · {len(data['overdue'])}", C["red"], bold=True)] + [entry_line(e, show_day=True) for e in data["overdue"][:4]]
    if not online:
        when = datetime.fromtimestamp(data["saved_at"]).strftime("%d/%m %H:%M") if data and data.get("saved_at") else "nunca"
        parts += ["", span(f"{I_OFF} Sin conexión con el Panel · datos de {when}", C["red"])]
    parts += ["", f"<span color='{C['dim']}' size='small'>Clic o Super+Alt+K: agenda · Clic derecho: evento rápido · Rueda: cambiar de mes</span>"]
    return "\n".join(parts)


def waybar() -> dict:
    now = datetime.now()
    data, online = fetch(7)
    if online:
        side_jobs()
    try:
        offset = int(MONTH.read_text())
    except (OSError, ValueError):
        offset = 0
    st = status(data, now)
    classes = [st["class"]] + ([] if online else ["sin-conexion"])
    return {"text": bar_text(st, now), "tooltip": tooltip(data, now, online, offset), "class": classes, "alt": st["class"]}


# ─────────────────────────────────────────────
# Menú rofi (clic izquierdo o Super+Alt+K): la agenda con atajos directos
# ─────────────────────────────────────────────

KEYS = [("Alt+c", "done"), ("Alt+p", "1h"), ("Alt+m", "manana"), ("Alt+o", "open")]  # kb-custom-1…4 → códigos 10…13


def rofi(lines: list[str], mesg: str, theme: str = "panel-agenda.rasi", selected: int = 0, active: list[int] | None = None,
         urgent: list[int] | None = None, keys: bool = False) -> tuple[int | None, int]:
    """(fila elegida, código de salida): 0 = Intro, 10… = Alt+tecla de KEYS, 1 = Esc."""
    cmd = [os.environ.get("PANEL_ROFI", "rofi"), "-dmenu", "-i", "-format", "i", "-no-custom", "-markup-rows",
           "-config", str(DIR / "rofi" / theme), "-mesg", mesg, "-p", "", "-selected-row", str(selected)]
    if active:
        cmd += ["-a", ",".join(map(str, active))]
    if urgent:
        cmd += ["-u", ",".join(map(str, urgent))]
    if keys:
        for n, (k, _) in enumerate(KEYS, 1):
            cmd += [f"-kb-custom-{n}", k]
    proc = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True)
    out = proc.stdout.strip()
    return (int(out) if out.isdigit() else None), proc.returncode


def act(e: dict, what: str) -> str:
    if what == "done":
        if e["kind"] == "event":
            return ""
        if e["kind"] == "routine":
            pc.request("POST", f"/api/routines/{e['item_id']}/check", {"day": e["day"], "done": not e["done"]})
        else:
            pc.request("PATCH", f"/api/items/{e['item_id']}", {"done": not e["done"]})
        return "Hecho" if not e["done"] else "Vuelve a pendiente"
    if what in ("1h", "manana"):
        if e["kind"] == "routine":
            return ""
        delta = timedelta(hours=1) if what == "1h" else timedelta(days=1)
        if e["kind"] == "event":
            if e["all_day"]:
                start = (parse(e["start"]) + timedelta(days=1)).date().isoformat()
                pc.request("PATCH", f"/api/calendar/events/{e['id']}", {"start": start})
            else:
                pc.request("PATCH", f"/api/calendar/events/{e['id']}", {"start": (parse(e["start"]) + delta).strftime("%Y-%m-%dT%H:%M")})
        elif e["kind"] == "task":
            base = parse(e["start"])
            if e.get("overdue") or base.date() < date.today():  # atrasada: a hoy (o mañana) desde hoy
                base = datetime.combine(date.today() - (timedelta(days=1) if what == "manana" else timedelta(0)), base.time())
            nd = base + (delta if not e["all_day"] else timedelta(days=1))
            body = {"due_date": nd.date().isoformat()}
            if not e["all_day"]:
                body["due_time"] = nd.strftime("%H:%M")
            pc.request("PATCH", f"/api/items/{e['item_id']}", body)
        return "Pospuesto" if what == "1h" else "Pasado a mañana"
    url = pc.base_url() + (f"/calendario?dia={e['start'][:10]}" if e["kind"] == "event" else f"/tareas?item={e['item_id']}")
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ""


def menu_rows(data: dict, today: date, now: datetime | None = None) -> tuple[list[str], list, list[int], list[int], int]:
    """Filas del menú: acciones, atrasadas, y la agenda por días con su cabecera.
    Devuelve (filas, qué es cada fila, cabeceras, atrasadas, fila que se selecciona al abrir)."""
    rows = [f"<span color='{C['blue']}'>{I_PLUS}</span>  <b>Nuevo evento…</b>",
            f"<span color='{C['teal']}'>{I_EDIT}</span>  <b>Capturar una tarea, idea o rutina…</b>",
            f"<span color='{C['mauve']}'>{I_OPEN}</span>  <b>Abrir el calendario</b>"]
    what: list = ["new-event", "capture", "open-cal"]
    heads, late, sel = [], [], None
    if data.get("overdue"):
        heads.append(len(rows))
        rows.append(f"<span color='{C['red']}'><b>{I_LATE}  ATRASADAS · {len(data['overdue'])}</b></span>")
        what.append(None)
        for e in data["overdue"]:
            late.append(len(rows))
            rows.append(entry_line({**e, "overdue": True}, show_day=True))
            what.append({**e, "overdue": True})
    entries = sorted(data["entries"], key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))
    now = now or datetime.now()
    for i in range(7):
        day = today + timedelta(days=i)
        items = [e for e in entries if on_day(e, day) and (i == 0 or e["start"][:10] == day.isoformat())]
        if not items and i > 1:
            continue
        label = "HOY" if i == 0 else "MAÑANA" if i == 1 else DIAS[day.weekday()].upper()
        heads.append(len(rows))
        rows.append(f"<span color='{C['mauve']}'><b>{label}</b></span>  <span color='{C['sub']}'>{DIAS[day.weekday()]} {day.day} {MESES_CORTOS[day.month - 1]}</span>")
        what.append(None)
        if not items:
            rows.append(f"     <span color='{C['dim']}'>Nada</span>")
            what.append(None)
        for e in items:
            if sel is None and i == 0 and not e.get("done") and (e["all_day"] or parse(e["end"] or e["start"]) >= now):
                sel = len(rows)
            rows.append(entry_line(e))
            what.append(e)
    if sel is None:  # nada pendiente hoy: el primer elemento que haya
        sel = next((n for n, w in enumerate(what) if isinstance(w, dict)), 0)
    return rows, what, heads, late, sel


def menu() -> int:
    sel = None
    while True:
        data, online = fetch(7)
        if not data:
            notify("normal", "Panel sin conexión", "No hay agenda guardada todavía")
            return 1
        rows, what, heads, late, first = menu_rows(data, date.today())
        keys = "  ".join(f"<b>{k.title()}</b> {t}" for (k, _), t in zip(KEYS, ["completar", "+1 hora", "a mañana", "abrir"]))
        mesg = f"<b>Intro</b> opciones   {keys}" + ("" if online else f"   <span color='{C['red']}'>{I_OFF} sin conexión: solo lectura</span>")
        i, rc = rofi(rows, mesg, selected=sel if sel is not None else first, active=heads, urgent=late, keys=online)
        if i is None or rc == 1 or i >= len(what):
            return 0
        sel = i
        w = what[i]
        if w in ("new-event", "capture"):
            subprocess.Popen([str(DIR / "quick_capture.sh")] + (["--evento"] if w == "new-event" else []),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        if w == "open-cal":
            subprocess.Popen(["xdg-open", pc.base_url() + "/calendario"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        if not isinstance(w, dict) or not online:
            continue  # cabecera o «Nada»: el menú sigue abierto
        if rc >= 10:  # atajo directo: se hace y el menú vuelve a abrirse en la misma fila
            how = KEYS[rc - 10][1]
        else:
            how = submenu(w)
            if how is None:
                continue
        try:
            msg = act(w, how)
        except (pc.Offline, pc.AuthError, RuntimeError) as ex:
            notify("critical", "Panel: no se pudo", str(ex))
            return 1
        if msg:
            notify("low", f"Panel: {msg}", w["title"])
        refresh_bar()
        if how == "open":
            return 0


def submenu(e: dict) -> str | None:
    opts = []
    if e["kind"] != "event":
        opts.append(("done", f"{I_DONE}  " + ("Desmarcar" if e.get("done") else "Completar") + "   <span size='small'>Alt+C</span>"))
    if e["kind"] in ("event", "task"):
        if not e["all_day"]:
            opts.append(("1h", "\uf017  Posponer 1 hora   <span size='small'>Alt+P</span>"))
        opts.append(("manana", "\uf061  Pasar a mañana   <span size='small'>Alt+M</span>"))
    opts += [("open", f"{I_OPEN}  Abrir en el Panel   <span size='small'>Alt+O</span>"), ("back", "\uf060  Volver a la agenda")]
    when = "todo el día" if e["all_day"] else e["start"][11:16] + (f"–{e['end'][11:16]}" if e.get("end") else "")
    d = parse(e["start"])
    j, _ = rofi([t for _, t in opts], f"<b>{esc(e['title'])}</b>   <span size='small'>{DIAS[d.weekday()]} {d.day} {MESES_CORTOS[d.month - 1]} · {when}</span>",
                theme="panel-confirmar.rasi")
    if j is None or opts[j][0] == "back":
        return None
    return opts[j][0]


def refresh_bar() -> None:
    subprocess.run(["pkill", f"-RTMIN+{SIGNAL}", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def main(argv: list[str]) -> int:
    if "--menu" in argv:
        return menu()
    if "--mes" in argv:
        step = argv[argv.index("--mes") + 1] if len(argv) > argv.index("--mes") + 1 else "0"
        try:
            cur = int(MONTH.read_text())
        except (OSError, ValueError):
            cur = 0
        new = 0 if step == "0" else max(-24, min(24, cur + int(step)))
        CACHE.mkdir(parents=True, exist_ok=True)
        MONTH.write_text(str(new))
        refresh_bar()
        return 0
    try:
        out = waybar()
    except Exception as e:  # noqa: BLE001 — la barra nunca debe quedarse sin módulo
        out = {"text": f"{I_CAL} {datetime.now():%H:%M}", "tooltip": esc(f"Panel: {e}"), "class": ["sin-conexion"]}
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
