#!/usr/bin/env python3
"""
Módulo de la Waybar con el contador en marcha del Panel (P-2). Solo biblioteca estándar.

    panel_contador.py            modo continuo para la Waybar (`exec` sin `interval`): escribe una línea JSON por
                                 segundo mientras hay algo en marcha, calculada aquí con la hora de inicio; al Panel
                                 solo le pregunta cada REFRESCO segundos (con un latido: «el portátil sigue aquí») o
                                 al recibir SIGUSR1 (lo manda --toggle/--menu tras cambiar algo)
    panel_contador.py --toggle   clic: pausar / seguir (sin nada en marcha, abre el menú)
    panel_contador.py --menu     clic derecho: rofi con Pausar/Seguir, Completar, Cambiar a otra, Quitar, Abrir

Notificaciones (notify-send): al empezar algo (lo empiece quien lo empiece) y al pasar la duración prevista; una
vez por sesión, también si la Waybar se reinicia (estado en ~/.local/state/panel-maestro/contador.json).
Sin conexión, el módulo queda vacío (la Waybar lo oculta).
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_client as pc  # noqa: E402

DIR = Path(__file__).resolve().parent
REFRESCO = int(os.environ.get("PANEL_CONTADOR_REFRESCO", "30"))
PIDS = pc.STATE / "contador.pids"  # un archivo por instancia (una por barra: una por monitor)
VISTO = pc.STATE / "contador.json"  # {"empezada": id, "pasada": id}: lo ya notificado
I_PLAY, I_PAUSE, I_WARN = "", "", ""
KIND = {"tarea": "Tarea", "idea": "Idea", "rutina": "Rutina", "paso": "Paso", "libre": "Actividad libre"}


def esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clock(sec: int) -> str:
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def short(t: str, n: int = 28) -> str:
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def elapsed(a: dict, offset: float, now: float | None = None) -> int:
    """Segundos de la sesión: los tramos cerrados más el abierto, con el reloj del Panel (`offset`)."""
    now = (time.time() if now is None else now) + offset
    return max(0, int(a["segundos"] + (now - a["tramo_inicio"] if a.get("tramo_inicio") else 0)))


def render(state: dict | None, offset: float = 0.0, now: float | None = None) -> dict:
    """Lo que pinta la Waybar: texto, tooltip y clase (marcha, pausa, pasado, vacio, sin-conexion)."""
    if state is None:
        return {"text": "", "tooltip": "Panel sin conexión", "class": ["sin-conexion"]}
    a = state.get("activa")
    if not a:
        return {"text": "", "tooltip": "Nada en marcha", "class": ["vacio"]}
    sec = elapsed(a, offset, now)
    running = a["estado"] == "marcha"
    over = bool(a.get("prevista_min") and sec > a["prevista_min"] * 60)
    icon = I_WARN if over else (I_PLAY if running else I_PAUSE)
    cls = ["marcha" if running else "pausa"] + (["pasado"] if over else [])
    sub = [f"Paso de «{a['padre']}»" if a.get("padre") else KIND.get(a["tipo"], a["tipo"])]
    if a.get("prevista_min"):
        sub.append(f"{a['prevista_min']} min previstos")
    if not running:
        sub.append("en pausa")
    tip = (
        f"<b>{esc(a['titulo'])}</b>\n{esc(' · '.join(sub))}\n\n"
        "Clic: pausar / seguir · Clic derecho: completar, cambiar, quitar"
    )
    return {"text": f"{icon}  {clock(sec)}  {esc(short(a['titulo']))}", "tooltip": tip, "class": cls, "alt": cls[0]}


def fetch(beat: bool) -> tuple[dict | None, float]:
    """(estado, desfase con el reloj del Panel). Con `beat`, el latido de «sigo aquí» (solo si algo está en marcha)."""
    try:
        st = pc.request("POST", "/api/contador/latido") if beat else pc.request("GET", "/api/contador")
    except (pc.Offline, pc.AuthError, RuntimeError):
        return None, 0.0
    return st, float(st.get("ahora", time.time())) - time.time()


def notify(urgency: str, title: str, body: str) -> None:
    subprocess.run(
        [os.environ.get("PANEL_NOTIFY", "notify-send"), "-a", "Panel", "-u", urgency, "-i", "chronometer", title, body],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _visto() -> dict:
    try:
        return json.loads(VISTO.read_text())
    except (OSError, ValueError):
        return {}


def notices(state: dict | None, offset: float = 0.0, now: float | None = None) -> list[str]:
    """Notifica (una vez por sesión) al empezar y al pasar la duración prevista. Devuelve lo notificado."""
    a = (state or {}).get("activa")
    if not a:
        return []
    seen, out = _visto(), []
    if seen.get("empezada") != a["id"]:
        seen["empezada"] = a["id"]
        out.append("empezada")
        notify(
            "low", f"En marcha: {a['titulo']}", f"{a['prevista_min']} min previstos" if a.get("prevista_min") else ""
        )
    if a.get("prevista_min") and seen.get("pasada") != a["id"] and elapsed(a, offset, now) > a["prevista_min"] * 60:
        seen["pasada"] = a["id"]
        out.append("pasada")
        notify("normal", f"Pasaste los {a['prevista_min']} min previstos", a["titulo"])
    if out:
        pc.STATE.mkdir(parents=True, exist_ok=True)
        VISTO.write_text(json.dumps(seen))
    return out


# ─────────────────────────────────────────────
# Modo continuo (Waybar)
# ─────────────────────────────────────────────

_despierta = False


def _on_usr1(*_):
    global _despierta
    _despierta = True


def run(max_lines: int | None = None, sleep=time.sleep) -> None:
    """Bucle de la Waybar. `max_lines` y `sleep` solo para los tests."""
    global _despierta
    signal.signal(signal.SIGUSR1, _on_usr1)
    pc.STATE.mkdir(parents=True, exist_ok=True)
    PIDS.mkdir(parents=True, exist_ok=True)
    (PIDS / str(os.getpid())).touch()
    state, offset, last_fetch, last_line, lines = None, 0.0, 0.0, None, 0
    while max_lines is None or lines < max_lines:
        if _despierta or time.monotonic() - last_fetch >= REFRESCO or not last_fetch:
            beat = bool(state and (state.get("activa") or {}).get("estado") == "marcha")
            state, offset = fetch(beat)
            last_fetch, _despierta = time.monotonic(), False
            try:
                notices(state, offset)
            except OSError:
                pass
        out = render(state, offset)
        line = json.dumps(out, ensure_ascii=False)
        if line != last_line:  # en pausa o sin nada, no se repite la misma línea
            print(line, flush=True)
            last_line = line
            lines += 1
        sleep(1)


def _es_modulo(pid: int) -> bool:
    """Que ese pid siga siendo un módulo del contador (un pid viejo puede ser ya de otro programa)."""
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(c.endswith(b"panel_contador.py") for c in cmd) and not any(c.startswith(b"--") for c in cmd)


def poke() -> None:
    """Avisa a los módulos de la Waybar (uno por barra) de que algo cambió: SIGUSR1, se ponen al día sin esperar.
    Los pids que ya no son un módulo se olvidan."""
    try:
        files = list(PIDS.iterdir())
    except OSError:
        return
    for f in files:
        pid = int(f.name) if f.name.isdigit() else 0
        if pid and _es_modulo(pid):
            try:
                os.kill(pid, signal.SIGUSR1)
                continue
            except OSError:
                pass
        f.unlink(missing_ok=True)


# ─────────────────────────────────────────────
# Clic y menú
# ─────────────────────────────────────────────


def toggle() -> int:
    st, _ = fetch(False)
    a = (st or {}).get("activa")
    if not a:
        return menu()
    try:
        pc.request("POST", "/api/contador/pausar" if a["estado"] == "marcha" else "/api/contador/seguir")
    except (pc.Offline, pc.AuthError, RuntimeError) as e:
        notify("critical", "Panel: no se pudo", str(e))
        return 1
    poke()
    return 0


def rofi(lines: list[str], mesg: str, custom: bool = False) -> tuple[int | None, str]:
    """(fila elegida o None, texto escrito si no coincide con ninguna fila)."""
    cmd = [os.environ.get("PANEL_ROFI", "rofi"), "-dmenu", "-i", "-format", "i|s", "-markup-rows",
           "-config", str(DIR / "rofi" / "panel-agenda.rasi"), "-mesg", mesg, "-p", ""]  # fmt: skip
    if not custom:
        cmd.append("-no-custom")
    proc = subprocess.run(cmd, input="\n".join(lines), capture_output=True, text=True, check=False)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        return None, ""
    idx, _, text = out.partition("|")
    return (int(idx) if idx.lstrip("-").isdigit() and int(idx) >= 0 else None), text


def candidates() -> list[dict]:
    """Lo que se puede empezar: tareas y rutinas de hoy sin hacer y las atrasadas (la agenda de la Waybar)."""
    try:
        ag = pc.request("GET", "/api/calendar/agenda?days=1&contexto=waybar")
    except (pc.Offline, pc.AuthError, RuntimeError):
        return []
    seen, out = set(), []
    for e in (ag.get("overdue") or []) + (ag.get("entries") or []):
        if e["kind"] == "event" or e.get("done") or not e.get("item_id") or e["item_id"] in seen:
            continue
        seen.add(e["item_id"])
        out.append(e)
    return out


def choose_new(current: dict | None) -> dict | None:
    """Rofi para elegir qué empezar; escribir algo que no está en la lista = actividad libre."""
    opts = [e for e in candidates() if not current or e["item_id"] != current.get("item_id")]
    rows = [f"{I_PLAY}  {esc(e['title'])}" + ("  <span size='small'>(atrasada)</span>" if e.get("overdue") else "")
            for e in opts]  # fmt: skip
    i, text = rofi(rows, "<b>Empezar</b>: elige o escribe una actividad libre", custom=True)
    if i is not None and i < len(opts):
        return {"item_id": opts[i]["item_id"]}
    if text.strip():
        return {"titulo": text.strip()[:200]}
    return None


def menu() -> int:
    st, offset = fetch(False)
    if st is None:
        notify("normal", "Panel sin conexión", "No se puede usar el contador ahora")
        return 1
    a = st.get("activa")
    opts: list[tuple[str, str]] = []
    if a:
        running = a["estado"] == "marcha"
        opts.append(
            (
                "pausar" if running else "seguir",
                f"{I_PAUSE if running else I_PLAY}  {'Pausar' if running else 'Seguir'}",
            )
        )
        if a["tipo"] != "libre":
            opts.append(("completar", "  Completar"))
        opts += [("cambiar", "  Cambiar a otra…"), ("quitar", "  Quitar (el tiempo se guarda)")]
        if a.get("href"):
            opts.append(("abrir", "  Abrir en el Panel"))
        mesg = f"<b>{esc(a['titulo'])}</b>  ·  {clock(elapsed(a, offset))}"
    else:
        opts.append(("cambiar", f"{I_PLAY}  Empezar…"))
        mesg = "Nada en marcha"
    i, _ = rofi([t for _, t in opts], mesg)
    if i is None or i >= len(opts):
        return 0
    what = opts[i][0]
    try:
        if what in ("pausar", "seguir", "completar", "quitar"):
            pc.request("POST", f"/api/contador/{what}")
        elif what == "cambiar":
            body = choose_new(a)
            if not body:
                return 0
            pc.request("POST", "/api/contador/empezar", body)
        elif what == "abrir":
            subprocess.Popen(
                ["xdg-open", pc.base_url() + a["href"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except (pc.Offline, pc.AuthError, RuntimeError) as e:
        notify("critical", "Panel: no se pudo", str(e))
        return 1
    poke()
    return 0


def main(argv: list[str]) -> int:
    if "--toggle" in argv:
        return toggle()
    if "--menu" in argv:
        return menu()
    try:
        run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
