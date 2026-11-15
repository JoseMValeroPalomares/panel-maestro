"""
Captura rápida con prefijos (escritorio con rofi, la app y la extensión usan lo mismo).

    algo           → Inbox, tarea sin clasificar
    t: algo        → tarea          i: algo → idea
                     con fecha si la lleva clara («t: llamar a Juan el viernes», «t: pagar la luz mañana a las 10»);
                     si no hay fecha o no está clara, se guarda el texto tal cual (nunca se inventa)
    r: algo        → rutina («r: gimnasio lunes y jueves a las 19», «r: leer cada día»)
    e: algo        → evento en lenguaje natural («e: dentista mañana 17:00», «e: examen 3 nov 9:00 2h»)
    g: 4,50 café   → gasto en Economía (importe y concepto; la categoría se adivina por palabras clave
                     y va a la primera cuenta). Sin importe claro, al Inbox para revisarlo

Menciones (app/contextos.py): «@gabd» lleva el elemento a esa asignatura y «#panel-maestro» a ese
proyecto (con «v0.3», a esa versión). Una mención que no existe NO se crea en silencio: la captura
devuelve error con el aviso y no guarda nada.

Un evento que no se entiende con seguridad NO se inventa: va al Inbox como tarea con la categoría
«Revisar fecha» y el motivo en sus notas. `dry_run` devuelve la vista previa sin guardar nada.
"""

import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.natural_date import WEEKDAYS, _fold, describe, parse_event

router = APIRouter(prefix="/api")
PREFIX_RE = re.compile(r"^\s*([tireg])\s*:\s*", re.I)
REVISAR = "Revisar fecha"


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    dry_run: bool = False
    # Dónde va si el texto no lleva @mención ni #proyecto (la app manda el contexto que se está viendo)
    contexto: str | None = Field(default=None, max_length=12)
    asignatura_id: int | None = Field(default=None, ge=1)
    proyecto_id: int | None = Field(default=None, ge=1)
    # «Más opciones» del formulario rápido (P-3): mandan sobre lo escrito. "" quita lo leído del texto
    opciones: "OpcionesIn | None" = None


class OpcionesIn(BaseModel):
    due_date: str | None = Field(default=None, max_length=10)
    due_time: str | None = Field(default=None, max_length=5)
    duration_min: int | None = Field(default=None, ge=0, le=1440)
    priority: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=60)
    literal: bool = False  # «Sin fecha»: el texto tal cual, sin leer fecha ni hora
    location: str | None = Field(default=None, max_length=300)  # eventos
    reminder_min: int | None = Field(default=None, ge=-1, le=10080)  # eventos; -1 = según su tipo


CaptureIn.model_rebuild()


def split_prefix(text: str) -> tuple[str, str]:
    m = PREFIX_RE.match(text)
    if not m:
        return "inbox", text.strip()
    return {"t": "tarea", "i": "idea", "r": "rutina", "e": "evento", "g": "gasto"}[m.group(1).lower()], text[
        m.end() :
    ].strip()


GASTO_RE = re.compile(r"(?:^|\s)(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)?(?=\s|$)", re.I)
CAT_WORDS = {  # palabra clave (sin tildes) → categoría de Economía
    "Comida": (
        "cafe",
        "menu",
        "comida",
        "cena",
        "desayuno",
        "bar",
        "restaurante",
        "pizza",
        "bocadillo",
        "tapas",
        "kebab",
    ),
    "Supermercado": ("super", "mercadona", "lidl", "carrefour", "compra", "dia ", "aldi"),
    "Transporte": ("bus", "autobus", "metro", "tren", "taxi", "uber", "gasolina", "abono", "parking", "billete"),
    "Ocio": ("cine", "concierto", "entradas", "juego", "copas", "fiesta", "teatro"),
    "Universidad": ("libro", "apuntes", "matricula", "universidad", "fotocopias", "material"),
    "Suscripciones": ("spotify", "netflix", "suscripcion", "icloud", "youtube", "prime"),
    "Deporte": ("gimnasio", "gym", "piscina", "padel", "futbol"),
    "Salud": ("farmacia", "medico", "dentista", "medicina"),
    "Ropa": ("ropa", "camiseta", "zapatillas", "pantalon", "zara"),
    "Regalos": ("regalo", "cumple"),
}


def parse_gasto(body: str) -> dict | None:
    """«4,50 café» o «café 4,50 €» → {importe: 4.5, concepto: "Café", categoria: "Comida"}; sin importe, None."""
    m = GASTO_RE.search(body)
    if not m:
        return None
    importe = round(float(m.group(1).replace(",", ".")), 2)
    if importe <= 0:
        return None
    concepto = (body[: m.start()] + " " + body[m.end() :]).strip(" -·,")
    concepto = re.sub(r"\s+", " ", concepto)
    plain = " " + _fold(concepto) + " "
    cat = next((c for c, words in CAT_WORDS.items() if any(w in plain for w in words)), "Otros")
    return {"importe": importe, "concepto": concepto[:1].upper() + concepto[1:] if concepto else None, "categoria": cat}


DAY_LETTERS = "lmxjvsd"  # L M X J V S D (0 = lunes)
# «L X V», «L,X,V», «LXV» (mayúsculas) · «lxv» (minúsculas, sin repetir letra) · «L-V», «l a v» (rango)
_DIAS_RANGO = re.compile(r"(?<!\S)([LMXJVSD]|[lmxjvsd])(?:\s*[-–]\s*|\s+a\s+)([LMXJVSD]|[lmxjvsd])(?!\S)")
_DIAS_MAYUS = re.compile(r"(?<!\S)[LMXJVSD](?:\s*(?:,|y)?\s*[LMXJVSD])*(?!\S)|(?<!\S)[LMXJVSD]{2,7}(?!\S)")
_DIAS_MINUS = re.compile(r"(?<!\S)[lmxjvsd]{2,7}(?!\S)")
# Duración: «30m», «30 min», «90 minutos», «1h», «1h30», «2 horas», «1 h 30 min»
_DUR_MIN = re.compile(r"(?<![\d:])(\d{1,3})\s*(?:m|min|mins|minutos?)\b")
_DUR_H = re.compile(r"(?<![\d:])(\d{1,2})\s*(?:h|horas?)(?:\s*(\d{1,2})\s*(?:m|min|minutos)?)?(?![\w:])")


def _dias_compactos(text: str) -> tuple[list[int], list[tuple[int, int]]]:
    """Días escritos con sus letras; devuelve los días (0 = lunes) y los trozos del texto que ocupan."""
    m = _DIAS_RANGO.search(text)
    if m:
        a, b = DAY_LETTERS.index(m.group(1).lower()), DAY_LETTERS.index(m.group(2).lower())
        if a < b:
            return list(range(a, b + 1)), [m.span()]
    days, spans = [], []
    for m in _DIAS_MAYUS.finditer(text):
        days += [DAY_LETTERS.index(ch.lower()) for ch in m.group(0) if ch.isalpha()]
        spans.append(m.span())
    for m in _DIAS_MINUS.finditer(text):
        tok = m.group(0)
        if len(set(tok)) == len(tok):  # «lxv» sí; una palabra con letras repetidas, no
            days += [DAY_LETTERS.index(ch) for ch in tok]
            spans.append(m.span())
    return sorted(set(days)), spans


def parse_routine(text: str) -> dict:
    """Repetición, hora y duración de una rutina escrita en castellano. Lo que no se entiende se queda en el título.

    «gimnasio L X V 18:00 1h», «leer lxv 22h 30m», «estirar de lunes a viernes 7:30», «yoga L-V a las 7».
    Una duración en horas («1h») solo se lee como tal si ya hay otra hora («18:00», «a las 7»); si no, «5h» es la hora.
    """
    f = _fold(text)
    spans = []
    repeat = {"freq": "daily"}
    m = re.search(r"\b(?:de lunes a viernes|entre semana|laborables|dias laborables)\b", f)
    if m:
        repeat, spans = {"freq": "weekly", "days": [0, 1, 2, 3, 4]}, spans + [m.span()]
    else:
        m = re.search(r"\b(?:los )?fines? de semana\b", f)
        if m:
            repeat, spans = {"freq": "weekly", "days": [5, 6]}, spans + [m.span()]
        else:
            m = re.search(r"\bcada (\d+) dias\b", f)
            if m:
                repeat, spans = {"freq": "interval", "every": int(m.group(1))}, spans + [m.span()]
            else:
                m = re.search(r"\b(?:cada dia|todos los dias|a diario|diario|diariamente)\b", f)
                if m:
                    spans.append(m.span())
                else:
                    days = []
                    for dm in re.finditer(
                        r"\b(?:los |el |cada )?(lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\b", f
                    ):
                        name = dm.group(1) if dm.group(1) in WEEKDAYS else dm.group(1).rstrip("s")
                        days.append(WEEKDAYS[name])
                        spans.append(dm.span())
                    if not days:
                        days, more = _dias_compactos(text)
                        spans += more
                    if days:
                        repeat = {"freq": "weekly", "days": sorted(set(days))}
                        if repeat["days"] == list(range(7)):
                            repeat = {"freq": "daily"}

    def blank(a: int, b: int) -> None:  # lo ya leído no se vuelve a leer
        nonlocal f
        f = f[:a] + " " * (b - a) + f[b:]

    for a, b in spans:
        blank(a, b)
    duration = 0
    for dm in _DUR_MIN.finditer(f):
        duration += int(dm.group(1))
        spans.append(dm.span())
        blank(*dm.span())
    clock = re.search(r"\b(?:a las |sobre las )?([01]?\d|2[0-3]):([0-5]\d)\b", f) or re.search(
        r"\ba las ([01]?\d|2[0-3])\b", f
    )
    hours = list(_DUR_H.finditer(f))
    if not clock and hours:  # sin otra hora, la primera «18h» es la hora; las demás, duración
        first, hours = hours[0], hours[1:]
        if int(first.group(1)) <= 23 and not first.group(2):
            clock = first
    for dm in hours:
        duration += int(dm.group(1)) * 60 + int(dm.group(2) or 0)
        spans.append(dm.span())
    due_time = None
    if clock:
        h = int(clock.group(1))
        minutos = clock.group(2) if clock.re.groups >= 2 else None  # «a las 5» no tiene minutos
        mi = int(minutos) if minutos else 0
        if "a las" in clock.group(0) and 1 <= h <= 7 and not minutos:
            h += 12  # «a las 7» = 19:00, como en los eventos
        due_time, spans = f"{h:02d}:{mi:02d}", spans + [clock.span()]
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    title = re.sub(r"\s+", " ", "".join(chars)).strip(" ,.-")
    title = re.sub(r"\s+(?:y|e|,|los|las|el|a|cada|de|durante)$", "", title, flags=re.I).strip(" ,.-")
    return {
        "title": title[:1].upper() + title[1:] if title else text.strip(),
        "repeat": repeat,
        "due_time": due_time,
        "duration_min": duration if 0 < duration <= 1440 else None,
    }


def _sin_version(ctx: dict) -> dict:
    """Eventos y rutinas no llevan versión de proyecto."""
    return {k: v for k, v in ctx.items() if k != "version_id"}


def _con_menciones(body: str, ctx: dict) -> tuple[str, dict, str] | dict:
    """Quita «@asignatura» y «#proyecto [versión]» del texto y lleva el elemento allí: (texto, contexto, dónde).
    Si una mención no existe, el dict de error (no se guarda nada)."""
    from app.contextos import parse_mentions

    m = parse_mentions(body)
    if m["errores"]:
        return {"status": "error", "message": " · ".join(m["errores"]), "errores": m["errores"]}
    body = m["text"]
    if not body:
        return {"status": "error", "message": "Falta el texto"}
    donde = ""
    if m["asignatura"]:
        ctx, donde = {"asignatura_id": m["asignatura"]["id"]}, f"@{m['asignatura']['codigo']}"
    elif m["proyecto"]:
        ctx, donde = {"proyecto_id": m["proyecto"]["id"]}, f"#{m['proyecto']['slug']}"
        if m["version"]:
            ctx["version_id"] = m["version"]["id"]
            donde += f" {m['version']['nombre']}"
    return body, ctx, donde


def _a_revisar(body: str, reason: str, message: str) -> dict:
    """Lo que no se entiende con seguridad va al Inbox marcado «Revisar fecha» (aquí, solo la respuesta)."""
    return {
        "status": "success",
        "kind": "inbox",
        "revisar": True,
        "reason": reason,
        "preview": {"title": body, "when": None},
        "message": message,
    }


def _tipo_de_evento(title: str, ctx: dict) -> str:
    """En una asignatura, «examen»/«parcial» y «entrega» dan ese tipo de evento."""
    if not ctx.get("asignatura_id"):
        return "evento"
    if re.search(r"\b(examen|parcial)\b", title, re.I):
        return "examen"
    return "entrega" if re.search(r"\bentrega\b", title, re.I) else "evento"


def _capturar_evento(body: str, ctx: dict, donde: str, dry_run: bool, op: "OpcionesIn | None" = None) -> dict:
    from app.calendar import EventIn, create_event
    from app.items import ItemIn, create

    p = parse_event(body)
    if not p["ok"]:
        out = _a_revisar(body, p["reason"], f"No entiendo la fecha ({p['reason']}): va al Inbox marcado «{REVISAR}»")
        if not dry_run:
            out["id"] = create(
                ItemIn(
                    text=body, type="tarea", category=REVISAR, details=f"Fecha sin interpretar: {p['reason']}", **ctx
                )
            )
        return out
    title, location = p["title"], (op.location if op and op.location is not None else None)
    m = LUGAR_RE.match(title)
    if m and location is None:  # «Dentista viernes 10:00 en Clínica Sur»: el lugar con mayúscula al final
        title, location = m.group(1), m.group(2)
    p["title"] = title
    preview = {
        "title": p["title"],
        "location": location or None,
        "when": describe(p),
        "start": p["start"].strftime("%Y-%m-%dT%H:%M") if not p["all_day"] else p["start"].date().isoformat(),
        "end": p["end"].strftime("%Y-%m-%dT%H:%M") if not p["all_day"] else p["end"].date().isoformat(),
        "all_day": p["all_day"],
    }
    preview["donde"] = donde or None
    out = {
        "status": "success",
        "kind": "evento",
        "preview": preview,
        "message": f"{p['title']} · {describe(p)}" + (f" · {donde}" if donde else ""),
    }
    if not dry_run:
        out["id"] = create_event(
            EventIn(
                title=p["title"],
                start=preview["start"],
                end=preview["end"],
                all_day=p["all_day"],
                kind=_tipo_de_evento(p["title"], ctx),
                location=location or None,
                reminder_min=op.reminder_min if op and op.reminder_min is not None and op.reminder_min >= 0 else None,
                **_sin_version(ctx),
            )
        )
    return out


def _capturar_gasto(body: str, dry_run: bool) -> dict:
    from app.database import get_db
    from app.finance import MovementIn, api_create_movement
    from app.items import ItemIn, create

    g = parse_gasto(body)
    if not g:
        out = _a_revisar(body, "no dice cuánto", f"No veo el importe: va al Inbox marcado «{REVISAR}»")
        if not dry_run:
            out["id"] = create(ItemIn(text=f"Gasto: {body}", type="tarea", category=REVISAR))
        return out
    with get_db() as conn:
        acc = conn.execute(
            "SELECT id, nombre FROM fin_accounts WHERE archivada=0 ORDER BY orden, id LIMIT 1"
        ).fetchone()
    when = f"{g['categoria']}" + (f" · {acc['nombre']}" if acc else "")
    euros = f"{g['importe']:.2f}".replace(".", ",")
    out = {
        "status": "success",
        "kind": "gasto",
        "preview": {"title": f"{euros} € · {g['concepto'] or g['categoria']}", "when": when, **g},
        "message": f"Gasto: {euros} € {g['concepto'] or ''} · {when}".replace("  ", " "),
    }
    if not dry_run:
        out["id"] = api_create_movement(
            MovementIn(
                importe=g["importe"],
                tipo="gasto",
                categoria=g["categoria"],
                concepto=g["concepto"],
                cuenta_id=acc["id"] if acc else None,
            )
        )["id"]
    return out


def _capturar_rutina(body: str, ctx: dict, donde: str, dry_run: bool) -> dict:
    from app.items import ItemIn, create
    from app.routines import describe as describe_repeat

    r = parse_routine(body)
    when = (
        describe_repeat(r["repeat"])
        + (f" a las {r['due_time']}" if r["due_time"] else "")
        + (f" · {r['duration_min']} min" if r["duration_min"] else "")
    )
    out = {
        "status": "success",
        "kind": "rutina",
        "preview": {"title": r["title"], "when": when, "donde": donde or None},
        "message": f"Rutina: {r['title']} · {when}" + (f" · {donde}" if donde else ""),
    }
    if not dry_run:
        out["id"] = create(
            ItemIn(
                text=r["title"],
                type="rutina",
                repeat=r["repeat"],
                due_time=r["due_time"],
                duration_min=r["duration_min"],
                **_sin_version(ctx),
            )
        )
    return out


PRIO_RE = re.compile(r"(?<!\S)(?:!(alta|media|baja)|(!!))(?!\S)", re.I)
CAT_RE = re.compile(r"(?<!\S)\+([^\s+!@#]{1,60})(?!\S)")
LUGAR_RE = re.compile(r"^(.*\S)\s+en\s+((?:[A-ZÁÉÍÓÚÑ0-9][^\s]*)(?:\s+(?:de|del|la|el|y)?\s*[A-ZÁÉÍÓÚÑ0-9][^\s]*)*)$")


def _marcas(line: str) -> tuple[str, dict]:
    """«!alta» / «!!» = prioridad alta (también «!media», «!baja») y «+Categoría»: se quitan del texto."""
    extra = {}
    m = PRIO_RE.search(line)
    if m:
        extra["priority"] = (m.group(1) or "alta").lower()
        line = line[: m.start()] + line[m.end() :]
    m = CAT_RE.search(line)
    if m:
        extra["category"] = m.group(1)
        line = line[: m.start()] + line[m.end() :]
    return re.sub(r"\s{2,}", " ", line).strip(), extra


def _con_opciones(extra: dict, op: "OpcionesIn | None") -> dict:
    """Lo elegido en «Más opciones» manda; una hora sin día es para hoy."""
    if op is None:
        return extra
    for k in ("due_date", "due_time", "duration_min", "priority", "category"):
        v = getattr(op, k)
        if v is not None:
            if v in ("", 0):
                extra.pop(k, None)
            else:
                extra[k] = v
    if extra.get("due_time") and not extra.get("due_date"):
        extra["due_date"] = date.today().isoformat()
    if not extra.get("due_time"):
        extra.pop("duration_min", None)
    return extra


def _when(extra: dict) -> str | None:
    if not extra.get("due_date"):
        return None
    p = {
        "ok": True,
        "title": "",
        "all_day": not extra.get("due_time"),
        "start": datetime.fromisoformat(f"{extra['due_date']}T{extra.get('due_time') or '00:00'}"),
        "duration_min": extra.get("duration_min") or 0,
    }
    p["end"] = p["start"] + timedelta(minutes=p["duration_min"] or 0)
    try:
        return describe(p).replace(" · todo el día", "")
    except Exception:  # noqa: BLE001  (la vista previa nunca rompe la captura)
        return extra["due_date"]


def _capturar_tarea(kind: str, body: str, ctx: dict, donde: str, dry_run: bool, op: "OpcionesIn | None" = None) -> dict:
    """Inbox, tarea o idea; las dos últimas con fecha (y hora) si la llevan clara. Solo se lee la primera línea:
    el resto (lo pegado o compartido) se queda tal cual."""
    from app.items import ItemIn, create

    type_ = "idea" if kind == "idea" else "tarea"
    label = {"inbox": "Inbox", "tarea": "Tarea", "idea": "Idea"}[kind]
    first, sep, rest = body.partition("\n")
    first, extra = _marcas(first)
    title, when, leido = first, None, None
    if kind in ("tarea", "idea") and not (op and op.literal):
        p = parse_event(first)
        if p["ok"]:
            title, leido = p["title"], p
            extra["due_date"] = p["start"].date().isoformat()
            if not p["all_day"]:
                extra.update(due_time=p["start"].strftime("%H:%M"), duration_min=p["duration_min"])
    extra = _con_opciones(extra, op)
    if leido and extra.get("due_date") == leido["start"].date().isoformat() and op is None:
        when = describe(leido).replace(" · todo el día", "")
    else:
        when = _when(extra)
    title = (title or first or body).strip() + (sep + rest if rest else "")
    if ctx.get("asignatura_id") and type_ == "tarea" and re.search(r"pr[aá]ctica|entrega|trabajo", title, re.I):
        extra["uni_tipo"] = "entrega"  # «t: práctica 4 @gabd viernes» es una entrega de GABD
    out = {
        "status": "success",
        "kind": kind,
        "preview": {"title": title, "when": when, "donde": donde or None, "fecha_leida": bool(leido), **extra},
        "message": f"{label}: {title.split(chr(10))[0][:80]}"
        + (f" · {when}" if when else "")
        + (f" · {donde}" if donde else ""),
    }
    if not dry_run:
        out["id"] = create(ItemIn(text=title, type=type_, **extra, **ctx))
    return out


def capture(text: str, dry_run: bool = False, default: dict | None = None, op: "OpcionesIn | None" = None) -> dict:
    kind, body = split_prefix(text)
    if not body:
        return {"status": "error", "message": "Falta el texto"}
    ctx = {k: v for k, v in (default or {}).items() if v}
    donde = ""
    if kind != "gasto" and any(c in body for c in "@#"):
        leido = _con_menciones(body, ctx)
        if isinstance(leido, dict):
            return leido
        body, ctx, donde = leido
    if kind == "evento":
        return _capturar_evento(body, ctx, donde, dry_run, op)
    if kind == "gasto":
        return _capturar_gasto(body, dry_run)
    if kind == "rutina":
        return _capturar_rutina(body, ctx, donde, dry_run)
    return _capturar_tarea(kind, body, ctx, donde, dry_run, op)


@router.post("/capture")
def api_capture(data: CaptureIn):
    return capture(
        data.text,
        data.dry_run,
        {"contexto": data.contexto, "asignatura_id": data.asignatura_id, "proyecto_id": data.proyecto_id},
        data.opciones,
    )
