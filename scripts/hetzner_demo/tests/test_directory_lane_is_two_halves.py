"""§FRAMELIC findings row 170 — the discovery strip is TWO halves; a standup writes both or neither.

The federated-index strip on /explore and Discovery needs:
  1. `DIRECTORY_PUBLIC_URL` in the frame env  → published as `directory_url` in the registry's
     public config, which is the ONLY thing the console reads to decide the strip exists; and
  2. a `/directory/` proxy on the console vhost → how the browser actually reaches the index
     (it listens on loopback only; there is no public hostname for it).

Both were hand-added to the rehearsal pair and lived in NO template, so the clean reprovision
re-rendered the vhosts, wrote a fresh env, and removed the whole lane. Nothing errored: the
strip stopped existing, and `directory_url` read `''` while the index itself was perfectly
healthy (6 registries / 106 agents / fresh cycle). That is the failure this pins.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))

import standup_extras as extras  # noqa: E402

PORTS = {"registry": 8350, "es": 8461, "spire_bundle": 8445, "push": 8790}


def _console(directory_upstream: str) -> str:
    return extras.render_vhost("console", "eu", PORTS, directory_upstream=directory_upstream)


def test_an_upstream_renders_no_loopback_lane_since_mtlsgap():
    """§MTLSGAP (2026-09-08) moved the index behind the registry: the console asks
    `/api/v1/public/directory`, which falls through `location /` to the registry, and the registry
    dials the index over mTLS with its own SVID. So an upstream renders NO `/directory/` lane and no
    plain-http loopback proxy — the vhost only records which upstream the registry was pointed at.
    (This test pinned the pre-§MTLSGAP lane until §ONESHOT 2026-09-12 and had been red since.)"""
    body = _console("https://directory-nginx:8443")
    assert "location /directory/" not in body
    assert "proxy_pass http://127.0.0.1:8600/;" not in body
    assert "directory-nginx:8443" in body and "/api/v1/public/directory" in body


def test_no_upstream_renders_no_lane_at_all():
    """The control, and the point of the whole shape: an inert proxy to an index that does not
    exist is a flag claiming a capability its precondition cannot supply (§FXSTRAND)."""
    body = _console("")
    assert "location /directory/" not in body
    assert "8600" not in body


def test_the_template_still_renders_every_placeholder():
    for up in ("127.0.0.1:8600", ""):
        assert not re.findall(r"\{\{[A-Z_]+\}\}", _console(up))


def test_the_env_template_carries_the_key_the_compose_reads():
    """The three-file chain: env tmpl → compose interpolation → the name main.py reads. A key
    written in only the first two places is a value the process never sees (§D12)."""
    env = (REPO / "templates/frame-test/frame-test.env.tmpl").read_text()
    compose = (REPO / "templates/frame-test/docker-compose.frame-test.yml.tmpl").read_text()
    main = (REPO / "AgentVault/agentvault_registry/src/agentvault_registry/main.py").read_text()
    assert re.search(r"^FT_REG_DIRECTORY_PUBLIC_URL=", env, re.M)
    assert "DIRECTORY_PUBLIC_URL: ${FT_REG_DIRECTORY_PUBLIC_URL}" in compose
    assert 'environ.get("DIRECTORY_PUBLIC_URL"' in main
    # ⚠ THE LANE IS THREE HALVES, NOT TWO. The registry ANDs the address with DISCOVERY_VIA_DIRECTORY
    # and the FE ANDs them again, so an address alone still renders NOTHING — which is exactly what
    # the first pass at this fix produced: directory_url published, strip still absent.
    assert re.search(r"^FT_REG_DISCOVERY_VIA_DIRECTORY=", env, re.M)
    assert "DISCOVERY_VIA_DIRECTORY: ${FT_REG_DISCOVERY_VIA_DIRECTORY}" in compose
    assert 'environ.get("DISCOVERY_VIA_DIRECTORY"' in main


def test_the_driver_writes_the_env_key_from_the_same_flag_as_the_vhost():
    """One fact, one flag. If these ever come apart again the strip dies silently, which is
    exactly how it died the first time."""
    drv = (REPO / "scripts/hetzner_demo/standup_driver.py").read_text()
    assert '("FT_REG_DIRECTORY_PUBLIC_URL", "/api/v1/public/directory" if args.directory_upstream else "")' in drv
    assert '("FT_REG_DIRECTORY_MTLS_URL", args.directory_upstream or "")' in drv
    assert '("FT_REG_DISCOVERY_VIA_DIRECTORY", "true" if args.directory_upstream else "false")' in drv
    assert drv.count("directory_upstream=args.directory_upstream") == 2, \
        "both render_vhosts call sites must carry the upstream"
