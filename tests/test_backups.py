"""Fase 7: copias completas con SQLite backup API, rotación y restauración con copia previa."""
import io
import json
import time
import zipfile

import pytest

from app import backup
from core import config


@pytest.fixture()
def limpio():
    for p in backup.BACKUPS_DIR.glob("backup_*.zip"):
        p.unlink()
    backup.STATUS_FILE.unlink(missing_ok=True)
    yield


def test_copia_manual_completa(client, limpio):
    client.post("/api/notes/bk-nota", json={"title": "BK", "category": "Copias", "content": "original"})
    (config.UPLOADS_DIR / "thumbs").mkdir(parents=True, exist_ok=True)
    (config.UPLOADS_DIR / "thumbs" / "bk.webp").write_bytes(b"img")
    r = client.post("/api/backups/run")
    assert r.status_code == 200, r.text
    info = r.json()["backup"]
    assert info["kind"] == "manual" and info["filename"].startswith("backup_manual_")

    with zipfile.ZipFile(backup.BACKUPS_DIR / info["filename"]) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        db = zf.read("data/brain.db")
    assert {"data/brain.db", "comidas/comidas.db", "notes/bk-nota.md", "uploads/thumbs/bk.webp"} <= names
    assert manifest["counts"]["notas"] >= 1 and manifest["files"]["notes/bk-nota.md"]["sha256"]
    assert db.startswith(b"SQLite format 3")

    lista = client.get("/api/backups").json()["backups"]
    assert lista[0]["filename"] == info["filename"]
    st = client.get("/api/backups/status").json()
    assert st["health"] == "ok" and st["last"]["filename"] == info["filename"]
    det = client.get(f"/api/backups/{info['filename']}").json()
    assert det["manifest"]["kind"] == "manual"

    dl = client.get(f"/api/backups/{info['filename']}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(dl.content)).testzip() is None


def test_nombres_no_validos(client):
    for name in ["..%2Fsecreto.zip", "otra-cosa.zip", "backup_manual_2020.zip"]:
        assert client.get(f"/api/backups/{name}/download").status_code in (404, 422)
    assert client.get("/api/backups/backup_manual_20200101_000000.zip/download").status_code == 404


def test_rotacion(limpio):
    for i in range(12):
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() - 86400 * (i + 1)))
        (backup.BACKUPS_DIR / f"backup_manual_{stamp}.zip").write_bytes(b"")
    (backup.BACKUPS_DIR / "backup_20200101_000000.zip").write_bytes(b"")  # formato antiguo
    backup.create_backup("manual")
    kinds = [b["kind"] for b in backup.list_backups()["backups"]]
    assert kinds.count("manual") == backup.KINDS["manual"]
    assert kinds.count("antigua") == 1  # las antiguas no se borran solas


def test_diaria_y_semanal(limpio):
    assert backup.run_daily_backup().startswith("backup_semanal_")
    assert backup.run_daily_backup().startswith("backup_diaria_")


def test_restaurar_con_copia_previa(client, limpio):
    client.post("/api/notes/bk-r", json={"title": "Antes", "category": "Copias", "content": "v1"})
    ing = client.post("/comidas/api/ingredients", json={"nombre": "Ingrediente BK", "kcal_100g": 10}).json()["id"]
    origen = client.post("/api/backups/run").json()["backup"]["filename"]

    client.post("/api/notes/bk-r", json={"title": "Después", "category": "Copias", "content": "v2"})
    client.post("/api/notes/bk-nueva", json={"title": "Nueva tras la copia", "category": "Copias", "content": "x"})
    client.delete(f"/comidas/api/ingredients/{ing}")

    assert client.post(f"/api/backups/{origen}/restore", json={"confirm": "no"}).status_code == 422
    r = client.post(f"/api/backups/{origen}/restore", json={"confirm": "RESTAURAR", "parts": ["notas", "cerebro", "comidas"]})
    assert r.status_code == 200, r.text
    pre = r.json()["pre_backup"]
    assert pre.startswith("backup_pre-restauracion_")

    assert client.get("/api/notes/bk-r").json()["title"] == "Antes"
    assert not (config.NOTES_DIR / "bk-nueva.md").exists()
    assert client.get("/api/notes/bk-nueva").status_code == 404
    assert any(i["nombre"] == "Ingrediente BK" for i in client.get("/comidas/api/ingredients").json()["ingredients"])

    # Deshacer la restauración = restaurar la copia previa
    client.post(f"/api/backups/{pre}/restore", json={"confirm": "RESTAURAR", "parts": ["notas"]})
    assert (config.NOTES_DIR / "bk-nueva.md").exists()


def test_restaurar_solo_una_parte(client, limpio):
    client.post("/api/notes/bk-parte", json={"title": "Parte", "category": "Copias", "content": "a"})
    origen = backup.create_backup("manual")["filename"]
    client.post("/api/notes/bk-parte", json={"title": "Parte cambiada", "category": "Copias", "content": "b"})
    client.post(f"/api/backups/{origen}/restore", json={"confirm": "RESTAURAR", "parts": ["comidas"]})
    assert client.get("/api/notes/bk-parte").json()["title"] == "Parte cambiada"


def test_zip_con_rutas_maliciosas(client, limpio):
    name = "backup_manual_20250101_000000.zip"
    with zipfile.ZipFile(backup.BACKUPS_DIR / name, "w") as zf:
        zf.writestr("uploads/../../escapado.txt", "x")
    r = client.post(f"/api/backups/{name}/restore", json={"confirm": "RESTAURAR", "parts": ["imagenes"]})
    assert r.status_code == 422
    assert not (config.UPLOADS_DIR.parent / "escapado.txt").exists()


def test_borrar_copia(client, limpio):
    name = backup.create_backup("manual")["filename"]
    assert client.delete(f"/api/backups/{name}").status_code == 200
    assert not (backup.BACKUPS_DIR / name).exists()


def test_pagina_backups(client):
    r = client.get("/backups")
    assert r.status_code == 200 and "backups.js" in r.text
