"""
comidas/nutrition.py — cálculos nutricionales puros (sin base de datos).

Convenciones:
- Los macros de cada ingrediente se guardan POR 100 g y se escalan por la
  cantidad real: aporte = valor_100g × gramos / 100.
- Un plato es una lista de (ingrediente, gramos); su ración puede escalarse
  respecto a la receta completa (factor = gramos_ración / gramos_receta).
- Una comida (desayuno, comida…) suma varios platos; un día suma comidas.

Energía: factores de Atwater (4 kcal/g proteína e hidratos, 9 kcal/g grasa).
La fibra, el alcohol y los polialcoholes explican pequeñas diferencias, por
eso la comprobación usa tolerancia.

Objetivos: TMB de Mifflin-St Jeor × factor de actividad (TDEE) ± ajuste por
objetivo; proteína en g/kg, grasa en % de la energía y el resto, hidratos.
"""
from __future__ import annotations

MACROS = ("kcal", "proteinas", "carbohidratos", "grasas", "azucares", "sal", "grasas_saturadas")

KCAL_PROTEINA = 4.0
KCAL_HIDRATOS = 4.0
KCAL_GRASA = 9.0

# Factores de actividad de referencia (Harris-Benedict / FAO)
NIVELES_ACTIVIDAD = {
    1.2: "Sedentario",
    1.375: "Ligero (1-3 días/semana)",
    1.55: "Moderado (3-5 días/semana)",
    1.725: "Intenso (6-7 días/semana)",
    1.9: "Muy intenso (trabajo físico o doble sesión)",
}

# Ajuste por objetivo en % del gasto total. Los nombres antiguos se aceptan.
OBJETIVOS = {"definicion": -20.0, "mantenimiento": 0.0, "volumen": 10.0}
OBJETIVOS_ALIAS = {"perder": "definicion", "mantener": "mantenimiento", "ganar": "volumen"}

GRASA_PCT_DEFECTO = 25.0
SAL_MAX_G = 5.0           # OMS
AZUCAR_MAX_PCT = 10.0     # OMS, azúcares libres
FRUTA_VERDURA_MIN_G = 400  # OMS


def _zero() -> dict:
    return {k: 0.0 for k in MACROS}


def macros_por_cantidad(por_100g: dict, gramos: float) -> dict:
    """Aporte real de `gramos` de un alimento cuyos valores están por 100 g.
    Acepta claves `kcal_100g`, `proteinas_100g`… o `kcal`, `proteinas`…"""
    f = (gramos or 0) / 100.0
    out = {}
    for k in MACROS:
        v = por_100g.get(f"{k}_100g", por_100g.get(k, 0)) or 0
        out[k] = v * f
    return out


def sumar(*partes: dict) -> dict:
    total = _zero()
    for p in partes:
        for k in MACROS:
            total[k] += p.get(k, 0) or 0
    return total


def escalar(macros: dict, factor: float) -> dict:
    return {k: (macros.get(k, 0) or 0) * factor for k in MACROS}


def redondear(macros: dict, decimales: int = 1) -> dict:
    out = {k: round(macros.get(k, 0) or 0, decimales) for k in MACROS}
    out["kcal"] = round(macros.get("kcal", 0) or 0)
    return out


def receta(ingredientes: list[dict]) -> tuple[dict, float]:
    """Suma literal de una receta. Cada ingrediente: valores por 100 g + `gramos`.
    Devuelve (macros_totales, gramos_totales)."""
    total = _zero()
    gramos = 0.0
    for ing in ingredientes:
        total = sumar(total, macros_por_cantidad(ing, ing.get("gramos", 0)))
        gramos += ing.get("gramos", 0) or 0
    return total, gramos


def densidad_100g(macros_receta: dict, gramos_receta: float) -> dict:
    if not gramos_receta:
        return _zero()
    return escalar(macros_receta, 100.0 / gramos_receta)


def racion(macros_receta: dict, gramos_receta: float, gramos_racion: float) -> dict:
    """Macros de `gramos_racion` de un plato cuya receta completa pesa `gramos_receta`."""
    if not gramos_receta:
        return _zero()
    return escalar(macros_receta, (gramos_racion or 0) / gramos_receta)


# ── Coherencia energética (Atwater) ─────────────────────────────
def kcal_atwater(proteinas: float, carbohidratos: float, grasas: float) -> float:
    return KCAL_PROTEINA * (proteinas or 0) + KCAL_HIDRATOS * (carbohidratos or 0) + KCAL_GRASA * (grasas or 0)


def comprobar_kcal(kcal: float, proteinas: float, carbohidratos: float, grasas: float,
                   tolerancia_pct: float = 12.0, tolerancia_abs: float = 20.0) -> dict:
    """¿Cuadran las kcal declaradas con 4P + 4C + 9G? Se acepta la diferencia si
    es menor que la tolerancia relativa O la absoluta (los alimentos casi sin
    energía tienen diferencias relativas grandes pero irrelevantes)."""
    esperadas = kcal_atwater(proteinas, carbohidratos, grasas)
    diff = (kcal or 0) - esperadas
    base = max(esperadas, kcal or 0, 1e-9)
    diff_pct = abs(diff) / base * 100
    ok = abs(diff) <= tolerancia_abs or diff_pct <= tolerancia_pct
    return {"ok": ok, "kcal": round(kcal or 0, 1), "esperadas": round(esperadas, 1),
            "diferencia": round(diff, 1), "diferencia_pct": round(diff_pct, 1)}


# ── Objetivos ───────────────────────────────────────────────────
def normalizar_objetivo(objetivo: str | None) -> str:
    o = (objetivo or "mantenimiento").strip().lower()
    o = OBJETIVOS_ALIAS.get(o, o)
    return o if o in OBJETIVOS else "mantenimiento"


def tmb_mifflin(peso_kg: float, altura_cm: float, edad: float, sexo: str) -> float:
    """Mifflin-St Jeor (1990): 10·peso + 6.25·altura − 5·edad + 5 (hombre) / −161 (mujer)."""
    base = 10 * peso_kg + 6.25 * altura_cm - 5 * edad
    return base + (5 if (sexo or "").lower().startswith("h") else -161)


def gasto_total(tmb: float, nivel_actividad: float) -> float:
    return tmb * nivel_actividad


def calcular_objetivos(perfil: dict) -> dict:
    """Objetivos diarios a partir del perfil. Devuelve también claves antiguas
    (carb_min_g, grasa_max_g…) para no romper la API existente."""
    peso = float(perfil.get("peso_kg") or 0)
    objetivo = normalizar_objetivo(perfil.get("objetivo"))
    ajuste_pct = perfil.get("ajuste_pct")
    if ajuste_pct is None:
        ajuste_pct = OBJETIVOS[objetivo]
    grasa_pct = perfil.get("grasa_pct")
    grasa_pct = GRASA_PCT_DEFECTO if grasa_pct is None else float(grasa_pct)
    prot_gkg = float(perfil.get("proteina_g_kg") or 1.6)

    tmb = tmb_mifflin(peso, float(perfil.get("altura_cm") or 0), float(perfil.get("edad") or 0), perfil.get("sexo", "hombre"))
    tdee = gasto_total(tmb, float(perfil.get("nivel_actividad") or 1.2))
    kcal = tdee * (1 + float(ajuste_pct) / 100)

    proteina_g = peso * prot_gkg
    grasa_g = kcal * grasa_pct / 100 / KCAL_GRASA
    carb_kcal = kcal - proteina_g * KCAL_PROTEINA - grasa_g * KCAL_GRASA
    carbohidratos_g = max(carb_kcal, 0) / KCAL_HIDRATOS
    aviso = None
    if carb_kcal < 0:
        aviso = "La proteína y la grasa superan las kcal objetivo: baja los g/kg o el % de grasa."

    kcal_r = round(kcal)
    return {
        "objetivo": objetivo,
        "ajuste_pct": round(float(ajuste_pct), 1),
        "grasa_pct": round(grasa_pct, 1),
        "bmr": round(tmb),
        "tdee": round(tdee),
        "kcal_objetivo": kcal_r,
        "proteina_g": round(proteina_g),
        "grasa_g": round(grasa_g),
        "carbohidratos_g": round(carbohidratos_g),
        "reparto_pct": {
            "proteinas": round(proteina_g * KCAL_PROTEINA / kcal * 100) if kcal else 0,
            "grasas": round(grasa_pct),
            "carbohidratos": round(max(carb_kcal, 0) / kcal * 100) if kcal else 0,
        },
        "aviso": aviso,
        # Claves de la versión anterior (las usan el generador y el front antiguo)
        "carb_min_g": round(kcal_r * 0.45 / 4),
        "carb_max_g": round(kcal_r * 0.75 / 4),
        "grasa_max_g": round(grasa_g),
        "azucar_max_g": round(kcal_r * AZUCAR_MAX_PCT / 100 / 4),
        "sal_max_g": SAL_MAX_G,
        "fruta_verdura_min_g": FRUTA_VERDURA_MIN_G,
    }


def objetivos_comparables(obj: dict) -> dict:
    """Objetivo diario en las mismas claves que los macros."""
    return {"kcal": obj["kcal_objetivo"], "proteinas": obj["proteina_g"],
            "carbohidratos": obj["carbohidratos_g"], "grasas": obj["grasa_g"],
            "azucares": obj["azucar_max_g"], "sal": obj["sal_max_g"]}


def progreso(consumido: dict, objetivo: dict) -> dict:
    """% conseguido de cada macro respecto al objetivo (0 si no hay objetivo)."""
    return {k: (round((consumido.get(k, 0) or 0) / objetivo[k] * 100) if objetivo.get(k) else 0) for k in objetivo}


def restante(consumido: dict, objetivo: dict) -> dict:
    return {k: round(objetivo[k] - (consumido.get(k, 0) or 0), 1) for k in objetivo}


# ── Sugerencias según lo que queda del día ──────────────────────
MAX_GRAMOS_EXTRA = 250
PESOS_SUGERENCIA = {"kcal": 1.0, "proteinas": 1.4, "carbohidratos": 0.7, "grasas": 0.8}


def _error_relativo(aporte: dict, hueco: dict) -> float:
    err = 0.0
    for k, w in PESOS_SUGERENCIA.items():
        objetivo = max(hueco.get(k, 0), 0)
        escala = max(objetivo, {"kcal": 150, "proteinas": 10, "carbohidratos": 15, "grasas": 6}[k])
        exceso = max(aporte.get(k, 0) - objetivo, 0)
        defecto = max(objetivo - aporte.get(k, 0), 0)
        err += w * ((exceso * 1.5 + defecto) / escala) ** 2  # pasarse penaliza más que quedarse corto
    return err


def sugerir_platos(hueco: dict, platos: list[dict], n: int = 5, fraccion_dia: float = 1.0) -> list[dict]:
    """Platos que mejor encajan en `hueco` (macros que faltan, quizá escalados a
    la fracción del día que representa esta comida). Cada plato: `id`, `nombre`,
    `densidad` (macros por 100 g), `gramos_min`, `gramos_max`, `gramos_base`."""
    objetivo = {k: max(v, 0) * fraccion_dia for k, v in hueco.items()}
    if objetivo.get("kcal", 0) < 50:
        return []
    candidatos = []
    for p in platos:
        d = p["densidad"]
        if not d.get("kcal"):
            continue
        ideal = objetivo["kcal"] / d["kcal"] * 100
        gramos = max(p["gramos_min"], min(p["gramos_max"], ideal))
        gramos = round(gramos / 5) * 5
        aporte = escalar(d, gramos / 100)
        candidatos.append({
            "id": p["id"], "nombre": p["nombre"], "franja": p.get("franja"), "gramos": gramos,
            "aporte": redondear(aporte), "puntuacion": round(_error_relativo(aporte, objetivo), 3),
        })
    candidatos.sort(key=lambda c: c["puntuacion"])
    return candidatos[:n]


def sugerir_ingredientes(hueco: dict, ingredientes: list[dict], n: int = 5) -> list[dict]:
    """Ingredientes sueltos para cubrir el macro que más falta (en proporción a
    su objetivo) sin pasarse de las kcal restantes."""
    kcal_rest = hueco.get("kcal", 0)
    if kcal_rest < 40:
        return []
    deficits = {k: hueco.get(k, 0) for k in ("proteinas", "carbohidratos", "grasas")}
    if max(deficits.values()) <= 0:
        return []
    # El macro que falta más en kcal equivalentes
    kcal_eq = {"proteinas": deficits["proteinas"] * 4, "carbohidratos": deficits["carbohidratos"] * 4, "grasas": deficits["grasas"] * 9}
    clave = max(kcal_eq, key=kcal_eq.get)
    out = []
    for ing in ingredientes:
        kcal100 = ing.get("kcal_100g") or 0
        macro100 = ing.get(f"{clave}_100g") or 0
        if kcal100 <= 0 or macro100 <= 0:
            continue
        densidad = macro100 * (9 if clave == "grasas" else 4) / kcal100  # fracción de kcal que aporta ese macro
        gramos_para_macro = deficits[clave] / macro100 * 100
        gramos_por_kcal = kcal_rest / kcal100 * 100
        gramos = max(10, min(gramos_para_macro, gramos_por_kcal))
        if gramos > MAX_GRAMOS_EXTRA:  # una ración razonable de un alimento suelto
            continue
        gramos = round(gramos / 5) * 5
        out.append({"id": ing["id"], "nombre": ing["nombre"], "macro": clave, "gramos": gramos,
                    "aporte": redondear(macros_por_cantidad(ing, gramos)), "densidad": round(densidad, 3)})
    out.sort(key=lambda x: -x["densidad"])
    return out[:n]
