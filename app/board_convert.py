"""
Conversión de tableros del formato antiguo (JSON de fabric.js) al formato 2.

Formato 2 (lo que pinta static/js/board.js):
    {"format": 2,
     "nodes":   [{id, kind, x, y, w, h, text, fill, stroke, color, fontSize, group?, inboxId?, itemType?, parentLabel?}],
     "edges":   [{id, from?, to?, p1?, p2?, color, width, head, dashed}],   # from/to = id de nodo (anclada)
     "strokes": [{id, points: [[x, y], ...], color, width}],
     "view":    {x, y, zoom}}

Las flechas no guardan geometría si están ancladas: se calculan desde las cajas.
Se descartan solo restos inválidos del formato antiguo (flecha con origen igual
al destino, puntas de flecha sueltas) y se cuentan en `report`.
"""
import json
import math
import secrets

KINDS = {"rect", "ellipse", "sticky", "text", "inbox"}


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _box(o: dict) -> tuple[float, float, float, float]:
    """(x, y, w, h) en coordenadas del lienzo, sea cual sea el origen del objeto."""
    w = float(o.get("width") or 0) * float(o.get("scaleX") or 1)
    h = float(o.get("height") or 0) * float(o.get("scaleY") or 1)
    left, top = float(o.get("left") or 0), float(o.get("top") or 0)
    x = left - w / 2 if o.get("originX") == "center" else left
    y = top - h / 2 if o.get("originY") == "center" else top
    return x, y, w, h


def _walk(o: dict):
    yield o
    for child in o.get("objects") or []:
        yield from _walk(child)


def _texts(o: dict) -> list[dict]:
    return [c for c in _walk(o) if c.get("type") in ("i-text", "textbox", "text") and c is not o]


def _shape(o: dict) -> dict | None:
    return next((c for c in _walk(o) if c.get("type") in ("rect", "ellipse", "circle") and c is not o), None)


def _clean_color(c, default):
    return c if isinstance(c, str) and c and c != "rgb(0,0,0)" else default


def convert(data: dict) -> tuple[dict, dict]:
    """Devuelve (tablero en formato 2, informe de lo convertido/descartado)."""
    if data.get("format") == 2:
        return data, {"ya_convertido": True}
    nodes, edges, strokes = [], [], []
    link_to_node: dict[str, str] = {}
    report = {"nodos": 0, "flechas": 0, "trazos": 0, "descartados": []}
    objects = data.get("objects") or []

    for o in objects:
        t, ct = o.get("type"), o.get("customType")
        if t in ("line", "triangle") and ct in ("arrow", "arrowhead", "line"):
            continue  # se tratan después, cuando ya existen los nodos
        x, y, w, h = _box(o)
        scale = float(o.get("scaleX") or 1)
        node = None
        if t == "group":
            texts = _texts(o)
            shape = _shape(o)
            first = texts[0] if texts else {}
            is_card = ct != "shape" and len(texts) >= 1 and first.get("type") == "textbox"
            if is_card:  # tarjeta del Inbox
                stroke = _clean_color((shape or {}).get("stroke"), "#89b4fa")
                parent = texts[1].get("text", "") if len(texts) > 1 else ""
                node = {"kind": "inbox", "text": first.get("text", ""), "itemType": "nota" if "f59e0b" in stroke else "tarea",
                        "parentLabel": parent.replace("↳", "").strip(), "inboxId": o.get("inboxId")}
            else:
                node = {"kind": "ellipse" if shape and shape.get("type") in ("ellipse", "circle") else "rect",
                        "text": "\n".join(tt.get("text", "") for tt in texts).strip(),
                        "fill": _clean_color((shape or {}).get("fill"), None), "stroke": _clean_color((shape or {}).get("stroke"), None),
                        "color": _clean_color(first.get("fill"), None),
                        "fontSize": round(float(first.get("fontSize") or 18) * scale, 1) if texts else None}
        elif t in ("rect", "ellipse", "circle"):
            node = {"kind": "ellipse" if t != "rect" else "rect", "text": "",
                    "fill": _clean_color(o.get("fill"), None), "stroke": _clean_color(o.get("stroke"), None)}
        elif t in ("i-text", "textbox", "text"):
            node = {"kind": "text", "text": o.get("text", ""), "color": _clean_color(o.get("fill"), None),
                    "fontSize": round(float(o.get("fontSize") or 18) * scale, 1)}
        elif t == "path":
            pts = []
            off = o.get("pathOffset") or {"x": 0, "y": 0}
            dx = x - (float(off.get("x", 0)) - w / 2) if w else 0
            dy = y - (float(off.get("y", 0)) - h / 2) if h else 0
            for cmd in o.get("path") or []:
                if len(cmd) >= 3:
                    pts.append([round(float(cmd[-2]) + dx, 1), round(float(cmd[-1]) + dy, 1)])
            if len(pts) >= 2:
                strokes.append({"id": _id("s"), "points": pts, "color": _clean_color(o.get("stroke"), "#cdd6f4"),
                                "width": float(o.get("strokeWidth") or 3)})
                report["trazos"] += 1
            continue
        if node is None:
            report["descartados"].append(f"objeto {t}")
            continue
        node.update({"id": _id("n"), "x": round(x, 1), "y": round(y, 1), "w": round(max(w, 24), 1), "h": round(max(h, 24), 1)})
        node = {k: v for k, v in node.items() if v not in (None, "")} | {"text": node.get("text", "")}
        if o.get("linkId"):
            link_to_node[o["linkId"]] = node["id"]
        nodes.append(node)
        report["nodos"] += 1

    for o in objects:
        if o.get("type") != "line":
            continue
        start, end = link_to_node.get(o.get("startObjId")), link_to_node.get(o.get("endObjId"))
        if o.get("startObjId") and o.get("startObjId") == o.get("endObjId"):
            report["descartados"].append(f"flecha {o.get('connId')} con origen igual al destino")
            continue
        edge = {"id": _id("e"), "color": _clean_color(o.get("stroke"), "#89b4fa"), "width": float(o.get("strokeWidth") or 2),
                "head": "arrow" if o.get("customType") == "arrow" else "none"}
        if start and end:
            edge.update({"from": start, "to": end})
        else:
            x, y, w, h = _box(o)
            cx, cy = x + w / 2, y + h / 2
            p1 = [round(cx + float(o.get("x1") or 0), 1), round(cy + float(o.get("y1") or 0), 1)]
            p2 = [round(cx + float(o.get("x2") or 0), 1), round(cy + float(o.get("y2") or 0), 1)]
            if math.dist(p1, p2) < 2:
                report["descartados"].append(f"línea vacía {o.get('connId')}")
                continue
            if start:
                edge["from"] = start
            else:
                edge["p1"] = p1
            if end:
                edge["to"] = end
            else:
                edge["p2"] = p2
        edges.append(edge)
        report["flechas"] += 1
    lone_heads = {o.get("connId") for o in objects if o.get("type") == "triangle"} - {o.get("connId") for o in objects if o.get("type") == "line"}
    report["descartados"] += [f"punta de flecha suelta {c}" for c in sorted(c for c in lone_heads if c)]
    return {"format": 2, "nodes": nodes, "edges": edges, "strokes": strokes}, report


def convert_text(raw: str | None) -> tuple[str, dict | None]:
    """Igual que convert() pero sobre el texto guardado. (texto nuevo, informe o None si no hacía falta)."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return raw or "{}", None
    if not isinstance(data, dict) or data.get("format") == 2 or not data.get("objects"):
        return raw or "{}", None
    new, report = convert(data)
    return json.dumps(new, ensure_ascii=False), report
