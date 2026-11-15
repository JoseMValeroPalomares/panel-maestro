"""
comidas/rapido.py — altas rápidas de Comidas (P-3): lo mínimo en una línea y lo demás pegado o una cosa por línea.

    POST /api/meals/rapido        {"texto": "Tortilla de patatas cena 30 min +casera",
                                   "ingredientes": "3 huevos\\n300 g patata\\ncebolla 50", "pasos": "…", "dry_run": true}
        → vista previa (cada línea con el ingrediente que se ha reconocido, sus gramos y kcal) o, sin dry_run, el plato.
          Una línea que no se reconoce no se inventa: sale en `sin_reconocer` y el plato no se crea hasta arreglarla.
    POST /api/ingredients/rapido  {"texto": "Avena 389 16,9 66,3 6,9", "dry_run": true}
        → nombre y kcal, proteínas, hidratos y grasas por 100 g, por orden; o con su nombre («p 16,9», «12 g de grasas»).
          También se puede pegar la tabla nutricional de una etiqueta («Valor energético … 389 kcal, Grasas 6,9 g, de las
          cuales saturadas 1,2 g, Hidratos de carbono 66,3 g, de los cuales azúcares 1 g, Proteínas 16,9 g, Sal 0,01 g»).
"""

import re
import unicodedata

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from . import nutrition as nu
from .core import FRANJA_ORDEN, IngredientIn, MealIn, MealIngredientIn, _sync_franjas
from .database import get_db
from .ingredientes import create_ingredient
from .platos import create_meal

router = APIRouter()

MAX_LINEAS = 60


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _singular(w: str) -> str:
    for suf in ("ces", "es", "s"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            base = w[: -len(suf)] + ("z" if suf == "ces" else "")
            return base
    return w


def _palabras(s: str) -> list[str]:
    return [
        _singular(w) for w in re.findall(r"[a-z0-9ñ]+", _fold(s)) if w not in {"de", "del", "la", "el", "en", "con"}
    ]


def _num(s: str) -> float:
    return float(s.replace(",", "."))


# ─────────── Ingredientes de un plato ───────────

UNIDADES = {
    "g": 1,
    "gr": 1,
    "grs": 1,
    "gramo": 1,
    "gramos": 1,
    "ml": 1,
    "kg": 1000,
    "l": 1000,
    "litro": 1000,
    "litros": 1000,
    "cl": 10,
}
UDS = {"ud", "uds", "u", "unidad", "unidades", "pieza", "piezas"}
_N = r"(\d+(?:[.,]\d+)?|½|un|una|medio|media)"
_LINEA_DELANTE = re.compile(rf"^{_N}\s*([a-záéíóú]+\.?)?\s+(?:de\s+)?(.+)$", re.I)
_LINEA_DETRAS = re.compile(rf"^(.+?)\s+{_N}\s*([a-záéíóú]+\.?)?$", re.I)
_VINETA = re.compile(r"^\s*(?:[-*•·+]\s*|\d{1,2}[.)]\s+)?")


def _cantidad(tok: str) -> float:
    return {"½": 0.5, "un": 1, "una": 1, "medio": 0.5, "media": 0.5}.get(tok.lower()) or _num(tok)


def leer_linea(line: str) -> dict | None:
    """«300 g de patata», «3 huevos», «patata 300», «1 kg tomate» → {"texto", "cantidad", "unidad"} (unidad g | ud | None)."""
    text = _VINETA.sub("", line, count=1).strip().rstrip(".,;")
    if not text:
        return None
    for rx, order in ((_LINEA_DELANTE, "delante"), (_LINEA_DETRAS, "detras")):
        m = rx.match(text)
        if not m:
            continue
        if order == "delante":
            qty, unit, name = m.group(1), (m.group(2) or "").rstrip(".").lower(), m.group(3)
            if unit and unit not in UNIDADES and unit not in UDS:  # «3 huevos»: la «unidad» era el nombre
                name, unit = f"{m.group(2)} {name}", ""
        else:
            name, qty, unit = m.group(1), m.group(2), (m.group(3) or "").rstrip(".").lower()
            if unit and unit not in UNIDADES and unit not in UDS:
                continue
        cantidad = _cantidad(qty)
        if unit in UNIDADES:
            return {"texto": name.strip(), "cantidad": cantidad * UNIDADES[unit], "unidad": "g"}
        return {"texto": name.strip(), "cantidad": cantidad, "unidad": "ud" if unit in UDS else None}
    return {"texto": text, "cantidad": None, "unidad": None}


def buscar_ingrediente(nombre: str, catalogo: list[dict]) -> dict | None:
    """El ingrediente del catálogo que mejor encaja: igual, luego que empiece igual, luego con todas las palabras.
    Entre varios, el de nombre más corto (el más genérico)."""
    q = _palabras(nombre)
    if not q:
        return None
    qs = " ".join(q)
    tries = (
        lambda w: " ".join(w) == qs,
        lambda w: " ".join(w).startswith(qs) or qs.startswith(" ".join(w)),
        lambda w: all(x in w for x in q),
        lambda w: all(any(x in y or y in x for y in w) for x in q),
    )
    for ok in tries:
        hits = [c for c in catalogo if ok(c["_w"])]
        if hits:
            return min(hits, key=lambda c: (len(c["nombre"]), c["nombre"]))
    return None


def _catalogo(conn) -> list[dict]:
    rows = [dict(r) for r in conn.execute("SELECT * FROM ingredients ORDER BY nombre")]
    for r in rows:
        r["_w"] = _palabras(r["nombre"])
    return rows


class PlatoRapidoIn(BaseModel):
    texto: str = Field(min_length=1, max_length=300)
    ingredientes: str = Field(default="", max_length=20_000)
    pasos: str = Field(default="", max_length=40_000)
    dry_run: bool = False
    franja: str | None = Field(default=None, max_length=30)  # «Más opciones»: mandan sobre lo escrito
    tiempo_preparacion_min: int | None = Field(default=None, ge=0, le=10_000)
    tags: str | None = Field(default=None, max_length=500)
    es_racion_unica: bool | None = None


_TIEMPO = re.compile(r"(?<!\S)(\d{1,4})\s*(min|mins|minutos|m|h|horas?)(?!\S)", re.I)
_TAG = re.compile(r"(?<!\S)\+([^\s+]{1,40})")


def leer_cabecera(texto: str, franjas: list[dict]) -> dict:
    """«Tortilla de patatas cena 30 min +casera» → nombre, franja, tiempo y etiquetas."""
    out: dict = {"franja": None, "tiempo": None, "tags": []}
    t = texto
    m = _TIEMPO.search(t)
    if m:
        n = int(m.group(1))
        out["tiempo"] = n * 60 if m.group(2).lower().startswith("h") else n
        t = t[: m.start()] + t[m.end() :]
    out["tags"] = _TAG.findall(t)
    t = _TAG.sub("", t)
    nombres = {_fold(f["clave"]): f["clave"] for f in franjas} | {_fold(f["nombre"]): f["clave"] for f in franjas}
    words = t.split()
    # la franja solo si va al final («… cena»): «Crema de cena» no existe, pero «Desayuno inglés» es un nombre
    if len(words) > 1 and _fold(words[-1]) in nombres:
        out["franja"] = nombres[_fold(words.pop())]
    out["nombre"] = re.sub(r"\s{2,}", " ", " ".join(words)).strip(" ,.-·")
    return out


def _pasos(text: str) -> list[str]:
    out = [_VINETA.sub("", x, count=1).strip() for x in (text or "").splitlines()]
    return [x[:2000] for x in out if x][:100]


@router.post("/api/meals/rapido")
def plato_rapido(data: PlatoRapidoIn, background_tasks: BackgroundTasks):
    with get_db() as conn:
        franjas = _sync_franjas(conn)
        catalogo = _catalogo(conn)
    cab = leer_cabecera(data.texto, franjas)
    if not cab["nombre"]:
        raise HTTPException(status_code=422, detail="Falta el nombre del plato")
    lineas = [x for x in (leer_linea(line) for line in (data.ingredientes or "").splitlines()) if x]
    if len(lineas) > MAX_LINEAS:
        raise HTTPException(status_code=422, detail=f"Como mucho {MAX_LINEAS} ingredientes de una vez")
    filas, items, sin = [], [], []
    for ln in lineas:
        ing = buscar_ingrediente(ln["texto"], catalogo)
        fila = {"texto": ln["texto"], "cantidad": ln["cantidad"], "unidad": ln["unidad"], "ingrediente": None}
        if ing is None:
            fila["problema"] = "No está en tus ingredientes"
            sin.append(ln["texto"])
        elif not ln["cantidad"]:
            fila["problema"] = "Falta la cantidad"
            sin.append(ln["texto"])
        else:
            gpu = ing["gramos_por_unidad"]
            # sin unidad: unidades si el ingrediente las tiene y la cantidad es pequeña («3 huevos»), si no, gramos
            unidades = ln["unidad"] == "ud" or (ln["unidad"] is None and gpu and ln["cantidad"] <= 20)
            if unidades and not gpu:
                fila["problema"] = f"«{ing['nombre']}» no tiene gramos por unidad: escribe los gramos"
                sin.append(ln["texto"])
            else:
                gramos = ln["cantidad"] * gpu if unidades else ln["cantidad"]
                fila.update(
                    gramos=round(gramos, 1),
                    unidades=ln["cantidad"] if unidades else None,
                    unidad_nombre=ing["unidad_nombre"] if unidades else None,
                    kcal=round(ing["kcal_100g"] * gramos / 100),
                )
                items.append(
                    MealIngredientIn(
                        ingredient_id=ing["id"], **({"unidades": ln["cantidad"]} if unidades else {"gramos": gramos})
                    )
                )
        if ing is not None:
            fila["ingrediente"] = {"id": ing["id"], "nombre": ing["nombre"]}
        filas.append(fila)
    franja = data.franja or cab["franja"] or "comida"
    tags = data.tags if data.tags is not None else ", ".join(cab["tags"])
    tiempo = data.tiempo_preparacion_min if data.tiempo_preparacion_min is not None else (cab["tiempo"] or 0)
    pasos = _pasos(data.pasos)
    total = sum(f.get("kcal") or 0 for f in filas)
    out = {
        "status": "success",
        "preview": {
            "nombre": cab["nombre"],
            "franja": franja,
            "franja_nombre": next((f["nombre"] for f in franjas if f["clave"] == franja), franja.capitalize()),
            "tiempo_preparacion_min": tiempo,
            "tags": tags,
            "ingredientes": filas,
            "pasos": pasos,
            "kcal_receta": total,
            "gramos_receta": round(sum(f.get("gramos") or 0 for f in filas)),
        },
        "sin_reconocer": sin,
    }
    if data.dry_run:
        return out
    if sin:
        raise HTTPException(status_code=422, detail="Revisa: " + ", ".join(f"«{x}»" for x in sin))
    if franja not in FRANJA_ORDEN and franja not in {f["clave"] for f in franjas}:
        raise HTTPException(status_code=422, detail="Esa franja no existe")
    meal = MealIn(
        nombre=cab["nombre"][:200],
        franja=franja,
        tags=tags,
        tiempo_preparacion_min=tiempo,
        es_racion_unica=bool(data.es_racion_unica),
        instrucciones=pasos,
        image_source="manual",
        ingredientes=items,
    )
    res = create_meal(meal, background_tasks)
    out.update(id=res["id"], gramos_recomendados=res["gramos_recomendados"])
    return out


# ─────────── Ingrediente en una línea o pegando la etiqueta ───────────

CAMPOS = [  # palabra completa (sin tildes) → campo; las saturadas y los azúcares antes que las grasas y los hidratos
    (r"saturad[oa]s?", "grasas_saturadas_100g"),
    (r"trans", "grasas_trans_100g"),
    (r"azucar(?:es)?", "azucares_100g"),
    (r"sal", "sal_100g"),
    (r"proteinas?|prot", "proteinas_100g"),
    (r"hidratos?|carbohidratos?", "carbohidratos_100g"),
    (r"grasas?|lipidos?", "grasas_100g"),
    (r"kcal|energia|energetico|calorias", "kcal_100g"),
]
LETRAS = {
    "p": "proteinas_100g",
    "h": "carbohidratos_100g",
    "c": "carbohidratos_100g",
    "g": "grasas_100g",
    "k": "kcal_100g",
}
ORDEN = ["kcal_100g", "proteinas_100g", "carbohidratos_100g", "grasas_100g"]
CATEGORIA_POR_PALABRA = {
    "cereal": ("avena", "arroz", "pan", "pasta", "harina", "trigo", "maiz", "quinoa", "cereal", "copos", "tortita"),
    "verdura": (
        "tomate",
        "lechuga",
        "cebolla",
        "pimiento",
        "zanahoria",
        "calabac",
        "brocoli",
        "espinaca",
        "patata",
        "ajo",
    ),
    "fruta": ("manzana", "platano", "naranja", "pera", "fresa", "uva", "kiwi", "melon", "sandia", "mango", "fruta"),
    "lacteo": ("leche", "yogur", "queso", "kefir", "nata", "requeson", "skyr"),
    "proteina": ("pollo", "pavo", "ternera", "cerdo", "atun", "salmon", "merluza", "huevo", "jamon", "tofu", "lomo"),
    "legumbre": ("lenteja", "garbanzo", "alubia", "judia", "soja", "guisante"),
    "grasa": ("aceite", "mantequilla", "aguacate", "nuez", "almendra", "cacahuete", "anacardo", "pipa"),
}


def leer_ingrediente(texto: str) -> dict:
    """Nombre y valores por 100 g. Lo etiquetado («proteínas 16,9 g», «p16,9») va a su campo; los números sueltos, en
    orden: kcal, proteínas, hidratos, grasas. En una etiqueta, el valor en kJ se ignora."""
    f = _fold(texto)
    valores: dict = {}
    usados: list[tuple[int, int]] = []
    # «Valor energético 1630 kJ / 389 kcal»: los kJ no cuentan
    for m in re.finditer(r"\d+(?:[.,]\d+)?\s*kj\b", f):
        usados.append(m.span())
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*kcal\b", f):
        valores.setdefault("kcal_100g", _num(m.group(1)))
        usados.append(m.span())
    # palabra y número cerca («proteínas 16,9 g», «hidratos de carbono: 66,3 g», «de las cuales azúcares 1 g»)
    for m in re.finditer(r"([a-z]+)[a-z ,:/()]{0,30}?(\d+(?:[.,]\d+)?)\s*(?:g\b)?", f):
        if any(a <= m.start(2) < b for a, b in usados):
            continue
        campo = next((c for k, c in CAMPOS if re.fullmatch(k, m.group(1))), None)
        if campo and campo not in valores:
            valores[campo] = _num(m.group(2))
            usados.append(m.span(2))
    # letra pegada al número: «p16,9», «16,9p», «16,9 p», «6 g» (g = grasa cuando va suelta tras su número)
    for m in re.finditer(r"(?<![a-z])([phcgk])(\d+(?:[.,]\d+)?)(?![\d.,])|(\d+(?:[.,]\d+)?)\s?([phcg])(?![a-z])", f):
        num, letra = (m.group(2), m.group(1)) if m.group(1) else (m.group(3), m.group(4))
        start = m.start(2) if m.group(1) else m.start(3)
        if any(a <= start < b for a, b in usados):
            continue
        campo = LETRAS[letra]
        if campo not in valores:
            valores[campo] = _num(num)
            usados.append(m.span())
    # números sueltos en orden
    libres = [campo for campo in ORDEN if campo not in valores]
    for m in re.finditer(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w.,])", f):
        if not libres:
            break
        if any(a <= m.start() < b for a, b in usados):
            continue
        valores[libres.pop(0)] = _num(m.group(1))
        usados.append(m.span())
    # nombre: lo que va antes del primer número o palabra de la tabla, en una sola línea
    primera = texto.strip().splitlines()[0] if texto.strip() else ""
    corte = re.search(
        r"(?<!\w)\d|\b(?:valor|energ[ií]a|energ[eé]tico|kcal|grasas?|prote[ií]nas?|hidratos|carbohidratos|az[uú]car(?:es)?|sal)\b",
        primera,
        re.I,
    )
    nombre = (primera[: corte.start()] if corte else primera).strip(" :,-·")
    nombre = re.sub(r"\s+(?:por|x)\s*$", "", nombre, flags=re.I).strip()
    fold = _fold(nombre)
    categoria = next((c for c, ws in CATEGORIA_POR_PALABRA.items() if any(w in fold for w in ws)), None)
    return {"nombre": nombre[:1].upper() + nombre[1:], "valores": valores, "categoria": categoria}


class IngredienteRapidoIn(BaseModel):
    texto: str = Field(min_length=1, max_length=5000)
    dry_run: bool = False
    categoria: str | None = Field(default=None, max_length=60)
    gramos_por_unidad: float | None = Field(default=None, gt=0, le=5000)
    unidad_nombre: str | None = Field(default=None, max_length=40)


@router.post("/api/ingredients/rapido")
def ingrediente_rapido(data: IngredienteRapidoIn):
    r = leer_ingrediente(data.texto)
    categoria = data.categoria or r["categoria"] or "General"
    v = r["valores"]
    check = nu.comprobar_kcal(
        v.get("kcal_100g", 0), v.get("proteinas_100g", 0), v.get("carbohidratos_100g", 0), v.get("grasas_100g", 0)
    )
    out = {
        "status": "success",
        "preview": {"nombre": r["nombre"], "categoria": categoria, "categoria_adivinada": not data.categoria, **v},
        "kcal_check": check,
    }
    if data.dry_run:
        return out
    if not r["nombre"]:
        raise HTTPException(status_code=422, detail="Falta el nombre del ingrediente")
    if "kcal_100g" not in v:
        raise HTTPException(status_code=422, detail="Faltan las kcal por 100 g")
    try:
        ing = IngredientIn(
            nombre=r["nombre"][:120],
            categoria=categoria,
            gramos_por_unidad=data.gramos_por_unidad,
            unidad_nombre=data.unidad_nombre,
            **v,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Algún valor no cabe en 100 g: " + str(e).split("\n")[1])
    res = create_ingredient(ing)
    if not isinstance(res, dict):  # 409: ya existe
        return res
    out.update(id=res["id"])
    return out
