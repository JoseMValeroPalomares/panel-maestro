"""S-1: HTTPS. HSTS y cookie Secure solo cuando la petición llega por HTTPS (directa o tras tailscale serve);
los clientes del escritorio aceptan la CA local (mkcert) y no confunden un certificado malo con «sin conexión»."""

import json
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import auth
from tests.conftest import TEST_API_TOKEN, TEST_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "desktop"))
import panel_client as pc  # noqa: E402


@pytest.fixture()
def https_client(app):
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_hsts_y_cookie_secure_por_https(https_client):
    r = https_client.head("/healthz")
    assert r.status_code == 200 and r.headers["strict-transport-security"] == "max-age=15552000"
    r = https_client.post("/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303 and "secure" in r.headers["set-cookie"].lower()


def test_por_http_sin_hsts_ni_secure(anon):
    r = anon.get("/healthz")
    assert r.status_code == 200 and "strict-transport-security" not in r.headers
    r = anon.post("/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
    assert "secure" not in r.headers["set-cookie"].lower()


def test_x_forwarded_host_solo_del_proxy_local():
    h = {"host": "127.0.0.1:8000", "origin": "https://panel.tailnet.ts.net", "x-forwarded-host": "panel.tailnet.ts.net"}
    assert auth._origin_matches_host(h, "127.0.0.1")  # tailscale serve en el mismo equipo
    assert not auth._origin_matches_host(h, "192.168.1.50")  # alguien de la red no puede inventárselo
    assert not auth._origin_matches_host({**h, "x-forwarded-host": "evil.com"}, "127.0.0.1")


# ---------- Clientes del escritorio con una CA local (como mkcert) ----------
def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def panel_https(app, client, tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("sin openssl")
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "ca-key.pem",
        "-out",
        "ca.pem",
        "-days",
        "2",
        "-subj",
        "/CN=CA de pruebas",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        cwd=tmp_path,
    )
    _openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "key.pem",
        "-out",
        "srv.csr",
        "-subj",
        "/CN=localhost",
        cwd=tmp_path,
    )
    (tmp_path / "ext.cnf").write_text(
        "subjectAltName=IP:127.0.0.1\nbasicConstraints=CA:FALSE\n"
        "extendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n"
    )
    _openssl(
        "x509",
        "-req",
        "-in",
        "srv.csr",
        "-CA",
        "ca.pem",
        "-CAkey",
        "ca-key.pem",
        "-CAcreateserial",
        "-out",
        "cert.pem",
        "-days",
        "2",
        "-extfile",
        "ext.cnf",
        cwd=tmp_path,
    )
    tc = TestClient(app)

    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            r = tc.request(
                method,
                self.path,
                content=self.rfile.read(n) if n else None,
                headers={k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")},
            )
            self.send_response(r.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(r.content)

        def do_POST(self):
            self._go("POST")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "cert.pem", tmp_path / "key.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{srv.server_address[1]}", tmp_path / "ca.pem"
    srv.shutdown()


def test_cliente_del_escritorio_por_https_con_la_ca(panel_https, tmp_path, monkeypatch):
    url, ca = panel_https
    token = tmp_path / "token"
    token.write_text(TEST_API_TOKEN)
    token.chmod(0o600)
    monkeypatch.setenv("PANEL_URL", url)
    monkeypatch.setenv("PANEL_TOKEN_FILE", str(token))
    monkeypatch.setattr(pc, "STATE", tmp_path / "estado")
    monkeypatch.setattr(pc, "QUEUE", tmp_path / "estado" / "cola.jsonl")
    monkeypatch.setattr(pc, "CONF", tmp_path / "conf")  # sin ca.pem en la configuración

    # sin la CA: error claro y el texto no se pierde (va a la cola), no «sin conexión»
    monkeypatch.delenv("PANEL_CA_FILE", raising=False)
    res = pc.capture("t: por https sin ca")
    assert res["status"] == "error" and "certificado" in res["message"] and "cola" in res["message"]
    assert [q["text"] for q in pc.queued()] == ["t: por https sin ca"]
    with pytest.raises(pc.CertError):
        pc.flush()  # la cola no se descarta por un certificado malo
    assert len(pc.queued()) == 1

    # con la CA: sale lo de la cola y lo nuevo
    monkeypatch.setenv("PANEL_CA_FILE", str(ca))
    res = pc.capture("t: por https con ca")
    assert res["status"] == "success", res
    assert pc.queued() == []
    assert json.dumps(res, ensure_ascii=False).count("por https con ca") >= 1
