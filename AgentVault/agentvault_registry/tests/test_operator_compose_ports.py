"""CB-324 (2026-10-16): the operator bundle's compose binds its plain registry and TEG ports to loopback, so the bundle
as shipped exposes neither; the provisioner rewrites EITHER placeholder form (the loopback one and the older
every-interface one) to the operator's own bind and port. The federation port stays public on purpose.

The module is loaded by path: core/operator_compose.py imports only the standard library, and the package imports
would pull in the registry's settings.
"""
import importlib.util
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "core" / "operator_compose.py"
if _SRC.exists():   # a checkout: load the file itself
    _spec = importlib.util.spec_from_file_location("operator_compose_under_test", _SRC)
    oc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(oc)
else:               # the image (CI mounts tests/ beside an installed package)
    from agentvault_registry.core import operator_compose as oc

TEMPLATE = """services:
  registry:
    ports:
      - "{reg}"
  teg-layer:
    image: images.example/teg-layer:x
    container_name: ${{REGISTRY_NAME:-operator}}-teg
    restart: unless-stopped
    ports:
      - "{teg}"
  nginx-federation:
    container_name: ${{REGISTRY_NAME:-operator}}-nginx-federation
    ports:
      - "12443:8443"
"""


def _adapt(reg_ph, teg_ph, bind):
    compose, notes = oc.adapt_operator_compose(
        TEMPLATE.format(reg=reg_ph, teg=teg_ph), safe="probe", domain="probe.op.example", reg_port=31000,
        fed_port=31443, teg_port=31080, worker_count=2, identity_network="probe-identity", bind_address=bind)
    return compose, notes


def test_loopback_placeholders_take_the_operator_ports():
    out, notes = _adapt("127.0.0.1:12000:8000", "127.0.0.1:12080:8080", "127.0.0.1")
    assert '"127.0.0.1:31000:8000"' in out and '"127.0.0.1:31080:8080"' in out
    assert "12000" not in out and "12080" not in out
    assert not any("teg-layer ports" in n for n in notes)


def test_older_every_interface_placeholders_still_rewritten():
    out, _ = _adapt("12000:8000", "12080:8080", "127.0.0.1")
    assert '"127.0.0.1:31000:8000"' in out and '"127.0.0.1:31080:8080"' in out
    assert "12000" not in out and "12080" not in out


def test_empty_bind_keeps_every_interface_when_asked():
    out, _ = _adapt("127.0.0.1:12000:8000", "127.0.0.1:12080:8080", "")
    assert '"31000:8000"' in out and '"31080:8080"' in out
    assert "127.0.0.1:31000" not in out and "12000" not in out


def test_federation_port_stays_public():
    out, _ = _adapt("127.0.0.1:12000:8000", "127.0.0.1:12080:8080", "127.0.0.1")
    assert '"31443:8443"' in out and "127.0.0.1:31443" not in out
