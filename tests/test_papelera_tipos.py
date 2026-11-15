"""D-5 y D-7: lo que el usuario escribió pasa por la papelera y vuelve idéntico; restaurar nunca borra nada vivo."""

import json
import time

import pytest

from app.database import get_db


def _comidas_db():
    from comidas.database import get_db as comidas_db

    return comidas_db()


def _row(db, table, where, params):
    with get_db() if db == "brain" else _comidas_db() as conn:
        r = conn.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchone()
        return dict(r) if r else None


def _insert(db, sql, params):
    with get_db() if db == "brain" else _comidas_db() as conn:
        return conn.execute(sql, params).lastrowid


def _delete_and_restore(client, url, db="brain", expected=1):
    r = client.delete(url)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["undo_token"] and res["undo_db"] == db
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == res["undo_token"])
    assert entry["db"] == db and entry["label"] and entry["plural"]
    back = client.post(f"/api/trash/{db}/{res['undo_token']}/restore")
    assert back.status_code == 200 and back.json()["restored"] == expected, back.text
    assert not any(e["token"] == res["undo_token"] for e in client.get("/api/trash").json()["entries"])
    return entry


# (bd, tabla, INSERT, parámetros, URL de borrado con {id}, columna clave)
CASES = {
    "recurso": (
        "brain",
        "resources",
        "INSERT INTO resources (url, title, description, category, watch_later, watched, sort_order) VALUES (?, ?, ?, ?, 1, 0, 7.5)",
        ("https://ejemplo.test/papelera", "Recurso de prueba", "con descripción", "Lecturas"),
        "/api/resources/{id}",
        "id",
    ),
    "plantilla-tablero": (
        "brain",
        "board_templates",
        "INSERT INTO board_templates (name, data) VALUES (?, ?)",
        ("Plantilla T", '{"nodes": []}'),
        "/api/board-templates/{id}",
        "id",
    ),
    "plantilla-rutina": (
        "brain",
        "routine_templates",
        "INSERT INTO routine_templates (name, data) VALUES (?, ?)",
        ("Rutina T", '{"steps": []}'),
        "/api/routine-templates/{id}",
        "id",
    ),
    "plantilla-dia": (
        "brain",
        "day_templates",
        "INSERT INTO day_templates (name, data) VALUES (?, ?)",
        ("Día T", '{"bloques": []}'),
        "/api/day-templates/{id}",
        "id",
    ),
    "filtro": (
        "brain",
        "saved_filters",
        "INSERT INTO saved_filters (scope, name, params) VALUES (?, ?, ?)",
        ("notas", "Filtro T", '{"q": "x"}'),
        "/api/saved-filters/{id}",
        "id",
    ),
    "tema": (
        "brain",
        "temas",
        "INSERT INTO temas (asignatura_id, titulo, tipo, grupo) VALUES (?, ?, 'manual', 'teoria')",
        None,
        "/api/uni/temas/{id}",
        "id",
    ),
    "plantilla-comida": (
        "comidas",
        "meal_templates",
        "INSERT INTO meal_templates (nombre, franja, items, favorito) VALUES (?, ?, ?, 1)",
        ("Desayuno T", "desayuno", '[{"meal_id": 1}]'),
        "/comidas/api/meal-templates/{id}",
        "id",
    ),
    "peso": (
        "comidas",
        "body_log",
        "INSERT INTO body_log (fecha, peso_kg, cintura_cm, notas) VALUES (?, 71.5, 80, 'tras correr')",
        ("2026-01-02",),
        "/comidas/api/body/2026-01-02",
        "id",
    ),
}


@pytest.fixture()
def asignatura(client):
    client.get("/api/uni/asignaturas")  # asegura el esquema
    return _insert(
        "brain",
        "INSERT INTO asignaturas (nombre, codigo) VALUES (?, ?)",
        (f"Asig {time.time_ns()}", f"PT{time.time_ns() % 10**8}"),
    )


@pytest.mark.parametrize("name", CASES)
def test_borrar_y_restaurar_fila_identica(client, asignatura, name):
    db, table, sql, params, url, key = CASES[name]
    from app.search import ensure_schema

    with get_db() as conn:
        ensure_schema(conn)  # la tabla de filtros se crea al usarla
    rid = _insert(db, sql, params if params is not None else (asignatura, "Tema manual T"))
    before = _row(db, table, f"{key}=?", (rid,))
    entry = _delete_and_restore(client, url.format(id=rid), db)
    assert entry["label"]
    assert _row(db, table, f"{key}=?", (rid,)) == before


def test_tablero_con_su_lienzo(client):
    b = client.post("/api/boards", json={"name": "Tablero de la papelera"}).json()
    bid = b.get("id") or b["board"]["id"]
    parsed = {
        "format": 2,
        "nodes": [{"id": "n1", "type": "rect", "x": 1, "y": 2, "w": 30, "h": 40, "text": "dentro"}],
        "edges": [],
        "strokes": [],
    }
    assert client.post(f"/api/boards/{bid}/canvas", json={"data": json.dumps(parsed)}).status_code == 200
    board, canvas = _row("brain", "boards", "id=?", (bid,)), _row("brain", "board_canvas", "board_id=?", (bid,))
    assert "dentro" in canvas["data"]
    entry = _delete_and_restore(client, f"/api/boards/{bid}")
    assert entry["label"] == "tablero" and entry["title"] == "Tablero de la papelera"
    assert _row("brain", "boards", "id=?", (bid,)) == board
    assert _row("brain", "board_canvas", "board_id=?", (bid,)) == canvas


def test_categoria_con_su_rama_y_sus_notas(client):
    parent = _insert(
        "brain", "INSERT INTO categories (name, slug) VALUES (?, ?)", ("Rama T", f"rama-t-{time.time_ns()}")
    )
    child = _insert(
        "brain",
        "INSERT INTO categories (name, slug, parent_id) VALUES (?, ?, ?)",
        ("Hoja T", f"hoja-t-{time.time_ns()}", parent),
    )
    client.post("/api/notes/nota-de-rama", json={"title": "De rama", "category": "Rama T", "content": "x"})
    with get_db() as conn:
        conn.execute("UPDATE notes SET category_id=? WHERE id='nota-de-rama'", (child,))
    rows = [_row("brain", "categories", "id=?", (i,)) for i in (parent, child)]
    _delete_and_restore(client, f"/api/categories/{parent}", expected=2)
    assert [_row("brain", "categories", "id=?", (i,)) for i in (parent, child)] == rows
    assert _row("brain", "notes", "id=?", ("nota-de-rama",))["category_id"] == child


def test_proyecto_vacio_y_version_con_sus_tareas(client):
    client.get("/api/proyectos")
    pid = _insert(
        "brain",
        "INSERT INTO proyectos (nombre, slug, descripcion) VALUES (?, ?, ?)",
        ("Proyecto T", f"proyecto-t-{time.time_ns()}", "desc"),
    )
    vid = _insert(
        "brain", "INSERT INTO versiones (proyecto_id, nombre, changelog) VALUES (?, ?, ?)", (pid, "v1.0", "- cambios")
    )
    proyecto, version = _row("brain", "proyectos", "id=?", (pid,)), _row("brain", "versiones", "id=?", (vid,))
    _delete_and_restore(client, f"/api/proyectos/{pid}")  # un proyecto sin nada se borra con sus versiones
    assert (
        _row("brain", "proyectos", "id=?", (pid,)) == proyecto and _row("brain", "versiones", "id=?", (vid,)) == version
    )

    task = client.post("/api/items", json={"text": "Tarea de la versión"}).json()
    tid = task.get("id") or task["item"]["id"]
    with get_db() as conn:
        conn.execute("UPDATE inbox SET version_id=?, proyecto_id=?, contexto='proyectos' WHERE id=?", (vid, pid, tid))
    _delete_and_restore(client, f"/api/proyectos/versiones/{vid}")
    assert _row("brain", "versiones", "id=?", (vid,)) == version
    assert _row("brain", "inbox", "id=?", (tid,))["version_id"] == vid


def test_asignatura_vacia(client, asignatura):
    tema = _insert(
        "brain",
        "INSERT INTO temas (asignatura_id, titulo, tipo, grupo) VALUES (?, 'De carpeta', 'carpeta', 'teoria')",
        (asignatura,),
    )
    rows = _row("brain", "asignaturas", "id=?", (asignatura,)), _row("brain", "temas", "id=?", (tema,))
    _delete_and_restore(client, f"/api/uni/asignaturas/{asignatura}")
    assert (_row("brain", "asignaturas", "id=?", (asignatura,)), _row("brain", "temas", "id=?", (tema,))) == rows


def test_recurso_con_la_url_vuelta_a_guardar_no_se_duplica(client):
    rid = _insert(
        "brain", "INSERT INTO resources (url, title) VALUES (?, ?)", ("https://ejemplo.test/doble", "Primera")
    )
    token = client.delete(f"/api/resources/{rid}").json()["undo_token"]
    nuevo = _insert(
        "brain", "INSERT INTO resources (url, title) VALUES (?, ?)", ("https://ejemplo.test/doble", "Guardada otra vez")
    )
    assert client.post(f"/api/trash/brain/{token}/restore").json()["restored"] == 0
    assert _row("brain", "resources", "id=?", (nuevo,))["title"] == "Guardada otra vez"  # lo actual se queda
