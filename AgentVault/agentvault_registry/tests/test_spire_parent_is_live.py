"""§FRAMELIC findings row 198 — an agent identity must be parented to a node that EXISTS.

`POST /agent/enable-mtls` answered **200 "enrolled"** on EU and ASIA while creating a SPIRE entry
parented to `MAINFRAME_AGENT_FINGERPRINT` — Frame A's node, hardcoded — because the parent
auto-detect looks up `/service/registry-<safe>` and the frame template registers the service as
plain `/service/registry`. Measured on EU: 0 agents match that fingerprint, 1 entry was parented
to it (the one just created), and the workload sat on `PERMISSION_DENIED` forever.

The code's own comment records this happening before: *"§pass31 Phase 4 fix — before this,
sandbox-A + Frame B registries fell through to mainframe fingerprint, producing SPIRE entries with
wrong parentID → PERMISSION_DENIED"*. That fix cured the instance and LEFT THE FALLBACK, so it
came back the moment a frame named its registry service differently.

Two halves here, and the second is the one that generalises:
  1. the auto-detect looks under both names the service is registered under; and
  2. whatever produced the parent, it is checked against the live agent nodes before anything is
     created — because a 200 that means "never" is the worst answer a rail can give.
"""
import pytest

from agentvault_registry.services import agent_spire


class _Exec:
    """Stands in for `container.exec_run`, answering per spire-server subcommand."""

    def __init__(self, entries: dict, nodes: list):
        self.entries = entries      # spiffeID -> parent fingerprint (or None for "Found 0")
        self.nodes = nodes
        self.calls = []

    def exec_run(self, cmd, demux=True):
        self.calls.append(cmd)
        if "agent" in cmd and "list" in cmd:
            body = "".join(
                f"SPIFFE ID : spiffe://eu.theprotocol.cloud/spire/agent/x509pop/{n}\n"
                for n in self.nodes
            )
            return 0, (body.encode(), b"")
        if "entry" in cmd and "show" in cmd:
            sid = cmd[cmd.index("-spiffeID") + 1]
            parent = self.entries.get(sid)
            if not parent:
                return 0, (b"Found 0 entries\n", b"")
            body = (f"SPIFFE ID : {sid}\n"
                    f"Parent ID : spiffe://eu.theprotocol.cloud/spire/agent/x509pop/{parent}\n")
            # ⚠ (exit_code, (stdout, stderr)) — the caller unpacks TWO values, and the first
            # draft returned a 3-tuple here, which failed as an "autodetect broken" result.
            return 0, (body.encode(), b"")
        return 1, (b"", b"unexpected")


LIVE = "f7f4bd38aa768526d8a2336334636d9bcc2377ab"
FRAME_A = agent_spire.MAINFRAME_AGENT_FINGERPRINT


@pytest.fixture
def spire(monkeypatch):
    """Wire the module at a fake SPIRE, and clear the fingerprint cache between tests."""
    state = {"exec": None}

    class _Client:
        class containers:
            @staticmethod
            def get(_name):
                return state["exec"]

    def _install(entries, nodes):
        e = _Exec(entries, nodes)
        # exec_run must be reachable as container.exec_run
        e_obj = type("C", (), {"exec_run": e.exec_run, "_probe": e})()
        state["exec"] = e_obj
        return e

    monkeypatch.setattr(agent_spire, "_LOCAL_SPIRE_AVAILABLE", True)
    monkeypatch.setattr(agent_spire, "_get_docker_client", lambda: _Client())
    monkeypatch.setattr(agent_spire, "TRUST_DOMAIN", "eu.theprotocol.cloud")
    monkeypatch.setattr(agent_spire, "_cached_local_fingerprint", None)
    monkeypatch.delenv("OPERATOR_SPIRE_AGENT_FINGERPRINT", raising=False)
    return _install


# ── half 1: find the entry under the name the template actually writes ────────────────────

def test_autodetect_finds_the_plain_service_registry_entry(spire, monkeypatch):
    """THE BUG. The composed name `/service/registry-eu` does not exist; the real one is
    `/service/registry`. Before this, that produced 'Found 0 entries' and a fallback."""
    monkeypatch.setattr(agent_spire, "_proxy_spiffe_id",
                        lambda: "spiffe://eu.theprotocol.cloud/service/registry-eu")
    spire({"spiffe://eu.theprotocol.cloud/service/registry": LIVE}, [LIVE])
    assert agent_spire._autodetect_local_fingerprint() == LIVE


def test_autodetect_still_prefers_the_suffixed_name_when_it_exists(spire, monkeypatch):
    """The control: frames that DO register `/service/registry-<safe>` must be unaffected, and
    that name must still win — it is the more specific of the two."""
    other = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    monkeypatch.setattr(agent_spire, "_proxy_spiffe_id",
                        lambda: "spiffe://eu.theprotocol.cloud/service/registry-eu")
    spire({"spiffe://eu.theprotocol.cloud/service/registry-eu": other,
           "spiffe://eu.theprotocol.cloud/service/registry": LIVE}, [other, LIVE])
    assert agent_spire._autodetect_local_fingerprint() == other


# ── half 2: never hand back a node this frame does not have ───────────────────────────────

def test_the_hardcoded_fallback_is_refused_when_it_is_not_a_live_node(spire, monkeypatch):
    """The exact production state on EU: nothing auto-detectable, and Frame A's fingerprint is
    not one of this frame's nodes. Issuing anyway is what produced an unusable identity."""
    monkeypatch.setattr(agent_spire, "_proxy_spiffe_id",
                        lambda: "spiffe://eu.theprotocol.cloud/service/registry-eu")
    spire({}, [LIVE])                       # no own entry; the only live node is not Frame A's
    with pytest.raises(agent_spire.SpireParentUnresolved) as e:
        agent_spire._parent_fingerprint_for_self()
    msg = str(e.value)
    assert "live agent node" in msg
    # the refusal must be USEFUL to whoever reads it: cause, fix, and where the rules live
    assert "OPERATOR_SPIRE_AGENT_FINGERPRINT" in msg
    assert "docs.theprotocol.cloud/learn/security" in msg


def test_the_fallback_is_allowed_when_it_genuinely_IS_a_live_node(spire, monkeypatch):
    """The control that keeps Frame A working: on the frame the constant was written for, it is
    a live node and must still be returned."""
    monkeypatch.setattr(agent_spire, "_proxy_spiffe_id",
                        lambda: "spiffe://eu.theprotocol.cloud/service/registry-eu")
    spire({}, [FRAME_A])
    assert agent_spire._parent_fingerprint_for_self() == FRAME_A


def test_an_explicit_but_dead_fingerprint_is_also_refused(spire, monkeypatch):
    """The check lives at the ONE place every path passes through, so an env override or an
    explicit argument is checked too — a parent is a guess until it is checked, whoever guessed."""
    spire({}, [LIVE])
    with pytest.raises(agent_spire.SpireParentUnresolved):
        agent_spire.register_agent_spire_entry("did:theprotocol:eu:abc", fingerprint="dead" * 10)


def test_unknown_is_not_treated_as_empty(spire, monkeypatch):
    """⚠ THE THIRD STATE. If the node list cannot be read at all, that is UNKNOWN — and UNKNOWN
    must not become 'no live nodes, refuse everything', which would take enrollment down on any
    node without a docker socket. `live_agent_fingerprints()` returns None and the checks pass."""
    monkeypatch.setattr(agent_spire, "_LOCAL_SPIRE_AVAILABLE", False)
    assert agent_spire.live_agent_fingerprints() is None
    monkeypatch.setattr(agent_spire, "_proxy_spiffe_id",
                        lambda: "spiffe://eu.theprotocol.cloud/service/registry-eu")
    # unreadable list ⇒ no refusal from the liveness check
    assert agent_spire._parent_fingerprint_for_self() == FRAME_A
