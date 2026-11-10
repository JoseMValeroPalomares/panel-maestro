"""
Validación de lo que devuelve la IA al corregir una nota. Funciones puras (sin red ni BD): se usan igual en el
servicio, en el script de evaluación de modelos (scripts/evaluar_modelos.py) y en los tests.

`validar(original, corregido, titulos)` devuelve la lista de problemas (vacía = válida). Reglas, todas sobre la
sintaxis real del editor (static/js/cerebro.js, app/notes_core.py:sync_flashcards, app/note_tasks.py):
  · Bloques ``` (código, sim, calendario) equilibrados; mismo número de bloques sim/calendario y de <script>.
  · Fórmulas $…$ / $$…$$: ninguna menos que antes, llaves y \\left/\\right equilibradas.
  · Tablas: misma cantidad, con separador y el mismo número de columnas en todas las filas.
  · Enlaces [[wiki]]: los nuevos solo a notas existentes; los marcadores [[tarea:N]] intactos.
  · Sin etiquetas: ni #hashtags nuevos, ni «tags:», ni líneas «Etiquetas:».
  · Longitud razonable; todos los números del original siguen; sin números inventados.
  · Flashcards (`pregunta >> respuesta`), casillas `- [ ]`/`- [x]` y anotaciones {{tipo:…}}: no se pierden ni cambian de estado.
  · Sin frontmatter ni envoltorio ```markdown. Las dudas van como `<!-- REVISAR: … -->`.
"""
import re

FENCE = re.compile(r"^[ \t]*(```|~~~)", re.M)
BLOQUE = re.compile(r"(^|\n)([ \t]*)(```|~~~)([^\n]*)\n(.*?)(\n[ \t]*\3[ \t]*(?=\n|$))", re.S)
MATH_BLOCK = re.compile(r"\$\$([\s\S]+?)\$\$")
MATH_INLINE = re.compile(r"\$([^\$\n]+?)\$")
WIKI = re.compile(r"\[\[(.+?)\]\]")
ITEM_LINK = re.compile(r"\[\[(?:tarea|idea|rutina|item):\d+\]\]")
ANOT = re.compile(r"\{\{(resumir|entender|mal):")
TASK = re.compile(r"^\s*[-*] \[([ xX])\]", re.M)
FLASH = re.compile(r"^\s*(.+?)\s*>>\s*(.+?)\s*$", re.M)
HASHTAG = re.compile(r"(?<![\w&#/\[(])#(?!\d+\b)[^\W\d][\w-]*", re.U)
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")
COMENTARIO_OK = re.compile(r"<!--\s*REVISAR:.*?-->", re.S)


def slugify(texto: str) -> str:
    """Igual que app/notes_core.py:slugify y el front: minúsculas y guiones, CONSERVANDO los acentos (un enlace sin
    acento no llega a la nota)."""
    return re.sub(r"\s+", "-", texto.strip().lower().replace("/", "-"))


def quitar_envoltorio(texto: str) -> str:
    """Si el modelo envolvió toda la respuesta en ```markdown … ```, lo quita."""
    t = texto.strip("\n")
    m = re.match(r"^```(?:markdown|md)[ \t]*\n(.*)\n```[ \t]*$", t, re.S)
    return m.group(1) if m else t


def _sin_codigo(texto: str) -> str:
    return BLOQUE.sub(lambda m: m.group(1), texto)


def _formulas(texto: str) -> list[str]:
    t = _sin_codigo(texto)
    bloques = MATH_BLOCK.findall(t)
    t = MATH_BLOCK.sub(" ", t)
    return [b.strip() for b in bloques] + [i.strip() for i in MATH_INLINE.findall(t)]


def _formula_rota(f: str) -> str | None:
    if f.count("{") - f.count("\\{") != f.count("}") - f.count("\\}"):
        return "llaves sin cerrar"
    if len(re.findall(r"\\left\b", f)) != len(re.findall(r"\\right\b", f)):
        return "\\left/\\right descompensados"
    if len(re.findall(r"\\begin\{", f)) != len(re.findall(r"\\end\{", f)):
        return "\\begin/\\end descompensados"
    return None


def _tablas(texto: str) -> list[list[str]]:
    t = _sin_codigo(texto)
    out, cur = [], []
    for linea in t.split("\n"):
        if linea.strip().startswith("|"):
            cur.append(linea.strip())
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _columnas(fila: str) -> int:
    f = fila.strip()
    f = f[1:] if f.startswith("|") else f
    f = f[:-1] if f.endswith("|") and not f.endswith("\\|") else f
    return len(re.split(r"(?<!\\)\|", f))


def _tabla_rota(tabla: list[str]) -> str | None:
    if len(tabla) < 2 or not re.fullmatch(r"\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?", tabla[1]):
        return "sin fila separadora"
    n = _columnas(tabla[0])
    if any(_columnas(f) != n for f in tabla):
        return "filas con distinto número de columnas"
    return None


def _numeros(texto: str) -> list[str]:
    t = _sin_codigo(texto)
    t = re.sub(r"^\s*\d+[.)]\s", "", t, flags=re.M)  # numeración de listas
    t = re.sub(r"^#{1,6}\s*\d+[.)]?\s", "", t, flags=re.M)
    t = ITEM_LINK.sub(" ", t)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    return [n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n for n in NUM.findall(t)]


def _codigo(texto: str) -> list[tuple[str, str]]:
    return [(m.group(4).strip().lower(), m.group(5)) for m in BLOQUE.finditer(texto)]


def validar(original: str, corregido: str, titulos: dict[str, str] | set[str] | None = None) -> list[str]:
    """Problemas encontrados (en español, para mostrarlos). `titulos`: ids (slug) de notas existentes."""
    p: list[str] = []
    c = corregido
    if not c.strip():
        return ["La respuesta está vacía"]
    if c.lstrip().startswith("---") and not original.lstrip().startswith("---"):
        p.append("Añade un bloque de metadatos (---) que no estaba")
    if re.search(r"^\s*(tags?|etiquetas?)\s*:", c, re.I | re.M) and not re.search(r"^\s*(tags?|etiquetas?)\s*:", original, re.I | re.M):
        p.append("Añade etiquetas")

    # Longitud: ni recorta ni inventa grandes bloques
    lo, ln = len(original.strip()), len(c.strip())
    if lo >= 400:
        if ln < lo * 0.75:
            p.append(f"Recorta demasiado ({ln} de {lo} caracteres)")
        elif ln > lo * 1.35:
            p.append(f"Añade demasiado texto ({ln} de {lo} caracteres)")
    elif ln > lo * 2.5 + 150 or ln < lo * 0.4:
        p.append("Longitud muy distinta de la original")

    # Bloques de código
    if len(FENCE.findall(c)) % 2:
        p.append("Bloque de código sin cerrar")
    co, cc = _codigo(original), _codigo(c)
    for lang in ("sim", "calendario"):
        a, b = [x for x in co if x[0] == lang], [x for x in cc if x[0] == lang]
        if len(a) != len(b):
            p.append(f"Cambia el número de bloques «{lang}» ({len(a)} → {len(b)})")
        else:
            for (_, x), (_, y) in zip(a, b):
                if x.lower().count("<script") != y.lower().count("<script") or x.lower().count("</script") != y.lower().count("</script"):
                    p.append(f"Rompe un bloque «{lang}» (etiquetas <script>)")
                if len(y.strip()) < len(x.strip()) * 0.6 or len(y.strip()) > len(x.strip()) * 1.4 + 40:
                    p.append(f"Reescribe un bloque «{lang}»")
    if len(co) != len(cc) and not any("bloques" in x for x in p):
        p.append(f"Cambia el número de bloques de código ({len(co)} → {len(cc)})")

    # Fórmulas
    fo, fc = _formulas(original), _formulas(c)
    if len(fc) < len(fo):
        p.append(f"Pierde fórmulas ({len(fo)} → {len(fc)})")
    if _sin_codigo(c).replace("$$", "").count("$") % 2:
        p.append("Un «$» sin pareja (fórmula rota)")
    if _sin_codigo(c).count("$$") % 2:
        p.append("Un «$$» sin cerrar")
    for f in fc:
        if f not in fo and (r := _formula_rota(f)):
            p.append(f"Fórmula rota ({r}): {f[:40]}")
            break

    # Tablas
    to, tc = _tablas(original), _tablas(c)
    if len(tc) < len(to):
        p.append(f"Pierde tablas ({len(to)} → {len(tc)})")
    for t in tc:
        if t not in to and (r := _tabla_rota(t)):
            p.append(f"Tabla rota ({r})")
            break

    # Enlaces
    il_o, il_c = sorted(ITEM_LINK.findall(original)), sorted(ITEM_LINK.findall(c))
    if il_o != il_c:
        p.append("Cambia los enlaces a tareas ([[tarea:N]])")
    wo = {slugify(x) for x in WIKI.findall(_sin_codigo(original)) if not ITEM_LINK.fullmatch(f"[[{x}]]")}
    existentes = {slugify(t) for t in (titulos or [])} | {slugify(v) for v in (titulos.values() if isinstance(titulos, dict) else [])}
    if isinstance(titulos, dict):
        existentes |= set(titulos)
    for x in WIKI.findall(_sin_codigo(c)):
        if ITEM_LINK.fullmatch(f"[[{x}]]"):
            continue
        s = slugify(x.split("|")[0])
        if s not in wo and s not in existentes:
            p.append(f"Enlaza a una nota que no existe: [[{x}]]")
            break

    # Etiquetas
    def hashtags(t):
        return len(HASHTAG.findall(re.sub(r"`[^`\n]*`", "", _sin_codigo(t))))
    if hashtags(c) > hashtags(original):
        p.append("Añade etiquetas (#algo)")

    # Datos
    from collections import Counter
    no, nc = Counter(_numeros(original)), Counter(_numeros(c))
    faltan = no - nc
    if faltan:
        p.append("Pierde números del original: " + ", ".join(list(faltan)[:5]))
    nuevos = nc - no
    if sum(nuevos.values()) > 3:
        p.append("Introduce números que no estaban: " + ", ".join(list(nuevos)[:5]))

    # Estructura propia de las notas
    if len(FLASH.findall(_sin_codigo(c))) < len(FLASH.findall(_sin_codigo(original))):
        p.append("Pierde flashcards (pregunta >> respuesta)")
    if [m.upper() for m in TASK.findall(original)] != [m.upper() for m in TASK.findall(c)]:
        p.append("Cambia las casillas de tareas (- [ ])")
    if len(ANOT.findall(c)) < len(ANOT.findall(original)):
        p.append("Pierde anotaciones {{…}}")
    bad = re.sub(COMENTARIO_OK, "", c)
    if "<!--" in bad and "<!--" not in original:
        p.append("Comentarios que no son «<!-- REVISAR: … -->»")
    return p


def validar_estructura(texto: str) -> list[str]:
    """Comprobación mínima para un resultado ya compuesto aceptando solo algunas partes."""
    p = []
    if len(FENCE.findall(texto)) % 2:
        p.append("Bloque de código sin cerrar")
    if _sin_codigo(texto).replace("$$", "").count("$") % 2:
        p.append("Un «$» sin pareja")
    for t in _tablas(texto):
        if r := _tabla_rota(t):
            p.append(f"Tabla rota ({r})")
            break
    return p
