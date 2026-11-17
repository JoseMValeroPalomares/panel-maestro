"""Bloque C · Proyectos (migración 27): prioridad, fechas y etiquetas; versiones con título y descripción;
comentarios y adjuntos de tareas con papelera, copias y purga de huérfanos."""

import time
import uuid

from app import item_extras
from app.database import get_db


def _proy(client, **extra):
    nombre = f"Gestor {uuid.uuid4().hex[:6]}"
    r = client.post("/api/proyectos", json={"nombre": nombre, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _tarea(client, pid, texto="Tarea del gestor"):
    r = client.post("/api/items", json={"text": texto, "type": "tarea", "proyecto_id": pid})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_proyecto_con_prioridad_fechas_y_etiquetas(client):
    p = _proy(
        client,
        prioridad="alta",
        fecha_inicio="2026-11-01",
        fecha_fin="2026-12-20",
        etiquetas=["web", " #Web ", "uni", ""],
        descripcion="## Objetivo\n\n- [ ] algo",
    )
    assert (p["prioridad"], p["fecha_inicio"], p["fecha_fin"]) == ("alta", "2026-11-01", "2026-12-20")
    assert p["etiquetas"] == ["web", "uni"]  # sin repetidas, sin # ni vacías
    # Quitar con "" y cambiar etiquetas
    assert (
        client.patch(
            f"/api/proyectos/{p['id']}", json={"prioridad": "", "fecha_fin": "", "etiquetas": ["x"]}
        ).status_code
        == 200
    )
    q = client.get(f"/api/proyectos/{p['slug']}").json()
    assert (
        q["prioridad"] is None
        and q["fecha_fin"] is None
        and q["fecha_inicio"] == "2026-11-01"
        and q["etiquetas"] == ["x"]
    )
    # Validación
    assert client.patch(f"/api/proyectos/{p['id']}", json={"prioridad": "urgente"}).status_code == 422
    assert client.patch(f"/api/proyectos/{p['id']}", json={"fecha_inicio": "20-11-2026"}).status_code == 422


def test_version_con_titulo_y_descripcion_en_el_registro(client):
    p = _proy(client)
    vid = client.post(
        f"/api/proyectos/{p['id']}/versiones",
        json={"nombre": "0.1", "titulo": "Primer tablero", "descripcion": "Lo **básico**"},
    ).json()["id"]
    tid = _tarea(client, p["id"], "Arrastrar columnas")
    client.patch(f"/api/items/{tid}", json={"version_id": vid, "done": True})
    v = client.get(f"/api/proyectos/{p['slug']}").json()["versiones"][0]
    assert (v["nombre"], v["titulo"], v["descripcion"]) == ("v0.1", "Primer tablero", "Lo **básico**")
    log = client.post(f"/api/proyectos/versiones/{vid}/cerrar", json={}).json()["changelog"]
    assert log.startswith("## v0.1 · Primer tablero — ") and "- Arrastrar columnas" in log
    assert client.patch(f"/api/proyectos/versiones/{vid}", json={"titulo": ""}).status_code == 200
    assert client.get(f"/api/proyectos/{p['slug']}").json()["versiones"][0]["titulo"] is None


def test_comentarios_con_papelera_y_contadores(client):
    p = _proy(client)
    tid = _tarea(client, p["id"])
    c1 = client.post(f"/api/items/{tid}/comentarios", json={"texto": "Primero"}).json()
    client.post(f"/api/items/{tid}/comentarios", json={"texto": "Segundo"})
    assert client.post(f"/api/items/{tid}/comentarios", json={"texto": "   "}).status_code == 422
    assert client.post("/api/items/99999999/comentarios", json={"texto": "x"}).status_code == 404
    r = client.patch(f"/api/items/{tid}/comentarios/{c1['id']}", json={"texto": "Primero (editado)"}).json()
    assert r["texto"] == "Primero (editado)" and r["updated_at"]
    assert client.get(f"/api/proyectos/{p['slug']}").json()["extras"][str(tid)] == {"comentarios": 2, "adjuntos": 0}
    # Borrar va a la papelera y vuelve
    d = client.delete(f"/api/items/{tid}/comentarios/{c1['id']}").json()
    assert [c["texto"] for c in client.get(f"/api/items/{tid}/extras").json()["comentarios"]] == ["Segundo"]
    assert client.post(f"/api/trash/brain/{d['undo_token']}/restore").status_code == 200
    assert len(client.get(f"/api/items/{tid}/extras").json()["comentarios"]) == 2
    # Otra tarea no puede tocar el comentario
    otra = _tarea(client, p["id"], "Otra")
    assert client.delete(f"/api/items/{otra}/comentarios/{c1['id']}").status_code == 404


def test_adjuntos_seguros_y_restaurables(client, tmp_root):
    p = _proy(client)
    tid = _tarea(client, p["id"])
    pdf = client.post(f"/api/items/{tid}/adjuntos", files={"archivo": ("Apuntes tema 1.pdf", b"%PDF-1.4 hola")}).json()
    html = client.post(
        f"/api/items/{tid}/adjuntos", files={"archivo": ("../../evil.html", b"<script>x</script>")}
    ).json()
    assert pdf["nombre"] == "Apuntes tema 1.pdf" and pdf["bytes"] == 13 and pdf["mime"] == "application/pdf"
    assert html["nombre"] == "evil.html"  # sin rutas
    # El archivo vive en data/adjuntos/<item>/<uuid>.<ext>, nunca con el nombre del cliente
    with get_db() as conn:
        rel = conn.execute("SELECT archivo FROM item_adjuntos WHERE id=?", (html["id"],)).fetchone()[0]
    assert rel.startswith(f"{tid}/") and rel.endswith(".html") and "evil" not in rel
    # PDF se ve en el navegador; HTML siempre se descarga y como octet-stream
    r = client.get(pdf["url"])
    assert r.status_code == 200 and r.content == b"%PDF-1.4 hola"
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    r = client.get(html["url"])
    assert r.headers["content-type"] == "application/octet-stream" and r.headers["content-disposition"].startswith(
        "attachment"
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (
        client.get(f"/api/items/{tid}/adjuntos/{pdf['id']}?descargar=1")
        .headers["content-disposition"]
        .startswith("attachment")
    )
    # Vacío y demasiado grande
    assert client.post(f"/api/items/{tid}/adjuntos", files={"archivo": ("v.txt", b"")}).status_code == 400
    old = item_extras.MAX_BYTES
    item_extras.MAX_BYTES = 10
    try:
        assert client.post(f"/api/items/{tid}/adjuntos", files={"archivo": ("g.bin", b"x" * 11)}).status_code == 413
    finally:
        item_extras.MAX_BYTES = old
    assert len(list((item_extras.adjuntos_dir() / str(tid)).iterdir())) == 2  # los fallidos no dejan archivo
    # Borrar → papelera: el archivo sigue mientras la papelera lo nombre, y la purga no lo toca
    d = client.delete(f"/api/items/{tid}/adjuntos/{html['id']}").json()
    path = item_extras.adjuntos_dir() / rel
    item_extras.purge_orphans(now=time.time() + 7200)
    assert path.exists()
    assert client.post(f"/api/trash/brain/{d['undo_token']}/restore").status_code == 200
    assert client.get(html["url"]).status_code == 200


def test_huerfanos_vuelven_con_la_tarea_y_se_purgan_despues(client, tmp_root):
    p = _proy(client)
    tid = _tarea(client, p["id"])
    client.post(f"/api/items/{tid}/comentarios", json={"texto": "Se queda"})
    adj = client.post(f"/api/items/{tid}/adjuntos", files={"archivo": ("a.txt", b"hola")}).json()
    with get_db() as conn:
        rel = conn.execute("SELECT archivo FROM item_adjuntos WHERE id=?", (adj["id"],)).fetchone()[0]
    path = item_extras.adjuntos_dir() / rel
    # Borrar la tarea deja comentarios y adjuntos; restaurarla los devuelve
    tok = client.delete(f"/api/items/{tid}").json()["undo"]
    item_extras.purge_orphans()
    with get_db() as conn:
        assert conn.execute("SELECT huerfano_desde FROM item_comentarios WHERE item_id=?", (tid,)).fetchone()[0]
    assert client.post(f"/api/trash/brain/{tok}/restore").status_code == 200
    item_extras.purge_orphans()
    ex = client.get(f"/api/items/{tid}/extras").json()
    assert len(ex["comentarios"]) == 1 and len(ex["adjuntos"]) == 1
    with get_db() as conn:
        assert conn.execute("SELECT huerfano_desde FROM item_comentarios WHERE item_id=?", (tid,)).fetchone()[0] is None
    # Si la tarea no vuelve, a los 31 días se van fila y archivo
    client.delete(f"/api/items/{tid}")
    item_extras.purge_orphans()
    item_extras.purge_orphans(now=time.time() + item_extras.ORPHAN_TTL_S + 10)
    with get_db() as conn:
        assert not conn.execute("SELECT 1 FROM item_comentarios WHERE item_id=?", (tid,)).fetchone()
        assert not conn.execute("SELECT 1 FROM item_adjuntos WHERE item_id=?", (tid,)).fetchone()
    assert not path.exists()


def test_migracion_27_se_deshace_sin_perder_nada(tmp_path):
    import sqlite3

    from app.migrations import MIGRATIONS
    from core.migrations import apply_pending, revert

    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending', "
        "parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT, category TEXT)"
    )
    conn.execute(
        "CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, "
        "channel TEXT, added_at REAL, watch_later INTEGER DEFAULT 0, watched INTEGER DEFAULT 0)"
    )
    apply_pending(conn, [m for m in MIGRATIONS if m.version < 27])
    conn.execute("INSERT INTO proyectos (nombre, slug) VALUES ('P', 'p')")
    conn.execute("INSERT INTO versiones (proyecto_id, nombre) VALUES (1, 'v0.1')")
    antes = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("proyectos", "versiones")}
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 27]) == [27]
    conn.execute("UPDATE proyectos SET prioridad='alta', fecha_fin='2026-12-01', etiquetas='[\"a\"]'")
    conn.execute("UPDATE versiones SET titulo='Tablero'")
    conn.execute("INSERT INTO item_comentarios (item_id, texto) VALUES (1, 'c')")
    revert(conn, MIGRATIONS, 26)
    assert {
        t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("proyectos", "versiones")
    } == antes
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 27]) == [27]
    p = conn.execute("SELECT prioridad, fecha_fin, etiquetas FROM proyectos").fetchone()
    assert tuple(p) == ("alta", "2026-12-01", '["a"]')
    assert conn.execute("SELECT titulo FROM versiones").fetchone()[0] == "Tablero"
    assert conn.execute("SELECT texto FROM item_comentarios").fetchone()[0] == "c"
