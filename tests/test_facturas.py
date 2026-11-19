"""Facturas de Economía (migración 30): subir, ver, descargar, editar, enlazar con un gasto, papelera y purga."""

import time

from app import facturas
from core import config

PDF = b"%PDF-1.4 factura de prueba"


def _subir(client, nombre="Luz_noviembre.pdf", datos=PDF, **campos):
    r = client.post("/api/finance/facturas", files={"archivo": (nombre, datos)}, data=campos)
    assert r.status_code == 200, r.text
    return r.json()


def test_subir_ver_y_descargar(client):
    f = _subir(client, proveedor="Endesa", fecha="2026-11-03", importe="41,20", categoria="Casa")
    assert (f["titulo"], f["proveedor"], f["fecha"], f["importe"], f["pdf"]) == (
        "Luz noviembre",  # el título sale del nombre del archivo
        "Endesa",
        "2026-11-03",
        41.2,
        True,
    )
    r = client.get(f["url"])
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    r = client.get(f["url"] + "?descargar=1")
    assert (
        r.headers["content-disposition"].startswith("attachment")
        and "Luz_noviembre.pdf" in r.headers["content-disposition"]
    )
    # El archivo se guarda con un nombre propio, nunca con el que manda el cliente
    archivos = list((config.DATA_DIR / "facturas").iterdir())
    assert archivos and all("Luz" not in p.name for p in archivos)


def test_html_nunca_en_linea_y_validaciones(client):
    f = _subir(client, nombre="x.html", datos=b"<script>alert(1)</script>")
    r = client.get(f["url"])
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"] == "application/octet-stream"
    assert client.post("/api/finance/facturas", files={"archivo": ("v.pdf", b"")}).status_code == 400
    bad = client.post("/api/finance/facturas", files={"archivo": ("a.pdf", PDF)}, data={"fecha": "2026-02-30"})
    assert bad.status_code == 422
    bad = client.post("/api/finance/facturas", files={"archivo": ("a.pdf", PDF)}, data={"importe": "doce"})
    assert bad.status_code == 422
    assert client.post("/api/finance/facturas", files={"archivo": ("../../evil.pdf", PDF)}).json()["nombre"] == (
        "evil.pdf"
    )


def test_lista_busqueda_anios_y_edicion(client):
    a = _subir(client, nombre="agua.pdf", proveedor="Aguas Jaén", fecha="2025-06-01", importe="20")
    _subir(client, nombre="movil.pdf", proveedor="Operadora", fecha="2026-01-10", importe="9,99")
    d = client.get("/api/finance/facturas", params={"q": "Aguas"}).json()
    assert [x["id"] for x in d["facturas"]] == [a["id"]] and d["total"] == 20
    assert {"2025", "2026"} <= set(client.get("/api/finance/facturas").json()["anios"])
    assert all(x["fecha"].startswith("2025") for x in client.get("/api/finance/facturas?anio=2025").json()["facturas"])
    r = client.patch(f"/api/finance/facturas/{a['id']}", json={"titulo": "Agua junio", "importe": "", "notas": "ok"})
    assert r.status_code == 200 and (r.json()["titulo"], r.json()["importe"], r.json()["notas"]) == (
        "Agua junio",
        None,
        "ok",
    )
    assert client.patch(f"/api/finance/facturas/{a['id']}", json={"titulo": "  "}).status_code == 422


def test_enlace_con_un_gasto(client):
    mid = client.post(
        "/api/finance/movements", json={"fecha": "2026-11-05", "importe": 30, "tipo": "gasto", "concepto": "Gas"}
    ).json()["id"]
    f = _subir(client, movimiento_id=str(mid))
    assert f["movimiento"]["concepto"] == "Gas"
    movs = client.get("/api/finance/movements", params={"month": "2026-11"}).json()["movements"]
    assert next(m for m in movs if m["id"] == mid)["facturas"] == 1
    assert client.get(f"/api/finance/facturas?movimiento_id={mid}").json()["facturas"][0]["id"] == f["id"]
    assert client.patch(f"/api/finance/facturas/{f['id']}", json={"movimiento_id": 999999}).status_code == 422
    # Borrar el gasto no borra la factura
    assert client.delete(f"/api/finance/movements/{mid}").status_code == 200
    assert client.get(f["url"]).status_code == 200


def test_papelera_y_purga(client):
    f = _subir(client, nombre="borrable.pdf")
    d = client.delete(f"/api/finance/facturas/{f['id']}").json()
    assert d["undo_token"]
    assert client.get(f["url"]).status_code == 404
    entrada = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == d["undo_token"])
    assert entrada["label"] == "factura"
    # Mientras la papelera la nombra, el archivo no se purga (ni aunque sea viejo)
    facturas.purge_files(now=time.time() + 7200)
    assert client.post(f"/api/trash/brain/{d['undo_token']}/restore").status_code == 200
    assert client.get(f["url"]).content == PDF
    # Un archivo que nadie nombra se va (si no es recién subido)
    huerfano = config.DATA_DIR / "facturas" / "huerfano.pdf"
    huerfano.write_bytes(b"x")
    facturas.purge_files()
    assert huerfano.exists()
    facturas.purge_files(now=time.time() + 7200)
    assert not huerfano.exists() and client.get(f["url"]).status_code == 200
