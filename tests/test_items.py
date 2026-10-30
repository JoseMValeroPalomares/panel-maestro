"""Tercera ronda: API única de tareas e ideas (/api/items) y casillas de las notas como elementos."""
import sqlite3

from app.migrations import MIGRATIONS
from core import config
from core.migrations import apply_pending, revert

NOTA = ("---\ncategory: Proyectos - Taller\nstatus: por-escribir\ntags:\n- x\ntitle: Plan\n---\n\n# Plan\n\n"
        "- [ ] Comprar pilas\n  - [ ] Pilas AA\n* [x] Llamar al taller\n- [ ] Comprar pilas\n"
        "Texto normal - [ ] no\n\n```\n- [ ] en código, no cuenta\n```\n")


def _escribir(note_id, raw):
    (config.NOTES_DIR / f"{note_id}.md").write_text(raw, encoding="utf-8")


def _leer(note_id):
    return (config.NOTES_DIR / f"{note_id}.md").read_text(encoding="utf-8")


def _todo(client):
    return client.get("/api/items").json()


def _items(client, **filtro):
    return [i for i in _todo(client)["items"] if all(i[k] == v for k, v in filtro.items())]


def _nuevo(client, text, type="tarea", **extra):
    r = client.post("/api/items", json={"text": text, "type": type, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _ids(client, origin, parent_id=None, prefix="IT"):
    return [i["id"] for i in _todo(client)["items"]
            if i["origin"] == origin and i["parent_id"] == parent_id and i["text"].startswith(prefix)]


def _mover(client, item_id, **body):
    return client.post(f"/api/items/{item_id}/move", json=body)


# ─────────── Casillas de las notas ───────────

def test_casillas_de_una_nota_son_elementos(client):
    _escribir("it-plan", NOTA)
    mias = _items(client, note_id="it-plan", origin="nota")
    assert [(i["note_index"], i["text"], i["done"]) for i in mias] == [
        (0, "Comprar pilas", False), (1, "Pilas AA", False), (2, "Llamar al taller", True), (3, "Comprar pilas", False)]
    padre = mias[0]
    assert mias[1]["parent_id"] == padre["id"] and mias[3]["parent_id"] is None
    assert padre["note_title"] == "Plan" and padre["note_category"] == "Proyectos - Taller"
    # Volver a indexar no duplica ni cambia ids
    from app.indexer import sync_notes_to_db
    sync_notes_to_db(force=True)
    assert [i["id"] for i in _items(client, note_id="it-plan")] == [i["id"] for i in mias]


def test_marcar_desde_la_lista_cambia_solo_esa_linea(client):
    _escribir("it-linea", NOTA)
    tercera = _items(client, note_id="it-linea")[3]
    assert client.patch(f"/api/items/{tercera['id']}", json={"done": True}).status_code == 200
    assert _leer("it-linea") == NOTA.replace("* [x] Llamar al taller\n- [ ] Comprar pilas", "* [x] Llamar al taller\n- [x] Comprar pilas")
    assert next(i for i in _items(client, note_id="it-linea") if i["id"] == tercera["id"])["done"] is True


def test_editar_texto_en_la_lista_y_en_la_nota(client):
    _escribir("it-texto", NOTA)
    primera = _items(client, note_id="it-texto")[0]
    client.patch(f"/api/items/{primera['id']}", json={"priority": "alta", "due_date": "2026-11-02", "details": "En la ferretería"})
    assert client.patch(f"/api/items/{primera['id']}", json={"text": "Comprar pilas recargables"}).status_code == 200
    assert "- [ ] Comprar pilas recargables\n  - [ ] Pilas AA" in _leer("it-texto")
    # Y al revés: editar la nota (por el guardado normal) cambia el elemento sin perder id ni prioridad
    raw = _leer("it-texto").replace("Comprar pilas recargables", "Comprar pilas de litio").replace("- [ ] Pilas AA", "- [x] Pilas AA")
    body = raw.split("---\n", 2)[2]
    r = client.post("/api/notes/it-texto", json={"title": "Plan", "content": body, "category": "Proyectos - Taller", "status": "por-escribir"})
    assert r.status_code == 200
    ahora = {i["id"]: i for i in _items(client, note_id="it-texto")}
    assert ahora[primera["id"]]["text"] == "Comprar pilas de litio"
    assert (ahora[primera["id"]]["priority"], ahora[primera["id"]]["due_date"]) == ("alta", "2026-11-02")
    assert any(i["text"] == "Pilas AA" and i["done"] for i in ahora.values())


def test_borrar_casilla_en_la_nota_quita_el_elemento(client):
    _escribir("it-borra", NOTA)
    antes = _items(client, note_id="it-borra")
    _escribir("it-borra", NOTA.replace("* [x] Llamar al taller\n", ""))
    ahora = _items(client, note_id="it-borra")
    assert len(ahora) == len(antes) - 1 and not any(i["text"] == "Llamar al taller" for i in ahora)


def test_nota_cifrada_o_indice_no_aporta_tareas(client):
    _escribir("it-cifrada", NOTA.replace("tags:", "encrypted: true\ntags:"))
    assert _items(client, note_id="it-cifrada") == []


# ─────────── Crear, ordenar, convertir ───────────

def test_crear_desde_cualquier_sitio_y_orden(client):
    a = _nuevo(client, "IT a")
    b = client.post("/api/inbox", json={"content": "IT b", "item_type": "tarea"}).json()["id"]  # alias de la extensión
    c = _nuevo(client, "IT c")
    assert _ids(client, "inbox")[:3] == [c, b, a]  # lo último, arriba
    assert _mover(client, a, before_id=c).status_code == 200
    assert _ids(client, "inbox")[:3] == [a, c, b]
    assert _mover(client, c).status_code == 200  # sin before_id: al final
    assert _ids(client, "inbox")[-1] == c


def test_crear_en_una_nota_y_como_paso(client):
    _escribir("it-crea", NOTA)
    nid = _nuevo(client, "Revisar presupuesto", note_id="it-crea")
    assert next(i for i in _items(client, note_id="it-crea") if i["id"] == nid)["origin"] == "nota"
    padre = _items(client, note_id="it-crea")[0]
    pid = _nuevo(client, "Pilas AAA", parent_id=padre["id"])
    raw = _leer("it-crea")
    assert "  - [ ] Pilas AA\n  - [ ] Pilas AAA\n" in raw and "- [ ] Revisar presupuesto\n" in raw
    assert next(i for i in _items(client, note_id="it-crea") if i["id"] == pid)["parent_id"] == padre["id"]
    assert client.post("/api/items", json={"text": "idea", "type": "idea", "note_id": "it-crea"}).status_code == 422


def test_convertir_tarea_idea_y_reglas(client):
    t = _nuevo(client, "IT convertible")
    assert client.patch(f"/api/items/{t}", json={"type": "idea"}).status_code == 200
    assert t in _ids(client, "ideas")
    assert _mover(client, t, target="inbox").status_code == 200
    padre = _nuevo(client, "IT padre")
    hijo = _nuevo(client, "IT hijo", parent_id=padre)
    r = _mover(client, padre, target="ideas")
    assert r.status_code == 422 and "pasos" in r.json()["detail"]
    assert client.patch(f"/api/items/{padre}", json={"type": "idea"}).status_code == 422
    idea = _nuevo(client, "IT idea", type="idea")
    r = _mover(client, hijo, parent_id=idea)
    assert r.status_code == 422 and "subidea" in r.json()["detail"]
    r = _mover(client, padre, parent_id=_nuevo(client, "IT otro"))
    assert r.status_code == 422 and "pasos" in r.json()["detail"]


def test_anidar_y_sacar_arrastrando(client):
    p = _nuevo(client, "IT madre")
    x = _nuevo(client, "IT suelta")
    assert _mover(client, x, parent_id=p).status_code == 200
    assert _ids(client, "inbox", parent_id=p) == [x]
    assert _mover(client, x, target="inbox", before_id=p).status_code == 200  # sacarlo del padre
    lista = _ids(client, "inbox")
    assert lista.index(x) == lista.index(p) - 1 and _ids(client, "inbox", parent_id=p) == []


def test_de_inbox_a_nota_y_vuelta(client):
    _escribir("it-mueve", NOTA)
    p = _nuevo(client, "IT llevar a la nota\nhttps://ejemplo.org")
    h = _nuevo(client, "IT paso", parent_id=p)
    destino = _items(client, note_id="it-mueve")[2]  # «Llamar al taller»
    assert _mover(client, p, target="nota", note_id="it-mueve", before_id=destino["id"]).status_code == 200
    raw = _leer("it-mueve")
    assert "- [ ] IT llevar a la nota\n  - [ ] IT paso\n* [x] Llamar al taller" in raw
    mias = {i["id"]: i for i in _items(client, note_id="it-mueve")}
    assert mias[p]["origin"] == "nota" and mias[h]["parent_id"] == p and mias[p]["details"] == "https://ejemplo.org"
    # y de vuelta al Inbox: sale de la nota con su paso
    assert _mover(client, p, target="inbox").status_code == 200
    assert "IT llevar" not in _leer("it-mueve")
    assert next(i for i in _todo(client)["items"] if i["id"] == h)["parent_id"] == p
    assert _leer("it-mueve") == NOTA


def test_reordenar_y_anidar_dentro_de_una_nota(client):
    _escribir("it-orden", NOTA)
    a, aa, llamar, b = _items(client, note_id="it-orden")
    assert _mover(client, b["id"], target="nota", note_id="it-orden", before_id=a["id"]).status_code == 200
    assert _leer("it-orden").count("- [ ] Comprar pilas\n- [ ] Comprar pilas\n  - [ ] Pilas AA") == 1
    r = _mover(client, llamar["id"], parent_id=a["id"])
    assert r.status_code == 200, r.text
    assert "  - [ ] Pilas AA\n  * [x] Llamar al taller\n" in _leer("it-orden")
    assert next(i for i in _items(client, note_id="it-orden") if i["id"] == llamar["id"])["parent_id"] == a["id"]


def test_borrar_con_deshacer(client):
    _escribir("it-undo", NOTA)
    p = _nuevo(client, "IT con pasos", priority="media", category="Casa")
    h = _nuevo(client, "IT su paso", parent_id=p)
    tok = client.delete(f"/api/items/{p}").json()["undo"]
    assert not any(i["id"] in (p, h) for i in _todo(client)["items"])
    assert client.post("/api/items/undo", json={"token": tok}).json()["restored"] == 2
    vuelto = {i["id"]: i for i in _todo(client)["items"]}
    assert vuelto[p]["priority"] == "media" and vuelto[h]["parent_id"] == p
    # casilla de una nota: sale del .md y vuelve en su sitio
    primera = _items(client, note_id="it-undo")[0]
    tok = client.delete(f"/api/items/{primera['id']}").json()["undo"]
    assert "Pilas AA" not in _leer("it-undo")
    client.post("/api/items/undo", json={"token": tok})
    assert _leer("it-undo") == NOTA
    assert client.post("/api/items/undo", json={"token": tok}).status_code == 404


def test_lote(client):
    ids = [_nuevo(client, f"IT lote {n}") for n in range(3)]
    r = client.post("/api/items/bulk", json={"ids": ids, "action": "done"}).json()
    assert r["count"] == 3
    assert all(i["done"] for i in _todo(client)["items"] if i["id"] in ids)
    client.post("/api/items/bulk", json={"ids": ids, "action": "category", "value": "Recados"})
    assert {i["category"] for i in _todo(client)["items"] if i["id"] in ids} == {"Recados"}
    client.post("/api/items/bulk", json={"ids": ids[:2], "action": "move", "target": "ideas"})
    assert set(ids[:2]) <= set(_ids(client, "ideas"))
    tok = client.post("/api/items/bulk", json={"ids": ids, "action": "delete"}).json()["undo"]
    assert not any(i["id"] in ids for i in _todo(client)["items"])
    client.post("/api/items/undo", json={"token": tok})
    assert all(any(i["id"] == x for i in _todo(client)["items"]) for x in ids)
    assert client.post("/api/items/bulk", json={"ids": ids, "action": "explotar"}).status_code == 422


def test_contadores_iguales_en_todas_partes(client):
    datos = _todo(client)
    tops = [i for i in datos["items"] if i["parent_id"] is None]
    c = datos["counts"]
    # las rutinas tienen su contador pero no suman al total (se repiten)
    assert c["pendientes"] == sum(1 for i in tops if not i["done"] and i["type"] != "rutina")
    for g in ("inbox", "nota", "ideas"):
        assert c[g]["pendientes"] == sum(1 for i in tops if i["origin"] == g and not i["done"])
    assert client.get("/api/items/counts").json() == c
    assert client.get("/api/ext/status").json()["pending"] == c["pendientes"]


def test_pasar_a_nota_nueva(client):
    t = _nuevo(client, "IT preparar viaje")
    _nuevo(client, "IT maleta", parent_id=t)
    note_id = client.post(f"/api/items/{t}/to-note", json={"title": "Viaje IT", "category": "Planes"}).json()["note_id"]
    assert "- [ ] IT preparar viaje\n  - [ ] IT maleta" in _leer(note_id)
    assert next(i for i in _todo(client)["items"] if i["id"] == t)["origin"] == "nota"
    idea = _nuevo(client, "IT idea suelta", type="idea")
    nid = client.post(f"/api/items/{idea}/to-note", json={"title": "Idea IT"}).json()["note_id"]
    assert "IT idea suelta" in _leer(nid)
    assert next(i for i in _todo(client)["items"] if i["id"] == idea)["done"] is True


def test_validacion(client):
    assert client.post("/api/items", json={"text": ""}).status_code == 422
    assert client.post("/api/items", json={"text": "x", "type": "otra"}).status_code == 422
    assert client.post("/api/items", json={"text": "x", "due_date": "mañana"}).status_code == 422
    assert client.patch("/api/items/999999", json={"done": True}).status_code == 404
    assert client.post("/api/items", json={"text": "x", "note_id": "../../etc/passwd"}).status_code in (400, 404, 422)


# ─────────── Migración 7 ───────────

def test_migracion_7_arriba_y_abajo(tmp_path):
    conn = sqlite3.connect(tmp_path / "m7.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending',
                    parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT)""")
    conn.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL)")
    conn.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, content TEXT, encrypted INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO notes (id, content) VALUES ('n', '- [ ] sigue aquí')")
    conn.execute("""INSERT INTO inbox (id, content, item_type, status, note_id, note_task) VALUES
        (1, '--- hecha', 'tarea', 'processed', NULL, NULL), (2, 'sigue aquí', 'tarea', 'pending', 'n', 'sigue aquí'),
        (3, 'ya no está', 'tarea', 'pending', 'n', 'ya no está')""")
    apply_pending(conn, MIGRATIONS)
    rows = {r["id"]: tuple(r) for r in conn.execute("SELECT id, content, note_id, note_task FROM inbox")}
    assert rows[1] == (1, "hecha", None, None) and rows[2] == (2, "sigue aquí", "n", "sigue aquí") and rows[3] == (3, "ya no está", None, None)
    conn.execute("INSERT INTO inbox (id, content, note_id, note_task) VALUES (10, 'nueva casilla', 'n', 'nueva casilla')")
    conn.execute("UPDATE inbox SET due_date='2026-01-01' WHERE id=2")
    revert(conn, MIGRATIONS, 6)
    assert {r["id"]: tuple(r) for r in conn.execute("SELECT id, content, note_id, note_task FROM inbox")} == {
        1: (1, "--- hecha", None, None), 2: (2, "sigue aquí", "n", "sigue aquí"), 3: (3, "ya no está", "n", "ya no está")}
    assert "due_date" not in [r[1] for r in conn.execute("PRAGMA table_info(inbox)")]
    assert tuple(conn.execute("SELECT id, due_date FROM inbox_items_backup").fetchone()) == (2, "2026-01-01")


def test_orden_manual_de_las_notas(client):
    _escribir("it-ord-b", NOTA.replace("title: Plan", "title: B nota"))
    _escribir("it-ord-a", NOTA.replace("title: Plan", "title: A nota"))
    _todo(client)
    assert client.post("/api/notes/it-ord-a/move", json={"before_id": None}).status_code == 200  # A al final
    pos = {i["note_id"]: i["note_position"] for i in _todo(client)["items"] if i["note_id"] in ("it-ord-a", "it-ord-b")}
    assert pos["it-ord-b"] is not None and pos["it-ord-a"] > pos["it-ord-b"]
