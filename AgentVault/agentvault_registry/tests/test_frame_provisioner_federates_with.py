"""§FRAMEFED (2026-09-04) — the frame provisioner federates its workload entries.

Federation has three layers (HANDOVER_2026-09-03_SANDBOX_STANDUP §7.1): the bundle import, the
SPIRE relationship, and `-federatesWith <peer>` on every workload entry. The provisioner created
its three entries without the third; §SBXFED re-created them BY HAND on both sandbox frames.

These tests run the provisioner's pure helpers and `register_test_frame_spire_entries` itself
against a FAKE SPIRE server (a container double whose `exec_run` answers `agent list`,
`bundle list`, `entry create/show/update` and RECORDS every argv). No docker, no network.

RED control: `FRAMEFED_SRC=<pre-fix frame_test_provisioner.py>` and
`FRAMEFED_INV_SRC=<pre-fix frame_invitations.py>` must turn the structural tests red.
"""
from __future__ import annotations

import ast
import os
import pathlib
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get(
    "FRAMEFED_SRC",
    HERE.parent / "src" / "agentvault_registry" / "services" / "frame_test_provisioner.py",
))
INV_SRC = pathlib.Path(os.environ.get(
    "FRAMEFED_INV_SRC",
    HERE.parent / "src" / "agentvault_registry" / "routers" / "frame_invitations.py",
))

WANTED = [
    "parse_entry_show", "parse_bundle_list", "merge_federates_with", "spire_entry_argv",
    "_exec_run_rc_out", "federate_frame_workload_entries", "register_test_frame_spire_entries",
    "never_federated",   # §F6 WP6.1: federate_frame_workload_entries asks it (the data identity and the broker stay unfederated)
    "planned_service_entries",  # §F5: the per-service identities register_test_frame_spire_entries creates
]


def _load():
    """Exec ONLY the functions under test out of the module's AST — the module itself imports
    docker + app settings. Missing functions are simply absent (that is the RED control)."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    ns: dict = {"List": list, "Optional": object, "time": types.SimpleNamespace(sleep=lambda s: None)}
    import logging
    ns["logger"] = logging.getLogger("framefed-test")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANTED:
            mod = ast.Module(body=[node], type_ignores=[])
            exec(compile(mod, str(SRC), "exec"), ns)
    return ns


# ──────────────────────────── fixtures: the live sbx-alpha shape ────────────────────────────
ENTRY_SHOW = """Found 7 entries
Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000001
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/sbx-alpha-registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 3
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:svid-writer-sbx-alpha
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : sbx-alpha-nginx-federation
DNS name         : sbx-alpha-nginx-teg
DNS name         : sandbox-a.theprotocol.cloud

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000002
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/teg-layer
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 1
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:teg-core-sbx-alpha
DNS name         : sbx-alpha-nginx-federation

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000003
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 1
X509-SVID TTL    : default
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:registry-sbx-alpha
Selector         : docker:label:com.agentvault.role:registry
DNS name         : sbx-alpha-nginx-federation

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000004
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/operator/op-sbxalpha
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 1
X509-SVID TTL    : 3600
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:operator-op-sbxalpha
DNS name         : op-sbxalpha-nginx-federation

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000005
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/operator/op-sbxbeta
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 1
X509-SVID TTL    : 3600
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:operator-op-sbxbeta
FederatesWith    : spiffe://frame-c.theprotocol.cloud
DNS name         : op-sbxbeta-nginx-federation

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000006
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did:theprotocol:0000-1111
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Revision         : 1
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.agent:0000-1111

Entry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000007
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/server
Revision         : 0
X509-SVID TTL    : default
JWT-SVID TTL     : default
Selector         : x509pop:subject:cn:sbx-alpha-spire-agent
"""

BUNDLE_LIST = """****************************************
* sandbox-b.theprotocol.cloud
****************************************
-----BEGIN CERTIFICATE-----
MIIBxjCCAWygAwIBAgIQ
-----END CERTIFICATE-----
****************************************
* spiffe://frame-c.theprotocol.cloud
****************************************
-----BEGIN CERTIFICATE-----
MIIBxjCCAWygAwIBAgIQ
-----END CERTIFICATE-----
"""

AGENT_LIST = """Found 1 attested agent:

SPIFFE ID         : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789
Attestation type  : x509pop
Expiration time   : 2026-09-05 10:00:00 +0000 UTC
Serial number     : 12345
"""


def _argv_flag_values(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


# ──────────────────────────────────── pure helpers ────────────────────────────────────
def test_parse_entry_show_reads_the_live_shape():
    ns = _load()
    entries = ns["parse_entry_show"](ENTRY_SHOW)
    assert len(entries) == 7
    first = entries[0]
    assert first["entry_id"] == "0a1b2c3d-1111-4a4a-8b8b-000000000001"
    assert first["spiffe_id"].endswith("/service/sbx-alpha-registry")
    assert first["parent_id"].endswith("/x509pop/abcdef0123456789")
    assert first["selectors"] == ["docker:label:com.agentvault.service:svid-writer-sbx-alpha"]
    # ⚠ THIS ONE DESCRIBES THE FIXTURE ABOVE, NOT THE WIRE. It is a PARSER test: its subject is
    # the text `spire-server entry show` prints, so it asserts what that text contains. The
    # three tests that assert what the PROVISIONER EMITS carry the ES sidecar SAN (§MTLSGAP);
    # since §SOVKIT K1 (2026-09-14) also `<frame>-redpanda`, the ledger broker's TLS name (the store verifies it);
    # widening this one too would have made the parser agree with a fixture it never read.
    assert first["dns"] == ["sbx-alpha-nginx-federation", "sbx-alpha-nginx-teg", "sandbox-a.theprotocol.cloud"]
    assert first["federates_with"] == ["sandbox-b.theprotocol.cloud"]
    assert first["ttl"] == "14400"
    # `default` TTL is None (never re-passed as the literal word "default")
    assert entries[2]["ttl"] is None
    assert entries[2]["selectors"] == [
        "docker:label:com.agentvault.service:registry-sbx-alpha",
        "docker:label:com.agentvault.role:registry",
    ]
    # the spiffe:// form of FederatesWith is normalised to the bare domain
    assert entries[4]["federates_with"] == ["frame-c.theprotocol.cloud"]
    assert entries[5].get("federates_with", []) == []


def test_parse_bundle_list_reads_the_star_lines_only():
    ns = _load()
    assert ns["parse_bundle_list"](BUNDLE_LIST) == ["sandbox-b.theprotocol.cloud", "frame-c.theprotocol.cloud"]
    assert ns["parse_bundle_list"]("") == []
    assert ns["parse_bundle_list"]("****\n-----BEGIN CERTIFICATE-----\nabc\n") == []


def test_merge_federates_with_is_an_order_preserving_union():
    ns = _load()
    m = ns["merge_federates_with"]
    assert m(["b.example", "spiffe://a.example/"], ["a.example", "c.example", "", None, "b.example"]) == [
        "b.example", "a.example", "c.example"
    ]
    assert m([], []) == []


def test_create_argv_carries_federates_with_for_each_present_peer():
    ns = _load()
    argv = ns["spire_entry_argv"](
        "create", spiffe_id="spiffe://td/service/registry", parent_id="spiffe://td/spire/agent/x509pop/ab",
        selectors=["docker:label:x:y", "docker:label:x:y"], dns=["a-nginx-federation", "a-nginx-teg", "a-nginx-teg", "pub.example"],
        ttl="14400", federates_with=["peer-b.example", "spiffe://peer-c.example", "peer-b.example"],
    )
    assert argv[:3] == ["/opt/spire/bin/spire-server", "entry", "create"]
    assert "-entryID" not in argv
    assert _argv_flag_values(argv, "-selector") == ["docker:label:x:y"]
    assert _argv_flag_values(argv, "-dns") == ["a-nginx-federation", "a-nginx-teg", "pub.example"]
    assert _argv_flag_values(argv, "-x509SVIDTTL") == ["14400"]
    assert _argv_flag_values(argv, "-federatesWith") == ["spiffe://peer-b.example", "spiffe://peer-c.example"]
    assert "-ttl" not in argv  # the deprecated flag never comes back


def test_update_argv_repasses_everything_because_update_is_a_replace():
    """R49's rule: `entry update` drops every selector/dns/ttl/federatesWith not re-passed."""
    ns = _load()
    argv = ns["spire_entry_argv"](
        "update", entry_id="E1", spiffe_id="spiffe://td/service/registry", parent_id="spiffe://td/spire/agent/x509pop/ab",
        selectors=["s1", "s2"], dns=["d1"], ttl="3600", federates_with=["old.example", "new.example"],
    )
    assert argv[:5] == ["/opt/spire/bin/spire-server", "entry", "update", "-entryID", "E1"]
    assert _argv_flag_values(argv, "-selector") == ["s1", "s2"]
    assert _argv_flag_values(argv, "-dns") == ["d1"]
    assert _argv_flag_values(argv, "-x509SVIDTTL") == ["3600"]
    assert _argv_flag_values(argv, "-federatesWith") == ["spiffe://old.example", "spiffe://new.example"]
    with pytest.raises(AssertionError):
        ns["spire_entry_argv"]("update", spiffe_id="x", parent_id="y", selectors=[], dns=[])
    # a None TTL (SPIRE printed `default`) is simply not passed — never the word "default"
    argv2 = ns["spire_entry_argv"]("update", entry_id="E2", spiffe_id="x", parent_id="y", selectors=["s"], dns=[], ttl=None)
    assert "-x509SVIDTTL" not in argv2 and "default" not in argv2


# ──────────────────────────── federate_frame_workload_entries ────────────────────────────
class _FakeSpire:
    """exec_fn double: answers `entry show`, records every `entry update`, fails the ones named."""

    def __init__(self, fail_entry_ids=()):
        self.calls = []
        self.fail = set(fail_entry_ids)

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[1:3] == ["entry", "show"]:
            return 0, ENTRY_SHOW
        if argv[1:3] == ["entry", "update"]:
            eid = argv[argv.index("-entryID") + 1]
            return (1, f"rc=1: datastore error for {eid}") if eid in self.fail else (0, "Entry ID : " + eid)
        raise AssertionError(f"unexpected argv {argv}")


def test_federate_workload_entries_updates_services_and_operators_and_skips_agents():
    ns = _load()
    fake = _FakeSpire()
    ok, detail = ns["federate_frame_workload_entries"]("sbx-alpha-spire-server", "spiffe://sandbox-b.theprotocol.cloud/", exec_fn=fake)
    assert ok is True
    assert detail["peer"] == "sandbox-b.theprotocol.cloud"
    # 3 services + 2 operators = 5 workload entries; entry 1 already federates with the peer
    assert detail["updated"] == 4 and detail["already"] == 1 and detail["failed"] == []
    # the agent identity and the SPIRE agent itself are never touched
    assert detail["skipped"] == 2
    updates = [c for c in fake.calls if c[1:3] == ["entry", "update"]]
    assert len(updates) == 4
    touched = {c[c.index("-spiffeID") + 1] for c in updates}
    assert all(("/service/" in s or "/operator/" in s) for s in touched)
    assert not any("/agent/" in s or "/spire/agent/" in s for s in touched)
    # every update re-passes what the entry had (R49) and adds the peer
    by_id = {c[c.index("-entryID") + 1]: c for c in updates}
    reg = by_id["0a1b2c3d-1111-4a4a-8b8b-000000000003"]
    assert _argv_flag_values(reg, "-selector") == [
        "docker:label:com.agentvault.service:registry-sbx-alpha", "docker:label:com.agentvault.role:registry"
    ]
    assert _argv_flag_values(reg, "-dns") == ["sbx-alpha-nginx-federation"]
    assert "-x509SVIDTTL" not in reg  # it printed `default`
    assert _argv_flag_values(reg, "-parentID") == ["spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789"]
    assert _argv_flag_values(reg, "-federatesWith") == ["spiffe://sandbox-b.theprotocol.cloud"]
    # an entry that already federates with ANOTHER peer keeps it — union, never replace
    opb = by_id["0a1b2c3d-1111-4a4a-8b8b-000000000005"]
    assert _argv_flag_values(opb, "-federatesWith") == ["spiffe://frame-c.theprotocol.cloud", "spiffe://sandbox-b.theprotocol.cloud"]
    assert _argv_flag_values(opb, "-x509SVIDTTL") == ["3600"]


def test_federate_workload_entries_reports_failures_by_name_and_is_not_ok():
    ns = _load()
    fake = _FakeSpire(fail_entry_ids={"0a1b2c3d-1111-4a4a-8b8b-000000000002"})
    ok, detail = ns["federate_frame_workload_entries"]("x", "sandbox-b.theprotocol.cloud", exec_fn=fake)
    assert ok is False
    assert detail["updated"] == 3 and len(detail["failed"]) == 1
    assert "/service/teg-layer" in detail["failed"][0] and "rc=1" in detail["failed"][0]


def test_federate_workload_entries_refuses_an_empty_peer_and_a_failed_show():
    ns = _load()
    ok, detail = ns["federate_frame_workload_entries"]("x", "   ", exec_fn=lambda argv: (0, ""))
    assert ok is False and "empty" in detail["error"]
    ok, detail = ns["federate_frame_workload_entries"]("x", "b.example", exec_fn=lambda argv: (7, "boom"))
    assert ok is False and "rc=7" in detail["error"]


def test_include_operators_false_touches_only_service_entries():
    ns = _load()
    fake = _FakeSpire()
    ok, detail = ns["federate_frame_workload_entries"]("x", "sandbox-b.theprotocol.cloud", exec_fn=fake, include_operators=False)
    assert ok and detail["updated"] == 2 and detail["already"] == 1 and detail["skipped"] == 4


# ──────────────────────── register_test_frame_spire_entries end to end ────────────────────────
class _FakeContainer:
    """docker SDK container double for ONE frame's spire-server. `existing` = the entries SPIRE
    already holds (spiffe_id -> block text); `entry create` on one of them fails like SPIRE does."""

    def __init__(self, bundle_list_text, existing=None, create_rc=0):
        self.calls = []
        self.bundle_list_text = bundle_list_text
        self.existing = dict(existing or {})
        self.create_rc = create_rc

    def exec_run(self, cmd, **_kw):
        cmd = list(cmd)
        self.calls.append(cmd)
        sub = cmd[1:3]
        if sub == ["agent", "list"]:
            return (0, AGENT_LIST.encode())
        if sub == ["bundle", "list"]:
            return (0, self.bundle_list_text.encode())
        if sub == ["entry", "create"]:
            sid = cmd[cmd.index("-spiffeID") + 1]
            if sid in self.existing:
                return (1, b"Error: similar entry already exists")
            return (self.create_rc, b"Entry ID : new")
        if sub == ["entry", "show"]:
            sid = cmd[cmd.index("-spiffeID") + 1]
            return (0, self.existing.get(sid, "Found 0 entries\n").encode())
        if sub == ["entry", "update"]:
            return (0, b"Entry ID : updated")
        if sub == ["entry", "delete"]:
            # §F5: a re-key is delete-then-create; after the delete the create of that id succeeds
            eid = cmd[cmd.index("-entryID") + 1]
            self.existing = {sid: blk for sid, blk in self.existing.items() if f"Entry ID         : {eid}\n" not in blk}
            return (0, b"Entry deleted")
        raise AssertionError(f"unexpected {cmd}")


def _ctx(**over):
    base = dict(
        trust_domain="sandbox-a.theprotocol.cloud", registry_name="sbx-alpha",
        public_hostname="sandbox-a.theprotocol.cloud",
        extra_trusted_spiffe_domains=["sandbox-b.theprotocol.cloud", "agentvault.com", "sandbox-a.theprotocol.cloud"],
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _run_provisioner(ns, container, ctx):
    ns["_docker_client"] = lambda: types.SimpleNamespace(containers=types.SimpleNamespace(get=lambda name: container))
    return ns["register_test_frame_spire_entries"](ctx)


# The entries the provisioner creates for one frame. §F5 (2026-09-26): the three registry-class entries (the writer's file
# identity, the TEG's `teg-layer` on ITS writer's label, the registry's own Workload identity) are CLIENT identities and carry
# no DNS name; every service that SERVES a name has its own entry with exactly that name and its own writer's selector
# (§SOVKIT the Directory; §MTLSHOPS T2 the kit and the solo auditor; T3 the data identity; F5 the store, the three sidecars
# and the broker). A new identity changes this table on purpose; the tests below never count on their own.
SIDECAR_IDENTITIES = ("/service/sbx-alpha-registry", "/service/teg-layer", "/service/registry")
OWN_IDENTITIES = {
    "/service/directory": (["sbx-alpha-directory-nginx", "directory-nginx", "directory"],
                           "docker:label:com.agentvault.service:svid-writer-directory-sbx-alpha"),
    "/service/kit": (["sbx-alpha-opa", "sbx-alpha-prometheus", "sbx-alpha-alertmanager", "sbx-alpha-nginx-ntfy"],
                     "docker:label:com.agentvault.service:svid-writer-kit-sbx-alpha"),
    "/service/auditor": (["sbx-alpha-nginx-auditor"], "docker:label:com.agentvault.service:svid-writer-auditor-sbx-alpha"),
    # §MTLSHOPS T3: the data identity, served by the three Postgres servers and Redis under the names their clients verify
    "/service/data": (["sbx-alpha-db", "sbx-alpha-teg-db", "sbx-alpha-es-db", "sbx-alpha-redis"],
                      "docker:label:com.agentvault.service:svid-writer-data-sbx-alpha"),
    # §F5: the store (a client identity, no name), each sidecar with only its own name (the federation gateway also the
    # public host a peer dials), the broker with the name the store verifies
    "/service/event-store": ([], "docker:label:com.agentvault.service:svid-writer-es-sbx-alpha"),
    "/service/sbx-alpha-nginx-event-store": (["sbx-alpha-nginx-event-store"],
                                             "docker:label:com.agentvault.service:svid-writer-nginx-event-store-sbx-alpha"),
    "/service/sbx-alpha-nginx-teg": (["sbx-alpha-nginx-teg"], "docker:label:com.agentvault.service:svid-writer-nginx-teg-sbx-alpha"),
    "/service/sbx-alpha-nginx-federation": (["sbx-alpha-nginx-federation", "sandbox-a.theprotocol.cloud"],
                                            "docker:label:com.agentvault.service:svid-writer-nginx-federation-sbx-alpha"),
    "/service/sbx-alpha-redpanda": (["sbx-alpha-redpanda"], "docker:label:com.agentvault.service:svid-writer-redpanda-sbx-alpha"),
}
# §MTLSHOPS T3 / §F5: the data identity and the broker are never federated, so their bundles hold the frame's own root alone
# and no peer's SPIRE can mint a certificate the data services or the store's Kafka client accept.
NEVER_FEDERATED = {"/service/data", "/service/sbx-alpha-redpanda"}
ENTRIES = len(SIDECAR_IDENTITIES) + len(OWN_IDENTITIES)


def _split_entries(creates):
    """The created entries by SPIFFE path, each exactly once: the sidecar entries in order, the own-name identities by path."""
    by_path = {}
    for c in creates:
        path = "/" + _argv_flag_values(c, "-spiffeID")[0].split("://", 1)[1].split("/", 1)[1]
        assert path not in by_path, f"{path} is created exactly once"
        by_path[path] = c
    assert set(by_path) == set(SIDECAR_IDENTITIES) | set(OWN_IDENTITIES), sorted(by_path)
    return [by_path[p] for p in SIDECAR_IDENTITIES], {p: by_path[p] for p in OWN_IDENTITIES}


def test_provisioner_federates_at_create_time_with_peers_whose_bundle_is_present():
    ns = _load()
    fake = _FakeContainer(BUNDLE_LIST)          # sandbox-b + frame-c present; agentvault.com NOT
    ok, msg = _run_provisioner(ns, fake, _ctx())
    assert ok, msg
    creates = [c for c in fake.calls if c[1:3] == ["entry", "create"]]
    assert len(creates) == ENTRIES
    sidecars, own = _split_entries(creates)
    for path, (dns, selector) in OWN_IDENTITIES.items():
        assert _argv_flag_values(own[path], "-dns") == dns, path
        assert _argv_flag_values(own[path], "-selector") == [selector], path
        # the Directory reads peers' cards; the kit and the auditor federate as every service entry does; the data identity never
        want = [] if path in NEVER_FEDERATED else ["spiffe://sandbox-b.theprotocol.cloud"]
        assert _argv_flag_values(own[path], "-federatesWith") == want, path
    for c in sidecars:
        # present peer → federatesWith; our own domain never; absent bundle → deferred, not passed
        assert _argv_flag_values(c, "-federatesWith") == ["spiffe://sandbox-b.theprotocol.cloud"]
        # §F5: a client identity carries NO DNS name; the names moved to the entries of the services that serve them
        assert "-dns" not in c, c
        assert _argv_flag_values(c, "-x509SVIDTTL") == ["14400"]
        assert _argv_flag_values(c, "-parentID") == ["spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789"]
    # §F5: each of the three is keyed on its OWN writer's label; the TEG's `teg-layer` on `svid-writer-teg-<frame>`,
    # never on the TEG container's own label (that entry was never fetched, so the TEG spoke as the registry)
    assert [_argv_flag_values(c, "-selector") for c in sidecars] == [
        ["docker:label:com.agentvault.service:svid-writer-sbx-alpha"],
        ["docker:label:com.agentvault.service:svid-writer-teg-sbx-alpha"],
        ["docker:label:com.agentvault.service:registry-sbx-alpha"],
    ]
    assert "registry dns=none (§F5)" in msg
    assert f"added {ENTRIES}/{ENTRIES}" in msg
    assert "federatesWith=['sandbox-b.theprotocol.cloud']" in msg
    assert "deferred until their bundle lands: ['agentvault.com']" in msg


def test_provisioner_without_any_peer_bundle_creates_plain_entries_and_names_the_deferred():
    ns = _load()
    fake = _FakeContainer("")                    # a brand-new frame: no bundle imported yet
    ok, msg = _run_provisioner(ns, fake, _ctx(extra_trusted_spiffe_domains=["sandbox-b.theprotocol.cloud"]))
    assert ok, msg
    creates = [c for c in fake.calls if c[1:3] == ["entry", "create"]]
    assert len(creates) == ENTRIES and all("-federatesWith" not in c for c in creates)
    assert "federatesWith=none" in msg and "deferred" in msg and "sandbox-b.theprotocol.cloud" in msg


# §MTLSGAP (2026-09-08) — THE SAN LIST GREW BY ONE AND THAT IS THE POINT, not drift to undo.
# The EventStore had no mTLS gateway on any frame the template ever built (it renders two
# sidecars and never a third), so a registry wrote to its own ledger over plain http. The third
# sidecar `<frame>-nginx-event-store` needs its DNS SAN or a caller that verifies the hostname
# gets a mismatch however sound the chain — a gateway nothing can verify against is worse than
# none. §F5 (2026-09-26) moved that name from the registry's shared entry onto the ES gateway's OWN
# entry; the name is still carried, by the one service that serves it. If this assertion goes red,
# ask whether the ES gateway was removed before dropping its name.
def test_provisioner_without_public_hostname_keeps_each_servers_own_san():
    ns = _load()
    fake = _FakeContainer("")
    ok, msg = _run_provisioner(ns, fake, _ctx(public_hostname="", extra_trusted_spiffe_domains=[]))
    assert ok, msg
    creates = [c for c in fake.calls if c[1:3] == ["entry", "create"]]
    sidecars, own = _split_entries(creates)
    assert all("-dns" not in c for c in sidecars), "the registry-class identities are clients: no name, with or without a public host"
    assert _argv_flag_values(own["/service/sbx-alpha-nginx-event-store"], "-dns") == ["sbx-alpha-nginx-event-store"]
    for path, (dns, _selector) in OWN_IDENTITIES.items():
        want = [d for d in dns if d != "sandbox-a.theprotocol.cloud"]  # only the federation gateway ever carried it
        assert _argv_flag_values(own[path], "-dns") == want, f"{path}'s SANs carry the public hostname only when one is set"
    assert "federatesWith=none" in msg and "deferred" not in msg


def test_provisioner_rerun_updates_an_existing_entry_instead_of_failing_it():
    """A re-run (or a retry after a partial first run) meets entries that exist. `entry create`
    refuses; the provisioner shows the entry and UPDATEs it — re-passing everything, adding
    what this run wants (the now-present peer). §F5: the DNS list is REPLACED by what this run
    wants, never appended, so a pre-F5 entry that carried the sidecars' names loses them here."""
    ns = _load()
    existing_block = (
        "Entry ID         : E-REG\n"
        "SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/registry\n"
        "Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789\n"
        "X509-SVID TTL    : 14400\n"
        "Selector         : docker:label:com.agentvault.service:registry-sbx-alpha\n"
        "FederatesWith    : frame-c.theprotocol.cloud\n"
        "DNS name         : sbx-alpha-nginx-federation\n"
        "DNS name         : sbx-alpha-nginx-teg\n"
    )
    fake = _FakeContainer(BUNDLE_LIST, existing={"spiffe://sandbox-a.theprotocol.cloud/service/registry": existing_block})
    ok, msg = _run_provisioner(ns, fake, _ctx())
    assert ok, msg
    assert f"added {ENTRIES - 1}/{ENTRIES}" in msg and "updated 1" in msg and "FAILED" not in msg
    updates = [c for c in fake.calls if c[1:3] == ["entry", "update"]]
    assert len(updates) == 1
    u = updates[0]
    assert _argv_flag_values(u, "-entryID") == ["E-REG"]
    assert _argv_flag_values(u, "-selector") == ["docker:label:com.agentvault.service:registry-sbx-alpha"]
    assert "-dns" not in u, "the two names the pre-F5 entry carried come OFF: an update replaces, an empty list is a removal"
    assert _argv_flag_values(u, "-x509SVIDTTL") == ["14400"]
    # union: what it had (frame-c) + what this run wants (sandbox-b, present)
    assert _argv_flag_values(u, "-federatesWith") == ["spiffe://frame-c.theprotocol.cloud", "spiffe://sandbox-b.theprotocol.cloud"]


def test_provisioner_rerun_rekeys_the_teg_entry_from_its_container_label_to_its_writers():
    """§F5: `entry update` MERGES selectors and SPIRE ANDs them, so an entry updated onto a second label matches no
    container at all (measured on the sandbox pair 2026-09-26). An entry found on ANOTHER label is deleted and created
    again on the writer's label, keeping its TTL, its parent and the union of its peers; nothing else is touched."""
    ns = _load()
    existing_block = (
        "Entry ID         : E-TEG\n"
        "SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/teg-layer\n"
        "Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789\n"
        "X509-SVID TTL    : 7200\n"
        "Selector         : docker:label:com.agentvault.service:teg-core-sbx-alpha\n"
        "FederatesWith    : frame-c.theprotocol.cloud\n"
        "DNS name         : sbx-alpha-nginx-federation\n"
        "DNS name         : sandbox-a.theprotocol.cloud\n"
    )
    fake = _FakeContainer(BUNDLE_LIST, existing={"spiffe://sandbox-a.theprotocol.cloud/service/teg-layer": existing_block})
    ok, msg = _run_provisioner(ns, fake, _ctx())
    assert ok, msg
    assert f"added {ENTRIES - 1}/{ENTRIES}" in msg and "updated 1" in msg and "FAILED" not in msg
    assert [c for c in fake.calls if c[1:3] == ["entry", "update"]] == [], "a re-key never UPDATEs (a merged selector matches nothing)"
    deletes = [c for c in fake.calls if c[1:3] == ["entry", "delete"]]
    assert deletes == [["/opt/spire/bin/spire-server", "entry", "delete", "-entryID", "E-TEG"]]
    teg_creates = [c for c in fake.calls if c[1:3] == ["entry", "create"] and c[c.index("-spiffeID") + 1].endswith("/service/teg-layer")]
    assert len(teg_creates) == 2, "the refused first create, then the re-key create after the delete"
    assert fake.calls.index(deletes[0]) < fake.calls.index(teg_creates[1])
    rk = teg_creates[1]
    assert _argv_flag_values(rk, "-selector") == ["docker:label:com.agentvault.service:svid-writer-teg-sbx-alpha"]
    assert "-dns" not in rk
    assert _argv_flag_values(rk, "-x509SVIDTTL") == ["7200"], "the entry's own TTL survives the re-key"
    assert _argv_flag_values(rk, "-parentID") == ["spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789"]
    assert _argv_flag_values(rk, "-federatesWith") == ["spiffe://frame-c.theprotocol.cloud", "spiffe://sandbox-b.theprotocol.cloud"]


def test_provisioner_rerun_strips_any_federation_from_the_data_identity():
    """§MTLSHOPS T3: an existing data entry that somehow federates is updated back to no peer (update is a replace)."""
    ns = _load()
    existing_block = (
        "Entry ID         : E-DATA\n"
        "SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/data\n"
        "Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789\n"
        "X509-SVID TTL    : 14400\n"
        "Selector         : docker:label:com.agentvault.service:svid-writer-data-sbx-alpha\n"
        "FederatesWith    : frame-c.theprotocol.cloud\n"
        "DNS name         : sbx-alpha-db\n"
    )
    fake = _FakeContainer(BUNDLE_LIST, existing={"spiffe://sandbox-a.theprotocol.cloud/service/data": existing_block})
    ok, msg = _run_provisioner(ns, fake, _ctx())
    assert ok, msg
    (u,) = [c for c in fake.calls if c[1:3] == ["entry", "update"]]
    assert _argv_flag_values(u, "-entryID") == ["E-DATA"] and "-federatesWith" not in u
    assert _argv_flag_values(u, "-dns") == ["sbx-alpha-db", "sbx-alpha-teg-db", "sbx-alpha-es-db", "sbx-alpha-redis"]


def test_the_approve_rail_never_federates_the_data_identity():
    ns = _load()
    show = ENTRY_SHOW + (
        "\nEntry ID         : 0a1b2c3d-1111-4a4a-8b8b-000000000008\n"
        "SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/data\n"
        "Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/abcdef0123456789\n"
        "X509-SVID TTL    : 14400\n"
        "Selector         : docker:label:com.agentvault.service:svid-writer-data-sbx-alpha\n"
        "DNS name         : sbx-alpha-db\n"
    )
    calls = []

    def exec_fn(argv):
        calls.append(list(argv))
        return (0, show) if argv[1:3] == ["entry", "show"] else (0, "ok")

    ok, detail = ns["federate_frame_workload_entries"]("sbx-alpha-spire-server", "sandbox-b.theprotocol.cloud", exec_fn=exec_fn)
    assert ok and detail["updated"] == 4 and detail["already"] == 1 and detail["skipped"] == 3
    assert not any(c[c.index("-spiffeID") + 1].endswith("/service/data") for c in calls if c[1:3] == ["entry", "update"])


def test_provisioner_still_reports_a_refused_create_as_failed():
    """The exit-code accounting of §XFRAMETEG survives: a create that fails for a reason other
    than 'exists' (entry show finds nothing) is counted and named, never swallowed."""
    ns = _load()
    fake = _FakeContainer("", create_rc=1)
    ok, msg = _run_provisioner(ns, fake, _ctx(extra_trusted_spiffe_domains=[]))
    assert ok  # the function's contract: True with the failures NAMED in msg
    assert f"{ENTRIES} FAILED" in msg and f"added 0/{ENTRIES}" in msg


# ──────────────────────────────── structural (RED-controlled) ────────────────────────────────
def test_provisioner_source_wires_federation_and_the_update_path():
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register_test_frame_spire_entries")
    body = ast.get_source_segment(src, fn)
    assert "parse_bundle_list(" in body, "create-time federation reads `bundle list`"
    assert "_federates(svid)" in body and "never_federated" in body, "present peers ride the create of every entry but the never-federated ones"
    assert "planned_service_entries(" in body, "§F5: the per-service identities come from the one pure plan the tests pin"
    assert '"entry", "delete"' in body and "selector not in e.get(" in body, "§F5: an entry on another label is re-keyed by delete-then-create, never merged"
    assert "fed_deferred" in body, "absent bundles are NAMED, not forgotten"
    assert "ctx.public_hostname" in body, "the public hostname is a DNS SAN"
    assert '"update"' in body and "parse_entry_show(" in body, "an existing entry is updated, not failed"
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"federate_frame_workload_entries", "spire_entry_argv", "merge_federates_with"} <= names


def test_approve_rail_federates_entries_right_after_the_bundle_import():
    src = INV_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_federate_entries_after_bundle" in names
    helper = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_federate_entries_after_bundle")
    hsrc = ast.get_source_segment(src, helper)
    assert "federate_frame_workload_entries" in hsrc and "FRAME_FEDERATE_ENTRIES_ON_APPROVE" in src
    assert "mgr.spire_container" in hsrc
    # both bundle-import sites call it, and every completed response carries the outcome
    sites = 0
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name != "_federate_entries_after_bundle":
            s = ast.get_source_segment(src, n)
            if "add_peer_bundle(" in s:
                sites += 1
                assert "_federate_entries_after_bundle(" in s, n.name
                assert s.index("add_peer_bundle(") < s.index("_federate_entries_after_bundle("), n.name
                assert '"entries_federated": entries_federated' in s, n.name
    assert sites == 2, sites

# ─────────────────────── the LIVE shape, captured read-only from sbx-alpha 2026-09-04 ───────────────────────
# (entry metadata only: SPIFFE IDs, selectors, DNS SANs, TTLs — the frame §SBXFED federated BY HAND)
REAL_ENTRY_SHOW = """Found 13 entries
Entry ID         : db52104e-fc02-4d38-8619-96a5b915985b
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-04e166c0-1c0d-77ef-ae00
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-04e166c0-1c0d-77ef-ae00

Entry ID         : f6da89eb-974b-449c-ab81-6892e70bd4cd
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-4fe2c451-c875-25bb-f429
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-4fe2c451-c875-25bb-f429

Entry ID         : 22e0d32e-c5fa-45fe-8c37-9b2d7e19c9b2
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-5f5dcf46-a9f6-124c-b7bb
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-5f5dcf46-a9f6-124c-b7bb

Entry ID         : 881b7144-eaf2-4d2a-bbd1-30d45aa3ca99
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-ba6df0c0-8f26-971e-8577
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-ba6df0c0-8f26-971e-8577

Entry ID         : a7e80656-8c7f-4c4e-ae9c-4784d58fe554
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-d14c60cd-796e-5ad1-4061
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-d14c60cd-796e-5ad1-4061

Entry ID         : e5c6fe82-5557-4532-85d2-fb7f215ccf2a
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-d61b3524-7fa4-7ac4-098c
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-d61b3524-7fa4-7ac4-098c

Entry ID         : 4dfebec6-99fe-44a7-a0f8-169dd5f79238
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/agent/did-theprotocol-ecd4e3e6-84e6-92cb-5a00
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007
Revision         : 0
X509-SVID TTL    : 1800
JWT-SVID TTL     : default
Selector         : docker:label:com.theprotocol.agent-did:did-theprotocol-ecd4e3e6-84e6-92cb-5a00

Entry ID         : 033812ec-2a01-4f25-aaf9-c2678b6d8a4f
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/bc4efc7aae78d62961cedbf48f6fdeee150ec357
Revision         : 1
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:registry
FederatesWith    : sandbox-b.theprotocol.cloud

Entry ID         : 21efa099-97dd-4f01-b94f-a89e846c78bc
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/svid-writer
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/bc4efc7aae78d62961cedbf48f6fdeee150ec357
Revision         : 3
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:svid-writer-operator
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : nginx-federation
DNS name         : sbxalphaop.op.theprotocol.cloud
DNS name         : nginx-teg

Entry ID         : 4adc65f9-e257-4176-80c9-69741913df06
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/operator/sbxalphaop/teg
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/bc4efc7aae78d62961cedbf48f6fdeee150ec357
Revision         : 1
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:teg-layer
FederatesWith    : sandbox-b.theprotocol.cloud

Entry ID         : 03acfe79-e620-4d7d-90f5-4e51e82d67c6
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/dae5b651396319afea4481d7b0ff72ef13a0087a
Revision         : 2
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:registry-sbx-alpha
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : sbx-alpha-nginx-federation
DNS name         : sandbox-a.theprotocol.cloud

Entry ID         : a8cc72eb-0cb9-4cf0-bc68-155807c7be57
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/sbx-alpha-registry
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/dae5b651396319afea4481d7b0ff72ef13a0087a
Revision         : 3
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:svid-writer-sbx-alpha
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : sbx-alpha-nginx-federation
DNS name         : sbx-alpha-nginx-teg
DNS name         : sandbox-a.theprotocol.cloud

Entry ID         : c0839d6f-812a-4e7c-951b-885545248d6d
SPIFFE ID        : spiffe://sandbox-a.theprotocol.cloud/service/teg-layer
Parent ID        : spiffe://sandbox-a.theprotocol.cloud/spire/agent/x509pop/dae5b651396319afea4481d7b0ff72ef13a0087a
Revision         : 2
X509-SVID TTL    : 14400
JWT-SVID TTL     : default
Selector         : docker:label:com.agentvault.service:teg-core-sbx-alpha
FederatesWith    : sandbox-b.theprotocol.cloud
DNS name         : sbx-alpha-nginx-federation
DNS name         : sandbox-a.theprotocol.cloud

"""


def test_live_shape_parses_and_the_helper_reads_it_as_already_federated():
    ns = _load()
    entries = ns["parse_entry_show"](REAL_ENTRY_SHOW)
    assert len(entries) == 13
    kinds = {"service": 0, "operator": 0, "agent": 0}
    for e in entries:
        path = e["spiffe_id"].split("://", 1)[1].split("/", 1)[1]
        kinds[path.split("/")[0]] += 1
    assert kinds == {"service": 3, "operator": 3, "agent": 7}
    # every workload entry the hand step touched carries the peer; the helper must NOT re-update them
    fake = _FakeSpire()
    fake.__call__  # noqa: B018
    calls = []

    def exec_fn(argv):
        calls.append(list(argv))
        return (0, REAL_ENTRY_SHOW) if argv[1:3] == ["entry", "show"] else (0, "")

    ok, detail = ns["federate_frame_workload_entries"]("sbx-alpha-spire-server", "sandbox-b.theprotocol.cloud", exec_fn=exec_fn)
    assert ok and detail["updated"] == 0 and detail["already"] == 6 and detail["skipped"] == 7 and detail["failed"] == []
    assert [c for c in calls if c[1:3] == ["entry", "update"]] == []
    # a NEW peer lands on exactly the 6 workload entries, each re-passing its DNS SANs and sandbox-b
    calls.clear()
    ok, detail = ns["federate_frame_workload_entries"]("sbx-alpha-spire-server", "sandbox-c.theprotocol.cloud", exec_fn=exec_fn)
    assert ok and detail["updated"] == 6 and detail["already"] == 0 and detail["skipped"] == 7
    ups = [c for c in calls if c[1:3] == ["entry", "update"]]
    assert len(ups) == 6
    for u in ups:
        assert _argv_flag_values(u, "-federatesWith") == ["spiffe://sandbox-b.theprotocol.cloud", "spiffe://sandbox-c.theprotocol.cloud"]
        assert "-entryID" in u and "-parentID" in u and "-selector" in u
    reg = next(u for u in ups if u[u.index("-spiffeID") + 1].endswith("/service/sbx-alpha-registry"))
    assert set(_argv_flag_values(reg, "-dns")) >= {"sbx-alpha-nginx-federation", "sandbox-a.theprotocol.cloud"}
    assert _argv_flag_values(reg, "-x509SVIDTTL") == ["14400"]
