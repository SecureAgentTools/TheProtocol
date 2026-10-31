"""MCP tool contracts (phase 1 — 2026-05-25).

Per-MCP-tool declarative test contract. Phase 1 ships a DEFAULT_CONTRACT
that covers every tool surface-level, plus ~15 high-value contracts
that exercise tools whose past bugs (BUG-5/-9/-10/-15/-17/-22/-24) would
have been caught by contract-level assertions.

Future phases (per PLAN_2026-05-25_MCP_TESTER_REUSE_API_ENGINE.md):
  • Phase 2: write 50 contracts covering all Tier-2 financial + Tier-3
    dev-CRUD + critical admin destructive tools.
  • Phase 3: full coverage of all ~680 tools.

This module is imported eagerly by the flow_mcp_lifecycle test runner;
no decorator-based registration needed (kept simple for phase 1).

Architectural note:
  - HTTP api-tester's @Endpoint contracts live in core/contract.py.
  - MCP contracts intentionally use a separate, simpler dict-based
    registry because the dispatch is JSON-RPC (tools/call), not HTTP
    method+path, and tier-aware (Tier 0/1/2/3/admin instead of auth=
    none/agent/developer). Sharing the @Endpoint dataclass would force
    one or both shapes to compromise.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Literal, Optional
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD  # §SBROTATE



# §APITEST 2026-09-04 — venue symbol for the read-only AGORA tools.
import os as _os
_EXCHANGE_LISTING = _os.getenv("API_TEST_EXCHANGE_LISTING", "TUTCO")

# ---- Tier classification (mirrors mcp/auth_bridge.py + server.py TIER sets) ----

McpTier = Literal["0", "1", "2", "3", "admin"]


# ---- Contract object ----

@dataclass
class McpContract:
    """One contract per MCP tool. All fields optional except `tier`.

    The `arguments` template can reference fixture values via the
    ${fixture_name} pattern. Resolver substitutes them at runtime.

    `expect_keys` are keys that MUST appear in a successful response.
    Missing → fail. This is what would have caught BUG-9 (stake_id empty).

    `expect_status="success"` means the tool MUST NOT return a JSON-RPC
    error AND status must be 2xx.

    `expect_status="error_4xx"`/`error_5xx"` is ONLY allowed when paired
    with `expect_error_message_contains` (or `expect_error_keys`) so the
    tester verifies the error body — not just the status class. A bare
    `expect_status="error_4xx"` is doctrine-banned (2026-05-26 strict
    mode): "If a tool legitimately returns 4xx as its correct behavior,
    write that as a separate contract that passes only when 400 fires
    AND the error body matches an expected shape. But default behavior
    tests success." (handover HANDOVER_2026-05-26).

    `expect_status="error"` (§MCPTEST30, V0541) takes a 4xx OR a 5xx under the same rule: the body must name one of
    the expected refusals. It is for a route whose refusal depends on its subject's state, never a way to accept any
    failure: getRelayStatus refuses a sentinel by what its card declares (no address 404, an http one 422, an address
    that answers but not as a relay 502).

    `expect_types` maps each declared response field to its required
    Python type (or tuple of types). Catches "balance was an int, now
    it's a string" regressions cold.

    `side_effect_assert` is a callback `(inner_result, bag) -> bool`.
    Returns False → contract fails with reason "side_effect_assert".
    For mutations, side_effect_assert MUST verify the side effect via
    a read-back or EventStore event check (handover Part B.6).

    `skip_reason` records the tool as `skipped`, NOT `healthy`. Skips
    are surfaced as their own outcome category — never silently rolled
    into the pass rate. Banned: "tool not yet implemented",
    "expected failure", "sandbox state — ignore". Acceptable:
    "destructive cleanup deferred — covered by reset-sandbox",
    "needs fixture X — write contract once fixture lands".
    """
    tier: McpTier
    requires_fixtures: List[str] = field(default_factory=list)
    arguments: Dict[str, Any] = field(default_factory=dict)
    expect_keys: List[str] = field(default_factory=list)
    expect_types: Dict[str, Any] = field(default_factory=dict)
    expect_status: Literal["success", "error_4xx", "error_5xx", "error", "any"] = "success"
    # str, or a list/tuple of alternatives (any-of) — a tool can have more
    # than one legitimate documented 4xx depending on state the sweep creates.
    expect_error_message_contains: Optional[Any] = None
    expect_error_keys: List[str] = field(default_factory=list)
    side_effect_assert: Optional[Callable[[Dict[str, Any], "McpFixtureBag"], bool]] = None
    # ── Phase C bug-finder layer (2026-05-26 plan §PLAN_2026-05-25_MCP_TESTER_REUSE_API_ENGINE.md
    #    + §HANDOVER_2026-05-26_MCP_TESTER_PHASE_5_BUG_FINDER.md) ─────────────────
    # `expect_events` declares EventStore event_type values that MUST be emitted
    # within the post-call window (default 60s). The runner queries EventStore's
    # /events/recent endpoint; if ANY declared event is missing → fail with
    # "missing event: X". Catches BUG-10 class regressions (call returns 2xx
    # but no event landed → silent NO-OP).
    expect_events: List[str] = field(default_factory=list)
    # `expect_audit_row` (default True for mutations, False for reads) — when
    # True, after the call the runner queries security_audit_logs for a row
    # with target_type='mcp_tool' + target_id=<tool_name> + outcome='success'
    # created in the last 60s. Catches mcp_tool calls that bypass the audit
    # pipe (assertion class #4 from the Phase 5 handover).
    expect_audit_row: Optional[bool] = None
    # `expect_idempotent=True` triggers a second call with the same
    # Idempotency-Key header and asserts identical response. Catches §pass57
    # dedup regressions on financial endpoints.
    expect_idempotent: bool = False
    # ── Phase F.1 — Wrong-tier auth matrix (2026-05-26) ─────────────────
    # `expect_tier_rejections` lists wrong-tier credentials that MUST be
    # rejected with 401/403 when sent to this tool. Auto-populated from
    # `tier` by `_tier_to_rejections()` if left empty. Catches the bug class
    # where a Tier-2 endpoint accidentally accepts a Tier-1 caller — i.e. a
    # privilege-escalation regression. Override to skip checks (e.g.,
    # leave_empty=True) when a tool is legitimately reachable from
    # multiple tiers (notably authRegister and the few mcpPassthrough
    # tools that intentionally accept anonymous callers).
    expect_tier_rejections: List[str] = field(default_factory=list)
    # ── §FANCLAIM 2026-09-07 — "DO NOT CALL" AND "THIS IS NOT FULL COVERAGE" ARE
    # TWO DIFFERENT SENTENCES, AND `skip_reason` WAS CARRYING BOTH.
    # `skip_reason` means DO NOT CALL THIS TOOL — §MCPADMSKIP-3's gate enforces it
    # by refusing to let such a tool sit in a lifecycle call batch, which is what
    # stopped `adminAgoraDelistListing` being blind-swept. A tool that IS called,
    # deliberately, against a nonexistent target — so only its REFUSAL is measured —
    # needs the other sentence, and writing it as a `skip_reason` would both lie
    # ("do not call this", while a batch correctly does) and trip that gate.
    # This field says: the call is intended, the row is honest, and the SUCCESS path
    # is exercised by nothing. It downgrades the row to a declared skip in the
    # coverage fan; it never suppresses a call.
    success_path_unmeasured: Optional[str] = None
    # ── §EVTYPES8 2026-09-06 — THE WRONG-TIER PROBE IS STILL A REAL CALL ──
    # The auth matrix calls every tool with `{}` arguments and a wrong-tier
    # credential, on the stated assumption that "the auth gate fires before arg
    # validation". That assumption is exactly what the matrix exists to
    # FALSIFY — so for a tool that acts on the CALLER and needs no arguments,
    # `{}` is a complete, valid call, and the probe performs the thing the
    # moment the gate it is testing turns out to be open. Twenty-three
    # contracts already said in prose "not probed — would log the sweep out /
    # change its password / enable 2FA on its own account / tear down real
    # containers / recurse", and the matrix read `expect_tier_rejections` and
    # `tier` and ignored every one of those sentences: `skip_reason` stops the
    # SWEEP, never the matrix.
    #
    # Set this on a tool whose wrong-tier probe would be indistinguishable from
    # using it. The matrix then reports it as NOT PROBED, with the count and the
    # names in flow_values — coverage that is honestly missing beats coverage
    # whose safety depends on the property under test. Same class as a refusal
    # contract that becomes an action wherever the fixture happens to exist.
    #
    # MEASURED 2026-09-06 on sbx-alpha, so nobody reads more protection into this
    # than it gives: 23 contracts declare a self-acting or destructive call in
    # prose; the matrix runs over the PUBLIC tools/list only (435 of the 756
    # tools), so 8 of those 23 are genuinely probed today (all rejected —
    # violations 0), 5 admin-surface ones are excluded here, and the rest are
    # tier-1 (no wrong tier exists) or live only on /mcp/admin/rpc. **The admin
    # surface runs NO wrong-tier matrix at all** — on that surface this flag is a
    # declaration waiting for a consumer, not a guard that is currently doing
    # anything. Naming that beats leaving a reader to assume the teardown tools
    # are gate-tested and protected; they are neither.
    never_probe_wrong_tier: bool = False
    # ── Phase F.5 — Eventual consistency (2026-05-26) ─────────────────
    # When set, after a successful call the runner polls `consistency_check`
    # at 2-second intervals until either it returns None (consistent) or the
    # `expect_consistency_within` budget elapses (then fail). Useful for
    # cross-frame propagation (federation_sync), pull-sync, eigentrust epoch.
    # `consistency_check(bag) -> Optional[str]`: None means consistent;
    # str means "still inconsistent (here's why)".
    expect_consistency_within: Optional[int] = None
    consistency_check: Optional[Callable[["McpFixtureBag"], Optional[str]]] = None
    skip_reason: Optional[str] = None
    notes: Optional[str] = None
    # ── pass73.3.19 Option-A (2026-05-28) — coverage-fan precedence override ──
    # When True, this explicit success-contract is AUTHORITATIVE over any
    # coverage-fan / lifecycle outcome for the SAME tool: the runner skips the
    # fan's "any-status" probe result and runs THIS contract instead, so the
    # displayed status reflects the real success path (200) not the fan's
    # intentional-4xx reachability probe. Opt-in per tool — only set it on
    # self-contained reads whose args/keys are live-verified (no lifecycle
    # setup dependency), so flipping precedence can't regress a CRUD tool that
    # relies on its lifecycle for preconditions. See
    # [[feedback_mcp_tester_status_is_not_failure_signal]].
    override_coverage_fan: bool = False
    # ── §MCPTEST30 (2026-10-01) — what the run record may keep of the answer ──
    # True: the row's excerpt keeps the first five keys and each value's TYPE, never a value. For a read whose values
    # are configuration or personal records (getDiagnosticConfig's environment, an operator application): until this
    # existed such reads were left unmeasured on purpose, because the excerpt would have kept what they returned. The
    # credential census still scans the whole answer (it keeps a kind and a path, never a value).
    excerpt_shape_only: bool = False


# ── Phase F.1 — Tier-rejection auto-mapping ──────────────────────────────
# For each tier, which fake JWTs MUST be rejected with 401/403?
# Tier-0: getAgentToken — accepts no auth, must NOT auto-reject.
# Tier-1: public reads — no auth required; bypass.
# Tier-2: agent JWT — must reject {"empty", "developer_jwt"}.
# Tier-3: developer JWT — must reject {"empty", "agent_jwt"}.
# Tier-admin: must reject {"empty", "developer_jwt", "agent_jwt"} (any
# non-admin dev JWT).
_TIER_TO_REJECTIONS: Dict[str, List[str]] = {
    "0":      [],
    "1":      [],
    "2":      ["empty", "developer_jwt"],
    "3":      ["empty", "agent_jwt"],
    "admin":  ["empty", "agent_jwt", "developer_jwt_nonadmin"],
}

def auto_tier_rejections(tier: str) -> List[str]:
    """Map a tier label to the set of wrong-tier JWTs that MUST be rejected."""
    return list(_TIER_TO_REJECTIONS.get(str(tier), []))


# ---- Fixture bag passed to contracts at runtime ----

@dataclass
class McpFixtureBag:
    """Bundle of fresh credentials + flow values used by every contract.

    Populated once per test run by the flow_mcp_lifecycle runner from
    /admin/api-test/sandbox-credentials + /admin/api-test/flow-values.

    Same shape the HTTP api-tester already consumes — no parallel state.

    Phase-2 (2026-05-25): added `sentinel_agent_id` and `developer_id`
    fixtures so hand-curated read contracts can target the sandbox
    sentinel + sandbox admin without hard-coding IDs.
    """
    sentinel_did: str
    sentinel_jwt: str
    sentinel_agent_id: str = ""   # int as string — derived from agent JWT
    second_agent_did: str = ""
    second_agent_jwt: str = ""
    developer_jwt: str = ""
    developer_id: str = "1"       # admin@test.sandbox is developer #1
    admin_jwt: str = ""
    # §CLOUDOPMCP 2026-09-04 — the admin login pair as FIXTURES rather than a
    # literal baked into one contract. adminGetDeveloperToken hardcoded
    # admin@test.sandbox, which exists on the central sandbox and NOT on a cloud-op,
    # so the tool 401'd there and was counted a defect. Defaults are exactly the
    # previous literals, so the central sweep is unchanged; a cloud-op sweep passes
    # its own operator admin.
    admin_email: str = "admin@test.sandbox"
    admin_password: str = SANDBOX_ADMIN_PASSWORD
    # §CLOUDOPMCP 2026-09-04 — the AGORA listing the READ contracts query. It was a
    # module constant (_EXCHANGE_LISTING, from API_TEST_EXCHANGE_LISTING), so a
    # cloud-op sweep asked for the FRAME's listing and got 404 on all four reads.
    # A fixture with the constant as its default leaves the central sweep byte-
    # identical while letting each sweep name a listing that exists where it runs.
    exchange_listing: str = _EXCHANGE_LISTING
    # §pass73 task B (2026-05-26): genuine non-admin developer JWT minted at
    # bootstrap from the seeded `developer@test.sandbox` (is_admin=False per
    # test_seed.py TEST_DEVELOPER). Used by F.1 auth-matrix to verify
    # admin-tier endpoints reject a non-admin developer JWT. Pre-§pass73 this
    # fell back to the commander's admin JWT — making the rejection probe a
    # silent no-op. Empty string when the bootstrap login fails (logged); the
    # auth-matrix runner degrades to the "empty token" rejection check.
    developer_jwt_nonadmin: str = ""
    # §ADMINMATRIX-3 — a SECOND non-admin principal so the admin matrix does not
    # share a rate-limit bucket with the public one (the limiter keys on
    # PRINCIPAL, not role). Empty when the fixture is unavailable, which costs
    # coverage and not correctness.
    developer_jwt_nonadmin2: str = ""
    # §MCPTEST30 (2026-09-30) — WHERE `developer_jwt_nonadmin` CAME FROM, said on the run: the seeded fixture, or (when
    # its password is not on the tester frame, which was every night since §TESTBED) a throwaway developer the sweep
    # registered for this run. Empty means the matrix probed that slot with an empty bearer.
    nonadmin_source: str = ""
    # The throwaway principal behind `developer_jwt_nonadmin` ({email, password, ...}), so the teardown can have it ask
    # for its own deletion once the matrices are done with it. Never logged out or mutated during the run.
    nonadmin_principal: Dict[str, Any] = field(default_factory=dict)
    # A second throwaway developer, the SUBJECT of `lifecycle_self_account_on_throwaway` (2FA, password change,
    # logout, deletion request/cancel act on the caller's own account, so they run on an account the sweep owns and
    # never on the runner). {email, password, developer_id, access_token, refresh_token}, or {"why": ...} when the
    # target refused to make one.
    self_subject: Dict[str, Any] = field(default_factory=dict)
    # async (email, password) -> (http_code: str, body: dict): a developer login against the TARGET, the transport
    # the fixture phase itself uses. Injected by the runner (None on a bag built without one).
    dev_login: Optional[Callable[..., Any]] = None
    # Phase C bug-finder (2026-05-26): callable injected by the runner that
    # queries EventStore for recent events. Signature:
    #     async def event_verifier(event_types: List[str], tool_name: str)
    #                              -> Tuple[bool, Optional[str]]
    # Lifecycles pass `event_verifier=bag.event_verifier` to _exec_step
    # alongside `expect_events=[...]` to assert events landed in the
    # EventStore after a mutation. Catches BUG-10 silent NO-OP class.
    event_verifier: Optional[Callable[..., Any]] = None
    # §MCPTEST30 (2026-10-01): async (body, *, path, jwt, query, headers, timeout) -> (http_code, parsed, raw): one raw
    # JSON-RPC post to the target's MCP endpoint (any method, a notification, a batch, broken JSON). Injected by the runner.
    rpc_raw: Optional[Callable[..., Any]] = None
    # async (role) -> {email, password, developer_id, access_token, ...} or {"why": ...}: a developer the SWEEP owns,
    # registered for one lifecycle that must not touch a shared principal (toolset selections are keyed to the credential).
    mint_throwaway: Optional[Callable[..., Any]] = None
    # §MCPTEST30 (V0638): a throwaway agent's balance that earned_fixtures.Throwaways.close() could not return to the
    # treasury, one line per agent naming it and the amount (or that the balance could not be read). The runner's
    # summary carries the list; empty when every balance went back.
    throwaway_balances: List[str] = field(default_factory=list)
    flow_values: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        # First look in flow_values, then attribute lookup
        if key in self.flow_values:
            return self.flow_values[key]
        return getattr(self, key, default)


# ---- The fall-through default ----

DEFAULT_CONTRACT = McpContract(
    tier="1",
    expect_status="success",
    notes=(
        "Phase-1 fall-through. Treats the tool as Tier-1 (no auth, no args). "
        "Tools that require args or auth and have no explicit contract will "
        "fail loudly here, surfacing the gap."
    ),
)


# ---- Hand-picked phase-1 contracts (15 total) ----
#
# Selection bias: each one would have caught at least one bug from the
# 2026-05-25 E2E sweep, OR exercises a path no other contract covers.

MCP_CONTRACTS: Dict[str, McpContract] = {

    # ----- Tier 0: utility -----

    "theprotocol_getAgentToken": McpContract(
        tier="0",
        requires_fixtures=["sentinel_client_id", "sentinel_client_secret"],
        arguments={
            "client_id": "${sentinel_client_id}",
            "client_secret": "${sentinel_client_secret}",
        },
        expect_keys=["access_token", "token_type"],
        notes="Pre-flight: every other Tier-2 contract depends on this minting a JWT.",
    ),

    # ----- Tier 1: public reads -----

    "theprotocol_discoverAgents": McpContract(
        tier="1",
        arguments={"query": "test", "limit": 5},
        expect_keys=["agents"],
    ),
    "theprotocol_discoverRegistries": McpContract(tier="1", expect_keys=["registries"]),
    "theprotocol_getNetworkStats": McpContract(
        tier="1",
        expect_keys=["total_agents", "platform"],
    ),

    # ── Gateway meta-tools (L0/L1 2026-07-14) + L2 session pair ──────────
    # Without these, the walker would hit them with schema-generated junk:
    # the read-only trio gets real assertions; the proxy + session-mutating
    # pair are deliberate skips (each covered by scripts/mcp_ref_e2e.py).
    "theprotocol_listToolsets": McpContract(
        tier="1",
        expect_keys=["toolsets"],
    ),
    "theprotocol_searchTools": McpContract(
        tier="1",
        arguments={"query": "transfer tokens"},
        expect_keys=["results", "total_matches"],
    ),
    "theprotocol_describeTools": McpContract(
        tier="1",
        arguments={"names": ["getNetworkStats"]},
        expect_keys=["tools"],
    ),
    # (duplicate "theprotocol_invokeTool" removed §MCPTEST-MCP8 — a single
    #  authoritative definition now lives above; later-wins made two dangerous.)
    # (superseded by the §MCPTEST-MCP8 contract above — the old skip_reason
    #  contract was removed so later-wins cannot clobber it.)
    # (superseded by the §MCPTEST-MCP8 contract above — the old skip_reason
    #  contract was removed so later-wins cannot clobber it.)
    "theprotocol_getGovernanceProposals": McpContract(
        tier="1",
        arguments={"status": "VOTING", "limit": 5},
    ),
    "theprotocol_getFiatTiers": McpContract(tier="1", expect_keys=["tiers"]),

    # ----- Tier 2: agent-authed reads (would catch BUG-9, BUG-10, BUG-20) -----

    "theprotocol_getMyBalance": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["agent_did", "liquid_balance", "ve_token_power"],
        notes="Catches BUG-20 voting-power-disagreement if extended with cross-check.",
    ),
    "theprotocol_getMyLocks": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["positions"],
    ),

    # ----- Tier 3: developer reads -----

    "theprotocol_getAuthProfile": McpContract(
        tier="3",
        expect_keys=["id", "email", "is_admin"],
    ),
    "theprotocol_getMyDeveloperProfile": McpContract(
        tier="3",
        expect_keys=["id", "email"],
    ),
    "theprotocol_getMyFlareStatus": McpContract(
        tier="3",
        expect_keys=["flare_tier", "unlocked_corner_flares"],
    ),

    # ----- Admin: light reads (heavy/destructive admin deferred to phase 2) -----

    "theprotocol_getAdminDashboard": McpContract(tier="admin"),
    "theprotocol_getCloudOperators": McpContract(
        tier="admin",
        # §CLOUDOPCONTRACT 2026-09-07 — WAS skipped as "mainframe-only — sandbox is
        # not a mainframe", with a note prescribing an `error_5xx` + "not a mainframe"
        # pair. MEASURED on both node classes today, and the premise is stale rather
        # than the prescription wrong:
        #   frame sbx-alpha  → HTTP 200, {"operators": [{"name": "sbxalphaop", …}]}
        #   cloud operator   → the B6 envelope, status_code 503 + upstream_error,
        #                      detail "This feature runs on sovereign mainframes only"
        # The frames that replaced the RETIRED sandbox-A provision operators of their
        # own, so they ARE mainframes for this rail. The old skip was inherited from a
        # node that no longer exists — a fixture premise rots exactly like a fixture.
        # So: the real success path on a frame (this), and the operator side stays
        # handled by the sweep's live tier-gating, which keys on the measured 503
        # rather than on a name list.
        expect_keys=["operators"],
        notes="Measured 2026-09-07: 200 + `operators` on sbx-alpha (it provisions "
              "sbxalphaop); the 503 'sovereign mainframes only' path is the OPERATOR's, "
              "and the cloud-op sweep gates it from the live status, not from here.",
    ),
    "theprotocol_getReactorStatus": McpContract(tier="admin"),

    # ----- Skip-list: tools that need special setup or are destructive -----

    "theprotocol_authRegister": McpContract(
        tier="1",
        skip_reason="Creates a new developer row — leaves DB debris. Cover in destructive bucket.",
    ),
    "theprotocol_createAgent": McpContract(
        tier="3",
        skip_reason="Creates a new agent — covered by /admin/api-test/sandbox-credentials reset.",
    ),
    "theprotocol_transferUnits": McpContract(
        tier="2",
        arguments={"recipient_did": "did:theprotocol:00000000-0000-4000-8000-000000000000",
                   "amount": "1", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found on this registry or any federated peer"],
        notes=(
            "§EVTYPES8 2026-09-06 — WAS a skip reading 'Phase 2 — will move 1 AVT "
            "sentinel→second_agent + assert TokensTransferred lands in EventStore'. "
            "That is a LIFECYCLE's job (fund, move, poll the ledger) and no contract "
            "can do it in one call, so the row was never going to stop being a TODO "
            "on the strength of this file. §FEDPROOF 2026-09-13: that lifecycle now exists "
            "(mcp_lifecycles.lifecycle_transfer_settlement: 0.01 sentinel -> second agent, "
            "balance read-back, TokensTransferred) and its row displaces this pin when it runs. "
            "What a contract CAN do is pin the refusal, "
            "and this one writes nothing: a recipient that does not exist. "
            "MEASURED on the frame AND on a cloud operator, identical both times: "
            "404 'Recipient agent <did> not found on this registry or any federated "
            "peer.' The phrase starts after the DID on purpose — the id is minted "
            "per run, the sentence around it is not. "
            "⚠ The success path stays uncovered, and that is the honest gap: it needs "
            "the lifecycle the old note described, not a second contract. "
            "⚠⚠ 'WRITES NOTHING' IS TRUE OF THE FRAME AND CONDITIONALLY TRUE OF AN "
            "OPERATOR — the two 404s are identical and the side effects were not. An "
            "operator holds no reserves, so an unresolvable recipient is treated as "
            "possibly-remote and leaves through its parent's @fx_router: on 2026-09-07 "
            "00:47 this row ingressed 1 SBXA to the gateway, which emitted FxRouteRefunded "
            "claiming a 0.995 refund hop, moved nothing back and wrote no dead-letter row "
            "(§FXSTRAND, AgentVault 624b23e — closed by 895dfb4). Re-driven on the fixed "
            "image: 404, sender 5 → 5, @fx_router unchanged, no row. So the contract is "
            "sound again, and the reason it is sound is a PRODUCT fix, not a property of "
            "the call — a refusal that routes before it refuses can spend, and a status "
            "code cannot tell you which kind you have."
        ),
    ),
    "theprotocol_lockUnits": McpContract(
        tier="2",
        arguments={"amount": "1", "lock_period_days": 7, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["Minimum lock amount is"],
        notes=(
            "§EVTYPES8 2026-09-06 — WAS a skip reading 'Phase 2 — will stake 10 AVT "
            "lock=7d and assert stake_id / lockPeriod / cleanup unstake', i.e. a "
            "three-step lifecycle no single contract can perform. Pinned instead at "
            "the one refusal that is deterministic and writes nothing: BELOW the "
            "minimum. MEASURED identically on the frame and a cloud operator — "
            "400 'Minimum lock amount is 10.0 SBXA' (V0643's words). The phrase stops before the "
            "number AND the ticker, because the ticker is the FRAME'S CURRENCY "
            "(SBXA here, AVT on Frame A, BVT on frame-c) and pinning it would fail "
            "on every other frame. "
            "⚠ AND THE PROBE FOUND A PRODUCT DEFECT ON THE WAY, filed in the "
            "handover rather than contracted around: staking MORE than the balance "
            "answers HTTP 500 'Failed to process the lock request' (V0643's words), not a 4xx — "
            "measured at 100,000 (a sane number, simply over balance) and at "
            "999999999999, identically on both node classes. An insufficient balance "
            "is user input, and user input must not surface as an internal error. "
            "This contract deliberately does NOT pin that 500: a contract that "
            "expects a 500 would go red the day it is fixed, which is backwards."
        ),
    ),

    # ========================================================================
    # Phase-2 batch (2026-05-25 evening): hand-curated reads for tools that
    # the autogen pattern incorrectly marked as destructive OR that need
    # fixture mapping the autogen couldn't provide.
    # Each entry overrides the autogen-skip + actively probes the route.
    # ========================================================================

    # --- Tier 1 reads (mis-classified as destructive — actually read-only) ---

    "theprotocol_getLockPayoutTiers": McpContract(
        tier="1",
        notes="Phase-2: APY rates (no args) — pattern matched 'rate' substring.",
    ),
    "theprotocol_getAttestationHealth": McpContract(
        tier="1",
        notes="Phase-2: attestation subsystem health probe.",
    ),
    "theprotocol_getAttestationSigningPubkey": McpContract(
        tier="1",
        notes="Phase-2: attestation signing key — pubkey only.",
    ),
    "theprotocol_getFeeCurrentRate": McpContract(
        tier="1",
        notes="Phase-2: current TEG fee rate — pure read.",
    ),
    "theprotocol_getCommunityAnnouncements": McpContract(
        tier="3",
        expect_keys=["announcements", "total"],
        notes="Phase-2: the community page's feed. pass73.3.19: handler wraps "
              "to {announcements,total} — prior phantom 'body' key was stale. §MCPTEST30 V0538: Tier 3 (the route "
              "authenticates a developer; the tool sent no token and read the 401 as an empty feed, which passed).",
    ),

    # ========================================================================
    # pass73.3.19 (2026-05-28) — AUTH cluster 4xx fix batch.
    # These public auth endpoints were landing in the lenient "4xx accepted
    # as pass" bucket. Per strict-mode doctrine (lines 50-57): supply valid
    # args for a real 2xx, OR assert the 4xx is CORRECT behavior with an
    # error-body match. Done both ways below.
    # ------------------------------------------------------------------------
    # (a) Idempotent public endpoints — succeed (200) with a benign email.
    #     They return the same "if registered…" message regardless, so no
    #     account-enumeration side effect + no DB mutation for an unknown email.
    "theprotocol_authForgotPassword": McpContract(
        tier="1",
        arguments={"email": "nonexistent-sweep@test.sandbox"},
        expect_keys=["message"],
        notes="pass73.3.19: 200 idempotent — 'if that email is registered…'.",
    ),
    "theprotocol_authResendVerification": McpContract(
        tier="1",
        arguments={"email": "nonexistent-sweep@test.sandbox"},
        expect_keys=["message"],
        notes="pass73.3.19: 200 idempotent — 'if registered and unverified…'.",
    ),
    # (b) Token/key validators — a fake token MUST be rejected. Asserting
    #     the 4xx + error-body match is the doctrine-correct contract (a
    #     token-validator that 200s on a bogus token would be a real bug).
    "theprotocol_authResetPassword": McpContract(
        tier="1",
        arguments={"token": "sweep-invalid-token", "new_password": "Xx12345678!"},
        expect_status="error_4xx",
        expect_error_message_contains=["authResetPassword returned HTTP"],
        notes="pass73.3.19: bogus reset token correctly rejected with 400.",
    ),
    "theprotocol_authSetNewPassword": McpContract(
        tier="1",
        arguments={"token": "sweep-invalid-token", "new_password": "Xx12345678!"},
        expect_status="error_4xx",
        expect_error_message_contains=["authSetNewPassword returned HTTP"],
        notes="pass73.3.19: bogus set-new-password token correctly rejected (401).",
    ),
    "theprotocol_authValidate2FA": McpContract(
        tier="1",
        arguments={"login_token": "sweep-invalid", "code": "000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["authValidate2FA returned HTTP"],
        notes="pass73.3.19: bogus 2FA login_token+code correctly rejected.",
    ),
    "theprotocol_authRecover2FA": McpContract(
        tier="1",
        arguments={"login_token": "sweep-invalid", "backup_code": "sweep-invalid"},
        expect_status="error_4xx",
        expect_error_message_contains=["authRecover2FA returned HTTP"],
        notes="pass73.3.19: bogus 2FA recovery correctly rejected.",
    ),
    "theprotocol_authRecoverAccount": McpContract(
        tier="1",
        arguments={"email": "sweep-invalid@theprotocol.cloud", "recovery_key": "sweep-invalid-recovery-key"},
        expect_status="error_4xx",
        expect_error_message_contains=["authRecoverAccount returned HTTP"],
        notes="pass73.3.19: bogus recovery_key correctly rejected. §MCPSWEEP V0464: the tool now sends what its route requires; measured live on sbx-alpha 2026-09-27. (400 'Invalid email or recovery key.')",
    ),

    # ------------------------------------------------------------------------
    # pass73.3.19 (2026-05-28) — ZKP circuit reads. These need a circuit_id;
    # the sweep called them with none → 400/401. The 4 protocol circuits are
    # STATIC + deterministic (shipped with the image), so a hardcoded id is
    # stable. §ZKV2: fairMarkupPolicy/v2.0.0, whose bytecode (circuit.json),
    # source and Nargo.toml are tracked; v1.0.0 is retired and its bytecode is
    # not in a clean checkout.
    "theprotocol_getCircuitACIR": McpContract(
        tier="1",
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0"},
        expect_keys=["circuit_id", "content_type"],
        notes="pass73.3.19: static protocol circuit ACIR read.",
    ),
    "theprotocol_getCircuitSource": McpContract(
        tier="1",
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0"},
        expect_keys=["circuit_id", "source"],
        notes="pass73.3.19: static protocol circuit source read.",
    ),
    "theprotocol_getCircuitNargoToml": McpContract(
        tier="1",
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0"},
        expect_keys=["circuit_id", "nargo_toml"],
        notes="pass73.3.19: static protocol circuit Nargo.toml read.",
    ),
    "theprotocol_getCircuitVerificationKey": McpContract(
        tier="1",
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0"},
        expect_keys=["circuit_id", "verification_key_b64", "sha256"],
        notes="§ZKV2: the public verification key, for offline bb verify.",
    ),
    "theprotocol_getCircuitMetadata": McpContract(
        tier="1",
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0"},
        expect_keys=["circuit_id", "metadata"],
        notes="§ZKV2: statement, inputs, outputs and the policy limits in force.",
    ),
    # pass73.3.19 (2026-05-28) — exportTegTransactions is a READ (export),
    # not destructive — autogen mis-skipped it. Works with no args → 200
    # {format,total,transactions,filters,source}.
    "theprotocol_exportTegTransactions": McpContract(
        tier="3",
        expect_keys=["transactions", "total"],
        notes="pass73.3.19: dev tx export — read-only, was mis-skipped as destructive.",
    ),

    # ── pass73.3.19 4xx-reduction batch (2026-05-28) ─────────────────────
    # Each verified by live curl-probe against the v42 container: was 4xx
    # (missing/rejected arg or wrong server), now returns real 200 with the
    # supplied valid arg / fixture / no-arg. Replaces the autogen error_4xx
    # rubber-stamp with a genuine success-path assertion.
    "theprotocol_getArenaLeaderboard": McpContract(
        tier="1",
        arguments={"game_type": "robowars"},
        expect_keys=["game_type", "leaderboard"],
        notes="pass73.3.19: was 400 (missing game_type). Static 'robowars' → 200.",
    ),
    "theprotocol_getAgentCardById": McpContract(
        tier="1",
        requires_fixtures=["sample_card_id"],
        arguments={"card_id": "${sample_card_id}"},
        expect_keys=["id", "name", "is_active"],
        notes="pass73.3.19: was 400 (missing card_id). sample_card_id fixture "
              "(phase-3, from listAgentCards) → 200. Skips if no cards exist.",
    ),
    "theprotocol_getAgentCardByHRI": McpContract(
        tier="1",
        requires_fixtures=["sample_card_hri"],
        # §MCPTEST30 (2026-09-30): the coverage fan's invalid-input probe shadowed this contract, so every night
        # the row read NOT MEASURED ("REFUSED (HTTP 404)") although the fixture above is published by phase 3.
        # The real fixture now decides the row; an unresolved fixture still skips, and says so.
        override_coverage_fan=True,
        arguments={"human_readable_id": "${sample_card_hri}"},
        expect_keys=["id", "name"],
        notes=(
            "§EVTYPES8 2026-09-06 — FLIPPED, on the condition the old note set: the "
            "node now carries the route fix, so the tool succeeds. MEASURED on this "
            "image, both node classes: the operator answers 200 with a real card, and "
            "a nonexistent hri on the FRAME answers 404 whose body is the by-hri "
            "handler's own wording ('Agent Card with humanReadableId ... not found') "
            "— which is the proof the old note asked for, in reverse: the catch-all "
            "is no longer eating the literal 'by-hri'. The old phrase ('Agent Card "
            "not found', the catch-all's wording) can therefore never match again. "
            "⚠ On a frame with no HRI-bearing card the row is a FIXTURE question, "
            "not a product one — see the handover: `sample_card_hri` came back None "
            "in flow_values while the row still ran, which is the empty-string-is-not-"
            "unresolved class. Assert the success shape here and let the fixture "
            "machinery skip where there is nothing to look up. "
            "The superseded §EVTYPES5 reasoning, kept because it is the measurement "
            "that earned the fix: THIS TOOL COULD NOT SUCCEED ON ANY NODE, because "
            "now says so instead of asking for a 200 it will never get. The tool "
            "calls GET /api/v1/agent-cards/by-hri, and that route is REGISTERED "
            "AFTER GET /{card_id} in routers/agent_cards.py (1465 vs 1498). "
            "FastAPI matches in registration order, and `card_id` was widened "
            "from uuid.UUID to str to accept 'multiple formats', so the literal "
            "'by-hri' is happily taken as a card id and 404s. PROVEN by the "
            "MESSAGE, not the status: the body says 'Agent Card not found' (the "
            "/{card_id} handler's wording) and never 'Agent Card with "
            "humanReadableId ... not found' (the by-hri handler's), on a "
            "mainframe AND an operator, with a REAL hri that the sibling "
            "getAgentCardByHumanReadableId resolves to a 200 in the same breath. "
            "Both wrappers end in the same CRUD call, so this is purely the route "
            "table. The file already knows this class — see the comment at "
            "agent_cards.py:792, 'Registered BEFORE the /{card_id} route', "
            "applied to a different route and missed here. Product fix is moving "
            "one decorator; when it lands this row goes RED and carries this note "
            "with it, which is the point. "
            "⚠ THE FIX IS ALREADY IN THE TREE (agentvault2-60, riding V0225: the "
            "by-hri block registers before the catch-all, pinned by "
            "tests/test_agent_cards_route_order.py). So the first node this suite "
            "runs against that carries V0225 turns this row red, and the edit is "
            "one line: drop expect_status/expect_error_message_contains, put "
            "expect_keys=['id', 'name'] back — the same assertion its sibling "
            "getAgentCardByHumanReadableId already makes. Do NOT flip it before "
            "the node is on that image; today the 404 is the true reading."
        ),
    ),
    "theprotocol_getAgentCardByHumanReadableId": McpContract(
        tier="1",
        requires_fixtures=["sample_card_hri"],
        arguments={"human_readable_id": "${sample_card_hri}"},
        expect_keys=["id", "name"],
        notes="pass73.3.19: was 400 (missing human_readable_id). sample_card_hri "
              "fixture (phase-3) → 200.",
    ),
    "theprotocol_getAdminRegistryCard": McpContract(
        tier="admin",
        expect_keys=["registry_card_version", "identity"],
        notes="pass73.3.19: was 400 — admin tool; no-arg returns this registry's "
              "card v0.3 → 200.",
    ),
    "theprotocol_getOperatorLifecycle": McpContract(
        tier="admin",
        expect_keys=["registry_name", "is_local"],
        notes="pass73.3.19: was 400 — no-arg returns the local registry's operator "
              "lifecycle (self_hosted) → 200.",
    ),
    # (duplicate "theprotocol_getDiagnosticConfig" removed §MCPTEST-MCP8 — a single
    #  authoritative definition now lives above; later-wins made two dangerous.)
    "theprotocol_getAdminMcpAuditLogByActor": McpContract(
        tier="admin",
        arguments={"actor_id": "1"},
        expect_keys=["rows", "queried_actor_id"],
        notes="pass73.3.19: was 400 (missing actor_id). actor_id='1' (sandbox admin "
              "developer) → 200 audit rows.",
    ),
    "theprotocol_getHealthCheckWithAgentAuth": McpContract(
        tier="admin",
        expect_keys=["overallStatus", "results"],
        notes="pass73.3.19: was 400 — admin health tool; no-arg → 200 (composite "
              "health w/ authentication_used).",
    ),
    "theprotocol_getEventsAggregate": McpContract(
        tier="admin",
        requires_fixtures=["sentinel_did"],
        arguments={"aggregate_id": "${sentinel_did}"},
        expect_keys=["events", "count"],
        notes="pass73.3.19: was 400 (missing aggregate_id). sentinel DID is a real "
              "ES aggregate (AgentCreated etc.) → 200.",
    ),
    "theprotocol_getAgentCardDriftDetail": McpContract(
        tier="admin",
        requires_fixtures=["sentinel_did"],
        arguments={"did": "${sentinel_did}"},
        expect_keys=["agent_did", "stored"],
        notes="pass73.3.19: was 400 (missing did). sentinel DID → 200 drift detail.",
    ),
    # §CLOUDOPMCP 2026-09-04 — had NO contract, so the default sent no args and the
    # tool answered its own "agent_did is required" (mcp/tools_admin.py:1070-1073).
    "theprotocol_getEnforcementAgentStatus": McpContract(
        tier="admin",
        requires_fixtures=["sentinel_did"],
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_adminGetDeveloperToken": McpContract(
        tier="admin",
        arguments={"email": "${admin_email}", "password": "${admin_password}"},
        expect_keys=["access_token", "token_type"],
        notes="pass73.3.19: was 400 (missing email+password). Stable sandbox admin "
              "creds (test_seed; password un-rotatable per change-password guard) → "
              "200 minted dev token. Sandbox-only — never use real creds here.",
    ),
    # pass73.3.19 — operator-portal self-service tools are cloud-op-only; on a
    # mainframe (registry-test) they CORRECTLY return 503 with a "cloud-ops only"
    # guard. Contract that as the expected outcome so the new wrapped-error 5xx
    # rule doesn't false-fail an intentional guard — displays honest 503-healthy.
    # ══ §MCPTEST-MCP10c — the 8 "add explicit contract" skips. EVERY entry below
    # was executed BY HAND against sandbox-A first and encodes the response that
    # was actually observed, not a guess. Probing found three things a blind
    # contract would have got wrong: getContractV2 / instantiateContractTemplate /
    # runForgeEval are TIER 2 (agent JWT), not tier 3; runForgeEval's suite_id is
    # an INT (a string yields "invalid literal for int()"); and
    # guildCrossRegistryBid validates `price` before anything else.
    # A skip costs pass_pct exactly like a failure, so these are worth having —
    # but a wrong contract turns a skip into a FAILURE, which is worse.
    "theprotocol_getContractV2": McpContract(
        tier="2",
        # §EVTYPES 2026-09-05: was `ctr_l00000231`, described as "a real, long-lived
        # contract row on sandbox-A (251 exist)". That row belonged to the RETIRED
        # sandbox tier; on the frames that replaced it the id does not exist and the
        # suite has been reporting a CORRECT 404 as a failure ever since. A fixture
        # carrying an id from another environment rots by construction.
        # `${contract_v2_id}` is harvested per run in phase-3 setup AND verified there
        # (the v2 detail route enforces a party check, so an unverified id only swaps
        # the 404 for a 403). No verified candidate ⇒ the fixture stays unresolved and
        # this contract auto-skips, which is the honest outcome on a frame with none.
        arguments={"contract_id": "${contract_v2_id}", "agent_jwt": "${sentinel_jwt}"},
        expect_keys=["client_did", "contract_type", "currency", "created_at"],
        notes="EVTYPES: id harvested + verified at setup; skips cleanly when the "
              "frame has no contract the sentinel may read.",
    ),
    "theprotocol_instantiateContractTemplate": McpContract(
        tier="2",
        arguments={"template_id": "tpl_nonexistent", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["instantiateContractTemplate returned HTTP"],
        notes="MCP10c: sandbox-A has ZERO contract_templates, so there is no happy "
              "path to assert. This exercises auth + routing + the lookup and "
              "pins the 404 — honest coverage of the only reachable outcome.",
    ),
    "theprotocol_runForgeEval": McpContract(
        tier="2",
        arguments={"suite_id": 1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["forge/evals/run returned HTTP"],
        notes="MCP10c: probed → 403 (forge eval gated on sandbox). suite_id must be "
              "an INT — 'default' raised invalid literal for int().",
    ),
    "theprotocol_engageAgent": McpContract(
        tier="2",
        arguments={"provider_did": "${second_agent_did}", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        # §MCPTEST-MCP10d — accept EITHER. I probed with a throwaway agent's own
        # DID and got 400; the sweep passes ${second_agent_did} and gets 404.
        # I verified against a different subject than the contract references —
        # the probe was right about the tool and wrong about the fixture. Both
        # are correct refusals of an engagement (no terms on the card / provider
        # not resolvable), so pin the CLASS, not the accident of which fixture.
        expect_error_message_contains=["engageAgent returned HTTP"],
        notes="MCP10c/d: probed → 400 with a fresh agent, 404 with the sweep fixture. "
              "engageAgent mints a private contract OFFER from "
              "the provider card's engagement terms; a fixture agent carries none, "
              "so 400 is the correct answer and no escrow is created.",
    ),
    "theprotocol_guildCrossRegistryBid": McpContract(
        tier="2",
        arguments={"target_registry_url": "http://registry-test-b:8000",
                   "order_id": "1", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains="price is required",
        notes="MCP10c: probed → 'price is required for bid'. Deliberately asserts the "
              "VALIDATION gate rather than firing a real cross-registry bid at "
              "sandbox-B, which would need a live order id on the PEER.",
    ),
    "theprotocol_oauthRevoke": McpContract(
        tier="3",
        arguments={"client_id": "probe", "client_secret": "probe", "token": "nope"},
        # §EVTYPES 2026-09-05: was error_4xx / "Invalid client credentials", probed on a
        # tier that HAD active OAuth federation trusts. On a frame with none the rail
        # answers 501 "Cross-registry OAuth federation is not enabled on this registry
        # (no active trusted registries configured)" BEFORE it looks at the creds at all
        # — a deliberate guard, the same family as operatorPortalSelfLogs' "cloud-ops only"
        # (503, 404 from V0640) already contracted below as error. Pinning the credential
        # rejection made the suite report a working guard as a failure. Classify by the
        # SENTENCE, never the status alone.
        expect_status="error_5xx",
        expect_error_message_contains="OAuth federation is not enabled",
        notes="EVTYPES: 501 is the no-trusts guard on this frame. Where trusts DO exist "
              "the rail rejects bad creds first (401), so this contract is "
              "environment-shaped, not a universal truth.",
    ),
    "theprotocol_getOperatorMyLifecycle": McpContract(
        tier="3",
        # §EVTYPES 2026-09-05: the autogen contract expects success, but the sweep runs as
        # a FRESH developer that owns no operator application, and the rail correctly
        # answers 404 "No operator application found for this developer account". Probed
        # as a developer that DOES own one: 200 with the application body — so the rail is
        # right and the CALLER is what differs. Hand-curated beats autogen.
        expect_status="error_4xx",
        expect_error_message_contains="No operator application found",
        notes="EVTYPES: 404 is correct for a developer with no operator application; the "
              "sweep's developer never has one.",
        success_path_unmeasured="read on the parent frame by the operator's applicant: the federation suite measures it there (V0641: its row, earned_agent_public.NOT_DRIVEN)",
    ),
    "theprotocol_operatorPortalSelfLogs": McpContract(
        tier="3",
        expect_status="error",
        expect_error_message_contains="cloud-ops only",
        notes="pass73.3.19: 'cloud-ops only' is the correct mainframe guard: 503 up to V0639, 404 \"operator_only: "
              "<the same sentence>\" from V0640 (D6-820). Either class, judged by the sentence, so the pin reads both "
              "while frames and operators run mixed versions (tests/test_gate_refusal_both_forms.py).",
    ),
    "theprotocol_operatorPortalSelfRestart": McpContract(
        tier="3",
        skip_reason=(
            "never invoked by tester — DESTRUCTIVE: proxies to the mainframe with "
            "this operator's own licence and really restarts the operator."
        ),
        notes="§CLOUDOPMCP2 2026-09-05: was contracted to expect the mainframe's 503 "
              "'cloud-ops only' guard (pass73.3.19, when only the mainframe sweep "
              "existed). That is the right answer on a mainframe and the WRONG one on "
              "a cloud-op, where the tool works — and the cloud-op sweep, first run "
              "2026-09-05, invoked it for real: MEASURED [CLOUD-OP-RESTART] sbxalphaop "
              "duration=11148ms, after which the admin tools/list answered 000 and 319 "
              "admin tools went unswept (756 -> 435). It was harmless before only "
              "because the mainframe URL was unresolvable, so every call 502'd; "
              "repairing that rail armed it. Its own MCP schema says DESTRUCTIVE, and "
              "its mainframe-side twin theprotocol_cloudOperatorSelfRestart was "
              "already in the never-invoke set. A contract-level skip covers EVERY "
              "sweep; a set in one sweep would not have.",
        # §EVTYPES8: an open admin/tier gate here would not answer 401 — it would
        # run this. Excluded from the wrong-tier matrix, and named in
        # flow_values.auth_matrix_not_probed so the gap is visible, not assumed.
        never_probe_wrong_tier=True,
    ),
    "theprotocol_getAchievementCatalog": McpContract(
        tier="1",
        notes="Phase-2: static achievement catalog — no auth, no args.",
    ),
    "theprotocol_getAuthRegistrationConfig": McpContract(
        tier="1",
        notes="Phase-2: registration policy (open/closed, invite-required, etc.).",
    ),
    "theprotocol_getAutoTallyConfig": McpContract(
        tier="1",
        notes="Phase-2: governance auto-tally configuration.",
    ),
    "theprotocol_getRelayStatus": McpContract(
        tier="3",
        requires_fixtures=["sentinel_did"],
        arguments={"agent_did": "${sentinel_did}"},
        # §pass73.3.19 recorded the mismatch (an agent-tier wrapper at the developer-auth relay proxy: every call a 401)
        # and pinned it as documented. §MCPTEST30 V0538 fixed the TOOL (Tier 3), and assumed the sentinel declares no
        # relay (404). Round 11, the first run to reach the route, measured the sentinel's card: a frame's onboarding
        # gives it http://localhost:8100/agents/<name> (the SSRF guard's 422), an operator's its own public page
        # https://<operator>/agents/<name>, which answers the relay path with a 404 body (a 502 since V0541; it read
        # as a relay answering {} with 200). Each is the route refusing an agent with no relay, and says why.
        expect_status="error",
        expect_error_message_contains=["No relay configured for this agent", "Agent endpoint must be https",
                                       "The agent's address answered, but not as a relay"],
        success_path_unmeasured="the sentinel runs no relay; a relay's status needs an agent that runs one",
        # §MCPTEST30 (V0641): no longer pinned, so earned_agent_public's NOT_DRIVEN row reaches the run; its refusal is a
        # refusal row there
    ),
    "theprotocol_getReputationComputationStatus": McpContract(
        tier="1",
        notes="Phase-2: reputation engine status.",
    ),
    "theprotocol_getRevokedIdentities": McpContract(
        tier="2",   # agent JWT
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getSpireJWKS": McpContract(
        tier="1",
        notes="Phase-2: SPIRE JWKS endpoint.",
    ),
    "theprotocol_getStackHealth": McpContract(
        tier="1",
        notes="Phase-2: aggregate stack health.",
    ),
    "theprotocol_getLockPayoutTiersTeg": McpContract(
        tier="1",
        notes="Phase-2: APY tier table (matches 'tier' substring but is read-only).",
    ),
    "theprotocol_getLockPayoutRecords": McpContract(
        tier="3",
        # §MCPTEST30 (V0545): was a standing skip ("needs a known distribution_id fixture"). The id is a read-only pick
        # of a distribution the target already ran (staking_distribution_pick, both sweeps); none ran: the fixture
        # stays unresolved and the row skips as missing, which is what it is.
        requires_fixtures=["distribution_id"],
        arguments={"distribution_id": "${distribution_id}"},
        # V0546: the tool answers {"records": [...], "total": n} (it passed the route's bare list, which no contract could
        # state: round 14's cloud-op sweep called it a contract gap once the distribution pick gave it a subject)
        expect_keys=["records", "total"],
        expect_types={"records": list, "total": int},
    ),
    "theprotocol_getLockPayoutStats": McpContract(
        tier="1",
        notes="Phase-2: distribution stats roll-up.",
    ),
    "theprotocol_getNetworkHealth": McpContract(tier="1"),
    "theprotocol_getPublicEventStoreRecent": McpContract(tier="1"),
    "theprotocol_getPublicEventStoreStats": McpContract(tier="1"),
    "theprotocol_getPublicRegistryConfig": McpContract(tier="1"),
    "theprotocol_getRegistryCard": McpContract(tier="1"),
    "theprotocol_getRegistryFederationProposals": McpContract(
        tier="2",   # re-tiered to agent JWT in Sprint 8 per wrapper docstring
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getPublicShowcaseAgents": McpContract(tier="1"),
    "theprotocol_getSupportedWebhookEvents": McpContract(tier="1"),
    "theprotocol_getSystemActivityFeed": McpContract(tier="1"),
    "theprotocol_getDownloadsManifest": McpContract(tier="1"),
    "theprotocol_getCircuits": McpContract(tier="1"),
    "theprotocol_getFeaturedBundles": McpContract(tier="1"),

    # --- Tier 1 reads with simple DID fixtures ---

    "theprotocol_getAgentByDID": McpContract(
        tier="1",
        arguments={"did": "${sentinel_did}"},
        expect_keys=["did"],
    ),
    "theprotocol_getAgentByDIDAlt": McpContract(
        tier="1",
        arguments={"did": "${sentinel_did}"},  # wrapper takes `did`, not agent_did
    ),
    "theprotocol_getAgentDIDDoc": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentPayoutHistory": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentLockedBalance": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentLockHistory": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentAttestationsByDID": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentAttestationSchedulesByDID": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentTransactionHistory": McpContract(
        tier="1",
        arguments={"agent_id": "${sentinel_agent_id}"},
    ),
    "theprotocol_getAgentReputation": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_id": "${sentinel_agent_id}"},
        # §pass73.3.19: the /teg/agents/{id}/reputation endpoint is AGENT-authed
        # ("any authenticated agent can view reputation"); the wrapper was mis-tiered
        # as T3 (developer) → always 401. Re-tiered T3→T2 (agent). Returns a real
        # reputation envelope (BRONZE/0 for an unprimed agent) → genuine 200.
        expect_keys=["reputation_score", "reputation_tier"],
    ),
    "theprotocol_getAgentMetrics": McpContract(
        tier="1",
        arguments={"agent_id": "${sentinel_agent_id}"},
    ),
    "theprotocol_getAgentPublicKey": McpContract(
        tier="1",
        arguments={"did": "${sentinel_did}"},  # wrapper takes `did`
    ),
    "theprotocol_getAgentContracts": McpContract(
        tier="2",   # actually Tier-2 (agent JWT required)
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getCrossFrameReputation": McpContract(
        tier="1",
        # no args version
    ),

    # --- Tier 1 reads with simple value fixtures ---

    "theprotocol_getFiatQuote": McpContract(
        tier="1",
        arguments={"eur_amount": "10"},
        expect_keys=["eur_amount", "avt_amount"],
    ),
    "theprotocol_getActivityFeedByType": McpContract(
        tier="1",
        arguments={"event_type": "TokensTransferred", "limit": 5},
    ),
    "theprotocol_getDevTrustGraph": McpContract(
        tier="3",   # tools_developer.py; takes `did` not `developer_id`
        arguments={"did": "${sentinel_did}"},
    ),

    # --- Tier 2: my-X agent reads previously mis-skipped ---

    "theprotocol_getMyAgentInfo": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["did", "status"],
    ),
    "theprotocol_getMyAgentHealth": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyTegBalance": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyTegTransactions": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "limit": 5},
    ),
    "theprotocol_getMyTegDisputes": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyContracts": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "limit": 5},
    ),
    "theprotocol_getMyEnforcementStatus": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyReputationBondStatus": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyFederationRegistrations": McpContract(
        tier="3",   # tools_developer.py, no extra args
        # §pass73.3.19: the EmailStr→str backend fix (PeerRegistryRead) resolved
        # the documented 500; the endpoint now returns a genuine 200 paginated
        # envelope {items, pagination}. Updated from the stale _text rubber-stamp
        # to assert the real shape.
        expect_keys=["items", "pagination"],
    ),
    "theprotocol_getMyAgentDisputes": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "sentinel_did"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMyAgentLogs": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}", "limit": 5},
        # 2026-05-26 Phase D.3: wrapper now normalizes list response to
        # {logs, total, limit, offset} envelope.
        expect_keys=["logs", "total"],
    ),
    "theprotocol_getMyMtlsStatus": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        # §MCPTEST30 (V0545): a read of the caller's own enrolment, safe to run as its own call. The toggle
        # lifecycle's read-backs are verification probes, and round 11's only recorded call was one the transport
        # timed out (status 0), which the coverage fan graded "REFUSED (HTTP 0)": NOT MEASURED on every run. The keys
        # are the route's (routers/agent_mtls.py::mtls_status), so a renamed field fails here, not in a verifier.
        expect_keys=["enrolled", "spiffe_id", "spire_entry_exists"],
        override_coverage_fan=True,
    ),
    "theprotocol_listMyAttestationSchedules": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_listMyAttestations": McpContract(
        tier="3",   # tools_developer.py — developer JWT
        arguments={"limit": 5},
    ),

    # --- Tier 3 developer reads previously mis-skipped ---

    "theprotocol_getMyDeveloperActivity": McpContract(
        tier="3",
        arguments={"limit": 10},
    ),
    "theprotocol_getMyDeveloperActivityEventstore": McpContract(
        tier="3",
        arguments={"limit": 10},
    ),
    "theprotocol_getMyDeveloperJwks": McpContract(
        tier="3",
        arguments={"developer_id": "${developer_id}"},
    ),
    "theprotocol_getMyDeveloperTegSummary": McpContract(tier="3"),
    "theprotocol_getMyDeletionStatus": McpContract(tier="3"),
    "theprotocol_getMyIncome": McpContract(
        tier="2",   # in tools_agent.py → require_agent_auth
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "limit": 5},
    ),
    "theprotocol_getMyFiatPurchases": McpContract(tier="3"),
    "theprotocol_getMyMcpAuditLog": McpContract(tier="3", arguments={"limit": 10}),
    "theprotocol_getMyNotificationPrefs": McpContract(tier="3"),
    "theprotocol_getMyPayoutHistory": McpContract(
        tier="2",   # agent JWT — no extra args; agent_did inferred from context
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyLockStats": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        notes="Phase-2: covers BUG-11 territory — would let us assert 'rewards' field is monthly_projection (not earned).",
    ),
    "theprotocol_getMyLockHistory": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMyLockStatus": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getMySupportTickets": McpContract(tier="3"),
    "theprotocol_getMyVotingPower": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["votingPower", "canVote", "positions"],
        notes=("Phase-2: covers BUG-20 territory. §EVTYPES4 restored 'positions', "
               "which a DUPLICATE dict key had silently dropped; re-measured present "
               "on a live 200 before restoring it."),
    ),
    "theprotocol_getMyPaymentAuthorizations": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "limit": 5},
        expect_keys=["tokens"],
        notes=("§EVTYPES4 restored expect_keys, which a DUPLICATE dict key had "
               "silently dropped (this entry shadowed a richer one above it); "
               "re-measured present on a live 200 before restoring it."),
    ),
    "theprotocol_getMyApiKeys": McpContract(
        tier="3",
        expect_keys=["api_keys"],
        notes="Phase-2 (overrides hand-curated above): asserts envelope shape (BUG-3 class).",
    ),
    "theprotocol_listDeveloperApikeysMe": McpContract(tier="3"),
    "theprotocol_listDeveloperWebhooks": McpContract(tier="3"),
    "theprotocol_listDeveloperWebhooksAlt": McpContract(tier="3"),
    "theprotocol_getMyWebhooks": McpContract(tier="3", expect_keys=["webhooks"]),
    # §MCPTEST-MCP4 2026-08-08 — five tools were scored `contract gap: no
    # expect_keys AND no outputSchema.required`. That is the tester correctly
    # reporting that IT had nothing to assert, not a product defect: each of
    # these returns 200 with a real body. Keys below were READ OFF THE LIVE
    # RESPONSE on sandbox-A, not guessed, so the assertion is a real one.
    "theprotocol_getNotificationCatalog": McpContract(
        tier="3", expect_keys=["types", "categories", "channels"]),
    "theprotocol_getMyNotificationMatrix": McpContract(
        tier="3", expect_keys=["types", "categories", "channels"]),
    "theprotocol_oauthFederationTrustList": McpContract(
        tier="3", expect_keys=["trusted_registries", "count"]),
    "theprotocol_guildListOrders": McpContract(
        tier="1", expect_keys=["orders", "total"]),
    "theprotocol_guildNetworkBoard": McpContract(
        tier="1", expect_keys=["orders", "total"]),
    # `theprotocol_guildMyWork` is defined once, further down, with expect_keys.
    # It was tier-1 and the server said `requires 2 auth`; the SERVER is right,
    # so the label was fixed rather than the drift check silenced — drift
    # detection is the whole reason this tester exists.
    # §MCPTEST-MCP5 — with FORGE_ENABLED now set on the sandbox this tool
    # answers 200 instead of 403, so it moved from a capability failure to a
    # contract gap. Keys read off the live response, not guessed.
    "theprotocol_getForgeStatus": McpContract(
        tier="1", expect_keys=["enabled", "counts", "flags"]),
    # §MCPTEST-MCP5 2026-08-08 — converting `default contract: tool has required
    # params` SKIPS into real tests. Skips count AGAINST pass_pct, so a skipped
    # tool is indistinguishable from an untested one; each of these was simply
    # missing an argument the sandbox can supply.
    #
    # Every argument below is a REAL fixture on sandbox-A and every call was
    # executed before the contract was written (listings TUTCO/TUTXB are live
    # and `status=trading`; the org id is a real row). Keys are read off those
    # live responses, not guessed.
    #
    # DELIBERATELY NOT ADDED: placeAgoraOrder / buyAgoraLaunch /
    # cancelAgoraOrder / declareAgoraDistribution / createAgoraListing.
    # Those MOVE SHARES AND MONEY through the AGORA escrow mover. A blind sweep
    # firing them every run is a side effect a tester must not have — they need
    # a throwaway listing fixture, which is separate work.
    # §APITEST 2026-09-04 — the symbol was the literal "TUTCO", the tutorial
    # company on the RETIRED sandbox tier. On any other venue all four answer 404
    # and read as product failures. _EXCHANGE_LISTING keeps TUTCO as the default
    # and lets a frame name its own live symbol. (A dynamic resolve from
    # getAgoraListings would be better still and is the next improvement.)
    # §APITEST 2026-09-04 — four tools had NO contract at all, so the runner had
    # neither expect_keys nor an outputSchema to check and reported
    # "contract gap" / "missing required argument" as hard failures. Keys were
    # read from the live responses; the two review tools take a REQUIRED id that
    # no contract was supplying. The ids are env-overridable so a frame can name
    # its own fixtures.
    "theprotocol_listTransparentOrganizations": McpContract(
        tier="1", arguments={}, expect_keys=["organizations"]),
    # §CLOUDOPMCP2 2026-09-05 — OurChat is DUAL-PRINCIPAL, so an agent JWT is a
    # legitimate caller, not a wrong tier. Left at tier="3" (its developer-facing
    # tier for contract reporting) but the auto-derivation from that tier demands
    # ["empty", "agent_jwt"], which scored the correct 200 as the sweep's ONLY
    # auth_matrix violation, every run. Five independent signals say dual:
    #   · the tool's own schema — "Developer key or agent JWT" — and its explicit
    #     `agent_jwt` argument ("Optional: speak as an agent")
    #   · server.py registers it in TIER2_TOOLS, not TIER3
    #   · tools_agent._chat_request refuses ONLY the anonymous/no-token case
    #     ("This tool requires authentication (a developer key or an agent JWT)")
    #     and otherwise forwards the caller's own token for the route to scope
    #   · PRODUCTION_DOCS OurChat.md documents the surface as dual-principal
    # So the only credential that must be refused here is the empty one.
    # ⚠ This asserts WHICH credentials are refused, not that the route scopes an
    # agent's view correctly — that is the route's job and is not measured here.
    "theprotocol_listConversations": McpContract(
        tier="3", arguments={}, expect_keys=["conversations"],
        expect_tier_rejections=["empty"]),
    # §MCPTEST30 (V0553): the operator sweep runs no chat lifecycle (the central flow walks block and unblock end to end
    # between two developers' agents, a row these contracts never override), so both read "default contract: required
    # params ['ptype']" on every operator. A malformed remote address is refused by the route before anything is
    # written, for both tools alike: their one shared key rule.
    "theprotocol_blockChatPrincipal": McpContract(
        tier="3", arguments={"ptype": "remote", "remote_key": "mcp-tester-not-an-address"},
        expect_status="error_4xx", expect_error_message_contains="remote_key must be id@https://their.registry",
        expect_tier_rejections=["empty"]),
    "theprotocol_unblockChatPrincipal": McpContract(
        tier="3", arguments={"ptype": "remote", "remote_key": "mcp-tester-not-an-address"},
        expect_status="error_4xx", expect_error_message_contains="remote_key must be id@https://their.registry",
        expect_tier_rejections=["empty"]),
    # §CLOUDOPMCP2 2026-09-05 — these two were the run's `contract_gap: 2`, failing
    # "no expect_keys AND no outputSchema.required", i.e. the sweep called them and
    # then had nothing to validate. MEASURED on sbx-alpha rather than read off the
    # router: both return the admin_request ENVELOPE, not the route body, so the
    # router's own {ticket_id, grants} / {grant_id, messages, ...} sit nested under
    # `response` and would never have matched as top-level keys.
    #   adminReviewGrants   -> ok=True status_code=200 response{grants, ticket_id}
    #   adminReviewMessages -> ok=True status_code=200 response{conversation_id,
    #                          grant_id, messages, read_only, ticket_id}
    # `ok` is the load-bearing one: it is False when the upstream call failed, so a
    # dead seeded ticket/grant still fails rather than passing on envelope shape
    # alone (both fixtures verified live here — ticket 1 and the seeded grant).
    "theprotocol_adminReviewGrants": McpContract(
        tier="admin", arguments={"ticket_id": int(_os.getenv("API_TEST_SUPPORT_TICKET_ID", "1"))},
        expect_keys=["ok", "status_code", "response"]),
    "theprotocol_adminReviewMessages": McpContract(
        tier="admin", arguments={"grant_id": _os.getenv(
            "API_TEST_SUPPORT_GRANT_ID", "00000000-0000-4000-8000-000000000000")},
        expect_keys=["ok", "status_code", "response"]),
    "theprotocol_getAgoraListing": McpContract(
        tier="1", arguments={"listing": "${exchange_listing}"},
        expect_keys=["symbol", "status"]),
    "theprotocol_getAgoraOrderBook": McpContract(
        tier="1", arguments={"listing": "${exchange_listing}"},
        expect_keys=["bids", "asks"]),
    "theprotocol_getAgoraTrades": McpContract(
        tier="1", arguments={"listing": "${exchange_listing}"},
        expect_keys=["trades"]),
    "theprotocol_getAgoraCandles": McpContract(
        tier="1", arguments={"listing": "${exchange_listing}"},
        expect_keys=["candles", "tf"]),
    "theprotocol_getForgeLineage": McpContract(
        tier="1", arguments={"org_id": "ae374891-b427-4e83-b6a1-c797647210d0"},
        expect_keys=["org_id", "nodes", "edges"]),
    # Empty `rows` is a legitimate no-op update: the handler answers
    # {"applied": 0, "deleted": 0}. Exercises the write path without mutating
    # the runner's real notification preferences.
    "theprotocol_updateNotificationPrefs": McpContract(
        tier="3", arguments={"rows": []},
        expect_keys=["applied", "deleted"]),
    # ══ §MCPTEST-MCP6 2026-08-08 — contracts against the THROWAWAY fixtures
    # created in `_phase3_setup_entities` (guild order, two TEG policies, an
    # approved scratch listing + a resting order on it). Every one of these was
    # previously skipped for want of an id, and a skip costs pass_pct exactly
    # like a failure. Each call below was executed by hand on sandbox-A first.
    #
    # If a fixture fails to create, `${name}` stays unresolved and the runner
    # skips the contract with "phase-3 fixture missing" — degrading to today's
    # behaviour rather than firing a bogus argument at the wrapper.
    "theprotocol_guildGetOrder": McpContract(
        tier="1", arguments={"order_id": "${guild_order_id}"},
        expect_keys=["order"]),
    "theprotocol_guildMyWork": McpContract(
        tier="2", expect_keys=["orders"]),
    # The sentinel POSTED the order, and the venue correctly refuses
    # "Cannot bid on your own task" — so the bid must come from the SECOND
    # agent. Passing agent_jwt explicitly beats the tier-2 setdefault.
    "theprotocol_guildBid": McpContract(
        tier="2",
        arguments={"order_id": "${guild_order_id}", "price": "1",
                   "agent_jwt": "${second_agent_jwt}"},
        # MEASURED: the bid response is {ok, order_id, bidder, firm,
        # stake_locked} — there is NO `bid_id`. My first guess said there was,
        # and the run said otherwise. (It also means guildAward, which needs a
        # bid_id, cannot be contracted off this response alone.)
        expect_keys=["ok", "order_id", "bidder"]),
    # guildCancelOrder + oauthRevoke were TRIED and REVERTED (run 13):
    #   guildCancelOrder — needs agent auth and I could not verify its response
    #     shape, and a guessed expect_keys just trades a skip for a contract gap.
    #   oauthRevoke — answered 401 "Invalid client credentials" with the
    #     sentinel's stored creds; guessing at credentials is not a test.
    # A skip is the honest state for both until their shapes are measured.
    # `location_data` is the real parameter (a lat/long pair is rejected as an
    # unexpected kwarg — read from the schema, not assumed).
    "theprotocol_updateMyDeveloperLocation": McpContract(
        tier="3",
        arguments={"location_data": {"latitude": 47.8, "longitude": 12.9,
                                     "city": "Freilassing", "country": "DE"}},
        # MEASURED live: {"success": ..., "updated_agents": ...}
        expect_keys=["success"]),
    # Cancels the SECOND throwaway order, never the one guildBid/guildGetOrder
    # depend on — sweep order is not something a contract may assume. The
    # sentinel POSTED it, so the sentinel is the party allowed to cancel;
    # MEASURED: the rail refuses unauthenticated callers ("This tool requires
    # agent authentication"), so the jwt is passed explicitly.
    "theprotocol_guildCancelOrder": McpContract(
        tier="2",
        arguments={"order_id": "${guild_order_id_cancel}",
                   "agent_jwt": "${sentinel_jwt}"},
        # MEASURED from routers/guild.py::cancel — always
        # {"ok", "order_id", "status", "refund"}.
        expect_keys=["ok", "order_id", "status"]),
    # smartSend needs a FUNDED sender — MEASURED: a fresh 0-balance agent gets
    # "Smart send failed (HTTP 400)". The sentinel is funded by phase-3, and the
    # second agent is a real local DID, so the transfer has somewhere to land.
    "theprotocol_smartSend": McpContract(
        tier="2",
        arguments={"receiver_did": "${second_agent_did}", "amount": "1",
                   "agent_jwt": "${sentinel_jwt}"},
        # MEASURED from routers/teg_send.py::SmartSendResponse — ok/method/status
        # carry no default, so they are on every success shape.
        expect_keys=["ok", "method", "status"]),
    # MEASURED from routers/guild.py::cancel — the endpoint returns
    # {"ok", "order_id", "status", "refund"}. Run 15 proved the CALL succeeds;
    # it failed only on "contract gap: no expect_keys", so this is the last mile.
    # MEASURED from routers/teg_send.py::SmartSendResponse — ok/method/status are
    # non-defaulted fields, so they are present on every success shape (local,
    # 2pc, async, fx, dry_run). Same story: run 15 executed it fine.
    # Moved out of `lifecycle_admin_preview_reads` (see mcp_lifecycles.py): they
    # ran on a developer JWT the lifecycle phase had already revoked. PROBED with
    # a fresh token: 200 {"status": "ok", "raw": "<rendered template>"}.
    # NB the parameter is `template`, not `template_name`.
    "theprotocol_previewAdminEmailText": McpContract(
        tier="3", arguments={"template": "funding_approved"},
        expect_keys=["status", "raw"]),
    "theprotocol_previewAdminEmailWithContext": McpContract(
        tier="3",
        arguments={"template": "funding_approved", "context": {"name": "Phase5"}},
        expect_keys=["status", "raw"]),
    # ══ §MCPTEST-MCP8 2026-08-08 — Commander: "make it 100% without masking
    # things we could actually test in the sandbox env." Everything below was a
    # SKIP purely for want of an argument or a staged fixture, and a skip costs
    # pass_pct exactly like a failure. Each call was executed by hand on
    # sandbox-A first and the keys read off the real response.

    # --- guild lifecycle: three independently staged orders (phase-3 §18) ---
    "theprotocol_guildAward": McpContract(
        tier="2",
        arguments={"order_id": "${guild_award_order_id}",
                   "bid_id": "${guild_award_bid_id}",
                   "agent_jwt": "${sentinel_jwt}"},
        # MEASURED: {ok, order_id, status, worker, payee, firm}
        expect_keys=["ok", "order_id", "status"]),
    # The WORKER submits, not the poster — the rail answers 403 "Only the
    # awarded worker can submit" otherwise, which is correct and was measured.
    "theprotocol_guildSubmitWork": McpContract(
        tier="2",
        arguments={"order_id": "${guild_submit_order_id}",
                   "deliverable_text": "mcp-tester deliverable",
                   "agent_jwt": "${second_agent_jwt}"},
        expect_keys=["ok", "order_id", "status"]),
    # Verify pays out, so it must be the POSTER, on an order already SUBMITTED
    # (a still-open order answers 409 "Order is open" — also measured).
    "theprotocol_guildVerify": McpContract(
        tier="2",
        arguments={"order_id": "${guild_verify_order_id}", "accept": True,
                   "stars": 5, "agent_jwt": "${sentinel_jwt}"},
        # MEASURED: {ok, order_id, status, payout, fee, stars, payee,
        #            credential, credential_traveled, firm}
        expect_keys=["ok", "order_id", "status", "payout"]),

    # --- meta-tools: skipped out of caution, but this IS the sandbox ---
    # enable/disableToolset mutate the caller's own session listing. That is
    # exactly why they were skipped; in a throwaway sandbox it is a legitimate
    # thing to exercise. Paired on the same bucket so the net effect is nil.
    # MEASURED: {enabled_toolsets, session_scope, note}
    "theprotocol_enableToolset": McpContract(
        # MEASURED: "discovery" is a PUBLIC-catalog bucket only. The sweep
        # dispatches these admin-side, where the valid set is
        # ['broadcast','canary','core','diagnostics-tester',...]. "core" exists
        # in BOTH catalogs, so the contract no longer depends on which endpoint
        # the walker picks.
        tier="1", arguments={"toolsets": ["core"]},
        expect_audit_row=False,
        expect_keys=["enabled_toolsets", "session_scope"]),
    "theprotocol_disableToolset": McpContract(
        tier="1", arguments={"toolsets": ["core"]},
        expect_audit_row=False,
        expect_keys=["enabled_toolsets", "session_scope"]),
    # invokeTool is a proxy: point it at a read-only T1 tool and assert the
    # INNER tool's shape came back, which proves the proxy actually dispatched.
    "theprotocol_invokeTool": McpContract(
        # The proxy resolves the inner name against the catalog of the endpoint
        # that dispatched it. Run 23 proved that is the ADMIN side
        # ("unknown tool 'theprotocol_getNetworkStats'"), so point it at an
        # admin read. Asserting the INNER tool's own keys is what proves the
        # proxy actually dispatched rather than echoing.
        tier="1",
        # MEASURED: only SIX tools exist in both the public (423) and admin (319)
        # catalogs. listToolsets is one of them and returns the SAME
        # {toolsets, usage} shape on either side, so the contract no longer
        # depends on which endpoint the walker happens to dispatch through —
        # which is what made this flip between run 23 (getNetworkStats unknown
        # admin-side) and run 25 (getAdminDashboard unknown public-side).
        arguments={"name": "theprotocol_listToolsets", "arguments": {}},
        expect_keys=["toolsets", "usage"]),

    # --- arguments the sweep simply never supplied ---
    # get_diagnostic_config(target_id) — REQUIRED. With none, the wrapper raises
    # "missing 1 required positional argument" and the sweep saw a bare
    # "HTTP 400: Error:" with an empty body, which reads like a broken endpoint.
    # target ids come from getDiagnosticTargets[].operator_id. §NIGHTLYTRUTH (2026-09-14): the id
    # is the FIXTURE `${diagnostic_target_id}`; it used to be the literal "sandbox-a" ("this registry's own" on the
    # torn-down tier), which the EU sweep asked for every night and read 404 as a defect. Where no fixture is
    # published this contract auto-skips. §MCPSWEEP 2026-09-27: its publisher ran on the PUBLIC bridge, which
    # carries no admin tool, so it was never published, and it is deliberately not published now: the success path
    # returns the target's env masked by variable NAME, and the tester keeps the first five keys of a result with
    # their values, so a secret carried inside an innocuous value would land in the run record.
    # §MCPTEST30 (2026-10-01): published again, by lifecycle_admin_fixture_harvest on the ADMIN bridge, and the row keeps
    # the SHAPE of the answer only (excerpt_shape_only): the env never reaches the run record. Measured on sbx-alpha
    # before publishing: 200, env of 143 variables, no password inside a URL, nothing credential-shaped (the census).
    "theprotocol_getDiagnosticConfig": McpContract(
        # tier="admin" — MEASURED: it answers on /mcp/admin/rpc. An earlier
        # duplicate of this key already carried the right tier and target_id;
        # mine originally said tier="3" and, being later in the dict, would have
        # silently DOWNGRADED it. Duplicate keys in this file are later-wins.
        tier="admin", arguments={"target_id": "${diagnostic_target_id}"},
        expect_keys=["target", "docker", "env"], excerpt_shape_only=True),
    # compositeHealthCheck takes only an OPTIONAL agent_credentials dict and
    # returns a full report for {} — measured. Its 400 came from what the
    # default synthesizer was passing, not from the tool.
    "theprotocol_compositeHealthCheck": McpContract(
        tier="admin", arguments={},
        expect_keys=["overallStatus", "results"]),
    # getContractV2 stays SKIPPED: the phase-3 probe that fetched a live
    # contract ref answered 401 and, worse, recorded a FAILURE against
    # getMyContracts — the fixture cost more than the skip. Honest skip until a
    # contract ref can be obtained without perturbing another tool.
    "theprotocol_getTegPolicy": McpContract(
        tier="3", arguments={"policy_id": "${teg_policy_id}"},
        expect_keys=["policy_id"]),
    "theprotocol_updateTegPolicy": McpContract(
        tier="3",
        arguments={"policy_id": "${teg_policy_id}",
                   "updates": {"description": "phase-3 mcp-tester update"}},
        expect_keys=["policy_id"]),
    # Deliberately points at the SECOND policy: deleting the read/update
    # subject would strand those two contracts depending on sweep order.
    "theprotocol_deleteTegPolicy": McpContract(
        tier="3", arguments={"policy_id": "${teg_policy_id_del}"},
        expect_keys=["message"],
        notes=("§EVTYPES5: the delete answers 200 {'message': 'Policy <id> "
               "deactivated'} — MEASURED identical on a mainframe and a cloud "
               "operator. It carried NO expect_keys and leaned on the tool's "
               "advertised outputSchema.required, which made the same contract a "
               "PASS on one node and a 'contract gap' failure on another whose "
               "image advertises no schema for it. An assertion that depends on "
               "what a node happens to advertise is not portable; this one is. "
               "The row only became visible at all once the teg_policy_id_del "
               "fixture started resolving — a skip was hiding a missing assertion."),
    ),
    "theprotocol_placeAgoraOrder": McpContract(
        tier="2",
        arguments={"listing": "${scratch_listing}", "side": "buy", "qty": 1,
                   "order_type": "limit", "price": "1"},
        expect_keys=["order_id", "status"]),
    "theprotocol_cancelAgoraOrder": McpContract(
        tier="2", arguments={"order_id": "${scratch_order_id}"},
        expect_keys=["order_id", "status"]),
    "theprotocol_buyAgoraLaunch": McpContract(
        tier="2", arguments={"listing": "${scratch_listing}", "qty": 1},
        expect_keys=["purchase_id", "status"]),
    "theprotocol_declareAgoraDistribution": McpContract(
        tier="3",
        arguments={"listing": "${scratch_listing}", "per_share": "0.01"},
        expect_keys=["dividend_id"]),
    "theprotocol_listFederationPeers": McpContract(tier="1"),
    # ── Phase C (2026-05-26): explicit skip contracts for tools whose
    # happy path doesn't exist in the sandbox seed. Skips appear in the
    # `skipped:` outcome category (not `contract_gap:`), making the
    # remaining failures cleaner to triage.
    # 2026-05-26 Phase D: operator portal endpoints deliberately 503 on mainframes
    # ("This feature runs on sovereign mainframes only" — operator_self_service.py).
    # Wrapper packages as text envelope. Assert text presence.
    "theprotocol_getOperatorMyBundle": McpContract(
        tier="3",
        # §pass73.3.19: sentinel developer is not an approved operator → 403
        # "Only approved operators can download bundles." Documented 4xx.
        expect_status="error_4xx",
        # MEASURED BOTH WAYS: 403 "Only approved operators can download
        # bundles." standalone, and 410 "Bundle has expired." once the sweep
        # itself has approved an operator application earlier in the run.
        expect_error_message_contains=["approved operators", "Bundle has expired"],
        override_coverage_fan=True,
    ),
    "theprotocol_getOperatorMyStatus": McpContract(
        tier="3",
        # pass73.3.19 (2026-05-28) — real shape is
        # {is_federation_operator, federation_operator_status, application}.
        # Was stale expect_keys=["_text"].
        expect_keys=["is_federation_operator", "federation_operator_status"],
    ),
    # (duplicate "theprotocol_compositeHealthCheck" removed §MCPTEST-MCP8 — a single
    #  authoritative definition now lives above; later-wins made two dangerous.)
    "theprotocol_runAllApiTests": McpContract(
        tier="admin",
        skip_reason="recursive — admin endpoint that re-invokes the API tester itself; would loop",
        # §EVTYPES8: an open admin/tier gate here would not answer 401 — it would
        # run this. Excluded from the wrong-tier matrix, and named in
        # flow_values.auth_matrix_not_probed so the gap is visible, not assumed.
        never_probe_wrong_tier=True,
    ),
    # ── Incident 2026-06-01: the MCP sweep INVOKES these meta/provisioning tools →
    # they execute full api-test suites / provision REAL cloud-ops + whole frames,
    # and the suite re-enters the flow_mcp_lifecycle category → re-entrant fork-bomb
    # that spawned stray cloud-op-api-test-operator-* containers. runAllApiTests was
    # already guarded above; these are its unguarded siblings + their destructive
    # teardown partners. Skip in the MCP sweep — they're covered by the api-test
    # runner directly. (See SESSION_LOG_2026-06-01_BACKEND_DEFECT_SESSION.md.)
    "theprotocol_testApiFlow": McpContract(tier="admin", skip_reason="recursive/heavy — runs an api-test flow; re-invokes the tester. Cover via the api-test runner directly."),
    "theprotocol_testApiCategory": McpContract(tier="admin", skip_reason="recursive/heavy — runs an api-test category; re-invokes the tester."),
    "theprotocol_testApiFederation": McpContract(tier="admin", skip_reason="recursive/heavy — runs the FULL federation api-test suite; provisions operators/frames."),
    "theprotocol_eagerBootstrapApiTest": McpContract(tier="admin", skip_reason="heavy — kicks api-tester eager bootstrap (side effects)."),
    "theprotocol_provisionCloudOperator": McpContract(tier="admin", skip_reason="provisions a REAL cloud operator (containers) — destructive/heavy infra op."),
    "theprotocol_teardownCloudOperator": McpContract(tier="admin", skip_reason="destructive teardown of provisioned infra.",
        # §EVTYPES8: an open admin/tier gate here would not answer 401 — it would
        # run this. Excluded from the wrong-tier matrix, and named in
        # flow_values.auth_matrix_not_probed so the gap is visible, not assumed.
        never_probe_wrong_tier=True,
    ),
    "theprotocol_listFederationRegistries": McpContract(tier="1"),
    # pass73.3.19 (2026-05-28) — explicit expect_keys to override a stale
    # phantom 'body' required-key the harness was deriving. Handlers wrap to
    # {<collection>, total} (see tools_discovery.py list_* handlers).
    "theprotocol_listFederationRegistryCards": McpContract(tier="1",
        # §MCPTEST30 (V0547): the route authenticates only a federation PEER (the survey's PEER_ROUTE class), which no
        # MCP caller holds; the wrapper turned the 401 into an empty list and this contract read it as a pass on
        # every run. The refusal is what any MCP caller gets: documented 4xx. Leaving the surface or a route a
        # developer may call is his decision (PEER_ROUTE_BASELINE in test_mcp_tool_requests_meet_their_routes.py).
        expect_status="error_4xx",
        expect_error_message_contains="Federation authentication required",
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design (anyone reads the federation's registries through listFederationRegistries or discoverRegistries)",
        # §MCPTEST30 (V0640): not pinned. earned_agent_public's by-design lifecycle (PEER_ONLY_READS) says the row NOT
        # MEASURED and files this 401 as a refusal row; pinned, the sweep ran this contract instead and dropped that
        # row (kept_lifecycle_rows keeps only a pinned tool's real success), so the refusal stayed the tool's only test
    ),
    "theprotocol_listFederationAgentCards": McpContract(tier="1",
        # §MCPTEST30 (V0547): the route authenticates only a federation PEER (the survey's PEER_ROUTE class), which no
        # MCP caller holds; the wrapper turned the 401 into an empty list and this contract read it as a pass on
        # every run. The refusal is what any MCP caller gets: documented 4xx. Leaving the surface or a route a
        # developer may call is his decision (PEER_ROUTE_BASELINE in test_mcp_tool_requests_meet_their_routes.py).
        expect_status="error_4xx",
        expect_error_message_contains="Federation authentication required",
        override_coverage_fan=True,
    ),
    "theprotocol_listAgentCards": McpContract(tier="1"),
    "theprotocol_listAgentTemplates": McpContract(tier="3"),
    "theprotocol_listAgentBuilderTemplates": McpContract(tier="3"),
    "theprotocol_listArenaMatches": McpContract(tier="1"),
    "theprotocol_listPublicOperatorApplications": McpContract(
        tier="1",
        skip_reason=("§MCPSWEEP V0464: no registry publishes a list of operator applications (the route takes "
                     "submissions, POST only). The tool used to GET it, meet 405 and answer an empty list, which "
                     "this contract measured as a pass; it now answers an error saying so. Retiring it is his call."),
    ),
    "theprotocol_listTegPolicies": McpContract(tier="3"),
    "theprotocol_getTegPoliciesComplianceDashboard": McpContract(tier="3"),
    "theprotocol_getMyOrganizations": McpContract(tier="3"),
    "theprotocol_getMyAgentBundles": McpContract(
        tier="3",
        arguments={"limit": 5, "offset": 0},
    ),
    "theprotocol_getMyCicdPipelines": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMyCicdVersions": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMyCicdDeployments": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMyAgentCicdStats": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
    ),

    # --- Tier 1 / wellknown ---

    "theprotocol_getWellKnownDevJwks": McpContract(tier="1"),
    "theprotocol_getWellKnownRegistryCard": McpContract(tier="1"),
    "theprotocol_getPeerSlashConfig": McpContract(tier="1"),
    # 2026-05-26 strict mode: removed duplicate getFiatTiers entry that
    # shadowed the line-171 entry with expect_keys=["tiers"]. Python dict
    # literals process entries in order — last one wins. The duplicate
    # without expect_keys triggered contract_gap failures.
    "theprotocol_getFiatProviders": McpContract(tier="1", expect_keys=["providers"]),
    # 2026-05-26 Phase C: explicit contract was [total_purchases, total_eur]
    # but the real /api/v1/fiat/stats/public response has neither.
    # Actual shape: backers counts, AVT totals, recent_backers list.
    "theprotocol_getFiatStatsPublic": McpContract(
        tier="1",
        expect_keys=["total_backers", "total_avt_distributed",
                     "founder_slots_total", "founder_slots_remaining",
                     "recent_backers"],
    ),

    # --- OAuth federation (Tier 3) ---

    "theprotocol_getOAuthFederationStatus": McpContract(tier="3"),

    # --- Other batch additions ---

    "theprotocol_getDeveloperStats": McpContract(tier="3"),
    "theprotocol_getDeveloperFlare": McpContract(
        tier="1",
        arguments={"developer_id": "${developer_id}"},
    ),
    "theprotocol_getAgentFlare": McpContract(
        tier="1",
        arguments={"did": "${sentinel_did}"},
    ),
    "theprotocol_getTrustScore": McpContract(
        tier="3",
        # §EVTYPES8 2026-09-06 — WAS ${sentinel_did}, AND THAT PINNED ONE SIDE OF A
        # RACE. The tool answers 200-with-a-score for an agent that existed at the
        # last EigenTrust epoch and 404 for one created since; the sentinel is
        # created fresh per run, so which answer arrives depends on whether the
        # epoch worker (roughly hourly — MEASURED on sbxbetaop: epoch 91,
        # agents_computed 102, next_scheduled ~57 min later) happened to run in
        # between. It had been landing on 404 for months by luck; the moment the
        # operators were funded and busy, sandboxalpha's sentinel resolved to an
        # agent that WAS in epoch 135 and the row went red on a 200 carrying a
        # perfectly good score. Both answers are correct — the contract was wrong
        # to depend on which.
        #
        # A DID that does not exist can NEVER have a score, so the refusal is
        # deterministic. MEASURED on both operators AND the frame: identical
        # 404 "No EigenTrust++ score computed for …" on all three.
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        # pass73.3.19 (2026-05-28): was expect_keys=["_text"] — that ACCEPTED the
        # error envelope as healthy, i.e. a built-in masked false-pass (commander
        # caught this exact row). A 404 "No EigenTrust++ score computed" is the
        # CORRECT response for an agent without a completed reputation epoch, so
        # contract it as an expected error. Future enhancement: a reputation-setup
        # fixture that reliably completes an epoch could assert a real 200 score.
        expect_status="error_4xx",
        expect_error_message_contains="EigenTrust",
        override_coverage_fan=True,
    ),
    "theprotocol_getAgentANP": McpContract(
        tier="1",   # ANP description is public (tools_discovery)
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getAgentPendingPayouts": McpContract(
        tier="1",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMy2FAStatus": McpContract(tier="3"),
    "theprotocol_getMyAchievements": McpContract(tier="3"),

    # --- TEG-side reads ---

    "theprotocol_getTegPrice": McpContract(tier="1"),
    "theprotocol_getTegReputationRankings": McpContract(tier="1"),
    "theprotocol_getTegAdvancedTransactions": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "limit": 5},
    ),
    "theprotocol_getTegAttestations": McpContract(tier="2", requires_fixtures=["sentinel_jwt"],
                                                    arguments={"agent_jwt": "${sentinel_jwt}"}),

    # --- Tokenomics (Tier 1) ---

    "theprotocol_getUnitPayouts": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getUnitTransactions": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getRegistryTreasury": McpContract(
        tier="2",   # require_agent_auth
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),
    "theprotocol_getTransactionsAnalytics": McpContract(tier="1"),
    "theprotocol_getVolumeProfile": McpContract(
        tier="3",   # developer JWT
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getLockPayoutRuns": McpContract(
        tier="1",
        notes="Phase-2: list of distributions.",
    ),
    "theprotocol_getLockStats": McpContract(tier="1"),

    # --- Federation reads ---

    "theprotocol_getFederationInfo": McpContract(tier="1"),
    "theprotocol_getFederationHealthCheck": McpContract(tier="1"),
    "theprotocol_getFederationNetworkStats": McpContract(tier="1"),
    # 2026-05-26 Phase D: federation endpoints require SPIFFE mTLS peer auth
    # (require_peer_registry_identity). Dev JWT returns 401 by design — wrapper
    # packages as text envelope. Assert text presence.
    "theprotocol_getFederationPolicyCompliance": McpContract(tier="1",
        # §MCPTEST30 (V0547): the route authenticates only a federation PEER (the survey's PEER_ROUTE class), which no
        # MCP caller holds; the wrapper turned the 401 into an empty list and this contract read it as a pass on
        # every run. The refusal is what any MCP caller gets: documented 4xx. Leaving the surface or a route a
        # developer may call is his decision (PEER_ROUTE_BASELINE in test_mcp_tool_requests_meet_their_routes.py).
        expect_status="error_4xx",
        expect_error_message_contains="Federation authentication required",
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design (an admin reads the same answer through getAdminFederationPolicyCompliance)",
        # §MCPTEST30 (V0640): not pinned, so the by-design lifecycle's row decides (see listFederationRegistryCards)
    ),
    "theprotocol_getFederationSyncStatusDev": McpContract(tier="3",
        # §pass73.3.19: requires federation auth (mTLS cert / internal secret /
        # license) the MCP bridge can't present → 401. Documented 4xx.
        expect_status="error_4xx",
        expect_error_message_contains="Federation authentication required",
        # §MCPTEST30 (V0641): no longer pinned (override_coverage_fan), so earned_agent_public's by-design row reaches
        # the run (as 8fb73b27 for the two public peer-only reads); its 401 is a refusal row there
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design (an admin reads the same through getFederationSyncStatus)",
    ),

    # ========================================================================
    # Phase-3 batch (2026-05-25 night): contracts that use entities created
    # by `_phase3_setup_entities()`. Each references a `${name}` that the
    # setup phase populates. If setup fails to create that entity, the
    # unresolved-fixture detector skips with a clear reason.
    # ========================================================================

    # --- Webhooks ---
    "theprotocol_getWebhook": McpContract(
        tier="3",
        arguments={"webhook_id": "${webhook_id}"},
        expect_keys=["id", "url", "events"],
    ),
    "theprotocol_getWebhookDeliveries": McpContract(
        tier="3",
        arguments={"webhook_id": "${webhook_id}", "limit": 5},
    ),

    # --- Bundles ---
    "theprotocol_getBundleManifest": McpContract(
        tier="3",
        arguments={"bundle_id": "${bundle_id}"},
        expect_keys=["bundle_id", "bundle_kind"],
    ),

    # --- Organizations ---
    "theprotocol_getOrganization": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}"},
        expect_keys=["id", "name"],
    ),
    "theprotocol_getOrganizationBySlug": McpContract(
        tier="3",
        requires_fixtures=["organization_slug"],
        arguments={"slug": "${organization_slug}"},
        # 2026-06-02: converted error_4xx→success. Endpoint is fixed (live 200 on an
        # existing owned org); the prior 404 was full_crud clobbering organization_slug
        # with its DELETED org — that clobber is now removed (mcp_lifecycles.py), so the
        # fixture is phase-3's PERSISTENT org slug (alive through the per-tool sweep).
        expect_keys=["id", "name", "slug", "owner_id"],
        override_coverage_fan=True,
    ),
    "theprotocol_getAgentTemplate": McpContract(
        tier="3",
        requires_fixtures=["agent_template_id"],
        # §MCPTEST30 (2026-09-30): the coverage fan's invalid-input probe shadowed this contract, so every night
        # the row read NOT MEASURED ("REFUSED (HTTP 404)") although the fixture above is published by phase 3.
        # The real fixture now decides the row; an unresolved fixture still skips, and says so.
        override_coverage_fan=True,
        arguments={"template_id": "${agent_template_id}"},
        # 2026-06-02: converted autogen-skip→success. Agent templates are seeded
        # (5 on sandbox-A, e.g. "web-scraper"); phase-3 surfaces the first id as
        # agent_template_id. Returns the full template manifest.
        expect_keys=["capabilities", "endpoints", "tags", "versions"],
    ),
    "theprotocol_getAdminOperatorApplication": McpContract(
        tier="admin",
        requires_fixtures=["operator_application_id"],
        arguments={"application_id": "${operator_application_id}"},
        # §MCPTEST30 (2026-10-01): published by lifecycle_admin_fixture_harvest on the ADMIN bridge (an EXISTING
        # application, never one the sweep submits), the row keeping the shape only, so the record is measured and
        # never kept. Until now the only call was phase 6's deliberately-invalid id, read NOT MEASURED every night.
        override_coverage_fan=True, excerpt_shape_only=True,
        # 2026-06-02: a public-lifecycle read was to surface a real application_id from
        # listAdminOperatorApplications (auto-skips via requires_fixtures if none exist). §MCPSWEEP 2026-09-27: that
        # read ran on the PUBLIC bridge and never published it; it stays unpublished until the tester's result
        # excerpts are sanitized (a full application record would be kept in the run record).
        # Returns the full operator-application record.
        # §EVTYPES4: on the sandbox tier there are no operator applications, so this
        # skips. Do NOT close it by having the setup submit one — an application is
        # the front half of provisioning, which is a standing hard stop. The honest
        # state is a skip whose reason says the fixture is not attempted.
        expect_keys=["id", "name", "status", "use_case"],
    ),
    # ── §MCPTEST30 (2026-10-01) — admin lookups measured with an id that EXISTS ──
    # Each of these was called only by phase 6's deliberately-invalid id: a refusal, reported healthy with no contract,
    # so the success path of the read was never asked. lifecycle_admin_fixture_harvest takes one real id from the list
    # beside each (read-only, admin bridge); the keys below were measured on sbx-alpha (V0508) before they were
    # written. An id the frame does not have stays an unresolved fixture: a named skip, never a placeholder call.
    "theprotocol_getFederationLicenseDetail": McpContract(
        tier="admin", requires_fixtures=["federation_license_id"],
        arguments={"license_id": "${federation_license_id}"},
        expect_keys=["id", "operator_name", "licensee_type", "status", "license_key_prefix"],
        override_coverage_fan=True),
    "theprotocol_getPeerRegistryCard": McpContract(
        tier="admin", requires_fixtures=["peer_registry_id"],
        arguments={"peer_id": "${peer_registry_id}"},
        expect_keys=["peer_id", "peer_name", "peer_base_url", "cached_registry_card"],
        override_coverage_fan=True),
    "theprotocol_getTopologyPeerEvents": McpContract(
        tier="admin", requires_fixtures=["peer_registry_id"],
        arguments={"peer_id": "${peer_registry_id}", "limit": 5},
        expect_keys=["peer_id", "peer_name", "events", "count"],
        override_coverage_fan=True),
    "theprotocol_getFederationCompliancePeerByID": McpContract(
        tier="admin", requires_fixtures=["compliance_peer_id"],
        arguments={"peer_id": "${compliance_peer_id}"},
        expect_keys=["peer_registry_id", "peer_name", "federation_status", "compliance_score"],
        override_coverage_fan=True),
    "theprotocol_getFederationCompliancePeerByOperator": McpContract(
        tier="admin", requires_fixtures=["compliance_operator_id"],
        arguments={"operator_id": "${compliance_operator_id}"},
        expect_keys=["peer_registry_id", "peer_name", "federation_status", "compliance_score"],
        override_coverage_fan=True),
    "theprotocol_getBroadcastTemplateDetail": McpContract(
        tier="admin", requires_fixtures=["broadcast_template_id"],
        arguments={"template_id": "${broadcast_template_id}"},
        expect_keys=["id", "label", "title_template", "body_template", "broadcast_type"],
        override_coverage_fan=True),
    "theprotocol_getBroadcastStats": McpContract(
        tier="admin", requires_fixtures=["broadcast_id"],
        arguments={"broadcast_id": "${broadcast_id}"},
        expect_keys=["broadcast_id", "title", "read_count", "total_developers"],
        override_coverage_fan=True),
    # an INACTIVE operator answers 400 "Not an active cloud operator" (measured): the harvest takes an active one
    "theprotocol_getCloudOperatorHealth": McpContract(
        tier="admin", requires_fixtures=["active_cloud_operator_id"],
        arguments={"application_id": "${active_cloud_operator_id}"},
        expect_keys=["application_id", "name", "containers", "registry_health"],
        override_coverage_fan=True),
    "theprotocol_getOrganizationCicdSummary": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}"},
    ),
    "theprotocol_listOrganizationAgents": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}"},
    ),
    "theprotocol_listOrganizationMembers": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}"},
    ),
    "theprotocol_listOrganizationTeams": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}"},
    ),
    "theprotocol_getOrganizationTeam": McpContract(
        tier="3",
        arguments={"org_id": "${organization_id}", "team_id": "${team_id}"},
    ),

    # --- Pipelines / CI/CD ---
    "theprotocol_getCicdSummary": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getCicdDeployments": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}", "limit": 5},
    ),
    "theprotocol_getPipelineTemplates": McpContract(tier="1"),

    # --- API keys ---
    "theprotocol_getMyApiKeyDetail": McpContract(
        tier="3",
        requires_fixtures=["api_key_id"],
        arguments={"key_id": "${api_key_id}"},
        # 2026-06-02: BUG-4 RESOLVED (Commander-approved option A). There is no
        # GET-by-id route server-side (only LIST + DELETE), so the wrapper now filters
        # the key LIST by key_id (tools_developer.py get_my_api_key_detail). Returns
        # one non-secret ApiKeyRead element.
        expect_keys=["id", "key_prefix", "is_active", "created_at"],
    ),

    # --- Funding ---
    "theprotocol_getAdminFundingPending": McpContract(
        tier="admin",
        # §MCPADMSKIP-3 2026-09-07 — WAS `skip_reason="No pagination — returns ALL
        # pending (BUG-18). Re-enable when paginated."`, which is still TRUE of the
        # route (`funding_requests.py:304` takes no Query params and applies no
        # limit) but contradicted another declaration: the tool is a member of
        # `lifecycle_admin_dashboard_reads`, so it was called on every run anyway
        # and the "skip" bound nothing. Two declarations disagreeing, silently
        # resolved in favour of whichever consumer happened to run. The coverage is
        # real and the route is read-only, so the lifecycle wins and the warning
        # survives as a note instead of a switch nobody honoured.
        notes="Unpaginated by design as of 2026-09-07 (BUG-18): returns ALL pending "
              "rows. Harmless on a sandbox frame; think before pointing this at a "
              "busy production registry.",
    ),
    "theprotocol_getAdminFundingAll": McpContract(tier="admin"),

    # --- A2A payment ---
    "theprotocol_verifyPayment": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "payment_token"],
        arguments={"agent_jwt": "${sentinel_jwt}", "token": "${payment_token}"},
        expect_keys=["valid"],
        notes=("Phase-3: verify a phase-3-authorized token (token flips AUTHORIZED→CONSUMED). "
               "§EVTYPES4: this row skips because nothing publishes ${payment_token}, and that "
               "is NOT a coverage gap — mcp_lifecycles.py already drives the real path "
               "authorizePayment → verifyPayment → settlePayment against a real counterparty. "
               "Adding an authorize step to phase-3 setup just to fill this fixture would hold "
               "funds for a second, redundant token every run. Leave it skipping."),
    ),

    # --- Support tickets ---
    "theprotocol_getSupportTicketDetail": McpContract(
        tier="3",
        arguments={"ticket_id": "${support_ticket_id}"},
    ),

    # --- Governance proposals ---
    "theprotocol_getProposalDetail": McpContract(
        tier="1",
        arguments={"proposal_id": "${proposal_id}"},
        expect_keys=["id", "status", "title"],
    ),
    "theprotocol_getProposalVotes": McpContract(
        tier="3",
        arguments={"proposal_id": "${proposal_id}"},
        # 2026-05-26 Phase D.3: wrapper now normalizes list response to
        # {votes, total} envelope.
        expect_keys=["votes", "total"],
    ),
    "theprotocol_getMyVoteOnProposal": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "proposal_id"],
        arguments={"agent_jwt": "${sentinel_jwt}", "proposal_id": "${proposal_id}"},
    ),

    # --- Staking (sentinel staked 10 AVT lock=0 in setup) ---
    "theprotocol_estimateMyLockPayouts": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "sentinel_did"],
        arguments={"agent_jwt": "${sentinel_jwt}", "agent_did": "${sentinel_did}"},
        # 2026-05-26 Phase E.1: success path returns RewardEstimate model:
        # {staked_amount, tier_name, base_apy, lock_bonus_apy, total_apy,
        #  daily_reward, monthly_reward, yearly_reward} — sentinel stakes
        # 10 AVT in setup so 200 is expected. Error path: 400 "Agent has no
        # staked balance" → wrapper {error, body}. agent_did is in the URL
        # path, not the response — previous expect_keys=["agent_did"] was a
        # false claim (Phase D over-claim). Pin to the two most distinctive
        # success-path keys so a reshape would be loud.
        expect_status=200,
        expect_keys=["staked_amount", "total_apy"],
        # Pydantic v2 serializes Decimal as JSON string by default; tolerate
        # int/float too in case future config flips to numeric encoding.
        expect_types={"staked_amount": (str, int, float), "total_apy": (str, int, float)},
        notes="Phase E.1: RewardEstimate Decimal fields; sentinel pre-staked 10 AVT in fixture setup.",
    ),
    "theprotocol_claimLockPayouts": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        # Smoke (expect_status="any") BY NECESSITY. 2026-06-02: tried option-2
        # (assert a real 200 claim). A real claim needs an unclaimed StakingReward,
        # but the only in-run path — triggerLockPayoutRun after a fresh
        # flexible (lock=0) stake — is GLOBALLY day-gated: once the daily worker has
        # run for the date, the manual trigger no-ops ("Distribution already
        # completed for <date>", staking_rewards_service.py:386) and the fresh
        # sentinel (created post-00:00-UTC) is never credited → claim 400.
        # Asserting success would flip the suite red. Enabling option-2 needs a
        # PARKED financial change (force-flag on manual distribution / per-agent
        # day-gate / admin grant-reward endpoint) — see SESSION_LOG_2026-06-02.
        # Wrapper returns {amount_claimed,...} on success OR a text envelope on the
        # documented "No payouts to claim" 400; both are valid wrapper responses.
        expect_status="any",
        expect_keys=["_text"],
        expect_types={"_text": str},
    ),

    # --- Reads with admin-controlled fixtures (sandbox 1=admin) ---
    "theprotocol_getAdminDeveloperDetail": McpContract(
        tier="admin",
        arguments={"developer_id": "${developer_id}"},
        # §MCPTEST30 (V0552): held to its answer. Its route made one query per owned agent, so the tester's developer
        # (6,685 agents on sbx-alpha) timed out and the fan read the timeout as a refusal (NOT MEASURED, round 17); the
        # names now come in one statement per 5,000 agents. The answer lists every agent, so only its shape is kept.
        expect_keys=["id", "email", "agent_count", "agents", "api_keys", "organizations"],
        override_coverage_fan=True, excerpt_shape_only=True,
    ),
    "theprotocol_getAdminAgentsByDeveloper": McpContract(
        tier="admin",
        arguments={"developer_id": "${developer_id}"},
    ),
    "theprotocol_getAdminDeveloperActivity": McpContract(
        tier="admin",
        arguments={"developer_id": "${developer_id}"},
    ),
    "theprotocol_getAdminDeveloperQuota": McpContract(
        tier="admin",
        arguments={"developer_id": "${developer_id}"},
    ),
    "theprotocol_getAdminCollusionByAgent": McpContract(
        tier="admin",
        # §MCPSWEEP V0464: the tool declares agent_did (agent_id was refused by the dispatcher, measuring nothing), and
        # it now reads the rings feed filtered by that agent (the /collusion/agent/{did} route it called never existed)
        arguments={"agent_did": "${sentinel_did}"},
        expect_keys=["rings", "total_returned"],
    ),
    "theprotocol_getAdminAgentDetail": McpContract(
        tier="admin",
        arguments={"agent_id": "${sentinel_agent_id}"},
    ),
    "theprotocol_getAdminAgentFlags": McpContract(
        tier="admin",
        arguments={"agent_id": "${sentinel_agent_id}"},
    ),
    "theprotocol_getAdminAgentSigningKeys": McpContract(
        tier="admin",
        arguments={"agent_id": "${sentinel_agent_id}"},
    ),
    "theprotocol_getAgentHealthStatus": McpContract(
        tier="admin",
        expect_keys=["summary"],
        notes="pass73.3.19: was 400 — wrapper rejects 'agent_did' (unexpected kwarg). "
              "No-arg returns the fleet health summary. Dropped the bad arg → real 200.",
    ),
    "theprotocol_getAgentHealthTransitions": McpContract(
        tier="admin",
        arguments={"limit": 5},
        expect_keys=["transitions", "total_returned"],
        notes="pass73.3.19: was 400 — wrapper rejects 'agent_did'. Kept 'limit' (valid "
              "filter), dropped 'agent_did' → real 200.",
    ),

    # --- Agent-locations reads ---
    "theprotocol_getAgentLocations": McpContract(tier="1"),
    "theprotocol_getAgentLocationsEmissionPolicies": McpContract(tier="1"),
    "theprotocol_getAgentLocationsOperator": McpContract(tier="1"),
    "theprotocol_getAgentLocationsTrustedRegistries": McpContract(tier="1"),

    # --- Auto-compound (read on sentinel) ---
    "theprotocol_getPayoutRelockForAgent": McpContract(
        tier="3",   # tools_developer.py — developer JWT, takes only agent_did
        arguments={"agent_did": "${sentinel_did}"},
    ),
    "theprotocol_getMyPayoutRelock": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
    ),

    # --- TEG specific reads ---
    "theprotocol_getMyTreasuryBalance": McpContract(
        tier="3",
        notes="pass73.3.19: was tier=admin → auth-matrix flagged developer_jwt_nonadmin→200 "
              "as a wrong-tier acceptance. But the wrapper enforces DEVELOPER auth "
              "('requires developer authentication') and the tool is self-scoped ('My'). "
              "Reclassified admin→3 to match the wrapper's real tier; clears the false "
              "violation. NOTE: if system-treasury read SHOULD be admin-only, that's a "
              "wrapper-hardening review (server.py TIER sets), not a test fix.",
    ),
    "theprotocol_getFeeCollectorInfo": McpContract(tier="admin"),

    # --- Reads of public showcase ---
    "theprotocol_getPublicShowcaseCall": McpContract(
        tier="1",
        skip_reason=("§MCPSWEEP V0464: the tool now POSTs {service, input} as its route takes (it used GET, which "
                     "the route never served); the tester frame runs with the showcase disabled, so the route "
                     "answers 503 'disabled on this deployment' (measured 2026-09-27). The request shape is pinned "
                     "offline by tests/test_mcp_tool_requests_meet_their_routes.py."),
    ),

    # --- Misc reads that auto-skipped for "destructive substring match" ---
    "theprotocol_getMcpStdioBridgeJs": McpContract(tier="1"),
    "theprotocol_getMcpStdioBridgeAdminJs": McpContract(tier="1"),
    "theprotocol_mcpPassthroughGetAgentProfile": McpContract(
        tier="3",
        arguments={"agent_did": "${sentinel_did}"},
        # 2026-05-26 Phase D: real probe shows this actually returns the full
        # agent profile via the admin-passthrough route. Assert the canonical
        # profile keys.
        expect_keys=["did", "id", "name", "card_data"],
    ),

    # Add more contracts as bugs are found / phase 4 sprints land.

    # ───── §2026-06-26 — MCP-tester contract fixes (14 gaps the
    #       flow_mcp_lifecycle_complete sweep flagged at 682/706=96.6%). ALL are
    #       TEST-contract additions, NOT product bugs (verified source-grounded).
    # AGORA exchange — public listings + agent-authed reads:
    "theprotocol_getAgoraListings": McpContract(
        tier="1", expect_keys=["listings", "count"],
    ),
    "theprotocol_getMyAgoraOrders": McpContract(
        tier="2", requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["orders"],
    ),
    "theprotocol_getMyAgoraHoldings": McpContract(
        tier="2", requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["positions"],
    ),
    # AGORA admin reads (shape contracts):
    "theprotocol_adminAgoraOverview": McpContract(
        tier="admin",
        expect_keys=["venue_enabled", "listings_by_status", "orders_by_status", "trades_total", "settlement"],
    ),
    "theprotocol_adminAgoraInvariant": McpContract(
        tier="admin", expect_keys=["ok", "listings", "checked_at"],
    ),
    "theprotocol_adminAgoraParticipants": McpContract(
        tier="admin", expect_keys=["participants", "count"],
    ),
    # AGORA admin global-halt — pass halted=false (benign un-halt) + assert shape:
    "theprotocol_adminAgoraGlobalHalt": McpContract(
        tier="admin", arguments={"halted": False}, expect_keys=["global_halt"],
    ),
    # Canary fleet admin — status read + pause/resume (sandbox-benign mutations):
    "theprotocol_adminCanaryFleetStatus": McpContract(
        tier="admin", expect_keys=["mode", "fleet_paused", "local_paths", "remote_paths"],
    ),
    "theprotocol_adminCanaryFleetPause": McpContract(
        tier="admin", expect_keys=["paused", "mode"],
    ),
    "theprotocol_adminCanaryFleetResume": McpContract(
        tier="admin", expect_keys=["paused", "mode"],
    ),
    "theprotocol_adminCanaryFleetUpsertRemotePaths": McpContract(
        tier="admin",
        arguments={"paths": [{"home_registry": "Registry-A", "remote_path_id": 1,
                              "path_label": "mcp-contract-test", "interval_sec": 3600,
                              "is_active": False}]},
        expect_keys=["upserted"],
    ),
    # AGORA listing mutations need a LIVE listing_ref + change/destroy state → skip
    # (resolve listing_ref dynamically from getAgoraListings; not blind-sweepable):
    # §MCPTEST30 (2026-10-01): the three were permanent skips ("needs a live listing", "needs a throwaway listing
    # fixture"). Phase 3's scratch listing IS that fixture: lifecycle_admin_scratch_listing records phase 3's approve,
    # halts and resumes the listing, then delists it, after every public tool that trades it has run. The arguments
    # name ONLY the run's own listing; without it the fixture is unresolved and the row is a named skip, never a call
    # on another listing. Keys measured on sbx-alpha (V0508) on a leftover scratch listing, which that took to delisted.
    "theprotocol_adminAgoraApproveListing": McpContract(
        tier="admin", requires_fixtures=["scratch_listing"], arguments={"listing_ref": "${scratch_listing}"},
        expect_keys=["symbol"],
    ),
    "theprotocol_adminAgoraHaltListing": McpContract(
        tier="admin", requires_fixtures=["scratch_listing"],
        arguments={"listing_ref": "${scratch_listing}", "halted": True}, expect_keys=["symbol", "status"],
    ),
    "theprotocol_adminAgoraDelistListing": McpContract(
        tier="admin", requires_fixtures=["scratch_listing"], arguments={"listing_ref": "${scratch_listing}"},
        expect_keys=["listing_id", "orders_cancelled", "symbol"],
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # §EVTYPES2 2026-09-06 — the 158 destructive/state-changing tools
    #
    # These were the single largest coverage hole in the cloud-op sweep: 158 of its
    # 287 skips were one line, "autogen-skip: destructive/state-changing — explicit
    # contract needed". Autogen is right to refuse them (it would be guessing at a
    # tool that changes state), so each needed a contract written by hand.
    #
    # HOW EACH WAS PRODUCED. Every entry below encodes a response OBSERVED on
    # sbx-alpha, never inferred from a tool's name — this file's own rule is that a
    # wrong contract turns a skip into a FAILURE, which is worse than the skip. The
    # safe shape for a destructive tool is its REFUSAL path: call it with arguments
    # that are schema-VALID but name an entity that does not exist, and pin what
    # comes back. Schema-valid is load-bearing; a 422 from pydantic never reaches
    # the rail, so it would prove nothing about it.
    #
    # ⚠ THE PROBE WAS WRONG TWICE BEFORE IT WAS RIGHT, and both mistakes would have
    # been written down as contracts:
    #   1. it ignored the schema's declared TYPES and passed a uuid for every *_id.
    #      Nine tools whose id is an integer answered "-32603 Internal error:
    #      invalid literal for int()" — an unhandled ValueError, not a refusal.
    #      Type-aware arguments turned all nine into clean 404s.
    #   2. it classified by `result.isError` alone, so a JSON-RPC envelope error
    #      ({"code": -32001, "message": "requires agent authentication"}) read as a
    #      SUCCESS. submitDispute would have been contracted as passing while never
    #      reaching its rail.
    # A third pass fixed 29 more whose object/integer arguments were the wrong shape
    # ("spec must be an object" was the probe describing itself, not the tool).
    #
    # Three outcomes, and the third is deliberate: a tool that acts on the CALLER
    # has no entity to aim at, and a tool that cannot succeed as shipped is left
    # skipped with the defect named — contracting either green would be teaching the
    # suite to accept something it should keep reporting.
    # ═══════════════════════════════════════════════════════════════════════════

    "theprotocol_acceptContractFederated": McpContract(
        tier="2",
        # §TWOAGENT V0437: the tool is the contracts v2 provider rail and acts as the caller, so it takes no
        # upgrader_agent_did here (a DID that is not the caller's is refused before any call, which would measure
        # nothing about the route); the nonexistent contract is the v2 accept route's own 404.
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["acceptContractFederated returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_acceptOrgInvitation": McpContract(
        tier="3",
        arguments={"token": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid or expired invitation"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_activateOperator": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - PROVISIONING - HIS word"
        ),
    ),
    "theprotocol_activateVersion": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "version_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_addTeamMember": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "team_id": "00000000-0000-4000-8000-000000000000", "developer_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_agentBuilderGenerate": McpContract(
        tier="3",
        arguments={"spec": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["spec must be an object", "Field required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_agentBuilderGenerateTemplate": McpContract(
        tier="3",
        arguments={"template_spec": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["template_spec must be an object", "Field required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_agentBulkExport": McpContract(
        tier="3",
        arguments={"agent_dids": []},
        expect_status="error_4xx",
        expect_error_message_contains=["agent_dids list is required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_agentHeartbeat": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: not probed - writes agent liveness state the health checker reads"
        ),
    ),
    "theprotocol_agentRevokeAttestation": McpContract(
        tier="2",
        arguments={"attestation_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["agentRevokeAttestation returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_appendDeploymentLogs": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "deployment_id": "00000000-0000-4000-8000-000000000000", "logs": "apitest-probe"},
        expect_status="error_4xx",
        # §MCPTEST30 (V0513): since V0510 the route first checks the caller owns the agent, so an agent nobody holds
        # is refused before any deployment lookup; either refusal is the right one for these ids
        # V0551: the phrase stops before the probe's DID (the CI phrase gate cannot tell a fixed probe DID from a minted
        # one, and the stable clause is the code's own "Agent <did> not found")
        expect_error_message_contains=["Deployment not found", "Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_applyReputationSignal": McpContract(
        tier="2",
        arguments={"transaction_id": "00000000-0000-4000-8000-000000000000", "signal_value": -1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["applyReputationSignal returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_approveContractCompletion": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["approveContractCompletion returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_approveDisputeSettlement": McpContract(
        tier="3",
        arguments={"settlement_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Settlement not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
        success_path_unmeasured="held back: a settlement exists only for a ruled dispute against another registry's agent, and approving slashes it (V0641: NOT_DRIVEN)",
    ),
    # V0650 (l), approvals in the chat (agentvault2-d3, tester batch 1, Guild order gwo_2015b757c94ce69138500df6): the
    # sweep pins each tool's refusal of a room or a request that is not the caller's; the success path is a room of the
    # run's own, earned only on the nightly and proof pairs (earned_ad_chat_approvals)
    "theprotocol_requestChatApproval": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "conversation_id": "phase6-no-such-room",
                   "title": "phase-6 probe", "client_ref": "phase6-probe-ref-0001"},
        expect_status="error_4xx",
        expect_error_message_contains="conversation not found",
        success_path_unmeasured="the success path is an organization room of the run's own, earned only on the "
                                "nightly and proof pairs (earned_ad_chat_approvals)",
    ),
    "theprotocol_getChatApprovalStatus": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "approval_id": "apr_phase6_no_such"},
        expect_status="error_4xx",
        expect_error_message_contains="approval request not found",
        success_path_unmeasured="a request exists only in an organization room of the run's own, earned only on the "
                                "nightly and proof pairs (earned_ad_chat_approvals)",
    ),
    "theprotocol_decideChatApproval": McpContract(
        tier="3",
        arguments={"conversation_id": "phase6-no-such-room", "decision": "approve",
                   "approval_ids": ["apr_phase6_no_such"]},
        expect_status="error_4xx",
        expect_error_message_contains="conversation not found",
        success_path_unmeasured="a decision needs a request in an organization room of the run's own, earned only on "
                                "the nightly and proof pairs (earned_ad_chat_approvals)",
    ),
    "theprotocol_assignAgentToOrg": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_authRefresh": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - rotates the sweep's own token mid-run (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_authVerifyEmail": McpContract(
        tier="1",
        arguments={"token": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["auth/verify-email returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_authorizePayment": McpContract(
        tier="2",
        arguments={"target_agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "amount": "1", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["is not known to this registry: no agent row and no mirrored card, so i"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    # ── §FANCLAIM 2026-09-07 — THE SEVEN TOOLS THE FAN CREDITED WITH NO CONTRACT ──
    # Reported to us as "12 success paths nothing exercises". Measured: 538 tools are
    # named by a lifecycle and 261 hold no contract of any kind, so the twelve were a
    # SAMPLE found by reading. Five of them already had a hand contract (four with a
    # deliberate skip_reason the coverage fan overrode — fixed at the fan). These
    # seven had NOTHING, which is why they were invisible: a row with no contract
    # cannot contradict one. Each now DECLARES what is measured and what is not, so
    # the gap is a line in the skip census instead of an absence.
    "theprotocol_blockFederationAgent": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required". The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "reason": "apitest-probe: no such agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required"],
        # §MCPTEST30 (V0641): no longer pinned, so lifecycle_admin_destructive_safe's by-design row reaches the run
        # (ADMIN_PEER_ONLY_TOOLS); the refusal is a refusal row there
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design",
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_bridgeIssueWrapped": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required"; 503 "This feature runs on sovereign mainframes only" on an operator. The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "amount": "0", "source_frame": "apitest-no-such-frame"},
        expect_status="error",
        expect_error_message_contains=["Federation authentication required", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_bridgeRedeem": McpContract(
        tier="admin",
        # §MCPTEST30 (tester batch 2 item 2, agentvault2-d3): read on V0649: the wrapper can never succeed. The route
        # acts for the agent the wrapped units were minted to (require_agent_permission), while this admin tool sends the
        # admin's developer token (401 "Could not validate agent credentials") and an agent_did the route does not
        # declare. Left as it is on his D8 decision (tests/test_mcp_tool_requests_meet_their_routes.py KNOWN).
        success_path_unmeasured=(
            "the success path, redeeming a real bridge transaction, is exercised by nothing, and this wrapper cannot reach "
            "it: an admin tool at an agent route (it sends the admin's token; the route answers 401 for any caller that "
            "is no agent), left as it is because the Token Bridge is on the D8 retire list, his decision; its refusal is "
            "the admin destructive-safe probe's"
        ),
        notes="FANCLAIM: money rail; refusal measured, success deliberately not swept.",
    ),
    "theprotocol_bridgeUnlock": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required"; 503 "This feature runs on sovereign mainframes only" on an operator. The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"bridge_tx_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error",
        expect_error_message_contains=["Federation authentication required", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_bridgeTransfer": McpContract(
        tier="2",
        arguments={"target_agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "amount": "1", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found in federation\",\"type\":\"not_found\"},\"type\":\"https://docs.thep"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_unblockFederationAgent": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required". The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "reason": "apitest-probe: no such agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required"],
        # §MCPTEST30 (V0641): no longer pinned, so lifecycle_admin_destructive_safe's by-design row reaches the run
        # (ADMIN_PEER_ONLY_TOOLS); the refusal is a refusal row there
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design",
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_ironhandRegisterAgentProxy": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required". The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "spire_data": {"apitest": "probe"}},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required"],
        # §MCPTEST30 (V0641): no longer pinned, so lifecycle_admin_destructive_safe's by-design row reaches the run
        # (ADMIN_PEER_ONLY_TOOLS); the refusal is a refusal row there
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design",
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_ironhandDeleteAgentProxy": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): no MCP caller can succeed (the request survey's PEER_ROUTE, V0547): the route authenticates
        # only a federation peer. Measured 2026-10-02 on the frame and both operators: 401 "Federation authentication required". The refusal is
        # the contract; whether the tool stays on the surface is his decision (FINDINGS_2026-10-02_PEER_ONLY_MCP_TOOLS).
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required"],
        # §MCPTEST30 (V0641): no longer pinned, so lifecycle_admin_destructive_safe's by-design row reaches the run
        # (ADMIN_PEER_ONLY_TOOLS); the refusal is a refusal row there
        success_path_unmeasured="a federation peer's route: no MCP caller carries a peer identity, by design",
        notes="V0549: no MCP caller can succeed (PEER_ROUTE); refusal pinned on every node class.",
    ),
    "theprotocol_getCloudOperatorSelfLogs": McpContract(
        tier="admin",
        # §MCPTEST30 (V0549): measured on BOTH node classes on 2026-10-02 (round 14), so the refusal is pinned. On a frame
        # (sbx-alpha) the route answers 401 "X-Federation-License header required": it takes a cloud operator's own
        # licence, which the tool never sends. On an operator (sbxalphaop) the router is mainframe-only and answers 503.
        # No MCP caller can succeed (the request survey lists it under PEER_ROUTE); the operator's real path is
        # operatorPortalSelfLogs, measured 200 with log lines on the same run.
        expect_status="error",
        expect_error_message_contains=["X-Federation-License header required",
                                       "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0549: no MCP caller can succeed; refusal pinned on both node classes.",
    ),
    # §MCPTEST30 (V0549): the operator CLI's audit entry. Measured 2026-10-02: 400 "X-Federation-License header
    # required" on a frame (the tool sends no licence), 503 "Remote CLI audit-event emission is disabled" on an
    # operator with OPERATOR_CLI_AUDIT_EMIT_ENABLED off. No MCP caller can succeed (PEER_ROUTE).
    "theprotocol_federationCliAudit": McpContract(
        tier="admin",
        # §MCPTEST30 (V0550): the four keys the tool's schema requires; without them the dispatcher refused the call
        # (-32602) before the route could say its refusal (round 16, 2026-10-02: the run's one hard failure). Without a
        # licence the route records nothing.
        arguments={"action": "mcp-tester-refusal-probe", "cli_version": "0.0.0", "actor_host": "mcp-tester",
                   "actor_user": "mcp-tester"},
        expect_status="error",
        expect_error_message_contains=["X-Federation-License header required",
                                       "Remote CLI audit-event emission is disabled"],
        override_coverage_fan=True,
        notes="V0549: no MCP caller can succeed; the CLI calls the route with its own licence.",
    ),
    "theprotocol_cancelAccountDeletion": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - pairs with requestAccountDeletion; only meaningful after it (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_castVote": McpContract(
        tier="2",
        arguments={"proposal_id": 999999999, "vote_in_favor": False, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["Vote failed"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_changePassword": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - would change the sweep's own password mid-run (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_claimPendingAchievements": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_keys=["claimed", "message", "status"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_claimTegPayouts": McpContract(
        tier="3",   # §MCPTEST30 V0538: the route authenticates the agent's developer (was T2: every call a 401)
        skip_reason=(
            "EVTYPES2: not probed - moves value from the payout pool"
        ),
    ),
    "theprotocol_cloneAgent": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        # §MCPTEST30 (2026-09-30): this pinned "2xx on every node" for an agent that does not exist, which was the
        # ROUTE's defect (every failure answered 200 with success=false) sold as its answer: on the sandbox operator
        # the row read healthy while the route logged "not found or access denied", and the emission axis then
        # reported a missing AgentCloned for a clone that never happened. The route now answers 404 like export.
        # The success path (a real clone) is measured by lifecycle agent_clone_export_delete on the frame.
        expect_status="error_4xx",
        expect_error_message_contains=["not found"],
        success_path_unmeasured="a nonexistent agent is refused (404); a real clone is measured by lifecycle agent_clone_export_delete where lifecycles run",
        notes="EVTYPES2 probed on sbx-alpha; §MCPTEST30 refusal pinned to the route's 404.",
    ),
    "theprotocol_createApiKey": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - mints a real API key"
        ),
    ),
    "theprotocol_createArenaMatch": McpContract(
        tier="1",
        skip_reason=(
            "EVTYPES6: NOT a node disagreement — both node classes answer 200 "
            "identically. The real reason is worse: an EMPTY match_config still "
            "CREATES a match (measured: 200 with match_id, agents, mode, started, "
            "on the frame and the operator), so this tool has no non-mutating call "
            "at all and every run would leave an arena match behind. `match_config` "
            "is required and its CONTENT is not validated — worth a product look. A "
            "deliberate success contract needs a teardown, not just a fixture."
        ),
        notes="EVTYPES6: destructive-with-no-refusal-path; probed on both node classes.",
    ),
    "theprotocol_createAttestationSchedule": McpContract(
        tier="2",
        arguments={"circuit_id": "00000000-0000-4000-8000-000000000000", "interval_hours": 999999999, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["createAttestationSchedule returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createBundle": McpContract(
        tier="3",
        arguments={"bundle_data": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["bundle_data must be an object", "Field required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createDeveloperApikeyMe": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - mints a real API key for the sweep's developer"
        ),
    ),
    "theprotocol_createFederationPeer": McpContract(
        tier="3",
        arguments={"peer_data": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["peer_data must be an object", "Field required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createFrameInvitation": McpContract(
        tier="3",
        arguments={"trust_domain": "apitest-probe", "bundle_endpoint_url": "https://nonexistent.invalid", "federation_endpoint_url": "https://nonexistent.invalid", "name": "apitest destructive-contract probe", "contact_email": "apitest-probe@nonexistent.invalid", "initiator_nonce": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["String should match pattern '^"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createMalpracticeDispute": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "reason": "apitest destructive-contract probe", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["createMalpracticeDispute returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createOrganization": McpContract(
        tier="3",
        arguments={"name": "apitest destructive-contract probe"},
        expect_keys=["created_at", "description", "id", "is_active", "limits", "logo_url"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createOrganizationTeam": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "name": "apitest destructive-contract probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createPipeline": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "pipeline_name": "apitest-probe", "pipeline_config": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["agent_did, pipeline_name, and pipeline_config (object) are required", "Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createProposal": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: takes no entity argument, so there is nothing non-existent "
            "to aim at - MEASURED succeeding on sandboxdelta 2026-09-05 (created proposal id=1 in VOTING). "
            "It refuses on sbx-alpha only because that node has no funded sentinel "
            "agent; contracting that refusal makes the suite DO the thing on any "
            "node that has one. Needs a deliberate success contract with a "
            "side_effect_assert and its own funded fixture, not a refusal."
        ),
        notes="EVTYPES2: destructive-with-no-target; see the section header.",
    ),
    "theprotocol_createTegPoliciesBatch": McpContract(
        tier="3",
        arguments={"policies": []},
        expect_status="error_4xx",
        expect_error_message_contains=["policies (non-empty list) is required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createTegPolicy": McpContract(
        tier="3",
        arguments={"policy_code": "apitest-probe", "policy_name": "apitest-probe", "policy_type": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid policy_type. Must be one of:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createVersion": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "version": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_createWebhook": McpContract(
        tier="3",
        arguments={"url": "https://nonexistent.invalid", "events": []},
        expect_status="error_4xx",
        expect_error_message_contains=["events must be a non-empty list of event type strings"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_crossRegistryContractProxy": McpContract(
        tier="2",
        # §TWOAGENT V0437: the v2 provider rail, as the caller; a nonexistent contract is the accept route's 404
        arguments={"action_data": {"contract_id": "00000000-0000-4000-8000-000000000000", "action": "accept"},
                   "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["crossRegistryContractProxy returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_crossTegBalanceSync": McpContract(
        tier="2",
        arguments={"notification": {}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["notification must be an object", "crossTegBalanceSync returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_customizeFlare": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES6: the nodes DO differ here, but not by node CLASS — by DATA. "
            "Measured with an empty customizations object: 200 on the frame, whose "
            "developer holds a backer flare, and 403 'You don't have a backer flare "
            "to customize yet' on the operator, whose developer does not. That is a "
            "fixture property, so it would flip the moment either developer's flare "
            "state changed, and neither outcome is wrong. Closing it needs a "
            "flare-granting fixture step, not a contract."
        ),
        notes="EVTYPES6: outcome depends on the caller's flare, not on the node class.",
    ),
    "theprotocol_deleteBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Bundle not found or not yours"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteFederationPeerSelf": McpContract(
        tier="3",
        arguments={"peer_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be a valid integer, unable to parse string as an integer", "Peer registry not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteMyAgent": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: not probed - deletes the sentinel agent every later tool depends on"
        ),
    ),
    "theprotocol_deleteMyAgentByDev": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent not found or not authorized"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteMyApiKey": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - deletes an API key; could delete the one the "
            "sweep is authenticating with (same risk as revokeApiKey)"
        ),
    ),
    "theprotocol_deleteOrganization": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteOrganizationTeam": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "team_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deletePipeline": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "pipeline_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteVersion": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "version_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_deleteWebhook": McpContract(
        tier="3",
        arguments={"webhook_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_depositReputationBond": McpContract(
        tier="2",
        arguments={"amount": 1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["depositReputationBond returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    # §BATCH0911 item 4 — no argument can make this refusal structural (the tool acts on the
    # CALLER's own bond), so a refusal contract would perform the unlock on any node where the
    # sentinel's bond had matured (feedback: a refusal contract can become an action).
    "theprotocol_unlockReputationBond": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: not probed - moves value: it unlocks the caller's matured bond share (escrow -> funder, once per bond) and takes no entity argument, so there is nothing non-existent to aim at. Proven through the real dispatcher by tests/test_mcp_unlock_bond_wire.py."
        ),
    ),
    "theprotocol_disable2FASelf": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - mutates the sweep's own auth posture (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_disableMyAttestationSchedule": McpContract(
        tier="2",
        arguments={"schedule_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["disableMyAttestationSchedule returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_disableMyMtls": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: not probed - changes the sweep agent's mTLS enrolment "
            "(IRONHAND state), the reverse of enableMtls"
        ),
    ),
    "theprotocol_downloadBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Bundle not found or not accessible"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_downloadBundleViaOnboard": McpContract(
        tier="3",
        arguments={"bundle_data": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["bundle_data must be an object", "Field required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_downloadPipelineTemplate": McpContract(
        tier="3",
        arguments={"template_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Template not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_enableMtls": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: not probed - changes the sweep agent's mTLS enrolment (IRONHAND state)"
        ),
    ),
    "theprotocol_equipFlare": McpContract(
        tier="3",
        arguments={"slot": "corner", "agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid slot 'apitest-probe'. Use 'corner' or 'encirclement'", "You have no corner flare to equip. Pick one in /flare-manager first"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_exportAgentDev": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["An internal error occurred"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_federationProposeRaise": McpContract(
        tier="3",
        # §MCPGOVFIX 2026-09-07 — the EVTYPES2 skip ("sends a body missing a field the
        # endpoint requires … cannot succeed as shipped") was a correct reading of a
        # PRODUCT defect, so it could never be closed from this file. Fixed at the
        # tool: it now sends `local_proposal_id`, the field `FederationProposeRequest`
        # declares. What stays uncoverable is the SUCCESS path — elevating a proposal
        # to the federation is destructive and needs a PASSED local proposal — so this
        # pins the reachable refusal against a proposal id that does not exist.
        arguments={"proposal_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Local proposal not found"],
        notes="MCPGOVFIX: MEASURED on sbx-alpha 2026-09-07 — with the body key "
              "corrected, POST /governance/federation/propose {local_proposal_id: "
              "999999999} answers 404 'Local proposal not found' (governance.py:791). "
              "The 422 'Field required' is gone; it was the tool's body key, not the "
              "caller's argument.",
        success_path_unmeasured="held back: raising elevates a passed local proposal to every frame (V0641: its row, lifecycle_federation_safe_paths)",
    ),
    "theprotocol_federationSlashConfirmation": McpContract(
        tier="3",
        arguments={"settlement_id": "00000000-0000-4000-8000-000000000000", "status": "apitest-probe", "amount": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required (mTLS certificate, internal secret,"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
        success_path_unmeasured="a federation peer's route (the defendant's home confirms a slash): no MCP caller carries a peer identity, by design",   # §MCPTEST30 (V0641): its by-design row, earned_agent_public
    ),
    "theprotocol_federationSlashRequest": McpContract(
        tier="3",
        arguments={"settlement_id": "00000000-0000-4000-8000-000000000000", "dispute_id": 999999999, "ruling": "apitest-probe", "amount": 999999999, "complainant_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "defendant_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "origin_registry_url": "https://nonexistent.invalid", "callback_url": "https://nonexistent.invalid"},
        expect_status="error_4xx",
        expect_error_message_contains=["Federation authentication required (mTLS certificate, internal secret,"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
        success_path_unmeasured="a federation peer's route (the complainant's home asks for a slash): no MCP caller carries a peer identity, by design",   # §MCPTEST30 (V0641): its by-design row, earned_agent_public
    ),
    "theprotocol_federationSyncRequest": McpContract(
        tier="2",
        arguments={"request_data": {}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["request_data must be an object", "federationSyncRequest returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_federationVetoProposal": McpContract(
        tier="3",
        # §MCPGOVFIX 2026-09-07 — same shape: the EVTYPES2 skip named a real product
        # defect (integer argument, UUID path → 422 uuid_parsing, no argument could
        # satisfy both), which is why it sat as a permanent finding. Fixed at the tool
        # (str, no coercion, schema corrected to match its sibling
        # federationVoteProposal). The success path is a COMMANDER VETO and stays
        # deliberately undriven; this pins the refusal for a well-formed UUID that
        # names no proposal.
        arguments={"proposal_id": "00000000-0000-4000-8000-000000000000",
                   "reason": "apitest-probe"},
        expect_status="error_4xx",
        # Both node classes, because they refuse at DIFFERENT depths — the rule this
        # file states three entries above ("probed on the mainframe AND the operator")
        # and which I broke by measuring only the frame. The suite caught it as a
        # hard FAIL on the cloud-op sweep, which is the gate working.
        expect_error_message_contains=[
            "Federation proposal not found",                      # frame: 400, reached the ES
            "Only mainframe admin can veto federation proposals",  # operator: 403, refused earlier
        ],
        notes="MCPGOVFIX: MEASURED on BOTH classes 2026-09-07. Operator: 403 "
              "'Only mainframe admin can veto federation proposals' — it never reaches "
              "the EventStore. Frame: POST …/proposals/"
              "00000000-0000-4000-8000-000000000000/veto answers 400 with detail "
              "'EventStore: {\"detail\":\"Federation proposal not found\"…}'. The "
              "phrase pinned is the EventStore's own sentence, not the wrapper's "
              "status line, and it stops before any id.",
        success_path_unmeasured="held back: a veto ends a federation proposal everywhere, and no run holds one (V0641: its row, lifecycle_federation_safe_paths)",
    ),
    "theprotocol_federationVoteProposal": McpContract(
        tier="2",
        arguments={"proposal_id": "00000000-0000-4000-8000-000000000000", "vote": "FOR", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["federationVoteProposal returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_finalizeFrameInvitation": McpContract(
        tier="3",
        arguments={"invitation_id": "00000000-0000-4000-8000-000000000000", "approver_trust_domain": "phase6.invalid",
                   "approver_bundle_endpoint_url": "https://phase6.invalid/bundle", "approver_name": "phase6",
                   "approver_bundle_pem": "phase6-not-a-bundle-pem", "nonce_echo": "0" * 32},
        expect_status="error_4xx",
        expect_error_message_contains=["Invitation not found"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
        success_path_unmeasured="held back: finalizing federates two frames (V0641: its row, earned_agent_public.NOT_DRIVEN)",
    ),
    "theprotocol_flareCelebrationAcknowledge": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - mutates the caller's own flare state"
        ),
    ),
    "theprotocol_forkBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000"},
        expect_keys=["errors", "install_id", "produced_agents", "success", "warnings"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_getAttestationBundle": McpContract(
        tier="3",
        arguments={"attestation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Attestation not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_getAttestationDetail": McpContract(
        tier="3",
        arguments={"attestation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Attestation not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_getDeployment": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "deployment_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_getFederationDisputeSettlement": McpContract(
        tier="3",
        arguments={"settlement_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Settlement"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
        success_path_unmeasured="no run makes a settlement: one exists only for a ruled dispute against another registry's agent (V0641: NOT_DRIVEN)",
    ),
    "theprotocol_getFederationDisputeSettlements": McpContract(
        tier="3",
        expect_keys=["count", "settlements", "stats"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_getMyFundingRequests": McpContract(
        tier="2",
        arguments={"agent_jwt": "${sentinel_jwt}"},
        expect_keys=["requests", "total"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_importAgent": McpContract(
        tier="3",
        # a dry run of an empty export: nothing can be created, and the route names what the export lacks
        arguments={"agent_config": {}, "options": {"dry_run": True}},
        expect_status="success",
        expect_keys=["success", "errors"],
        success_path_unmeasured="an empty export in a dry run is refused in a 200 (success=false); a real import is exercised by nothing",
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
    ),
    "theprotocol_inviteOrganizationMember": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "email": "apitest-probe@nonexistent.invalid"},
        expect_status="error_4xx",
        expect_error_message_contains=["value is not a valid email address: The part after the @-sign is a spe"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_logEnhancedDispute": McpContract(
        tier="2",
        arguments={"defendant_agent_id": "00000000-0000-4000-8000-000000000000", "reason_code": "UNFAIR_FEE", "brief_description": "apitest destructive-contract probe", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["logEnhancedDispute returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_logTegDispute": McpContract(
        tier="2",
        arguments={"defendant_agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "reason_code": "apitest-probe", "brief_description": "apitest destructive-contract probe", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=[
            # the rail's own sentence, wherever the detail survives the wrapper …
            "is not known to this registry: no agent row and no mirrored card",
            # … and the wrapper's summary where it does not. MEASURED on both
            # operators: `_agent_post` renders {"_text": "logTegDispute returned
            # HTTP 404"} and the RFC7807 detail never reaches the caller, so
            # pinning only the rail's sentence fails on the very node class this
            # contract exists to exercise. Weak by the gate's count, and the
            # honest alternative — the B6 envelope class, one tool over.
            # ⚠ NO status code in it: my first attempt pinned "... HTTP 404" and
            # the phrase gate refused it in the same breath ("a bare HTTP status
            # code — node-specific"). It was right; the code is what differs
            # between a mainframe and an operator, and the code is the one part
            # of this sentence the contract must not depend on.
            "logTegDispute returned HTTP",
        ],
        notes=("§EVTYPES2 measured a 2xx here on every node that could reach it, and "
               "recorded it as expected: the TEG dispute-log rail forwarded "
               "`defendant_agent_did` to the TEG with no lookup, so a real TEG-side "
               "dispute was filed against a DID nobody knows. A contract can be right "
               "about the rail and still be documenting a hole — this one was. "
               "⚠ SCOPE, measured rather than assumed: that happened on the OPERATOR "
               "sweeps, where this contract actually runs. On the flagship the row is "
               "decided by phase-3 setup, which calls the same tool with a REAL "
               "defendant (`_defendant != sentinel_did`), so the frame files a "
               "legitimate fixture and this contract never executes there. "
               "§EVTYPES8 2026-09-06: relayed to agentvault2-27 as the sibling of the "
               "registry-rail guard they had just shipped, and closed at the source in "
               "973c3d8 — /teg/disputes/log now asks the same two-table question "
               "(native row OR active mirrored card) BEFORE minting the TEG token. "
               "The probe is unchanged and the expectation is inverted: same call, and "
               "now it writes NOTHING. The phrase carries no identifier and no status, "
               "so it is portable; both node classes carry the guard because the frames "
               "and both operators moved onto the same image together."),
    ),
    "theprotocol_logoutSession": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - acts on the CALLER's session - a probe would log the sweep out mid-run (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_markContractFailed": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["markContractFailed returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_markNotificationRead": McpContract(
        tier="3",
        arguments={"broadcast_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be a valid integer, unable to parse string as an integer", "Broadcast not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_moveFlare": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:", "You don't have a backer flare yet"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_oauthIntrospect": McpContract(
        tier="3",
        arguments={"token": "00000000-0000-4000-8000-000000000000", "client_id": "00000000-0000-4000-8000-000000000000", "client_secret": "apitest-probe-not-a-real-secret"},
        expect_status="error_5xx",
        expect_error_message_contains=["Cross-registry OAuth federation is not enabled on this registry (no ac"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_oauthTokenExchange": McpContract(
        tier="3",
        arguments={"subject_token": "00000000-0000-4000-8000-000000000000", "subject_token_type": "00000000-0000-4000-8000-000000000000", "client_id": "00000000-0000-4000-8000-000000000000", "client_secret": "apitest-probe-not-a-real-secret"},
        expect_status="error_5xx",
        expect_error_message_contains=["Cross-registry OAuth federation is not enabled on this registry (no ac"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_patchBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000", "updates": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["bundle_id and updates object are required", "Bundle not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_previewSlashReductionAttestation": McpContract(
        tier="3",
        arguments={"dispute_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be a valid integer, unable to parse string as an integer", "Dispute not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_previewVotingPowerAttestation": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="success",
        expect_keys=["agent_did", "multiplier"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
    ),
    "theprotocol_purchasePipelineTemplate": McpContract(
        tier="3",
        arguments={"template_id": "00000000-0000-4000-8000-000000000000", "buyer_did": "did:theprotocol:phase6-no-such"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
    ),
    "theprotocol_rateBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000", "rating": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be less than or equal to 5", "Referenced record does not exist"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_regenerateBackupCodes": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - rotates the sweep's own 2FA backup codes (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_rejectDisputeSettlement": McpContract(
        tier="3",
        arguments={"settlement_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Settlement not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
        success_path_unmeasured="no run makes a settlement: one exists only for a ruled dispute against another registry's agent (V0641: NOT_DRIVEN)",
    ),
    "theprotocol_relayAction": McpContract(
        tier="3",
        # §MCPTEST30 V0538: Tier 3 (the route authenticates the agent's developer). This pinned "relayAction returned
        # HTTP", the 401 every call met while the tool sent the agent's token: a pass that could not fail. A relay tool
        # the route does not offer is refused before anything is dialled, which is the refusal it can measure here.
        arguments={"agent_did": "${sentinel_did}", "action_payload": {"tool": "relay_phase6", "arguments": {}}},
        requires_fixtures=["sentinel_did"],
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid relay tool"],
        success_path_unmeasured="an unknown relay tool is refused (400); starting a relay needs an agent that declares one",
    ),
    "theprotocol_releasePayment": McpContract(
        tier="2",
        arguments={"token": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["release failed"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_releasePaymentById": McpContract(
        tier="2",
        arguments={"token_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["releasePaymentById returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_removeOrganizationMember": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "developer_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_removeTeamMember": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "team_id": "00000000-0000-4000-8000-000000000000", "developer_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_replySupportTicket": McpContract(
        tier="3",
        arguments={"ticket_id": "00000000-0000-4000-8000-000000000000", "message": "apitest destructive-contract probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be a valid integer, unable to parse string as an integer", "Ticket not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_reportBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000", "reason": "apitest destructive-contract probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid reason_code. Allowed:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_requestAccountDeletion": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - schedules deletion of the sweep's own developer account (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_requestFrame": McpContract(
        tier="3",
        arguments={"request_data": {}},
        # "error": a frame refuses the empty request 422; an operator answers the mainframe gate, 503 up to V0639 and
        # 404 "mainframe_only: <the sentence>" from V0640 (D6-820). Judged by the sentence either way.
        expect_status="error",
        expect_error_message_contains=["request_data must be an object", "Field required", "This feature runs on sovereign mainframes only. Cloud-operators federa"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_requestSelfRevocation": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - revokes the calling agent's own identity"
        ),
    ),
    "theprotocol_resetAgentCredentialsOnboard": McpContract(
        tier="3",
        # a password that is not the runner's: the route refuses before it looks at the agent
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "password": "phase6-not-the-password"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid password"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
    ),
    "theprotocol_resolveTegDispute": McpContract(
        tier="2",
        # §MCPTEST30 V0538: this pinned "Could not validate agent credentials", the 401 every call met while the tool sent
        # the developer's token to an agent route. Tier 2 now.
        # V0545: the TEG takes the registry's mTLS identity as its admin, so the route itself refuses every caller before it
        # forwards (its old gate, disputes.file, is a birth permission; only a body-vs-query slip, the TEG's 422 on every
        # call, stood in between). "Dispute not found" is no longer an answer this route can give: it would mean the call
        # reached the TEG again, so it is not accepted here. A dispute nobody filed, so even a reopened door moves nothing.
        arguments={"dispute_id": "00000000-0000-4000-8000-000000000000", "resolution": "RESOLVED_NO_ACTION",
                   "agent_jwt": "${sentinel_jwt}"},
        requires_fixtures=["sentinel_jwt"],
        expect_status="error_4xx",
        expect_error_message_contains=["Not authorized to resolve disputes", "lacks required permission"],
        success_path_unmeasured="no caller resolves a TEG dispute through the registry: the route refuses every caller",
    ),
    "theprotocol_restoreBundle": McpContract(
        tier="3",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="success",
        expect_keys=["success", "errors"],
        success_path_unmeasured="a nonexistent bundle is refused in a 200 (success=false, 'Bundle not found'); a real restore is exercised by nothing",
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27.",
    ),
    "theprotocol_restoreFromUpload": McpContract(
        tier="3",
        arguments={"bundle_b64": "cGhhc2U2LW5vdC1hLWJ1bmRsZQ=="},   # base64("phase6-not-a-bundle")
        expect_status="success",
        expect_keys=["success", "errors"],
        success_path_unmeasured="bytes that are not a bundle are refused in a 200 (success=false, 'Invalid bundle'); a real restore is exercised by nothing",
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27. The tool now sends the multipart upload the route takes.",
    ),
    "theprotocol_reverifyAttestation": McpContract(
        tier="1",
        arguments={"attestation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Attestation not found"],
        notes=("§EVTYPES6: the old reason said 'no stable message to pin'. There is "
               "one — the earlier probe just never aimed at the entity. A "
               "non-existent attestation_id answers 404 'Attestation not found', "
               "identically on a mainframe and a cloud operator, and re-verifying "
               "nothing writes nothing."),
    ),
    "theprotocol_revokeApiKey": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - could revoke the key the sweep is authenticating with"
        ),
    ),
    "theprotocol_rollbackVersion": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "version_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_rotateFederationLicenseSelf": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - rotates this registry's federation licence"
        ),
    ),
    "theprotocol_rotateMySigningKey": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - rotates the sweep agent's signing key"
        ),
    ),
    "theprotocol_selectFlare": McpContract(
        tier="3",
        arguments={"selection": {}},
        # §MCPTEST30 (2026-09-30): lifecycle_flare's phoenix probe (403, not earned) shadowed this contract and the
        # row read NOT MEASURED every night; the empty selection below is a real 200 of the tool (it returns the
        # caller's flare state), so it decides the row. Selecting an EARNED flare is still unmeasured.
        override_coverage_fan=True,
        expect_status="success",
        expect_keys=["flare_tier", "selected_corner_flare", "unlocked_corner_flares"],
        notes=("§EVTYPES6: the 'nodes disagree' verdict was an artifact of probing "
               "the SUCCESS path with a valid, mutating payload — the half a "
               "per-node flag changes. An EMPTY selection changes nothing and "
               "returns the caller's flare state, 200 on both node classes."),
    ),
    "theprotocol_selfProvisionOperator": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - PROVISIONING - HIS word (CLAUDE.md: M6 provisioning LAST and HIS)"
        ),
    ),
    "theprotocol_setFlareCornerVariant": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "variant": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_setFlareOverlay": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "overlay": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Unknown encirclement overlay 'apitest-probe'. Valid:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_setFlareVariant": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "variant": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Unknown encirclement variant 'apitest-probe'. Valid:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_settlePayment": McpContract(
        tier="2",
        arguments={"token": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["settle failed"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_setup2FA": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - would enable 2FA on the sweep's own account and break every later login (its success path is measured by lifecycle self_account_on_throwaway, on the run's own throwaway account)"
        ),
    ),
    "theprotocol_submitAttestation": McpContract(
        tier="2",
        # §MCPTEST30 V0614 (2026-10-14, agentvault2-5b's finding): since V0612 (§ZKV2) a v2.0.0 circuit refuses a
        # submission without public_inputs.reference_label with a 422 BEFORE anything is verified or written
        # (routers/attestations.py submit_attestation), so the refusal is measurable and writes nothing. The row read
        # skipped 422 on every nightly since V0612 under EVTYPES6's reason, which described V0611 and older (an unknown
        # circuit answered 200 'failed' and wrote a row). The success path is the zk-v2 lifecycle (zk_v2_attestations,
        # 15 rows on a throwaway agent's proofs).
        arguments={"circuit_id": "fairMarkupPolicy/v2.0.0",
                   "proof_data": {"proof_bytes": "AA==", "format": "ultra_honk"},
                   "public_inputs": {},
                   "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        # the status class only (phrase hygiene: a bare code is node-specific), and the product's own sentence, which the
        # route says on every node (the attestations router is mounted unconditionally in main.py)
        expect_error_message_contains=["submitAttestation returned HTTP", "reference_label is required"],
        notes="V0614: the no-label refusal (422, nothing written); V0611's EVTYPES6 skip no longer describes the route.",
    ),
    "theprotocol_submitContractWork": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "pr_url": "https://nonexistent.invalid", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["submitContractWork returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitContractWorkFederated": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "pr_url": "https://nonexistent.invalid", "registry_url": "https://nonexistent.invalid", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["submitContractWorkFederated returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitDispute": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "sentinel_did"],
        arguments={"agent_jwt": "${sentinel_jwt}",
                   "complainant_did": "${sentinel_did}",
                   "defendant_did": "${sentinel_did}",
                   "description": "apitest contract probe — must never be filed"},
        expect_status="error_4xx",
        expect_error_message_contains=["cannot be the same agent"],
        notes=("§EVTYPES6: the old reason quoted a truncated 401 as 'no stable "
               "message'. The 401 was the PROBE — it passed no agent JWT, and "
               "submitDispute's schema advertises none, though the dispatcher pops "
               "an inline `agent_jwt` for every TIER2 tool regardless. With one, "
               "the rail answers, and the SELF-DISPUTE guard is the only refusal "
               "that writes nothing: MEASURED 400 'complainant and defendant cannot "
               "be the same agent' on a mainframe AND a cloud operator. "
               "⚠ DO NOT 'improve' this to two distinct non-existent DIDs — that was "
               "measured too, and it answered 200: the rail did NOT verify the "
               "defendant existed, so the suite would have filed a real dispute "
               "against a nobody on every run. "
               "§EVTYPES8 2026-09-06: that hole is CLOSED at the source — "
               "agentvault2-27 took the measurement as §DIDWIDEN-1 and "
               "routers/disputes.py now answers 404 'Defendant <did> is not known "
               "to this registry: no agent row and no mirrored card'. The probe "
               "stays the SELF-DISPUTE 400 anyway, and the reason changed: it is no "
               "longer 'the only refusal that writes nothing' but 'the only refusal "
               "every node can make'. The 400 is raised before the lookup on any "
               "image; the 404 exists only where that commit landed, and the "
               "operators lag the frame by design. Pin the 404 when both node "
               "classes carry it, not before."),
    ),
    "theprotocol_submitDisputeEvidence": McpContract(
        tier="2",
        arguments={"dispute_id": "00000000-0000-4000-8000-000000000000", "evidence_data": {}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["evidence_data must be an object", "submitDisputeEvidence returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitFundingRequest": McpContract(
        tier="2",
        arguments={"amount": "1", "reason": "apitest destructive-contract probe", "agent_jwt": "${sentinel_jwt}"},
        expect_keys=["approved_amount", "created_at", "funded_at", "funding_transaction_id", "id", "reason"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitOnboardRegister": McpContract(
        tier="2",
        arguments={"registration_data": {}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["registration_data must be an object", "submitOnboardRegister returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitSupportTicket": McpContract(
        tier="3",
        arguments={"subject": "apitest-probe", "message": "apitest destructive-contract probe"},
        expect_keys=["category", "created_at", "developer_id", "id", "messages", "priority"],
        # EVTYPES2 probed -> 2xx on every node that could reach it
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_submitTegAttestation": McpContract(
        tier="2",
        arguments={"attestation_data": {}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["attestation_data must be an object", "submitTegAttestation returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_tallyProposal": McpContract(
        tier="2",
        arguments={"proposal_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["tallyProposal returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_tegCrossRegistryTransferDirect": McpContract(
        tier="2",
        arguments={"receiver_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "amount": "1", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["tegCrossRegistryTransferDirect returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_tegReputationSignal": McpContract(
        tier="2",
        arguments={"transaction_id": "00000000-0000-4000-8000-000000000000", "signal_value": -1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["tegReputationSignal returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_tegLockDirect": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: takes no entity argument, so there is nothing non-existent "
            "to aim at - MEASURED succeeding on sandboxdelta 2026-09-05 (a real stake_id). "
            "It refuses on sbx-alpha only because that node has no funded sentinel "
            "agent; contracting that refusal makes the suite DO the thing on any "
            "node that has one. Needs a deliberate success contract with a "
            "side_effect_assert and its own funded fixture, not a refusal."
        ),
        notes="EVTYPES2: destructive-with-no-target; see the section header.",
    ),
    "theprotocol_tegSystemTransfer": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES2: takes no entity argument, so there is nothing non-existent "
            "to aim at - MEASURED succeeding on sandboxdelta 2026-09-05 (transfer completed to teg_system_treasury). "
            "It refuses on sbx-alpha only because that node has no funded sentinel "
            "agent; contracting that refusal makes the suite DO the thing on any "
            "node that has one. Needs a deliberate success contract with a "
            "side_effect_assert and its own funded fixture, not a refusal."
        ),
        notes="EVTYPES2: destructive-with-no-target; see the section header.",
    ),
    "theprotocol_tegUnlockDirect": McpContract(
        tier="2",
        arguments={"stake_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["tegUnlockDirect returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_testDeveloperWebhookAlt": McpContract(
        tier="3",
        arguments={"webhook_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_testWebhook": McpContract(
        tier="3",
        arguments={"webhook_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_triggerDeployment": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "environment": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_triggerFederationSync": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - kicks the federation sync worker for the whole node"
        ),
    ),
    "theprotocol_triggerLockPayoutRun": McpContract(
        tier="3",
        skip_reason=(
            "EVTYPES2: not probed - moves value: fires a lock payout distribution"
        ),
    ),
    "theprotocol_unassignAgentFromOrg": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_unequipFlare": McpContract(
        tier="3",
        arguments={"slot": "corner", "agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid slot 'apitest-probe'. Use 'corner' or 'encirclement'", "Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_unlockUnits": McpContract(
        tier="2",
        arguments={"stake_id": "00000000-0000-4000-8000-000000000000", "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found, already unlocked, or does not belong to this agent"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updatePayoutRelock": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "enabled": False},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent not found or you don't have permission"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updateDeploymentStatus": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "deployment_id": "00000000-0000-4000-8000-000000000000", "status": "apitest-probe"},
        expect_status="error_4xx",
        # §MCPTEST30 (V0513): the ownership check comes first since V0510 (see appendDeploymentLogs)
        # V0551: the phrase stops before the probe's DID (the CI phrase gate cannot tell a fixed probe DID from a minted
        # one, and the stable clause is the code's own "Agent <did> not found")
        expect_error_message_contains=["Deployment not found", "Agent did:theprotocol:"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updateFederationPeer": McpContract(
        tier="3",
        arguments={"peer_id": "00000000-0000-4000-8000-000000000000", "updates": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["peer_id and updates object are required", "Input should be a valid integer, unable to parse string as an integer"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updateMyDeveloperProfile": McpContract(
        tier="3",
        arguments={"profile_updates": {"__apitest_nonexistent_field__": "x"}},
        expect_status="success",
        expect_keys=["id", "email", "name"],
        notes=("§EVTYPES6: 200 on both node classes, and the field is SILENTLY "
               "DROPPED — the 'a body whose fields the schema does not declare is "
               "dropped and the endpoint still answers 200' class, confirmed here "
               "rather than assumed. That is why this argument is safe: the tool is "
               "DESTRUCTIVE by its own description, and an undeclared field is the "
               "one payload that reaches the rail and writes nothing. The assertion "
               "is that the developer identity still comes back."),
    ),
    "theprotocol_updateOrganization": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["at least one field to update is required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updateOrganizationTeam": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "team_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["at least one field to update is required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updatePeerSlashConfig": McpContract(
        tier="3",
        arguments={"peer_id": "00000000-0000-4000-8000-000000000000", "config": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["peer_id and config object are required", "Input should be a valid integer, unable to parse string as an integer"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updatePipeline": McpContract(
        tier="3",
        arguments={"agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000", "pipeline_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["at least one field to update is required"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_updateWebhook": McpContract(
        tier="3",
        arguments={"webhook_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["at least one field must be provided to update"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_validateAgentCard": McpContract(
        tier="3",
        arguments={"card": {}},
        expect_status="success",
        expect_keys=["is_valid"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27. The validator answers is_valid=false for an empty card: its success path.",
    ),
    "theprotocol_validateAgentImport": McpContract(
        tier="3",
        arguments={"agent_config": {}},
        expect_status="success",
        expect_keys=["success", "errors"],
        notes="§MCPSWEEP V0464: EVTYPES2 pinned 'Field required', which was the TOOL's defect (it never sent the field) rather than the route's refusal of the entity; the tool is fixed and this pins the real answer, measured live on sbx-alpha 2026-09-27. The validator names what the export lacks (success=false): its success path.",
    ),
    "theprotocol_verify2FA": McpContract(
        tier="3",
        arguments={"code": "apitest-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["String should match pattern '^"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),
    "theprotocol_verifyPublicAttestationBundle": McpContract(
        tier="1",
        arguments={"bundle": {}},
        expect_status="error_4xx",
        expect_error_message_contains=["bundle must be an object", "verifyPublicAttestationBundle returned HTTP"],
        # EVTYPES2 probed on the mainframe AND the operator with a non-existent
        # entity; both refusals pinned
        notes="EVTYPES2: probed on sbx-alpha; see the section header.",
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # §EVTYPES3 2026-09-06 — the "default contract" tools
    #
    # Autogen refuses a tool with REQUIRED params (it would be guessing), so these
    # rode a generated default that asserted almost nothing. Each entry below was
    # PROBED on the central sandbox AND on cloud-op-sbxalphaop-registry with
    # type-correct arguments naming an entity that does not exist; both nodes
    # agreed on every one.
    #
    # No phrase carries a status code. expect_status already asserts the class via
    # the code_int range check, and the two node classes genuinely differ:
    # submitContractMilestone answers 404 on central and 503 on an operator (the
    # sweep intercepts a cloud-op 503 as tier-gating, so error_4xx still holds).
    # Four of these pin a real product sentence ("Organization not found",
    # "conversation not found", "organization not found" — note the case differs
    # between the org rail and the exchange rail, and `contains` is case-sensitive).
    #
    # ⚠ guildPostOrder is NOT here, deliberately — see its skip below.
    # ═══════════════════════════════════════════════════════════════════════════
    "theprotocol_getOrgPublicFeed": McpContract(
        tier="1",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["No public feed"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getOrgTrackRecord": McpContract(
        tier="1",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_listOrganizationInvitations": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_withdrawOrganizationInvitation": McpContract(
        tier="3",
        arguments={"org_id": "00000000-0000-4000-8000-000000000000", "invitation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Organization not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_readThread": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["readThread returned HTTP"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_sendChatMessage": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000", "body": "apitest contract probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["sendChatMessage returned HTTP"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_respondChatRequest": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000", "action": "decline"},
        expect_status="error_4xx",
        expect_error_message_contains=["respondChatRequest returned HTTP"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getSupportReviewState": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["conversation not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_grantSupportReview": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000", "ticket_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["conversation not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_revokeSupportReview": McpContract(
        tier="3",
        arguments={"conversation_id": "00000000-0000-4000-8000-000000000000", "grant_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["conversation not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_submitContractMilestone": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "seq": 1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["submitContractMilestone returned HTTP"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_releaseContractMilestone": McpContract(
        tier="2",
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000", "seq": 1, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["releaseContractMilestone returned HTTP"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_createAgoraListing": McpContract(
        tier="3",
        arguments={"organization_id": "00000000-0000-4000-8000-000000000000", "symbol": "ZZTEST", "total_shares": 1000, "ipo_float": 100, "ipo_price": "1", "funding_agent_did": "did:theprotocol:00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["organization not found"],
        notes="EVTYPES3: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_guildPostOrder": McpContract(
        tier="2",
        skip_reason=(
            "EVTYPES3: takes title+bounty and names NO entity, so there is nothing "
            "non-existent to aim at. READ FROM SOURCE rather than probed: "
            "routers/guild.py::post_order escrows the bounty (guild_escrow."
            "escrow_deposit, poster -> treasury) and INSERTs the work order before "
            "any lookup that could refuse; its only refusal is 402 when the poster "
            "is broke, which is a FIXTURE property, not the tool's behaviour. "
            "Pinning that refusal would make the suite post a real bounty-bearing "
            "order on any node with a funded agent - the tegLockDirect class. "
            "Needs a deliberate success contract with a funded fixture and a "
            "side_effect_assert."
        ),
        notes="EVTYPES3: destructive-with-no-target; source-read, not probed.",
    ),

    # ── §EVTYPES4 2026-09-06 — the last 14 `autogen-skip` tools ─────────────
    # Every one carried the SAME generated reason: "required param '<x>' has no
    # fixture mapping". Thirteen of those params name an ENTITY, so the refusal
    # shape applies unchanged: schema-valid arguments naming something that does
    # not exist. The fourteenth (recordAchievement) names a TYPE and was decided
    # by READING routers/achievements.py first — the reward-config lookup 404s
    # BEFORE any insert or payout, so an unknown type has no side effect. That
    # read is the guildPostOrder discipline applied before the call, not after.
    #
    # Probed on central AND cloud-op-sbxalphaop 2026-09-06 (probe:
    # scratchpad/autogen14/probe14.py, which imports the suite's own
    # _parse_rpc_result/_wrapped_http_status instead of re-implementing them).
    # 13 of 14 agreed; the one that did not is getFiatPurchaseSession, below.
    #
    # ⚠ TWO SCHEMA/ROUTE MISMATCHES the probe measured, both real:
    #   • getDisputeById and getFederationPeerByID advertise `{"type":"string"}`
    #     in their MCP inputSchema while the routes bind an INTEGER id
    #     (disputes.py::get_dispute takes `dispute_id: int`). A uuid therefore
    #     422s inside pydantic and never reaches the rail (§29k), so these two
    #     contracts pass a numeric string on purpose.
    #   • getTegDisputeDetail could not succeed for ANY caller (fixed 2026-10-01, §MCPTEST30) — see its note.
    "theprotocol_getArenaMatch": McpContract(
        tier="1",
        arguments={"match_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Match not found"],
        notes="EVTYPES4: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getArenaMatchBets": McpContract(
        tier="1",
        arguments={"match_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="success",
        expect_keys=["match_id", "total_pool", "bets", "odds"],
        notes=(
            "EVTYPES4: NOT a refusal — an unknown match answers 200 with an EMPTY "
            "book while its sibling getArenaMatch 404s the same id. Measured on "
            "both node classes; the contract pins the envelope shape, which is the "
            "assertion that would catch a silent drop of one of these fields."
        ),
    ),
    "theprotocol_getArenaMatchMap": McpContract(
        tier="1",
        arguments={"match_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Match not found"],
        notes="EVTYPES4: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getFederationRegistryHealthProfile": McpContract(
        tier="1",
        arguments={"peer_id_or_name": "apitest-no-such-peer"},
        expect_status="error_4xx",
        expect_error_message_contains=["Registry not found"],
        notes="EVTYPES4: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getFiatPurchaseSession": McpContract(
        tier="1",
        arguments={"session_id": "cs_test_apitest_nonexistent"},
        expect_status="error_4xx",
        expect_error_message_contains=[
            "Purchase session",              # mainframe: the session lookup refuses
            "mainframe-only by construction",  # operator: the whole rail refuses
        ],
        notes=(
            "EVTYPES4: THE ONE TOOL OF THE 14 WHERE THE TWO NODE CLASSES DISAGREE. "
            "A mainframe answers the session lookup's 404; a federated registry "
            "refuses the fiat rail outright (FIAT_GENESIS_REGISTRY — it cannot mint, "
            "so it cannot run a Stripe pipe). Both are correct refusals of a "
            "nonexistent session, so the phrase list carries both and matches ANY."
        ),
    ),
    "theprotocol_getContractById": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000",
                   "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["getContractById returned HTTP"],
        notes=(
            "EVTYPES4: weak by necessity — _agent_get collapses the upstream body to "
            "'<tool> returned HTTP <n>', so the rail's own sentence never reaches the "
            "caller. The status class is asserted separately."
        ),
    ),
    "theprotocol_acceptContract": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt", "sentinel_did"],
        arguments={"contract_id": "00000000-0000-4000-8000-000000000000",
                   "upgrader_agent_did": "${sentinel_did}",
                   "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["acceptContract returned HTTP"],
        notes=(
            "EVTYPES4: DESTRUCTIVE, and safe here because the ORDER was read before "
            "the call: routers/contracts.py::accept_contract checks the "
            "upgrader-DID match, then _resolve(contract_id), and only then runs "
            "_do_accept (which escrows). A contract id that cannot exist refuses at "
            "the resolve step with nothing written. Robust to a missing "
            "sentinel_did too: the DID-mismatch guard is also 4xx and the phrase "
            "matches either."
        ),
    ),
    "theprotocol_getBatchAgentBalances": McpContract(
        tier="3",
        arguments={"agent_dids": ["did:theprotocol:00000000-0000-4000-8000-000000000000"]},
        expect_status="success",
        expect_keys=["balances"],
        notes=(
            "EVTYPES4: a batch read answers 200 and reports the unknown DID INSIDE "
            "the envelope (balances.<did>.error), which is the right shape — one bad "
            "id must not fail the batch. Pinning `balances` is what would catch the "
            "envelope being dropped for a wholly-unknown input set."
        ),
    ),
    "theprotocol_getDeveloperWebhookDeliveriesAlt": McpContract(
        tier="3",
        arguments={"webhook_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        notes="EVTYPES4: probed on a mainframe AND a cloud operator 2026-09-06; both agreed.",
    ),
    "theprotocol_getDisputeById": McpContract(
        tier="3",
        arguments={"dispute_id": "999999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Dispute with id"],
        notes=(
            "EVTYPES4: numeric id ON PURPOSE — the inputSchema says string, the route "
            "binds `dispute_id: int`, so a uuid 422s in pydantic and proves nothing "
            "about the lookup. Phrase split on the id (the message embeds it)."
        ),
    ),
    "theprotocol_getFederationPeerByID": McpContract(
        tier="3",
        arguments={"peer_id": "999999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Peer registry not found"],
        notes="EVTYPES4: numeric id — same schema/route type mismatch as getDisputeById.",
    ),
    "theprotocol_getTegDisputeDetail": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"agent_jwt": "${sentinel_jwt}", "dispute_log_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Dispute not found"],
        notes=(
            "§MCPTEST30 (2026-10-01): re-tiered T3 -> T2, the getAgentReputation fix of §pass73.3.19. EVTYPES4 had "
            "pinned that this tool could not succeed for ANY caller: the wrapper forwarded a developer token to "
            "GET /teg/disputes/{id}, which takes an agent token (only a dispute's parties read it), so every call "
            "401'd before the id was read. As an agent, a dispute nobody filed is the TEG's own 404, passed through."
        ),
    ),
    "theprotocol_getTegTransactionDetail": McpContract(
        tier="3",
        arguments={"transaction_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found in event ledger"],
        notes=(
            "EVTYPES4: phrase split on the id — the message embeds the transaction "
            "id, so only the tail is portable."
        ),
    ),
    "theprotocol_recordAchievement": McpContract(
        tier="3",
        arguments={"achievement_type": "apitest_nonexistent_achievement_type"},
        expect_status="error_4xx",
        expect_error_message_contains=["Unknown achievement type"],
        notes=(
            "EVTYPES4: the only one of the 14 whose required param is a TYPE, not an "
            "entity — so it was READ before it was called. "
            "routers/achievements.py::record_achievement selects the AchievementReward "
            "row and 404s an unknown type BEFORE any insert, and the payout branch "
            "additionally needs an agent_did this contract does not pass. No row is "
            "written and no value moves."
        ),
    ),


    # ═══════════════════════════════════════════════════════════════════════════
    # §MCPTEST30 (V0550): THE REFUSALS ROUND 15 PASSED UNDER THE DEFAULT CONTRACT, PINNED
    # Round 15's strict run (65962184c67f4e40, 2026-10-02) passed 99 tool rows as a 4xx that no written contract judged
    # (pass_depth's refusal_default, §FANCLAIM's thin coverage: the route was reached and nothing more was checked). These
    # 87 are the destructive-safe design working (agentvault2-09's rules 1 and 2): a 404 that names the probe's own
    # nonexistent target, or a deliberately invalid value the route refuses by validation. Each is pinned to the sentence
    # that refuses it, with the lifecycle's own arguments (so this contract's call aims exactly where the lifecycle's does),
    # and holds on the frame AND both operators (round 15's cloud-op runs 30b36e3d36d44fc4 and 3193d421785d415f): where an
    # operator answers 503 because the feature runs on sovereign mainframes only, that sentence joins the list and the
    # status class is "error" (either class, the body must still name the refusal). The other 12 rows are listed for the
    # tester lane, not pinned: a probe whose own argument is malformed (rule 3), a bare 404 (rule 4), and two bodies that
    # name a defect rather than a refusal. tests/test_mcp_refusal_pins.py holds the answers round 15 recorded.
    # ═══════════════════════════════════════════════════════════════════════════
    "theprotocol_acknowledgeAgentFlag": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "flag_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Flag not found for this agent"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_adminDownloadOperatorBundle": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_approveFrameInvitation": McpContract(
        tier="admin",
        arguments={"invitation_id": "phase6-no-such-invite"},
        expect_status="error",
        expect_error_message_contains=["Invitation not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_approveFunding": McpContract(
        tier="admin",
        arguments={"request_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Funding request #999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_approveOperatorApplication": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_approvePeerRegistry": McpContract(
        tier="admin",
        arguments={"peer_id": "999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Peer registry not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_approvePendingEnforcement": McpContract(
        tier="admin",
        arguments={"action_id": "phase6-no-such-enforce"},
        expect_status="error_4xx",
        expect_error_message_contains=["Pending action phase6-no-such-enforce not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_blacklistRegistry": McpContract(
        tier="admin",
        arguments={"peer_id": "999999", "reason": "phase-6 sweep probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["No compliance record for peer_id=999999"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_deactivatePeerRegistry": McpContract(
        tier="admin",
        arguments={"peer_id": "999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Peer registry not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_deleteAdminAgent": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "reason": "phase-6 sweep probe of an agent that does not exist", "confirm_did": "did:theprotocol:phase6-confirm-mismatch"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_deleteFederationLicense": McpContract(
        tier="admin",
        arguments={"license_id": "phase6-no-such-license"},
        expect_status="error",
        expect_error_message_contains=["Federation license not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_deleteOauthFederationTrust": McpContract(
        tier="admin",
        arguments={"registry_url": "https://phase6-no-such-trust.invalid"},
        expect_status="error_4xx",
        expect_error_message_contains=["not found in trust config"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_deleteSpireOrphan": McpContract(
        tier="admin",
        arguments={"spiffe_id": "spiffe://phase6.invalid/agent/did-theprotocol-phase6-no-such"},
        expect_status="error_4xx",
        expect_error_message_contains=["Can only delete agent entries"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_disableDeveloper2FA": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "reason": "phase-6 sweep probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_disableWebhookAdmin": McpContract(
        tier="admin",
        arguments={"webhook_id": "phase6-no-such-webhook"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_dismissBundleReport": McpContract(
        tier="admin",
        arguments={"report_id": 999999, "resolution": "phase6-probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Report not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_enableWebhookAdmin": McpContract(
        tier="admin",
        arguments={"webhook_id": "phase6-no-such-webhook"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_federationPolicyUpdateRequest": McpContract(
        tier="admin",
        arguments={"peer_did": "did:theprotocol:phase6-no-such", "proposed_policy_json": {"phase6": True}},
        expect_status="error_4xx",
        expect_error_message_contains=["No peer registry found for that DID"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_finalizeRetryFrameInvitation": McpContract(
        tier="admin",
        arguments={"invitation_id": "phase6-no-such-invite"},
        expect_status="error",
        expect_error_message_contains=["Invitation not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_fireCanaryPath": McpContract(
        tier="admin",
        arguments={"path_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Canary path not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_forceDeveloperPasswordReset": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_forceEmailVerify": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_forceMtlsEnroll": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_forceRegisterAgentCard": McpContract(
        tier="admin",
        arguments={"did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["No card for agent did:theprotocol:phase6-no-such-agent"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_getAdminFiatPurchaseDetail": McpContract(
        tier="admin",
        arguments={"purchase_id": "phase6-no-such-purchase"},
        expect_status="error_4xx",
        expect_error_message_contains=["FiatPurchase phase6-no-such-purchase not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_getAdminFrameInvitation": McpContract(
        tier="admin",
        arguments={"invitation_id": "phase6-no-such-invite"},
        expect_status="error",
        expect_error_message_contains=["Invitation not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_getBridgeStatus": McpContract(
        tier="admin",
        arguments={"bridge_tx_id": "phase6-no-such-bridge-tx"},
        expect_status="error",
        expect_error_message_contains=["Bridge transaction not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_getCloudOperatorLogs": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_giftProvisioning": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "months": 1, "reason": "phase-6 sweep probe"},
        expect_status="error",
        expect_error_message_contains=["Developer 999999 not found", "Gift provisioning is mainframe-only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_grantFiatFlare": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "flare_tier": "phase6-not-a-tier"},
        expect_status="error_4xx",
        expect_error_message_contains=["Unknown flare tier 'phase6-not-a-tier'"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_hideBundle": McpContract(
        tier="admin",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000", "reason": "phase-6 sweep probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Bundle not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_ironhandEnrollAgent": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent not found: did:theprotocol:phase6-no-such-agent"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_ironhandRevokeAgent": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent not found: did:theprotocol:phase6-no-such-agent"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_pauseAgentPayouts": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_previewSlash": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "amount": 1},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reactivatePeerRegistry": McpContract(
        tier="admin",
        arguments={"peer_id": "999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Peer registry not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reconcileFiatProvisioning": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_recordAgentOffense": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "offense_type": "phase6_test", "reference": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_refreshAgentCardDrift": McpContract(
        tier="admin",
        arguments={"did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["No card for agent did:theprotocol:phase6-no-such-agent"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_refundFiatPurchase": McpContract(
        tier="admin",
        arguments={"purchase_id": "phase6-no-such-purchase"},
        expect_status="error_4xx",
        expect_error_message_contains=["FiatPurchase phase6-no-such-purchase not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reinstateAgentEnforcement": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reinstateBroadcast": McpContract(
        tier="admin",
        arguments={"broadcast_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Broadcast not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reinstateDeveloper": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_reinstateFederationLicense": McpContract(
        tier="admin",
        arguments={"license_id": "phase6-no-such-license"},
        expect_status="error",
        expect_error_message_contains=["Federation license not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_reinstateOperator": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_rejectFrameInvitation": McpContract(
        tier="admin",
        arguments={"invitation_id": "phase6-no-such-invite", "reason": "phase-6 sweep probe"},
        expect_status="error",
        expect_error_message_contains=["Invitation not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_rejectFunding": McpContract(
        tier="admin",
        arguments={"request_id": 999999, "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Funding request #999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_rejectOperatorApplication": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_rejectPeerRegistry": McpContract(
        tier="admin",
        arguments={"peer_id": "999999"},
        expect_status="error_4xx",
        expect_error_message_contains=["Peer registry not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_rejectPendingEnforcement": McpContract(
        tier="admin",
        arguments={"action_id": "phase6-no-such-enforce", "reason": "phase-6 sweep probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Pending action phase6-no-such-enforce not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_replayFiatPurchase": McpContract(
        tier="admin",
        arguments={"purchase_id": "phase6-no-such-purchase"},
        expect_status="error_4xx",
        expect_error_message_contains=["FiatPurchase phase6-no-such-purchase not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_resendFiatMagicLink": McpContract(
        tier="admin",
        arguments={"purchase_id": "phase6-no-such-purchase"},
        expect_status="error_4xx",
        expect_error_message_contains=["FiatPurchase phase6-no-such-purchase not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_resumeAgentPayouts": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_resyncFrameEventStore": McpContract(
        tier="admin",
        arguments={"peer_id": "999999"},
        expect_status="error",
        expect_error_message_contains=["Peer not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_retractBroadcast": McpContract(
        tier="admin",
        arguments={"broadcast_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Broadcast not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_revokeDeveloperApiKeys": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_revokeFederationLicense": McpContract(
        tier="admin",
        arguments={"license_id": "phase6-no-such-license", "reason": "phase-6 sweep"},
        expect_status="error",
        expect_error_message_contains=["Federation license not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_revokeFiatFlare": McpContract(
        tier="admin",
        arguments={"developer_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_revokeFrame": McpContract(
        tier="admin",
        arguments={"peer_id": "999999", "reason": "phase-6 sweep probe"},
        expect_status="error",
        expect_error_message_contains=["Peer not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_revokeInviteCode": McpContract(
        tier="admin",
        arguments={"code": "phase6-no-such-code"},
        expect_status="error_4xx",
        expect_error_message_contains=["Code not found or already used"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_revokeOperatorAccess": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_rotateAgentCredentials": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_rotateAgentSigningKey": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_rotateOperatorPullToken": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_runAllDiagnostics": McpContract(
        tier="admin",
        arguments={"target": "phase6-no-such-target"},
        expect_status="error_4xx",
        expect_error_message_contains=["target 'phase6-no-such-target' not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_runDiagnosticsSubset": McpContract(
        tier="admin",
        arguments={"targets": ["phase6-no-such-target"], "checks": ["phase6-no-such"]},
        expect_status="error_4xx",
        expect_error_message_contains=["no matching targets"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_setEventEmissionPolicy": McpContract(
        tier="admin",
        arguments={"emit_from_registry": True, "emit_from_teg": False, "event_type": "phase6-no-such-event"},
        expect_status="error_4xx",
        expect_error_message_contains=["No policy for event type"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_setFederationComplianceEnforcementMode": McpContract(
        tier="admin",
        arguments={"mode": "phase6-not-a-mode", "reason": "phase-6 sweep probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["Input should be 'off', 'dry_run' or 'enforcing'"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_softDeleteDeveloper": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "reason": "phase-6 sweep probe of a developer that does not exist", "confirm_email": "phase6@phase6.invalid"},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_supportCloseTicket": McpContract(
        tier="admin",
        arguments={"ticket_id": 999999, "status": "resolved", "message": "phase-6 close"},
        expect_status="error_4xx",
        # V0551: the tool's own sentence without the status (node-specific: the CI phrase gate refuses it); the 4xx
        # class is still asserted by expect_status
        expect_error_message_contains=["Failed to send reply before closing ticket #999999",
                                       "Failed to update ticket #999999"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_supportReplyTicket": McpContract(
        tier="admin",
        arguments={"ticket_id": 999999, "message": "phase-6 sweep reply"},
        expect_status="error_4xx",
        expect_error_message_contains=["Failed to reply to ticket #999999"],   # V0551: without the status (as above)
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_suspendAgent": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_suspendDeveloper": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_suspendFederationLicense": McpContract(
        tier="admin",
        arguments={"license_id": "phase6-no-such", "reason": "phase-6 sweep"},
        expect_status="error",
        expect_error_message_contains=["Federation license not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_suspendOperator": McpContract(
        tier="admin",
        arguments={"application_id": "phase6-no-such-app", "reason": "phase-6 sweep"},
        expect_status="error",
        expect_error_message_contains=["Application not found", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_tegTreasuryIssue": McpContract(
        tier="admin",
        arguments={"amount": "0", "reason": "phase-6 path test"},
        expect_status="error",
        expect_error_message_contains=["Amount must be positive", "This feature runs on sovereign mainframes only"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame; the operators refuse it as mainframe-only (503) in round 15.",
    ),
    "theprotocol_testWebhookAdmin": McpContract(
        tier="admin",
        arguments={"webhook_id": "phase6-no-such-webhook"},
        expect_status="error_4xx",
        expect_error_message_contains=["Webhook not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_toggleCanaryPath": McpContract(
        tier="admin",
        arguments={"path_id": 999999},
        expect_status="error_4xx",
        expect_error_message_contains=["Canary path not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_transferAgentOwnership": McpContract(
        tier="admin",
        arguments={"agent_did": "did:theprotocol:phase6-no-such-agent", "new_creator_developer_id": 999999, "reason": "phase-6 sweep"},
        expect_status="error_4xx",
        expect_error_message_contains=["Agent did:theprotocol:phase6-no-such-agent not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_triggerDiagnosticAction": McpContract(
        tier="admin",
        arguments={"action_id": "phase6-no-such-action", "target": "phase6-no-such-target", "dry_run": True},
        expect_status="error_4xx",
        expect_error_message_contains=["target 'phase6-no-such-target' not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_unhideBundle": McpContract(
        tier="admin",
        arguments={"bundle_id": "00000000-0000-4000-8000-000000000000"},
        expect_status="error_4xx",
        expect_error_message_contains=["Bundle not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_updateBroadcast": McpContract(
        tier="admin",
        arguments={"broadcast_id": 999999, "body": "phase-6 no-such"},
        expect_status="error_4xx",
        expect_error_message_contains=["Broadcast not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_updateDeveloperAdminFlags": McpContract(
        tier="admin",
        arguments={"developer_id": 999999, "admin_flags": {"admin_treasury": False}},
        expect_status="error_4xx",
        expect_error_message_contains=["Developer 999999 not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_updateDisputeRuling": McpContract(
        tier="admin",
        arguments={"dispute_id": "999999", "ruling": "PHASE6_NOT_A_RULING"},
        expect_status="error_4xx",
        expect_error_message_contains=["Invalid ruling. Must be one of"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_updateEnforcementPolicy": McpContract(
        tier="admin",
        arguments={"policy_json": {"phase6": True}, "reason": "phase-6 path test"},
        expect_status="error_4xx",
        expect_error_message_contains=["unknown policy key 'phase6'"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_updateSupportTicketStatus": McpContract(
        tier="admin",
        arguments={"ticket_id": 999999, "status": "open"},
        expect_status="error_4xx",
        expect_error_message_contains=["Ticket not found"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 1): the probe's own nonexistent target; refused on the frame and both operators in round 15.",
    ),
    "theprotocol_uploadRegistryCardIcon": McpContract(
        tier="admin",
        arguments={"icon_b64": "cGhhc2U2LW5vdC1hbi1pbWFnZQ==", "content_type": "image/png"},
        expect_status="error_4xx",
        expect_error_message_contains=["Icon must be PNG or JPEG"],
        override_coverage_fan=True,
        notes="V0550 pin (rule 2): a deliberately invalid value, refused by validation; refused on the frame and both operators in round 15.",
    ),
    # ── §MEMBERSHIP (V0551, agentvault2-09): membership and the commons (mcp/tools_commons.py) ──────────────────────
    # The membership reads hold their shape. Each commons tool probes a season that does not exist (season_not_found),
    # and the open probe a season that ended in the past (ends_in_past, or season_live where one is live): the route's
    # own refusal after its switch; no probe opens, pays or changes anything. Where COMMONS_ENABLED is off the switch
    # layer holds every commons tool to commons_disabled instead (mcp_switches.COMMONS_OFF). Their success paths are the
    # season lifecycle's (mcp_lifecycles.lifecycle_commons_season, on a target where the commons is on).
    "theprotocol_getMembershipStats": McpContract(
        tier="1",
        expect_keys=["mode", "members", "joined_30d", "left_30d", "min_bond_age_days", "requires_matured_bond",
                     "presence_mode", "as_of"],
        notes="§MEMBERSHIP (V0551): counts only, no member named (services/membership.stats).",
    ),
    "theprotocol_getMyMembership": McpContract(
        tier="3",
        expect_keys=["mode", "is_member", "points", "min_bond_age_days", "agents", "agents_total", "agents_qualifying",
                     "agents_shown"],
        notes="§MEMBERSHIP (V0551): the developer's own verdict (services/membership.status_for_developer).",
    ),
    "theprotocol_getCommonsSeasons": McpContract(
        tier="1",
        arguments={"limit": 3},
        expect_keys=["seasons", "currency"],
        expect_types={"seasons": list},
        notes="§MEMBERSHIP (V0551): the public season list.",
    ),
    "theprotocol_getCommonsSeason": McpContract(
        tier="1",
        arguments={"season_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_getMyCommonsSeason": McpContract(
        tier="3",
        arguments={"season_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_submitCommonsWork": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"season_id": 999999999, "kind": "other", "title": "MCP tester probe",
                   "evidence": [{"type": "other", "ref": "mcp-tester-probe"}], "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_castCommonsBallot": McpContract(
        tier="2",
        requires_fixtures=["sentinel_jwt"],
        arguments={"season_id": 999999999, "allocations": {"1": 10}, "agent_jwt": "${sentinel_jwt}"},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed (the season is read before membership, so a non-member meets the same refusal)",
    ),
    "theprotocol_adminCommonsOpenSeason": McpContract(
        tier="admin",
        arguments={"title": "MCP tester probe", "ends_at": "2020-01-01T00:00:00+00:00", "seed": "1"},
        expect_status="error_4xx",
        expect_error_message_contains=["ends_in_past", "season_live"],
        notes=("§MEMBERSHIP (V0551): a season that ended before it opened is refused (ends_in_past), or the live season "
               "is named first (season_live); a season is opened only by the season lifecycle, which cancels it."),
    ),
    "theprotocol_adminCommonsCloseSeason": McpContract(
        tier="admin",
        arguments={"season_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_adminCommonsStrikeSubmission": McpContract(
        tier="admin",
        arguments={"season_id": 999999999, "submission_id": 1, "reason": "MCP tester probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_adminCommonsPaySeason": McpContract(
        tier="admin",
        arguments={"season_id": 999999999},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed (pay MOVES MONEY: only ever probed on a season that does not exist)",
    ),
    "theprotocol_adminCommonsWriteOffAward": McpContract(
        tier="admin",
        arguments={"season_id": 999999999, "award_id": 1, "reason": "MCP tester probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
    "theprotocol_adminCommonsCancelSeason": McpContract(
        tier="admin",
        arguments={"season_id": 999999999, "reason": "MCP tester probe"},
        expect_status="error_4xx",
        expect_error_message_contains=["season_not_found"],
        notes="§MEMBERSHIP (V0551): a season that does not exist, refused by the route after its switch; nothing is opened, paid or changed.",
    ),
}


# ── pass73.3.19 Option-A (2026-05-28) — coverage-fan precedence override ──
# Mark live-verified, self-contained read contracts AUTHORITATIVE over their
# coverage-fan outcome. Only these flip the displayed status from the fan's
# intentional-4xx reachability probe to the real 200 success path. Each was
# curl-verified against the v42/v43 container this session. Opt-in keeps the
# ~180 other hand contracts (esp. CRUD tools that depend on lifecycle setup)
# on the fan path → zero regressions. See
# [[feedback_mcp_tester_status_is_not_failure_signal]].
_OVERRIDE_COVERAGE_FAN = (
    "theprotocol_getArenaLeaderboard",
    "theprotocol_getAgentCardById",
    # NOTE: getAgentCardByHRI is NOT here — it looks up by a slug-style HRI, not
    # the card's did-style humanReadableId, so the sample_card_hri fixture 404s
    # it (v44 surfaced this as 1 honest fail). Left on the coverage-fan path.
    "theprotocol_getAgentCardByHumanReadableId",
    "theprotocol_getAdminRegistryCard",
    "theprotocol_getOperatorLifecycle",
    "theprotocol_getDiagnosticConfig",
    "theprotocol_getAdminMcpAuditLogByActor",
    "theprotocol_getAgentHealthStatus",
    "theprotocol_getAgentHealthTransitions",
    "theprotocol_getHealthCheckWithAgentAuth",
    "theprotocol_getEventsAggregate",
    "theprotocol_getAgentCardDriftDetail",
    "theprotocol_adminGetDeveloperToken",
    # +6 prior-session success contracts (live-verified 200 this session; their
    # expect_keys are present in the real response → no healthy regression):
    "theprotocol_authForgotPassword",
    "theprotocol_authResendVerification",
    "theprotocol_getCircuitACIR",
    "theprotocol_getCircuitSource",
    "theprotocol_getCircuitNargoToml",
    "theprotocol_exportTegTransactions",
    # expected-error (mainframe guard) contracts — authoritative over the fan so
    # the 503 is classified as a correct rejection, not a false 5xx failure:
    "theprotocol_operatorPortalSelfLogs",
    "theprotocol_operatorPortalSelfRestart",
)
for _t in _OVERRIDE_COVERAGE_FAN:
    if _t in MCP_CONTRACTS:
        MCP_CONTRACTS[_t].override_coverage_fan = True


def _load_response_schemas() -> Dict[str, List[str]]:
    """Phase C (2026-05-26): load merged AST+live response-shape map.

    File is generated by `scripts/backfill_expect_keys.py` from
    `mcp_response_schemas.json` (AST) + `mcp_response_shapes_live.json`
    (live harvest). When the file exists, contracts with empty
    `expect_keys` get auto-filled from this map at `get_contract()` time.
    """
    try:
        import os
        path = os.path.join(os.path.dirname(__file__), "mcp_response_expect_keys.json")
        if not os.path.exists(path):
            return {}
        import json as _json
        with open(path, "r") as f:
            harvest = _json.load(f)
    except Exception:
        return {}
    return _carry_renamed_tools(harvest)


def _carry_renamed_tools(harvest: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """§MCPTEST30 (V0644): a renamed tool takes the keys harvested under its old name.

    The harvest is keyed by the names the tools had when it was taken. W3 (V0643) renamed the tools and their contracts
    but not this file, so 17 renamed tools resolved with no keys and each read as a contract gap (the V0643 pair proof
    nt261026x2, 2026-10-26), where V0642 had checked the same keys under the old names and passed. mcp/tool_aliases is
    the one rename table (old -> new); an entry under the new name wins."""
    from agentvault_registry.mcp.tool_aliases import TOOL_ALIASES
    if not isinstance(harvest, dict):
        return {}
    for old, new in TOOL_ALIASES.items():
        if old in harvest and new not in harvest:
            harvest[new] = harvest[old]
    return harvest


_RESPONSE_SCHEMAS = _load_response_schemas()


def _augment_contract_with_schema(c: McpContract, tool_name: str) -> McpContract:
    """If `c.expect_keys` is empty AND the harvest captured keys for this
    tool, return a NEW contract with `expect_keys` auto-filled. Preserves
    every other field. No-op when the contract already has explicit keys
    or when there's no harvest entry."""
    if c.expect_keys:
        return c
    if c.skip_reason:
        return c
    harvested = _RESPONSE_SCHEMAS.get(tool_name)
    if not harvested:
        return c
    return replace(c, expect_keys=list(harvested))


def get_contract(tool_name: str) -> McpContract:
    """Return contract for `tool_name`.

    Precedence: hand-curated MCP_CONTRACTS > autogen MCP_AUTOGEN_CONTRACTS > DEFAULT.
    Autogen module is optional — falls back gracefully if absent.

    Phase C augmentation: when the resolved contract has empty `expect_keys`,
    auto-fill from `mcp_response_expect_keys.json` (built from AST + live
    harvest). This drops the `contract_gap` count by ~135 — strict mode
    can now hold most tools accountable for at least a shape key check.
    """
    # §MCPTEST30 (V0550): a tool the run's target switched off is held to its switch's refusal (mcp_switches.py)
    from . import mcp_switches as _switches
    _sw = _switches.switched_off(tool_name)
    if tool_name in MCP_CONTRACTS:
        c = _augment_contract_with_schema(MCP_CONTRACTS[tool_name], tool_name)
        return _switches.refusal_contract(c, _sw) if _sw else c
    try:
        from .mcp_contracts_autogen import MCP_AUTOGEN_CONTRACTS
        if tool_name in MCP_AUTOGEN_CONTRACTS:
            c = _augment_contract_with_schema(MCP_AUTOGEN_CONTRACTS[tool_name], tool_name)
            return _switches.refusal_contract(c, _sw) if _sw else c
    except ImportError:
        pass
    c = _augment_contract_with_schema(DEFAULT_CONTRACT, tool_name)
    return _switches.refusal_contract(c, _sw) if _sw else c


def _autogen_dict() -> Dict[str, McpContract]:
    """Lazy import so tests work even if autogen module hasn't been regenerated."""
    try:
        from .mcp_contracts_autogen import MCP_AUTOGEN_CONTRACTS
        return MCP_AUTOGEN_CONTRACTS
    except ImportError:
        return {}


def contract_count() -> int:
    """How many explicit contracts (hand-curated + autogen, deduped)."""
    seen = set(MCP_CONTRACTS.keys())
    for k in _autogen_dict().keys():
        seen.add(k)
    return len(seen)


def skipped_tools() -> List[str]:
    """Tools deliberately skipped (destructive / phase 2 deferred / autogen-destructive)."""
    skipped = [name for name, c in MCP_CONTRACTS.items() if c.skip_reason]
    for name, c in _autogen_dict().items():
        if c.skip_reason and name not in MCP_CONTRACTS:
            skipped.append(name)
    return skipped


def resolve_args(
    template: Dict[str, Any],
    bag: McpFixtureBag,
) -> Dict[str, Any]:
    """Substitute ${fixture_name} tokens in the arguments template.

    Only top-level string values are substituted (phase 1 — keeps it simple).
    Phase 3: missing fixtures pass through the literal `${name}`; the runner
    detects this and skips with "phase-3 fixture missing" rather than
    sending the literal to the wrapper.
    """
    out: Dict[str, Any] = {}
    for k, v in template.items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            key = v[2:-1]
            got = bag.get(key, None)
            # ── §EVTYPES8 2026-09-06 — AN EMPTY RESOLUTION IS NOT A RESOLUTION ──
            # `bag.get` returns whatever is there, and BOTH of its paths can hand
            # back an empty value that is not the `${name}` sentinel: a
            # `flow_values` key published as "" or None, or a dataclass field
            # whose declared default IS "" (second_agent_did, sample_card_hri,
            # developer_jwt_nonadmin …). `unresolved_fixtures` then sees a string
            # that does not match `${…}`, reports nothing missing, and the call
            # goes out with a MEANINGLESS argument — so the row's colour is about
            # the empty string, not about the tool.
            #
            # MEASURED: on the frame, `flow_values.sample_card_hri` came back None
            # while `getAgentCardByHRI` still RAN and answered 401, with
            # skip_reason None. That 401 read as an auth finding and was nothing
            # of the sort; the frame simply has no card with an HRI. Same family
            # as a gate whose scope excludes its subject — the instrument answered
            # confidently about something it never looked at.
            #
            # Keeping the sentinel hands the row to the skip machinery that
            # already exists, which says "fixture missing" and names it. A skip is
            # the honest third state; a call with "" is a measurement of nothing.
            if got is None or (isinstance(got, str) and not got.strip()):
                out[k] = v
            else:
                out[k] = got
        else:
            out[k] = v
    return out


def unresolved_fixtures(args: Dict[str, Any]) -> List[str]:
    """Return names of fixtures that remained unresolved after resolve_args.

    A fixture is unresolved if its value still matches `${...}` exactly.
    The runner uses this to skip contracts whose required fixtures the
    phase-3 setup didn't manage to create.
    """
    out: List[str] = []
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            out.append(v[2:-1])
    return out
