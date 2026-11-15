"""Contextos (puntual / universidad / proyectos), asignaturas con temas desde la carpeta (solo lectura),
clases que se repiten, menciones en la captura, propuesta de migración y proyectos con versiones."""

import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import date, timedelta

import pytest

from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert

HOY = date.today()
D = lambda n: (HOY + timedelta(days=n)).isoformat()  # noqa: E731


def _tree_hash(root) -> str:
    """Huella de una carpeta (nombres, tamaños, fechas y contenido): demuestra que no se ha tocado."""
    h = hashlib.sha256()
    for dirpath, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            st = os.lstat(p)
            h.update(f"{os.path.relpath(p, root)}|{st.st_size}|{st.st_mtime_ns}".encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
        h.update(("D:" + ",".join(dirs)).encode())
    return h.hexdigest()


@pytest.fixture()
def uni(tmp_path, monkeypatch):
    """Una raíz de universidad de pruebas como la real: PDF sueltos, carpetas de prácticas, código y artefactos."""
    root = tmp_path / "Uja"
    asig = root / "Tercero" / "Bases de datos"
    (asig / "Practica 2").mkdir(parents=True)
    (asig / "Practica 3").mkdir()
    (asig / "build").mkdir()
    (asig / "Practica 3" / "práctica3.pdf").write_bytes(b"%PDF-1.4 p3")
    (asig / "Practica 3" / "trg.sql").write_text("select 1;")
    (asig / "tema1.pdf").write_bytes(b"%PDF-1.4 t1")
    (asig / "tema2.pdf").write_bytes(b"%PDF-1.4 t2")
    (asig / "main.cpp").write_text("int main(){}")
    (asig / "notas.zip").write_bytes(b"PK")
    fuera = tmp_path / "secreto"
    fuera.mkdir()
    (asig / "atajo").symlink_to(fuera)  # un enlace que sale de la raíz: ni tema ni ruta válida
    monkeypatch.setenv("PANEL_UNI_ROOT", str(root))
    return root


def _asig(client, codigo, **kw):
    body = {"nombre": kw.pop("nombre", f"Asignatura {codigo}"), "codigo": codigo, **kw}
    r = client.post("/api/uni/asignaturas", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(client, iid):
    return next(i for i in client.get("/api/items").json()["items"] if i["id"] == iid)


# ─────────────────────────────────────────────
# Migración
# ─────────────────────────────────────────────


def test_migracion_22_conserva_todo_y_se_deshace(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT DEFAULT 'pending', "
        "parent_id INTEGER, sort_order REAL DEFAULT 0, created_at REAL DEFAULT 0, note_id TEXT, note_task TEXT, category TEXT)"
    )
    conn.execute(
        "CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL, watch_later INTEGER DEFAULT 0, watched INTEGER DEFAULT 0)"
    )
    conn.executemany(
        "INSERT INTO inbox (id, content, item_type, category) VALUES (?, ?, ?, ?)",
        [(1, "GABD · Práctica 4", "tarea", "GABD"), (2, "Idea", "nota", None), (3, "Lunes", "rutina", None)],
    )
    apply_pending(conn, [m for m in MIGRATIONS if m.version < 22])
    conn.execute("INSERT INTO events (uid, title, start) VALUES ('u1', 'GABD · Examen', '2027-01-19')")
    antes = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("inbox", "events")}
    conn.execute(
        "INSERT INTO resources (id, url, title, category, resource_type) VALUES (9, 'https://x.org', 'X', 'Web', 'web')"
    )
    antes["resources"] = [tuple(r) for r in conn.execute("SELECT * FROM resources ORDER BY id")]
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 23]) == [22, 23]
    assert {r[0] for r in conn.execute("SELECT DISTINCT contexto FROM inbox")} == {"puntual"}  # todo queda puntual
    assert conn.execute("SELECT contexto FROM resources WHERE id=9").fetchone()[0] == "puntual"
    assert {r[0] for r in conn.execute("SELECT DISTINCT contexto FROM events")} == {"puntual"}
    conteos = json.loads(conn.execute("SELECT valor FROM contexto_meta WHERE clave='conteos_previos'").fetchone()[0])
    assert conteos["inbox"] == 3 and conteos["events"] == 1
    conn.execute("INSERT INTO asignaturas (nombre, codigo) VALUES ('Gestión', 'GABD')")
    conn.execute("UPDATE inbox SET contexto='universidad', asignatura_id=1 WHERE id=1")
    revert(conn, MIGRATIONS, 21)
    assert {
        t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("inbox", "events", "resources")
    } == antes
    guardado = dict(conn.execute("SELECT tabla, datos FROM contexto_backup").fetchall())
    assert json.loads(guardado["asignaturas"])[0]["codigo"] == "GABD"  # deshacer no pierde lo creado
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 23]) == [22, 23]


def test_integridad_conteos(client):
    r = client.get("/api/contextos/integridad").json()
    assert set(r["antes"]) >= {"inbox", "events"}
    assert all(r["ahora"][t] >= 0 for t in r["antes"])


# ─────────────────────────────────────────────
# Contexto en tareas, pasos, eventos y notas
# ─────────────────────────────────────────────


def test_contexto_por_defecto_y_contenedor_manda(client):
    aid = _asig(client, "CTXA")
    tid = client.post("/api/items", json={"text": "Comprar pan", "type": "tarea"}).json()["id"]
    assert _item(client, tid)["contexto"] == "puntual"
    u = client.post(
        "/api/items",
        json={
            "text": "Práctica 1",
            "type": "tarea",
            "asignatura_id": aid,
            "uni_tipo": "entrega",
            "due_date": D(2),
            "peso": 15,
        },
    ).json()["id"]
    it = _item(client, u)
    assert (it["contexto"], it["asignatura"], it["uni_tipo"], it["peso"]) == ("universidad", "CTXA", "entrega", 15)
    paso = client.post("/api/items", json={"text": "Leer el guion", "parent_id": u}).json()["id"]
    assert _item(client, paso)["asignatura_id"] == aid  # el paso hereda
    assert client.patch(f"/api/items/{paso}", json={"contexto": "puntual"}).status_code == 422
    # pasar a puntual quita la asignatura (y a los pasos)
    client.patch(f"/api/items/{u}", json={"contexto": "puntual"})
    assert _item(client, paso)["asignatura_id"] is None and _item(client, u)["contexto"] == "puntual"
    assert client.patch(f"/api/items/{u}", json={"asignatura_id": 999999}).status_code == 422
    # lote: a una asignatura
    r = client.post(
        "/api/items/bulk", json={"ids": [tid, u], "action": "contexto", "value": f"asignatura:{aid}"}
    ).json()
    assert r["count"] == 2 and _item(client, tid)["asignatura_id"] == aid


def test_casillas_de_una_nota_van_con_su_nota(client, tmp_root):
    aid = _asig(client, "CTXN")
    (tmp_root / "data" / "notes" / "apuntes-ctxn.md").write_text(
        "---\ntitle: Apuntes CTXN\ncategory: Universidad\nasignatura: CTXN\nstatus: por-escribir\n---\n\n- [ ] Repasar el tema 1\n",
        encoding="utf-8",
    )
    it = next(i for i in client.get("/api/items").json()["items"] if i["text"] == "Repasar el tema 1")
    assert it["origin"] == "nota" and it["contexto"] == "universidad" and it["asignatura_id"] == aid
    assert client.patch(f"/api/items/{it['id']}", json={"contexto": "puntual"}).status_code == 422


def test_filtro_de_contexto_en_calendario_hoy_y_agenda(client):
    aid = _asig(client, "CTXF")
    client.post(
        "/api/items", json={"text": "Entrega CTXF", "type": "tarea", "asignatura_id": aid, "due_date": HOY.isoformat()}
    )
    client.post("/api/items", json={"text": "Tender la ropa CTXF", "type": "tarea", "due_date": HOY.isoformat()})
    titulos = lambda ctx: {
        e["title"]
        for e in client.get("/api/calendar/entries", params={"start": D(0), "end": D(0), "contexto": ctx}).json()[
            "entries"
        ]
    }  # noqa: E731
    assert "Entrega CTXF" in titulos("universidad") and "Tender la ropa CTXF" not in titulos("universidad")
    assert "Tender la ropa CTXF" in titulos("puntual") and "Entrega CTXF" not in titulos("puntual")
    assert {"Entrega CTXF", "Tender la ropa CTXF"} <= titulos("todo")
    # «activo» = la preferencia guardada en el servidor (la misma para Waybar y extensión)
    client.put("/api/prefs/contexto", json={"value": "universidad"})
    assert "Tender la ropa CTXF" not in titulos("activo")
    hoy = client.get("/api/today", params={"contexto": "activo"}).json()
    assert hoy["contexto"] == "universidad" and any(t["title"] == "Entrega CTXF" for t in hoy["tareas"])
    entrega = next(t for t in hoy["tareas"] if t["title"] == "Entrega CTXF")
    assert entrega["asignatura"] == "CTXF" and entrega["color"]
    client.put("/api/contextos/ajustes", json={"waybar_contexto": "puntual"})
    ag = client.get("/api/calendar/agenda", params={"days": 1, "contexto": "waybar"}).json()
    assert ag["contexto"] == "puntual" and all(e["contexto"] == "puntual" for e in ag["entries"])
    client.put("/api/prefs/contexto", json={"value": "todo"})
    client.put("/api/contextos/ajustes", json={"waybar_contexto": "activo"})
    assert client.get("/api/calendar/entries", params={"contexto": "marte"}).status_code == 422


def test_completar_en_un_sitio_completa_en_todos(client):
    aid = _asig(client, "CTXD")
    tid = client.post(
        "/api/items",
        json={
            "text": "Práctica CTXD",
            "type": "tarea",
            "asignatura_id": aid,
            "uni_tipo": "entrega",
            "due_date": HOY.isoformat(),
        },
    ).json()["id"]
    client.patch(f"/api/items/{tid}", json={"done": True})  # p. ej. desde la vista Universidad
    hoy = client.get("/api/today", params={"contexto": "universidad"}).json()
    assert next(t for t in hoy["tareas"] if t["id"] == tid)["done"]
    cal = client.get("/api/calendar/entries", params={"start": D(0), "end": D(0), "contexto": "universidad"}).json()[
        "entries"
    ]
    assert next(e for e in cal if e.get("item_id") == tid)["done"]
    ent = client.get(f"/api/uni/asignaturas/{aid}/entregas").json()["entregas"]
    assert next(e for e in ent if e["id"] == tid)["hecho"]


# ─────────────────────────────────────────────
# Menciones en la captura
# ─────────────────────────────────────────────


def test_menciones_en_la_captura(client):
    aid = _asig(client, "GABD", nombre="Gestión y Administración de Bases de Datos", alias=["bd"])
    p = client.post("/api/proyectos", json={"nombre": "Panel Maestro", "slug": "panel-maestro"}).json()
    vid = client.post(f"/api/proyectos/{p['id']}/versiones", json={"nombre": "v0.3"}).json()["id"]
    r = client.post("/api/capture", json={"text": "t: práctica 4 @gabd viernes"}).json()
    assert r["status"] == "success", r
    it = _item(client, r["id"])
    viernes = HOY + timedelta(days=(4 - HOY.weekday()) % 7 or 7)
    assert (it["text"], it["asignatura_id"], it["contexto"], it["uni_tipo"]) == (
        "Práctica 4",
        aid,
        "universidad",
        "entrega",
    )
    assert it["due_date"] in (viernes.isoformat(), (viernes - timedelta(days=7)).isoformat())
    r = client.post("/api/capture", json={"text": "t: arreglar login #panel-maestro v0.3"}).json()
    it = _item(client, r["id"])
    assert (it["text"], it["proyecto_id"], it["version_id"], it["contexto"]) == (
        "Arreglar login" if it["text"][0].isupper() else "arreglar login",
        p["id"],
        vid,
        "proyectos",
    )
    assert client.post("/api/capture", json={"text": "i: algo @bd"}).json()["status"] == "success"  # alias
    # mención que no existe: avisa y no crea nada
    n = len(client.get("/api/items").json()["items"])
    r = client.post("/api/capture", json={"text": "t: estudiar @noexiste"}).json()
    assert r["status"] == "error" and "@noexiste" in r["message"]
    r = client.post("/api/capture", json={"text": "t: algo #panel-maestro v9.9"}).json()
    assert r["status"] == "error" and "v9.9" in r["message"]
    assert len(client.get("/api/items").json()["items"]) == n
    # evento con asignatura: un examen de GABD
    r = client.post(
        "/api/capture", json={"text": f"e: examen final @gabd {(HOY + timedelta(days=20)).strftime('%d/%m')} 9:00"}
    ).json()
    assert r["status"] == "success" and r["kind"] == "evento", r
    ev = client.get(f"/api/calendar/events/{r['id']}").json()
    assert ev["asignatura_id"] == aid and ev["type"] == "examen"
    m = client.get("/api/contextos/menciones").json()["menciones"]
    assert {"@gabd", "#panel-maestro"} <= {x["mencion"] for x in m}
    # el alias de una asignatura no puede pisar el de otra
    assert (
        client.post("/api/uni/asignaturas", json={"nombre": "Otra", "codigo": "OTRA", "alias": ["gabd"]}).status_code
        == 409
    )


# ─────────────────────────────────────────────
# Temas desde la carpeta (solo lectura)
# ─────────────────────────────────────────────


def test_sincronizar_con_carpeta(client, uni):
    huella = _tree_hash(uni)
    aid = _asig(client, "SYNC", carpeta="Tercero/Bases de datos")
    r = client.post(f"/api/uni/asignaturas/{aid}/sync").json()
    assert r["nuevos"] == 4, r  # Practica 2, Practica 3, tema1.pdf, tema2.pdf (no build, main.cpp, zip ni el enlace)
    temas = {t["ruta"]: t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid}
    assert set(temas) == {"Practica 2", "Practica 3", "tema1.pdf", "tema2.pdf"}
    assert temas["Practica 3"]["grupo"] == "practicas" and temas["tema1.pdf"]["grupo"] == "teoria"
    assert temas["tema1.pdf"]["tipo"] == "archivo" and temas["Practica 2"]["tipo"] == "carpeta"
    # cambios a mano: nombre, estado, orden y un tema propio
    t1 = temas["tema1.pdf"]["id"]
    client.patch(
        f"/api/uni/temas/{t1}",
        json={"titulo": "Tema 1 · Introducción", "estado": "repasado", "before_id": temas["Practica 2"]["id"]},
    )
    manual = client.post(f"/api/uni/asignaturas/{aid}/temas", json={"titulo": "Repaso para el parcial"}).json()["id"]
    # desaparece una carpeta en el disco (lo hace el usuario, no el panel)
    os.rename(
        uni / "Tercero" / "Bases de datos" / "Practica 2", uni / "Tercero" / "Bases de datos" / "Practica 2 vieja"
    )
    huella = _tree_hash(uni)
    r = client.post(f"/api/uni/asignaturas/{aid}/sync").json()
    assert (r["nuevos"], r["faltan"]) == (1, 1), r
    temas = {t["ruta"] or t["titulo"]: t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid}
    assert temas["Practica 2"]["falta"] and not temas["Practica 2 vieja"]["falta"]  # marcado, no borrado
    assert temas["tema1.pdf"]["titulo"] == "Tema 1 · Introducción" and temas["tema1.pdf"]["estado"] == "repasado"
    assert temas["tema1.pdf"]["orden"] < temas["Practica 3"]["orden"]
    assert "Repaso para el parcial" in temas
    assert _tree_hash(uni) == huella  # la sincronía no ha escrito nada en la carpeta
    # recursos de un tema y archivos sueltos (solo lectura)
    rec = client.get(f"/api/uni/temas/{temas['Practica 3']['id']}/recursos").json()["recursos"]
    assert {x["nombre"] for x in rec} == {"práctica3.pdf", "trg.sql"}
    sueltos = {x["nombre"] for x in client.get(f"/api/uni/asignaturas/{aid}/recursos").json()["recursos"]}
    assert {"main.cpp", "notas.zip"} <= sueltos and "atajo" not in sueltos
    # un tema que sigue en la carpeta no se borra; uno que falta, sí (sin tocar el disco)
    assert client.delete(f"/api/uni/temas/{temas['Practica 3']['id']}").status_code == 409
    assert client.delete(f"/api/uni/temas/{temas['Practica 2']['id']}").status_code == 200
    assert client.delete(f"/api/uni/temas/{manual}").status_code == 200
    assert _tree_hash(uni) == huella


def test_sin_disco_no_se_marca_nada(client, uni, monkeypatch):
    aid = _asig(client, "NODISK", carpeta="Tercero/Bases de datos")
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    monkeypatch.setenv("PANEL_UNI_ROOT", str(uni.parent / "no-montado"))
    r = client.post(f"/api/uni/asignaturas/{aid}/sync")
    assert r.status_code == 409 and "disponible" in r.json()["detail"]
    assert not any(t["falta"] for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid)


def test_rutas_fuera_de_la_raiz_se_rechazan(client, uni):
    for mala in ("../secreto", "/etc", "Tercero/../../secreto", "~/x", "Tercero/Bases de datos/atajo"):
        r = client.post(
            "/api/uni/asignaturas",
            json={"nombre": "Mala", "codigo": "MALA" + str(abs(hash(mala)) % 1000), "carpeta": mala},
        )
        if r.status_code == 200:  # el enlace es una ruta «limpia»: se rechaza al usarla
            aid = r.json()["id"]
            assert client.post(f"/api/uni/asignaturas/{aid}/sync").status_code == 422
            assert client.get(f"/api/abrir/asignatura/{aid}").json()["absoluta"] is None
            client.delete(f"/api/uni/asignaturas/{aid}")
        else:
            assert r.status_code == 422, (mala, r.text)
    assert client.get("/api/abrir/asignatura/999999").status_code == 404
    assert client.get("/api/abrir/carpeta/1").status_code == 404


def test_abrir_devuelve_ruta_relativa(client, uni):
    aid = _asig(client, "OPEN", carpeta="Tercero/Bases de datos")
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    r = client.get(f"/api/abrir/asignatura/{aid}").json()
    assert (r["raiz"], r["ruta"], r["existe"]) == ("universidad", "Tercero/Bases de datos", True)
    assert (
        r["absoluta"] == str(uni / "Tercero" / "Bases de datos")
        and r["url"] == f"panelmaestro://abrir/asignatura/{aid}"
    )
    tema = next(
        t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid and t["ruta"] == "tema1.pdf"
    )
    r = client.get(f"/api/abrir/tema/{tema['id']}").json()
    assert r["ruta"] == "Tercero/Bases de datos/tema1.pdf" and r["existe"]


def test_nota_de_tema_y_de_clase(client, uni):
    aid = _asig(client, "NOTA", carpeta="Tercero/Bases de datos")
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    tema = next(t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid)
    r = client.post(f"/api/uni/temas/{tema['id']}/nota").json()
    assert r["creada"] and client.post(f"/api/uni/temas/{tema['id']}/nota").json() == {
        "note_id": r["note_id"],
        "creada": False,
    }
    nota = client.get(f"/api/notes/{r['note_id']}").json()
    assert (
        "## Dudas" in nota["content"]
        and "## Para el examen" in nota["content"]
        and "Duda para el profe" in nota["content"]
    )
    c = client.post(
        f"/api/uni/asignaturas/{aid}/nota-clase", json={"fecha": HOY.isoformat(), "tema_id": tema["id"]}
    ).json()
    assert "Clase" in client.get(f"/api/notes/{c['note_id']}").json()["title"]
    v = client.get("/api/uni").json()
    assert next(a for a in v["asignaturas"] if a["id"] == aid)["notas"] >= 2


# ─────────────────────────────────────────────
# Clases: eventos que se repiten
# ─────────────────────────────────────────────


def test_clases_se_repiten_sin_duplicar_y_no_van_a_icloud(client):
    from estudio.calendar_sync import panel_events

    aid = _asig(client, "CLAS", aula="A3-201")
    lunes = HOY - timedelta(days=HOY.weekday())
    eid = client.post(
        "/api/uni/clases",
        json={
            "asignatura_id": aid,
            "dias": [0, 2],
            "inicio": "08:35",
            "fin": "10:30",
            "desde": lunes.isoformat(),
            "hasta": (lunes + timedelta(days=13)).isoformat(),
        },
    ).json()["id"]
    ents = [
        e
        for e in client.get(
            "/api/calendar/entries",
            params={
                "start": lunes.isoformat(),
                "end": (lunes + timedelta(days=20)).isoformat(),
                "contexto": "universidad",
            },
        ).json()["entries"]
        if e.get("id") == eid and e["kind"] == "event"
    ]
    assert [e["start"][:10] for e in ents] == [
        (lunes + timedelta(days=n)).isoformat() for n in (0, 2, 7, 9)
    ]  # hasta el fin del cuatrimestre
    assert all(
        e["start"][11:] == "08:35"
        and e["end"][11:] == "10:30"
        and e["location"] == "A3-201"
        and e["asignatura"] == "CLAS"
        for e in ents
    )
    assert len({e["key"] for e in ents}) == 4  # una entrada por día, sin repetidos
    uid = client.get(f"/api/calendar/events/{eid}").json()["uid"]
    assert uid not in panel_events()  # ni a iCloud ni al ESP32
    assert any(c["id"] == eid for c in client.get("/api/uni/horario").json()["clases"])
    ics = client.get("/api/calendar/export.ics").text
    assert "RRULE:FREQ=WEEKLY" in ics


def test_rutina_universidad_pasa_a_clase(client):
    rid = client.post(
        "/api/items",
        json={"text": "Mi día CLR", "type": "rutina", "repeat": {"freq": "weekly", "days": [0, 1, 2, 3, 4]}},
    ).json()["id"]
    paso = client.post("/api/items", json={"text": "Universidad", "parent_id": rid}).json()["id"]
    r = client.patch(
        f"/api/items/{paso}", json={"due_time": "02:35", "duration_min": 60}
    )  # hora libre: otras pruebas ocupan la mañana
    assert r.status_code == 200, r.text
    assert any(r["id"] == paso for r in client.get("/api/uni/horario/rutinas").json()["rutinas"])
    r = client.post(f"/api/uni/clases/desde-rutina/{paso}").json()
    ev = client.get(f"/api/calendar/events/{r['event_id']}").json()
    assert (
        ev["start"][11:] == "02:35"
        and ev["end"][11:] == "03:35"
        and ev["repeat"] == {"freq": "weekly", "days": [0, 1, 2, 3, 4]}
    )
    assert ev["contexto"] == "universidad" and ev["type"] == "clase"
    assert not any(i["id"] == paso for i in client.get("/api/items").json()["items"])  # sin duplicado: el paso se va
    assert client.post("/api/items/undo", json={"token": r["undo"]}).status_code == 200  # y se puede recuperar


# ─────────────────────────────────────────────
# Propuesta: pasar a Universidad lo que ya hay
# ─────────────────────────────────────────────


def test_propuesta_se_confirma_y_se_deshace(client):
    aid = _asig(client, "ZZQ", nombre="Zoología Cuántica")
    t1 = client.post("/api/items", json={"text": "ZZQ · Práctica 4", "type": "tarea", "category": "ZZQ"}).json()["id"]
    t2 = client.post(
        "/api/items", json={"text": "Algo de Zoología Cuántica", "type": "tarea", "category": "Zoología Cuántica"}
    ).json()["id"]
    t3 = client.post("/api/items", json={"text": "Lavar el coche", "type": "tarea"}).json()["id"]
    e1 = client.post(
        "/api/calendar/events", json={"title": "ZZQ · Examen de teoría", "start": D(30), "kind": "examen"}
    ).json()["id"]
    p = client.get("/api/uni/propuesta").json()
    ids = {x["id"]: x for x in p["items"]}
    assert t1 in ids and t2 in ids and t3 not in ids
    assert ids[t1]["asignatura"]["id"] == aid and ids[t1]["uni_tipo"] == "entrega"
    assert any(e["id"] == e1 for e in p["eventos"])
    # nada cambia hasta confirmar
    assert _item(client, t1)["contexto"] == "puntual"
    r = client.post(
        "/api/uni/propuesta/aplicar",
        json={
            "items": [{"id": t1, "asignatura_id": aid, "uni_tipo": "entrega"}],
            "eventos": [{"id": e1, "asignatura_id": aid}],
        },
    ).json()
    assert r == {"items": 1, "eventos": 1}
    assert _item(client, t1)["asignatura_id"] == aid and _item(client, t2)["contexto"] == "puntual"
    assert client.get(f"/api/calendar/events/{e1}").json()["asignatura_id"] == aid
    client.post("/api/uni/propuesta/deshacer")
    assert (
        _item(client, t1)["contexto"] == "puntual"
        and client.get(f"/api/calendar/events/{e1}").json()["contexto"] == "puntual"
    )


# ─────────────────────────────────────────────
# Proyectos y versiones
# ─────────────────────────────────────────────


def test_proyecto_con_versiones_y_registro_de_cambios(client):
    p = client.post("/api/proyectos", json={"nombre": "Robot Lego", "descripcion": "Un brazo"}).json()
    assert p["slug"] == "robot-lego" and p["estado"] == "en-curso"
    v1 = client.post(f"/api/proyectos/{p['id']}/versiones", json={"nombre": "0.1", "fecha_objetivo": D(10)}).json()[
        "id"
    ]
    v2 = client.post(f"/api/proyectos/{p['id']}/versiones", json={"nombre": "v0.2"}).json()["id"]
    assert client.post(f"/api/proyectos/{p['id']}/versiones", json={"nombre": "v0.1"}).status_code == 409
    ids = [
        client.post("/api/items", json={"text": t, "type": "tarea", "proyecto_id": p["id"], "version_id": v1}).json()[
            "id"
        ]
        for t in ("Montar la base", "Programar el motor", "Calibrar")
    ]
    paso = client.post("/api/items", json={"text": "Comprar tornillos", "parent_id": ids[0]}).json()["id"]
    client.patch(f"/api/items/{paso}", json={"done": True})
    client.patch(f"/api/items/{ids[0]}", json={"done": True})
    client.patch(f"/api/items/{ids[1]}", json={"done": True})
    client.patch(f"/api/items/{ids[2]}", json={"en_curso": True})
    assert _item(client, ids[2])["en_curso"]
    det = client.get("/api/proyectos/robot-lego").json()
    v = next(x for x in det["versiones"] if x["id"] == v1)
    assert (v["total"], v["hechas"], v["progreso"]) == (3, 2, 67)
    # versión de otro proyecto: no
    otro = client.post("/api/proyectos", json={"nombre": "Otro"}).json()
    assert (
        client.patch(
            f"/api/items/{ids[2]}",
            json={
                "version_id": client.post(f"/api/proyectos/{otro['id']}/versiones", json={"nombre": "v1"}).json()["id"]
            },
        ).status_code
        == 422
    )
    r = client.post(f"/api/proyectos/versiones/{v1}/cerrar", json={"mover_a": v2}).json()
    assert (
        "- Montar la base" in r["changelog"]
        and "  - Comprar tornillos" in r["changelog"]
        and "- Programar el motor" in r["changelog"]
    )
    assert "Calibrar" not in r["changelog"] and r["movidas"] == 1
    assert _item(client, ids[2])["version_id"] == v2
    client.patch(f"/api/proyectos/versiones/{v1}", json={"changelog": r["changelog"] + "- Retoque a mano\n"})
    det = client.get("/api/proyectos/robot-lego").json()
    assert "Retoque a mano" in next(x for x in det["versiones"] if x["id"] == v1)["changelog"]
    assert det["version_actual"]["id"] == v2 and det["ultima_version"]["id"] == v1
    b = client.post(f"/api/proyectos/{p['id']}/bitacora").json()
    assert b["creada"] and client.get(f"/api/notes/{b['note_id']}").json()["title"].startswith("Bitácora")
    assert client.delete(f"/api/proyectos/{p['id']}").status_code == 409  # tiene cosas: no se borra


def test_git_solo_lectura(client, tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "robot"
    repo.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("config", "user.name", "Pruebas")
    run("config", "user.email", "p@example.com")
    (repo / "a.txt").write_text("hola")
    run("add", ".")
    run("commit", "-qm", "Primer commit")
    run("tag", "v0.1")
    monkeypatch.setenv("PANEL_PROYECTOS_ROOT", str(tmp_path / "repos"))
    p = client.post("/api/proyectos", json={"nombre": "Robot Git", "carpeta": "robot"}).json()
    antes = _tree_hash(repo / ".git")
    g = client.get(f"/api/proyectos/{p['id']}/git").json()
    assert (
        g["disponible"]
        and g["ultimo"]["mensaje"] == "Primer commit"
        and g["etiquetas"] == ["v0.1"]
        and g["rama"] == "main"
    )
    assert _tree_hash(repo / ".git") == antes
    assert client.get(f"/api/abrir/proyecto/{p['id']}").json()["absoluta"] == str(repo)


def test_baul_y_esquemas_con_contexto(client):
    aid = _asig(client, "CTXB")
    p = client.post("/api/proyectos", json={"nombre": "Proyecto CTXB"}).json()
    r = client.post(
        "/api/resources", json={"url": "https://example.org/ctxb", "category": "Docs", "proyecto_id": p["id"]}
    )
    assert r.status_code == 200, r.text
    res = next(x for x in client.get("/api/resources").json()["resources"] if x["url"] == "https://example.org/ctxb")
    assert res["contexto"] == "proyectos" and res["proyecto"] == p["slug"]
    client.patch(f"/api/resources/{res['id']}", json={"asignatura_id": aid})
    res = next(x for x in client.get("/api/resources").json()["resources"] if x["id"] == res["id"])
    assert (res["contexto"], res["asignatura_id"], res["proyecto_id"]) == ("universidad", aid, None)
    b = client.post("/api/boards", json={"name": "Arquitectura CTXB", "proyecto_id": p["id"]}).json()["id"]
    lista = {x["id"]: x for x in client.get("/api/boards").json()["boards"]}
    assert lista[b]["contexto"] == "proyectos" and lista[b]["proyecto_id"] == p["id"]
    client.patch(f"/api/boards/{b}/contexto", json={"contexto": "puntual", "proyecto_id": 0})
    assert {x["id"]: x for x in client.get("/api/boards").json()["boards"]}[b]["contexto"] == "puntual"
    # el esquema de una tarea toma el contexto de su tarea
    t = client.post(
        "/api/items", json={"text": "Tarea con esquema CTXB", "type": "tarea", "asignatura_id": aid}
    ).json()["id"]
    b2 = client.post("/api/boards", json={"name": "Esquema de la tarea", "item_id": t}).json()["id"]
    assert {x["id"]: x for x in client.get("/api/boards").json()["boards"]}[b2]["asignatura_id"] == aid


def test_anotaciones_de_la_universidad(client, tmp_root):
    (tmp_root / "data" / "notes" / "anot-uni.md").write_text(
        "---\ntitle: Anot uni\ncategory: Universidad\nstatus: por-escribir\n---\n\n{{duda: ¿por qué el índice B+?}}\n\n{{examen: normalización hasta 3FN}}\n\n{{importante: entrega el 16}}\n\n{{resumir: todo}}\n",
        encoding="utf-8",
    )
    client.get("/api/items")  # reindexa
    tags = {a["tag"] for a in client.get("/api/annotations").json()["annotations"] if a["note_id"] == "anot-uni"}
    assert tags == {"duda", "examen", "importante", "resumir"}
    solo = client.get("/api/annotations", params={"tag": "examen"}).json()["annotations"]
    assert [a["text"] for a in solo if a["note_id"] == "anot-uni"] == ["normalización hasta 3FN"]


def test_prompt_de_la_ia_editable(client):
    """Tarea 194: el prompt para que una IA explique un tema; editable y con vuelta al de siempre."""
    v = client.get("/api/uni").json()
    assert "{asignatura}" in v["prompt"] and "{tema}" in v["prompt"] and "diapositivas" in v["prompt"]
    client.put("/api/contextos/ajustes", json={"uni_prompt": "Explícame {tema} de {asignatura}"})
    assert client.get("/api/uni").json()["prompt"] == "Explícame {tema} de {asignatura}"
    client.put("/api/contextos/ajustes", json={"uni_prompt": ""})
    assert client.get("/api/uni").json()["prompt"] == v["prompt"]
