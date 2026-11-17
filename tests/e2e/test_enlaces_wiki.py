"""Enlaces [[Título]]: si el slug del título no es el id de la nota (título cambiado, id con tildes), se abre esa nota."""

import pytest
from playwright.sync_api import expect

NOTAS = (
    ("enlace-id-viejo", "Título renovado del todo", "Enlaces", "Destino"),
    ("indice-física-pruebas", "Índice de pruebas", "Enlaces", "Índice"),
    (
        "enlace-origen",
        "Origen",
        "Enlaces",
        "[[Título renovado del todo]] · [[enlace-id-viejo]] · [[indice-física-pruebas]] · [[No existe todavía]]",
    ),
)


@pytest.fixture()
def notas(api):
    for slug, titulo, cat, texto in NOTAS:
        api.post(
            f"/api/notes/{slug}",
            json={"title": titulo, "category": cat, "content": texto, "tags": [], "status": "consolidado"},
        )
    yield
    for slug, *_ in NOTAS:
        api.delete(f"/api/notes/{slug}")


def test_enlace_por_titulo_abre_la_nota_aunque_el_id_sea_otro(page, server, api, notas):
    page.goto(server + "/?note=enlace-origen")
    links = page.locator("#readContent .wiki-link")
    expect(links).to_have_count(4)
    renovado, por_id, con_tilde, falta = (links.nth(i) for i in range(4))
    expect(renovado).to_have_attribute("data-note-id", "enlace-id-viejo")
    expect(renovado).not_to_have_class("wiki-link missing")
    expect(por_id).to_have_attribute("data-note-id", "enlace-id-viejo")
    expect(con_tilde).to_have_attribute("data-note-id", "indice-física-pruebas")
    expect(falta).to_have_class("wiki-link missing")
    renovado.click()
    expect(page.locator("#noteTitle")).to_have_value("Título renovado del todo")
    assert "note=enlace-id-viejo" in page.url
