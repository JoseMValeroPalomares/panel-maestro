"""Fase 6: gestión masiva de notas (lote, borrado con deshacer, duplicar, CSV/JSON)."""
import frontmatter

from core import config

BASE = "/api/bulk/notes"


def _crear(client, note_id, **kw):
    body = {"title": note_id.upper(), "category": "Lote - A", "tags": ["uno"], "content": f"Texto {note_id}\n¿P? >> R", **kw}
    assert client.post(f"/api/notes/{note_id}", json=body).status_code == 200


def _fm(note_id):
    return frontmatter.load(config.NOTES_DIR / f"{note_id}.md")


def test_editar_en_lote(client):
    _crear(client, "lote-1")
    _crear(client, "lote-2", tags=["uno", "dos"])
    r = client.post(f"{BASE}/update", json={"ids": ["lote-1", "lote-2", "no-existe"], "category": "Lote - B",
                                            "status": "consolidado", "tags_add": ["nuevo"], "tags_remove": ["uno"]})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2 and r.json()["skipped"] == ["no-existe"]
    post = _fm("lote-2")
    assert post["category"] == "Lote - B" and post["status"] == "consolidado"
    assert post["tags"] == ["dos", "nuevo"]
    assert client.get("/api/notes/lote-1").json()["category"] == "Lote - B"
    assert client.post(f"{BASE}/update", json={"ids": ["lote-1"], "status": "inventado"}).status_code == 422


def test_ids_no_validos(client):
    assert client.post(f"{BASE}/update", json={"ids": ["../etc"], "status": "consolidado"}).status_code == 400
    assert client.post(f"{BASE}/delete", json={"ids": []}).status_code == 422


def test_borrar_y_deshacer(client):
    _crear(client, "lote-borrar")
    cards = client.get("/api/flashcards/stats").json()["total"]
    r = client.post(f"{BASE}/delete", json={"ids": ["lote-borrar"]})
    assert r.json()["deleted"] == 1
    token = r.json()["undo_token"]
    assert not (config.NOTES_DIR / "lote-borrar.md").exists()
    assert (config.TRASH_DIR / token / "lote-borrar.md").exists()
    assert client.get("/api/notes/lote-borrar").status_code == 404
    assert client.get("/api/flashcards/stats").json()["total"] == cards - 1

    assert client.post(f"{BASE}/undo/{token}").json()["restored"] == 1
    assert (config.NOTES_DIR / "lote-borrar.md").exists()
    assert client.get("/api/notes/lote-borrar").status_code == 200
    assert client.get("/api/flashcards/stats").json()["total"] == cards
    assert client.post(f"{BASE}/undo/{token}").status_code == 404  # solo una vez


def test_duplicar(client):
    _crear(client, "lote-dup")
    r = client.post(f"{BASE}/duplicate", json={"ids": ["lote-dup", "lote-dup"]})
    assert r.json()["created"] == ["lote-dup-copia", "lote-dup-copia-2"]
    assert _fm("lote-dup-copia")["title"] == "LOTE-DUP (copia)"
    assert _fm("lote-dup-copia").content == _fm("lote-dup").content


def test_exportar(client):
    _crear(client, "lote-exp", tags=["a", "b"])
    j = client.get(f"{BASE}/export", params={"format": "json", "ids": "lote-exp"}).json()
    assert j["notes"][0]["tags"] == ["a", "b"] and len(j["notes"]) == 1
    r = client.get(f"{BASE}/export", params={"format": "csv", "ids": "lote-exp"})
    assert r.headers["content-type"].startswith("text/csv")
    assert "lote-exp" in r.text and "a, b" in r.text


def test_importar_csv_con_vista_previa(client):
    _crear(client, "imp-existe")
    csv_txt = ("id,title,category,status,tags,content\n"
               "imp-nueva,Importada,Imp - X,consolidado,\"t1, t2\",Hola\n"
               "imp-existe,Ya está,Imp,,,\n"
               ",,,,,sin título\n"
               ",Título Con Acentos Á,Imp,,,\n")
    files = {"file": ("notas.csv", csv_txt.encode(), "text/csv")}
    prev = client.post(f"{BASE}/import", files=files, data={"dry_run": "true"}).json()
    assert prev["status"] == "preview"
    assert prev["crear"] == ["imp-nueva", "titulo-con-acentos-a"] and prev["omitir"] == ["imp-existe"]
    assert len(prev["errores"]) == 1
    assert not (config.NOTES_DIR / "imp-nueva.md").exists()

    res = client.post(f"{BASE}/import", files=files).json()
    assert res["status"] == "success"
    post = _fm("imp-nueva")
    assert post["tags"] == ["t1", "t2"] and post["status"] == "consolidado" and post.content == "Hola"
    assert _fm("imp-existe")["title"] == "IMP-EXISTE"  # no se sobrescribe en modo skip


def test_importar_json_sobrescribir(client):
    _crear(client, "imp-json")
    body = b'{"notes": [{"id": "imp-json", "title": "Nueva", "content": "x", "tags": ["z"]}]}'
    res = client.post(f"{BASE}/import", files={"file": ("n.json", body, "application/json")}, data={"mode": "overwrite"}).json()
    assert res["sobrescribir"] == ["imp-json"]
    assert _fm("imp-json")["title"] == "Nueva"
    bad = client.post(f"{BASE}/import", files={"file": ("n.json", b"{roto", "application/json")})
    assert bad.status_code == 422


def test_papelera_caducada_se_purga(client):
    import os
    import time
    viejo = config.TRASH_DIR / "token-viejo"
    viejo.mkdir(parents=True, exist_ok=True)
    (viejo / "x.md").write_text("x")
    antes = time.time() - 31 * 86400  # la papelera guarda 30 días
    os.utime(viejo, (antes, antes))
    _crear(client, "lote-purga")
    client.post(f"{BASE}/delete", json={"ids": ["lote-purga"]})
    assert not viejo.exists()
