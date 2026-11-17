"""Universidad (tanda D): repartir los documentos en temas por el número del nombre, organizar con sugerencias,
vincular a mano cualquier documento de la raíz (también de fuera de la carpeta de la asignatura), quitar un
documento de su tema y el explorador. Todo en solo lectura sobre el disco."""

import hashlib
import os
import sqlite3

import pytest

from app.migrations import MIGRATIONS
from app.uni_organizar import clave_de_nombre, detectar
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
    """Como la carpeta real de Gráfica: todo lo de teoría en «Teoria», prácticas en «pr1»/«pr2» y un PDF común
    fuera de la asignatura."""
    root = tmp_path / "Uja"
    gi = root / "Grafica"
    (gi / "Teoria").mkdir(parents=True)
    (gi / "pr2" / "pr2a_conan").mkdir(parents=True)
    (gi / "pr1").mkdir()
    for n in ("Tema 4.pdf", "Tema 5.pdf", "Chuletario_Tema3_Proceso.pdf", "Relación 4 - Algoritmos.pdf", "Chuleta.pdf"):
        (gi / "Teoria" / n).write_bytes(b"%PDF-1.4 " + n.encode())
    (gi / "pr2" / "IGV_Practica2_pr2a_Mallas.pdf").write_bytes(b"%PDF-1.4 mallas")
    (gi / "pr2" / "Practica1 - repaso.pdf").write_bytes(b"%PDF-1.4 repaso")
    (gi / "pr2" / "pr2a_conan" / "CMakeLists.txt").write_text("project(x)")
    (gi / "pr1" / "enunciado.pdf").write_bytes(b"%PDF-1.4 p1")
    (root / "Comun").mkdir()
    (root / "Comun" / "Normativa.pdf").write_bytes(b"%PDF-1.4 normativa")
    monkeypatch.setenv("PANEL_UNI_ROOT", str(root))
    return root


def _gi(client, codigo):
    r = client.post("/api/uni/asignaturas", json={"nombre": "Gráfica", "codigo": codigo, "carpeta": "Grafica"})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    r = client.post(f"/api/uni/asignaturas/{aid}/escaneo", json={"temas": [{"ruta": t["ruta"]} for t in p["nuevos"]]})
    assert r.status_code == 200, r.text
    return aid


def _temas(client, aid):
    return {t["titulo"]: t for t in client.get("/api/uni").json()["temas"] if t["asignatura_id"] == aid}


def _archivos(client, aid):
    return {f["nombre"]: f for f in client.get(f"/api/uni/asignaturas/{aid}/archivos").json()["archivos"]}


def test_detectar_por_nombre_y_por_carpeta():
    casos = {
        "Teoria/Chuletario_Tema3_Proceso_de_visualizacion.pdf": ("teoria", 3),
        "Teoria/Relación de Ejercicios 03 - Representación.docx.pdf": ("teoria", 3),
        "Teoria/Relación 4 - Algoritmos del pipeline.pdf": ("teoria", 4),
        "tema3 - primera parte.pdf": ("teoria", 3),
        "lesson3_second_part.pdf": ("teoria", 3),
        "T02 - Procesos.pdf": ("teoria", 2),
        "pr2/IGV_Practica2_pr2a_Mallas_de_Triangulos.pdf": ("practicas", 2),
        "práctica1.pdf": ("practicas", 1),
        "Practica 3/guion.pdf": ("practicas", 3),
        "Practica 5/g2afm00098pr5proy3/memoria.pdf": ("practicas", 5),
        "Practica 5/Practica1 - REDMINE.docx (3).pdf": ("practicas", 1),  # el nombre manda sobre la carpeta
    }
    for ruta, k in casos.items():
        assert detectar(ruta) == k, ruta
    for nada in (
        "Instalación de software 2025-2026.pdf",
        "Chuletario_Transformaciones.pdf",
        "mp3 notas.pdf",
        "0 Entorno.pdf",
    ):
        assert detectar(nada) is None, nada
    assert clave_de_nombre("Tema 3 · Proceso de visualización") == ("teoria", 3)
    assert clave_de_nombre("Práctica 2") == ("practicas", 2)


def test_la_propuesta_junta_las_partes_del_mismo_tema(client, tmp_path, monkeypatch):
    root = tmp_path / "Uja"
    bd = root / "BD"
    bd.mkdir(parents=True)
    for n in ("tema1.pdf", "tema3 - primera parte.pdf", "tema3 - segunda parte.pdf", "lesson3_first_part.pdf"):
        (bd / n).write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("PANEL_UNI_ROOT", str(root))
    aid = client.post("/api/uni/asignaturas", json={"nombre": "Bases", "codigo": "BDPART", "carpeta": "BD"}).json()[
        "id"
    ]
    p = client.get(f"/api/uni/asignaturas/{aid}/escaneo").json()
    por_ruta = {t["ruta"]: t for t in p["nuevos"]}
    primero = por_ruta["lesson3_first_part.pdf"]  # orden natural: «lesson3…» antes que «tema3…»
    assert (primero["accion"], primero["titulo"]) == ("crear", "Tema 3")
    for r in ("tema3 - primera parte.pdf", "tema3 - segunda parte.pdf"):
        assert (por_ruta[r]["accion"], por_ruta[r]["destino"]) == ("fusionar", "lesson3_first_part.pdf")
    body = [{k: t[k] for k in ("ruta", "titulo", "grupo", "accion", "destino")} for t in p["nuevos"]]
    assert client.post(f"/api/uni/asignaturas/{aid}/escaneo", json={"temas": body}).json()["fusionados"] == 2
    t = _temas(client, aid)
    assert set(t) == {"Tema 1", "Tema 3"}
    assert t["Tema 3"]["archivos"] == 3


def test_organizar_sugiere_reparte_y_crea_los_temas(client, raiz):
    huella = _huella(raiz)
    aid = _gi(client, "GIORG")
    t = _temas(client, aid)
    assert {"Teoria", "Práctica 1", "Práctica 2"} <= set(t)
    a = _archivos(client, aid)
    assert "CMakeLists.txt" not in a  # ruido de las prácticas de C++
    assert a["Tema 4.pdf"]["tema_id"] == t["Teoria"]["id"]

    plan = client.get(f"/api/uni/asignaturas/{aid}/organizar").json()
    sug = {x["nombre"]: x["sugerido"] for x in plan["archivos"]}
    assert sug["Tema 4.pdf"] == sug["Relación 4 - Algoritmos.pdf"] == "nuevo:teoria:4"
    assert sug["Chuletario_Tema3_Proceso.pdf"] == "nuevo:teoria:3"
    assert sug["Chuleta.pdf"] is None  # sin número: se queda en «Teoria»
    assert sug["IGV_Practica2_pr2a_Mallas.pdf"] is None  # ya está en su práctica
    assert sug["Practica1 - repaso.pdf"] is None  # dentro de la Práctica 2: no se mueve solo
    assert list(plan["nuevos"]) == ["teoria:3", "teoria:4", "teoria:5"]

    cambios = [{"ruta": x["ruta"], "destino": x["sugerido"]} for x in plan["archivos"] if x["sugerido"]]
    r = client.post(
        f"/api/uni/asignaturas/{aid}/organizar",
        json={"cambios": cambios, "titulos": {"teoria:3": "Tema 3 · Visualización"}},
    ).json()
    assert (r["temas_creados"], r["movidos"]) == (3, 4)
    t = _temas(client, aid)
    assert {"Tema 3 · Visualización", "Tema 4", "Tema 5"} <= set(t)
    assert t["Tema 4"]["pdfs"] == 2 and t["Teoria"]["pdfs"] == 1
    orden = [x for x in t if x.startswith("Tema")]
    assert orden == ["Tema 3 · Visualización", "Tema 4", "Tema 5"]
    # la sincronía no los devuelve a «Teoria» y un PDF nuevo con número va solo a su tema
    (raiz / "Grafica" / "Teoria" / "Tema 5 - ejercicios.pdf").write_bytes(b"%PDF-1.4 e5")
    s = client.post(f"/api/uni/asignaturas/{aid}/sync").json()
    assert s["archivos"]["repartidos"] == 1
    a = _archivos(client, aid)
    assert a["Tema 4.pdf"]["tema_id"] == t["Tema 4"]["id"]
    assert a["Tema 5 - ejercicios.pdf"]["tema_id"] == t["Tema 5"]["id"]
    assert client.get(f"/api/uni/asignaturas/{aid}/organizar").json()["sugerencias"] == 0
    os.remove(raiz / "Grafica" / "Teoria" / "Tema 5 - ejercicios.pdf")
    assert _huella(raiz) == huella


def test_vincular_un_pdf_suelto_de_fuera_y_quitarlo(client, raiz):
    huella = _huella(raiz)
    aid = _gi(client, "GIVIN")
    t = _temas(client, aid)
    ex = client.get("/api/uni/explorar", params={"ruta": "Grafica/Teoria", "asignatura": aid}).json()
    assert [m["nombre"] for m in ex["migas"]] == ["Grafica", "Teoria"]
    assert ex["inicio"] == "Grafica"
    por = {f["nombre"]: f for f in ex["archivos"]}
    assert por["Tema 4.pdf"]["vinculado"]["titulo"] == "Teoria"
    raiz_ex = client.get("/api/uni/explorar", params={"asignatura": aid}).json()
    assert {c["nombre"] for c in raiz_ex["carpetas"]} == {"Comun", "Grafica"}
    for malo in ("../", "/etc", "Grafica/../../"):
        assert client.get("/api/uni/explorar", params={"ruta": malo}).status_code == 422, malo

    p1 = t["Práctica 1"]["id"]
    r = client.post(
        f"/api/uni/temas/{p1}/vincular", json={"rutas": ["Comun/Normativa.pdf", "Grafica/Teoria/Chuleta.pdf"]}
    )
    assert r.json() == {"nuevos": 1, "movidos": 1, "iguales": 0}
    a = _archivos(client, aid)
    assert a["Normativa.pdf"]["fuera"] and a["Normativa.pdf"]["tema_id"] == p1
    assert a["Chuleta.pdf"]["tema_id"] == p1
    assert client.get(f"/api/uni/archivos/{a['Normativa.pdf']['id']}/contenido").content == b"%PDF-1.4 normativa"
    # sincronizar no lo marca como no encontrado ni devuelve la chuleta a «Teoria»
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    a = _archivos(client, aid)
    assert not a["Normativa.pdf"]["falta"] and a["Chuleta.pdf"]["tema_id"] == p1
    # no es un documento, o sale de la raíz: 422 y no se guarda nada
    assert (
        client.post(
            f"/api/uni/temas/{p1}/vincular", json={"rutas": ["Grafica/pr2/pr2a_conan/CMakeLists.txt"]}
        ).status_code
        == 422
    )
    assert client.post(f"/api/uni/temas/{p1}/vincular", json={"rutas": ["../fuera.pdf"]}).status_code == 422
    # una carpeta entera
    assert client.post(f"/api/uni/temas/{p1}/vincular", json={"rutas": []}).status_code == 422
    r = client.post(f"/api/uni/temas/{p1}/vincular", json={"carpetas": ["Grafica/pr2"]})
    assert r.json()["movidos"] == 2

    # quitar de su tema: deja de verse y la sincronía no lo devuelve
    fid = _archivos(client, aid)["Tema 4.pdf"]["id"]
    assert client.patch(f"/api/uni/archivos/{fid}", json={"oculto": True}).status_code == 200
    client.post(f"/api/uni/asignaturas/{aid}/sync")
    assert "Tema 4.pdf" not in _archivos(client, aid)
    assert _temas(client, aid)["Teoria"]["pdfs"] == 3  # Tema 5, Chuletario_Tema3 y Relación 4
    plan = client.get(f"/api/uni/asignaturas/{aid}/organizar").json()
    x = next(x for x in plan["archivos"] if x["nombre"] == "Tema 4.pdf")
    assert x["quitado"] and x["tema_id"] is None
    # y se vuelve a poner organizando
    client.post(
        f"/api/uni/asignaturas/{aid}/organizar", json={"cambios": [{"ruta": x["ruta"], "destino": f"tema:{p1}"}]}
    )
    assert _archivos(client, aid)["Tema 4.pdf"]["tema_id"] == p1
    assert _huella(raiz) == huella


def test_migracion_28_se_aplica_y_se_deshace(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE inbox (id INTEGER PRIMARY KEY, content TEXT, item_type TEXT, status TEXT, parent_id INTEGER, sort_order REAL, created_at REAL, note_id TEXT, note_task TEXT, category TEXT)"
    )
    conn.execute(
        "CREATE TABLE resources (id INTEGER PRIMARY KEY, url TEXT, title TEXT, category TEXT, resource_type TEXT, channel TEXT, added_at REAL, watch_later INTEGER DEFAULT 0, watched INTEGER DEFAULT 0)"
    )
    apply_pending(conn, [m for m in MIGRATIONS if m.version < 28])
    conn.execute("INSERT INTO uni_archivos (asignatura_id, tema_id, ruta, nombre) VALUES (1, 1, 'a.pdf', 'a.pdf')")
    apply_pending(conn, MIGRATIONS)
    assert conn.execute("SELECT oculto FROM uni_archivos").fetchone()[0] == 0
    conn.execute("UPDATE uni_archivos SET oculto=1")
    revert(conn, MIGRATIONS, 27)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(uni_archivos)")]
    assert "oculto" not in cols and conn.execute("SELECT COUNT(*) FROM uni_archivos").fetchone()[0] == 1
    apply_pending(conn, MIGRATIONS)
    assert conn.execute("SELECT oculto FROM uni_archivos").fetchone()[0] == 0
