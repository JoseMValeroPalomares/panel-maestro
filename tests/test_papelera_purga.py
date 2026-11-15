"""Papelera (app/trash.py, T-1): purga a los 30 días, vaciado, restaurar economía y comidas, y errores.
Lo que ya cubren test_papelera*.py (tipos rows.*, notas, tareas) no se repite aquí."""

import json
import os
import shutil
import time

import pytest

from app import trash
from app.database import get_db
from core import config, undo

DIA = 86400


def _envejecer(token: str, dias: float, db=get_db):
    with db() as conn:
        conn.execute("UPDATE undo_log SET created_at=? WHERE token=?", (time.time() - dias * DIA, token))


def _guardar(kind="finance.debts", payload=None, title="De prueba") -> str:
    with get_db() as conn:
        return undo.save(conn, kind, payload or {"table": "fin_debts", "row": {"id": 999999}}, title=title, count=1)


def _tokens(client) -> set[str]:
    return {e["token"] for e in client.get("/api/trash").json()["entries"]}


def test_purga_lo_caducado_y_las_carpetas_huerfanas_viejas(client):
    viejo, nuevo = _guardar(title="viejo"), _guardar(title="nuevo")
    _envejecer(viejo, 31)
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    carpetas = {n: config.TRASH_DIR / n for n in (nuevo, "huerfana-vieja", "huerfana-reciente")}
    for c in carpetas.values():
        c.mkdir(exist_ok=True)
        (c / "nota.md").write_text("x")
    hace_40 = time.time() - 40 * DIA
    os.utime(carpetas["huerfana-vieja"], (hace_40, hace_40))
    os.utime(carpetas[nuevo], (hace_40, hace_40))  # vieja en disco pero su entrada sigue viva: se queda

    assert trash.purge_expired() >= 1
    vivos = _tokens(client)
    assert viejo not in vivos and nuevo in vivos
    assert not carpetas["huerfana-vieja"].exists()
    assert carpetas["huerfana-reciente"].exists() and carpetas[nuevo].exists()
    trash.remove("brain", nuevo)
    assert not carpetas[nuevo].exists()  # quitar una entrada se lleva su carpeta
    shutil.rmtree(carpetas["huerfana-reciente"])


def test_29_dias_aun_no_caduca(client):
    t = _guardar()
    _envejecer(t, 29)
    trash.purge_expired()
    assert t in _tokens(client)
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == t)
    assert entry["expires_at"] - time.time() == pytest.approx(DIA, abs=60)
    trash.remove("brain", t)


def test_purga_como_mucho_una_vez_al_dia(client, tmp_path, monkeypatch):
    estado = tmp_path / "programador.json"
    estado.write_text(json.dumps({"otra_tarea": 1}))
    monkeypatch.setattr(trash, "_purge_state_file", lambda: estado)
    assert isinstance(trash.purge_if_due(), int)
    assert trash.purge_if_due() is None
    guardado = json.loads(estado.read_text())
    assert guardado["otra_tarea"] == 1 and guardado["trash_purge_at"] == pytest.approx(time.time(), abs=60)
    estado.write_text(json.dumps({"trash_purge_at": time.time() - DIA - 1}))
    assert trash.purge_if_due() is not None
    estado.write_text("{roto")
    assert trash.purge_if_due() is not None  # un estado ilegible no bloquea la purga


def test_vaciar_solo_quita_lo_de_la_papelera(client):
    visible = _guardar()
    with get_db() as conn:
        interno = undo.save(conn, "bulk.edit", {"x": 1})  # «deshacer» interno: no es de la papelera
    config.TRASH_DIR.mkdir(parents=True, exist_ok=True)
    (config.TRASH_DIR / visible).mkdir(exist_ok=True)
    r = client.delete("/api/trash")
    assert r.status_code == 200 and r.json()["removed"] >= 1
    assert client.get("/api/trash").json()["count"] == 0
    assert not (config.TRASH_DIR / visible).exists()
    with get_db() as conn:
        assert any(e["token"] == interno for e in undo.entries(conn))
        undo.drop(conn, interno)


def test_restaurar_una_deuda_borrada(client):
    rid = client.post("/api/finance/debts", json={"persona": "Ana", "importe": 12.5}).json()["id"]
    token = client.delete(f"/api/finance/debts/{rid}").json()["trash"]
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == token)
    assert entry["label"] == "deuda" and entry["plural"] == "deudas" and entry["db"] == "brain"
    r = client.post(f"/api/trash/brain/{token}/restore")
    assert r.status_code == 200 and r.json()["restored"] == 1
    with get_db() as conn:
        assert conn.execute("SELECT persona FROM fin_debts WHERE id=?", (rid,)).fetchone()["persona"] == "Ana"
    assert client.post(f"/api/trash/brain/{token}/restore").status_code == 404  # ya no está


def test_restaurar_un_plato_borrado(client):
    mid = client.post("/comidas/api/meals", json={"nombre": "Plato de la papelera", "es_racion_unica": True}).json()
    mid = mid.get("id") or mid.get("meal", {}).get("id")
    token = client.delete(f"/comidas/api/meals/{mid}").json()["undo_token"]
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == token)
    assert entry["db"] == "comidas" and entry["label"] == "plato"
    assert client.post(f"/api/trash/comidas/{token}/restore").json()["restored"] == 1
    nombres = {m["nombre"] for m in client.get("/comidas/api/meals").json()["meals"]}
    assert "Plato de la papelera" in nombres


def test_errores(client):
    assert client.get("/api/trash").status_code == 200
    assert client.post("/api/trash/otra/abc/restore").status_code == 404  # BD desconocida
    assert client.post("/api/trash/brain/no-existe/restore").status_code == 404
    assert client.delete("/api/trash/brain/no-existe").status_code == 404


def test_etiqueta_de_items_con_carga_rota(client):
    with get_db() as conn:
        t = undo.save(conn, "items", {"rows": "no es una lista"}, title="raro")
    entry = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == t)
    assert entry["label"] == trash.KINDS[("brain", "items")][0]  # sin adivinar: la etiqueta genérica
    trash.remove("brain", t)


@pytest.mark.parametrize(
    ("label", "plural"),
    [
        ("nota", "notas"),
        ("versión de proyecto", "versiones de proyecto"),
        ("filtro guardado", "filtros guardados"),
        ("plantilla de tablero", "plantillas de tablero"),
        ("ingrediente", "ingredientes"),
        ("movimiento", "movimientos"),
        ("deseo", "deseos"),
        ("asignatura", "asignaturas"),
        ("recurrente", "recurrentes"),
        ("tablero", "tableros"),
        ("peso", "pesos"),
        ("tema", "temas"),
        ("plan", "planes"),
    ],
)
def test_plurales(label, plural):
    assert trash.plural(label) == plural
