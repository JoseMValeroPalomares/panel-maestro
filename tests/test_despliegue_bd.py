"""scripts/despliegue_bd.py (C-4): la copia y la vuelta atrás de las BDs y del estado del calendario que usa
scripts/desplegar.sh cuando una versión nueva no arranca."""

import json
import sqlite3
from contextlib import closing

import pytest

from scripts import despliegue_bd as d


def _bd(path, filas):
    with closing(sqlite3.connect(path)) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS t (x)")
        c.executemany("INSERT INTO t VALUES (?)", [(f,) for f in filas])
        c.commit()


def test_ida_y_vuelta_deja_todo_como_estaba(tmp_path, capsys):
    brain, comidas, estado = tmp_path / "brain.db", tmp_path / "comidas.db", tmp_path / "calendar_sync_v2.json"
    _bd(brain, ["a", "b"])
    _bd(comidas, ["c"])
    estado.write_text('{"icloud": {"u1": {}}}')
    antes = {p: d.huella(p) for p in (brain, comidas)}
    copia = tmp_path / "copias" / "v1"
    d.main(["copiar", str(copia), str(brain), str(comidas), str(estado)])

    # lo que haría una versión rota: migrar, escribir y dejar un WAL a medias
    with closing(sqlite3.connect(brain)) as c:
        c.execute("CREATE TABLE migracion_25 (y)")
        c.execute("UPDATE t SET x = x || ' (roto)'")
        c.commit()
    _bd(comidas, ["nuevo"])
    estado.write_text('{"icloud": {}}')
    assert d.huella(brain) != antes[brain]

    d.main(["restaurar", str(copia)])
    assert {p: d.huella(p) for p in (brain, comidas)} == antes
    assert estado.read_text() == '{"icloud": {"u1": {}}}'
    with closing(sqlite3.connect(brain)) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='migracion_25'").fetchone()
    manifest = json.loads((copia / d.MANIFEST).read_text())
    assert [e["existia"] for e in manifest] == [True, True, True] and manifest[0]["huella"] == antes[brain]


def test_lo_que_no_existia_vuelve_a_no_existir(tmp_path):
    brain, estado = tmp_path / "brain.db", tmp_path / "calendar_sync_v2.json"
    _bd(brain, ["a"])
    copia = tmp_path / "copia"
    d.main(["copiar", str(copia), str(brain), str(estado)])
    estado.write_text("{}")  # la versión nueva lo creó al sincronizar
    d.main(["restaurar", str(copia)])
    assert not estado.exists()


def test_la_huella_es_del_contenido_no_del_archivo(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    _bd(a, ["x", "y"])
    with closing(sqlite3.connect(a)) as src, closing(sqlite3.connect(b)) as dst:
        src.backup(dst)
    with closing(sqlite3.connect(b)) as c:
        c.execute("VACUUM")  # mismas filas, otras páginas
    assert d.huella(a) == d.huella(b)
    _bd(b, ["z"])
    assert d.huella(a) != d.huella(b)


def test_no_pisa_una_copia_que_ya_existe(tmp_path):
    brain = tmp_path / "brain.db"
    _bd(brain, ["a"])
    (tmp_path / "copia").mkdir()
    with pytest.raises(FileExistsError):
        d.main(["copiar", str(tmp_path / "copia"), str(brain)])


def test_uso(capsys):
    assert d.main([]) == 2 and d.main(["otra", "x"]) == 2
    assert "copiar DESTINO" in capsys.readouterr().err
