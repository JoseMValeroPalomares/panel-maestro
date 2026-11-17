"""HTTP → HTTPS para lo que llega por la tailnet (core/errors.HttpsRedirectMiddleware, docs/HTTPS.md).

TestClient no pasa por uvicorn: scope["scheme"] sale de la URL («http://…») y las cabeceras se mandan a mano como las pone
`tailscale serve` (ipn/ipnlocal/serve.go): X-Forwarded-Host y X-Forwarded-For siempre; X-Forwarded-Proto solo por TLS."""

import pytest

TS = "equipo.ejemplo.ts.net"


def _por_tailscale(host=TS, **extra):
    """Petición por el puerto 80 de la tailnet: sin X-Forwarded-Proto, como la manda tailscale serve."""
    return {"host": host, "x-forwarded-host": host, "x-forwarded-for": "100.64.0.7", **extra}


@pytest.mark.parametrize("ruta", ["/", "/hoy", "/tareas?item=12&x=1", "/healthz", "/no-existe", "/static/js/ui.js"])
def test_por_http_de_la_tailnet_va_a_https_con_la_misma_ruta(anon, ruta):
    r = anon.get(ruta, headers=_por_tailscale(), follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == f"https://{TS}{ruta}"


def test_conserva_el_metodo_y_va_antes_del_login(anon):
    r = anon.post("/api/inbox", json={"content": "x"}, headers=_por_tailscale(), follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == f"https://{TS}/api/inbox"


def test_host_con_puerto_80_o_sin_x_forwarded_host(anon):
    r = anon.get("/hoy", headers=_por_tailscale(host=f"{TS}:80"), follow_redirects=False)
    assert r.headers["location"] == f"https://{TS}/hoy"
    r = anon.get("/hoy", headers={"x-forwarded-proto": "http", "host": TS}, follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == f"https://{TS}/hoy"


def test_el_nombre_corto_va_al_completo(anon, monkeypatch):
    from core import red

    monkeypatch.setattr(red, "_tailscale", lambda: {"activo": True, "nombre": TS})
    r = anon.get("/hoy?x=1", headers=_por_tailscale(host="equipo"), follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == f"https://{TS}/hoy?x=1"
    # Un nombre corto que no es el de este equipo no se toca
    r = anon.get("/healthz", headers=_por_tailscale(host="otro"), follow_redirects=False)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},  # http://127.0.0.1:8000 directo: scripts del escritorio, Waybar
        {"x-forwarded-proto": "https", "x-forwarded-host": TS, "host": TS},  # ya llegó por https (el 443)
        {"host": "localhost:8000"},
        {"x-forwarded-proto": "http", "x-forwarded-host": "192.168.1.50:8000"},  # otro proxy, en la LAN
        {"x-forwarded-proto": "http", "x-forwarded-host": "panel.local"},
    ],
)
def test_lo_demas_no_se_redirige(client, headers):
    r = client.get("/healthz", headers=headers, follow_redirects=False)
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_el_308_lleva_las_cabeceras_de_seguridad(anon):
    r = anon.get("/", headers=_por_tailscale(), follow_redirects=False)
    assert r.status_code == 308 and r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in r.headers  # por http el navegador la ignoraría
