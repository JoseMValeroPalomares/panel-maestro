"""Categoría propuesta para un enlace nuevo del Baúl (la extensión la pide al abrir el popup: GET /api/ext/categoria).

Por orden, la primera pista que haya:
  1. el enlace ya está en el Baúl → su categoría (segura);
  2. vídeo de YouTube cuyo canal está en el Baúl, u otros vídeos de ese canal → esa categoría (segura);
  3. otras páginas de la misma web → la categoría más repetida (segura si todas coinciden y hay al menos dos);
  4. palabras del título: el nombre de una categoría o las palabras de los títulos que ya tiene (no segura).
Sin pista → None: la extensión deja elegirla a mano.
"""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlsplit

_PALABRA = re.compile(r"[a-z0-9ñ]+")
# Lo que añaden las webs al título y no dice nada del tema
_SUFIJO = re.compile(r"\s*[-|·–—]\s*(youtube|wikipedia|github|medium|reddit)\b.*$", re.IGNORECASE)
_VACIAS_TXT = """
    a al algo ante como con cual cuando de del desde donde el ella ellos en entre era es esa ese eso esta este esto
    fue ha hay la las le lo los mas me mi mis muy nada ni no nos o para pero por que quien se ser si sin sobre son su
    sus te tiene todo tu un una uno unos y ya yo vs video videos parte capitulo episodio curso tutorial explicado
    the and for with from this that your you are how what why when who into about of to in on is it its by an or be
    part episode video full new best guide www com net org http https html index home inicio mejor mejores
    gratis free online lab community friends dot oficial official channel canal
"""
_VACIAS = frozenset(_VACIAS_TXT.split())


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower().replace("ñ", "\0"))
    return "".join(c for c in t if not unicodedata.combining(c)).replace("\0", "ñ")


def palabras(texto: str, minimo: int = 3) -> list[str]:
    return [p for p in _PALABRA.findall(normalizar(texto)) if len(p) >= minimo and p not in _VACIAS and not p.isdigit()]


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    except ValueError:
        return ""


def _mayoria(cats: list[str]):
    """(categoría más repetida, cuántas veces, total) o None."""
    if not cats:
        return None
    (cat, n), total = Counter(cats).most_common(1)[0], len(cats)
    return cat, n, total


def _parecidas(p: str, n: str) -> bool:
    """Misma palabra, o singular/plural («matemática» ↔ «Matemáticas»)."""
    return p == n or (min(len(p), len(n)) >= 5 and (p.startswith(n) or n.startswith(p)))


def vocabulario_notas(conn, categorias) -> tuple[dict, dict]:
    """De las notas cuya categoría empieza por una del Baúl («Física - Óptica» → «Fisica»): sus títulos y etiquetas
    como palabras de esa categoría, y los nombres de las subcategorías como palabras fuertes. Las cifradas no cuentan."""
    por_nombre = {}
    for c in categorias:
        for p in palabras(c, 2):
            por_nombre.setdefault(p, c)
    textos: dict[str, list[str]] = defaultdict(list)
    fuertes: dict[str, set] = defaultdict(set)
    for n in conn.execute("SELECT title, tags, category FROM notes WHERE COALESCE(encrypted, 0) = 0"):
        partes = [x for x in re.split(r"\s*(?:-|->|/|›)\s*", n["category"] or "") if x.strip()]
        if not partes:
            continue
        raiz = palabras(partes[0], 2)
        cat = next((c for p in raiz for k, c in por_nombre.items() if _parecidas(p, k)), None)
        if not cat:
            continue
        textos[cat].append(f"{n['title'] or ''} {n['tags'] or ''}")
        for sub in partes[1:]:
            fuertes[cat].update(palabras(sub, 4))
    return textos, fuertes


def por_texto(titulo: str, filas, notas: tuple[dict, dict] | None = None) -> dict | None:
    """Puntúa cada categoría con las palabras del título: su nombre y los de las subcategorías de las notas (fuertes) y
    las palabras de lo que ya tiene (títulos, descripciones, canales y títulos de notas), pesadas por lo raras que son
    entre categorías (tipo tf-idf). Hace falta una palabra fuerte o dos normales: una sola palabra suelta engaña."""
    titulo = _SUFIJO.sub("", titulo or "")
    nuevas = set(palabras(titulo, 2))
    if not nuevas:
        return None
    textos_notas, fuertes_notas = notas or ({}, {})
    por_cat: dict[str, Counter] = defaultdict(Counter)
    for f in filas:
        cat = f["category"] or "General"
        por_cat[cat].update(set(palabras(f"{f['title'] or ''} {f['description'] or ''} {f['channel'] or ''}")))
    for cat, textos in textos_notas.items():
        if cat in por_cat:
            for t in textos:
                por_cat[cat].update(set(palabras(t)))
    if not por_cat:
        return None
    df = Counter(p for cnt in por_cat.values() for p in cnt)
    n_cats = len(por_cat)
    puntos: dict[str, float] = {}
    motivos: dict[str, list[str]] = {}
    for cat, cnt in por_cat.items():
        nombre = set(palabras(cat, 2))
        sub = fuertes_notas.get(cat, set())
        s, usadas, fuerte = 0.0, [], False
        for p in nuevas:
            if any(_parecidas(p, n) for n in nombre):  # el nombre de la categoría pesa mucho
                s, fuerte = s + 4.0, True
                usadas.append(p)
            elif len(p) >= 4 and any(_parecidas(p, n) for n in sub):  # «óptica» → Física (subcategoría de las notas)
                s, fuerte = s + 3.0, True
                usadas.append(p)
            elif cnt[p] and len(p) >= 4:
                s += math.log1p(cnt[p]) * (math.log((1 + n_cats) / df[p]) + 0.1)
                usadas.append(p)
        if s and (fuerte or len(usadas) >= 2):
            puntos[cat], motivos[cat] = s, usadas
    if not puntos:
        return None
    orden = sorted(puntos.items(), key=lambda kv: -kv[1])
    mejor, s1 = orden[0]
    s2 = orden[1][1] if len(orden) > 1 else 0.0
    if s1 < 1.0 or s1 < 1.4 * s2:  # poca pista o empate: mejor que la elijas tú
        return None
    return {"category": mejor, "certain": False, "source": "texto", "words": sorted(motivos[mejor])[:4]}


def sugerir(
    conn, url: str, title: str = "", channel_cat: str | None = None, channel_name: str = "", video=None
) -> dict:
    """channel_cat: categoría del canal si está guardado en el Baúl (la busca app/extension.py); video: fila del Baúl si
    el enlace es un vídeo ya guardado."""
    url = (url or "").strip()
    fila = video or (conn.execute("SELECT category FROM resources WHERE url=?", (url,)).fetchone() if url else None)
    if fila:
        cat = fila["category"] or "General"
        return {"category": cat, "certain": True, "source": "baul", "reason": "Ya está en el Baúl"}
    if channel_cat:
        return {"category": channel_cat, "certain": True, "source": "canal", "reason": "Su canal está en esa categoría"}
    filas = conn.execute("SELECT url, title, description, channel, category FROM resources").fetchall()
    if channel_name.strip():
        nombre = normalizar(channel_name.strip())
        m = _mayoria([f["category"] or "General" for f in filas if f["channel"] and normalizar(f["channel"]) == nombre])
        if m:
            cat, n, total = m
            return {
                "category": cat,
                "certain": n == total,
                "source": "canal",
                "reason": f"Otros vídeos de {channel_name.strip()} están ahí",
            }
    host = _host(url)
    if host and not host.endswith(("youtube.com", "youtu.be")):
        m = _mayoria([f["category"] or "General" for f in filas if _host(f["url"]) == host])
        if m:
            cat, n, total = m
            return {
                "category": cat,
                "certain": n == total and n >= 2,
                "source": "web",
                "reason": f"Otras páginas de {host} están ahí",
            }
    notas = vocabulario_notas(conn, {f["category"] or "General" for f in filas})
    t = por_texto(title, filas, notas)
    if t:
        t["reason"] = "Por el título: " + ", ".join(t.pop("words"))
        return t
    return {"category": None, "certain": False, "source": None, "reason": "Sin pistas: elígela tú"}
