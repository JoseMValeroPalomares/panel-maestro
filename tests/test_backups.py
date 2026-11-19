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
    r = client.post(
        f"/api/backups/{origen}/restore", json={"confirm": "RESTAURAR", "parts": ["notas", "cerebro", "comidas"]}
    )
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


# ─────────────────────────────────────────────
# D-3: la restauración devuelve todo lo que la copia guarda
# ─────────────────────────────────────────────

import hashlib  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

from app import versions  # noqa: E402


def _trees() -> dict[str, str]:
    """sha256 de cada archivo de lo que la copia tiene que devolver."""
    roots = {
        "notes": config.NOTES_DIR,
        "versions": config.DATA_DIR / "versions",
        "trash": config.TRASH_DIR,
        "dotfiles_base": config.DATA_DIR / "dotfiles_base",
        "uploads": config.UPLOADS_DIR,
        "adjuntos": config.DATA_DIR / "adjuntos",
        "facturas": config.DATA_DIR / "facturas",
    }
    out = {}
    for name, root in roots.items():
        for p in sorted(Path(root).rglob("*")) if Path(root).is_dir() else []:
            if p.is_file():
                out[f"{name}/{p.relative_to(root).as_posix()}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    if config.LLM_MODELS_FILE.is_file():
        out["llm"] = hashlib.sha256(config.LLM_MODELS_FILE.read_bytes()).hexdigest()
    return out


def _counts(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(db)
    try:
        tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def _wipe_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"
        ).fetchall():
            conn.execute(f'DELETE FROM "{t}"')
        conn.commit()
    finally:
        conn.close()


def test_ida_y_vuelta_completa(client, limpio):
    # Datos de todo tipo: notas con versiones, una nota en la papelera, imagen, ajustes y filas en las dos BDs
    client.post("/api/notes/rt-nota", json={"title": "RT", "category": "Copias", "content": "v1"})
    versions.snapshot("rt-nota", force=True)
    client.post("/api/notes/rt-nota", json={"title": "RT", "category": "Copias", "content": "v2"})
    client.post("/api/notes/rt-borrada", json={"title": "RT borrada", "category": "Copias", "content": "x"})
    assert client.delete("/api/notes/rt-borrada").json()["undo_token"]
    client.post("/api/inbox", json={"content": "Tarea de la copia"})
    tid = client.get("/api/items").json()["items"][0]["id"]
    assert (
        client.post(f"/api/items/{tid}/adjuntos", files={"archivo": ("plano.pdf", b"%PDF-1.4 rt")}).status_code == 200
    )
    assert client.post("/api/finance/facturas", files={"archivo": ("luz.pdf", b"%PDF-1.4 factura")}).status_code == 200
    client.post("/comidas/api/ingredients", json={"nombre": "Ingrediente RT", "kcal_100g": 5})
    (config.UPLOADS_DIR / "rt").mkdir(parents=True, exist_ok=True)
    (config.UPLOADS_DIR / "rt" / "foto.webp").write_bytes(b"\x00imagen\xff")
    base = config.DATA_DIR / "dotfiles_base"
    (base / "stow" / "zsh").mkdir(parents=True, exist_ok=True)
    (base / "stow" / "zsh" / ".zshrc").write_text("export A=1\n")
    (base / ".ultima-subida").write_text("123.0")
    config.LLM_MODELS_FILE.write_text('{"modelos": []}\n')

    trees, brain, comidas = _trees(), _counts(config.BRAIN_DB), _counts(config.COMIDAS_DB)
    assert any(k.startswith("versions/rt-nota/") for k in trees) and any(k.startswith("trash/") for k in trees)
    name = backup.create_backup("manual")["filename"]
    with zipfile.ZipFile(backup.BACKUPS_DIR / name) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["format"] == 3 and manifest["counts"]["versiones"] >= 1 and manifest["counts"]["papelera"] >= 1
    assert "data/llm_modelos.json" in manifest["files"] and "dotfiles_base/stow/zsh/.zshrc" in manifest["files"]

    # Se pierde todo
    for root in (
        config.NOTES_DIR,
        config.DATA_DIR / "versions",
        config.TRASH_DIR,
        base,
        config.UPLOADS_DIR,
        config.DATA_DIR / "adjuntos",
        config.DATA_DIR / "facturas",
    ):
        shutil.rmtree(root, ignore_errors=True)
    config.NOTES_DIR.mkdir(parents=True)
    config.LLM_MODELS_FILE.unlink()
    _wipe_db(config.BRAIN_DB)
    _wipe_db(config.COMIDAS_DB)
    assert _trees() == {} and _counts(config.BRAIN_DB)["notes"] == 0

    r = backup.restore_backup(name)
    assert r["restored"]["historial"] >= 1 and r["restored"]["papelera"] >= 1 and r["restored"]["modelos_ia"]
    assert _trees() == trees
    assert _counts(config.BRAIN_DB) == brain and _counts(config.COMIDAS_DB) == comidas

    # Y la nota borrada se puede sacar de la papelera después de restaurar
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["title"] == "RT borrada")
    assert client.post(f"/api/trash/brain/{entry['token']}/restore").status_code == 200
    assert client.get("/api/notes/rt-borrada").json()["title"] == "RT borrada"


def test_restaurar_no_pisa_historial_ni_papelera(client, limpio):
    client.post("/api/notes/rt-hist", json={"title": "H", "category": "Copias", "content": "a"})
    versions.snapshot("rt-hist", force=True)
    name = backup.create_backup("manual")["filename"]
    vdir = config.DATA_DIR / "versions" / "rt-hist"
    vfile = sorted(vdir.glob("*.md"))[0]
    vfile.write_text("cambiada a mano", encoding="utf-8")
    (vdir / "9999999999999.md").write_text("posterior a la copia", encoding="utf-8")
    backup.restore_backup(name, ["historial"])
    assert vfile.read_text(encoding="utf-8") == "cambiada a mano"  # lo que ya hay no se pisa
    assert (vdir / "9999999999999.md").exists()  # ni se borra


def test_zips_de_formato_1_y_2_siguen_valiendo(client, limpio):
    client.post("/api/notes/rt-f", json={"title": "Formato", "category": "Copias", "content": "actual"})
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    (config.TRASH_DIR / "tok-viva").mkdir(exist_ok=True)
    (config.TRASH_DIR / "tok-viva" / "x.md").write_text("en la papelera")
    nota = "---\ntitle: Formato viejo\ncategory: Copias\n---\n\nde la copia\n"
    db_copy = config.DATA_DIR / "f1.db"
    backup._sqlite_copy(config.BRAIN_DB, db_copy)
    # Formato 1: sin manifiesto, solo notas y brain.db
    # Las copias llevan el resto de notas tal cual: restaurar quita las que no están, y otros tests cuentan con ellas
    others = [p for p in config.NOTES_DIR.glob("*.md") if p.name != "rt-f.md"]
    f1 = "backup_20250102_000000.zip"
    with zipfile.ZipFile(backup.BACKUPS_DIR / f1, "w") as zf:
        zf.writestr("notes/rt-f.md", nota)
        for p in others:
            zf.write(p, f"notes/{p.name}")
        zf.write(db_copy, "data/brain.db")
    # Formato 2: con versiones pero sin papelera ni ajustes
    f2 = "backup_manual_20250103_000000.zip"
    with zipfile.ZipFile(backup.BACKUPS_DIR / f2, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": 2, "kind": "manual", "files": {}, "counts": {"notas": 1}}))
        zf.writestr("notes/rt-f.md", nota)
        for p in others:
            zf.write(p, f"notes/{p.name}")
        zf.writestr("versions/rt-f/1700000000000.md", "versión vieja")
        zf.write(db_copy, "data/brain.db")
    db_copy.unlink()
    for name in (f1, f2):
        assert backup.read_manifest(name)["format"] in (1, 2)
        r = client.post(f"/api/backups/{name}/restore", json={"confirm": "RESTAURAR"})
        assert r.status_code == 200, r.text
        assert client.get("/api/notes/rt-f").json()["title"] == "Formato viejo"
        assert (config.TRASH_DIR / "tok-viva" / "x.md").exists()  # lo que la copia no trae no se toca
    assert (config.DATA_DIR / "versions" / "rt-f" / "1700000000000.md").read_text() == "versión vieja"
    assert (backup.BACKUPS_DIR / f1).exists() and (backup.BACKUPS_DIR / f2).exists()


# ─────────────────────────────────────────────
# D-2: espejo en otra carpeta
# ─────────────────────────────────────────────


def test_espejo_copia_hash_y_rotacion(limpio, monkeypatch, tmp_path):
    mirror = tmp_path / "espejo"
    mirror.mkdir()
    monkeypatch.setattr(config, "BACKUP_MIRROR", mirror)
    for i in range(12):
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() - 86400 * (i + 1)))
        (mirror / f"backup_manual_{stamp}.zip").write_bytes(b"")
    (mirror / "backup_20200101_000000.zip").write_bytes(b"")  # formato antiguo: no se toca
    (mirror / "otra-cosa.txt").write_text("de otro")
    info = backup.create_backup("manual")
    assert info["mirror"] == "ok"
    copia = mirror / info["filename"]
    assert copia.read_bytes() == (backup.BACKUPS_DIR / info["filename"]).read_bytes()
    assert hashlib.sha256(copia.read_bytes()).hexdigest() == backup._read_status()["mirror"]["sha256"]
    manuals = [p for p in mirror.glob("backup_manual_*.zip")]
    assert len(manuals) == backup.KINDS["manual"] and copia in manuals
    assert (mirror / "backup_20200101_000000.zip").exists() and (mirror / "otra-cosa.txt").exists()
    assert not list(mirror.glob("*.part"))
    st = backup.status()
    assert (
        st["health"] == "ok" and st["mirror"]["state"] == "ok" and st["mirror"]["count"] == backup.KINDS["manual"] + 1
    )  # + la antigua


def test_espejo_ausente_es_aviso_no_error(client, limpio, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BACKUP_MIRROR", tmp_path / "unidad-sin-montar" / "panel")
    info = backup.create_backup("manual")
    assert (backup.BACKUPS_DIR / info["filename"]).exists() and info["mirror"] == "error"
    assert not (tmp_path / "unidad-sin-montar").exists()  # nunca se crea
    st = client.get("/api/backups/status").json()
    assert st["health"] == "ok" and st["mirror"]["state"] == "error" and st["mirror"]["error"]
    item = next(i for i in client.get("/api/status").json()["items"] if i["key"] == "backup-mirror")
    assert item["state"] == "aviso"


def test_espejo_con_hash_distinto_no_se_queda(limpio, monkeypatch, tmp_path):
    mirror = tmp_path / "espejo"
    mirror.mkdir()
    monkeypatch.setattr(config, "BACKUP_MIRROR", mirror)
    real = backup._sha256
    calls = {"n": 0}

    def falso(path):
        calls["n"] += 1
        return "0" * 64 if str(path).endswith(".part") else real(path)

    monkeypatch.setattr(backup, "_sha256", falso)
    info = backup.create_backup("manual")
    assert info["mirror"] == "error" and not list(mirror.iterdir())
    assert backup.status()["health"] == "ok"


def test_sin_espejo_configurado(limpio, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_MIRROR", None)
    assert "mirror" not in backup.create_backup("manual") and backup.status()["mirror"] is None


# ─────────────────────────────────────────────
# D-1: las copias se recuperan aunque el equipo durmiese a las 03:30
# ─────────────────────────────────────────────


def _fake(kind: str, hours_ago: float) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() - hours_ago * 3600))
    name = f"backup_{kind}_{stamp}.zip"
    (backup.BACKUPS_DIR / name).write_bytes(b"")
    return name


def test_recuperacion_con_la_ultima_de_hace_30_h_crea_una_diaria(limpio):
    backup.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    _fake("semanal", 72)
    _fake("diaria", 30)
    _fake("manual", 1)  # las manuales no cuentan como automáticas
    made = backup.ensure_recent_backup()
    assert made and made.startswith("backup_diaria_")
    assert backup.ensure_recent_backup() is None  # recién hecha: no repite


def test_recuperacion_con_la_ultima_de_hace_2_h_no_hace_nada(limpio):
    backup.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    _fake("diaria", 2)
    before = {p.name for p in backup.BACKUPS_DIR.glob("backup_*.zip")}
    assert backup.ensure_recent_backup() is None
    assert {p.name for p in backup.BACKUPS_DIR.glob("backup_*.zip")} == before


def test_recuperacion_sin_copias_hace_la_primera_semanal(limpio):
    assert backup.ensure_recent_backup().startswith("backup_semanal_")


def test_recuperacion_que_falla_no_lanza(limpio, monkeypatch):
    def boom(kind="manual"):
        raise backup.BackupError("disco lleno")

    monkeypatch.setattr(backup, "create_backup", boom)
    assert backup.ensure_recent_backup() is None


def test_purga_de_la_papelera_como_mucho_una_vez_al_dia(monkeypatch):
    from app import trash

    calls = []
    monkeypatch.setattr(trash, "purge_expired", lambda: calls.append(1) or 0)
    trash._purge_state_file().unlink(missing_ok=True)
    assert trash.purge_if_due() == 0 and trash.purge_if_due() is None
    assert len(calls) == 1


def test_planificador_recupera_al_arrancar(monkeypatch, tmp_path, limpio):
    """Con el planificador activo, el arranque programa la recuperación para ya, en segundo plano."""
    from apscheduler.schedulers.background import BackgroundScheduler

    import app.main as cerebro

    sched = BackgroundScheduler()
    monkeypatch.setattr(cerebro, "scheduler", sched)
    monkeypatch.setattr(cerebro.config, "DISABLE_SCHEDULER", False)
    for name in ("backfill_thumbnails", "backfill_video_metadata", "backfill_channels"):
        monkeypatch.setattr(cerebro, name, lambda: None)
    done = []
    monkeypatch.setattr(cerebro, "_catch_up", lambda: done.append(time.time()))

    import asyncio

    async def run():
        async with cerebro.lifespan(cerebro.app):
            jobs = {j.id: j for j in sched.get_jobs()}
            assert {"daily_backup", "trash_purge", "catch_up"} <= set(jobs)
            assert jobs["daily_backup"].misfire_grace_time >= 3600 and jobs["daily_backup"].coalesce
            for _ in range(50):
                if done:
                    break
                await asyncio.sleep(0.1)

    asyncio.run(run())
    assert done, "la recuperación no se lanzó al arrancar"


# ─────────────────────────────────────────────
# C-5: la salud de las copias se ve en Hoy y en Conexiones solo cuando no es «ok»
# ─────────────────────────────────────────────


def test_salud_de_las_copias_en_status_y_hoy(client, limpio):
    backup.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    _fake("diaria", 50)
    st = client.get("/api/status").json()
    assert st["backups"]["health"] == "antigua" and st["backups"]["age_h"] >= 49
    item = next(i for i in st["items"] if i["key"] == "backups")
    assert item["state"] == "antigua" and "50 h" in item["detail"]
    hoy = client.get("/api/today").json()
    assert hoy["copias"]["health"] == "antigua"

    backup.create_backup("manual")
    assert client.get("/api/status").json()["backups"]["health"] == "ok"
    assert client.get("/api/today").json()["copias"] is None
