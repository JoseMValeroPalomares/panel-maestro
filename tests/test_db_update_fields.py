"""A-4: core.db.update_fields, el UPDATE de varios campos que antes repetían siete módulos."""

import sqlite3

import pytest

from core.db import update_fields


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, clave TEXT, a TEXT, b INTEGER)")
    c.execute("INSERT INTO t VALUES (1, 'x', 'viejo', 1), (2, 'y', 'otro', 2)")
    return c


def test_actualiza_solo_lo_dado_y_solo_esa_fila(conn):
    assert update_fields(conn, "t", 1, {"a": "nuevo", "b": None}, ("a", "b")) == 1
    assert conn.execute("SELECT a, b FROM t ORDER BY id").fetchall() == [("nuevo", None), ("otro", 2)]


def test_otra_columna_de_id(conn):
    update_fields(conn, "t", "y", {"b": 5}, ("a", "b"), columna_id="clave")
    assert conn.execute("SELECT b FROM t WHERE id=2").fetchone() == (5,)


def test_sin_valores_no_hace_nada(conn):
    assert update_fields(conn, "t", 1, {}, ("a",)) == 0


@pytest.mark.parametrize(
    "valores, tabla, col",
    [
        ({"id": 9}, "t", "id"),  # no está entre los permitidos
        ({"a=1; --": 1}, "t", "id"),  # ni aunque se colase en la lista
        ({"a": 1}, "t; DROP TABLE t", "id"),
        ({"a": 1}, "t", "id OR 1=1"),
    ],
)
def test_rechaza_columnas_no_permitidas(conn, valores, tabla, col):
    with pytest.raises(ValueError):
        update_fields(conn, tabla, 1, valores, ("a", "a=1; --"), columna_id=col)
    assert conn.execute("SELECT a FROM t WHERE id=1").fetchone() == ("viejo",)
