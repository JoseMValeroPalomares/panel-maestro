"""Universidad (bloque A): carpeta de cada asignatura con su estado, temas propuestos que se confirman (renombrar,
reordenar, fusionar, descartar), archivos por tema con orden propio, «no encontrado», lector de PDF con la última
página y ejercicios asociables a varios temas. Todo en solo lectura sobre el disco."""

import hashlib
import os
import sqlite3

import pytest

from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert


def _huella(root) -> str:
    h = hashlib.sha256()
    for dirpath, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            st = os.lstat(p)
            h.update(f"{os.path.relpath(p, root)}|{st.st_size}|{st.st_mtime_ns}".encode())
        h.update(("D:" + ",".join(dirs)).encode())
    return h.hexdigest()


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    """Una asignatura como las reales: temas en carpetas con PDFs (también en subcarpetas) y PDFs sueltos."""
    root = tmp_path / "Uja"
    so = root / "Segundo" / "Sistemas Operativos"
    (so / "T2 - Procesos" / "Ejercicios").mkdir(parents=True)
    (so / "T3_hilos").mkdir()
    (so / "Practica 1").mkdir()
    (so / "T2 - Procesos" / "procesos.pdf").write_bytes(b"%PDF-1.4 procesos")
    (so / "T2 - Procesos" / "Ejercicios" / "boletin.pdf").write_bytes(b"%PDF-1.4 boletin")
    (so / "T2 - Procesos" / "planificacion.pdf").write_bytes(b"%PDF-1.4 planif")
    (so / "T2 - Procesos" / "codigo.c").write_text("int main(){}")
    (so / "T3_hilos" / "hilos.pdf").write_bytes(b"%PDF-1.4 hilos")
    (so / "Practica 1" / "enunciado.pdf").write_bytes(b"%PDF-1.4 p1")
    (so / "tema1.pdf").write_bytes(b"%PDF-1.4 " + b"x" * 5000)
    (so / "Guia docente.pdf").write_bytes(b"%PDF-1.4 guia")
    monkeypatch.setenv("PANEL_UNI_ROOT", str(root))
    return root


def _asig(client, codigo, **kw):
    r = client.post("/api/uni/asignaturas", json={"nombre": f"Asignatura {codigo}", "codigo": codigo, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _temas(client, aid):
    return {t["titulo"]: t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid}


def _confirmar_todo(client, aid):
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    r = client.post(f"/api/uni/asignaturas/{aid}/escaneo", json={"temas": [{"ruta": t["ruta"]} for t in p["nuevos"]]})
    assert r.status_code == 200, r.text
    return r.json()


# ─────────────────────────────────────────────
# Carpeta de la asignatura
# ─────────────────────────────────────────────


def test_carpeta_absoluta_dentro_de_la_raiz_y_estado(client, raiz):
    so = raiz / "Segundo" / "Sistemas Operativos"
    aid = _asig(client, "SOABS", carpeta=str(so))  # pegar la ruta absoluta: se guarda relativa
    a = next(a for a in client.get("/api/uni").json()["asignaturas"] if a["id"] == aid)
    assert (a["carpeta"], a["carpeta_estado"]) == ("Segundo/Sistemas Operativos", "vinculada")
    # fuera de la raíz, la raíz entera o una que no existe: 422 y no se guarda
    for mala in ("/etc", str(raiz), "Segundo/No existe"):
        r = client.patch(f"/api/uni/asignaturas/{aid}", json={"carpeta": mala})
        assert r.status_code == 422, (mala, r.text)
    assert client.get("/api/uni/carpeta-estado", params={"ruta": "Segundo/No existe"}).json()["estado"] == "invalida"
    est = client.get("/api/uni/carpeta-estado", params={"ruta": str(so)}).json()
    assert (est["ruta"], est["estado"], est["temas"]) == ("Segundo/Sistemas Operativos", "vinculada", 5)
    # la carpeta se mueve en el disco → rota; el disco sin montar → no disponible (no es lo mismo)
    os.rename(so, so.with_name("SO movida"))
    a = next(a for a in client.get("/api/uni").json()["asignaturas"] if a["id"] == aid)
    assert a["carpeta_estado"] == "rota"
    assert client.patch(f"/api/uni/asignaturas/{aid}", json={"carpeta": "Segundo/SO movida"}).status_code == 200
    a = next(a for a in client.get("/api/uni").json()["asignaturas"] if a["id"] == aid)
    assert a["carpeta_estado"] == "vinculada"
    os.environ["PANEL_UNI_ROOT"] = str(raiz.parent / "sin-montar")
    a = next(a for a in client.get("/api/uni").json()["asignaturas"] if a["id"] == aid)
    assert a["carpeta_estado"] == "no-disponible"


# ─────────────────────────────────────────────
# Propuesta de temas
# ─────────────────────────────────────────────


def test_propuesta_se_confirma_renombra_reordena_fusiona_y_descarta(client, raiz):
    huella = _huella(raiz)
    aid = _asig(client, "SOPROP", carpeta="Segundo/Sistemas Operativos")
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    sug = {t["ruta"]: t for t in p["nuevos"]}
    assert set(sug) == {"T2 - Procesos", "T3_hilos", "Practica 1", "tema1.pdf", "Guia docente.pdf"}
    assert sug["T2 - Procesos"]["titulo"] == "Tema 2 · Procesos"
    assert sug["T3_hilos"]["titulo"] == "Tema 3 · Hilos"
    assert sug["tema1.pdf"]["titulo"] == "Tema 1"
    assert sug["Practica 1"]["titulo"] == "Práctica 1"
    assert (sug["T2 - Procesos"]["archivos"], sug["T2 - Procesos"]["pdfs"]) == (3, 3)  # el .c no es documento
    assert next(a for a in client.get("/api/uni").json()["asignaturas"] if a["id"] == aid)["por_confirmar"] == 5

    r = client.post(
        f"/api/uni/asignaturas/{aid}/escaneo",
        json={
            "temas": [  # el orden de la lista es el de los temas
                {"ruta": "tema1.pdf", "titulo": "Tema 1 · Introducción"},
                {"ruta": "T2 - Procesos"},
                {"ruta": "T3_hilos", "accion": "fusionar", "destino": "T2 - Procesos"},
                {"ruta": "Guia docente.pdf", "accion": "descartar"},
                {"ruta": "Practica 1", "accion": "luego"},
                {"ruta": "../fuera", "accion": "crear"},  # no está en la carpeta: se ignora
            ]
        },
    ).json()
    assert (r["creados"], r["fusionados"], r["descartados"], r["por_confirmar"]) == (2, 1, 1, 1)
    temas = _temas(client, aid)
    assert list(temas) == ["Tema 1 · Introducción", "Tema 2 · Procesos"]  # el fusionado no se ve
    t2 = temas["Tema 2 · Procesos"]
    assert [f["titulo"] for f in t2["fusionados"]] == ["Tema 3 · Hilos"]
    assert t2["pdfs"] == 4  # los 3 suyos + el de hilos
    assert temas["Tema 1 · Introducción"]["titulo_manual"]
    # lo descartado no vuelve a proponerse (se puede recuperar); lo dejado para luego, sí
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    assert [t["ruta"] for t in p["nuevos"]] == ["Practica 1"]
    assert [t["ruta"] for t in p["descartados"]] == ["Guia docente.pdf"]
    client.post(f"/api/uni/asignaturas/{aid}/escaneo", json={"recuperar": ["Guia docente.pdf"]})
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    assert {t["ruta"] for t in p["nuevos"]} == {"Practica 1", "Guia docente.pdf"}
    # sincronizar no crea temas ni resucita el fusionado
    s = client.post(f"/api/uni/asignaturas/{aid}/sync").json()
    assert s["por_confirmar"] == 2 and list(_temas(client, aid)) == ["Tema 1 · Introducción", "Tema 2 · Procesos"]
    assert _huella(raiz) == huella


# ─────────────────────────────────────────────
# Archivos de cada tema
# ─────────────────────────────────────────────


def test_archivos_por_tema_orden_mover_y_no_encontrado(client, raiz):
    so = raiz / "Segundo" / "Sistemas Operativos"
    aid = _asig(client, "SOARCH", carpeta="Segundo/Sistemas Operativos")
    _confirmar_todo(client, aid)
    temas = _temas(client, aid)
    t2, t1 = temas["Tema 2 · Procesos"], temas["Tema 1"]
    arch = client.get(f"/api/uni/temas/{t2['id']}/archivos").json()["archivos"]
    assert [a["ruta"] for a in arch] == [
        "T2 - Procesos/Ejercicios/boletin.pdf",  # orden natural de la carpeta
        "T2 - Procesos/planificacion.pdf",
        "T2 - Procesos/procesos.pdf",
    ]
    assert all(a["visor"] and not a["falta"] for a in arch)
    ids = {a["nombre"]: a["id"] for a in arch}
    # orden a mano: procesos.pdf el primero
    client.patch(f"/api/uni/archivos/{ids['procesos.pdf']}", json={"before_id": ids["boletin.pdf"]})
    orden = [a["nombre"] for a in client.get(f"/api/uni/temas/{t2['id']}/archivos").json()["archivos"]]
    assert orden == ["procesos.pdf", "boletin.pdf", "planificacion.pdf"]
    # mover el boletín al tema 1: se queda allí al sincronizar; con tema_id 0 vuelve a su carpeta
    client.patch(f"/api/uni/archivos/{ids['boletin.pdf']}", json={"tema_id": t1["id"]})
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    t1_arch = client.get(f"/api/uni/temas/{t1['id']}/archivos").json()["archivos"]
    assert [a["nombre"] for a in t1_arch] == ["tema1.pdf", "boletin.pdf"] and t1_arch[1]["tema_manual"]
    client.patch(f"/api/uni/archivos/{ids['boletin.pdf']}", json={"tema_id": 0})
    assert len(client.get(f"/api/uni/temas/{t2['id']}/archivos").json()["archivos"]) == 3
    # la última página leída
    r = client.patch(f"/api/uni/archivos/{ids['procesos.pdf']}", json={"pagina": 12, "paginas": 40}).json()
    assert (r["pagina"], r["paginas"]) == (12, 40)
    assert client.patch(f"/api/uni/archivos/{ids['procesos.pdf']}", json={"pagina": 99}).json()["pagina"] == 40
    # desaparece del disco: «no encontrado», sin perder la página; vuelve y se desmarca
    (so / "T2 - Procesos" / "procesos.pdf").rename(so / "procesos.bak")
    assert client.get(f"/api/uni/archivos/{ids['procesos.pdf']}/contenido").status_code == 404
    a = next(
        x
        for x in client.get(f"/api/uni/temas/{t2['id']}/archivos").json()["archivos"]
        if x["id"] == ids["procesos.pdf"]
    )
    assert a["falta"] and a["pagina"] == 40
    assert client.get("/api/uni").status_code == 200  # nada se rompe
    assert next(t for t in client.get("/api/uni").json()["temas"] if t["id"] == t2["id"])["archivos_faltan"] == 1
    assert client.delete(f"/api/uni/archivos/{ids['boletin.pdf']}").status_code == 409  # sigue en la carpeta
    (so / "procesos.bak").rename(so / "T2 - Procesos" / "procesos.pdf")
    s = client.post(f"/api/uni/asignaturas/{aid}/sync").json()
    assert s["archivos"]["vuelven"] == 1
    a = client.get(f"/api/uni/archivos/{ids['procesos.pdf']}/info").json()
    assert not a["falta"] and a["pagina"] == 40


def test_contenido_del_pdf_solo_lectura_y_con_rangos(client, raiz):
    aid = _asig(client, "SOPDF", carpeta="Segundo/Sistemas Operativos")
    _confirmar_todo(client, aid)
    t1 = _temas(client, aid)["Tema 1"]
    a = client.get(f"/api/uni/temas/{t1['id']}/archivos").json()["archivos"][0]
    r = client.get(f"/api/uni/archivos/{a['id']}/contenido")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline") and r.content.startswith(b"%PDF")
    r = client.get(f"/api/uni/archivos/{a['id']}/contenido", headers={"Range": "bytes=0-7"})
    assert r.status_code == 206 and r.content == b"%PDF-1.4"
    assert client.get("/api/uni/archivos/999999/contenido").status_code == 404
    # disco sin montar: 409 y no se marca como no encontrado
    os.environ["PANEL_UNI_ROOT"] = str(raiz.parent / "sin-montar")
    assert client.get(f"/api/uni/archivos/{a['id']}/contenido").status_code == 409
    os.environ["PANEL_UNI_ROOT"] = str(raiz)
    assert not client.get(f"/api/uni/archivos/{a['id']}/info").json()["falta"]


def test_un_archivo_que_sale_de_la_carpeta_no_se_sirve(client, raiz, tmp_path):
    aid = _asig(client, "SOLINK", carpeta="Segundo/Sistemas Operativos")
    _confirmar_todo(client, aid)
    t2 = _temas(client, aid)["Tema 2 · Procesos"]
    a = client.get(f"/api/uni/temas/{t2['id']}/archivos").json()["archivos"][0]
    secreto = tmp_path / "secreto.pdf"
    secreto.write_bytes(b"%PDF secreto")
    p = raiz / "Segundo" / "Sistemas Operativos" / a["ruta"]
    p.unlink()
    p.symlink_to(secreto)  # alguien cambia el archivo por un enlace que sale de la raíz
    r = client.get(f"/api/uni/archivos/{a['id']}/contenido")
    assert r.status_code in (404, 422) and b"secreto" not in r.content


# ─────────────────────────────────────────────
# Fusionar y separar
# ─────────────────────────────────────────────


def test_fusionar_lleva_archivos_ejercicios_y_tareas_y_se_separa(client, raiz):
    aid = _asig(client, "SOFUS", carpeta="Segundo/Sistemas Operativos")
    _confirmar_todo(client, aid)
    temas = _temas(client, aid)
    t2, t3 = temas["Tema 2 · Procesos"], temas["Tema 3 · Hilos"]
    ej = client.post(
        "/api/uni/ejercicios", json={"asignatura_id": aid, "titulo": "Crear hilos", "temas": [t3["id"]]}
    ).json()["id"]
    tarea_id = client.post(
        "/api/items", json={"text": "Repasar hilos", "type": "tarea", "asignatura_id": aid, "temas": [t3["id"]]}
    ).json()["id"]
    assert client.post(f"/api/uni/temas/{t3['id']}/fusionar", json={"destino_id": t3["id"]}).status_code == 422
    assert client.post(f"/api/uni/temas/{t3['id']}/fusionar", json={"destino_id": t2["id"]}).status_code == 200
    temas = _temas(client, aid)
    assert "Tema 3 · Hilos" not in temas and temas["Tema 2 · Procesos"]["pdfs"] == 4
    assert client.get("/api/uni/ejercicios", params={"tema": t2["id"]}).json()["total"] == 1
    assert client.get("/api/uni/ejercicios", params={"tema": t3["id"]}).json()["total"] == 1  # cuenta como el otro
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == tarea_id)
    assert item["temas"] == [t2["id"]]  # la tarea pasa al tema con el que se fusionó
    # la sincronía no lo resucita; separar lo devuelve con sus archivos
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    assert "Tema 3 · Hilos" not in _temas(client, aid)
    assert client.post(f"/api/uni/temas/{t3['id']}/separar").json()["archivos"] == 1
    temas = _temas(client, aid)
    assert temas["Tema 3 · Hilos"]["pdfs"] == 1 and temas["Tema 2 · Procesos"]["pdfs"] == 3
    assert next(
        e for e in client.get("/api/uni/ejercicios", params={"asignatura": aid}).json()["ejercicios"] if e["id"] == ej
    )["temas"] == [t2["id"]]  # el ejercicio se queda en el otro


# ─────────────────────────────────────────────
# Ejercicios
# ─────────────────────────────────────────────


def test_ejercicios_filtros_temas_y_papelera(client, raiz):
    aid = _asig(client, "SOEJ", carpeta="Segundo/Sistemas Operativos")
    otra = _asig(client, "OTRAEJ")
    _confirmar_todo(client, aid)
    temas = _temas(client, aid)
    t1, t2 = temas["Tema 1"]["id"], temas["Tema 2 · Procesos"]["id"]
    pdf = client.get(f"/api/uni/temas/{t2}/archivos").json()["archivos"][0]["id"]
    crear = lambda **kw: client.post("/api/uni/ejercicios", json={"asignatura_id": aid, **kw})  # noqa: E731
    e1 = crear(titulo="Round robin", temas=[t2], dificultad=2, archivo_id=pdf, pagina=7).json()["id"]
    e2 = crear(titulo="Fork y exec", temas=[t1, t2], dificultad=3, enunciado="Dibuja el árbol de procesos").json()["id"]
    crear(titulo="Repaso", estado="hecho")
    assert crear(titulo="Malo", temas=[999999]).status_code == 422
    assert (
        client.post("/api/uni/ejercicios", json={"asignatura_id": otra, "titulo": "x", "temas": [t1]}).status_code
        == 422
    )
    assert crear(titulo="Malo", dificultad=5).status_code == 422
    assert crear(titulo="Malo", estado="regular").status_code == 422

    get = lambda **p: client.get("/api/uni/ejercicios", params={"asignatura": aid, **p}).json()  # noqa: E731
    assert get()["total"] == 3 and get()["hechos"] == 1
    assert [e["titulo"] for e in get(tema=t2)["ejercicios"]] == ["Round robin", "Fork y exec"]
    assert [e["titulo"] for e in get(tema=t1)["ejercicios"]] == ["Fork y exec"]
    assert [e["titulo"] for e in get(dificultad=3)["ejercicios"]] == ["Fork y exec"]
    assert [e["titulo"] for e in get(estado="pendiente")["ejercicios"]] == ["Round robin", "Fork y exec"]
    assert [e["titulo"] for e in get(q="arbol")["ejercicios"]] == ["Fork y exec"]  # sin tildes
    e = get(tema=t2)["ejercicios"][0]
    assert e["archivo"]["id"] == pdf and e["archivo"]["visor"] and e["pagina"] == 7

    client.patch(f"/api/uni/ejercicios/{e1}", json={"estado": "hecho", "temas": [t1], "dificultad": 0})
    e = next(x for x in get()["ejercicios"] if x["id"] == e1)
    assert e["estado"] == "hecho" and e["hecho_at"] and e["temas"] == [t1] and e["dificultad"] is None
    client.patch(f"/api/uni/ejercicios/{e2}", json={"before_id": e1})
    assert [x["id"] for x in get()["ejercicios"]][:2] == [e2, e1]
    v = client.get("/api/uni").json()
    assert next(t for t in v["temas"] if t["id"] == t1)["ejercicios"] == 2
    assert next(a for a in v["asignaturas"] if a["id"] == aid)["ejercicios"] == 3

    # con ejercicios, la asignatura no se borra (se archiva)
    assert client.delete(f"/api/uni/asignaturas/{aid}").status_code == 409
    # borrar va a la papelera con sus temas y se recupera
    r = client.delete(f"/api/uni/ejercicios/{e2}").json()
    assert r["undo_token"] and get()["total"] == 2
    assert client.post(f"/api/trash/brain/{r['undo_token']}/restore").status_code == 200
    assert next(x for x in get()["ejercicios"] if x["id"] == e2)["temas"] == [t1, t2]


def test_borrar_tema_manual_devuelve_sus_archivos(client, raiz):
    aid = _asig(client, "SOMAN", carpeta="Segundo/Sistemas Operativos")
    _confirmar_todo(client, aid)
    t1 = _temas(client, aid)["Tema 1"]
    manual = client.post(f"/api/uni/asignaturas/{aid}/temas", json={"titulo": "Repaso"}).json()["id"]
    a = client.get(f"/api/uni/temas/{t1['id']}/archivos").json()["archivos"][0]
    client.patch(f"/api/uni/archivos/{a['id']}", json={"tema_id": manual})
    assert client.get(f"/api/uni/temas/{manual}/archivos").json()["archivos"][0]["id"] == a["id"]
    r = client.delete(f"/api/uni/temas/{manual}").json()
    assert r["undo_token"]
    assert [x["id"] for x in client.get(f"/api/uni/temas/{t1['id']}/archivos").json()["archivos"]] == [a["id"]]


# ─────────────────────────────────────────────
# Migración 26
# ─────────────────────────────────────────────


def test_migracion_26_no_pierde_nada_y_se_deshace(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT, parent_id INTEGER, sort_order REAL, created_at REAL, note_id TEXT, note_task TEXT, category TEXT)"
    )
    conn.execute(
        "CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL, watch_later INTEGER DEFAULT 0, watched INTEGER DEFAULT 0)"
    )
    apply_pending(conn, [m for m in MIGRATIONS if m.version <= 25])
    conn.execute("INSERT INTO asignaturas (id, nombre, codigo, carpeta) VALUES (1, 'Gestión', 'GI', 'Segundo/GI')")
    conn.execute("INSERT INTO temas (id, asignatura_id, titulo, ruta, tipo) VALUES (1, 1, 'Tema 1', 't1', 'carpeta')")
    antes = [tuple(r) for r in conn.execute("SELECT * FROM asignaturas")]
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 26]) == [26]
    a = conn.execute("SELECT * FROM asignaturas").fetchone()
    assert (a["ignorar"], a["por_confirmar"], a["codigo"]) == ("[]", 0, "GI")
    conn.execute("UPDATE asignaturas SET ignorar='[\"guia.pdf\"]'")
    conn.execute(
        "INSERT INTO uni_archivos (asignatura_id, tema_id, ruta, nombre, ext, pagina) VALUES (1, 1, 't1/a.pdf', 'a.pdf', 'pdf', 5)"
    )
    conn.execute("INSERT INTO uni_ejercicios (asignatura_id, titulo) VALUES (1, 'E1')")
    conn.execute("INSERT INTO uni_ejercicio_temas VALUES (1, 1)")
    revert(conn, MIGRATIONS, 25)
    assert [tuple(r) for r in conn.execute("SELECT * FROM asignaturas")] == antes  # como estaba
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='uni_archivos'").fetchone()
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 26]) == [26]  # vuelve con sus datos
    assert conn.execute("SELECT pagina FROM uni_archivos").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM uni_ejercicio_temas").fetchone()[0] == 1
    assert conn.execute("SELECT ignorar FROM asignaturas").fetchone()[0] == '["guia.pdf"]'
