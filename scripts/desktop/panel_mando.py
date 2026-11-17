#!/usr/bin/env python3
"""
Centro de mando del Panel en rofi (P-11): Super+Alt+K o clic en la hora de la Waybar. Solo biblioteca estándar.

    panel_mando.py [--modo hoy|semana|buscar]    abre el centro de mando (por defecto, Hoy)
    panel_agenda.py --menu                       lo mismo (es lo que llaman el atajo de Hyprland y la Waybar)

Modos, con Alt+número en cualquier momento:
    Alt+1 Hoy       el contador en marcha, las atrasadas, hoy y mañana
    Alt+2 Semana    los próximos 7 días
    Alt+3 Buscar    tareas pendientes y notas (escribe para filtrar; Ctrl+Intro busca dentro del texto)
    Alt+4 Capturar  la captura rápida (Super+K)
Sobre cada línea: Intro opciones · Alt+C completar · Alt+P posponer · Alt+M a mañana · Alt+E empezar el contador ·
Alt+O abrir en el Panel. Borrar va solo en las opciones (Intro), y lo borrado va a la papelera del Panel.
Tras cada acción el menú vuelve a abrirse en el mismo modo y en la misma fila. Sin conexión: solo lectura, con la última
agenda guardada.

Es el único sitio desde el que se *hace* algo en el escritorio con varios elementos a la vista; la Waybar solo enseña
(y su clic abre esto) y las notificaciones llevan los botones de su propio aviso, que llaman a `act()` de aquí.
"""

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_agenda as pa  # noqa: E402
import panel_client as pc  # noqa: E402

DIR = Path(__file__).resolve().parent
C = pa.C
esc = pa.esc

# Acciones sobre la línea elegida: kb-custom-1…5 → códigos de salida 10…14
KEYS = [("Alt+c", "done"), ("Alt+p", "1h"), ("Alt+m", "manana"), ("Alt+o", "open"), ("Alt+e", "start")]
KEY_LABEL = {"done": "completar", "1h": "posponer", "manana": "a mañana", "open": "abrir", "start": "empezar"}
# Modos: kb-custom-6…9 → 15…18 (las Alt+número de rofi por defecto se reasignan aquí)
MODES = [("Alt+1", "hoy", "Hoy"), ("Alt+2", "semana", "Semana"), ("Alt+3", "buscar", "Buscar"), ("Alt+4", "capturar", "Capturar")]  # fmt: skip
I_PLAY, I_PAUSE, I_NOTE, I_SEARCH, I_TRASH = "", "", "", "", ""


def short_date(d: date) -> str:
    return f"{pa.DIAS[d.weekday()]} {d.day} {pa.MESES_CORTOS[d.month - 1]}"


# ─────────────────────────────────────────────
# rofi
# ─────────────────────────────────────────────


def rofi(
    lines: list[str],
    mesg: str,
    theme: str = "panel-agenda.rasi",
    selected: int = 0,
    active: list[int] | None = None,
    urgent: list[int] | None = None,
    keys: bool = False,
    modes: bool = False,
    custom: bool = False,
    placeholder: str | None = None,
) -> tuple[int | None, int, str]:
    """(fila elegida o None, código de salida, texto escrito). 0 = Intro, 10… = KEYS, 15… = MODES, 1 = Esc.
    Con `custom`, lo escrito que no es ninguna fila llega como (None, 0|…, texto); Ctrl+Intro siempre así."""
    cmd = [os.environ.get("PANEL_ROFI", "rofi"), "-dmenu", "-i", "-format", "i|s", "-markup-rows",
           "-config", str(DIR / "rofi" / theme), "-mesg", mesg, "-p", "", "-selected-row", str(max(0, selected))]  # fmt: skip
    if not custom:
        cmd.append("-no-custom")
    if placeholder:
        cmd += ["-theme-str", f'entry {{ placeholder: "{placeholder}"; }}']
    if active:
        cmd += ["-a", ",".join(map(str, active))]
    if urgent:
        cmd += ["-u", ",".join(map(str, urgent))]
    if keys:
        for n, (k, _) in enumerate(KEYS, 1):
            cmd += [f"-kb-custom-{n}", k]
    if modes:
        for n, (k, _, _) in enumerate(MODES, len(KEYS) + 1):
            cmd += [f"-kb-custom-{n}", k]
    proc = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True, check=False)
    out = proc.stdout.rstrip("\n")
    idx, _, text = out.partition("|")
    i = int(idx) if idx.lstrip("-").isdigit() and int(idx) >= 0 else None
    return i, proc.returncode, text


def mode_of(rc: int) -> str | None:
    n = rc - 10 - len(KEYS)
    return MODES[n][1] if 0 <= n < len(MODES) else None


def header(mode: str, online: bool, extra: str = "") -> str:
    tabs = "   ".join(
        (
            f"<span color='{C['mauve']}'><b>{label}</b></span>"
            if m == mode
            else f"<span color='{C['sub']}'>{label}</span>"
        )
        + f" <span size='small' color='{C['dim']}'>{k}</span>"
        for k, m, label in MODES
    )
    keys = "  ".join(f"<b>{k.title()}</b> {KEY_LABEL[w]}" for k, w in KEYS)
    line2 = f"<span size='small'><b>Intro</b> opciones   {keys}</span>"
    off = "" if online else f"\n<span color='{C['red']}'>{pa.I_OFF} Sin conexión: solo lectura</span>"
    return f"{tabs}\n{line2}{extra}{off}"


# ─────────────────────────────────────────────
# Acciones (las comparten el menú y los botones de las notificaciones)
# ─────────────────────────────────────────────


def open_url(path: str) -> None:
    subprocess.Popen(["xdg-open", pc.base_url() + path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def href(e: dict) -> str:
    if e.get("href"):
        return e["href"]
    if e["kind"] == "event":
        return f"/calendario?dia={e['start'][:10]}"
    if e["kind"] == "note":
        return f"/?note={e['id']}"
    return f"/tareas?item={e['item_id']}"


def act(e: dict, what: str) -> str:
    """Hace `what` sobre una línea de la agenda (evento, tarea o rutina). Devuelve el texto de la confirmación."""
    if what == "open":
        open_url(href(e))
        return ""
    if e["kind"] == "note":
        return ""
    if what == "start":  # contador en marcha (P-2): el módulo panel_contador.py lo enseña y lo notifica
        if e["kind"] == "event" or not e.get("item_id"):
            return ""
        pc.request("POST", "/api/contador/empezar", {"item_id": e["item_id"]})
        _poke_timer()
        return ""  # la notificación «En marcha» la da el módulo del contador
    if what == "done":
        if e["kind"] == "event":
            return ""
        if e["kind"] == "routine":
            pc.request("POST", f"/api/routines/{e['item_id']}/check", {"day": e["day"], "done": not e.get("done")})
        else:
            pc.request("PATCH", f"/api/items/{e['item_id']}", {"done": not e.get("done")})
        return "Hecho" if not e.get("done") else "Vuelve a pendiente"
    if what == "delete":
        if e["kind"] != "task":
            return ""
        pc.request("DELETE", f"/api/items/{e['item_id']}")
        return "A la papelera"
    if what in ("1h", "manana"):
        if e["kind"] == "routine":
            return ""
        today = date.today()
        if e["kind"] == "event":
            if e["all_day"]:
                start = (pa.parse(e["start"]) + timedelta(days=1)).date().isoformat()
            else:
                delta = timedelta(hours=1) if what == "1h" else timedelta(days=1)
                start = (pa.parse(e["start"]) + delta).strftime("%Y-%m-%dT%H:%M")
            pc.request("PATCH", f"/api/calendar/events/{e['id']}", {"start": start})
            return "Pospuesto" if what == "1h" else "Pasado a mañana"
        base = pa.parse(e["start"]) if e.get("start") else datetime.combine(today, datetime.min.time())
        late = e.get("overdue") or base.date() < today
        if late and what == "1h":  # atrasada: «posponer» la trae a hoy (a su hora, si la tenía)
            nd, msg = datetime.combine(today, base.time()), "Pasada a hoy"
        elif late:
            nd, msg = datetime.combine(today + timedelta(days=1), base.time()), "Pasada a mañana"
        elif what == "1h" and not e["all_day"]:
            nd, msg = base + timedelta(hours=1), "Pospuesta 1 hora"
        else:
            nd, msg = base + timedelta(days=1), "Pasada a mañana" if what == "manana" else "Pospuesta un día"
        body = {"due_date": nd.date().isoformat()}
        if not e["all_day"]:
            body["due_time"] = nd.strftime("%H:%M")
        pc.request("PATCH", f"/api/items/{e['item_id']}", body)
        return msg
    return ""


def _poke_timer() -> None:
    try:
        import panel_contador

        panel_contador.poke()
    except Exception:  # noqa: BLE001
        pass


def submenu(e: dict) -> str | None:
    """Opciones de una línea (Intro). Devuelve la acción o None («Volver»)."""
    opts = []
    if e["kind"] in ("task", "routine"):
        opts.append(("done", f"{pa.I_DONE}  " + ("Desmarcar" if e.get("done") else "Completar") + "   <span size='small'>Alt+C</span>"))  # fmt: skip
    if e["kind"] in ("event", "task"):
        late = e.get("overdue")
        if late:
            opts.append(("1h", "  Pasar a hoy   <span size='small'>Alt+P</span>"))
        elif not e["all_day"]:
            opts.append(("1h", "  Posponer 1 hora   <span size='small'>Alt+P</span>"))
        opts.append(("manana", "  Pasar a mañana   <span size='small'>Alt+M</span>"))
    if e["kind"] in ("task", "routine") and not e.get("done"):
        opts.append(("start", f"{I_PLAY}  Empezar contador   <span size='small'>Alt+E</span>"))
    opts.append(("open", f"{pa.I_OPEN}  Abrir en el Panel   <span size='small'>Alt+O</span>"))
    if e["kind"] == "task":
        opts.append(("delete", f"<span color='{C['red']}'>{I_TRASH}  Borrar (a la papelera)</span>"))
    opts.append(("back", "  Volver"))
    if e.get("start"):
        d = pa.parse(e["start"])
        when = "todo el día" if e["all_day"] else e["start"][11:16] + (f"–{e['end'][11:16]}" if e.get("end") else "")
        sub = f"{short_date(d.date())} · {when}"
    else:
        sub = "sin fecha" if e["kind"] == "task" else ""
    j, _, _ = rofi([t for _, t in opts], f"<b>{esc(e['title'])}</b>   <span size='small'>{sub}</span>", theme="panel-confirmar.rasi")  # fmt: skip
    if j is None or j >= len(opts) or opts[j][0] == "back":
        return None
    if opts[j][0] == "delete":
        k, _, _ = rofi(["Borrar", "Cancelar"], f"¿Borrar «{esc(e['title'])}»? Se puede recuperar desde la papelera del Panel.", theme="panel-confirmar.rasi")  # fmt: skip
        return "delete" if k == 0 else None
    return opts[j][0]


# ─────────────────────────────────────────────
# Filas de cada modo
# ─────────────────────────────────────────────


def timer_state() -> tuple[dict | None, float]:
    try:
        st = pc.request("GET", "/api/contador")
    except (pc.Offline, pc.AuthError, RuntimeError):
        return None, 0.0
    import time

    return st, float(st.get("ahora", time.time())) - time.time()


def timer_row(st: dict | None, offset: float) -> tuple[str, dict | str] | None:
    import panel_contador

    if st is None:
        return None
    a = st.get("activa")
    if not a:
        return f"<span color='{C['green']}'>{I_PLAY}</span>  <b>Empezar el contador…</b>", "timer-new"
    running = a["estado"] == "marcha"
    t = panel_contador.clock(panel_contador.elapsed(a, offset))
    color = C["green"] if running else C["yellow"]
    state = "en marcha" if running else "en pausa"
    row = (f"<span color='{color}'>{I_PLAY if running else I_PAUSE}</span>  <tt><b>{t}</b></tt>  "
           f"<span color='{C['text']}'>{esc(a['titulo'])}</span>  <span color='{C['sub']}' size='small'>{state}</span>")  # fmt: skip
    return row, {"kind": "timer", **a}


def rows_hoy(data: dict, today: date, now: datetime, timer: tuple | None) -> tuple[list[str], list, list[int], list[int], int]:  # fmt: skip
    """Contador, acciones, atrasadas, hoy y mañana. (filas, qué es cada una, cabeceras, atrasadas, fila inicial)."""
    rows: list[str] = []
    what: list = []
    if timer:
        rows.append(timer[0])
        what.append(timer[1])
    rows += [
        f"<span color='{C['teal']}'>{pa.I_EDIT}</span>  <b>Capturar una tarea, idea o rutina…</b>",
        f"<span color='{C['blue']}'>{pa.I_PLUS}</span>  <b>Nuevo evento…</b>",
    ]
    what += ["capture", "new-event"]
    heads, late, sel = [], [], None
    if data.get("overdue"):
        heads.append(len(rows))
        rows.append(f"<span color='{C['red']}'><b>{pa.I_LATE}  ATRASADAS · {len(data['overdue'])}</b></span>")
        what.append(None)
        for e in data["overdue"]:
            late.append(len(rows))
            rows.append(pa.entry_line({**e, "overdue": True}, show_day=True))
            what.append({**e, "overdue": True})
    r2, w2, h2, s2 = _days(data, today, now, 2, offset=len(rows))
    rows += r2
    what += w2
    heads += h2
    sel = s2
    if sel is None:
        sel = next((n for n, w in enumerate(what) if isinstance(w, dict) and w.get("kind") != "timer"), 0)
    return rows, what, heads, late, sel


def rows_semana(data: dict, today: date, now: datetime) -> tuple[list[str], list, list[int], list[int], int]:
    rows = [f"<span color='{C['mauve']}'>{pa.I_OPEN}</span>  <b>Abrir el calendario</b>"]
    what: list = ["open-cal"]
    r2, w2, h2, sel = _days(data, today, now, 7, offset=1)
    if sel is None:
        sel = next((n for n, w in enumerate(w2, 1) if isinstance(w, dict)), 0)
    return rows + r2, what + w2, h2, [], sel


def _days(data: dict, today: date, now: datetime, n: int, offset: int) -> tuple[list[str], list, list[int], int | None]:
    entries = sorted(data["entries"], key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))
    rows, what, heads, sel = [], [], [], None
    for i in range(n):
        day = today + timedelta(days=i)
        items = [e for e in entries if pa.on_day(e, day) and (i == 0 or e["start"][:10] == day.isoformat())]
        if not items and i > 1:
            continue
        label = "HOY" if i == 0 else "MAÑANA" if i == 1 else pa.DIAS[day.weekday()].upper()
        heads.append(offset + len(rows))
        rows.append(
            f"<span color='{C['mauve']}'><b>{label}</b></span>  <span color='{C['sub']}'>{short_date(day)}</span>"
        )
        what.append(None)
        if not items:
            rows.append(f"     <span color='{C['dim']}'>Nada</span>")
            what.append(None)
        for e in items:
            if (
                sel is None
                and i == 0
                and not e.get("done")
                and (e["all_day"] or pa.parse(e["end"] or e["start"]) >= now)
            ):
                sel = offset + len(rows)
            rows.append(pa.entry_line(e))
            what.append(e)
    return rows, what, heads, sel


def task_entry(it: dict, today: date) -> dict:
    """Una tarea de /api/items o de /api/search con la forma de una línea de la agenda (para act y submenu)."""
    due, tm = it.get("due_date"), it.get("due_time")
    return {
        "kind": "task",
        "id": it["id"],
        "item_id": it["id"],
        "title": (it.get("text") or "").split("\n")[0],
        "type": it.get("type") or "tarea",
        "done": bool(it.get("done")),
        "start": f"{due}T{tm}" if due and tm else due,
        "end": None,
        "all_day": not tm,
        "overdue": bool(due and due < today.isoformat()),
    }


def search_line(e: dict) -> str:
    if e["kind"] == "note":
        cat = f"  <span color='{C['dim']}'>{esc(e.get('category') or '')}</span>" if e.get("category") else ""
        return f"  <span color='{C['mauve']}'>{I_NOTE}</span>  {esc(e['title'])}{cat}"
    if e["kind"] == "event":
        return pa.entry_line(e, show_day=True)
    color = C["red"] if e.get("overdue") else pa.KIND_COLOR.get(e["type"], C["teal"])
    when = ""
    if e.get("start"):
        d = pa.parse(e["start"])
        when = f"  <span color='{C['red'] if e.get('overdue') else C['sub']}'>{short_date(d.date())}{' ' + e['start'][11:16] if not e['all_day'] else ''}</span>"  # fmt: skip
    return f"  <span color='{color}'>{pa.ICON.get(e['type'], pa.ICON['tarea'])}</span>  {esc(e['title'][:80])}{when}"


def rows_buscar(today: date) -> tuple[list[str], list]:
    """Tareas e ideas pendientes (primero las que tienen fecha) y todas las notas, para filtrar con rofi."""
    items = pc.request("GET", "/api/items").get("items", [])
    tasks = [task_entry(i, today) for i in items if not i.get("done") and i.get("type") in ("tarea", "idea")]
    tasks.sort(key=lambda e: (not e["start"], e["start"] or "", e["title"].lower()))
    notes = [
        {"kind": "note", "id": n["id"], "title": n["title"] or n["id"], "category": n.get("category")}
        for n in pc.request("GET", "/api/notes").get("notes", [])
    ]
    what = tasks + notes
    return [search_line(e) for e in what], what


def rows_fts(q: str, today: date) -> tuple[list[str], list]:
    """Resultados de la búsqueda dentro del texto (/api/search): notas, tareas y eventos, con su fragmento."""
    from urllib.parse import quote

    res = pc.request("GET", f"/api/search?q={quote(q)}&limit=30&contexto=todo")
    rows, what = [], []

    def snip(r) -> str:
        s = " ".join((r.get("snippet") or "").split())[:160]  # 14 palabras de FTS; en una fila (rofi corta en \n)
        s += "\x03" * (s.count("\x02") - s.count("\x03"))  # que el recorte no deje una marca abierta
        s = esc(s).replace("\x02", f"<span color='{C['yellow']}'><b>").replace("\x03", "</b></span>")
        return f"   <span size='small' color='{C['sub']}'>{s}</span>" if s else ""

    for n in res.get("notes", []):
        e = {
            "kind": "note",
            "id": n["id"],
            "title": n["title"] or n["id"],
            "category": n.get("category"),
            "href": n["href"],
        }
        rows.append(search_line(e) + snip(n))
        what.append(e)
    for it in res.get("items", []):
        e = {**task_entry(it, today), "done": it.get("done")}
        rows.append(search_line(e) + snip(it))
        what.append(e)
    for ev in res.get("events", []):
        e = {"kind": "event", "id": ev["id"], "title": ev["title"], "start": ev["start"], "end": ev.get("end"),
             "all_day": bool(ev.get("all_day")), "type": "evento", "href": ev["href"]}  # fmt: skip
        rows.append(search_line(e) + snip(ev))
        what.append(e)
    return rows, what


# ─────────────────────────────────────────────
# Bucle
# ─────────────────────────────────────────────


def launch_capture(evento: bool = False) -> None:
    subprocess.Popen([str(DIR / "quick_capture.sh")] + (["--evento"] if evento else []),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip


def run_action(w: dict, how: str) -> bool:
    """Hace la acción y avisa. False si no se pudo (el menú se cierra)."""
    try:
        msg = act(w, how)
    except (pc.Offline, pc.AuthError, RuntimeError) as ex:
        pa.notify("critical", "Panel: no se pudo", str(ex))
        return False
    if msg:
        pa.notify("low", f"Panel: {msg}", w["title"], tag="panel-accion")
    pa.refresh_bar()
    return True


def timer_menu(w: dict | str, rc: int) -> None:
    import panel_contador

    if w == "timer-new":
        body = panel_contador.choose_new(None)
        if body:
            pc.request("POST", "/api/contador/empezar", body)
            panel_contador.poke()
        return
    how = KEYS[rc - 10][1] if 10 <= rc < 10 + len(KEYS) else None
    if how == "done" and w.get("tipo") != "libre":
        pc.request("POST", "/api/contador/completar")
    elif how == "start":
        pc.request("POST", "/api/contador/pausar" if w["estado"] == "marcha" else "/api/contador/seguir")
    elif how == "open" and w.get("href"):
        open_url(w["href"])
        return
    elif how is None:
        panel_contador.menu()
        return
    panel_contador.poke()


def main_loop(mode: str = "hoy") -> int:
    sel: dict[str, int] = {}
    query = ""
    fts: tuple[list[str], list] | None = None
    while True:
        if mode == "capturar":
            launch_capture()
            return 0
        data, online = pa.fetch(7)
        today, now = date.today(), datetime.now()
        heads: list[int] = []
        late: list[int] = []
        custom = False
        placeholder = None
        extra = ""
        if mode == "buscar":
            if not online:
                pa.notify("normal", "Panel sin conexión", "Buscar necesita el Panel")
                mode = "hoy"
                continue
            try:
                rows, what = fts if fts else rows_buscar(today)
            except (pc.Offline, pc.AuthError, RuntimeError) as ex:
                pa.notify("critical", "Panel: no se pudo buscar", str(ex))
                return 1
            first, custom = 0, True
            placeholder = "Filtrar tareas y notas · Ctrl+Intro: buscar dentro del texto"
            if fts:
                extra = f"\n<span size='small'>{I_SEARCH}  Dentro del texto: <b>{esc(query)}</b> · {len(rows)} resultado{'s' if len(rows) != 1 else ''} · Alt+3 vuelve a la lista</span>"  # fmt: skip
                if not rows:
                    rows, what = [f"     <span color='{C['dim']}'>Nada con «{esc(query)}»</span>"], [None]
        else:
            if not data:
                pa.notify("normal", "Panel sin conexión", "No hay agenda guardada todavía")
                return 1
            if mode == "semana":
                rows, what, heads, late, first = rows_semana(data, today, now)
            else:
                timer = timer_row(*timer_state()) if online else None
                rows, what, heads, late, first = rows_hoy(data, today, now, timer)
        i, rc, text = rofi(rows, header(mode, online, extra), selected=sel.get(mode, first), active=heads,
                           urgent=late, keys=online, modes=True, custom=custom, placeholder=placeholder)  # fmt: skip
        new_mode = mode_of(rc)
        if new_mode:
            if new_mode == "buscar" and mode == "buscar":
                fts, query = None, ""  # Alt+3 dentro de Buscar: vuelve a la lista
            mode = new_mode
            continue
        if rc == 1 or (i is None and not text):
            return 0
        if i is None:  # texto escrito (Ctrl+Intro o sin coincidencias): buscar dentro del texto
            if mode != "buscar" or not text.strip():
                return 0
            query = text.strip()
            try:
                fts = rows_fts(query, today)
            except (pc.Offline, pc.AuthError, RuntimeError) as ex:
                pa.notify("critical", "Panel: no se pudo buscar", str(ex))
                return 1
            sel["buscar"] = 0
            continue
        if i >= len(what):
            return 0
        sel[mode] = i
        w = what[i]
        if w in ("new-event", "capture"):
            launch_capture(evento=w == "new-event")
            return 0
        if w == "open-cal":
            open_url("/calendario")
            return 0
        if w == "timer-new" or (isinstance(w, dict) and w.get("kind") == "timer"):
            try:
                timer_menu(w, rc)
            except (pc.Offline, pc.AuthError, RuntimeError) as ex:
                pa.notify("critical", "Panel: no se pudo", str(ex))
                return 1
            continue
        if not isinstance(w, dict):
            continue  # cabecera o «Nada»: el menú sigue abierto
        if w["kind"] == "note":
            open_url(href(w))
            return 0
        if not online:
            continue
        how = KEYS[rc - 10][1] if 10 <= rc < 10 + len(KEYS) else submenu(w)
        if how is None:
            continue
        if not run_action(w, how):
            return 1
        if how == "open":
            return 0
        if mode == "buscar" and fts and how in ("done", "delete"):
            try:
                fts = rows_fts(query, today)
            except (pc.Offline, pc.AuthError, RuntimeError):
                fts = None


def main(argv: list[str]) -> int:
    mode = "hoy"
    if "--modo" in argv and len(argv) > argv.index("--modo") + 1:
        mode = argv[argv.index("--modo") + 1]
    if mode not in {m for _, m, _ in MODES}:
        mode = "hoy"
    # Un solo menú a la vez (como los demás scripts de rofi del sistema)
    if not os.environ.get("PANEL_ROFI"):
        subprocess.run(["pkill", "-x", "rofi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return main_loop(mode)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
