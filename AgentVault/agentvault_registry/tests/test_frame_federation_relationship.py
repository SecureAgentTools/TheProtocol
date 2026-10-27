"""§MONEY-R52 (2026-09-04, his word "r52 approved too") — the SPIRE federation relationship the approve
rail now creates right after the bundle import. RED control: `R52_SRC=<pre-fix frame_trust_manager.py>`
and `R52_INV_SRC=<pre-fix frame_invitations.py>`.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("R52_SRC", HERE.parent / "src/agentvault_registry/services/frame_trust_manager.py"))
INV = pathlib.Path(os.environ.get("R52_INV_SRC", HERE.parent / "src/agentvault_registry/routers/frame_invitations.py"))
WANTED = ["_normalize_trust_domain", "parse_federation_list", "spire_bundle_endpoint_from_url", "federation_overrides",
          "federation_relationship_argv", "plan_federation_relationship", "ensure_federation_relationship"]


def _load():
    import json
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    ns: dict = {"Optional": object, "List": list, "Tuple": tuple, "json": json, "os": os,
                "logger": logging.getLogger("r52-test"), "SPIRE_BIN_PATH": "/opt/spire/bin/spire-server"}
    picked = [n for n in tree.body if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in WANTED)
              or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("FEDERATION_PROFILE_DEFAULT", "FEDERATION_OVERRIDES_ENV") for t in n.targets))]
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(SRC), "exec"), ns)
    return ns


# the LIVE shapes, read-only, 2026-09-04
FRAME_A_LIST = """Found 2 federation relationships

Trust domain              : frame-b.theprotocol.cloud
Bundle endpoint URL       : https://spire-server-b:8443
Bundle endpoint profile   : https_spiffe
Endpoint SPIFFE ID        : spiffe://frame-b.theprotocol.cloud/spire/server

Trust domain              : frame-c.theprotocol.cloud
Bundle endpoint URL       : https://frame-c-spire-server:8443
Bundle endpoint profile   : https_spiffe
Endpoint SPIFFE ID        : spiffe://frame-c.theprotocol.cloud/spire/server
"""
SBX_ALPHA_LIST = """Found 1 federation relationship

Trust domain              : sandbox-b.theprotocol.cloud
Bundle endpoint URL       : https://sbx-beta-spire-server:8443
Bundle endpoint profile   : https_spiffe
Endpoint SPIFFE ID        : spiffe://sandbox-b.theprotocol.cloud/spire/server
"""
EMPTY_LIST = "Found 0 federation relationships\n"


def test_parser_reads_the_live_shapes():
    ns = _load()
    a = ns["parse_federation_list"](FRAME_A_LIST)
    assert set(a) == {"frame-b.theprotocol.cloud", "frame-c.theprotocol.cloud"}
    assert a["frame-b.theprotocol.cloud"] == {"url": "https://spire-server-b:8443", "profile": "https_spiffe",
                                              "endpoint_spiffe_id": "spiffe://frame-b.theprotocol.cloud/spire/server"}
    assert ns["parse_federation_list"](SBX_ALPHA_LIST)["sandbox-b.theprotocol.cloud"]["url"] == "https://sbx-beta-spire-server:8443"
    assert ns["parse_federation_list"](EMPTY_LIST) == {} and ns["parse_federation_list"]("") == {}


def test_endpoint_derivation_covers_the_three_stored_url_shapes():
    ns = _load()
    f = ns["spire_bundle_endpoint_from_url"]
    assert f("https://frame-b.theprotocol.cloud:8443/.well-known/spiffe/bundle") == "https://frame-b.theprotocol.cloud:8443"
    assert f("https://spire-c.theprotocol.cloud") == "https://spire-c.theprotocol.cloud"
    assert f("https://sbx-beta-spire-server:8443/") == "https://sbx-beta-spire-server:8443"
    assert f("sbx-beta-spire-server:8443") == "https://sbx-beta-spire-server:8443"
    assert f("") == "" and f("https://") == ""


def test_argv_matches_the_cli_and_the_live_model():
    ns = _load()
    argv = ns["federation_relationship_argv"]("create", "sandbox-b.theprotocol.cloud", "https://sbx-beta-spire-server:8443",
                                              "https_spiffe", "spiffe://sandbox-b.theprotocol.cloud/spire/server")
    assert argv == ["/opt/spire/bin/spire-server", "federation", "create",
                    "-trustDomain", "sandbox-b.theprotocol.cloud",
                    "-bundleEndpointURL", "https://sbx-beta-spire-server:8443",
                    "-bundleEndpointProfile", "https_spiffe",
                    "-endpointSpiffeID", "spiffe://sandbox-b.theprotocol.cloud/spire/server"]


def test_plan_creates_when_absent_and_never_touches_an_existing_relationship():
    ns = _load()
    plan = ns["plan_federation_relationship"]
    d, argv, detail = plan({}, "spiffe://sandbox-b.theprotocol.cloud/", "https://sbx-beta-spire-server:8443/")
    assert d == "create" and argv[2] == "create" and detail["url"] == "https://sbx-beta-spire-server:8443"
    assert detail["endpoint_spiffe_id"] == "spiffe://sandbox-b.theprotocol.cloud/spire/server" and detail["profile"] == "https_spiffe"
    # prod's hand-pointed relationship survives an invitation carrying the public well-known URL
    existing = ns["parse_federation_list"](FRAME_A_LIST)
    d, argv, detail = plan(existing, "frame-b.theprotocol.cloud", "https://frame-b.theprotocol.cloud:8443/.well-known/spiffe/bundle")
    assert d == "already" and argv is None and detail["url"] == "https://spire-server-b:8443"
    d, argv, detail = plan({}, "x.example", "")
    assert d == "skip" and argv is None


def test_overrides_win_and_malformed_json_is_ignored():
    ns = _load()
    ov = ns["federation_overrides"]('{"spiffe://peer.example/": {"url": "https://spire.peer.example:8444", "endpoint_spiffe_id": "spiffe://peer.example/spire/server"}}')
    assert "peer.example" in ov
    d, argv, detail = ns["plan_federation_relationship"]({}, "peer.example", "https://peer.example:8443/.well-known/spiffe/bundle", ov)
    assert d == "create" and detail["url"] == "https://spire.peer.example:8444" and detail["overridden"] is True
    assert ns["federation_overrides"]("{not json") == {} and ns["federation_overrides"]("") == {}


def _runner(list_text, create_rc=0, calls=None):
    calls = calls if calls is not None else []

    async def run(container, cmd):
        calls.append((container, list(cmd)))
        if cmd[1:3] == ["federation", "list"]:
            return 0, list_text, ""
        if cmd[1:3] == ["federation", "create"]:
            return create_rc, "" if create_rc == 0 else "", "Error: already exists" if create_rc else ""
        raise AssertionError(cmd)
    return run, calls


def test_ensure_creates_on_a_fresh_server_and_reports_already_on_a_federated_one():
    ns = _load()
    run, calls = _runner(EMPTY_LIST)
    ok, detail = asyncio.run(ns["ensure_federation_relationship"](run, "sbx-alpha-spire-server", "sandbox-b.theprotocol.cloud", "https://sbx-beta-spire-server:8443/"))
    assert ok and detail["decision"] == "create"
    assert [c for _, c in calls if c[1:3] == ["federation", "create"]][0][4] == "sandbox-b.theprotocol.cloud"
    run, calls = _runner(SBX_ALPHA_LIST)
    ok, detail = asyncio.run(ns["ensure_federation_relationship"](run, "sbx-alpha-spire-server", "sandbox-b.theprotocol.cloud", "https://sbx-beta-spire-server:8443/"))
    assert ok and detail["decision"] == "already" and len(calls) == 1   # list only, no write


def test_ensure_reports_a_failed_create_and_a_failed_list():
    ns = _load()
    run, _ = _runner(EMPTY_LIST, create_rc=1)
    ok, detail = asyncio.run(ns["ensure_federation_relationship"](run, "c", "peer.example", "https://peer.example:8443"))
    assert not ok and detail["decision"] == "failed" and "rc=1" in detail["error"]

    async def broken(container, cmd):
        return 2, "", "socket gone"
    ok, detail = asyncio.run(ns["ensure_federation_relationship"](broken, "c", "peer.example", "https://peer.example:8443"))
    assert not ok and detail["decision"] == "error" and "socket gone" in detail["error"]


def test_approve_rail_creates_the_relationship_after_bundle_and_entries_at_both_sites():
    src = INV.read_text(encoding="utf-8"); tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_federation_relationship_after_bundle" in names and "FRAME_FEDERATION_RELATIONSHIP_ON_APPROVE" in src
    sites = 0
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name != "_federation_relationship_after_bundle":
            s = ast.get_source_segment(src, n)
            if "add_peer_bundle(" in s:
                sites += 1
                i1, i2, i3 = s.index("add_peer_bundle("), s.index("_federate_entries_after_bundle("), s.index("_federation_relationship_after_bundle(")
                assert i1 < i2 < i3, n.name
                assert '"federation_relationship": federation_relationship' in s, n.name
    assert sites == 2
    mgr = SRC.read_text(encoding="utf-8")
    assert "async def ensure_federation_relationship(self, trust_domain: str, bundle_endpoint_url: str)" in mgr
