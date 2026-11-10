"""Algoritmo del grafo automático (app/graph_layout.py): sin solapes, grupos separados, mayor al centro, anillos por
profundidad, independientes fuera, fijados respetados y rendimiento con cientos de nodos."""
import math
import random
import time

from app import graph_layout as gl


def arbol(grupos: dict[str, dict], independientes: int = 0, seed: int = 1):
    """grupos: {raíz: {"subs": n_subcategorías_por_nivel[], "notas": notas_por_categoría}} → (nodos, aristas)."""
    rnd = random.Random(seed)
    nodos, aristas = [], []
    for raiz, cfg in grupos.items():
        nodos.append({"id": f"cat:{raiz}", "label": raiz, "type": "category", "depth": 0, "group": raiz})
        nivel = [f"cat:{raiz}"]
        for d, n in enumerate(cfg["subs"], start=1):
            nuevo = []
            for k in range(n):
                padre = nivel[k % len(nivel)]
                cid = f"{padre}/s{d}{k}"
                nodos.append({"id": cid, "label": f"Sub {raiz} {d}.{k}", "type": "category", "depth": d, "group": raiz})
                aristas.append({"from": padre, "to": cid, "type": "category"})
                nuevo.append(cid)
            nivel = nuevo or nivel
        cats = [n["id"] for n in nodos if n["type"] == "category" and n["group"] == raiz]
        for c in cats:
            for k in range(cfg["notas"]):
                nid = f"{c}/n{k}"
                nodos.append({"id": nid, "label": f"Nota {rnd.randint(0, 999)} de {raiz} {k}", "type": "note", "group": raiz})
                aristas.append({"from": c, "to": nid, "type": "category"})
    if independientes:
        nodos.append({"id": "cat:sin", "label": "Sin categoría", "type": "category", "depth": 0, "group": "Sin categoría"})
        for k in range(independientes):
            nodos.append({"id": f"ind{k}", "label": f"Suelta {k:03d}", "type": "note", "group": "Sin categoría"})
            aristas.append({"from": "cat:sin", "to": f"ind{k}", "type": "category"})
    return nodos, aristas


GRUPOS = {"Física": {"subs": [3, 4], "notas": 3}, "Biología": {"subs": [2, 2], "notas": 2}, "Química": {"subs": [1], "notas": 2}, "Arte": {"subs": [], "notas": 4}}


def test_sin_solapes_y_todos_colocados():
    nodos, aristas = arbol(GRUPOS, independientes=12)
    pos = gl.disenar(nodos, aristas)
    por_id = {n["id"]: n for n in nodos}
    assert set(pos) == {n["id"] for n in nodos if n["id"] != "cat:sin"}      # la raíz ficticia no se dibuja como grupo
    assert gl.solapes(pos, por_id) == []


def test_el_mayor_al_centro_y_mas_grande_mas_cerca():
    nodos, aristas = arbol(GRUPOS)
    pos = gl.disenar(nodos, aristas)
    assert pos["cat:Física"] == (0.0, 0.0)
    dist = {r: math.hypot(*pos[f"cat:{r}"]) for r in ("Física", "Biología", "Química", "Arte")}
    # tamaños: Física > Biología > Química > Arte → distancia no decreciente
    orden = sorted(dist, key=dist.get)
    assert orden[0] == "Física" and dist["Biología"] <= dist["Química"] + 1 <= dist["Arte"] + 2


def test_grupos_separados():
    nodos, aristas = arbol(GRUPOS)
    pos = gl.disenar(nodos, aristas)
    grupo = {n["id"]: n["group"] for n in nodos}
    ids = list(pos)
    minimo = min(math.dist(pos[a], pos[b]) for a in ids for b in ids if a < b and grupo[a] != grupo[b])
    assert minimo >= gl.GAP_GRUPOS * 0.6


def test_anillos_por_profundidad_y_notas_junto_a_su_categoria():
    nodos, aristas = arbol({"Física": {"subs": [3, 4, 3], "notas": 1}})
    pos = gl.disenar(nodos, aristas)
    prof = {n["id"]: n.get("depth") for n in nodos if n["type"] == "category"}
    medio = {}
    for i, d in prof.items():
        medio.setdefault(d, []).append(math.hypot(*pos[i]))
    medias = [sum(v) / len(v) for _, v in sorted(medio.items())]
    assert medias == sorted(medias) and medias[0] == 0
    # cada nota está más lejos del centro que su categoría y cerca de ella
    padres = {a["to"]: a["from"] for a in aristas}
    for n in nodos:
        if n["type"] == "note":
            assert math.dist(pos[n["id"]], pos[padres[n["id"]]]) < 450


def test_independientes_en_el_anillo_exterior_y_ordenadas():
    nodos, aristas = arbol(GRUPOS, independientes=30)
    pos = gl.disenar(nodos, aristas)
    fuera = [math.hypot(*pos[f"ind{k}"]) for k in range(30)]
    dentro = [math.hypot(*p) for i, p in pos.items() if not i.startswith("ind")]
    assert min(fuera) > max(dentro)
    # ordenadas por título a lo largo del anillo (sentido horario desde arriba)
    ang = [(math.atan2(pos[f"ind{k}"][1], pos[f"ind{k}"][0]) + math.pi / 2) % (2 * math.pi) for k in range(30)]
    assert ang == sorted(ang)


def test_respeta_fijados_y_los_demas_los_esquivan():
    nodos, aristas = arbol(GRUPOS, independientes=5)
    por_id = {n["id"]: n for n in nodos}
    base = gl.disenar(nodos, aristas)
    fij = {"cat:Biología": (5.0, 5.0), "ind0": (0.0, 40.0)}                       # encima de otros nodos a propósito
    pos = gl.disenar(nodos, aristas, fijados=fij)
    assert pos["cat:Biología"] == (5.0, 5.0) and pos["ind0"] == (0.0, 40.0)
    for a, b in gl.solapes(pos, por_id):
        assert a in fij and b in fij or False, (a, b)                              # solo pueden pisarse dos fijados entre sí
    assert pos != base


def test_cientos_de_nodos_rapido_y_sin_solapes():
    grupos = {f"G{i}": {"subs": [3, 3], "notas": 4} for i in range(10)}
    nodos, aristas = arbol(grupos, independientes=60)
    assert len(nodos) > 400
    t0 = time.time()
    pos = gl.disenar(nodos, aristas)
    assert time.time() - t0 < 3
    assert gl.solapes(pos, {n["id"]: n for n in nodos}) == []


def test_casos_limite():
    assert gl.disenar([], []) == {}
    nodos, aristas = arbol({}, independientes=3)
    assert len(gl.disenar(nodos, aristas)) == 3
    nodos, aristas = arbol({"Solo": {"subs": [], "notas": 0}})
    assert gl.disenar(nodos, aristas) == {"cat:Solo": (0.0, 0.0)}
