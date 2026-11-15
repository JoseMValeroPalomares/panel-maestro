"""Tanda 1c · D-4: dos dispositivos no se pisan al guardar una nota o un tablero."""

import sqlite3
import uuid

from app.migrations import MIGRATIONS
from core import config
from core.migrations import apply_pending, revert


def _nota(client, texto="Hola", **extra):
    nid = "conf-" + uuid.uuid4().hex[:8]
    body = {
        "title": "Conflicto",
        "category": "Pruebas",
        "content": texto,
        "status": "en-desarrollo",
        "tags": [],
        **extra,
    }
    r = client.post(f"/api/notes/{nid}", json=body)
    assert r.status_code == 200, r.text
    return nid, body, r.json()["version"]


def _md(nid):
    return (config.NOTES_DIR / f"{nid}.md").read_text(encoding="utf-8")


def test_get_devuelve_la_version_del_archivo(client):
    nid, _, v = _nota(client)
    n = client.get(f"/api/notes/{nid}").json()
    assert n["version"] == v and len(v) == 16 and n["content"] == "Hola"


def test_guardados_encadenados_nunca_dan_409(client):
    nid, body, v = _nota(client)
    for i in range(30):
        r = client.post(f"/api/notes/{nid}", json={**body, "content": f"Texto {i}", "base_version": v})
        assert r.status_code == 200, r.text
        v = r.json()["version"]
    assert "Texto 29" in _md(nid)


def test_segundo_dispositivo_recibe_409_con_lo_actual(client):
    nid, body, v0 = _nota(client)
    a = client.post(f"/api/notes/{nid}", json={**body, "content": "De A", "base_version": v0})
    assert a.status_code == 200
    b = client.post(f"/api/notes/{nid}", json={**body, "content": "De B", "base_version": v0})
    assert b.status_code == 409
    d = b.json()
    assert d["conflict"] and d["current"]["content"] == "De A" and d["current"]["version"] == a.json()["version"]
    assert "De A" in _md(nid)  # no se ha pisado


def test_quedarme_con_lo_mio_deja_lo_otro_en_el_historial(client):
    nid, body, v0 = _nota(client)
    a = client.post(f"/api/notes/{nid}", json={**body, "content": "De A", "base_version": v0}).json()
    r = client.post(
        f"/api/notes/{nid}", json={**body, "content": "De B", "base_version": a["version"], "overwrite": True}
    )
    assert r.status_code == 200 and "De B" in _md(nid)
    vers = client.get(f"/api/notes/{nid}/versions").json()["versions"]
    contenidos = [client.get(f"/api/notes/{nid}/versions/{x['id']}").json()["content"] for x in vers]
    assert "De A" in contenidos


def test_recargar_la_otra_guarda_lo_mio_en_el_historial(client):
    nid, body, _ = _nota(client)
    r = client.post(
        f"/api/notes/{nid}/versions",
        json={"title": "Conflicto", "category": "Pruebas", "content": "Lo mío", "tags": []},
    )
    assert r.status_code == 200
    vers = client.get(f"/api/notes/{nid}/versions").json()["versions"]
    mia = next(x for x in vers if x["id"] == r.json()["id"])
    assert mia["conflict"]
    assert client.get(f"/api/notes/{nid}/versions/{mia['id']}").json()["content"] == "Lo mío"
    # Restaurarla no deja la marca del historial en la nota
    client.post(f"/api/notes/{nid}/versions/{mia['id']}/restore")
    assert "conflicto" not in _md(nid) and "Lo mío" in _md(nid)


def test_sin_version_se_guarda_como_siempre(client):
    """Extensión, scripts y la IA no envían versión: siguen escribiendo sin conflicto."""
    nid, body, v0 = _nota(client)
    client.post(f"/api/notes/{nid}", json={**body, "content": "De A", "base_version": v0})
    r = client.post(f"/api/notes/{nid}", json={**body, "content": "Sin versión"})
    assert r.status_code == 200 and "Sin versión" in _md(nid)


def test_reintento_identico_no_es_conflicto(client):
    """La respuesta del primer guardado se perdió: el reintento con la base vieja es el mismo texto."""
    nid, body, v0 = _nota(client)
    first = client.post(f"/api/notes/{nid}", json={**body, "content": "Una vez", "base_version": v0}).json()
    r = client.post(f"/api/notes/{nid}", json={**body, "content": "Una vez", "base_version": v0})
    assert r.status_code == 200 and r.json()["version"] == first["version"]


def test_crear_encima_de_una_que_ya_existe_da_409(client):
    nid, body, _ = _nota(client, "Original")
    r = client.post(f"/api/notes/{nid}", json={**body, "content": "Otra", "base_version": ""})
    assert r.status_code == 409 and "Original" in _md(nid)


def test_nota_borrada_en_otro_dispositivo(client):
    nid, body, v0 = _nota(client)
    client.delete(f"/api/notes/{nid}")
    r = client.post(f"/api/notes/{nid}", json={**body, "content": "Sigo", "base_version": v0})
    assert r.status_code == 409 and r.json()["current"] is None


def test_estado_y_meta_devuelven_la_version_nueva(client):
    nid, body, v0 = _nota(client)
    v1 = client.patch(f"/api/notes/{nid}/status", json={"status": "consolidado"}).json()["version"]
    assert v1 != v0
    v2 = client.patch(f"/api/notes/{nid}/meta", json={"title": "Otro título"}).json()["version"]
    assert v2 != v1
    r = client.post(
        f"/api/notes/{nid}",
        json={**body, "title": "Otro título", "status": "consolidado", "content": "Sigue", "base_version": v2},
    )
    assert r.status_code == 200


def test_cambio_del_servidor_en_una_casilla_da_409_al_editor_viejo(client):
    """Items marca una casilla (reescribe la línea del .md): el editor con la versión de antes no la pisa."""
    nid, body, v0 = _nota(client, "- [ ] comprar pan")
    it = next(i for i in client.get("/api/items").json()["items"] if i.get("note_id") == nid)
    assert client.patch(f"/api/items/{it['id']}", json={"done": True}).status_code == 200
    assert "[x] comprar pan" in _md(nid)
    r = client.post(f"/api/notes/{nid}", json={**body, "content": "- [ ] comprar pan\n- [ ] leche", "base_version": v0})
    assert r.status_code == 409


# ── Tableros ──────────────────────────────────────────────────────────────────


def _tablero(client):
    bid = client.post("/api/boards", json={"name": "Conflicto"}).json()["id"]
    return bid, client.get(f"/api/boards/{bid}").json()["rev"]


def _doc(texto):
    import json

    return json.dumps(
        {
            "format": 2,
            "nodes": [{"id": "n1", "kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "text": texto}],
            "edges": [],
            "strokes": [],
        }
    )


def test_tablero_guardados_seguidos_y_409(client):
    bid, rev = _tablero(client)
    for i in range(30):
        r = client.post(f"/api/boards/{bid}/canvas", json={"data": _doc(f"v{i}"), "base_rev": rev})
        assert r.status_code == 200, r.text
        rev = r.json()["rev"]
    b = client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("B"), "base_rev": rev - 5})
    assert b.status_code == 409 and b.json()["conflict"] and "v29" in b.json()["current"]["data"]
    assert b.json()["current"]["rev"] == rev
    # Reintento idéntico con revisión vieja = éxito
    assert client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("v29"), "base_rev": 0}).status_code == 200
    # Sin revisión (cliente viejo) = como siempre
    assert client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("viejo")}).status_code == 200


def test_tablero_quedarme_con_lo_mio_y_deshacer_ultimo_guardado(client):
    bid, rev = _tablero(client)
    rev = client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("De A"), "base_rev": rev}).json()["rev"]
    r = client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("De B"), "base_rev": rev, "force": True})
    assert r.status_code == 200
    assert client.get(f"/api/boards/{bid}").json()["has_prev"]
    u = client.post(f"/api/boards/{bid}/canvas/undo-save").json()
    assert "De A" in u["data"] and u["rev"] > r.json()["rev"]
    # Deshacer otra vez vuelve a lo de B (es un intercambio)
    assert "De B" in client.post(f"/api/boards/{bid}/canvas/undo-save").json()["data"]


def test_tablero_recargar_el_otro_guarda_lo_mio_como_copia(client):
    bid, rev = _tablero(client)
    client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("De A"), "base_rev": rev})
    assert client.post(f"/api/boards/{bid}/canvas/prev", json={"data": _doc("Lo mio")}).status_code == 200
    assert "Lo mio" in client.post(f"/api/boards/{bid}/canvas/undo-save").json()["data"]


def test_tablero_borrado_y_restaurado_conserva_la_copia_previa(client):
    bid, rev = _tablero(client)
    rev = client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("A"), "base_rev": rev}).json()["rev"]
    client.post(f"/api/boards/{bid}/canvas", json={"data": _doc("B"), "base_rev": rev, "force": True})
    res = client.delete(f"/api/boards/{bid}").json()
    assert client.post(f"/api/trash/brain/{res['undo_token']}/restore").status_code == 200
    b = client.get(f"/api/boards/{bid}").json()
    assert "B" in b["data"] and b["has_prev"]


M24 = [m for m in MIGRATIONS if m.version == 24]


def test_migracion_24_sube_y_baja(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE boards (id INTEGER PRIMARY KEY, name TEXT, updated_at REAL)")
    conn.execute("CREATE TABLE board_canvas (board_id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}')")
    conn.execute("INSERT INTO boards VALUES (1, 'T', 0)")
    conn.execute("INSERT INTO board_canvas VALUES (1, '{}')")
    apply_pending(conn, M24)
    assert conn.execute("SELECT rev FROM board_canvas").fetchone()[0] == 0
    conn.execute("INSERT INTO board_canvas_prev VALUES (1, '{\"format\":2}', 0, 1)")
    revert(conn, M24, 23)
    assert "rev" not in {r[1] for r in conn.execute("PRAGMA table_info(board_canvas)")}
    assert conn.execute("SELECT count(*) FROM board_canvas_prev_bak").fetchone()[0] == 1  # la copia no se tira
    assert apply_pending(conn, M24) == [24]
    assert conn.execute("SELECT count(*) FROM board_canvas_prev").fetchone()[0] == 1
    assert conn.execute("SELECT data FROM board_canvas WHERE board_id=1").fetchone()[0] == "{}"


def test_estado_dice_la_version_anterior_para_no_adoptar_cambios_ajenos(client):
    """Si otro dispositivo guardó antes del PATCH, previous_version no es la del cliente: no debe adoptar la nueva."""
    nid, body, v0 = _nota(client)
    client.post(f"/api/notes/{nid}", json={**body, "content": "De otro", "base_version": v0})
    r = client.patch(f"/api/notes/{nid}/status", json={"status": "consolidado"}).json()
    assert r["previous_version"] != v0 and r["version"] != r["previous_version"]
    m = client.patch(f"/api/notes/{nid}/meta", json={"title": "T"}).json()
    assert m["previous_version"] == r["version"]
