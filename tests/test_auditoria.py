"""Regresiones de la auditoría de errores (2026-10-30): cada test falló antes de su arreglo."""
import asyncio
import os
from pathlib import Path

import frontmatter

from app.database import get_db
from app.indexer import NOTES_DIR, sync_notes_to_db
from core import auth
from core.files import atomic_write


def nota(client, note_id, content, title=None, category="Prueba", **extra):
    r = client.post(f"/api/notes/{note_id}", json={"title": title or note_id, "category": category, "content": content, **extra})
    assert r.status_code == 200, r.text
    return r


def filas(sql, *args):
    with get_db() as conn:
        return conn.execute(sql, args).fetchall()


# ── Login ───────────────────────────────────────────────────────

def _llega_a_la_app(path: str) -> bool:
    """Directo al middleware: httpx normaliza los «..» antes de mandarlos, un atacante no."""
    llegado = []

    async def app(scope, receive, send):
        llegado.append(scope["path"])

    async def send(message):
        pass

    scope = {"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []}
    asyncio.run(auth.AuthMiddleware(app)(scope, None, send))
    return bool(llegado)


def test_los_puntos_no_saltan_el_login():
    assert _llega_a_la_app("/static/js/ui.js")
    for path in ("/static/js/../uploads/foto.png", "/static/css/../../main.py", "/static/js/foo/../../uploads/x"):
        assert not auth.is_public_path(path)
        assert not _llega_a_la_app(path), path


# ── Notas ───────────────────────────────────────────────────────

def test_escritura_atomica_sin_restos(tmp_path):
    destino = tmp_path / "nota.md"
    destino.write_text("antes", encoding="utf-8")
    os.chmod(destino, 0o640)
    atomic_write(destino, "después\r\n", newline="")
    assert destino.read_bytes() == "después\r\n".encode()
    assert destino.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["nota.md"]


def test_fallo_al_escribir_no_toca_la_nota(tmp_path, monkeypatch):
    destino = tmp_path / "nota.md"
    destino.write_text("original", encoding="utf-8")

    def falla(fd):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "fsync", falla)
    try:
        atomic_write(destino, "nuevo")
    except OSError:
        pass
    assert destino.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["nota.md"]


def test_guardar_conserva_el_progreso_de_las_flashcards(client):
    nota(client, "aud-flash", "pregunta >> respuesta")
    with get_db() as conn:
        conn.execute("UPDATE flashcards SET repetitions=5, ease_factor=2.9, interval_days=30 WHERE note_id='aud-flash'")
    nota(client, "aud-flash", "pregunta >> respuesta\n\nmás texto")
    tarjeta = filas("SELECT repetitions, ease_factor, interval_days FROM flashcards WHERE note_id='aud-flash'")[0]
    assert (tarjeta["repetitions"], tarjeta["ease_factor"], tarjeta["interval_days"]) == (5, 2.9, 30)


def test_actualizar_un_indice_conserva_su_repaso(client):
    nota(client, "aud-idx", "x", category="AreaIndice")
    with get_db() as conn:
        conn.execute("UPDATE notes SET last_reviewed=123 WHERE id='indice-areaindice'")
    nota(client, "aud-idx", "y", category="AreaIndice")
    assert filas("SELECT last_reviewed FROM notes WHERE id='indice-areaindice'")[0][0] == 123


def test_cifrar_una_nota_no_deja_flashcards_en_claro(client):
    nota(client, "aud-cifrada", "secreto >> clave\n\n[[otra-nota]]")
    assert filas("SELECT 1 FROM flashcards WHERE note_id='aud-cifrada'")
    nota(client, "aud-cifrada", "CIFRADO", encrypted=True)
    assert not filas("SELECT 1 FROM flashcards WHERE note_id='aud-cifrada'")
    assert not filas("SELECT 1 FROM graph_edges WHERE source='aud-cifrada' AND type='auto'")


def test_titulo_con_barra_invertida_no_rompe_el_indice(client):
    nota(client, "aud-barra-a", "x", title=r"C:\Users\nota", category="AreaBarra")
    nota(client, "aud-barra-b", "y", title="Otra", category="AreaBarra")
    assert r"C:\Users\nota" in client.get("/api/notes/indice-areabarra").json()["content"]


def test_borrar_en_lote_quita_las_tareas_y_restaurar_las_devuelve(client):
    nota(client, "aud-lote", "- [ ] tarea del lote\n    - [ ] su paso\n")
    item = filas("SELECT id FROM inbox WHERE note_id='aud-lote' AND parent_id IS NULL")[0]["id"]
    client.patch(f"/api/items/{item}", json={"priority": "alta", "due_date": "2030-01-02"})

    token = client.post("/api/bulk/notes/delete", json={"ids": ["aud-lote"]}).json()["undo_token"]
    assert not filas("SELECT 1 FROM inbox WHERE note_id='aud-lote'")

    assert client.post(f"/api/bulk/notes/undo/{token}").json()["restored"] == 1
    fila = filas("SELECT id, priority, due_date FROM inbox WHERE note_id='aud-lote' AND parent_id IS NULL")[0]
    assert (fila["id"], fila["priority"], fila["due_date"]) == (item, "alta", "2030-01-02")
    assert len(filas("SELECT 1 FROM inbox WHERE note_id='aud-lote'")) == 2


def test_restaurar_una_nota_recupera_los_enlaces_de_otras_a_sus_tareas(client):
    nota(client, "aud-origen", "- [ ] tarea enlazada\n")
    item = filas("SELECT id FROM inbox WHERE note_id='aud-origen'")[0]["id"]
    nota(client, "aud-enlaza", f"mira [[tarea:{item}]]\n")
    token = client.delete("/api/notes/aud-origen").json()["undo_token"]
    assert not filas("SELECT 1 FROM item_links WHERE note_id='aud-enlaza'")
    client.post(f"/api/bulk/notes/undo/{token}")
    assert filas("SELECT 1 FROM item_links WHERE note_id='aud-enlaza' AND item_id=?", item)


def test_borrar_una_nota_y_restaurarla_devuelve_sus_tareas(client):
    nota(client, "aud-una", "- [ ] tarea suelta\n")
    token = client.delete("/api/notes/aud-una").json()["undo_token"]
    assert not filas("SELECT 1 FROM inbox WHERE note_id='aud-una'")
    client.post(f"/api/bulk/notes/undo/{token}")
    assert filas("SELECT 1 FROM inbox WHERE note_id='aud-una'")


def test_pasar_a_nota_un_titulo_con_signos(client):
    item = client.post("/api/items", json={"text": "Comprar pan, leche y ¿huevos?", "type": "idea"}).json()["id"]
    r = client.post(f"/api/items/{item}/to-note", json={})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/notes/{r.json()['note_id']}").status_code == 200


def test_renombrar_categoria_actualiza_los_indices(client):
    nota(client, "aud-ren", "x", title="Nota renombrada", category="ViejaAud")
    client.post("/api/notes/rename-category", json={"old_category": "ViejaAud", "new_category": "NuevaAud"})
    assert "Nota renombrada" in client.get("/api/notes/indice-nuevaaud").json()["content"]


def test_mover_de_area_desde_el_gestor_actualiza_los_indices(client):
    nota(client, "aud-meta", "x", title="Nota movida", category="OrigenAud")
    client.patch("/api/notes/aud-meta/meta", json={"category": "DestinoAud"})
    assert "Nota movida" in client.get("/api/notes/indice-destinoaud").json()["content"]
    assert "Nota movida" not in client.get("/api/notes/indice-origenaud").json()["content"]


def test_cambiar_estado_se_ve_en_el_indice_y_no_toca_una_nota_indice(client):
    nota(client, "aud-est", "x", title="Con estado", category="AreaEstado")
    client.patch("/api/notes/aud-est/status", json={"status": "consolidado"})
    assert "✅ [[Con estado]]" in client.get("/api/notes/indice-areaestado").json()["content"]
    r = client.patch("/api/notes/indice-areaestado/status", json={"status": "por-escribir"})
    assert r.json()["new_status"] == "indice"
    assert client.patch("/api/notes/no-existe/status", json={"status": "consolidado"}).status_code == 404


def test_category_id_huerfano_no_impide_arrancar_ni_guardar(client):
    archivo = Path(NOTES_DIR) / "aud-huerfana.md"
    archivo.write_text("---\ntitle: Huérfana\ncategory: X\ncategory_id: 4242\n---\n\nhola\n", encoding="utf-8")
    try:
        sync_notes_to_db()  # con la clave foránea activa, esto tumbaba el arranque
        assert filas("SELECT category_id FROM notes WHERE id='aud-huerfana'")[0][0] is None
        nota(client, "aud-huerfana", "hola", category_id=4242)
        assert frontmatter.load(archivo).get("category_id") is None
    finally:
        archivo.unlink()
        sync_notes_to_db()


def test_borrar_categoria_con_notas(client):
    padre = client.post("/api/categories", json={"name": "PadreAud"}).json()["id"]
    hija = client.post("/api/categories", json={"name": "HijaAud", "parent_id": padre}).json()["id"]
    nota(client, "aud-cat", "x", category_id=hija)
    assert client.delete(f"/api/categories/{padre}").status_code == 200
    assert filas("SELECT category_id FROM notes WHERE id='aud-cat'")[0][0] is None
    assert client.post("/api/categories", json={"name": "Sin padre", "parent_id": 99999}).status_code == 404


# ── Entradas no válidas: 4xx, nunca 500 ─────────────────────────

def test_entradas_no_validas_no_dan_500(client):
    item = client.post("/api/items", json={"text": "x"}).json()["id"]
    assert client.get("/api/calendar/agenda?start=mal").status_code == 422
    assert client.patch(f"/api/items/{item}", json={"done": True, "day": "2026-99-99"}).status_code == 422
    assert client.post(f"/api/routines/{item}/check", json={"day": "mal"}).status_code == 422
    assert client.get("/api/finance/movements?month=mal").status_code == 422
    assert client.get("/api/finance/export.csv?month=2026-13").status_code == 422
    assert client.put("/api/finance/budgets/Comida", json={"importe": "abc"}).status_code == 422
    assert client.post("/api/items/bulk", json={"ids": [item], "action": "priority", "value": "urgente"}).status_code == 422
    assert client.get("/api/backups/backup_20269999_000000.zip").status_code == 422
    assert client.post("/api/boards/99999/canvas", json={"data": "{}"}).status_code == 404
    assert client.get("/api/flashcards/due?limit=99999999999999999999").status_code == 200
    assert client.get("/api/finance/movements?cuenta_id=99999999999999999999").status_code == 422
    assert client.post("/api/inbox", json={"content": "   "}).status_code == 422
    assert client.post("/comidas/api/shopping-list", json={"ingredient_id": 999999}).status_code == 422
    assert client.post("/comidas/api/weekly-plan/assign",
                       json={"semana": "2026-10-26", "dia": "lunes", "franja": "comida", "meal_id": 999999}).status_code == 422


def test_texto_en_blanco_no_crea_ni_vacia_un_elemento(client):
    assert client.post("/api/items", json={"text": "   "}).status_code == 422
    item = client.post("/api/items", json={"text": "con texto"}).json()["id"]
    assert client.patch(f"/api/items/{item}", json={"text": "  \n "}).status_code == 422


def test_importe_infinito_no_se_guarda(client):
    assert client.post("/api/finance/movements", json={"importe": "inf", "tipo": "gasto"}).status_code == 422
    assert client.post("/api/finance/movements", json={"importe": "nan", "tipo": "gasto"}).status_code == 422
    assert client.get("/api/finance/summary").status_code == 200


def test_editar_un_recurrente_no_vacia_lo_obligatorio(client):
    rid = client.post("/api/finance/recurring", json={"concepto": "Luz", "importe": 3, "dia": 28}).json()["id"]
    for body in ({"concepto": "   "}, {"dia": None}, {"activo": None}):
        assert client.patch(f"/api/finance/recurring/{rid}", json=body).status_code == 200
    fila = filas("SELECT concepto, dia, activo FROM fin_recurring WHERE id=?", rid)[0]
    assert (fila["concepto"], fila["dia"], fila["activo"]) == ("Luz", 28, 1)
    client.delete(f"/api/finance/recurring/{rid}")


def test_un_recurrente_no_se_apunta_dos_veces_a_la_vez(client):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date

    from app.finance import apply_recurring

    rid = client.post("/api/finance/recurring", json={"concepto": "Doble", "importe": 1, "dia": 1}).json()["id"]
    with get_db() as conn:
        conn.execute("UPDATE fin_recurring SET desde='2026-01', ultimo=NULL WHERE id=?", (rid,))

    def aplica(_):
        with get_db() as conn:
            return apply_recurring(conn, date(2026, 10, 15))

    with ThreadPoolExecutor(8) as pool:
        total = sum(pool.map(aplica, range(8)))
    assert total == 10
    assert len(filas("SELECT 1 FROM fin_movements WHERE concepto='Doble'")) == 10
    with get_db() as conn:
        conn.execute("DELETE FROM fin_recurring WHERE id=?", (rid,))
        conn.execute("DELETE FROM fin_movements WHERE concepto='Doble'")


def test_estado_muestra_el_error_de_la_copia(client):
    import time

    from app import backup

    backup._write_status(last_error={"at": time.time() + 10 ** 6, "kind": "manual", "error": "disco lleno"})
    try:
        copias = next(i for i in client.get("/api/status").json()["items"] if i["key"] == "backups")
        assert copias["detail"] == "disco lleno"
    finally:
        backup._write_status(last_error=None)


def test_sugerir_gramos_con_unidades(client):
    from comidas.database import get_db as comidas_db
    from comidas.main import MealIngredientIn, _suggest_gramos_recomendados

    r = client.post("/comidas/api/ingredients", json={"nombre": "Huevo auditoría", "categoria": "proteina", "kcal_100g": 150, "gramos_por_unidad": 60})
    ing = r.json()["id"]
    with comidas_db() as conn:
        assert _suggest_gramos_recomendados(conn, [MealIngredientIn(ingredient_id=ing, unidades=2)], "cena") > 0


# ── Estudio, copias y red ───────────────────────────────────────

def test_sondear_playerctl_no_para_el_servidor(monkeypatch):
    import time

    import estudio.main as em

    def lento():
        time.sleep(0.25)

    monkeypatch.setattr(em, "get_metadata", lento)

    async def prueba():
        vueltas = 0

        async def latido():
            nonlocal vueltas
            while True:
                vueltas += 1
                await asyncio.sleep(0.02)

        tarea = asyncio.create_task(latido())
        await em.SpotifyBridge(None)._build_payload(None)
        tarea.cancel()
        return vueltas

    assert asyncio.run(prueba()) > 5  # con la llamada en el bucle, el latido no llega a dar dos vueltas


def test_pedir_sincronia_desde_un_hilo_despierta_al_bucle(monkeypatch):
    from estudio import calendar_sync as cs

    async def prueba():
        monkeypatch.setattr(cs, "WAKE", asyncio.Event())
        monkeypatch.setattr(cs, "LOOP", asyncio.get_running_loop())
        await asyncio.to_thread(cs.request_sync)
        await asyncio.wait_for(cs.WAKE.wait(), timeout=1)

    asyncio.run(prueba())


def test_la_copia_guarda_el_estado_del_calendario_y_restaurar_lo_olvida(client):
    import zipfile

    from app import backup
    from core import config

    assert config.CALENDAR_STATE.parent == config.DATA_DIR  # los tests nunca tocan el del panel real
    config.CALENDAR_STATE.write_text('{"icloud": {"uid-1": {}}, "esp32": {}}', encoding="utf-8")
    nombre = client.post("/api/backups/run").json()["backup"]["filename"]
    with zipfile.ZipFile(backup.backup_path(nombre)) as zf:
        assert "estudio/calendar_sync_v2.json" in zf.namelist()
    r = client.post(f"/api/backups/{nombre}/restore", json={"parts": ["cerebro"], "confirm": "RESTAURAR"})
    assert r.status_code == 200, r.text
    assert not config.CALENDAR_STATE.exists()


def test_comprime_y_cachea_lo_versionado(client):
    from core.templating import asset

    url = asset("/static/js/ui.js")
    assert "?v=" in url
    r = client.get(url, headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert "immutable" in r.headers["cache-control"]
    assert "cache-control" not in client.get("/static/js/ui.js").headers
    assert client.get("/api/items", headers={"Accept-Encoding": "gzip"}).status_code == 200
