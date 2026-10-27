"""§SHOWCASE-A — the two trust systems, pinned at the points where they were silently wrong.

Both defects were of the same kind: a mechanism implemented correctly and not wired at its ends.
Each test below FAILS against the pre-fix source, which is the only reason to keep it.
"""
import ast
import importlib
import math
import os
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


# ---------------------------------------------------------------------------------------------
# EigenTrust: the projection
# ---------------------------------------------------------------------------------------------

def _project(mode, gt_val, log_floor):
    """The engine's projector, exercised without importing numpy/sqlalchemy."""
    import agentvault_registry.services.eigentrust_engine as eng
    old = eng.PROJECTION_MODE
    eng.PROJECTION_MODE = mode
    try:
        return eng._project(gt_val, log_floor)
    finally:
        eng.PROJECTION_MODE = old


def test_linear_projection_is_byte_identical_to_the_old_behaviour():
    """The default must not move a single published number."""
    for v in (1.0, 0.4466, 0.0555, 1e-4, 3.88e-06, 7.55e-08, 0.0):
        assert _project("linear", v, 7.55e-08) == min(1000, int(v * 1000))


def test_the_linear_projection_is_why_four_thousand_agents_read_zero():
    """The control: this is the defect, stated as a passing assertion about the old behaviour.

    MEASURED on registry-a 2026-09-10 — the trust vector spans 7.1 orders of magnitude, and a
    linear x1000 integer can only carry the top three.
    """
    floor = 7.554842239741107e-08
    decades = [10.0 ** -k for k in range(0, 8)]
    zeros = [v for v in decades if _project("linear", v, floor) == 0]
    assert len(zeros) >= 4, "a linear projection should floor everything below 1e-3"


def test_log_projection_preserves_the_ordering_across_decades():
    floor = 7.554842239741107e-08
    vals = sorted([1.0, 0.4466, 0.0555, 1e-4, 3.88e-06, 1e-6, 1e-7], reverse=True)
    scores = [_project("log", v, floor) for v in vals]
    assert scores == sorted(scores, reverse=True), f"not monotonic: {list(zip(vals, scores))}"
    assert len(set(scores)) == len(scores), f"decades collapsed onto each other: {scores}"
    # and the agent the linear projection threw away now has a real position
    assert _project("linear", 3.88e-06, floor) == 0
    assert _project("log", 3.88e-06, floor) > 0


def test_log_projection_stays_inside_the_published_range():
    floor = 1e-9
    for v in (1.0, 0.5, 1e-3, 1e-6, 1e-9, 0.0, -1.0):
        s = _project("log", v, floor)
        assert 0 <= s <= 1000, f"{v} -> {s}"


def test_a_new_agent_is_seeded_the_same_way_in_both_places():
    """The two lookups of prev_vectors used DIFFERENT defaults twelve lines apart: 1/n when the
    power iteration seeded, 0.0 when the decay blended. A newcomer therefore kept 5 % of its
    computed trust while an established agent carried 95 % of its history."""
    src = (SRC / "services" / "eigentrust_engine.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_epoch")
    defaults = []
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and getattr(node.func.value, "id", "") == "prev_vectors"
                and len(node.args) == 2):
            defaults.append(ast.unparse(node.args[1]))
    assert len(defaults) == 2, f"expected two prev_vectors.get() sites, found {defaults}"
    assert defaults[0] == defaults[1], f"the same lookup still has two defaults: {defaults}"


def test_the_decay_is_tunable_without_editing_the_source():
    src = (SRC / "services" / "eigentrust_engine.py").read_text()
    assert "EIGENTRUST_EPOCH_DECAY" in src
    import agentvault_registry.services.eigentrust_engine as eng
    assert eng.EPOCH_DECAY == 0.95, "the default must reproduce today's behaviour exactly"


# ---------------------------------------------------------------------------------------------
# Bayesian peer trust
# ---------------------------------------------------------------------------------------------

def test_there_is_exactly_one_bayesian_formula():
    """federation_disputes carried `1 - lost/(total+PRIOR)` while the service carried a Beta
    point estimate, both writing peer.bayesian_discount. One model, one implementation."""
    disputes = (SRC / "routers" / "federation_disputes.py").read_text()
    assert "1.0 - (lost /" not in disputes, "the duplicate formula is back"
    assert "get_bayesian_trust_service" in disputes, "the dispute path must use the service"
    tree = ast.parse(disputes)
    writers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               for t in n.targets
               if isinstance(t, ast.Attribute) and t.attr == "bayesian_discount"]
    assert not writers, f"federation_disputes still writes the column directly: {len(writers)}"


def _code_only(fn: ast.AST) -> str:
    """A function's CODE with its docstring stripped.

    A source-reading gate finds its own documentation first — three times in one night, once
    on a comment inside an argument list. The prose beside a fix names the CLASS; only the
    statements say what the code does.
    """
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return "\n".join(ast.unparse(n) for n in body)


def test_every_cross_registry_settlement_path_records_an_observation():
    """🔴 THE LESSON THIS FILE EXISTS FOR, EARNED THREE TIMES IN ONE DAY.

    V0313 wired the observation into the SYNC cross-registry branch only. registry-a runs
    TEG_CROSS_FRAME_BACKEND=async, where the endpoint returns `locked` and the transfer settles
    later in reactor_cross_frame_settled — so a real transfer answered 200 `completed` and the
    peer row did not move. V0314 wired that branch too, and a real transfer STILL did not move
    the row: every frame pair on this network holds a different currency, so frame-to-frame
    money goes through the FX pool swap, which was the third sibling and was wired by neither.

    This COUNTS the settlement events one implementation covers, because what went wrong each
    time was a branch nobody widened. A fourth settlement event is one entry in REACTOR_CLASSES.
    """
    mod = importlib.import_module(
        "agentvault_registry.background_tasks.reactor_peer_trust_observed"
    )
    covered = {cls.event_type for cls in mod.REACTOR_CLASSES}
    assert covered == {
        "FxSwapSettled",                  # the FX pool swap — the ONLY path that runs between frames
        "CrossFrameTransferSettled",      # the async saga, at the locked -> settled flip
        "CrossRegistryTransferCompleted", # the sync same-currency path and each FX route hop
    }, f"a settlement path is uncovered: {covered}"

    # one leader key per channel, or one reactor silently steals another's lock
    keys = [cls.leader_key for cls in mod.REACTOR_CLASSES]
    assert len(set(keys)) == len(keys), keys

    # ...and ONE handler implementation behind all three, which is the whole point
    handlers = {cls.handle_event for cls in mod.REACTOR_CLASSES}
    assert len(handlers) == 1, "the three channels do not share one handler"


def test_the_hand_wired_call_sites_are_gone():
    """Three implementations of one observation is the defect, not the missing site. Once the
    reactor covers every settlement event, the two hand-wired sites must be DELETED — leaving
    them would double-count the paths they do reach."""
    teg = (SRC / "routers" / "teg_integration.py").read_text()
    reactor = (SRC / "background_tasks" / "reactor_cross_frame_settled.py").read_text()
    assert "_record_peer_trust_interaction" not in teg, "the sync call site is still wired"
    assert "record_interaction" not in reactor, "the async call site is still wired"
    # and nothing else may quietly grow a fourth one
    callers = sorted(
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if "record_interaction(" in p.read_text()
    )
    assert callers == [
        "background_tasks/reactor_peer_trust_observed.py",  # every settlement
        "routers/federation_disputes.py",                   # the negative half
        "services/bayesian_trust.py",                       # the model itself
    ], callers


def test_the_model_is_fed_from_a_settlement():
    """record_interaction() had NO caller anywhere: the Beta model had a decay half and no
    evidence half, so every peer read total_interactions=0 after days of live federation."""
    mod = importlib.import_module(
        "agentvault_registry.background_tasks.reactor_peer_trust_observed"
    )
    src = (SRC / "background_tasks" / "reactor_peer_trust_observed.py").read_text()
    assert "record_interaction" in src
    # recorded at SETTLED and never at initiated: a locked transfer can still refund, and an
    # observation of a success that did not happen is worse than no observation
    assert "success=True" in src
    assert "Initiated" not in {cls.event_type for cls in mod.REACTOR_CLASSES}


def test_a_bare_teg_layer_identifies_nobody():
    """🔴 MEASURED 2026-09-10: frame-b, frame-c, EU and ASIA all run LOCAL_TEG_ID=teg-layer, so
    four registries stamp the same `source_teg`. A resolver that treated it as a name would
    attribute every one of their settlements to whichever peer sorted first — the same string
    that once silently cross-frame mis-routed the FX sidecar map."""
    from agentvault_registry.background_tasks.reactor_peer_trust_observed import _peer_key_from_teg
    assert _peer_key_from_teg("teg-layer") is None
    assert _peer_key_from_teg("") is None
    assert _peer_key_from_teg(None) is None
    # both provisioner generations are live on this network, and both must resolve. §SUITES1018 (2026-10-18): in
    # the ONE key the TEG partner rule compares by (core/operator_names.peer_key, letters and digits only), so a frame
    # named "Sandbox Beta" and the TEG id its peers stamp, teg-layer-sandbox-beta, are one key (§FEDPROOF F2)
    assert _peer_key_from_teg("teg-layer-frame-b") == "frameb"
    assert _peer_key_from_teg("teg-layer-a") == "a"          # matches peer row "Registry-A"
    assert _peer_key_from_teg("teg-layer-op-berlin") == "opberlin"
    assert _peer_key_from_teg("teg-op-doha") == "opdoha"
    assert _peer_key_from_teg("teg-amsterdam") == "amsterdam"
    assert _peer_key_from_teg("teg-layer-asia") == "asia"
    assert _peer_key_from_teg("teg-layer-sandbox-beta") == "sandboxbeta"


def test_the_payload_shapes_are_the_ones_that_actually_arrive():
    """Every field name here was copied off a LIVE event, not off the emitter's signature: the
    FX emitter's keyword arguments are sender_did/receiver_did while the stored keys are
    from/to, and CrossRegistryTransferCompleted has a second, thinner shape that names no
    counterparty at all and must resolve to nothing rather than to a guess."""
    from agentvault_registry.background_tasks.reactor_peer_trust_observed import _sides

    sid, src, dst = _sides("FxSwapSettled", {
        "swap_id": "5f38979b", "dest_teg": "teg-layer-frame-b", "source_teg": "teg-layer-a",
        "dest_frame": "frame-b.theprotocol.cloud", "source_frame": "agentvault.com"})
    assert sid == "5f38979b" and src.key == "a" and dst.key == "frameb"
    assert src.frame == "agentvault.com" and dst.frame == "frame-b.theprotocol.cloud"

    sid, src, dst = _sides("CrossRegistryTransferCompleted", {
        "transfer_id": "21ac95bb", "source_teg": "teg-op-doha", "target_teg": "teg-layer"})
    assert sid == "21ac95bb" and src.key == "opdoha" and dst.key is None

    # the thin shape — {to, memo, transfer_id} and nothing else
    sid, src, dst = _sides("CrossRegistryTransferCompleted", {
        "transfer_id": "24e39904", "to": "did:theprotocol:533f9afe", "memo": "x"})
    assert sid == "24e39904" and not src and not dst

    sid, src, dst = _sides("CrossFrameTransferSettled", {
        "transfer_id": "b7fcb4d8", "source_frame": "agentvault.com",
        "target_frame": "agentvault.com"})
    assert sid == "b7fcb4d8" and src.frame == dst.frame == "agentvault.com"


def test_one_settlement_is_one_observation_however_many_events_announce_it():
    """The sync cross-frame path emits CrossRegistryTransferCompleted AND
    CrossFrameTransferSettled for the SAME transfer_id, and every settlement event is
    replicated to peers and arrives again with a different event id. The framework's own dedup
    ring keys on event_id and can see neither, so the claim is keyed on the SETTLEMENT."""
    src = (SRC / "background_tasks" / "reactor_peer_trust_observed.py").read_text()
    tree = ast.parse(src)
    claim = next(n for n in ast.walk(tree)
                 if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_claim")
    body = _code_only(claim)
    assert "settlement_id" in body and "peer_id" in body, "the claim is not per settlement+peer"
    assert "nx=True" in body, "the claim is not atomic"
    assert "event_id" not in body, "keying on event_id cannot dedup two event types"


def test_a_dropped_observation_is_not_reported_as_a_duplicate():
    """A three-state claim, not a bool. The first cut returned False both when the settlement was
    already counted and when the dedup store could not answer, and the caller then logged
    "already counted" about a Redis failure — an instrument stating a cause it had not
    established, in the one file whose whole subject is refusing to guess."""
    src = (SRC / "background_tasks" / "reactor_peer_trust_observed.py").read_text()
    tree = ast.parse(src)
    claim = next(n for n in ast.walk(tree)
                 if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_claim")
    # the states it can answer with — a ternary return is not an ast.Return constant, so walk
    # every string literal in the function rather than only the direct returns
    states = {n.value for n in ast.walk(claim)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert {"unavailable", "duplicate", "claimed"} <= states, \
        f"_claim cannot tell a dropped observation from a duplicate: {sorted(states)}"
    assert "dropped" in src, "a dropped observation has no state of its own"


def test_an_overheard_settlement_between_two_peers_is_not_our_observation():
    """These events replicate: a settlement between two OTHER registries lands here too. The
    reactor must be able to tell a settlement it took part in from one it merely overheard, so
    reactor_base marks foreign deliveries — on BOTH paths, because the WS bridge and the
    polling backstop each carried the emitting frame and each dropped it here."""
    base = (SRC / "background_tasks" / "reactor_base.py").read_text()
    assert '"_foreign_frame_id"' in base, "reactor_base does not mark foreign events"
    assert 'ev.get("frame_id")' in base, "the polling backstop still drops the emitting frame"
    # and NOT under `source_frame` inside data — FxSwapSettled already uses that key for the
    # swap's own source trust domain, and the two would collide
    assert '"source_frame": str(_foreign)' not in base

    reactor = (SRC / "background_tasks" / "reactor_peer_trust_observed.py").read_text()
    assert "_foreign_frame_id" in reactor
    assert "third_party" in reactor, "an overheard settlement is not distinguished"


def test_a_shared_trust_domain_is_not_an_identity():
    """🔴 A CLOUD OPERATOR SHARES ITS PARENT FRAME'S TRUST DOMAIN AND HAS NO EVENTSTORE OF ITS
    OWN. amsterdam's EVENT_STORE_URL is EU's ledger and its SPIRE_TRUST_DOMAIN is
    eu.theprotocol.cloud, so EU's settlements with ASIA arrive at amsterdam looking local and
    addressed to "our" trust domain. A `frame == our trust domain` test made amsterdam claim
    them, which would have published an interaction count for transfers it took no part in.

    The rule: a side the payload names specifically is us only if it names US; a side the payload
    does not name may be claimed only by a node the payload could not have named — the frames
    that stamp the bare `teg-layer`. An operator, always nameable by its own TEG id, never claims
    an unnamed side."""
    from agentvault_registry.background_tasks.reactor_peer_trust_observed import _Side
    import agentvault_registry.background_tasks.reactor_peer_trust_observed as mod

    unnamed = _Side("eu.theprotocol.cloud", "teg-layer")     # EU's own stamp
    named = _Side("eu.theprotocol.cloud", "teg-amsterdam")   # amsterdam's own stamp

    old = mod._local_teg_named_cache
    try:
        mod._local_teg_named_cache = True   # a node the payload COULD name (an operator)
        assert not unnamed.is_local("eu.theprotocol.cloud", {"amsterdam"}), \
            "an operator claimed a side stamped with its parent's bare teg id"
        assert named.is_local("eu.theprotocol.cloud", {"amsterdam"})
        mod._local_teg_named_cache = False  # a frame, which the bare stamp is the only name for
        assert unnamed.is_local("eu.theprotocol.cloud", {"eu"})
        # ...and even a frame does not claim a side the payload named as someone else
        assert not named.is_local("eu.theprotocol.cloud", {"eu"})
    finally:
        mod._local_teg_named_cache = old


def test_the_teg_less_channel_reads_our_own_rows():
    """CrossFrameTransferSettled names only trust domains, and every trust domain on this network
    is shared — registry-a sits in agentvault.com beside five operators, and those operators write
    to registry-a's EventStore. The payload cannot say which of them settled. Our own tables can:
    the sender holds the cross_frame_transfers row, the receiver the inbound row."""
    src = (SRC / "background_tasks" / "reactor_peer_trust_observed.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
              and n.name == "_crossframe_counterparty")
    body = _code_only(fn)
    assert "CrossFrameTransfer" in body and "CrossFrameTransferInbound" in body, \
        "both directions must be resolvable from our own records"
    assert "local_td" not in body and "trust_domain" not in body, \
        "the shared trust domain is back in the teg-less channel"
    # and the channel actually uses it
    handler = next(n for n in ast.walk(tree)
                   if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                   and n.name == "handle_event")
    assert "_crossframe_counterparty" in ast.unparse(handler)


def test_the_recorder_is_atomic():
    """🔴 A READ-MODIFY-WRITE WITH NO ROW LOCK LOSES CONCURRENT OBSERVATIONS, and
    total_interactions is PUBLISHED on the peer card. This was survivable only while nothing
    called record_interaction at all; routing every settlement through one reactor with
    handler_concurrency=50 makes the race real on the day it ships. Same defect, measured, in
    the TEG's reputation-signal rail: 9 of 764 concurrent signals lost, all answering 200."""
    src = (SRC / "services" / "bayesian_trust.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
              and n.name == "record_interaction")
    body = _code_only(fn)
    assert "total_interactions = COALESCE(total_interactions, 0) + 1" in body, \
        "the counter is not incremented in SQL"
    assert "RETURNING" in body, "the caller cannot see what it actually wrote"
    # the read-modify-write must be GONE, not merely accompanied
    assert "peer.total_interactions = " not in body, "the read-modify-write is back"
    assert "select(PeerRegistry)" not in body, "the row is still read before being written"
    # and the Beta formula still lives in exactly one place: the recorder writes the one derivation (SEC-20,
    # services/bayesian_trust.derived_trust, which starts from the Beta point estimate)
    assert "derived_trust(" in body, "the recorder does not write the one derivation"
    assert "PRIOR_ALPHA" not in body and "PRIOR_BETA" not in body, \
        "a second copy of the Beta formula has appeared in the recorder"


def test_an_unmeasured_peer_is_not_decayed():
    """Absence of instrumentation is not evidence of inactivity. A peer that has never had an
    interaction RECORDED must not have its published trust pulled toward 0.5."""
    src = (SRC / "services" / "bayesian_trust.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "run_decay_pass")
    body = ast.unparse(fn)
    assert "total_interactions" in body, "the decay does not consider whether anything was measured"
    assert "continue" in body, "the decay has no skip branch for an unmeasured peer"
    assert "skipped_uninstrumented" in body, "the skip is not counted, so it cannot be reported"


def test_the_decay_reports_what_it_withheld():
    """A filter that silently removes its whole population is indistinguishable from a worker
    that is not running (§DISCMIX)."""
    src = (SRC / "services" / "bayesian_trust.py").read_text()
    assert "UNMEASURED" in src
    assert "candidates" in src


def test_beta_point_estimate_is_unchanged():
    from agentvault_registry.services.bayesian_trust import BayesianTrustService
    svc = BayesianTrustService()
    assert svc._compute_discount(0, 0) == pytest.approx(0.5)
    assert svc._compute_discount(10, 0) == pytest.approx(11 / 12)
    # 10 interactions of which 10 were lost is all-bad evidence: alpha=1, beta=11.
    assert svc._compute_discount(10, 10) == pytest.approx(1 / 12)
    assert svc._compute_discount(0, 10) == pytest.approx(1 / 12)
    # and a half-and-half record lands back on the uninformative prior
    assert svc._compute_discount(10, 5) == pytest.approx(0.5)
