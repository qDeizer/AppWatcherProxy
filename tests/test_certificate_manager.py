from backend.cert.manager import CertificateManager


def test_ensure_ca_creates_reusable_certificate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(CertificateManager, "_is_trusted", lambda *_: False)
    manager = CertificateManager(tmp_path / "mitmproxy")

    first = manager.ensure_ca()
    second = manager.ensure_ca()

    assert first.exists
    assert first.path.exists()
    assert manager.combined_ca_path.exists()
    assert first.thumbprint == second.thumbprint
    assert first.subject == "O=mitmproxy,CN=mitmproxy"
    assert not first.trusted


def test_status_reports_missing_certificate(tmp_path) -> None:
    status = CertificateManager(tmp_path / "missing").status()

    assert not status.exists
    assert status.thumbprint is None
    assert not status.trusted

