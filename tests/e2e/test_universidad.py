"""Universidad en el navegador: la carpeta propone los temas, se confirman (renombrar, fusionar), la ficha del tema
lista sus PDFs y el lector abre uno, salta de página y la recuerda al volver a abrirlo."""

import tempfile
from pathlib import Path


def _pdf(path: Path, titulo: str, n: int) -> None:
    """PDF mínimo válido de n páginas (Helvetica estándar)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for i in range(1, n + 1):
        txt = f"BT /F1 24 Tf 60 700 Td ({titulo} {i}) Tj ET"
        objs.append(f"<< /Length {len(txt)} >>\nstream\n{txt}\nendstream")
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {len(objs)} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)


def test_asignatura_temas_con_documentos_lector_y_explorador(page, server, api):
    raiz = Path(tempfile.mkdtemp(prefix="uni-e2e-"))
    so = raiz / "Segundo" / "SO"
    _pdf(so / "T2 - Procesos" / "procesos.pdf", "Procesos", 30)
    _pdf(so / "T3_hilos" / "hilos.pdf", "Hilos", 5)
    _pdf(so / "tema1.pdf", "Intro", 3)
    _pdf(raiz / "Comun" / "normativa.pdf", "Normativa", 2)
    assert api.put("/api/contextos/ajustes", json={"uni_raiz": str(raiz)}).status_code == 200
    try:
        aid = api.post("/api/uni/asignaturas", json={"nombre": "Sistemas Operativos", "codigo": "SOE2E"}).json()["id"]
        # portada: una tarjeta por asignatura; clic = entrar (con la asignatura en la URL)
        page.goto(f"{server}/universidad")
        page.locator(f"[data-goto-asig='{aid}']").click()
        page.wait_for_function(f"location.search.includes('asignatura={aid}')")
        assert page.locator("#uniHeading").inner_text() == "Sistemas Operativos"
        # vincular la carpeta desde el diálogo (la ruta completa vale y se comprueba al escribir)
        page.get_by_role("button", name="Elegir carpeta").first.click()
        page.locator("input[name=carpeta]").fill(str(so))
        page.wait_for_function("document.querySelector('#uniCarpetaEstado').dataset.estado === 'vinculada'")
        page.locator(".uni-dialog button[type=submit]").click()
        # propuesta: «T2 - Procesos» → «Tema 2 · Procesos»; los hilos se fusionan con él
        page.wait_for_selector(".uni-prop-row[data-ruta='T3_hilos']")
        assert (
            page.locator(".uni-prop-row[data-ruta='T2 - Procesos'] [data-f=titulo]").input_value()
            == "Tema 2 · Procesos"
        )
        page.locator(".uni-prop-row[data-ruta='T3_hilos'] [data-f=accion]").select_option("fusionar")
        page.locator(".uni-prop-row[data-ruta='T3_hilos'] [data-f=destino]").select_option("T2 - Procesos")
        page.locator(".uni-dialog button[type=submit]").click()
        page.wait_for_selector(".uni-ts")
        assert page.locator(".uni-ts-name").all_inner_texts() == ["Tema 1", "Tema 2 · Procesos"]
        # cada tema enseña sus documentos como cuadrados (también los del tema fusionado)
        tema2 = page.locator(".uni-ts", has_text="Tema 2 · Procesos")
        assert tema2.locator(".uni-tile-name").all_inner_texts() == ["procesos", "hilos"]
        # plegar se guarda
        tema2.locator(".uni-ts-toggle").click()
        page.wait_for_timeout(400)
        page.reload()
        page.wait_for_selector(".uni-ts")
        tema2 = page.locator(".uni-ts", has_text="Tema 2 · Procesos")
        assert tema2.locator(".uni-ts-toggle").get_attribute("aria-expanded") == "false"
        tema2.locator(".uni-ts-toggle").click()
        # lector: abre, salta de página y la recuerda
        tema2.locator("button[data-ver]").first.click()
        page.wait_for_function("document.querySelector('.pdf-visor [data-total]')?.textContent === 'de 30'")
        page.wait_for_selector(".pdf-page-box.is-painted")
        page.locator(".pdf-visor [data-page]").fill("12")
        page.locator(".pdf-visor [data-page]").press("Enter")
        page.keyboard.press("ArrowRight")
        page.wait_for_function("document.querySelector('.pdf-visor [data-page]').value === '13'")
        page.locator(".pdf-visor [data-close]").click()
        page.wait_for_function(
            "[...document.querySelectorAll('.uni-tile-foot')].some((x) => x.textContent.includes('p. 13/30'))"
        )
        page.locator(".uni-ts", has_text="Tema 2 · Procesos").locator("button[data-ver]").first.click()
        page.wait_for_function("document.querySelector('.pdf-visor [data-page]')?.value === '13'")
        page.keyboard.press("Escape")
        # un PDF suelto de otra carpeta de la raíz, con el explorador
        page.locator(".uni-ts", has_text="Tema 1").locator("[data-vincular]").click()
        page.locator(".uni-explorar [data-ir='']").first.click()
        page.locator(".uni-explorar [data-ir='Comun']").click()
        page.locator(".uni-explorar label", has_text="normativa.pdf").click()
        page.locator(".uni-explorar [data-ok]").click()
        page.wait_for_function(
            "[...document.querySelectorAll('.uni-ts')].find((s) => s.textContent.includes('Tema 1'))?.textContent.includes('normativa')"
        )
        # Atrás vuelve a la portada
        page.go_back()
        page.wait_for_selector(".uni-card")
        assert page.locator("#uniHeading").inner_text() == "Universidad"
    finally:
        api.put("/api/contextos/ajustes", json={"uni_raiz": ""})
