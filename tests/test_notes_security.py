import io

import pytest
from PIL import Image


@pytest.mark.parametrize("bad_id", ["..%2F..%2Fetc%2Fpasswd", "%2E%2E", ".oculta", "a%00b", "con espacio", "a.b"])
def test_note_id_invalido_rechazado(client, bad_id):
    r = client.get(f"/api/notes/{bad_id}")
    assert r.status_code in (400, 404)
    r = client.post(f"/api/notes/{bad_id}", json={"title": "x", "category": "x", "content": "x"})
    assert r.status_code in (400, 404, 405)


def test_note_id_con_tildes_sigue_valido(client):
    r = client.post("/api/notes/indice-electrónica-prueba",
                    json={"title": "Índice", "category": "Electrónica", "content": "x", "status": "indice"})
    assert r.status_code == 200
    assert client.get("/api/notes/indice-electrónica-prueba").status_code == 200


def test_guardar_y_leer_nota(client, tmp_root):
    r = client.post("/api/notes/nota-test", json={"title": "Nota test", "category": "Pruebas", "content": "Hola [[Nota inicial]]",
                                                  "tags": ["a"]})
    assert r.status_code == 200
    note = client.get("/api/notes/nota-test").json()
    assert note["title"] == "Nota test"
    assert (tmp_root / "data" / "notes" / "nota-test.md").exists()


def test_ruta_recall_ya_no_choca_con_get_note(client):
    r = client.get("/api/notes/recall")
    assert r.status_code == 200
    assert "note_id" in r.json()


def test_rename_category_funciona(client):
    client.post("/api/notes/para-renombrar", json={"title": "R", "category": "Vieja", "content": "x"})
    r = client.post("/api/notes/rename-category", json={"old_category": "Vieja", "new_category": "Nueva"})
    assert r.status_code == 200 and r.json()["updated"] >= 1  # incluye el índice automático
    assert client.get("/api/notes/para-renombrar").json()["category"] == "Nueva"


def test_limites_pydantic(client):
    r = client.post("/api/notes/largo", json={"title": "x" * 400, "category": "c", "content": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "Datos no válidos" and body["detail"][0]["campo"] == "title"
    assert client.post("/api/inbox", json={"content": ""}).status_code == 422
    assert client.post("/api/resources", json={"url": "javascript:alert(1)"}).status_code == 422
    assert client.post("/api/flashcards/1/review", json={"quality": 9}).status_code == 422
    assert client.patch("/comidas/api/profile", json={"edad": 5, "peso_kg": 70, "altura_cm": 170, "sexo": "hombre",
                                                       "nivel_actividad": 1.5, "objetivo": "mantener",
                                                       "proteina_g_kg": 1.6}).status_code == 422
    assert client.get("/comidas/api/weekly-plan/no-es-fecha").status_code == 422


def _png_bytes(size=(4, 4)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


def test_subida_imagen_valida(client, tmp_root):
    r = client.post("/api/upload-image", files={"image": ("a.png", _png_bytes(), "image/png")})
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.endswith(".png")
    assert client.get(url).status_code == 200


def test_subida_rechaza_no_imagen(client):
    payload = b"<script>alert(1)</script>"
    r = client.post("/api/upload-image", files={"image": ("a.png", payload, "image/png")})
    assert r.status_code == 400


def test_subida_detecta_formato_real(client):
    # un JPEG enviado como "image/png" se guarda como .jpg
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="JPEG")
    r = client.post("/api/upload-image", files={"image": ("x.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200 and r.json()["url"].endswith(".jpg")


def test_subida_rechaza_bmp(client):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="BMP")
    assert client.post("/api/upload-image", files={"image": ("x.bmp", buf.getvalue(), "image/bmp")}).status_code == 400


def test_error_no_controlado_devuelve_json(app, client):
    from app.main import app as cerebro

    @cerebro.get("/api/_boom_test")
    def boom():
        raise RuntimeError("fallo")

    with __import__("fastapi.testclient").testclient.TestClient(app, raise_server_exceptions=False) as c:
        c.cookies = client.cookies
        r = c.get("/api/_boom_test")
    assert r.status_code == 500
    assert r.json() == {"error": "Error interno del servidor"}
