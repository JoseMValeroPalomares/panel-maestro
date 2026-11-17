"""comidas/pasos.py — pasos de receta escritos a mano (P-10): partir un texto pegado en pasos, detectar los tiempos
(«10 min», «3-4 minutos», «1 h 30 min», «media hora») y qué ingredientes de la receta nombra cada paso. Python puro,
sin IA ni dependencias: lo usan el editor (vista previa al pegar) y el modo cocina."""

import re
import unicodedata

MAX_PASOS = 100
MAX_SEGUNDOS = 24 * 3600

_VINETA = re.compile(r"^\s*(?:[-*•·–—]+|\(?\d{1,2}[.)º°:-]|paso\s*\d{1,2}\s*[:.)-]?)\s*", re.I)
# «1.», «2)», «Paso 3:» delante de un paso (también en mitad de una línea: «1. Corta… 2. Fríe…»)
_MARCA = re.compile(r"(?:^|(?<=\s))(?:paso\s*(\d{1,2})\s*[:.)-]?|(\d{1,2})[.)])\s+(?=\S)", re.I)


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _marcas_en_orden(texto: str) -> list[re.Match]:
    """Las marcas que siguen la secuencia 1, 2, 3… (así «cuece 2. Luego» o «1.5 kg» no parten nada)."""
    elegidas: list[re.Match] = []
    for m in _MARCA.finditer(texto):
        n = int(m.group(1) or m.group(2))
        if n == len(elegidas) + 1:
            elegidas.append(m)
    return elegidas if len(elegidas) >= 2 else []


def partir(texto: str) -> list[str]:
    """Texto libre → lista de pasos. Si viene numerado («1.», «2)», «Paso 3:»), parte por los números aunque estén en
    la misma línea; si no, un paso por línea. Quita viñetas y líneas vacías."""
    texto = (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not texto:
        return []
    marcas = _marcas_en_orden(texto)
    if marcas:
        trozos = []
        if marcas[0].start() > 0 and texto[: marcas[0].start()].strip():
            trozos.append(texto[: marcas[0].start()])  # lo de antes del «1.» (un título, una nota) se queda
        for i, m in enumerate(marcas):
            fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
            trozos.append(texto[m.end() : fin])
    else:
        trozos = texto.split("\n")
    pasos = []
    for t in trozos:
        t = " ".join(_VINETA.sub("", t, count=1).split()) if not marcas else " ".join(t.split())
        if t:
            pasos.append(t[:2000])
    return pasos[:MAX_PASOS]


# ── Tiempos ────────────────────────────────────────────────────────────
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIDAD = r"(horas?|hrs?|h|minutos?|mins?|min|m|segundos?|segs?|seg|s|')"
_DURACION = re.compile(rf"{_NUM}(?:\s*(?:-|–|a|o|ó|y)\s*{_NUM})?\s*{_UNIDAD}(?![a-zñ])")
_PALABRAS = [
    (re.compile(r"\bhora y media\b"), 5400),
    (re.compile(r"\bhora y cuarto\b"), 4500),
    (re.compile(r"\bmedia hora\b"), 1800),
    (re.compile(r"\b(?:un )?cuarto de hora\b"), 900),
    (re.compile(r"\buna hora\b"), 3600),
    (re.compile(r"\bun par de minutos\b"), 120),
    (re.compile(r"\bun minuto\b"), 60),
    (re.compile(r"\bmedio minuto\b"), 30),
]


def _a_segundos(valor: str, unidad: str) -> int:
    v = float(valor.replace(",", "."))
    if unidad.startswith("h"):
        return round(v * 3600)
    if unidad.startswith("s"):
        return round(v)
    return round(v * 60)  # min, m, '


def tiempos(paso: str) -> list[int]:
    """Duraciones (en segundos) que nombra un paso, en orden y sin repetir. Un rango («3-4 minutos») cuenta por lo
    largo; «1 h 30 min» o «1 hora y 30 minutos» son una sola duración."""
    t = _sin_tildes(paso or "")
    hallados: list[tuple[int, int, int]] = []  # (inicio, fin, segundos)
    for m in _DURACION.finditer(t):
        unidad = m.group(3)
        # «m» y «s» sueltas solo detrás de un número pegado («10m», «30s»): «2 s» o «5 m» en una frase son raras
        if unidad in ("m", "s") and m.group(0)[-2:-1] == " ":
            continue
        valor = m.group(2) or m.group(1)
        hallados.append((m.start(), m.end(), _a_segundos(valor, unidad)))
    for patron, seg in _PALABRAS:
        for m in patron.finditer(t):
            if not any(m.start() < b and a < m.end() for a, b, _ in hallados):  # «una hora y media» es una
                hallados.append((m.start(), m.end(), seg))
    hallados.sort()
    out: list[int] = []
    prev_fin, prev_seg = -10, 0
    for ini, fin, seg in hallados:
        # «1 h 30 min»: la segunda va pegada a la primera (como mucho « y ») y es una unidad menor
        if out and ini - prev_fin <= 3 and seg < prev_seg and re.fullmatch(r"\s*(?:y\s*)?", t[prev_fin:ini]):
            out[-1] += seg
        else:
            out.append(seg)
        prev_fin, prev_seg = fin, seg
    vistos, unicos = set(), []
    for s in out:
        if 0 < s <= MAX_SEGUNDOS and s not in vistos:
            vistos.add(s)
            unicos.append(s)
    return unicos


# ── Ingredientes de cada paso ──────────────────────────────────────────
_VACIAS = {
    "de", "del", "la", "el", "los", "las", "con", "sin", "en", "y", "o", "a", "al", "para", "por", "un", "una",
    "fresco", "fresca", "frescos", "frescas", "natural", "naturales", "entero", "entera", "desnatado", "desnatada",
    "semidesnatado", "semidesnatada", "integral", "integrales", "blanco", "blanca", "rallado", "rallada", "cocido",
    "cocida", "light", "virgen", "extra", "normal", "tipo", "bote", "lata", "congelado", "congelada", "polvo",
    "molido", "molida", "picado", "picada", "troceado", "troceada", "grande", "pequeno", "pequena", "medio", "media",
}  # fmt: skip
_PALABRA = re.compile(r"[a-zñ]+")


def _clave(nombre: str) -> list[str]:
    return [w for w in _PALABRA.findall(_sin_tildes(nombre)) if len(w) >= 3 and w not in _VACIAS]


def _misma(a: str, b: str) -> bool:
    return a == b or a + "s" == b or b + "s" == a or a + "es" == b or b + "es" == a


def ingredientes_del_paso(paso: str, nombres: list[str]) -> list[int]:
    """Índices de los ingredientes (de esa receta) que el paso nombra: basta una palabra con significado del nombre
    («Pechuga de pollo» ↔ «dora el pollo»; singular o plural)."""
    palabras = set(_PALABRA.findall(_sin_tildes(paso or "")))
    out = []
    for i, nombre in enumerate(nombres):
        if any(_misma(c, w) for c in _clave(nombre) for w in palabras):
            out.append(i)
    return out


def describir(pasos: list[str], nombres: list[str] | None = None) -> list[dict]:
    """Cada paso con sus tiempos y, si se dan los nombres de los ingredientes, los que nombra."""
    return [
        {"texto": p, "tiempos": tiempos(p), **({"ingredientes": ingredientes_del_paso(p, nombres)} if nombres else {})}
        for p in pasos
    ]
