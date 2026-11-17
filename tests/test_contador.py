"""P-2: contador en marcha. Máquina de estados (empezar, pausar, cambiar, completar, medianoche, sin señal), tiempos
por día y por elemento, la API y la migración 25 arriba y abajo sobre una copia de la BD real."""

import shutil
import sqlite3
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import contador as C
from app.calendar import TZ
from app.database import get_db
from app.migrations import MIGRATIONS
from core.migrations import apply_pending, revert

HOY = date.today()


def ts(d: date, h: int, m: int = 0, s: int = 0) -> float:
    return datetime.combine(d, dtime(h, m, s), tzinfo=TZ).timestamp()


@pytest.fixture(autouse=True)
def limpio(client):
    with get_db() as conn:
        conn.execute("DELETE FROM sesion_tramos")
        conn.execute("DELETE FROM sesiones")
    yield


def _nuevo(client, text, type="tarea", **extra):
    r = client.post("/api/items", json={"text": text, "type": type, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_empezar_pausar_seguir_y_tiempo(client):
    t = _nuevo(client, "CT leer el tema 3", duration_min=30)
    a = C.empezar(C.EmpezarIn(item_id=t), now=ts(HOY, 10))
    assert a["estado"] == "marcha" and a["titulo"] == "CT leer el tema 3" and a["prevista_min"] == 30
    assert a["tipo"] == "tarea" and a["tramo_inicio"] == ts(HOY, 10)
    p = C.pausar(now=ts(HOY, 10, 20))
    assert p["estado"] == "pausa" and p["transcurrido"] == 20 * 60 and p["tramo_inicio"] is None
    assert C.estado(now=ts(HOY, 11))["activa"]["transcurrido"] == 20 * 60  # en pausa no corre
    s = C.seguir(now=ts(HOY, 11))
    assert s["estado"] == "marcha" and s["segundos"] == 20 * 60  # el cliente suma (ahora - tramo_inicio)
    e = C.estado(now=ts(HOY, 11, 15))["activa"]
    assert e["transcurrido"] == 35 * 60 and e["pasada"]  # 35 min > 30 previstos


def test_un_solo_contador_cambiar_cierra_el_anterior(client):
    a, b = _nuevo(client, "CT uno"), _nuevo(client, "CT dos")
    C.empezar(C.EmpezarIn(item_id=a), now=ts(HOY, 9))
    nueva = C.empezar(C.EmpezarIn(item_id=b), now=ts(HOY, 9, 10))
    assert nueva["item_id"] == b
    with get_db() as conn:
        filas = conn.execute("SELECT item_id, cierre, activa FROM sesiones ORDER BY id").fetchall()
        assert [(r["item_id"], r["cierre"], r["activa"]) for r in filas] == [(a, "cambio", None), (b, None, 1)]
        with pytest.raises(sqlite3.IntegrityError):  # la BD no admite dos activas
            conn.execute("INSERT INTO sesiones (titulo, dia, inicio, activa) VALUES ('x', ?, 0, 1)", (HOY.isoformat(),))
    # empezar la misma que está en pausa = seguir (sin sesión nueva)
    C.pausar(now=ts(HOY, 9, 20))
    otra = C.empezar(C.EmpezarIn(item_id=b), now=ts(HOY, 9, 30))
    assert otra["id"] == nueva["id"] and otra["estado"] == "marcha" and otra["segundos"] == 10 * 60


def test_completar_marca_hecho_y_quitar_conserva_el_tiempo(client):
    t = _nuevo(client, "CT completar")
    C.empezar(C.EmpezarIn(item_id=t), now=ts(HOY, 8))
    out = C.completar(C.CompletarIn(), now=ts(HOY, 8, 25))
    assert out["estado"] == "cerrada" and out["cierre"] == "completada" and out["transcurrido"] == 25 * 60
    assert next(i for i in client.get("/api/items").json()["items"] if i["id"] == t)["done"]
    assert C.estado(now=ts(HOY, 9))["activa"] is None
    libre = C.empezar(C.EmpezarIn(titulo="Ordenar la mesa"), now=ts(HOY, 9))
    assert libre["tipo"] == "libre" and libre["item_id"] is None
    q = C.cerrar("quitada", now=ts(HOY, 9, 5))
    assert q["cierre"] == "quitada" and q["transcurrido"] == 300
    with pytest.raises(HTTPException) as e:
        C.pausar(now=ts(HOY, 9, 6))
    assert e.value.status_code == 409


def test_paso_de_rutina_y_completar_sin_marcar(client):
    r = _nuevo(client, "CT rutina mañana", type="rutina")
    paso = client.post("/api/items", json={"text": "CT estirar", "type": "rutina", "parent_id": r, "duration_min": 10})
    pid = paso.json()["id"]
    a = C.empezar(C.EmpezarIn(item_id=pid), now=ts(HOY, 7))
    assert a["tipo"] == "paso" and a["padre"] == "CT rutina mañana" and a["prevista_min"] == 10
    C.completar(C.CompletarIn(marcar=False), now=ts(HOY, 7, 9))  # el paso a paso marca el paso por su cuenta
    paso_item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == pid)
    assert not paso_item["done"]


def test_cierre_a_medianoche(client):
    ayer = HOY - timedelta(days=1)
    t = _nuevo(client, "CT nocturna")
    C.empezar(C.EmpezarIn(item_id=t), now=ts(ayer, 23, 30))
    C.latido(now=ts(ayer, 23, 50))
    st = C.estado(now=ts(HOY, 0, 10))  # 10 min después de medianoche: ya cerrada, a las 00:00
    assert st["activa"] is None
    assert st["reciente"]["cierre"] == "medianoche" and st["reciente"]["transcurrido"] == 30 * 60
    tiempos = C.tiempos(ayer.isoformat(), HOY.isoformat(), now=ts(HOY, 0, 10))
    assert tiempos["por_dia"] == {ayer.isoformat(): 30 * 60, HOY.isoformat(): 0}
    # una pausada desde ayer tampoco sigue hoy: «seguir» ya no tiene nada que seguir
    C.empezar(C.EmpezarIn(item_id=t), now=ts(ayer, 22))
    C.pausar(now=ts(ayer, 22, 30))
    with pytest.raises(HTTPException):
        C.seguir(now=ts(HOY, 8))


def test_tramo_que_cruza_medianoche_se_reparte(client):
    ayer = HOY - timedelta(days=1)
    partes = list(C.trocear(ts(ayer, 23, 45), ts(HOY, 0, 20)))
    assert partes == [(ayer.isoformat(), 15 * 60), (HOY.isoformat(), 20 * 60)]


def test_sin_senal_pausa_sola_y_recuperar(client):
    t = _nuevo(client, "CT portátil dormido")
    C.empezar(C.EmpezarIn(item_id=t), now=ts(HOY, 9))
    C.latido(now=ts(HOY, 9, 30))
    st = C.latido(now=ts(HOY, 9, 45))["activa"]  # con señal: sigue
    assert st["estado"] == "marcha"
    # el portátil se suspende a las 9:45 y vuelve a las 11:00: se pausa donde se le vio
    st = C.estado(now=ts(HOY, 11))["activa"]
    assert st["estado"] == "pausa" and st["auto_pausa"] == ts(HOY, 9, 45) and st["transcurrido"] == 45 * 60
    r = C.recuperar(now=ts(HOY, 11, 1))  # sí lo estaba haciendo: el hueco cuenta
    assert r["estado"] == "marcha" and r["auto_pausa"] is None
    assert C.estado(now=ts(HOY, 11, 2))["activa"]["transcurrido"] == 122 * 60
    with pytest.raises(HTTPException):
        C.recuperar(now=ts(HOY, 11, 3))


def test_tiempo_por_item_en_la_lista_y_por_dia(client):
    t = _nuevo(client, "CT con tiempo")
    C.empezar(C.EmpezarIn(item_id=t), now=ts(HOY, 6))
    C.cerrar("quitada", now=ts(HOY, 6, 40))
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == t)
    assert item["tiempo_s"] == 40 * 60
    r = client.get("/api/contador/tiempos", params={"desde": HOY.isoformat(), "hasta": HOY.isoformat()}).json()
    assert r["total"] >= 40 * 60
    assert any(e["item_id"] == t and e["segundos"] == 40 * 60 for e in r["elementos"])
    assert client.get("/api/contador/tiempos", params={"desde": "x"}).status_code == 422


def test_bloques_de_estudio_para_rendimiento(client):
    t = _nuevo(client, "CT estudiar tema 2", contexto="universidad")
    C.empezar(C.EmpezarIn(item_id=t), now=ts(HOY, 16))
    C.cerrar("completada", now=ts(HOY, 16, 50))
    corto = _nuevo(client, "CT repaso corto", contexto="universidad")
    C.empezar(C.EmpezarIn(item_id=corto), now=ts(HOY, 17))
    C.cerrar("quitada", now=ts(HOY, 17, 5))
    bloques = C.bloques_de_estudio(HOY.isoformat())
    assert bloques and bloques[0]["minutos"] == 55 and "CT estudiar tema 2" in bloques[0]["de"]
    dia = client.get("/api/rendimiento/dia", params={"fecha": HOY.isoformat()}).json()
    assert dia["bloques_propuestos"] == bloques


def test_api(client):
    t = _nuevo(client, "CT api")
    assert client.get("/api/contador").json()["activa"] is None
    assert client.post("/api/contador/empezar", json={}).status_code == 422
    assert client.post("/api/contador/empezar", json={"item_id": 999999}).status_code == 404
    r = client.post("/api/contador/empezar", json={"item_id": t})
    assert r.status_code == 200 and r.json()["activa"]["estado"] == "marcha"
    assert client.post("/api/contador/pausar").json()["activa"]["estado"] == "pausa"
    assert client.post("/api/contador/seguir").json()["activa"]["estado"] == "marcha"
    assert client.post("/api/contador/latido").json()["activa"]["item_id"] == t
    assert client.post("/api/contador/completar").json()["cerrada"]["cierre"] == "completada"
    assert client.post("/api/contador/quitar").status_code == 409


# ─────────────────────────────────────────────
# Migración 25 sobre una copia de la BD real
# ─────────────────────────────────────────────

REAL = Path(__file__).resolve().parents[1] / "backups" / "pre-8" / "brain.db"


@pytest.mark.skipif(not REAL.exists(), reason="sin copia de la BD real (backups/pre-8/brain.db)")
def test_migracion_25_arriba_y_abajo_sobre_copia_real(tmp_path):
    db = tmp_path / "real.db"
    shutil.copy(REAL, db)
    conn = sqlite3.connect(db, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    antes = {
        r[0]: conn.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%fts%'"
        )
    }
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 25]) == [25]
    item = conn.execute("SELECT id FROM inbox LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO sesiones (item_id, titulo, tipo, dia, inicio, activa) VALUES (?, 'x', 'tarea', '2026-11-15', 1, 1)",
        (item,),
    )
    conn.execute("INSERT INTO sesion_tramos (sesion_id, inicio, fin) VALUES (1, 1, 61)")
    revert(conn, MIGRATIONS, 24)
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sesiones'").fetchone()
    assert apply_pending(conn, [m for m in MIGRATIONS if m.version <= 25]) == [25]  # vuelve con sus datos
    assert conn.execute("SELECT COUNT(*) FROM sesion_tramos WHERE sesion_id=1").fetchone()[0] == 1
    assert conn.execute("SELECT activa FROM sesiones").fetchone()[0] == 1
    conn.execute("DELETE FROM sesiones")  # en cascada, sus tramos (la clave foránea sigue apuntando bien)
    assert conn.execute("SELECT COUNT(*) FROM sesion_tramos").fetchone()[0] == 0
    despues = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in antes if t != "schema_migrations"}
    antes.pop("schema_migrations")
    assert despues == antes  # nada más cambió
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
