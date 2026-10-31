"""V0650 (session-lead's batch, external dev-machine test run 2): the x509pop helper image is pinned by digest, overridable."""
import importlib
import pathlib


def test_the_openssl_helper_is_pinned_by_digest(monkeypatch):
    monkeypatch.delenv("FRAME_OPENSSL_IMAGE", raising=False)
    from agentvault_registry.services import frame_test_provisioner as p
    p = importlib.reload(p)
    assert p.OPENSSL_IMAGE.startswith("alpine/openssl@sha256:") and len(p.OPENSSL_IMAGE.split("@sha256:")[1]) == 64
    src = pathlib.Path(p.__file__).read_text(encoding="utf-8")
    assert '"alpine/openssl:latest"' not in src    # RED control: V0649 runs the moving tag


def test_the_helper_image_can_be_overridden(monkeypatch):
    monkeypatch.setenv("FRAME_OPENSSL_IMAGE", "registry.example/openssl@sha256:" + "0" * 64)
    from agentvault_registry.services import frame_test_provisioner as p
    p = importlib.reload(p)
    assert p.OPENSSL_IMAGE == "registry.example/openssl@sha256:" + "0" * 64
