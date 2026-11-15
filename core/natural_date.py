"""
Fechas y horas en lenguaje natural (español, Europe/Madrid) para crear eventos
escribiendo, p. ej. en la captura rápida «e: dentista mañana 17:00».

    parse_event("examen de SO 3 nov 9:00 2h", now)
    → {"ok": True, "title": "Examen de SO", "start": datetime(…9:00), "end": …11:00,
       "all_day": False, "duration_min": 120, "matched": [...]}

Entiende:
  día     hoy, mañana, pasado mañana, (el|este|el próximo) lunes…domingo, «lunes que
          viene», dentro de/en N días|semanas, 3 nov, 3 de noviembre (de 2026), 3/11,
          3/11/2026, 2026-11-03, «el 15»
  hora    17:00, 17.30, 17h, a las 5, a las 5 de la tarde, 9 y media, mediodía,
          «dentro de 2 horas» / «en 30 minutos» (fija día y hora)
  duración 2h, 1h30, 90 min, durante 2 horas, «de 10 a 12» (rango), «10-12»
Sin hora → evento de todo el día. Sin duración → 1 hora.

Si algo no se puede interpretar con seguridad (no hay ningún día, la fecha no existe,
hay dos fechas distintas, «a las 25»…) devuelve ok=False con el motivo: quien llama
NO debe inventarse la fecha (la captura lo deja en el Inbox marcado «revisar fecha»).
"""

import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
DEFAULT_MIN = 60

WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
MONTHS = {
    "ene": 1,
    "enero": 1,
    "feb": 2,
    "febrero": 2,
    "mar": 3,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "may": 5,
    "mayo": 5,
    "jun": 6,
    "junio": 6,
    "jul": 7,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "sep": 9,
    "sept": 9,
    "septiembre": 9,
    "setiembre": 9,
    "oct": 10,
    "octubre": 10,
    "nov": 11,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}
NUMBERS = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
    "media": 0.5,
}


def _fold(s: str) -> str:
    """Minúsculas y sin tildes, conservando la longitud (para cortar el texto original)."""
    out = []
    for ch in s:
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower() if len(base) == 1 else ch.lower())
    return "".join(out)


NUM = r"(\d+(?:[.,]\d+)?|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|quince|veinte|treinta|media)"
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
# Abreviaturas de los días («vie 10:00»); «mar» no, que también es marzo
WD_ABBR = {"lun": 0, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}
WD_RE = "|".join([*WEEKDAYS, *WD_ABBR])

# (nombre, patrón) en orden: los más largos primero para que no se pisen
PATTERNS = [
    ("rel_time", rf"\b(?:dentro de|en) {NUM} (horas?|h|minutos?|mins?|min)\b"),
    ("rel_days", rf"\b(?:dentro de|en) {NUM} (dias?|semanas?)\b"),
    ("pasado", r"\bpasado manana\b"),
    ("iso", r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    ("dmy", r"\b(?:el )?(\d{1,2})([/-])(\d{1,2})(?:\2(\d{2,4}))?\b"),
    ("dmon", rf"\b(?:el )?(\d{{1,2}}) (?:de )?({MONTH_RE})\.?(?:,? (?:de |del )?(\d{{4}}))?\b"),
    (
        "range",
        r"\b(?:de|desde las?) (\d{1,2})(?:[:.h](\d{2}))? (?:a|hasta) (?:las? )?(\d{1,2})(?:[:.h](\d{2}))?(?: ?h)?\b",
    ),
    ("range2", r"\b(\d{1,2})(?::(\d{2}))? ?- ?(\d{1,2})(?::(\d{2}))?\b"),
    ("weekday", rf"\b(?:(?:el|este) (?:proximo |siguiente )?|proximo |el )?({WD_RE})(?: que viene| proximo)?\b"),
    ("hoy", r"\bhoy\b"),
    ("manana_day", r"(?<!de la )(?<!por la )\bmanana\b"),
    ("dur", rf"\b(?:durante )?(\d+)h(\d{{1,2}})\b|\b(?:durante )?{NUM} ?(horas?|h|minutos?|mins?|min|m)\b"),
    (
        "clock",
        r"\b(?:a las? |sobre las? |a eso de las )?(\d{1,2})(?:[:.](\d{2})| ?h(?:oras)?\b)( (?:de la (?:manana|tarde|noche)|por la (?:manana|tarde|noche)))?",
    ),
    (
        "at",
        r"\b(?:a las?|sobre las?|a eso de las) (\d{1,2})(?: y (media|cuarto)| menos cuarto)?( (?:de la (?:manana|tarde|noche)|por la (?:manana|tarde|noche)|en punto))?\b",
    ),
    ("noon", r"\b(?:a )?mediodia\b"),
    ("day_of_month", r"\bel (?:dia )?(\d{1,2})\b"),
]
COMPILED = [(n, re.compile(p)) for n, p in PATTERNS]
FILLER = re.compile(r"(?:^|\s)(?:el|la|los|las|a|de|del|en|para|por|con)(?=\s*$)")


def _num(tok: str) -> float:
    tok = tok.replace(",", ".")
    return NUMBERS[tok] if tok in NUMBERS else float(tok)


def _pm(hour: int, part: str | None) -> int:
    part = part or ""
    if ("tarde" in part or "noche" in part) and hour < 12:
        return hour + 12
    if "manana" in part and hour == 12:
        return 0
    return hour


def _next_weekday(today: date, wd: int, explicit_next: bool) -> date:
    delta = (wd - today.weekday()) % 7
    if delta == 0:
        delta = 7 if explicit_next else 0
    return today + timedelta(days=delta)


def _clean_title(original: str, spans: list[tuple[int, int]]) -> str:
    chars = list(original)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    title = re.sub(r"\s+", " ", "".join(chars)).strip(" ,.-·")
    # conectores que quedan colgando al quitar la fecha («dentista el», «reunión a las»)
    for _ in range(3):
        stripped = re.sub(r"\s+(?:el|la|los|las|a|de|del|en|para|por|con|y|desde|hasta)$", "", title, flags=re.I).strip(
            " ,.-·"
        )
        if stripped == title:
            break
        title = stripped
    return title[:1].upper() + title[1:] if title else title


def _mkdate(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


class _Lectura:
    """Lo que se va entendiendo del texto: trozos ya usados, día (y todos los días vistos), hora de inicio y de
    fin, duración y lo que no cuadra. Cada patrón lo lee un `_lector_*`; el resultado lo arma `_resultado`."""

    def __init__(self, now: datetime, folded: str):
        self.now = now
        self.today = now.date()
        self.taken = [False] * len(folded)
        self.spans: list[tuple[int, int]] = []
        self.matched: list[str] = []
        self.day: date | None = None
        self.days: set[date] = set()
        self.start_t: time | None = None
        self.end_t: time | None = None
        self.duration: int | None = None
        self.problems: list[str] = []

    def free(self, m: re.Match) -> bool:
        return not any(self.taken[m.start() : m.end()])

    def take(self, m: re.Match, name: str) -> None:
        for i in range(m.start(), m.end()):
            self.taken[i] = True
        self.spans.append((m.start(), m.end()))
        self.matched.append(f"{name}:{m.group(0).strip()}")

    def set_day(self, d: date | None, why: str) -> None:
        if d is None:
            self.problems.append(f"fecha imposible ({why})")
            return
        self.days.add(d)
        self.day = d

    def set_time(self, h: int, mi: int, why: str) -> None:
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            self.problems.append(f"hora imposible ({why})")
            return
        if self.start_t is not None and self.start_t != time(h, mi):
            self.problems.append("hay dos horas distintas")
            return
        self.start_t = time(h, mi)


# Cada lector recibe los grupos del patrón; devuelve False si el trozo no cuenta (queda libre para otro patrón)
def _lector_rel_time(st: _Lectura, g: tuple, m: re.Match) -> bool:
    n, unit = _num(g[0]), g[1]
    minutes = n * 60 if unit.startswith("h") else n
    exact = (st.now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    st.set_day(exact.date(), m.group(0))
    st.set_time(exact.hour, exact.minute, m.group(0))
    return True


def _lector_rel_days(st: _Lectura, g: tuple, m: re.Match) -> bool:
    n, unit = _num(g[0]), g[1]
    st.set_day(st.today + timedelta(days=int(n * (7 if unit.startswith("semana") else 1))), m.group(0))
    return True


def _lector_pasado(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_day(st.today + timedelta(days=2), m.group(0))
    return True


def _lector_iso(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_day(_mkdate(int(g[0]), int(g[1]), int(g[2])), m.group(0))
    return True


def _lector_dmy(st: _Lectura, g: tuple, m: re.Match) -> bool:
    if g[1] == "-" and not g[3]:
        return False  # «10-12» puede ser un rango de horas: sin año no es fecha
    y = int(g[3]) if g[3] else st.today.year
    if y < 100:
        y += 2000
    d = _mkdate(y, int(g[2]), int(g[0]))
    if d and not g[3] and d < st.today - timedelta(days=60):
        d = _mkdate(y + 1, int(g[2]), int(g[0]))  # «3/1» en noviembre = enero que viene
    st.set_day(d, m.group(0))
    return True


def _lector_dmon(st: _Lectura, g: tuple, m: re.Match) -> bool:
    y = int(g[2]) if g[2] else st.today.year
    d = _mkdate(y, MONTHS[g[1]], int(g[0]))
    if d and not g[2] and d < st.today - timedelta(days=60):
        d = _mkdate(y + 1, MONTHS[g[1]], int(g[0]))
    st.set_day(d, m.group(0))
    return True


def _lector_rango(st: _Lectura, g: tuple, m: re.Match, sin_minutos_vale: bool) -> bool:
    h1, m1, h2, m2 = int(g[0]), int(g[1] or 0), int(g[2]), int(g[3] or 0)
    if not sin_minutos_vale and not (g[1] or g[3]):
        return False  # «10-12» sin minutos es ambiguo (¿horas o fecha?)
    if h2 < h1 and h2 < 12:
        h2 += 12  # «de 10 a 1»
    if not (0 <= h1 <= 23 and 0 <= h2 <= 24):
        st.problems.append(f"hora imposible ({m.group(0)})")
    else:
        st.set_time(h1, m1, m.group(0))
        st.end_t = time(h2 % 24, m2)
    return True


def _lector_weekday(st: _Lectura, g: tuple, m: re.Match) -> bool:
    # «el viernes» dicho un viernes es el de la semana que viene; «este viernes», hoy
    explicit = not m.group(0).startswith("este ")
    st.set_day(_next_weekday(st.today, WEEKDAYS.get(g[0], WD_ABBR.get(g[0], 0)), explicit), m.group(0))
    return True


def _lector_hoy(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_day(st.today, m.group(0))
    return True


def _lector_manana(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_day(st.today + timedelta(days=1), m.group(0))
    return True


def _lector_dur(st: _Lectura, g: tuple, m: re.Match) -> bool:
    if g[0]:
        st.duration = int(g[0]) * 60 + int(g[1])
        return True
    n, unit = _num(g[2]), g[3]
    if unit.startswith("h") and n > 6 and "durante" not in m.group(0):
        return False  # «17h» es una hora del día, no una duración
    st.duration = int(round(n * 60 if unit.startswith("h") else n))
    return True


def _lector_clock(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_time(_pm(int(g[0]), g[2]), int(g[1] or 0), m.group(0))
    return True


def _lector_at(st: _Lectura, g: tuple, m: re.Match) -> bool:
    h = int(g[0])
    mi = 30 if g[1] == "media" else 15 if g[1] == "cuarto" else 0
    if "menos cuarto" in m.group(0):
        h, mi = h - 1, 45
    if not g[2] and 1 <= h <= 7:
        h += 12  # «a las 5» es por la tarde salvo que diga lo contrario
    st.set_time(_pm(h, g[2]), mi, m.group(0))
    return True


def _lector_noon(st: _Lectura, g: tuple, m: re.Match) -> bool:
    st.set_time(12, 0, m.group(0))
    return True


def _lector_day_of_month(st: _Lectura, g: tuple, m: re.Match) -> bool:
    today = st.today
    d = _mkdate(today.year, today.month, int(g[0]))
    if d and d < today:
        nm = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        d = _mkdate(nm.year, nm.month, int(g[0]))
    st.set_day(d, m.group(0))
    return True


LECTORES: dict[str, Callable[[_Lectura, tuple, re.Match], bool]] = {
    "rel_time": _lector_rel_time,
    "rel_days": _lector_rel_days,
    "pasado": _lector_pasado,
    "iso": _lector_iso,
    "dmy": _lector_dmy,
    "dmon": _lector_dmon,
    "range": lambda st, g, m: _lector_rango(st, g, m, sin_minutos_vale=True),
    "range2": lambda st, g, m: _lector_rango(st, g, m, sin_minutos_vale=False),
    "weekday": _lector_weekday,
    "hoy": _lector_hoy,
    "manana_day": _lector_manana,
    "dur": _lector_dur,
    "clock": _lector_clock,
    "at": _lector_at,
    "noon": _lector_noon,
    "day_of_month": _lector_day_of_month,
}


def _leer(folded: str, now: datetime) -> _Lectura:
    """Pasa los patrones en orden (los largos antes); cada trozo del texto lo usa como mucho uno."""
    st = _Lectura(now, folded)
    for name, rx in COMPILED:
        lector = LECTORES.get(name)
        for m in rx.finditer(folded):
            if not st.free(m) or lector is None:
                continue
            if lector(st, m.groups(), m):
                st.take(m, name)
    return st


def _resultado(st: _Lectura, title: str) -> dict:
    """ok=False con el motivo si algo no cuadra; si no, inicio y fin (todo el día si no hay hora)."""
    out = {
        "title": title,
        "matched": st.matched,
        "ok": False,
        "reason": None,
        "start": None,
        "end": None,
        "all_day": False,
        "duration_min": None,
    }
    if len(st.days) > 1:
        st.problems.append("hay dos fechas distintas")
    if st.problems:
        out["reason"] = "; ".join(st.problems)
        return out
    if st.day is None:
        out["reason"] = "no dice qué día"
        return out
    if not title:
        out["reason"] = "falta el título"
        return out
    day = st.day
    if st.start_t is None:
        out.update(
            ok=True,
            all_day=True,
            start=datetime.combine(day, time(0), TZ),
            end=datetime.combine(day + timedelta(days=1), time(0), TZ),
        )
        return out
    start = datetime.combine(day, st.start_t, TZ)
    if st.end_t is not None:
        end = datetime.combine(day, st.end_t, TZ)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + timedelta(minutes=st.duration or DEFAULT_MIN)
    out.update(ok=True, start=start, end=end, duration_min=int((end - start).total_seconds() // 60))
    return out


def parse_event(text: str, now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    original = text.strip()
    st = _leer(_fold(original), now)
    return _resultado(st, _clean_title(original, st.spans))


def describe(parsed: dict) -> str:
    """«martes 3 nov · 9:00–11:00» para vistas previas y notificaciones."""
    if not parsed.get("ok"):
        return "Fecha sin interpretar"
    s, e = parsed["start"], parsed["end"]
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    d = f"{dias[s.weekday()]} {s.day} {meses[s.month - 1]}" + (f" {s.year}" if s.year != datetime.now(TZ).year else "")
    if parsed["all_day"]:
        return f"{d} · todo el día"
    return f"{d} · {s:%H:%M}–{e:%H:%M}"
