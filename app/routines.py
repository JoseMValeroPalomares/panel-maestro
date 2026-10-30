"""
Rutinas (hábitos): un tipo más de la lista única (inbox.item_type = 'rutina') con una regla
de repetición en `inbox.repeat` (JSON) y un registro de días hechos (`routine_checks`).

    {"freq": "daily"}                                  todos los días
    {"freq": "weekly", "days": [0, 2, 4]}              lunes, miércoles y viernes (0 = lunes)
    {"freq": "interval", "every": 3, "from": "2026-10-24"}   cada 3 días desde esa fecha

Marcar una rutina es marcarla «hecha hoy» (o el día que se diga, desde el calendario); su
casilla en la lista refleja el día de hoy.

Pasos («bloques» del día): una rutina tiene pasos en orden (filas hijas, también de tipo rutina), cada
uno con su duración opcional, una hora fija opcional (`due_time`: «Universidad a las 8:30») y, si se
quiere, sus propios días (`repeat` semanal: «solo de lunes a viernes»); sin días propios, siguen los de su
rutina. Así una rutina «Mi día» cambia según el día. Un paso se marca por días igual que la rutina; con
todos los pasos de ese día hechos la rutina queda hecha, y marcar la rutina marca los de ese día.
Horario: cada paso empieza a su hora fija o, si no tiene, cuando acaba el anterior (desde la hora de la
rutina). Solo la rutina cuenta para la racha y el historial. Las tareas e ideas pueden ir asociadas a una
rutina o a uno de sus pasos (`inbox.routine_step`): se ven dentro del bloque. Racha = ocurrencias seguidas hechas hasta hoy (si
hoy toca y aún no está hecha, no rompe la racha). Cada marca va también a `item_log`
(historial de la revisión semanal).
"""
import json
import re
import time
from datetime import date, timedelta

from fastapi import HTTPException

WEEKDAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def clean_repeat(v):
    """Valida y normaliza la regla; None = sin regla (se trata como diaria)."""
    if v in (None, "", {}):
        return None
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise ValueError("La repetición no es válida")
    if not isinstance(v, dict) or v.get("freq") not in ("daily", "weekly", "interval"):
        raise ValueError("La repetición es diaria, por días de la semana o cada N días")
    if v["freq"] == "daily":
        return {"freq": "daily"}
    if v["freq"] == "weekly":
        days = sorted({int(d) for d in v.get("days") or [] if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6})
        if not days:
            raise ValueError("Elige al menos un día de la semana")
        return {"freq": "weekly", "days": days}
    every = int(v.get("every") or 0)
    if not 1 <= every <= 365:
        raise ValueError("«Cada N días» va de 1 a 365")
    start = v.get("from") or date.today().isoformat()
    try:
        start = date.fromisoformat(start).isoformat()
    except ValueError:
        raise ValueError("La fecha de inicio va como AAAA-MM-DD")
    return {"freq": "interval", "every": every, "from": start}


def parse(raw) -> dict:
    try:
        return clean_repeat(raw) or {"freq": "daily"}
    except ValueError:
        return {"freq": "daily"}


def occurs_on(rule: dict, day: date, since: date | None = None) -> bool:
    if since and day < since:
        return False
    f = rule.get("freq", "daily")
    if f == "weekly":
        return day.weekday() in rule.get("days", [])
    if f == "interval":
        start = date.fromisoformat(rule.get("from") or day.isoformat())
        return day >= start and (day - start).days % max(1, int(rule.get("every", 1))) == 0
    return True


def describe(rule: dict) -> str:
    f = rule.get("freq", "daily")
    if f == "weekly":
        days = rule.get("days", [])
        if days == [0, 1, 2, 3, 4]:
            return "De lunes a viernes"
        if days == [5, 6]:
            return "Fines de semana"
        plural = lambda n: n + "s" if n.endswith("o") else n  # noqa: E731  (sábados, domingos; lunes no cambia)
        return "Los " + ", ".join(plural(WEEKDAY_NAMES[d]) for d in days)
    if f == "interval":
        n = rule.get("every", 1)
        return "Cada día" if n == 1 else f"Cada {n} días"
    return "Cada día"


def checks(conn, item_id: int, since: date | None = None) -> set[str]:
    q = "SELECT day FROM routine_checks WHERE item_id=?" + (" AND day >= ?" if since else "")
    return {r["day"] for r in conn.execute(q, (item_id, since.isoformat()) if since else (item_id,))}


def created_day(row) -> date:
    try:
        return date.fromtimestamp(row["created_at"] or time.time())
    except (OverflowError, OSError, ValueError):
        return date.today()


def streak(rule: dict, done: set[str], today: date, since: date) -> dict:
    """Racha actual y la mejor, en ocurrencias seguidas hechas. Hoy sin hacer no rompe la actual."""
    best = run = 0
    d = since
    while d <= today:
        if occurs_on(rule, d, since):
            if d.isoformat() in done:
                run += 1
                best = max(best, run)
            elif d != today:
                run = 0
        d += timedelta(days=1)
    cur = 0
    d = today
    while d >= since:
        if occurs_on(rule, d, since):
            if d.isoformat() in done:
                cur += 1
            elif d != today:
                break
        d -= timedelta(days=1)
    return {"actual": cur, "mejor": max(best, cur)}


def heatmap(rule: dict, done: set[str], today: date, since: date, weeks: int = 12) -> list[dict]:
    """Días de las últimas `weeks` semanas (de lunes a hoy): done | missed | off | future."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    out = []
    d = start
    end = start + timedelta(days=7 * weeks - 1)
    while d <= end:
        if d > today:
            st = "future"
        elif not occurs_on(rule, d, since):
            st = "off"
        elif d.isoformat() in done:
            st = "done"
        else:
            st = "pending" if d == today else "missed"
        out.append({"day": d.isoformat(), "state": st})
        d += timedelta(days=1)
    return out


def set_check(conn, row, day: date, done: bool, rule: dict | None = None, log_it: bool = True) -> None:
    rule = rule or parse(row["repeat"])
    if done and not occurs_on(rule, day, created_day(row) - timedelta(days=3650)):
        raise HTTPException(status_code=422, detail="Esa rutina no toca ese día")
    was = conn.execute("SELECT 1 FROM routine_checks WHERE item_id=? AND day=?", (row["id"], day.isoformat())).fetchone() is not None
    if done:
        conn.execute("INSERT OR IGNORE INTO routine_checks (item_id, day, at) VALUES (?, ?, ?)", (row["id"], day.isoformat(), time.time()))
    else:
        conn.execute("DELETE FROM routine_checks WHERE item_id=? AND day=?", (row["id"], day.isoformat()))
    if log_it and was != done:
        log(conn, row, "check" if done else "uncheck", day)


def steps_of(conn, routine_id: int) -> list:
    return conn.execute("SELECT * FROM inbox WHERE parent_id=? ORDER BY sort_order DESC, created_at DESC", (routine_id,)).fetchall()


def step_rule(step) -> dict | None:
    """Días propios de un paso (o None: los de su rutina). Solo cuentan los días de la semana: una regla
    diaria en un paso (la dejaban versiones antiguas al moverlo) equivale a no tener días propios."""
    rule = clean_repeat(step["repeat"]) if step["repeat"] else None
    return rule if rule and rule.get("freq") == "weekly" else None


def step_on(step, day: date) -> bool:
    rule = step_rule(step)
    return rule is None or occurs_on(rule, day)


def steps_on(conn, routine_id: int, day: date) -> list:
    return [s for s in steps_of(conn, routine_id) if step_on(s, day)]


def check_with_steps(conn, row, day: date, done: bool) -> None:
    """Marca una rutina o uno de sus pasos y deja los dos lados de acuerdo (ese día)."""
    if row["parent_id"] is not None:  # un paso: sigue la regla de su rutina (y la suya, si la tiene)
        parent = conn.execute("SELECT * FROM inbox WHERE id=?", (row["parent_id"],)).fetchone()
        rule = parse(parent["repeat"])
        if done and not step_on(row, day):
            raise HTTPException(status_code=422, detail="Ese paso no toca ese día")
        set_check(conn, row, day, done, rule=rule, log_it=False)
        steps = steps_on(conn, parent["id"], day)
        all_done = bool(steps) and all(day.isoformat() in checks(conn, s["id"], since=day) for s in steps)
        parent_done = day.isoformat() in checks(conn, parent["id"], since=day)
        if all_done != parent_done:
            set_check(conn, parent, day, all_done, rule=rule)
        return
    rule = parse(row["repeat"])
    set_check(conn, row, day, done, rule=rule)
    for s in steps_on(conn, row["id"], day):
        set_check(conn, s, day, done, rule=rule, log_it=False)


def _mins(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return h * 60 + m


def _hhmm(t: int) -> str:
    return f"{t // 60 % 24:02d}:{t % 60:02d}"


def schedule(start: str | None, steps: list[dict]) -> list[dict]:
    """Hora de cada paso: su hora fija (`due_time`) o, si no, cuando acaba el anterior, empezando por la
    hora de la rutina. `end` solo si se sabe la duración. Sin ninguna hora, no hay horario."""
    out, t = [], _mins(start)
    for s in steps:
        fixed = _mins(s.get("due_time"))
        if fixed is not None:
            t = fixed
        dur = s.get("duration_min") or 0
        out.append({**s, "at": _hhmm(t) if t is not None else None, "end": _hhmm(t + dur) if t is not None and dur else None,
                    "fixed": fixed is not None})
        if t is not None:
            t += dur
    return out


DURATION_RE = re.compile(r"\s*[·,-]?\s*\(?(\d{1,3})\s*(min|mins|minutos|m|h|horas?)\)?\s*$", re.I)


def split_duration(text: str) -> tuple[str, int | None]:
    """«Ducha 10 min» → («Ducha», 10); «Estudiar 1h» → («Estudiar», 60). Sin duración, (texto, None)."""
    m = DURATION_RE.search(text)
    if not m or not text[:m.start()].strip():
        return text.strip(), None
    n = int(m.group(1)) * (60 if m.group(2).lower().startswith("h") else 1)
    return text[:m.start()].strip(), n if 1 <= n <= 1440 else None


def log(conn, row, action: str, day: date | None = None) -> None:
    """Historial de completados (revisión semanal)."""
    from app.items import clean_text, item_type
    conn.execute("INSERT INTO item_log (item_id, action, day, text, type, at) VALUES (?, ?, ?, ?, ?, ?)",
                 (row["id"], action, (day or date.today()).isoformat(), clean_text(row["content"])[:500], item_type(row), time.time()))
