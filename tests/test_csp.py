"""CSP sin JS en línea: el panel no tiene manejadores on…= ni <script> en línea; las simulaciones van en /sim."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUENTES = ["templates/*.html", "static/*.html", "static/js/*.js", "comidas/static/js/*.js", "estudio/static/*.js"]
EN_LINEA = re.compile(r"""\son(click|change|input|submit|keydown|keyup|load|error|focus|blur|mouse\w+|pointer\w+)\s*=\s*["']""", re.I)


def _directivas(csp: str) -> dict[str, str]:
    return {p.split()[0]: p for p in (x.strip() for x in csp.split(";")) if p}


def test_csp_del_panel_sin_unsafe_inline_en_scripts(anon):
    csp = anon.get("/login").headers["content-security-policy"]
    script = _directivas(csp)["script-src"]
    assert script == "script-src 'self'"
    assert "'unsafe-eval'" not in csp


def test_sin_manejadores_ni_scripts_en_linea():
    for pat in FUENTES:
        for f in ROOT.glob(pat):
            texto = f.read_text(encoding="utf-8")
            hit = EN_LINEA.search(texto)
            assert not hit, f"{f.relative_to(ROOT)}: manejador en línea «{hit.group(0).strip()}» (usa data-call)"
            if f.suffix == ".html":
                assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", texto), f"{f.relative_to(ROOT)}: <script> en línea"


def test_data_call_apunta_a_nombres_validos():
    """data-call="nombre;Objeto.metodo" con data-args en JSON: lo interpreta ui.js:runCall."""
    import json
    for f in (ROOT / "templates").glob("*.html"):
        texto = f.read_text(encoding="utf-8")
        for m in re.finditer(r"""data-call="([^"]+)"(?: data-args='([^']*)')?""", texto):
            nombres = m.group(1).split(";")
            assert all(re.fullmatch(r"[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*", n) for n in nombres), m.group(0)
            if m.group(2):
                args = json.loads(m.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
                assert isinstance(args, list) and (len(nombres) == 1 or len(args) == len(nombres)), m.group(0)


def test_sim_es_publico_aislado_y_con_su_csp(anon):
    r = anon.get("/sim")
    assert r.status_code == 200 and "sim-ready" in r.text
    d = _directivas(r.headers["content-security-policy"])
    assert d["sandbox"] == "sandbox allow-scripts"          # sin allow-same-origin: origen opaco
    assert d["connect-src"] == "connect-src 'none'"         # el código de una nota no puede llamar a la API
    assert d["frame-ancestors"] == "frame-ancestors 'self'"
    assert "'self'" not in d["script-src"]
