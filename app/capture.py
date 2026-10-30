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

Un evento que no se entiende con seguridad NO se inventa: va al Inbox como tarea con la categoría
«Revisar fecha» y el motivo en sus notas. `dry_run` devuelve la vista previa sin guardar nada.
"""
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.natural_date import WEEKDAYS, _fold, describe, parse_event

router = APIRouter(prefix="/api")
PREFIX_RE = re.compile(r"^\s*([tireg])\s*:\s*", re.I)
REVISAR = "Revisar fecha"


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    dry_run: bool = False


def split_prefix(text: str) -> tuple[str, str]:
    m = PREFIX_RE.match(text)
    if not m:
        return "inbox", text.strip()
    return {"t": "tarea", "i": "idea", "r": "rutina", "e": "evento", "g": "gasto"}[m.group(1).lower()], text[m.end():].strip()


GASTO_RE = re.compile(r"(?:^|\s)(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)?(?=\s|$)", re.I)
CAT_WORDS = {  # palabra clave (sin tildes) → categoría de Economía
    "Comida": ("cafe", "menu", "comida", "cena", "desayuno", "bar", "restaurante", "pizza", "bocadillo", "tapas", "kebab"),
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
    concepto = (body[:m.start()] + " " + body[m.end():]).strip(" -·,")
    concepto = re.sub(r"\s+", " ", concepto)
    plain = " " + _fold(concepto) + " "
    cat = next((c for c, words in CAT_WORDS.items() if any(w in plain for w in words)), "Otros")
    return {"importe": importe, "concepto": concepto[:1].upper() + concepto[1:] if concepto else None, "categoria": cat}


def parse_routine(text: str) -> dict:
    """Repetición y hora de una rutina escrita en castellano. Lo que no se entiende se queda en el título."""
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
                    for dm in re.finditer(r"\b(?:los |el |cada )?(lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\b", f):
                        name = dm.group(1) if dm.group(1) in WEEKDAYS else dm.group(1).rstrip("s")
                        days.append(WEEKDAYS[name])
                        spans.append(dm.span())
                    if days:
                        repeat = {"freq": "weekly", "days": sorted(set(days))}
    due_time = None
    m = re.search(r"\b(?:a las |sobre las )?([01]?\d|2[0-3])(?::([0-5]\d)|h\b)", f) or re.search(r"\ba las ([01]?\d|2[0-3])\b", f)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
        if "a las" in m.group(0) and 1 <= h <= 7 and not m.group(2):
            h += 12  # «a las 7» = 19:00, como en los eventos
        due_time, spans = f"{h:02d}:{mi:02d}", spans + [m.span()]
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    title = re.sub(r"\s+", " ", "".join(chars)).strip(" ,.-")
    title = re.sub(r"\s+(?:y|e|,|los|las|el|a|cada)$", "", title, flags=re.I).strip(" ,.-")
    return {"title": title[:1].upper() + title[1:] if title else text.strip(), "repeat": repeat, "due_time": due_time}


def capture(text: str, dry_run: bool = False) -> dict:
    from app.calendar import EventIn, create_event
    from app.items import ItemIn, create
    from app.routines import describe as describe_repeat
    kind, body = split_prefix(text)
    if not body:
        return {"status": "error", "message": "Falta el texto"}
    if kind == "evento":
        p = parse_event(body)
        if p["ok"]:
            preview = {"title": p["title"], "when": describe(p), "start": p["start"].strftime("%Y-%m-%dT%H:%M") if not p["all_day"] else p["start"].date().isoformat(),
                       "end": p["end"].strftime("%Y-%m-%dT%H:%M") if not p["all_day"] else p["end"].date().isoformat(), "all_day": p["all_day"]}
            out = {"status": "success", "kind": "evento", "preview": preview, "message": f"{p['title']} · {describe(p)}"}
            if not dry_run:
                out["id"] = create_event(EventIn(title=p["title"], start=preview["start"], end=preview["end"], all_day=p["all_day"]))
            return out
        out = {"status": "success", "kind": "inbox", "revisar": True, "reason": p["reason"],
               "preview": {"title": body, "when": None}, "message": f"No entiendo la fecha ({p['reason']}): va al Inbox marcado «{REVISAR}»"}
        if not dry_run:
            out["id"] = create(ItemIn(text=body, type="tarea", category=REVISAR, details=f"Fecha sin interpretar: {p['reason']}"))
        return out
    if kind == "gasto":
        g = parse_gasto(body)
        if not g:
            out = {"status": "success", "kind": "inbox", "revisar": True, "reason": "no dice cuánto",
                   "preview": {"title": body, "when": None}, "message": f"No veo el importe: va al Inbox marcado «{REVISAR}»"}
            if not dry_run:
                out["id"] = create(ItemIn(text=f"Gasto: {body}", type="tarea", category=REVISAR))
            return out
        from app.database import get_db
        from app.finance import MovementIn, api_create_movement
        with get_db() as conn:
            acc = conn.execute("SELECT id, nombre FROM fin_accounts WHERE archivada=0 ORDER BY orden, id LIMIT 1").fetchone()
        when = f"{g['categoria']}" + (f" · {acc['nombre']}" if acc else "")
        euros = f"{g['importe']:.2f}".replace(".", ",")
        out = {"status": "success", "kind": "gasto", "preview": {"title": f"{euros} € · {g['concepto'] or g['categoria']}", "when": when, **g},
               "message": f"Gasto: {euros} € {g['concepto'] or ''} · {when}".replace("  ", " ")}
        if not dry_run:
            out["id"] = api_create_movement(MovementIn(importe=g["importe"], tipo="gasto", categoria=g["categoria"],
                                                       concepto=g["concepto"], cuenta_id=acc["id"] if acc else None))["id"]
        return out
    if kind == "rutina":
        r = parse_routine(body)
        when = describe_repeat(r["repeat"]) + (f" a las {r['due_time']}" if r["due_time"] else "")
        out = {"status": "success", "kind": "rutina", "preview": {"title": r["title"], "when": when}, "message": f"Rutina: {r['title']} · {when}"}
        if not dry_run:
            out["id"] = create(ItemIn(text=r["title"], type="rutina", repeat=r["repeat"], due_time=r["due_time"]))
        return out
    type_ = "idea" if kind == "idea" else "tarea"
    label = {"inbox": "Inbox", "tarea": "Tarea", "idea": "Idea"}[kind]
    title, extra, when = body, {}, None
    if kind in ("tarea", "idea"):
        p = parse_event(body)
        if p["ok"]:
            title, when = p["title"], describe(p).replace(" · todo el día", "")
            extra = {"due_date": p["start"].date().isoformat()}
            if not p["all_day"]:
                extra.update(due_time=p["start"].strftime("%H:%M"), duration_min=p["duration_min"])
    out = {"status": "success", "kind": kind, "preview": {"title": title, "when": when, **extra},
           "message": f"{label}: {title[:80]}" + (f" · {when}" if when else "")}
    if not dry_run:
        out["id"] = create(ItemIn(text=title, type=type_, **extra))
    return out


@router.post("/capture")
def api_capture(data: CaptureIn):
    return capture(data.text, data.dry_run)
