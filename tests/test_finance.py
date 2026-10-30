"""Economía (/api/finance): cuentas con saldo, movimientos, resumen del mes, deudas, deseos y papelera."""
from datetime import date

import pytest

from app.finance import money

MES = "2030-03"


def test_importes_en_formato_espanol():
    assert money("12,50") == 12.5 and money("1.234,5") == 1234.5 and money("12.5") == 12.5 and money(3) == 3.0
    with pytest.raises(ValueError):
        money("doce")


def test_cuentas_movimientos_y_resumen(client):
    banco = client.post("/api/finance/accounts", json={"nombre": "Banco R", "tipo": "banco", "saldo_inicial": "1.000,00"}).json()["id"]
    caja = client.post("/api/finance/accounts", json={"nombre": "Efectivo R", "tipo": "efectivo", "saldo_inicial": 50}).json()["id"]
    def mov(**kw):
        r = client.post("/api/finance/movements", json={"fecha": f"{MES}-10", **kw})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    mov(importe="12,40", tipo="gasto", categoria="Comida", concepto="Menú", cuenta_id=caja)
    mov(importe=30, tipo="gasto", categoria="Transporte", concepto="Abono", cuenta_id=banco)
    mov(importe=200, tipo="ingreso", categoria="Paga", cuenta_id=banco)
    mov(importe=20, tipo="transferencia", cuenta_id=banco, cuenta_destino=caja)
    # una transferencia necesita dos cuentas distintas; el importe tiene que ser positivo
    assert client.post("/api/finance/movements", json={"importe": 5, "tipo": "transferencia", "cuenta_id": banco}).status_code == 422
    assert client.post("/api/finance/movements", json={"importe": "-3"}).status_code == 422
    s = client.get("/api/finance/summary", params={"month": MES}).json()
    saldo = {c["nombre"]: c["saldo"] for c in s["cuentas"]}
    assert saldo["Banco R"] == 1000 - 30 + 200 - 20 and saldo["Efectivo R"] == 50 - 12.4 + 20
    assert s["mes"]["gastos"] == 42.4 and s["mes"]["ingresos"] == 200 and s["mes"]["balance"] == 157.6
    assert s["mes"]["por_categoria"][0] == {"categoria": "Transporte", "total": 30, "presupuesto": None}
    assert len(s["meses"]) == 6 and s["meses"][-1]["mes"] == MES
    lista = client.get("/api/finance/movements", params={"month": MES, "q": "Menú"}).json()["movements"]
    assert [m["concepto"] for m in lista] == ["Menú"]
    # editar: cambia el importe; un vacío no deja la fecha a NULL
    client.patch(f"/api/finance/movements/{lista[0]['id']}", json={"importe": "15", "fecha": ""})
    m = client.get("/api/finance/movements", params={"month": MES, "q": "Menú"}).json()["movements"][0]
    assert m["importe"] == 15 and m["fecha"] == f"{MES}-10"
    # una cuenta con movimientos no se borra (se archiva)
    assert client.delete(f"/api/finance/accounts/{banco}").status_code == 422


def test_deudas_deseos_y_papelera(client):
    cuenta = client.post("/api/finance/accounts", json={"nombre": "Banco D", "saldo_inicial": 0}).json()["id"]
    ana = client.post("/api/finance/debts", json={"persona": "Ana", "importe": "25", "direccion": "me-deben", "concepto": "Cena"}).json()["id"]
    client.post("/api/finance/debts", json={"persona": "Luis", "importe": 10, "direccion": "debo"})
    s = client.get("/api/finance/summary").json()
    assert s["me_deben"] >= 25 and s["debo"] >= 10
    # cobrarla apunta un ingreso en la cuenta y la quita de las pendientes
    assert client.post(f"/api/finance/debts/{ana}/settle", json={"cuenta_id": cuenta}).status_code == 200
    s = client.get("/api/finance/summary").json()
    assert not any(d["id"] == ana for d in s["deudas"])
    assert next(c for c in s["cuentas"] if c["id"] == cuenta)["saldo"] == 25
    assert client.post(f"/api/finance/debts/{ana}/settle", json={}).status_code == 422
    # deseo comprado = gasto «Compras»
    w = client.post("/api/finance/wishes", json={"nombre": "Auriculares", "precio": "59,90", "prioridad": "alta"}).json()["id"]
    assert any(x["id"] == w for x in client.get("/api/finance/summary").json()["deseos"])
    client.post(f"/api/finance/wishes/{w}/buy", json={"cuenta_id": cuenta})
    s = client.get("/api/finance/summary").json()
    assert not any(x["id"] == w for x in s["deseos"]) and next(c for c in s["cuentas"] if c["id"] == cuenta)["saldo"] == round(25 - 59.9, 2)
    # borrar un movimiento va a la papelera y se restaura
    mid = client.post("/api/finance/movements", json={"importe": 3, "concepto": "Café papelera"}).json()["id"]
    tok = client.delete(f"/api/finance/movements/{mid}").json()["trash"]
    entrada = next(e for e in client.get("/api/trash").json()["entries"] if e["token"] == tok)
    assert entrada["label"] == "movimiento" and entrada["title"] == "Café papelera"
    assert client.post(f"/api/trash/brain/{tok}/restore").json()["restored"] == 1
    hoy = date.today().strftime("%Y-%m")
    assert any(m["id"] == mid for m in client.get("/api/finance/movements", params={"month": hoy}).json()["movements"])
