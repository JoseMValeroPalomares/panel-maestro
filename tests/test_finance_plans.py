"""Economía: presupuestos por categoría, recurrentes que se apuntan solos y exportar a CSV."""
from datetime import date

from app import finance
from app.database import get_db


def test_presupuesto_por_categoria(client):
    mes = date.today().strftime("%Y-%m")
    assert client.put("/api/finance/budgets/Ocio", json={"importe": "60,5"}).status_code == 200
    client.post("/api/finance/movements", json={"importe": 20, "categoria": "Ocio", "concepto": "Cine"})
    s = client.get(f"/api/finance/summary?month={mes}").json()
    ocio = next(c for c in s["mes"]["por_categoria"] if c["categoria"] == "Ocio")
    assert ocio["presupuesto"] == 60.5 and ocio["total"] >= 20
    # una categoría con presupuesto sale aunque no tenga gasto
    client.put("/api/finance/budgets/Ropa", json={"importe": 30})
    s = client.get(f"/api/finance/summary?month={mes}").json()
    assert any(c["categoria"] == "Ropa" and c["presupuesto"] == 30 for c in s["mes"]["por_categoria"])
    client.put("/api/finance/budgets/Ropa", json={"importe": ""})  # vacío lo quita
    assert "Ropa" not in client.get(f"/api/finance/summary?month={mes}").json()["presupuestos"]


def test_recurrente_se_apunta_cada_mes_una_vez(client):
    r = client.post("/api/finance/recurring", json={"concepto": "Gimnasio R", "importe": 29.9, "categoria": "Deporte", "dia": 5}).json()
    with get_db() as conn:  # como si se hubiera creado en julio: se ponen al día agosto, septiembre…
        conn.execute("UPDATE fin_recurring SET desde='2026-07', ultimo=NULL WHERE id=?", (r["id"],))
        n = finance.apply_recurring(conn, date(2026, 10, 10))
        assert n == 4  # julio, agosto, septiembre y octubre (el 5 ya pasó)
        assert finance.apply_recurring(conn, date(2026, 10, 20)) == 0  # no se repite
        assert finance.apply_recurring(conn, date(2026, 11, 4)) == 0   # noviembre aún no toca
        assert finance.apply_recurring(conn, date(2026, 11, 5)) == 1
        fechas = [x["fecha"] for x in conn.execute("SELECT fecha FROM fin_movements WHERE concepto='Gimnasio R' ORDER BY fecha")]
    assert fechas == ["2026-07-05", "2026-08-05", "2026-09-05", "2026-10-05", "2026-11-05"]
    # en pausa no se apunta; al reactivarlo no rellena los meses en pausa
    client.patch(f"/api/finance/recurring/{r['id']}", json={"activo": False})
    with get_db() as conn:
        assert finance.apply_recurring(conn, date(2027, 2, 10)) == 0
    client.patch(f"/api/finance/recurring/{r['id']}", json={"activo": True})
    with get_db() as conn:
        ultimo = conn.execute("SELECT ultimo FROM fin_recurring WHERE id=?", (r["id"],)).fetchone()[0]
    assert ultimo >= date.today().strftime("%Y-%m")[:7] or ultimo == finance._shift(date.today().strftime("%Y-%m"), -1)
    # borrar va a la papelera
    assert client.delete(f"/api/finance/recurring/{r['id']}").json()["trash"]
    assert client.post("/api/finance/recurring", json={"concepto": "X", "importe": 1, "tipo": "transferencia"}).status_code == 422


def test_exportar_csv(client):
    client.post("/api/finance/movements", json={"importe": "12,30", "categoria": "Comida", "concepto": "Menú CSV", "fecha": "2026-09-14"})
    r = client.get("/api/finance/export.csv?month=2026-09")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    body = r.text
    assert body.splitlines()[0].lstrip("﻿").startswith("fecha,tipo,importe")
    assert "Menú CSV" in body and '"12,30"' in body
