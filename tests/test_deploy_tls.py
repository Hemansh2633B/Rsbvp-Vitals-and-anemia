"""HTTPS deployment: needed because browsers only expose a camera on a secure context.

`http://localhost` is a secure context, so the machine running the server can
always use its camera. A phone opening `http://<lan-ip>:8000` is not, and the
browser blocks getUserMedia there - so the deploy scripts offer `--tls`.
"""
from __future__ import annotations

import ssl
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import deploy_server  # noqa: E402


def test_certificate_is_created_once_and_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_server, "local_ip_addresses", lambda: ["192.168.1.50"])
    monkeypatch.setattr(deploy_server, "lan_address", lambda: "192.168.1.50")
    if not _openssl() and not _cryptography():
        pytest.skip("neither openssl nor cryptography is available")

    cert, key = deploy_server.ensure_certificate(tmp_path)
    assert cert.is_file() and key.is_file()
    first = cert.read_bytes()

    cert_again, key_again = deploy_server.ensure_certificate(tmp_path)
    assert (cert_again, key_again) == (cert, key)
    assert cert_again.read_bytes() == first, "an existing certificate must be reused"


def test_certificate_covers_localhost_and_lan_addresses(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_server, "local_ip_addresses", lambda: ["192.168.1.50"])
    monkeypatch.setattr(deploy_server, "lan_address", lambda: "192.168.1.50")
    if not _openssl():
        pytest.skip("openssl not available")
    cert, _key = deploy_server.ensure_certificate(tmp_path)
    details = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-ext",
                              "subjectAltName"], capture_output=True, text=True)
    assert details.returncode == 0, details.stderr
    text = details.stdout
    assert "localhost" in text
    assert "127.0.0.1" in text
    assert "192.168.1.50" in text, "a phone reaching the machine by IP needs that SAN"


def test_private_key_is_not_world_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy_server, "local_ip_addresses", lambda: [])
    if not _openssl():
        pytest.skip("openssl not available")
    _cert, key = deploy_server.ensure_certificate(tmp_path)
    mode = key.stat().st_mode & 0o777
    assert mode & 0o077 == 0, f"private key is too permissive: {oct(mode)}"


def test_health_probe_accepts_the_self_signed_certificate():
    context = deploy_server._ssl_context(insecure=True)
    assert context is not None
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
    assert deploy_server._ssl_context(insecure=False) is None


@pytest.mark.parametrize("name, flag", [
    ("deploy.sh", "--tls"),
    ("deploy.cmd", "--tls"),
    ("deploy.ps1", "-Tls"),
])
def test_every_script_offers_https(name, flag):
    text = (ROOT / name).read_text(encoding="utf-8")
    assert flag in text, f"{name} must offer the HTTPS switch"
    assert "--tls" in text, f"{name} must pass --tls to deploy_server.py"


def test_server_builds_https_urls_when_tls_is_on():
    source = (ROOT / "deploy_server.py").read_text(encoding="utf-8")
    assert '"--ssl-certfile"' in source and '"--ssl-keyfile"' in source
    assert 'scheme = "https"' in source


def _openssl() -> bool:
    import shutil

    return shutil.which("openssl") is not None


def _cryptography() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False
