"""
Diseño radial automático del grafo («Generar grafo automático»). Función pura: sin BD ni red.

    disenar(nodos, aristas, fijados=None) -> {id: (x, y)}

Entrada = lo que devuelve /api/graph: nodos `type` category|note (con `depth`, `group`, `label`) y aristas `type: category`
(padre → hijo). Reglas:
  · Cada categoría RAÍZ es un grupo con su propio círculo; entre grupos queda un hueco (GAP_GRUPOS).
  · El grupo mayor (subcategorías + notas) va al centro; los demás, en anillos alrededor: cuanto mayor, más cerca del centro.
  · Dentro de un grupo: la raíz en su centro; subcategorías y notas en anillos de profundidad creciente (la nota, en el anillo
    siguiente al de su categoría, dentro del sector de ésta). Cada nodo recibe un sector proporcional a su peso.
  · «Independientes» = notas sin categoría (la raíz ficticia «Sin categoría» de /api/graph): anillo(s) exterior(es), por título.
  · Sin solapes: cajas de nodo+etiqueta (`caja`) y una relajación con rejilla; `fijados` (posiciones que el usuario quiere
    conservar) no se mueven y los demás los esquivan.
"""
import math
from collections import defaultdict

GAP_GRUPOS = 170.0      # hueco mínimo entre los círculos de dos grupos
PASO_ANILLO = 100.0     # distancia mínima entre anillos de profundidad consecutivos
COMPACTAR = 0.5         # los anillos «holgados» se aprietan y la relajación separa solo lo que se pisa
MARGEN = 8.0            # margen entre cajas
SIN_CATEGORIA = "sin categoría"


def _lineas(label: str) -> list[str]:
    """Mismo ajuste de línea que graph.js:wrapLabel (18 caracteres)."""
    if len(label) <= 18:
        return [label]
    out, cur = [], ""
    for w in label.split(" "):
        if len((cur + w).strip()) > 18:
            out.append(cur.strip())
            cur = w + " "
        else:
            cur += w + " "
    if cur.strip():
        out.append(cur.strip())
    return out


def caja(nodo: dict) -> tuple[float, float]:
    """Ancho y alto (px) de la caja de un nodo con su etiqueta, como las dibuja graph.js. En las notas la etiqueta cuelga
    BAJO el punto, así que la caja se simetriza respecto al punto (alto = 2 × lo que baja la etiqueta): conservador."""
    label = nodo.get("label") or ""
    if nodo.get("type") == "category":
        return min(260.0, 24 + 9.5 * len(label)), 44.0
    lineas = _lineas(label)
    ancho = max(40.0, 7.4 * max(len(x) for x in lineas) + 10)
    return min(160.0, ancho), 2 * (17 + 16.0 * len(lineas))


def disenar(nodos: list[dict], aristas: list[dict], fijados: dict[str, tuple[float, float]] | None = None) -> dict[str, tuple[float, float]]:
    por_id = {n["id"]: n for n in nodos}
    hijos: dict[str, list[str]] = defaultdict(list)
    tiene_padre = set()
    for e in aristas:
        if e.get("type") == "category" and e["from"] in por_id and e["to"] in por_id:
            hijos[e["from"]].append(e["to"])
            tiene_padre.add(e["to"])
    raices = [n["id"] for n in nodos if n["type"] == "category" and n["id"] not in tiene_padre]
    independientes = [n["id"] for n in nodos if n["type"] == "note" and n["id"] not in tiene_padre]
    for r in list(raices):  # la raíz «Sin categoría» no es un grupo: sus notas son independientes
        if (por_id[r].get("label") or "").strip().lower() == SIN_CATEGORIA:
            independientes += [h for h in hijos[r] if por_id[h]["type"] == "note"]
            raices.remove(r)
            for h in hijos[r]:
                if por_id[h]["type"] == "category":
                    raices.append(h)
    titulo = lambda i: (por_id[i].get("label") or "").lower()  # noqa: E731

    peso_cache: dict[str, int] = {}

    def peso(i: str) -> int:
        """Notas del subárbol (mínimo 1): reparte los sectores."""
        if i not in peso_cache:
            h = hijos.get(i, [])
            peso_cache[i] = 1 if por_id[i]["type"] == "note" else max(1, sum(peso(x) for x in h))
        return peso_cache[i]

    def tamano(i: str) -> int:
        """Subcategorías + notas del grupo: decide quién va al centro."""
        return 1 + sum(tamano(x) for x in hijos.get(i, []))

    def ordenar(i: str) -> list[str]:
        h = hijos.get(i, [])
        return sorted([x for x in h if por_id[x]["type"] == "category"], key=lambda x: (-tamano(x), titulo(x))) + sorted([x for x in h if por_id[x]["type"] == "note"], key=titulo)

    # ── 1. Cada grupo en coordenadas locales (raíz en 0,0) ──
    grupos = []
    for r in sorted(raices, key=lambda x: (-tamano(x), titulo(x))):
        pos = {i: (x * COMPACTAR, y * COMPACTAR) for i, (x, y) in _disenar_grupo(r, por_id, ordenar, peso).items()}
        _relajar(pos, por_id, {r}, 200)  # la raíz queda en el centro del grupo
        radio = max((math.hypot(p[0], p[1]) + 0.5 * math.hypot(*caja(por_id[i])) for i, p in pos.items()), default=60.0)
        grupos.append({"raiz": r, "pos": pos, "radio": radio + GAP_GRUPOS / 2, "tam": tamano(r)})

    # ── 2. Grupos: el mayor al centro, los demás en anillos (mayor = más cerca) ──
    centros = _colocar_grupos(grupos)
    final: dict[str, tuple[float, float]] = {}
    extension = 0.0
    for g, (cx, cy) in zip(grupos, centros):
        for i, (x, y) in g["pos"].items():
            final[i] = (x + cx, y + cy)
        extension = max(extension, math.hypot(cx, cy) + g["radio"])

    # ── 3. Independientes: anillo(s) exterior(es) ordenados por título ──
    if independientes:
        independientes.sort(key=titulo)
        paso = 170.0
        r = max(extension + 40.0, 240.0)
        resto = list(independientes)
        while resto:
            capacidad = max(1, int(2 * math.pi * r / paso))
            tanda, resto = resto[:capacidad], resto[capacidad:]
            for k, i in enumerate(tanda):
                a = -math.pi / 2 + 2 * math.pi * k / len(tanda)
                final[i] = (r * math.cos(a), r * math.sin(a))
            r += 95.0

    # ── 4. Fijados: se respetan y los demás los esquivan ──
    inmov = set()
    for i, p in (fijados or {}).items():
        if i in final:
            final[i] = (float(p[0]), float(p[1]))
            inmov.add(i)
    _relajar(final, por_id, inmov)
    return {i: (round(x, 1), round(y, 1)) for i, (x, y) in final.items()}


def _disenar_grupo(raiz: str, por_id: dict, ordenar, peso) -> dict[str, tuple[float, float]]:
    """Radial por sectores: la raíz en 0,0; cada nivel de profundidad en su anillo."""
    sectores: dict[str, tuple[float, float, int]] = {raiz: (0.0, 2 * math.pi, 0)}
    por_nivel: dict[int, list[str]] = defaultdict(list)
    pila = [raiz]
    while pila:
        i = pila.pop()
        a0, a1, d = sectores[i]
        hs = ordenar(i)
        total = sum(peso(h) for h in hs) or 1
        a = a0
        for h in hs:
            ancho = (a1 - a0) * peso(h) / total
            sectores[h] = (a, a + ancho, d + 1)
            por_nivel[d + 1].append(h)
            a += ancho
            pila.append(h)
    radios = {0: 0.0}
    for d in sorted(por_nivel):
        necesario = radios[d - 1] + PASO_ANILLO
        for h in por_nivel[d]:
            a0, a1, _ = sectores[h]
            w, hh = caja(por_id[h])
            ancho = a1 - a0
            if 0 < ancho < math.pi:
                ang = (a0 + a1) / 2 - math.pi / 2
                # longitud de la caja proyectada sobre la tangente del anillo (más corta arriba/abajo que a los lados)
                tangencial = w * abs(math.sin(ang)) + hh * abs(math.cos(ang)) + MARGEN * 2
                necesario = max(necesario, tangencial / ancho)
        radios[d] = necesario
    pos = {raiz: (0.0, 0.0)}
    for h, (a0, a1, d) in sectores.items():
        if h != raiz:
            a = (a0 + a1) / 2 - math.pi / 2
            pos[h] = (radios[d] * math.cos(a), radios[d] * math.sin(a))
    return pos


def _colocar_grupos(grupos: list[dict]) -> list[tuple[float, float]]:
    """El primero (mayor) en el centro; los demás en anillos concéntricos, de mayor a menor hacia fuera."""
    if not grupos:
        return []
    centros = [(0.0, 0.0)]
    resto = list(range(1, len(grupos)))
    base = grupos[0]["radio"]
    while resto:
        r_max = grupos[resto[0]]["radio"]
        r = base + r_max
        miembros: list[int] = []
        # añade grupos mientras quepan en la circunferencia; si un grupo solo no cabe, se agranda el anillo
        while resto:
            cand = miembros + [resto[0]]
            ang = sum(2 * math.asin(min(1.0, grupos[k]["radio"] / max(r, grupos[k]["radio"] + 1))) for k in cand)
            if ang <= 2 * math.pi or not miembros:
                miembros.append(resto.pop(0))
                r_max = max(r_max, grupos[miembros[-1]]["radio"])
                r = max(r, base + r_max)
            else:
                break
        angulos = [2 * math.asin(min(1.0, grupos[k]["radio"] / r)) for k in miembros]
        sobra = (2 * math.pi - sum(angulos)) / len(miembros)
        a = -math.pi / 2
        for k, w in zip(miembros, angulos):
            a_c = a + w / 2
            centros.append((r * math.cos(a_c), r * math.sin(a_c)))
            a += w + sobra
        base = r + r_max
    return centros


def _relajar(pos: dict[str, tuple[float, float]], por_id: dict, inmoviles: set[str], max_pasadas: int = 80) -> None:
    """Separa cajas solapadas (rejilla espacial). Modifica `pos` en sitio."""
    ids = list(pos)
    medias = {i: tuple(c / 2 + MARGEN / 2 for c in caja(por_id[i])) for i in ids}
    celda = 200.0
    for _ in range(max_pasadas):
        rejilla: dict[tuple[int, int], list[str]] = defaultdict(list)
        for i in ids:
            x, y = pos[i]
            rejilla[(int(x // celda), int(y // celda))].append(i)
        movido = False
        visto = set()
        for (cx, cy), lista in rejilla.items():
            vecinos = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in rejilla.get((cx + dx, cy + dy), [])]
            for i in lista:
                for j in vecinos:
                    if i >= j or (i, j) in visto:
                        continue
                    visto.add((i, j))
                    xi, yi = pos[i]
                    xj, yj = pos[j]
                    ox = medias[i][0] + medias[j][0] - abs(xi - xj)
                    oy = medias[i][1] + medias[j][1] - abs(yi - yj)
                    if ox <= 0 or oy <= 0:
                        continue
                    if i in inmoviles and j in inmoviles:
                        continue
                    movido = True
                    fi = 0.0 if i in inmoviles else (1.0 if j in inmoviles else 0.5)
                    fj = 1.0 - fi
                    if ox < oy:  # separar por el eje de menor solape
                        d = (1 if xi >= xj else -1) * (ox + 0.5)
                        pos[i] = (xi + d * fi, yi)
                        pos[j] = (xj - d * fj, yj)
                    else:
                        d = (1 if yi >= yj else -1) * (oy + 0.5)
                        pos[i] = (xi, yi + d * fi)
                        pos[j] = (xj, yj - d * fj)
        if not movido:
            return


def solapes(pos: dict[str, tuple[float, float]], por_id: dict) -> list[tuple[str, str]]:
    """Pares de cajas que se pisan (para tests y diagnóstico)."""
    out = []
    ids = list(pos)
    for a in range(len(ids)):
        wa, ha = caja(por_id[ids[a]])
        for b in range(a + 1, len(ids)):
            wb, hb = caja(por_id[ids[b]])
            if abs(pos[ids[a]][0] - pos[ids[b]][0]) < (wa + wb) / 2 and abs(pos[ids[a]][1] - pos[ids[b]][1]) < (ha + hb) / 2:
                out.append((ids[a], ids[b]))
    return out
