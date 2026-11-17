#!/usr/bin/env python3
"""
Módulo de la Waybar con la agenda del Panel (sustituye al reloj nativo). Solo biblioteca estándar.

    panel_agenda.py              JSON para Waybar: texto (hora, lo siguiente con cuenta atrás, número de atrasadas y
                                 un icono si las copias no están al día), tooltip (mes con hoy resaltado + agenda de
                                 hoy y mañana) y clase (sin-eventos, proximo, ahora, retrasado, atrasadas,
                                 copias-aviso, sin-conexion)
    panel_agenda.py --mes +1|-1|0   cambia el mes del tooltip (rueda; 0 = el actual) y refresca
    panel_agenda.py --menu [modo]   el centro de mando (panel_mando.py; clic izquierdo y Super+Alt+K)
    panel_agenda.py --atrasada JSON   (interno) notificación con botones de una tarea atrasada; espera al botón y
                                 llama a la API. La lanza el propio módulo, en segundo plano, una vez al día por tarea
    panel_agenda.py --aviso JSON (interno) igual con un aviso (tarea o rutina con hora, evento, resumen de la mañana)

Cada vez que se ejecuta además: reenvía la cola de capturas pendientes y muestra con notify-send los
avisos de escritorio que toquen (si están activados en el Panel → Avisos): los de tareas y rutinas con botones
(Empezar · Completar · +1 h o Mañana), los eventos con «Abrir», el resumen de la mañana una vez al día, y las tareas
atrasadas con los suyos (Completar · Mañana · Hoy no · Borrar; a la hora y en los días de Avisos, una vez al día por
tarea). Cada aviso se reclama antes en el Panel (POST /api/reminders/vistos): si ya lo enseñó el navegador, aquí no se
repite. Todas las notificaciones van como app «Panel» (swaync las agrupa) y las que se sustituyen a sí mismas (copias,
confirmaciones) llevan la pista `synchronous`. Sin conexión usa la última agenda guardada
(~/.cache/panel-maestro/agenda.json) y marca la clase «sin-conexion», sin errores.
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
COPIAS_AVISADO = pc.STATE / "copias-avisado"  # fecha del último aviso de copias (uno al día como mucho)
SIGNAL = 9
DIR = Path(__file__).resolve().parent

# Catppuccin Mocha, igual que la barra (style/Fusion Personalizada.css) y el tooltip del reloj anterior
C = {
    "mauve": "#cba6f7",
    "text": "#cdd6f4",
    "sub": "#9399b2",
    "dim": "#6c7086",
    "base": "#1e1e2e",
    "red": "#f38ba8",
    "peach": "#fab387",
    "yellow": "#f9e2af",
    "green": "#a6e3a1",
    "blue": "#89b4fa",
    "teal": "#94e2d5",
}
KIND_COLOR = {
    "examen": C["red"],
    "entrega": C["peach"],
    "evento": C["blue"],
    "bloque": C["teal"],
    "tarea": C["teal"],
    "idea": C["peach"],
    "rutina": C["mauve"],
}
# Colores de asignatura y proyecto (tokens cat-0…9 del panel, en Catppuccin Mocha como la barra)
CAT = dict(
    zip(
        (f"cat-{i}" for i in range(10)),
        ("#b4befe", "#89b4fa", "#a6e3a1", "#fab387", "#cba6f7", "#94e2d5", "#f9e2af", "#f38ba8", "#74c7ec", "#f2cdcd"),
    )
)
CTX_LABEL = {"puntual": "Puntual", "universidad": "Universidad", "proyectos": "Proyectos"}
# Contexto que muestra: el ajuste del panel (Universidad → Ajustes: «Contexto de la Waybar», por defecto el activo);
# PANEL_WAYBAR_CONTEXTO lo fija aquí (activo, todo, puntual, universidad, proyectos)
CONTEXTO = os.environ.get("PANEL_WAYBAR_CONTEXTO", "waybar")
MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
I_CAL, I_OFF, I_CHECK, I_DOT = "\U000f00ed", "\U000f0e7a", "", "•"


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
        data = pc.request("GET", f"/api/calendar/agenda?days={days}&contexto={CONTEXTO}")
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
                notify(
                    "low",
                    "Panel: cola enviada",
                    tag="panel-cola",
                    body=f"{res['sent']} captura{'s' if res['sent'] != 1 else ''} pendiente{'s' if res['sent'] != 1 else ''} enviada{'s' if res['sent'] != 1 else ''}",
                )
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
    shown = set(data.get("shown") or [])
    due = [r for r in data.get("reminders", []) if r["fire_at"] <= now and r["key"] not in seen]
    changed = bool(due)
    for r in due:
        seen[r["key"]] = time.time()  # aquí ya no se vuelve a mirar, lo enseñe quien lo enseñe
    claimed = set()
    fresh = [r["key"] for r in due if r["key"] not in shown]
    if fresh:
        try:
            claimed = set(pc.request("POST", "/api/reminders/vistos", {"keys": fresh}).get("claimed") or [])
        except RuntimeError:  # un Panel sin esa ruta (servicio aún sin reiniciar): se avisa como antes
            claimed = set(fresh)
        except Exception:  # noqa: BLE001 — sin conexión: mejor no avisar que avisar dos veces
            claimed = set()
    for r in due:
        if r["key"] in claimed:
            spawn("--aviso", json.dumps(r, ensure_ascii=False))
    if changed:
        week = time.time() - 7 * 86400
        seen = {k: v for k, v in seen.items() if v > week}
        pc.STATE.mkdir(parents=True, exist_ok=True)
        SEEN.write_text(json.dumps(seen))
    try:
        late_jobs()
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────────────────────
# Tareas atrasadas: una notificación con botones por tarea (P-1)
# ─────────────────────────────────────────────

LATE_ACTIONS = [("completar", "Completar"), ("manana", "Mañana"), ("hoy_no", "Hoy no"), ("borrar", "Borrar")]
LATE_MAX = 3  # más que esto, una sola notificación con el resto
LATE_WAIT = 12 * 3600  # lo que espera una notificación a que se pulse un botón


def late_jobs() -> list[dict]:
    """Pide al panel a cuáles toca avisar (él sabe la hora, los días, «hoy no» y lo ya avisado hoy), lo anota y lanza
    una notificación por tarea (en segundo plano: notify-send espera al botón). Devuelve las avisadas."""
    data = pc.request("GET", f"/api/items/atrasadas?contexto={CONTEXTO}&avisar=1")
    by_id = {e["id"]: e for e in data.get("atrasadas", [])}
    late = [by_id[i] for i in data.get("avisar") or [] if i in by_id]
    if not late:
        return []
    # Primero se anota: si no se puede, no se avisa (mejor eso que repetirlo cada minuto)
    pc.request("POST", "/api/items/atrasadas/avisadas", {"ids": [e["id"] for e in late]})
    for e in late[:LATE_MAX]:
        spawn("--atrasada", json.dumps(e, ensure_ascii=False))
    if late[LATE_MAX:]:
        spawn("--atrasadas-resto", json.dumps([e["id"] for e in late[LATE_MAX:]]))
    return late


def spawn(*args: str) -> None:
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def notify_actions(
    urgency: str, title: str, body: str, actions: list[tuple[str, str]], icon: str = "appointment-missed"
) -> str | None:
    """notify-send con botones (-A); espera y devuelve el nombre del pulsado («default» = clic en el aviso) o None."""
    cmd = [os.environ.get("PANEL_NOTIFY", "notify-send"), "-a", "Panel", "-u", urgency, "-i", icon]
    cmd += [f"--action={name}={label}" for name, label in actions] + [title, body]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=LATE_WAIT, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = out.strip().splitlines()
    return out[-1].strip() if out else None


def late_body(e: dict) -> str:
    dias = "ayer" if e.get("dias") == 1 else f"hace {e.get('dias')} días"
    d = parse(e["due_date"])
    extra = f" · {e['parent']}" if e.get("parent") else ""
    return f"Atrasada: era para {dias} ({DIAS[d.weekday()]} {d.day} {MESES_CORTOS[d.month - 1]}){extra}"


def late_notification(e: dict) -> str:
    """La notificación de una tarea y lo que hace su botón. Devuelve el mensaje de confirmación ('' = nada)."""
    what = notify_actions("normal", e["title"], late_body(e), LATE_ACTIONS + [("default", "Abrir en el panel")])
    if what == "default":
        subprocess.Popen(["xdg-open", pc.base_url() + e.get("href", f"/tareas?item={e['id']}")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        return ""
    if what not in dict(LATE_ACTIONS):
        return ""  # cerrada sin elegir
    body = {"ids": [e["id"]], "action": "posponer" if what == "manana" else what}
    if what == "manana":
        body["value"] = "manana"
    try:
        pc.request("POST", "/api/items/atrasadas/accion", body)
    except (pc.Offline, pc.AuthError, RuntimeError) as ex:
        notify("critical", "Panel: no se pudo", str(ex))
        return ""
    msg = {
        "completar": "Hecha",
        "manana": "Pasada a mañana",
        "hoy_no": "Callada hasta mañana",
        "borrar": "A la papelera",
    }[what]
    notify("low", f"Panel: {msg}", e["title"], tag="panel-accion")
    refresh_bar()
    return msg


def late_rest_notification(ids: list[int]) -> str:
    n = len(ids)
    what = notify_actions(
        "normal",
        f"Y {n} tarea{'s' if n != 1 else ''} atrasada{'s' if n != 1 else ''} más",
        "Ábrelas en el panel para cerrarlas de una en una",
        [("ver", "Ver todas"), ("hoy_no", "Hoy no a todas"), ("default", "Ver todas")],
    )
    if what in ("ver", "default"):
        subprocess.Popen(
            ["xdg-open", pc.base_url() + "/hoy?atrasadas=1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return ""
    if what == "hoy_no":
        try:
            pc.request("POST", "/api/items/atrasadas/accion", {"ids": ids, "action": "hoy_no"})
        except (pc.Offline, pc.AuthError, RuntimeError):
            return ""
        return "Calladas hasta mañana"
    return ""


def reminder_entry(r: dict) -> dict:
    """Un aviso con la forma de una línea de la agenda, para las acciones de panel_mando.act()."""
    kind = {"tarea": "task", "rutina": "routine", "evento": "event"}.get(r["kind"], r["kind"])
    return {"kind": kind, "id": r.get("item_id"), "item_id": r.get("item_id"), "title": r["title"], "done": False,
            "start": r.get("start"), "end": None, "all_day": bool(r.get("all_day")), "day": r.get("day")}  # fmt: skip


def reminder_actions(r: dict) -> list[tuple[str, str]]:
    if r["kind"] == "tarea" and r.get("item_id"):
        later = ("manana", "Mañana") if r.get("all_day") else ("1h", "+1 hora")
        return [("start", "Empezar"), ("done", "Completar"), later, ("default", "Abrir en el panel")]
    if r["kind"] == "rutina" and r.get("item_id"):
        return [("start", "Empezar"), ("done", "Hecha"), ("default", "Abrir en el panel")]
    if r["kind"] == "resumen":
        return [("mando", "Ver el día"), ("default", "Abrir Hoy")]
    return [("default", "Abrir en el panel")]


def reminder_notification(r: dict) -> str:
    """La notificación de un aviso con sus botones y lo que hace cada uno. Devuelve la confirmación ('' = nada)."""
    import panel_mando

    urgency = "critical" if r["kind"] == "evento" else "low" if r["kind"] == "resumen" else "normal"
    icon = {"resumen": "weather-clear", "evento": "appointment-soon"}.get(r["kind"], "appointment-soon")
    what = notify_actions(urgency, r["title"], r["body"], reminder_actions(r), icon=icon)
    if what == "default":
        subprocess.Popen(["xdg-open", pc.base_url() + (r.get("url") or "/hoy")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        return ""
    if what == "mando":
        spawn("--menu")
        return ""
    if what not in ("start", "done", "1h", "manana"):
        return ""  # cerrada sin elegir
    e = reminder_entry(r)
    try:
        msg = panel_mando.act(e, what)
    except (pc.Offline, pc.AuthError, RuntimeError) as ex:
        notify("critical", "Panel: no se pudo", str(ex))
        return ""
    if msg:
        notify("low", f"Panel: {msg}", r["title"], tag="panel-accion")
    refresh_bar()
    return msg or what


def backups_problem() -> dict | None:
    """Estado de las copias si NO están al día (antigua, error o ninguna); None si van bien o no se sabe."""
    try:
        bk = pc.request("GET", "/api/backups/status")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(bk, dict) or bk.get("health") in (None, "ok"):
        return None
    return bk


def backups_text(bk: dict) -> str:
    if bk["health"] == "sin-copias":
        return "Todavía no hay ninguna copia de seguridad"
    if bk["health"] == "error":
        return "Falló la última copia de seguridad"
    age = bk.get("age_h") or 0
    return f"La última copia tiene {round(age / 24)} días" if age >= 48 else f"La última copia tiene {round(age)} horas"


def notify_backups_once(bk: dict, today: date) -> None:
    """Notificación de escritorio de las copias: una al día como mucho (la barra se refresca cada minuto)."""
    try:
        if COPIAS_AVISADO.read_text().strip() == today.isoformat():
            return
    except OSError:
        pass
    notify(
        "normal",
        "Panel: copias de seguridad",
        f"{backups_text(bk)}. Ábrelas en Copias o pulsa «Hacer copia ahora» en Hoy.",
        tag="panel-copias",
    )
    try:
        pc.STATE.mkdir(parents=True, exist_ok=True)
        COPIAS_AVISADO.write_text(today.isoformat())
    except OSError:
        pass


def notify(urgency: str, title: str, body: str, tag: str | None = None) -> None:
    """notify-send como app «Panel» (swaync agrupa). Con `tag`, sustituye a la anterior del mismo tag en vez de
    amontonarse (pista synchronous, la que usan los OSD de volumen)."""
    hints = ["-h", f"string:x-canonical-private-synchronous:{tag}", "-h", f"string:synchronous:{tag}"] if tag else []
    subprocess.run(
        [
            os.environ.get("PANEL_NOTIFY", "notify-send"),
            "-a",
            "Panel",
            "-u",
            urgency,
            "-i",
            "appointment-soon",
            *hints,
            title,
            body,
        ],  # fmt: skip
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


# ─────────────────────────────────────────────
# Estado de la barra
# ─────────────────────────────────────────────

# Iconos (Nerd Font, la de la barra) y color de cada tipo
ICON = {
    "evento": "\uf073",
    "examen": "\uf02d",
    "entrega": "\uf15c",
    "bloque": "\uf017",
    "tarea": "\uf096",
    "idea": "\uf0eb",
    "rutina": "\uf021",
}
I_DONE, I_LATE, I_PLUS, I_EDIT, I_OPEN = "\uf14a", "\uf071", "\uf067", "\uf044", "\uf35d"
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def short(t: str, n: int = 26) -> str:
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s if len(s) > 10 else s + "T00:00")


def kind_of(e: dict) -> str:
    return e["type"] if e["kind"] == "event" else ("rutina" if e["kind"] == "routine" else e.get("type") or "tarea")


def status(data: dict | None, now: datetime) -> dict:
    """Texto y clase: lo que está pasando, lo próximo con hora (cuenta atrás si falta menos de una hora)
    o lo atrasado de hoy (tareas y rutinas con hora pasada sin hacer). `label` es lo que va tras la hora."""
    hora = now.strftime("%H:%M")
    out = lambda label, cls, nxt=None, **kw: {
        "text": f"{hora}  {I_DOT} {label}" if label else hora,
        "label": label,  # noqa: E731
        "class": cls,
        "next": nxt,
        **kw,
    }
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
        when = (
            countdown(mins)
            if mins < COUNTDOWN_MIN and e["start"][:10] == today
            else (
                e["start"][11:16]
                if e["start"][:10] == today
                else (
                    "mañana "
                    if e["start"][:10] == (now.date() + timedelta(days=1)).isoformat()
                    else DIAS[parse(e["start"]).weekday()][:3] + " "
                )
                + e["start"][11:16]
            )
        )
        cls = "proximo" if mins < 60 else ("retrasado" if late else "con-eventos")
        return out(f"{when} {short(e['title'])}", cls, e, late=len(late))
    if late:
        return out(f"{len(late)} pendiente{'s' if len(late) != 1 else ''}", "retrasado")
    return out("", "sin-eventos")


COUNTDOWN_MIN = 6 * 60  # lo de hoy que empieza antes de esto va en cuenta atrás («en 2 h 10»)
I_BACKUP = "\uf1c0"  # fa-database (Nerd Font)


def countdown(mins: int) -> str:
    if mins < 60:
        return f"en {max(mins, 1)} min"
    h, m = divmod(mins, 60)
    return f"en {h} h {m:02d}" if m else f"en {h} h"


def bar_text(st: dict, now: datetime, late: int = 0, copias: bool = False) -> str:
    """Hora en negrita, el día en gris, lo próximo con el color del estado (CSS de la barra) y, al final, el número de
    atrasadas (rojo) y un aviso de copias (melocotón) solo cuando los hay."""
    dia = f"{DIAS[now.weekday()][:3]} {now.day}"
    txt = f"<span color='{C['blue']}'>{I_CAL}</span> <b>{now:%H:%M}</b> <span color='{C['sub']}'>{dia}</span>"
    txt += f"  <span size='small'>{I_DOT}</span> {esc(st['label'])}" if st.get("label") else ""
    if late:
        txt += f"  <span color='{C['red']}'>{I_LATE} {'20+' if late >= 20 else late}</span>"
    if copias:
        txt += f"  <span color='{C['peach']}'>{I_BACKUP}</span>"
    return txt


def month_block(ref: date, today: date, marked: set[str]) -> list[str]:
    """Mes en monoespaciada: hoy con fondo, los días con algo en azul y negrita, el fin de semana en gris."""
    cal = calendar.Calendar(firstweekday=0)
    head = f"{MESES[ref.month - 1].capitalize()} {ref.year}"
    lines = [
        f"<tt>{span(head.center(20), C['mauve'], bold=True)}</tt>",
        f"<tt>{span(' L  M  X  J  V ', C['sub'])}{span(' S  D', C['dim'])}</tt>",
    ]
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
    color = C["dim"] if e.get("done") else CAT.get(e.get("color") or "") or KIND_COLOR.get(k, C["blue"])
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
    return (
        f"  <span color='{color}'>{icon}</span>  <tt><span color='{C['sub']}'>{when}</span></tt>  "
        f"<span color='{C['dim'] if e.get('done') else C['text']}'>{title}</span>{tail}"
    )


def on_day(e: dict, day: date) -> bool:
    d = day.isoformat()
    return e["start"][:10] == d or (e["all_day"] and e["start"][:10] <= d < (e["end"] or e["start"])[:10])


def agenda_lines(data: dict, day: date, label: str) -> list[str]:
    items = sorted((e for e in data["entries"] if on_day(e, day)), key=lambda e: (not e["all_day"], e["start"]))
    pend = [e for e in items if e["kind"] != "event"]
    resumen = (
        f"  <span color='{C['sub']}' size='small'>{sum(1 for e in pend if e.get('done'))} de {len(pend)} hechas</span>"
        if pend
        else ""
    )
    out = [span(f"{label} · {DIAS[day.weekday()]} {day.day}", C["mauve"], bold=True) + resumen]
    if not items:
        return out + [f"  <span color='{C['dim']}'>Nada</span>"]
    return out + [entry_line(e) for e in items]


def tooltip(data: dict | None, now: datetime, online: bool, offset: int, copias: dict | None = None) -> str:
    today = now.date()
    ref = date(today.year, today.month, 1)
    m = ref.month - 1 + offset
    ref = date(ref.year + m // 12, m % 12 + 1, 1)
    marked = {e["start"][:10] for e in (data or {}).get("entries", [])}
    titulo = f"{DIAS[today.weekday()].capitalize()}, {today.day} de {MESES[today.month - 1]}"
    ctx = CTX_LABEL.get((data or {}).get("contexto") or "")
    parts = [
        f"<span size='large' color='{C['text']}'><b>{titulo}</b></span>  <span color='{C['sub']}'>{now:%H:%M} · semana {today.isocalendar().week}"
        f"{f' · {ctx}' if ctx else ''}</span>",
        "",
    ]
    parts += month_block(ref, today, marked)
    if data:
        parts += (
            [""] + agenda_lines(data, today, "Hoy") + [""] + agenda_lines(data, today + timedelta(days=1), "Mañana")
        )
        later = [
            e
            for e in data["entries"]
            if e["start"][:10] > (today + timedelta(days=1)).isoformat() and not e.get("done")
        ]
        if later:
            parts += ["", span("Próximos días", C["mauve"], bold=True)] + [
                entry_line(e, show_day=True) for e in later[:6]
            ]
            if len(later) > 6:
                parts.append(f"  <span color='{C['dim']}'>y {len(later) - 6} más…</span>")
        if data.get("overdue"):
            parts += ["", span(f"{I_LATE}  Atrasadas · {len(data['overdue'])}", C["red"], bold=True)] + [
                entry_line(e, show_day=True) for e in data["overdue"][:4]
            ]
    if copias:
        parts += ["", span(f"{I_LATE}  {backups_text(copias)}", C["peach"], bold=True)]
    if not online:
        when = (
            datetime.fromtimestamp(data["saved_at"]).strftime("%d/%m %H:%M")
            if data and data.get("saved_at")
            else "nunca"
        )
        parts += ["", span(f"{I_OFF} Sin conexión con el Panel · datos de {when}", C["red"])]
    parts += [
        "",
        f"<span color='{C['dim']}' size='small'>Clic o Super+Alt+K: centro de mando · Clic derecho: evento rápido · Rueda: cambiar de mes</span>",
    ]
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
    copias = backups_problem() if online else None
    if copias:
        notify_backups_once(copias, now.date())
    late = len((data or {}).get("overdue") or [])
    classes = (
        [st["class"]]
        + (["atrasadas"] if late else [])
        + ([] if online else ["sin-conexion"])
        + (["copias-aviso"] if copias else [])
    )
    return {
        "text": bar_text(st, now, late, bool(copias)),
        "tooltip": tooltip(data, now, online, offset, copias),
        "class": classes,
        "alt": st["class"],
    }


# ─────────────────────────────────────────────
# Menú: el centro de mando (panel_mando.py)
# ─────────────────────────────────────────────


def menu(mode: str = "hoy") -> int:
    import panel_mando

    return panel_mando.main(["panel_mando.py", "--modo", mode])


def refresh_bar() -> None:
    subprocess.run(
        ["pkill", f"-RTMIN+{SIGNAL}", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )


def main(argv: list[str]) -> int:
    if "--menu" in argv:
        i = argv.index("--menu")
        return menu(argv[i + 1] if len(argv) > i + 1 else "hoy")
    if "--aviso" in argv:
        reminder_notification(json.loads(argv[argv.index("--aviso") + 1]))
        return 0
    if "--atrasada" in argv:
        late_notification(json.loads(argv[argv.index("--atrasada") + 1]))
        return 0
    if "--atrasadas-resto" in argv:
        late_rest_notification(json.loads(argv[argv.index("--atrasadas-resto") + 1]))
        return 0
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
