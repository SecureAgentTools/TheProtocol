"""
Base Test Class for API Testing Framework

Provides core functionality for all category-specific test modules.
"""

import asyncio
import os
import time
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import httpx

from .auth_manager import AuthManager
from .test_fixes import TestFixes
from .endpoints_registry import EndpointsRegistry
from .request_bodies import RequestBodies

logger = logging.getLogger(__name__)


# 2026-07-15 — destructive-op classifier (Commander: skip destructive tests so
# the sandbox's federation/operator/identity state is never torn down). Returns
# a human reason when (method, path) is genuinely destructive, else "".
# DELIBERATELY CONSERVATIVE: recovery/idempotent ops (reinstate, unblock,
# unquarantine, activate, resume, approve, lift) are NOT destructive; ordinary
# creates/updates are NOT destructive. Only irreversible teardown of shared
# state qualifies.
_DESTRUCTIVE_PATH_KEYWORDS = (
    "/suspend", "/revoke", "revocation", "/quarantine", "/blacklist", "/slash",
    "/teardown", "/reject", "/deactivate", "/reset-credentials",
    "/rotate-credentials", "/rotate-signing-key", "/hard-delete",
    "/force-delete", "/force-password-reset", "/soft-delete",
    "/disable-2fa", "/block", "/revoke-frame", "/revoke-access",
    "/emergency", "/halt", "/delist", "/wipe", "/purge",
)
# DELETE on these resource roots destroys shared sandbox/federation/operator
# identity (as opposed to deleting a throwaway row the tester itself made).
_DESTRUCTIVE_DELETE_ROOTS = (
    "/admin/agents/", "/admin/developers/", "/developers/me/agents/",
    "/admin/cloud-operators/", "/operators/", "/admin/operators/",
    "/federation/peers/", "/admin/federation/", "/federation/licenses/",
    "/admin/frame-invitations/", "/organizations/", "/admin/spire",
    "/admin/ironhand/", "/registries/", "/admin/registries/",
)
# recovery verbs that must NEVER be classified destructive even if a keyword
# above appears as a substring
_RECOVERY_MARKERS = ("reinstate", "unblock", "unquarantine", "/activate",
                     "/reactivate", "resume", "lift-", "/lift", "restore")
# NB 2026-07-16: "activate" (bare) was a bug — "deactivate" contains it as a
# substring, so the destructive DEactivate endpoints were wrongly exempted and
# ran live. Anchored to "/activate" + explicit "/reactivate" so /operators/activate
# and /versions/{id}/activate stay runnable, reactivate stays a recovery op, and
# /deactivate is (correctly) protected as destructive.


# 2026-07-15 — OPERATIONAL side-effects that mutate LIVE infra/economy and must
# never be exercised by a test sweep: simulation control (start/stop/fund/mint —
# the timeout fix made these actually FIRE, which started the prod-adjacent sim),
# token minting, projection snapshots, mass broadcasts (send comms). Reads
# (GET simulation/status|topology|agents) are NOT here — only the mutators.
_SIDE_EFFECT_MARKERS = (
    "/simulation/start", "/simulation/stop", "/simulation/fund",
    "/simulation/mint", "/mint-frame-b", "/projection-snapshot",
    "/simulation/restart", "/simulation/deadman/",
)


# §SUITES1018 (2026-10-18): a READ is never destructive and never needs a counterparty, so no classifier below withholds
# one (the markers are substrings and caught GET /admin/simulation/fund-status, GET /chat/blocks and every GET under
# /frame-invitations or /governance/federation/). Only the wildcard proxy shells stay out: they are not endpoints.
_READ_METHODS = ("GET", "HEAD", "OPTIONS")


def not_measured_result(method: str, path: str, auth_type: str, kind: str, reason: str) -> Dict[str, Any]:
    """§SUITES1018 (2026-10-18): the result of a row the sweep did NOT call. Every skip used to answer healthy=True with
    status 200 in 1 ms, so the 2026-10-18 sweep counted 92 uncalled rows as passes (and three of them then failed the
    EventStore check for events no call could have emitted). Nothing here is a verdict: healthy is False, statusCode is
    None, `not_measured` carries the reason, and `unmeasured` keeps the row out of every pass rate (the consoles and the
    sweep exclude unmeasured rows from the denominator)."""
    return {
        "path": path, "method": method, "authRequired": auth_type,
        "healthy": False, "statusCode": None, "responseTime": 0,
        "responseData": {"skipped": True, kind: True, "reason": reason},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": None, "actualAuthUsed": auth_type,
        "expected_failure": False, "expected_failure_reason": None,
        "failure_bucket": f"not_measured_{kind}",
        "not_measured": True, "not_measured_reason": reason, "unmeasured": True,
    }


# §SUITES1018 (2026-10-18): the routes that START another whole suite, reset the tester itself, or provision. Called
# from inside a sweep they ran it: POST /admin/mcp-tester/run answered 200 by starting a full MCP lifecycle on sbx-alpha
# (13:06Z with the morning sweep; again at 14:51Z with a rehearsal, and that run died at 14:53:23Z in the second
# sbx-alpha's registry went into a fifteen-minute SIGBUS loop), reset-flow-values emptied the sweep's own fixtures
# mid-run, POST /admin/console-suite/runs starts a browser suite, POST /admin/mcp-tester/sandbox provisions frames.
# The MCP tester refuses its twins of these tools (testApiFlow, testApiCategory, resetApiTestSandbox...: "never invoked
# by tester"); the sweep does the same: NOT MEASURED, with the reason. Each suite runs on its own schedule.
_SUITE_LAUNCH_ROUTES = (
    "/admin/mcp-tester/run", "/admin/mcp-tester/refire-single", "/admin/mcp-tester/sandbox",
    "/admin/console-suite/runs",
    "/admin/api-test/run-all", "/admin/api-test/test-category", "/admin/api-test/test-flow",
    "/admin/api-test/test-federation", "/admin/api-test/test-mcp-tool", "/admin/api-test/test-endpoint",
    "/admin/api-test/reset-sandbox", "/admin/api-test/reset-flow-values", "/admin/api-test/eager-bootstrap",
    "/admin/evals/suites/{suite_id}/run",
)


def _classify_suite_launch(method: str, path: str) -> str:
    p = (path or "").split("?", 1)[0].rstrip("/")
    # the legacy GET /admin/api-test/run-all is a launch in a read's clothing: it runs every category again
    if (method or "GET").upper() in _READ_METHODS and p != "/admin/api-test/run-all":
        return ""
    for route in _SUITE_LAUNCH_ROUTES:
        if _route_equals(route, p):
            return ("starts another whole suite run, resets or provisions the tester itself: a sweep never runs one "
                    "inside itself (each suite runs on its own schedule; the MCP tester refuses the same tools)")
    return ""


# §SUITES1018 batch 6: rows that read NOT MEASURED "the sweep sent no body", as if a body were all they lacked. Each is a
# frame's live configuration or market control, or moves value; the sweep calls neither (a write-back of the current
# value would reset every field it omits, and a trade or payout moves real units on the sandbox ledger). They stay NOT
# MEASURED, now with the reason that is true.
_FRAME_CONTROL_ROUTES = (
    ("PUT", "/admin/enforcement/policy"), ("PUT", "/admin/enforcement/policy/section/{name}"),
    ("POST", "/agora/admin/campaign/start"), ("POST", "/agora/admin/campaign/stop"),
    ("PUT", "/agora/admin/demand-director"), ("POST", "/agora/admin/global-halt"),
    ("POST", "/agora/admin/listings/{listing_ref}/circuit-breaker"), ("POST", "/agora/admin/listings/{listing_ref}/price-band"),
    ("PUT", "/admin/fiat/pricing"),
    ("PUT", "/admin/registry-card"), ("POST", "/admin/registry-card/avatar"), ("POST", "/admin/registry-card/icon"),
    ("PUT", "/admin/status/incidents"),
    ("POST", "/admin/federation/licence/install"), ("POST", "/admin/federation/licence/issue"),
    ("POST", "/admin/federation/licence/{cert_hash}/{action}"),
    ("POST", "/admin/commons/seasons"), ("POST", "/admin/commons/seasons/{season_id}/cancel"),
    ("POST", "/admin/commons/seasons/{season_id}/close"), ("POST", "/admin/commons/seasons/{season_id}/strike"),
    ("POST", "/admin/federation/ballots"), ("POST", "/admin/federation/ballots/local-vote"),
    ("POST", "/admin/federation/compliance/peers/{peer_id}/accept-baseline"),
    # §SUITES1018 batch 6c: the compliance kill switch (the sweep set sbx-alpha's from off to dry_run on 2026-09-03 and
    # it stayed so), and the per-event emission policy: the contract writes one fixed row to whatever {event_type}
    # resolves to, and skip_in_projection=false on a type the ledger skips would make the projection count it twice.
    ("POST", "/admin/federation/compliance/enforcement-mode"),
    ("PUT", "/admin/event-emission-policies/{event_type}"),
)
# §SUITES1018 batch 6c: the routes that change a PEER's federation standing. The sweep has no peer of its own that carries
# a compliance record (its fixture peers are never federated), and these rows took {peer_id} from the shared values, where
# the frame_invitations prereq leaves the frame's REAL peer for its own rows: on 2026-10-18 the V0624 sweep blacklisted
# and quarantined sbx-alpha's "Sandbox Beta" through the enforcement contracts (21:10:11Z), which run before any
# destructive check, and the V0623 sweep did the same to a revoked frame at 13:14Z. A blacklist cannot be undone from
# the API; a quarantine takes the peer off the TEG's partners. Not measured, contract or not.
_PEER_STANDING_ROUTES = (
    ("POST", "/admin/enforcement/registries/{peer_id}/quarantine"),
    ("POST", "/admin/enforcement/registries/{peer_id}/lift-quarantine"),
    ("POST", "/admin/enforcement/registries/{peer_id}/blacklist"),
    ("POST", "/admin/federation/frames/{peer_id}/revoke"),
    ("POST", "/admin/federation/frames/{peer_id}/resync-eventstore"),
    # §SUITES1018 batch 7: a peer's word to put an agent on this frame's TEG blocklist, or take it off. Their contracts
    # send a developer token, so the gate alone answered (401); spoken as the frame's real peer it would block the
    # sweep's agent at the TEG for every later row.
    ("POST", "/federation/admin/agents/{agent_did}/block"),
    ("POST", "/federation/admin/agents/{agent_did}/unblock"),
)
_MONEY_ROUTES = (
    # §SUITES1018 batch 7: a cross-frame FX hop converts and delivers units; a slash request the peer's word makes
    # accepted slashes the defendant into the treasury (the GROUP1 note in the router), and its confirmation executes
    # one. Each read EF on the 401 its gate gave a tester that spoke for no peer.
    ("POST", "/teg/fx/route-hop"),
    ("POST", "/federation/disputes/slash-request"), ("POST", "/federation/disputes/slash-confirmation"),
    # the admin IRONHAND probe fires a real transfer of up to 10 units between real agents (_fire_probe_core); on
    # sbx-alpha it answered 503 only because no demo fallback is configured there
    ("POST", "/admin/ironhand/probe"),
    ("POST", "/agora/orders"), ("POST", "/agora/listings"), ("POST", "/agora/listings/{listing_ref}/distributions"),
    ("POST", "/agora/listings/{listing_ref}/launch/buy"), ("POST", "/agora/passport/orders"),
    ("POST", "/agora/organizations/{org_id}/listings/{symbol}/market-maker"),
    ("POST", "/agora/organizations/{org_id}/listings/{symbol}/split"),
    ("POST", "/agora/organizations/{org_id}/proposals"),
    ("POST", "/agora/organizations/{org_id}/treasury/{from_symbol}/sweep"),
    ("POST", "/agora/organizations/{org_id}/treasury/{symbol}/buy"),
    ("POST", "/agora/organizations/{org_id}/treasury/{symbol}/distribution"),
    ("POST", "/agora/organizations/{org_id}/treasury/{symbol}/refloat"),
    ("POST", "/agora/organizations/{org_id}/treasury/{symbol}/sell"),
    ("POST", "/agora/organizations/{org_id}/treasury/{symbol}/transfer"),
    ("PUT", "/agora/organizations/{org_id}/treasury/{symbol}/fees"),
    ("PUT", "/agora/organizations/{org_id}/treasury/{symbol}/maker-rebate"),
    ("PUT", "/agora/organizations/{org_id}/treasury/{symbol}/mm"),
    ("POST", "/teg/send"),
    ("POST", "/contracts/v2/engage/{did}"), ("POST", "/contracts/v2/{cid}/milestones/{seq}/submit"),
    ("POST", "/contracts/v2/{cid}/milestones/{seq}/release"), ("POST", "/contracts/templates/{tid}/instantiate"),
    ("POST", "/admin/contracts/{cid}/resolve"), ("POST", "/admin/guild/orders/{oid}/resolve"),
    ("POST", "/admin/reputation-bond/backstop"), ("POST", "/admin/commons/seasons/{season_id}/pay"),
    ("POST", "/admin/commons/seasons/{season_id}/awards/{award_id}/write-off"),
)


# §SUITES1018 batch 7: a real setting of the signed-in developer. Every pref key is one of a closed set the console and
# the phone read (a watchlist, price alerts, away mode, desk layouts), and a PUT replaces the whole value: on the sweep's
# shared admin the next console session would read the sweep's value. The GET reads one (base, test_endpoint).
_ACCOUNT_SETTING_ROUTES = (
    ("PUT", "/developers/me/prefs/{key}"),
)


# §SUITES1018 batch 7: the rows the V0624 sweep left NOT MEASURED "runner gap: the sweep sent this route no body it
# accepts", as if a body were all they lacked. Each was read against its handler (its OpenAPI summary first): none is a
# call a sweep makes, whatever body it sends, and each says why. (kind, what it does)
_NOT_FOR_A_SWEEP = {
    # value moves
    ("POST", "/organizations/{org_id}/treasury/fund"): ("moves_money", "funds an org agent from the org treasury"),
    ("POST", "/organizations/{org_id}/treasury/remit"): ("moves_money", "an org agent pays its own units into the org "
                                                                        "treasury"),
    ("POST", "/organizations/{org_id}/treasury/sweep"): ("moves_money", "drains the org treasury to one of the owner's "
                                                                        "agents"),
    ("POST", "/organizations/{org_id}/work-orders"): ("moves_money", "commissions Guild work with a bounty escrowed "
                                                                     "from the org treasury"),
    ("POST", "/organizations/{org_id}/work-orders/{oid}/award"): ("moves_money", "awards a bid on an escrowed work "
                                                                                 "order"),
    ("POST", "/organizations/{org_id}/work-orders/{oid}/verify"): ("moves_money", "accepts and pays, or disputes, an "
                                                                                  "escrowed work order"),
    ("POST", "/contracts/{contract_id}/mark-failed"): ("moves_money", "fails a contract and refunds its unreleased "
                                                                      "escrow"),
    ("POST", "/teg/fx/route/sweep"): ("moves_money", "sweeps the FX router's residue to a target"),
    ("POST", "/admin/fee-collector/distribute"): ("moves_money", "pays units from the fee account to an agent"),
    ("POST", "/commons/seasons/{season_id}/ballot"): ("moves_money", "spreads a member's points over a live season's "
                                                                     "submissions, which decide its paid awards"),
    ("POST", "/commons/seasons/{season_id}/submissions"): ("moves_money", "enters work into a live season whose awards "
                                                                          "are paid"),
    ("POST", "/admin/fiat/flare/grant"): ("moves_money", "gives a developer a paid flare tier"),
    # a frame's (or an org's) live configuration
    ("PUT", "/teg/fx/reserve-keeper"): ("frame_control", "the FX reserve peg keeper's live configuration"),
    ("PUT", "/teg/fx/router-keeper"): ("frame_control", "the FX router keeper's live configuration"),
    ("PUT", "/admin/jurisdiction-profile"): ("frame_control", "the frame's jurisdiction profile"),
    ("POST", "/admin/jurisdiction-profile/authorizations"): ("frame_control", "records a regulatory authorization in "
                                                                              "the frame's jurisdiction profile"),
    ("PUT", "/admin/reward-funding/policy"): ("frame_control", "the frame's funding waterfall"),
    ("PUT", "/admin/release-channel/schedule"): ("frame_control", "the frame's release channel schedule"),
    ("POST", "/admin/canary/fleet/remote-paths"): ("frame_control", "the canary master's schedule of peer-homed paths, "
                                                                    "each of which fires real currency"),
    ("POST", "/agora/organizations/{org_id}/listings/{symbol}/market-makers"): ("frame_control", "grants or revokes a "
                                                                                                 "market-maker seat on "
                                                                                                 "a listing"),
    ("PUT", "/organizations/{org_id}/settings"): ("frame_control", "an org's settings, which only ever tighten: a "
                                                                   "sweep run after run would ratchet its own org's"),
    # the host's frame runner and the tester itself
    ("POST", "/admin/frame-runner/jobs"): ("suite_launch", "starts a frame standup on the host's frame runner"),
    ("POST", "/admin/frame-runner/frames/{name}/resume"): ("suite_launch", "resumes a frame standup on the host's frame "
                                                                           "runner"),
    ("POST", "/admin/frame-runner/plan"): ("suite_launch", "runs the standup driver's plan on the host's frame runner, "
                                                           "the one production frames are stood up with (the sweep "
                                                           "reads its status and its jobs)"),
    ("POST", "/admin/api-test/runs/publish"): ("suite_launch", "writes into the tester's own run history, the archive "
                                                               "the runs are kept in"),
    ("POST", "/admin/mcp-tester/sandbox/reveal"): ("suite_launch", "answers with a sandbox frame's admin credential: "
                                                                   "the sweep never asks for a secret"),
    # an act of a person, or one that speaks to people or to other agents
    ("POST", "/admin/email/send"): ("for_a_person", "sends a real mail"),
    ("POST", "/agents/{did}/instruct"): ("for_a_person", "sends an instruction to a running agent, which acts on it"),
    ("POST", "/operators/request-frame"): ("for_a_person", "files a frame request for a person's review"),
    ("PATCH", "/admin/frame-requests/{request_id}"): ("for_a_person", "approves or rejects a frame request someone "
                                                                      "filed"),
    ("POST", "/admin/bundles/reports/{report_id}/dismiss"): ("for_a_person", "a moderation decision on someone's "
                                                                             "report"),
    ("POST", "/admin/agents/{did}/authz/clamp"): ("for_a_person", "clamps an agent's authority (on the sweep's own "
                                                                  "agent its later rows would lose the authority they "
                                                                  "use)"),
    ("PUT", "/agents/{did}/authz"): ("for_a_person", "replaces an agent's whole role set and spend policy with one "
                                                     "expiry (the single-role grant beside it is measured)"),
    ("POST", "/organizations/{org_id}/agents/grant-bulk"): ("for_a_person", "applies a role slice to every agent of "
                                                                            "the org"),
    ("PUT", "/organizations/{org_id}/members/{developer_id}/role"): ("for_a_person", "changes an org member's role"),
    ("POST", "/organizations/{org_id}/ownership/transfer"): ("for_a_person", "offers the org to another member: the "
                                                                             "sweep would hand its own org away"),
    ("POST", "/organizations/{org_id}/ownership/respond"): ("for_a_person", "accepts or declines an ownership offer "
                                                                            "made to the calling developer"),
    ("PATCH", "/agent-cards/{card_id}/listing"): ("for_a_person", "shows or hides an agent in discovery here and on "
                                                                  "every peer (an unlisting travels as a tombstone)"),
    ("POST", "/admin/agents/bulk/refresh-cards"): ("for_a_person", "re-pulls every agent card from its origin, dialling "
                                                                   "each agent's own host"),
    ("POST", "/admin/agents/orphaned-listings/sweep"): ("for_a_person", "unlists the cards of deleted owners, "
                                                                        "frame-wide"),
    ("POST", "/admin/evals/suites/{suite_id}/tasks"): ("for_a_person", "adds a task to an evaluation suite"),
    ("POST", "/liability/webauthn/register"): ("for_a_person", "binds a real authenticator's biometric credential: "
                                                               "the sweep holds none"),
    ("POST", "/auth/push-login/{approval_id}/approve"): ("for_a_person", "approves a sign-in with a phone's biometric"),
    ("POST", "/auth/push-login/{approval_id}/approve-direct"): ("for_a_person", "approves a sign-in with a biometric "
                                                                                "assertion"),
    ("POST", "/phone/sessions"): ("for_a_person", "starts a phone session (phone.use is platform-reserved)"),
    ("POST", "/phone/sessions/{sid}/act"): ("for_a_person", "performs a metered action in a live phone session"),
    # §SUITES1018 batch 7, the V0625 sweep (2026-10-19): 33 rows had read PASS on the 422 their contract sent itself
    # (a body or query the route refuses before its handler); batch 6 made them NOT MEASURED "runner gap". Read against
    # their handlers, these are no call a sweep makes; the rest are measured (the contracts' bodies fixed) or remain
    # honest runner gaps (OAuth introspect and revoke need a client of the sweep's own).
    ("POST", "/account/request-deletion"): ("for_a_person", "requests the deletion of the signed-in developer's "
                                                            "account"),
    ("POST", "/admin/agents/bulk/suspend"): ("for_a_person", "suspends agents in bulk"),
    ("POST", "/admin/agents/bulk/reinstate"): ("for_a_person", "reinstates agents in bulk"),
    ("POST", "/auth/login"): ("credential", "answers with a developer's access and refresh tokens"),
    ("POST", "/auth/agent/token"): ("credential", "answers with an agent's access token"),
    ("POST", "/auth/api-keys"): ("credential", "issues an API key carrying the caller's authority"),
    ("GET", "/docker-registry/token"): ("credential", "issues an image registry token"),
    # §SUITES1018 batch 8: a read that CONSUMES. It went out with a literal id (404) only because the invitation prereq
    # ran under a category name the catalog no longer uses; named a real invitation, it takes a new frame's licence key
    ("GET", "/admin/federation/frame-invitations/{invitation_id}/licence-key"): (
        "credential", "hands a new frame's parked licence key out once, to that frame's own admin"),
    # §SUITES1018 batch 8 (part 6): a running cloud operator's stack. Called with an application of nothing (400) only
    # because the id named a test application; withheld by what it does, whatever it names
    ("POST", "/admin/cloud-operators/{application_id}/restart-service"): (
        "frame_control", "restarts a service of a running cloud operator's stack"),
    ("POST", "/admin/cloud-operators/{application_id}/provision"): (
        "suite_launch", "provisions a cloud operator's whole stack (infrastructure: his word)"),
    ("POST", "/bridge/transfer"): ("moves_money", "locks units on this frame to mint their wrapped copy on another"),
    ("POST", "/fiat/proxy/checkout-session"): ("moves_money", "opens a card-payment checkout session"),
    ("POST", "/onboard/create_agent"): ("moves_money", "creates an agent and mints its genesis grant where the frame "
                                                       "grants one (the sweep's own agents come from its bootstrap)"),
    ("POST", "/fiat/stripe-webhook"): ("for_a_person", "a payment provider's signed callback: the sweep holds no "
                                                       "provider signature"),
    ("POST", "/bundles"): ("for_a_person", "publishes a bundle of agents to the marketplace"),
    ("POST", "/bundles/restore-from-upload"): ("for_a_person", "restores agents from an uploaded bundle file"),
    ("POST", "/bundles/{bundle_id}/rating"): ("for_a_person", "rates someone's bundle"),
    ("POST", "/bundles/{bundle_id}/report"): ("for_a_person", "reports someone's bundle to the moderators"),
    ("POST", "/federation/cli-audit"): ("for_a_person", "writes an operator's CLI audit event into the frame's ledger"),
    ("POST", "/federation/license/rotate-self"): ("frame_control", "rotates the frame's own federation licence"),
    ("POST", "/federation/peers"): ("peer_standing", "registers a peer registry for the frame's admins to approve "
                                                      "(the sweep's peer rows make their own fixture through it)"),
    ("POST", "/operator-applications"): ("for_a_person", "files an operator application for a person's review"),
    ("POST", "/operators/self-provision"): ("suite_launch", "provisions an operator on the host"),
    ("POST", "/support/tickets"): ("for_a_person", "files a support ticket for a person's attention (the chat rows "
                                                   "keep one ticket of the sweep's own)"),
}


def _classify_frame_control(method: str, path: str) -> Tuple[str, str]:
    """(kind, reason) for a route the sweep never calls because of what it changes, else ("", "")."""
    m, p = (method or "GET").upper(), (path or "").split("?", 1)[0].rstrip("/")
    for (em, route), (kind, what) in _NOT_FOR_A_SWEEP.items():
        if m == em and _route_equals(route, p):
            return kind, f"{what}: not a call a sweep makes, whatever body it sends"
    if any(m == em and _route_equals(route, p) for em, route in _ACCOUNT_SETTING_ROUTES):
        return "account_setting", ("a real setting of the signed-in developer (a closed set of keys the console and the "
                                   "phone read, each replaced whole): the sweep never overwrites one")
    if any(m == em and _route_equals(route, p) for em, route in _FRAME_CONTROL_ROUTES):
        return "frame_control", ("a frame's live configuration or market control (policy, pricing, its signed card, the "
                                 "status page, licences, seasons, ballots, market halts and campaigns, the compliance "
                                 "kill switch, the event emission policy): the sweep never rewrites it, and a "
                                 "write-back of the current value would reset every field it omits")
    if any(m == em and _route_equals(route, p) for em, route in _MONEY_ROUTES):
        return "moves_money", ("moves value on the frame's ledger or market (an order, a listing, a treasury move, a "
                               "payout, an escrowed contract, a slash, a cross-frame FX hop): the api-tester sweep "
                               "does not trade or pay")
    if any(m == em and _route_equals(route, p) for em, route in _PEER_STANDING_ROUTES):
        return "peer_standing", ("changes a peer's federation standing (a quarantine, its lift, a blacklist the API "
                                 "cannot undo, a frame revoke or resync) or an agent's on a peer's word (the TEG "
                                 "blocklist): the sweep never does it to a peer, and it has no peer of its own with a "
                                 "compliance record to do it to")
    return "", ""


# §SUITES1018 batch 6b: revocations that act only on an object the sweep made for itself in the same run (the router
# resolves the placeholder to the sweep's own object or to nothing): the next sweep makes a fresh one.
_SWEEP_OWN_REVOCATIONS = ("/liability/devices/{device_id}/revoke-key",
                          # §SUITES1018 batch 8: its catalog body names a token that is none and a client that is none
                          # (request_bodies): a configured federation refuses the client (401), an unconfigured one
                          # answers 501; nothing is ever revoked
                          "/oauth/revoke",
                          # §SUITES1018 batch 8 (part 3): {mid} is the sweep's own mandate (the router's _sweep_mandate),
                          # issued by the sweep's admin for the sweep's agent; the next row that needs one issues anew
                          "/liability/mandates/{mid}/revoke")

# §SUITES1018 batch 6c: the admin peer status routes and the per-peer slash settings act on ANY peer the frame knows
# (its real peer frame, a retired operator), so none of them is ever exempt by name. The router resolves each to the
# sweep's own fixture peer (routers/admin_api_test._fixture_peer_for) and marks the one call it checked; unmarked, every
# one of them is withheld, reactivate included: a recovery verb elsewhere, but reviving a retired peer federates it
# again (on 2026-10-18 the reactivate row took the `peer_id` an earlier row had left and left that peer ACTIVE), and the
# slash row would have switched auto-slash on toward the frame's real peer had that `peer_id` been there.
_PEER_STATUS_ROUTES = (
    ("POST", "/admin/federation/peers/{peer_id}/approve"), ("POST", "/admin/federation/peers/{peer_id}/reject"),
    ("POST", "/admin/federation/peers/{peer_id}/reactivate"), ("POST", "/admin/federation/peers/{peer_id}/deactivate"),
    ("PUT", "/federation/disputes/peer-slash-config/{peer_id}"),
)
_VERIFIED_SWEEP_OWN: set = set()

# §SUITES1018 batch 8 (part 4): the developer-account actions. Withheld while {developer_id} could name a real account
# (developer 2, the tester's own admin, or 1, the frame admin); measured when the router verified the one call names an
# account of the sweep's own (its target throwaway, or the throwaway the DELETE row was made for).
_SWEEP_OWN_ACCOUNT_ROUTES = (
    "/admin/developers/{developer_id}",
    "/admin/developers/{developer_id}/suspend",
    "/admin/developers/{developer_id}/force-password-reset",
    "/admin/developers/{developer_id}/disable-2fa",
)
# §MCPTEST30 V0640: a broadcast send the router verified is a direct notice to the sweep's own throwaway developer
# (routers/admin_api_test._mark_own_notice); every other one stays withheld below (a mass broadcast)
_SWEEP_OWN_NOTICE_ROUTES = ("/admin/broadcasts",)


def is_test_operator_application(app) -> bool:
    """§SUITES1018 batch 8 (part 6): an operator application the sweep may act on (approve, rotate its pull token, read
    its operator's health and logs): one of the testers' own (their reserved test.sandbox domain), already approved
    (approving a pending one is a decision about someone), neither activated nor cloud-hosted (no running operator).
    The seed took the list's first row, the newest application of ANY applicant."""
    return (isinstance(app, dict) and str(app.get("email") or "").lower().endswith("@test.sandbox")
            and str(app.get("status") or "").lower() == "approved"
            and not app.get("activated_developer_id") and not app.get("cloud_hosted"))


def mark_sweep_own(method: str, path: str) -> None:
    """The router has checked that this one call acts on an object the sweep made for itself."""
    _VERIFIED_SWEEP_OWN.clear()
    _VERIFIED_SWEEP_OWN.add(((method or "").upper(), (path or "").split("?", 1)[0].rstrip("/")))


def _classify_destructive(method: str, path: str) -> str:
    p = (path or "").lower()
    m = (method or "GET").upper()
    if m in _READ_METHODS:
        return ""
    _concrete = (path or "").split("?", 1)[0].rstrip("/")
    if (m, _concrete) in _VERIFIED_SWEEP_OWN and any(_route_equals(r, _concrete)
                                                      for r in _SWEEP_OWN_ACCOUNT_ROUTES + _SWEEP_OWN_NOTICE_ROUTES):
        return ""
    if any(m == em and _route_equals(r, _concrete) for em, r in _PEER_STATUS_ROUTES):
        if (m, _concrete) in _VERIFIED_SWEEP_OWN:
            return ""
        return ("acts on any peer the frame knows (its status or its slash settings), and no fixture peer of the "
                "sweep's own was verified for this call — skipped to protect the frame's federation")
    if m == "POST" and any(_route_equals(r, (path or "").split("?", 1)[0]) for r in _SWEEP_OWN_REVOCATIONS):
        return ""
    if any(mk in p for mk in _RECOVERY_MARKERS):
        return ""
    for kw in _SIDE_EFFECT_MARKERS:
        if kw in p:
            return f"operational side-effect ({kw.strip('/')}) — skipped (mutates live sim/economy)"
    # POST /admin/broadcasts sends a real broadcast; GET is fine
    if m == "POST" and p.rstrip("/").endswith("/admin/broadcasts"):
        return "mass-broadcast send — skipped (side-effect)"
    # POST /public/showcase/call invokes a LIVE showcase service agent over A2A
    # (a real, potentially PAYMENT_REQUIRED outbound call) — the tester must not
    # trigger real paid work; the endpoint's JSON/service validation is covered
    # by its own unit path, not by having the sweep call a paid agent.
    if m == "POST" and "/public/showcase/call" in p:
        return "invokes a live (paid) showcase service agent via A2A — skipped (real outbound paid work)"
    # 2026-07-16: PROTECT THE SHARED FIXTURE AGENT. `DELETE /agents/me`
    # (developer-auth) + self-revocation + account-deletion destroy the ONE
    # agent every subsequent category depends on — in a back-to-back sweep this
    # revoked/deleted the agent mid-run and every later category 403'd
    # ("Agent account is revoked"). A deleted agent can't be reinstated, so this
    # MUST be prevented, not healed.
    _pr = p.rstrip("/")
    if m == "DELETE" and (_pr.endswith("/agents/me") or _pr.endswith("/developers/me")):
        return "would delete the shared fixture agent/developer — skipped to protect sweep state"
    if ("self-revocation" in p or "request-account-deletion" in p
            or "/account/deletion" in p or _pr.endswith("/deletion")):
        return "self-revocation/account-deletion of the fixture identity — skipped to protect sweep state"
    for kw in _DESTRUCTIVE_PATH_KEYWORDS:
        if kw in p:
            return f"destructive op ({kw.strip('/')}) — skipped to protect sandbox state"
    if m == "DELETE" and any(root in p for root in _DESTRUCTIVE_DELETE_ROOTS):
        return "destructive DELETE on shared identity/federation/operator resource — skipped"
    return ""


# 2026-07-15 Wave E — INFRA-GATED: endpoints that interact with a FEDERATED PEER
# or a CROSS-FRAME service that a single-frame barebones sandbox structurally
# lacks. These can never pass here (they need sandbox-B / a live peer TEG / a
# bridge counterparty) and are covered by the federation FLOW suites when the
# peer tier is up. Skipped WITH A TRUTHFUL REASON + tagged infra_gated (the
# report separates these from real passes). Deliberately NARROW — only true
# cross-frame INTERACTIONS; local federation reads (list peers, info, health)
# are NOT here and still run.
_INFRA_GATED_MARKERS = (
    "cross-registry", "cross-teg", "/bridge/transfer", "/bridge/mint",
    "/bridge/redeem", "/bridge/unlock", "/bridge/status", "/federation/sync-request",
    # /sandbox/{a,b,es}/{path:path} are WILDCARD passthrough PROXIES to the
    # sandbox frames (part of the intentionally-unwrapped proxy surface). A
    # literal "{path:path}" probe is not a real endpoint, and the 403 is the
    # proxy guard doing its job — the proxied surface is exercised by the
    # actual sandbox test traffic, not by probing the proxy shell.
    "/sandbox/a/", "/sandbox/b/", "/sandbox/es/",
    "/federation/frames/", "/frame-invitations", "multiframe",
    "oauth-federation", "oauth/federation", "/federation/slash",
    "/federation/propose", "/agora-vote",
    # 2026-07-16 round 4: cross-frame federated governance (vote/veto on a
    # federated proposal) needs a real INBOUND proposal relayed from a peer
    # frame — a standalone sandbox can't synthesize one, so the EventStore 422 is
    # structural. The local governance path (create/vote/tally on this frame) is
    # covered by the governance category.
    "/governance/federation/",
    # OAuth token-exchange (RFC 8693) + introspection (RFC 7662) require a
    # REGISTERED OAuth client / federation trust that exists only after an OAuth
    # federation handshake — a standalone sandbox has no registered client, so
    # the "missing client_id/secret" / "field required" rejections are structural.
    "/oauth/token/exchange", "/oauth/introspect",
    # the Command Relay (Galactic Command Center) backend is a mainframe-only
    # service; a standalone sandbox doesn't run it, so /relay/status 503s ("cannot
    # reach relay") and /relay/action 400s (no relay tools configured). The relay
    # surface is exercised on the mainframes where COMMAND_RELAY_SCOPE is set.
    "/relay/status", "/relay/action",
)


_PROXY_SHELL_MARKERS = ("/sandbox/a/", "/sandbox/b/", "/sandbox/es/")


def _classify_infra_gated(method: str, path: str) -> str:
    """§SUITES1018 (2026-10-18): the reason used to say the peer was "not present on the single-frame sandbox"; the
    sandbox has been a federated pair (with operators) since 2026-09, so the reason named a world that no longer exists.
    What is true: a cross-frame ACTION needs a live counterparty object the sweep does not create. Reads run."""
    p = (path or "").lower()
    if any(mk in p for mk in _PROXY_SHELL_MARKERS):
        return ("a wildcard pass-through proxy ({path}), not an endpoint: the routes it proxies are measured as "
                "themselves")
    if (method or "GET").upper() in _READ_METHODS:
        return ""
    for mk in _INFRA_GATED_MARKERS:
        if mk in p:
            return ("a cross-frame action: it needs a live counterparty object (an invitation, a federated proposal, "
                    "a bridge lock, a peer-side delivery) that the sweep does not create")
    return ""


# 2026-07-15 Wave C — EXPECTED 4xx: (method, path-substring) → (status, reason).
# The endpoint is WORKING; the 4xx IS its correct response to the tester's
# context (duplicate create, cross-agent read by a non-owner, non-arbiter
# action). Verified against BOTH the status AND that the body is a well-formed
# error (never a bare force-pass — mirrors the mcp_contracts doctrine).
_EXPECTED_4XX = (
    ("POST", "/operator-applications", 409, "duplicate application — 409 is correct (already applied)"),
    ("POST", "/disputes/{dispute_id}/resolve", 403, "non-arbiter resolve — 403 is correct authz"),
    ("GET", "/disputes/agent/", 403, "cross-agent dispute read by non-owner — 403 is correct authz"),
    ("POST", "/contracts/malpractice", 403, "malpractice by non-party — 403 is correct authz"),
    ("POST", "/contracts/{contract_id}/submit", 403, "submit by non-party — 403 is correct authz"),
    ("POST", "/contracts/{contract_id}/approve-completion", 403, "approve by non-client — 403 is correct authz"),
    # §SUITES1018 (2026-10-18): the 21 peer-only federation rows that stood here ("403 without a peer SPIFFE cert is
    # correct") are gone. They sit behind get_federation_identity, whose Mode 2 the tester reaches from inside its own
    # registry, and the tester now declares an ACTIVE peer frame's identity (auth_manager.federation_spiffe_id), so
    # each route answers the way it answers a peer, and a 403 from one is a refusal of a peer: a finding, never an EF.
    # What stays out of reach is the operator lane (§OPLANE): those routes take the calling operator's own SVID,
    # vouched by this frame's mTLS terminator, and the sweep runs behind that terminator with no operator certificate.
    ("GET", "/federation/operator-self/", 401, "the operator lane (§OPLANE) takes the calling operator's SVID, vouched by this frame's mTLS terminator; the sweep presents no operator certificate"),
    ("POST", "/federation/operator-self/", 401, "the operator lane (§OPLANE) takes the calling operator's SVID, vouched by this frame's mTLS terminator; the sweep presents no operator certificate"),
    ("POST", "/federation/ironhand/", 401, "the operator lane (§OPLANE) takes the calling operator's SVID, vouched by this frame's mTLS terminator; the sweep presents no operator certificate"),
    # /auth/refresh needs a live refresh token; the JWT-based harness has no
    # refresh-token capture, so it posts a placeholder → 401. The endpoint is
    # correctly REJECTING an invalid token (the valid-token refresh path is a
    # login-flow concern, covered by the auth flow suite), so 401 is expected.
    ("POST", "/auth/refresh", 401, "placeholder refresh token (harness has no refresh-token capture) → 401 is the correct rejection"),
    # the fixture agent votes on the seeded proposal once; every later run's
    # re-vote is refused — the idempotent duplicate-vote rejection IS the
    # correct behavior under test.
    ("POST", "/governance/proposals/{proposal_id}/vote", 409, "duplicate vote on the seeded proposal — idempotent rejection is correct"),
    # the tester probing its own run endpoints while a run holds the heavy-run
    # lock: refusing re-entrancy IS the behavior under test.
    ("POST", "/admin/api-test/", 409, "heavy-run lock refuses re-entrant tester runs — correct guard"),
    # the seeded TEG-direct stake carries a 30-day lock; early unstake is
    # refused by the documented FIFO cooldown.
    ("POST", "/teg/staking/unstake", 403, "early unlock within the lock period — cooldown rejection is correct"),
    ("POST", "/teg/staking/unstake", 400, "position locked until its unlock date — cooldown rejection is correct"),
    ("GET", "/admin/api-test/run-all", 409, "heavy-run lock refuses re-entrant tester runs — correct guard"),
    ("POST", "/admin/api-test/self-reset", 403, "secret-gated internal endpoint refuses without the reset secret — correct"),
    # arena matches exist only when live game sessions have run; a clean
    # sandbox has none, so detail-by-id correctly 404s.
    ("GET", "/arena/matches/{match_id}", 404, "no arena matches on a clean sandbox (populated by live game sessions) — 404 correct"),
    ("GET", "/arena/matches/{match_id}/map", 404, "no arena matches on a clean sandbox — 404 correct"),
    # federated variants require a PEER mTLS / federation identity the JWT tester
    # can't present — 401 "Federation authentication required" is the correct
    # rejection (the non-federated twin covers the happy path).
    # (§TWOAGENT V0437: the /contracts/{contract_id}/{accept,submit}-federated rows left with their routes: both are 410)
    ("POST", "/admin/ironhand/register-agent-proxy", 401, "federation-auth required (peer mTLS) — 401 correct for a JWT tester"),
    ("POST", "/admin/ironhand/delete-agent-proxy", 401, "federation-auth required (peer mTLS) — 401 correct for a JWT tester"),
    # /anp/register is DIDWba-authenticated (a distinct scheme), not JWT.
    ("POST", "/anp/register", 401, "DIDWba Authorization required (distinct auth scheme) — 401 correct for a JWT tester"),
    # transfer-ownership to the CURRENT owner + closed-dispute ruling + already-used
    # invite = correct idempotent/state rejections.
    ("POST", "/admin/agents/{agent_did}/transfer-ownership", 400, "transfer to current owner — idempotent rejection is correct"),
    ("POST", "/admin/agents/{target_agent_did}/transfer-ownership", 400, "transfer to current owner — idempotent rejection is correct"),
    ("PUT", "/admin/disputes/{dispute_id}/ruling", 409, "dispute already closed — ruling rejection is correct"),
    ("POST", "/admin/agents/{agent_did}/force-mtls-enrol", 400, "agent already mTLS-enrolled — idempotent rejection is correct"),
    ("POST", "/admin/agents/{target_agent_did}/force-mtls-enrol", 400, "agent already mTLS-enrolled — idempotent rejection is correct"),
    # ---- 2026-07-16 round 3: state-correct rejections a stateless probe can't avoid ----
    # auth: the tester holds no valid current-password (changing the shared dev's
    # password would break every later login) and no live reset token.
    ("POST", "/auth/change-password", 400, "no valid current password (changing the shared dev pw would break later logins) — 400 correct"),
    ("POST", "/auth/reset-password", 400, "no live reset token (issued only by the forgot-password email flow) — 400 correct"),
    # operators: activation tokens + operator-scoped bundles exist only after a
    # real cloud-operator provisioning; a clean sandbox has none.
    ("POST", "/operators/activate", 404, "no pending operator activation token on a clean sandbox — 404 correct"),
    ("GET", "/operators/my-bundle", 401, "operator-scoped endpoint — a dev/admin JWT is not an operator identity — 401 correct"),
    # operators_admin: the seeded application is already APPROVED/provisioned, so
    # re-approve / re-provision / status-transition correctly reject.
    ("POST", "/admin/operator-applications/{application_id}/approve", 400, "application already approved — idempotent rejection is correct"),
    ("POST", "/admin/operator-applications/{application_id}/provision", 400, "application already in a terminal/approved state — rejection is correct"),
    ("GET", "/admin/operator-applications/{application_id}/bundle", 404, "bundle only exists after provisioning — 404 correct on a merely-approved app"),
    ("POST", "/admin/operator-applications/{application_id}/reinstate-operator", 400, "app merely approved, no active operator to reinstate — 400 correct"),
    ("POST", "/admin/operator-applications/{application_id}/rotate-pull-token", 400, "app merely approved, no active operator/token to rotate — 400 correct"),
    # admin_federation: admission records + pending peer registrations exist only
    # mid-handshake; an established bilateral federation + clean sandbox has none.
    ("POST", "/admin/federation/complete-admission/{admission_id}", 404, "no in-flight admission record on a clean sandbox — 404 correct"),
    ("GET", "/admin/federation/admission-status/{admission_id}", 404, "no in-flight admission record on a clean sandbox — 404 correct"),
    ("POST", "/admin/federation/policy-update-request", 404, "no pending peer for the policy-update target — 404 correct"),
    ("POST", "/admin/federation/peers/{peer_id}/approve", 404, "no PENDING peer registration to approve (federation already established) — 404 correct"),
    ("POST", "/admin/federation/peers/{peer_id}/reactivate", 404, "no deactivated local peer to reactivate on an established bilateral federation — 404 correct"),
    ("POST", "/admin/federation/request-admission", 422, "admission policy validation requires a real inbound applicant the sandbox can't synthesize — 422 correct"),
    # agent cards: the fixture agent's card carries no humanReadableId on a fresh
    # sandbox, so HRI lookups correctly 404.
    ("GET", "/agent-cards/id/{human_readable_id:path}", 404, "fixture agent card has no humanReadableId — 404 correct"),
    ("GET", "/agent-cards/by-hri", 404, "fixture agent card has no humanReadableId — 404 correct"),
    ("GET", "/agent-cards/by-hri", 422, "hri query param requires a real humanReadableId the fixture lacks — 422 correct"),
    # org validation rejections (now surfaced with a real message after the
    # organizations.py masking fix) — a duplicate/invalid input is correct.
    ("POST", "/organizations/{org_id}/teams/{team_id}/members", 400, "developer already a team member (or not an org member) — validation rejection is correct"),
    ("POST", "/organizations/invitations/{token}/accept", 400, "invitation already accepted / invalid token — validation rejection is correct"),
    ("GET", "/admin/federation/compliance/peers/{peer_id}", 404, "no compliance record for this peer on a clean sandbox — 404 correct"),
    ("GET", "/admin/federation/licenses/{license_id}", 404, "no federation license issued on a standalone sandbox — 404 correct"),
    ("POST", "/admin/federation/licenses/{license_id}/reinstate", 404, "no federation license to reinstate — 404 correct"),
    # TEG rewards/claim (sandbox handler fixed 2026-07-16) correctly 404s when the
    # fixture agent has no accrued payouts to claim.
    ("POST", "/teg/rewards/claim", 404, "no pending payouts to claim for the fixture agent — 404 correct"),
    # ---- 2026-07-16 round 4: remaining tail correct-rejections ----
    # achievements: a clean sandbox seeds no achievement_rewards rows, so EVERY
    # achievement_type is "unknown" — the 404 is the endpoint's correct rejection
    # (the happy path needs seeded achievement types, a prod-only data condition).
    ("POST", "/achievements/record", 404, "sandbox seeds no achievement types → unknown-type 404 is the correct rejection"),
    # funding: the seeded funding request #1 is FUNDED after the first run; every
    # later re-approve is correctly refused by the terminal-state guard.
    ("POST", "/admin/funding/{request_id}/approve", 400, "funding request already funded — idempotent state rejection is correct"),
    # agent-builder: the JWT harness captures no real client_id, so the synthetic
    # placeholder can't match the agent-<uuid> schema pattern — the 422 is the
    # endpoint's correct input validation (its bundle-generate happy path is a
    # developer-portal concern with a real registered client_id).
    ("POST", "/agent-builder/generate-template", 422, "synthetic client_id placeholder fails the agent-<uuid> schema pattern — 422 validation is correct"),
    # agent CI/CD: a clean sandbox has no pipeline/deployment rows; create-deploy
    # correctly 404s ("Active pipeline not found") and every by-deployment_id read
    # 404s ("Deployment not found"). The endpoints work — they need prior CI/CD
    # state a barebones sandbox doesn't seed (a full pipeline→deploy chain fixture
    # is a future enhancement; the 404s are the correct rejection meanwhile).
    ("POST", "/deployments", 404, "no active CI/CD pipeline/deployment on a clean sandbox — 404 is correct"),
    ("GET", "/deployments/", 404, "no CI/CD deployment on a clean sandbox — 404 is correct"),
    # governance tally is creator-only; the resolved {proposal_id} is not one this
    # agent created (or the seeded proposal predates its creator context), so the
    # "Only the proposal creator can trigger" 403 is the endpoint's correct authz.
    ("POST", "/governance/proposals/{proposal_id}/tally", 403, "creator-only tally by a non-creator — 403 is correct authz"),
    # ...and when the caller IS the creator, the fixture's proposal still has an
    # open (30-day) voting window, so an early tally is correctly refused. Both
    # rejections are correct; the post-close happy path needs an elapsed window a
    # stateless probe can't produce.
    ("POST", "/governance/proposals/{proposal_id}/tally", 400, "voting period still active — early tally is correctly refused"),
    # diagnostics: diagnostic action rows exist only after a diagnostic RUN; a
    # clean sandbox has none, so action-by-id correctly 404s ("unknown action").
    ("POST", "/admin/diagnostics/actions/{action_id}", 404, "no diagnostic action on a clean sandbox (created only by a diagnostic run) — 404 is correct"),
    # admin developer lifecycle: the shared fixture developer is neither suspended
    # nor unverified, so reinstate / force-email-verify correctly refuse (idempotent
    # state guards). Suspending the shared dev to exercise the happy path would
    # break every later login, so these stay correct-rejection.
    ("POST", "/admin/developers/{developer_id}/reinstate", 400, "developer not suspended — idempotent rejection is correct"),
    ("POST", "/admin/developers/{developer_id}/force-email-verify", 400, "developer email already verified — idempotent rejection is correct"),
    # ---- 2026-07-16 round 4: admin category correct-rejections ----
    # ZKP tutorial proof-gen: the sweep's body names no tutorial circuit
    # ("test-circuit"), so the route answers 400 naming the two it proves
    # (fairMarkupPolicy/v2.0.0, accurateResourceUsagePolicy/v2.0.0). That 400 is
    # the correct rejection; real proofs are made and submitted by the
    # flow_zkp_* flows (§ZKV2).
    ("POST", "/admin/tutorial/generate-proof", 400, "the sweep body names no tutorial circuit; the unknown-circuit 400 is correct (the flow_zkp_* flows make real proofs)"),
    # invite-code delete: the {code} placeholder matches no live (unused) invite
    # code, so DELETE correctly 404s ("not found or already used").
    ("DELETE", "/admin/invite-codes/", 404, "no matching unused invite code for the placeholder — 404 is correct"),
    # lift-quarantine needs a quarantined peer with a compliance record; a clean
    # sandbox with an established federation has none, so 400 is correct.
    ("POST", "/lift-quarantine", 400, "peer has no compliance record / is not quarantined — 400 is correct"),
    # cloud-operator provision + health require an ACTIVATED / ACTIVE operator; a
    # merely-created application on a clean sandbox is neither.
    ("POST", "/admin/cloud-operators/{application_id}/provision", (400, 409), "provision refused — app already cloud-hosted (409) or not yet activated (400); both are correct rejections"),
    ("GET", "/admin/cloud-operators/{application_id}/health", 400, "not an active cloud operator — 400 is correct"),
    # docker-registry v2 token endpoint requires service/scope params a bare probe
    # doesn't supply → the 422 field-required is correct input validation.
    ("GET", "/docker-registry/token", 422, "docker-registry token requires service/scope params — 422 field-required is correct validation"),
    # ---- 2026-07-16 round 4: in-SWEEP state-drift correct-rejections. These pass
    # 100% in ISOLATION; in a full sequential sweep an earlier category consumes/
    # mutates the shared fixture, and the endpoint then returns its CORRECT
    # response to the drifted state (verified against the exact status + body seen
    # in the def_sweep). Classifying keeps the suite honest: the endpoint works in
    # both the happy path (isolation) and the correct-rejection path (in-sweep).
    # (The cleaner alternative — pinning each placeholder to the fixture's OWN
    # resource so the happy path runs in-sweep too — needs a ~90-min in-sweep
    # re-validation per change; deferred.)
    ("GET", "/developers/me/agents/{agent_did}/balance", 404, "in-sweep {agent_did} resolved to a non-owned agent — cross-owner balance 404 is correct authz"),
    ("POST", "/disputes/{dispute_id}/evidence", 403, "in-sweep {dispute_id} is a dispute the fixture agent isn't party to — non-party 403 is correct authz"),
    ("PUT", "/federation/peers/{peer_id}", 404, "no peer matches the in-sweep {peer_id} — 404 is correct"),
    ("POST", "/onboard/download-bundle", 400, "in-sweep client_id/agent pairing drifted — client_id-mismatch 400 is correct validation"),
    ("POST", "/a2a-payment/authorize", 429, "fixture agent hit the 20-pending-token cap after the sweep's a2a seeding — 429 rate-limit is the correct guard"),
    # ---- §SUITES1018 (2026-10-18): refusals read from each route's code and its live answer on sbx-alpha ----
    ("POST", "/staking/claim-rewards", 404, "rewards are paid by the distributor, never claimed: the route exists to say so (its 404 sentence)"),
    ("POST", "/admin/federation/licence/genesis", 409, "this frame already holds its genesis certificate: a network has one genesis, a second would split it"),
    ("POST", "/developers/me/agents/{did}/reputation-bond/unlock", 409, "the unlock opens at the bond's maturity; the sweep's bond (or none) has not matured"),
    ("POST", "/agents/reputation-bond/release", 409, "the calling agent holds no bond to release (the release is the bond's exit)"),
    ("POST", "/agents/reputation-bond/unlock", 409, "the calling agent's bond has not matured (or it holds none): the unlock opens at maturity"),
    ("POST", "/organizations/{org_id}/work-orders/", 409, "the sweep's organization holds no treasury of its own (its money lives in an AGORA listing purse): the work-order rails refuse, as they say"),
    ("POST", "/admin/frame-runner/frames/{name}/reveal", 409, "the show-once handover of a new frame's admin credential: the sweep names no frame, so it consumes no one's credential"),
    ("POST", "/admin/frame-runner/jobs/{job_id}/cancel", 409, "the sweep cancels only an ENDED job (it never stops a standup); the runner refuses a job that is not running"),
    ("GET", "/federation/ironkey/issuer-authority", 404, "the sweep's agent has issued no cross-registry delegation the peer holds (the route answers only for one it issued)"),
    ("GET", "/federation/contract-digest", 404, "this frame holds no cross-frame contract with the peer frame the sweep speaks for"),
    ("POST", "/flare-shop/purchase", 400, "the sweep asks for a tier that is not for sale (validation); a purchase with a real agent is the console suite's"),
)


# §SUITES1018 (2026-10-18): the peer-only writes the tester calls AS a peer, each only with the body request_bodies holds
# for it (read against the handler: it names nothing real, so the route refuses before any side effect). Its refusal,
# 4xx or a 501/503 switch, is what the row measures (the guard, the validation, the first lookup) and is an EXPECTED
# FAILURE with this reason; anything else (a 2xx where a refusal was expected, a 5xx) is the row's finding.
PEER_WRITE_REFUSALS = {
    "/federation/ironhand-probe": "the probe moves up to 10 units between real agents; the sweep names agents not homed here",
    "/federation/fx/parked-claim": "the sweep names no parked route and no configured gateway router",
    "/federation/fx/parked-resolve": "the sweep names no parked route and no configured gateway router",
    "/federation/agora-order": "the sweep names no listing (a real one would leave a funding order the sweeper opens)",
    "/federation/agora-certificate": "the sweep's agent holds nothing on this market",
    "/federation/contract-command": "the sweep names no contract and no relayable action",
    "/federation/guild/orders/{oid}/bid": "the sweep bids for no agent of the calling peer",
    "/federation/guild/orders/{oid}/submit": "the sweep names no order its worker holds",
    "/federation/guild/stake": "the sweep names no collateral action",
    "/federation/guild/work-credential": "the sweep's worker is not homed here",
    "/federation/guild/notice": "the sweep's worker is not homed here",
    "/federation/ironkey/delegation-credential": "the sweep's delegate is not homed here (a real one would be granted authority)",
    "/federation/mail-relay": "the sweep names no mail template: the relay sends nothing",
    "/federation/chat/deliver": "the sweep names a host that is no peer",
    "/federation/chat/state": "the sweep names a participant of no peer",
    "/federation/chat/relay-send": "the sweep names a sender of no peer",
    "/federation/governance/ballots": "the sweep delivers no ballot (and the ballot rail takes mTLS, never the internal rail)",
    "/federation/sync-request": "the sweep reports no sync it did not do: a source that is not the caller is refused",
}
# the routes that refuse IN THE BODY of a 2xx ({"ok": false, ...}): a refusal there is no pass either
_OK_FALSE_REFUSALS = ("/federation/canary-fire", "/federation/canary-refill")

# §SUITES1018 (2026-10-18): refusals the sweep's own fixtures meet by construction, each keyed on its SENTENCE as well as
# its status, so the same status for another reason stays a finding (accept on a conversation the sweep has LEFT says
# "you are 'left' in": the fixture broke, and the row says so).
SENTENCE_REFUSALS = (
    ("POST", "/chat/conversations/{conversation_id}/accept", 409, "cannot accept a conversation you are 'active' in",
     "the sweep's conversation is a DM to its own agent, active on both sides: accept answers a request (a stranger's "
     "first thread), which this conversation never is"),
    ("POST", "/chat/conversations/{conversation_id}/decline", 409, "cannot decline a conversation you are 'active' in",
     "the sweep's conversation is a DM to its own agent, active on both sides: decline answers a request (a "
     "stranger's first thread), which this conversation never is"),
    ("POST", "/chat/conversations/{conversation_id}/ping", 429, "one ping per thread per 10 minutes",
     "the documented ping limit (one per thread per 10 minutes): a sweep repeated inside the window meets it"),
    ("POST", "/chat/conversations/{conversation_id}/certificate", 409, "so there is nothing to certify",
     "the sweep's agent holds no shares of the symbol it names: the route refuses by name rather than mint an empty "
     "certificate"),
    ("POST", "/chat/conversations/{conversation_id}/service-call", 409, "service calls run only in agent_service threads",
     "a service call runs in a paid agent_service thread, which the sweep never opens (it would move money); its DM "
     "is refused first"),
    # §SUITES1018 batch 6: writes that name nothing real, so the route's first lookup refuses before any effect
    ("POST", "/guild/orders/{oid}/bids", 404, "Order not found",
     "the sweep bids on no live order (a real bid would sit in a poster's queue): the route loads the order first"),
    ("POST", "/guild/orders/{oid}/award", 404, "Order not found",
     "the sweep awards on no live order: the route loads the order first"),
    ("POST", "/guild/orders/{oid}/submit", 404, "Order not found",
     "the sweep delivers to no live order: the route loads the order first"),
    ("POST", "/guild/orders/{oid}/verify", 404, "Order not found",
     "the sweep verifies no live order (a real verify pays or disputes): the route loads the order first"),
    ("POST", "/forge/evals/run", 404, "Suite not found",
     "the sweep names no eval suite (a real run executes a whole suite against its agent): refused before it runs"),
    ("POST", "/liability/intents", 404, "no_underwriter",
     "no live mandate underwrites the sweep's agent, so no human is answerable for an announcement: the route says so"),
    # §SUITES1018 batch 8 (part 3): the sweep answers a challenge with a TOTP code; a posture whose floor is above it
    # (hardened) or a developer with a WebAuthn key (balanced) refuses that by name, and a sweep makes no biometric
    ("POST", "/liability/challenges/{chid}/approve", 403, "method_below_floor",
     "the consent posture in force asks for a stronger presence than a TOTP code (an enrolled device's signature, "
     "which a sweep cannot make): the route refuses by its floor"),
    ("POST", "/liability/challenges/{chid}/approve", 403, "totp_superseded_by_enrolled_key",
     "the developer holds a WebAuthn credential, so this posture no longer hears a TOTP code: the route says so"),
    # §SUITES1018 batch 8 (part 4): the emergency 2FA unlock acts on the sweep's own throwaway, which holds no second
    # factor (its password is random and kept nowhere, so nothing can enrol one)
    ("POST", "/admin/developers/{developer_id}/disable-2fa", 400, "Developer does not have 2FA enabled",
     "the sweep's own throwaway developer has no second factor to unlock: the route says so"),
)


def _classify_sentence_refusal(method: str, path: str, status_code, response_data) -> str:
    m = (method or "").upper()
    said = _refusal_sentence(response_data)
    try:   # a structured detail (an error code) is matched in the body as well
        hay = said + " " + json.dumps(response_data, default=str)
    except Exception:  # noqa: BLE001
        hay = said
    for em, key, code, sentence, reason in SENTENCE_REFUSALS:
        if m == em and status_code == code and _route_equals(key, path) and sentence in hay:
            return f"{reason} ({status_code}: {said})"
    return ""


def _route_equals(key: str, path: str) -> bool:
    """The whole path (query aside) is this route: "/federation/agora-order" is not "/federation/agora-order-status"."""
    import re as _re
    pattern = _re.sub(r"\\\{[^/]*?\\\}", "[^/?]+", _re.escape(key))
    return _re.fullmatch(pattern, (path or "").split("?", 1)[0]) is not None


def _refusal_sentence(response_data) -> str:
    if isinstance(response_data, dict):
        d = response_data.get("detail") or (response_data.get("error") or {})
        if isinstance(d, dict):
            d = d.get("detail") or d.get("message")
        return str(d or response_data.get("message") or "")[:160]
    return str(response_data or "")[:160]


def _classify_peer_write_refusal(method: str, path: str, status_code, response_data) -> str:
    if (method or "").upper() != "POST" or not isinstance(response_data, (dict, str)):
        return ""
    if not (400 <= int(status_code or 0) < 500 or status_code in (501, 503)):
        return ""
    for key, reason in PEER_WRITE_REFUSALS.items():
        if _route_equals(key, path):
            return f"{reason}; refused before it acts ({status_code}: {_refusal_sentence(response_data)})"
    return ""


# 2026-08-06 §MCPTEST — endpoints that answer with a NEVER-ENDING SSE stream
# (routers/mcp_tester.py: StreamingResponse(..., media_type="text/event-stream")).
# A request-completion timeout against these is the correct observation.
_STREAMING_PATHS = (
    "/admin/mcp-tester/event-stream",
    "/mcp-tester/event-stream",
)


# 2026-08-06 §MCPTEST — CAPABILITY GATES.
# (path-substring, status, env-vars that would ENABLE it, reason).
# These endpoints refuse because THIS NODE deliberately does not host the
# capability; the refusal is the documented contract, not a defect. They are
# stamped expected_failure (NOT a plain pass), because on a node that DOES hold
# the capability the same endpoint must still be exercised for real.
#
# The env check is what keeps this honest: if the capability IS configured and
# the endpoint still refuses, that is a genuine failure and stays a failure.
_CAPABILITY_GATES = (
    ("/admin/mail/", (404,), ("OPERATOR_MAIL_PASSWORD", "MAIL_RELAY_CALLERS"),
     "node holds no mail credentials — §FRAMEMAIL-5 404s the whole mail console "
     "so it only exists where it can be acted on"),
    ("/admin/simulation/", (503,), ("ADMIN_SIMULATION_ENABLED",),
     "simulation control is gated by ADMIN_SIMULATION_ENABLED (§EXCISION shipped "
     "it dark; opted in on registry-a alone) — 503 is the correct refusal"),
    # §SUITES1018 (2026-10-18)
    ("/public/reach-probe", (503,), ("REACH_PROBE_ENABLED",),
     "the reachability probe is offered by the network's root frame alone (REACH_PROBE_ENABLED, EU)"),
    ("/public/directory/graphql", (503,), ("DIRECTORY_MTLS_URL",),
     "no federated index is configured on this registry (DIRECTORY_MTLS_URL)"),
    ("/federation/agora-", (503,), ("EXCHANGE_PASSPORT_ENABLED",),
     "the cross-frame market (AGORA passport) is switched off on this registry (EXCHANGE_PASSPORT_ENABLED)"),
    # §SUITES1018 batch 7: the V0625 sweep's body reached the handler (2026-10-19 06:19:59Z), whose switch answers first:
    # 403 "Agent-triggered eval runs are disabled (EVALS_AGENT_TRIGGER_ENABLED)" (routers/forge.trigger_eval)
    ("/forge/evals/run", (403,), ("EVALS_AGENT_TRIGGER_ENABLED",),
     "agent-triggered eval runs are switched off on this registry (EVALS_AGENT_TRIGGER_ENABLED)"),
    # §SUITES1018 batch 8: the OAuth federation's surface fails CLOSED with no trusted registry configured (data, not an
    # env switch: routers/oauth_federation._require_oauth_federation_enabled): 501 is its answer by design. The sweep
    # adds no trust entry of its own, because one would switch the frame's surface on for every caller.
    ("/oauth/", (501,), (),
     "cross-registry OAuth federation is not enabled on this registry (no trusted registry configured): the route "
     "answers 501, fail-closed"),
)


def _classify_capability_gate(path: str, status_code) -> tuple:
    """Return (reason, bucket) when a refusal is this node's declared posture.

    Returns ("", "") when the capability IS enabled here — so a real breakage on
    a capable node is never masked.
    """
    import os as _os
    p = path or ""
    for key, codes, env_names, reason in _CAPABILITY_GATES:
        if key in p and status_code in codes:
            # §MCPTEST 2026-08-06 — WHOSE env is this?
            # The env below belongs to the process RUNNING the tester, which is
            # only evidence about the TARGET when they are the same node. Driving
            # the suite from registry-a (mail configured, ADMIN_SIMULATION_ENABLED
            # =true) against registry-test (neither) made this gate read the
            # runner's capabilities and call 11 correct refusals real failures.
            # So: only trust the local env when the target IS local. When the
            # target is a DIFFERENT node we cannot assert it has the capability,
            # and the refusal matches the documented absent-capability contract —
            # classify it, and never claim knowledge we do not have.
            _tgt = (_os.getenv("API_TEST_TARGET_URL") or "").lower()
            _target_is_local = (not _tgt) or any(
                h in _tgt for h in ("localhost", "127.0.0.1", "://registry-a")
            )
            if _target_is_local:
                enabled = any((_os.getenv(e) or "").strip().lower()
                              not in ("", "false", "0", "no") for e in env_names)
                if enabled:
                    return "", ""   # capability present HERE -> refusal is a REAL failure
            return reason, "capability_absent"
    return "", ""


def _template_matches(key: str, path: str) -> bool:
    """§SUITES1018: a key matches the path as a substring; a key carrying {placeholders} matches with each placeholder
    standing for one path segment. The router substitutes placeholders BEFORE this classifier runs (replace_path_
    placeholders), so a literal "{did}" in a key could never be found in the path it is asked about."""
    if "{" not in key:
        return key in path
    import re as _re
    pattern = _re.sub(r"\\\{[^/]*?\\\}", "[^/?]+", _re.escape(key))
    return _re.search(pattern, path) is not None


def _classify_expected_4xx(method: str, path: str, status_code, response_data) -> str:
    m = (method or "GET").upper()
    p = (path or "")
    for em, ekey, ecode, reason in _EXPECTED_4XX:
        # ecode may be a single int OR a tuple/list/set of acceptable codes
        _codes = ecode if isinstance(ecode, (tuple, list, set)) else (ecode,)
        if m == em and _template_matches(ekey, p) and status_code in _codes:
            # verify the body is a real error shape (not empty / not a 2xx payload)
            if isinstance(response_data, dict) and (
                "error" in response_data or "detail" in response_data or "title" in response_data):
                return reason
    return ""


def _summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """§SUITES1018: total / healthy / unhealthy / percentage over the rows that were MEASURED, plus how many were not."""
    measured = [r for r in results if not r.get("not_measured")]
    healthy = sum(1 for r in measured if r.get("healthy"))
    return {
        "total": len(measured),
        "healthy": healthy,
        "unhealthy": len(measured) - healthy,
        "percentage": round((healthy / len(measured) * 100) if measured else 0, 1),
        "not_measured": len(results) - len(measured),
    }


class APITestBase:
    """Base class for all API category tests"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.auth_manager = AuthManager()
        self.endpoints_registry = EndpointsRegistry()
        self.request_bodies = RequestBodies()
        self.test_fixes = TestFixes()  # f037: Initialize in base class
        self.results = []
        self.category_name = None
        self._dynamic_ids = {}  # OWL32: Populated with real IDs on first use
        
    async def setup_category(self, category_name: str):
        """Category-specific setup"""
        self.category_name = category_name
        logger.info(f"Setting up test category: {category_name}")

    @staticmethod
    def _extract_first_id(payload, id_fields=("id",), predicate=None):
        """Pull the first usable id from a list-or-wrapped-list JSON payload.
        Handles bare lists AND {items|agents|webhooks|proposals|...: [...]}."""
        items = payload
        if isinstance(payload, dict):
            for k in ("items", "agents", "webhooks", "proposals", "disputes",
                      "contracts", "transactions", "results", "data", "developers",
                      # 2026-07-15 T4: real wrapper keys observed live — /teg/policies
                      # wraps with "policies" (was unparsed → policy_id fell back to
                      # "1" → GET/PUT/DELETE 404). Same class of miss for the rest.
                      "policies", "positions", "licenses", "applications",
                      "invitations", "peers", "stakes", "matches", "keys", "records",
                      # §SUITES1018 batch 7: the CI/CD lists (routers/agent_cicd.py) wrap with these, so the
                      # pipeline and version seeds below found none and made a new one every time: 2,929 pipelines
                      # on sbx-alpha on 2026-10-18.
                      "pipelines", "versions", "deployments"):
                if isinstance(payload.get(k), list):
                    items = payload[k]
                    break
            else:
                items = []
        if not isinstance(items, list):
            return None, None
        for it in items:
            if not isinstance(it, dict):
                continue
            if predicate and not predicate(it):
                continue
            for f in id_fields:
                if it.get(f) not in (None, ""):
                    return it[f], it
        return None, None

    async def _populate_dynamic_ids(self, developer_token=None, agent_token=None):
        """OWL32 (+2026-07-15 real-id pass): populate REAL ids from live sandbox
        data for placeholder replacement, so {webhook_id}/{proposal_id}/
        {transaction_id}/{dispute_id}/{contract_id}/{developer_id}/{agent_002_did}
        resolve to real rows instead of literal "1"/"txn_1" (which 404). Fetch-
        first from the 200+ seeded agents + existing rows; every lookup is best-
        effort and never raises."""
        if self._dynamic_ids.get("_populated"):
            return
        self._dynamic_ids["_populated"] = True
        logger.info("OWL32: Populating dynamic IDs from live API...")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
                dev_hdrs = {"Authorization": f"Bearer {developer_token}"} if developer_token else {}
                ag_hdrs = {"Authorization": f"Bearer {agent_token}"} if agent_token else {}

                async def _get(url, hdrs):
                    try:
                        return await client.get(f"{self.base_url}{url}", headers=hdrs)
                    except Exception:
                        return None

                # ---- primary agent DID (agent token, then dev list) ----
                if agent_token:
                    r = await _get("/api/v1/agents/me", ag_hdrs)
                    if r is not None and r.status_code == 200:
                        did = r.json().get("did")
                        if did:
                            self._dynamic_ids["agent_did"] = did
                            logger.info(f"OWL32: Got real agent DID: {did}")

                # ---- agent list → primary fallback + agent_002_did (list-shape safe) ----
                if developer_token:
                    r = await _get("/api/v1/developers/me/agents", dev_hdrs)
                    if r is not None and r.status_code == 200:
                        payload = r.json()
                        agents = payload if isinstance(payload, list) else (
                            payload.get("agents") or payload.get("items") or [])
                        dids = [a.get("did") for a in agents
                                if isinstance(a, dict) and a.get("did")]
                        if dids:
                            self._dynamic_ids.setdefault("agent_did", dids[0])
                            # second DISTINCT did → sacrificial counterparty for
                            # destructive-path routing (never the primary)
                            for d in dids:
                                if d != self._dynamic_ids.get("agent_did"):
                                    self._dynamic_ids["agent_002_did"] = d
                                    break
                            self._dynamic_ids.setdefault(
                                "agent_002_did", dids[-1] if len(dids) > 1 else dids[0])

                # ---- non-admin developer_id (so {developer_id} tests never target admin self) ----
                if developer_token:
                    r = await _get("/api/v1/admin/developers?limit=50", dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(
                            r.json(), id_fields=("id", "developer_id"),
                            predicate=lambda d: not d.get("is_admin") and str(d.get("email", "")).find("admin@test.sandbox") < 0,
                        )
                        if _id is not None:
                            self._dynamic_ids["developer_id"] = str(_id)

                # ---- webhook_id (existing, else leave default) ----
                for url in ("/api/v1/developers/me/webhooks", "/api/v1/webhooks"):
                    r = await _get(url, dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(r.json(), id_fields=("id", "webhook_id"))
                        if _id is not None:
                            self._dynamic_ids["webhook_id"] = str(_id); break

                # ---- proposal_id ----
                r = await _get("/api/v1/governance/proposals?limit=10", dev_hdrs)
                if r is not None and r.status_code == 200:
                    _id, _ = self._extract_first_id(r.json(), id_fields=("id", "proposal_id"))
                    if _id is not None:
                        self._dynamic_ids["proposal_id"] = str(_id)

                # ---- transaction_id (agent's TEG history — agent has staked 10K) ----
                # 2026-07-15 T4: reputation-signal accepts ONLY transfer-type
                # transactions, and the fixture agent's history is dominated by
                # stake/fund rows ('reward_fund_*'). SEED one real 1-AVT transfer
                # to the counterparty and use ITS id — guaranteed transfer-type,
                # Δ-neutral by construction.
                # §SUITES1018 batch 7: the agent's own history FIRST, the seed only while it holds no transfer. The
                # seed ran for every tester instance, and the router makes several per row: 3,255 one-unit fixture
                # transfers on sbx-alpha on 2026-10-18 (three sweeps). A transfer is never consumed by a row (the
                # reputation-signal row makes a fresh one of its own, GROUP10), so the first one serves the sweep.
                def _is_transfer(_it):
                    return "transfer" in str(_it.get("transaction_type", _it.get("type", ""))).lower()
                for url, hdrs in (("/api/v1/teg/transactions?limit=100", ag_hdrs),
                                  ("/api/v1/teg/transactions?limit=100", dev_hdrs)):
                    if not hdrs:
                        continue
                    r = await _get(url, hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(
                            r.json(), id_fields=("transaction_id", "id", "tx_id"),
                            predicate=_is_transfer)
                        if _id is not None:
                            self._dynamic_ids["transaction_id"] = str(_id); break
                if agent_token and not self._dynamic_ids.get("transaction_id"):
                    try:
                        _rcv = self._dynamic_ids.get("agent_002_did") or self._dynamic_ids.get("agent_did")
                        cr = await client.post(
                            f"{self.base_url}/api/v1/teg/transfer",
                            headers={**ag_hdrs, "Content-Type": "application/json"},
                            json={"receiver_agent_id": _rcv, "amount": "1",
                                  "message": "api-tester transfer fixture"},
                        )
                        if cr is not None and cr.status_code in (200, 201):
                            _tid = (cr.json() or {}).get("transaction_id")
                            if _tid:
                                self._dynamic_ids["transaction_id"] = str(_tid)
                                logger.info(f"2026-07-15 T4: seeded transfer tx {_tid}")
                    except Exception as _txe:
                        logger.warning(f"transfer seed skipped: {_txe}")
                for url, hdrs in (("/api/v1/teg/transactions?limit=10", ag_hdrs),
                                  ("/api/v1/teg/transactions?limit=10", dev_hdrs)):
                    if self._dynamic_ids.get("transaction_id"):
                        break
                    if not hdrs:
                        continue
                    r = await _get(url, hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(
                            r.json(), id_fields=("transaction_id", "id", "tx_id"))
                        if _id is not None:
                            self._dynamic_ids["transaction_id"] = str(_id); break

                # ---- WAVE B (2026-07-15): sub-resource CHAINS. The per-endpoint
                # tester can't chain create→use, so CREATE owned resources here
                # and store their ids → agent_cicd + contracts test the real
                # happy path instead of 404/403 on a foreign/absent id. All
                # best-effort; fetch-first, create-if-none; never raises.
                did = self._dynamic_ids.get("agent_did")
                if did and developer_token:
                    async def _post(url, body):
                        try:
                            return await client.post(f"{self.base_url}{url}",
                                headers={**dev_hdrs, "Content-Type": "application/json"}, json=body or {})
                        except Exception:
                            return None
                    # agent_cicd chain: pipeline → version → deployment
                    try:
                        pl = self.request_bodies.get_body("/agents/{agent_did}/pipelines") or {"pipeline_name": "apitest-pl", "config": {}}
                        if isinstance(pl, dict):
                            pl = {**pl, "pipeline_name": f"apitest-pl-{int(time.time()*1000)%1000000}"}
                        r = await _get(f"/api/v1/agents/{did}/pipelines", dev_hdrs)
                        pid, _ = (self._extract_first_id(r.json(), id_fields=("id", "pipeline_id")) if (r is not None and r.status_code == 200) else (None, None))
                        if pid is None:
                            cr = await _post(f"/api/v1/agents/{did}/pipelines", pl)
                            if cr is not None and cr.status_code in (200, 201):
                                pid = cr.json().get("id") or cr.json().get("pipeline_id")
                        if pid:
                            self._dynamic_ids["pipeline_id"] = str(pid)
                            vb = self.request_bodies.get_body("/agents/{agent_did}/versions") or {"version": "1.0.0"}
                            r = await _get(f"/api/v1/agents/{did}/versions", dev_hdrs)
                            vid, _ = (self._extract_first_id(r.json(), id_fields=("id", "version_id")) if (r is not None and r.status_code == 200) else (None, None))
                            if vid is None:
                                cr = await _post(f"/api/v1/agents/{did}/versions", vb)
                                if cr is not None and cr.status_code in (200, 201):
                                    vid = cr.json().get("id") or cr.json().get("version_id")
                            if vid:
                                self._dynamic_ids["version_id"] = str(vid)
                            # §SUITES1018 batch 7: fetch-first like the pipeline and the version above (this one posted a
                            # deployment for every tester instance; most were refused, and with the version now found
                            # each would have been made).
                            r = await _get(f"/api/v1/agents/{did}/deployments", dev_hdrs)
                            dep, _ = (self._extract_first_id(r.json(), id_fields=("id", "deployment_id")) if (r is not None and r.status_code == 200) else (None, None))
                            if dep is None:
                                db = self.request_bodies.get_body("/agents/{agent_did}/deployments") or {"version_id": str(vid or ""), "environment": "sandbox"}
                                cr = await _post(f"/api/v1/agents/{did}/deployments", db)
                                if cr is not None and cr.status_code in (200, 201):
                                    dep = cr.json().get("id") or cr.json().get("deployment_id")
                            if dep:
                                self._dynamic_ids["deployment_id"] = str(dep)
                    except Exception as _ce:
                        logger.warning(f"cicd chain seed skipped: {_ce}")
                    # owned contract so contracts submit/approve test the happy path
                    try:
                        r = await _get("/api/v1/contracts?limit=5", dev_hdrs)
                        cid, _ = (self._extract_first_id(r.json(), id_fields=("id", "contract_id")) if (r is not None and r.status_code == 200) else (None, None))
                        if cid is None:
                            cb = self.request_bodies.get_body("/contracts/") or {}
                            cr = await _post("/api/v1/contracts/", cb)
                            if cr is not None and cr.status_code in (200, 201):
                                cid = cr.json().get("id") or cr.json().get("contract_id")
                        if cid:
                            self._dynamic_ids["contract_id"] = str(cid)
                    except Exception as _ce2:
                        logger.warning(f"contract seed skipped: {_ce2}")

                # ---- dispute_id / contract_id (existing rows if any) ----
                # §SUITES1018 batch 8 (part 7): a dispute the sweep's OWN agent filed. An administrator's list holds every
                # dispute (newest first), and the admin ruling row closes the one named and moves both parties'
                # reputation: the seed named the newest dispute of anyone. The route filters by complainant itself.
                from urllib.parse import quote as _q
                _own_did = self._dynamic_ids.get("agent_did")
                r = (await _get(f"/api/v1/disputes?limit=10&complainant_did={_q(str(_own_did), safe=':')}", dev_hdrs)
                     if _own_did else None)
                if r is not None and r.status_code == 200:
                    _id, _ = self._extract_first_id(r.json(), id_fields=("id", "dispute_id"))
                    if _id is not None:
                        self._dynamic_ids["dispute_id"] = str(_id)
                r = await _get("/api/v1/contracts?limit=10", dev_hdrs)
                if r is not None and r.status_code == 200:
                    _id, _ = self._extract_first_id(r.json(), id_fields=("id", "contract_id"))
                    if _id is not None:
                        self._dynamic_ids["contract_id"] = str(_id)

                # ---- teg policy_id + dispute_log_id ----
                r = await _get("/api/v1/teg/policies?limit=10", dev_hdrs)
                if r is not None and r.status_code == 200:
                    _id, _ = self._extract_first_id(r.json(), id_fields=("id", "policy_id"))
                    if _id is not None:
                        self._dynamic_ids["policy_id"] = str(_id)
                # 2026-07-15 T4: /teg/disputes is AGENT-auth (dev token → 401 →
                # dispute_log_id never resolved). Read with agent headers, and
                # SEED one dispute log if none exists so the detail endpoint has
                # a real target.
                r = await _get("/api/v1/teg/disputes?limit=10", ag_hdrs or dev_hdrs)
                if r is not None and r.status_code == 200:
                    _id, _ = self._extract_first_id(r.json(), id_fields=("id", "dispute_log_id", "dispute_id"))
                    if _id is not None:
                        self._dynamic_ids["dispute_log_id"] = str(_id)
                if not self._dynamic_ids.get("dispute_log_id") and agent_token:
                    try:
                        _dfd = self._dynamic_ids.get("agent_002_did") or self._dynamic_ids.get("agent_did")
                        cr = await client.post(
                            f"{self.base_url}/api/v1/teg/disputes/log",
                            headers={**ag_hdrs, "Content-Type": "application/json"},
                            json={"defendant_agent_did": _dfd,
                                  "reason_code": "api_test_probe",
                                  "brief_description": "api-tester fixture dispute log"},
                        )
                        if cr is not None and cr.status_code in (200, 201):
                            _id, _ = self._extract_first_id(cr.json(), id_fields=("id", "dispute_log_id", "dispute_id"))
                            if _id is None and isinstance(cr.json(), dict):
                                _id = cr.json().get("dispute_log_id") or cr.json().get("id")
                            if _id is not None:
                                self._dynamic_ids["dispute_log_id"] = str(_id)
                                logger.info(f"2026-07-15 T4: seeded teg dispute log {_id}")
                    except Exception as _dle:
                        logger.warning(f"dispute log seed skipped: {_dle}")

                # ---- operator application_id / frame invitation_id / peer_id
                # (already read from _dynamic_ids in the replace chain; just
                # populate real ones so operators_admin/frame_invitations/
                # federation resolve instead of 404 on a zero-UUID) ----
                for url, key, fields in (
                    ("/api/v1/admin/operator-applications?limit=10", "application_id", ("id", "application_id")),
                    ("/api/v1/admin/federation/frame-invitations?limit=10", "invitation_id", ("id", "invitation_id")),
                    ("/api/v1/admin/federation/peers?limit=10", "peer_id", ("id", "peer_id")),
                    ("/api/v1/federation/licenses?limit=10", "license_id", ("id", "license_id")),
                ):
                    r = await _get(url, dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _payload = r.json()
                        if key == "application_id":   # §SUITES1018 batch 8 part 6: a TEST application or none
                            _apps = _payload if isinstance(_payload, list) else (
                                (_payload or {}).get("applications") or (_payload or {}).get("items") or [])
                            _payload = [a for a in _apps if is_test_operator_application(a)]
                        _id, _ = self._extract_first_id(_payload, id_fields=fields)
                        if _id is not None:
                            self._dynamic_ids[key] = str(_id)

                # peer_id: prefer a REAL ACTIVE peer. The ?limit=10 list above can
                # be empty/pending; /all returns every peer with status, so PUT
                # /federation/peers/{peer_id} + peer-slash-config/{peer_id} resolve
                # to a live peer instead of the "1"→404 default.
                try:
                    r = await _get("/api/v1/admin/federation/peers/all", dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _pl = r.json()
                        _peers = _pl if isinstance(_pl, list) else _pl.get("peers", _pl.get("items", []))
                        _active = [x for x in _peers if isinstance(x, dict)
                                   and str(x.get("status", "")).upper() == "ACTIVE"
                                   and (x.get("id") or x.get("peer_id"))]
                        _pick = _active or [x for x in _peers if isinstance(x, dict) and (x.get("id") or x.get("peer_id"))]
                        if _pick:
                            self._dynamic_ids["peer_id"] = str(_pick[0].get("id") or _pick[0].get("peer_id"))
                except Exception as _pe:
                    logger.warning(f"peer_id(active) resolve skipped: {_pe}")

                # ---- organization_id / team_id / member_id (org endpoints need
                # a real org; seed one if none exist) ----
                org_id = None; org_slug = None
                for url in ("/api/v1/organizations", "/api/v1/developers/me/organizations"):
                    r = await _get(url, dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _row = self._extract_first_id(r.json(), id_fields=("id", "org_id", "organization_id"))
                        if _id is not None:
                            org_id = str(_id)
                            if isinstance(_row, dict):
                                org_slug = _row.get("slug")
                            break
                if not org_id and developer_token:
                    try:
                        import uuid as _uuid
                        _new_slug = f"apitest-{_uuid.uuid4().hex[:8]}"
                        cr = await client.post(
                            f"{self.base_url}/api/v1/organizations",
                            headers={**dev_hdrs, "Content-Type": "application/json"},
                            json={"name": f"apitest-org-{_uuid.uuid4().hex[:8]}",
                                  "slug": _new_slug,
                                  "description": "api-tester fixture org"},
                        )
                        if cr is not None and cr.status_code in (200, 201):
                            org_id = str(cr.json().get("id") or cr.json().get("org_id") or "")
                            org_slug = cr.json().get("slug") or _new_slug
                    except Exception as _oe:
                        logger.warning(f"org seed skipped: {_oe}")
                if org_id:
                    self._dynamic_ids["org_id"] = org_id
                    self._dynamic_ids["organization_id"] = org_id
                    # 2026-07-16: capture the org's slug so /organizations/slug/{slug}
                    # resolves instead of a placeholder → 404.
                    if not org_slug:
                        _od = await _get(f"/api/v1/organizations/{org_id}", dev_hdrs)
                        if _od is not None and _od.status_code == 200 and isinstance(_od.json(), dict):
                            org_slug = _od.json().get("slug")
                    if org_slug:
                        self._dynamic_ids["slug"] = str(org_slug)
                    r = await _get(f"/api/v1/organizations/{org_id}/teams", dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(r.json(), id_fields=("id", "team_id"))
                        if _id is not None:
                            self._dynamic_ids["team_id"] = str(_id)
                    r = await _get(f"/api/v1/organizations/{org_id}/members", dev_hdrs)
                    if r is not None and r.status_code == 200:
                        _id, _ = self._extract_first_id(r.json(), id_fields=("id", "member_id", "developer_id"))
                        if _id is not None:
                            self._dynamic_ids["member_id"] = str(_id)

                # ---- webhook_id (DEV store = /developers/webhooks, the SAME path
                # the developers category's {webhook_id} endpoints read from —
                # NOT /developers/me/webhooks, a different store). Prune to
                # headroom (hard cap 10/dev) then create a keeper + sacrificial
                # (the category's DELETE consumes one). ----
                # 2026-07-16 round 4: seed into a DEDICATED dev_webhook_id slot
                # (NOT the generic webhook_id, which the early /developers/me
                # capture already sets from a different store and which
                # /admin/webhooks/{id} still consumes). Gate on dev_webhook_id so
                # this actually runs — the old `not webhook_id` guard was always
                # true→skipped because webhook_id was pre-set, leaving the
                # developers-category {webhook_id} pointed at a wrong-store id (404).
                if not self._dynamic_ids.get("dev_webhook_id") and developer_token:
                    try:
                        lr = await _get("/api/v1/developers/webhooks", dev_hdrs)
                        if lr is not None and lr.status_code == 200:
                            _wl = lr.json()
                            _whs = _wl if isinstance(_wl, list) else _wl.get("webhooks", _wl.get("items", []))
                            _ids = [w.get("id") or w.get("webhook_id") for w in _whs if isinstance(w, dict)]
                            _ids = [i for i in _ids if i]
                            for _wx in (_ids[:-2] if len(_ids) > 6 else []):
                                try:
                                    await client.delete(f"{self.base_url}/api/v1/developers/webhooks/{_wx}", headers=dev_hdrs)
                                except Exception:
                                    pass
                        for _dslot in ("dev_webhook_id", "dev_webhook_del_id"):
                            cr = await client.post(
                                f"{self.base_url}/api/v1/developers/webhooks",
                                headers={**dev_hdrs, "Content-Type": "application/json"},
                                json={"url": "https://example.com/sandbox-test-webhook",
                                      "events": ["agent.created"], "description": "api-tester fixture"},
                            )
                            if cr is not None and cr.status_code in (200, 201):
                                wid = cr.json().get("id") or cr.json().get("webhook_id")
                                if wid:
                                    self._dynamic_ids[_dslot] = str(wid)
                        logger.info(f"2026-07-16: seeded dev webhooks "
                                    f"{self._dynamic_ids.get('dev_webhook_id')}/{self._dynamic_ids.get('dev_webhook_del_id')}")
                        # 2026-07-17: /admin/webhooks/{webhook_id}/{test,disable,
                        # enable} SHARE this /developers/webhooks store (verified
                        # live: admin test on a dev webhook → 200). The generic
                        # webhook_id reads /developers/me/webhooks (empty for this
                        # dev) → admin_health 3× "Webhook not found" 404 in
                        # isolation / early-in-sweep. Point the generic slot at the
                        # seeded dev webhook when it's otherwise unset.
                        if not self._dynamic_ids.get("webhook_id") and self._dynamic_ids.get("dev_webhook_id"):
                            self._dynamic_ids["webhook_id"] = self._dynamic_ids["dev_webhook_id"]
                    except Exception as _we:
                        logger.warning(f"webhook seed skipped: {_we}")

                # ---- key_id: resolve a REAL developer API key (list first, else
                # seed one) so DELETE/GET /auth/api-keys/{key_id} +
                # /developers/me/apikeys/{key_id} chain to a real resource instead
                # of the hardcoded "1"→404 (honest happy-path fixture) ----
                if not self._dynamic_ids.get("key_id") and developer_token:
                    try:
                        for _kurl in ("/api/v1/auth/api-keys", "/api/v1/developers/me/apikeys"):
                            r = await _get(_kurl, dev_hdrs)
                            if r is not None and r.status_code == 200:
                                _id, _ = self._extract_first_id(r.json(), id_fields=("id", "key_id", "api_key_id"))
                                if _id is not None:
                                    self._dynamic_ids["key_id"] = str(_id); break
                        if not self._dynamic_ids.get("key_id"):
                            cr = await client.post(
                                f"{self.base_url}/api/v1/auth/api-keys",
                                headers={**dev_hdrs, "Content-Type": "application/json"},
                                json={"description": "api-tester fixture key"},
                            )
                            if cr is not None and cr.status_code in (200, 201):
                                kid = cr.json().get("id") or cr.json().get("key_id") or cr.json().get("api_key_id")
                                if kid:
                                    self._dynamic_ids["key_id"] = str(kid)
                                    logger.info(f"2026-07-15: seeded api-key fixture {kid}")
                    except Exception as _ke:
                        logger.warning(f"key_id seed skipped: {_ke}")

                # ---- proposal_id: SEED an ACTIVE proposal if none exists, so the
                # governance lifecycle endpoints (vote / my-vote / votes / detail)
                # have a real target. Requires stake = voting power — the T1
                # economic top-up stakes the fixture agent before governance
                # categories, so this runs with authority. Tally on the ACTIVE
                # proposal then 400s, which is the CORRECT rejection
                # (expected-4xx), not a red. ----
                if not self._dynamic_ids.get("proposal_id") and agent_token:
                    try:
                        cr = await client.post(
                            f"{self.base_url}/api/v1/governance/proposals",
                            headers={"Authorization": f"Bearer {agent_token}",
                                     "Content-Type": "application/json"},
                            json={"title": "api-tester fixture proposal",
                                  "description": "Seeded so vote/my-vote/votes endpoints have an active target.",
                                  "duration_seconds": 3600,
                                  "proposal_type": "standard"},
                        )
                        if cr is not None and cr.status_code in (200, 201):
                            pid = cr.json().get("id") or cr.json().get("proposal_id")
                            if pid:
                                self._dynamic_ids["proposal_id"] = str(pid)
                                logger.info(f"2026-07-15 T3: seeded governance proposal {pid}")
                    except Exception as _ge:
                        logger.warning(f"proposal seed skipped: {_ge}")

                # ---- root-store webhook (/webhooks CRUD is a SEPARATE store from
                # /developers/me/webhooks — its {webhook_id} needs an id from THIS
                # store or deliveries/test 404) ----
                # ALWAYS create OWN webhooks (list-resolve can pick another
                # developer's row → owner-scoped detail 404s). TWO of them: the
                # category's DELETE consumes the sacrificial one, so the keeper
                # survives for deliveries/test which run AFTER delete.
                if not self._dynamic_ids.get("root_webhook_id") and developer_token:
                    try:
                        # PRUNE first — there's a hard cap of 10 webhooks/dev; a
                        # back-to-back sweep accumulates to the cap and then
                        # webhook creation 400s ("Maximum of 10 webhooks per
                        # developer") → deliveries/test 404. Delete down to ≤7 so
                        # there's headroom for the two fixtures below.
                        lr = await _get("/api/v1/webhooks", dev_hdrs)
                        if lr is not None and lr.status_code == 200:
                            _wl = lr.json()
                            _whs = _wl if isinstance(_wl, list) else _wl.get("webhooks", _wl.get("items", []))
                            _ids = [w.get("id") or w.get("webhook_id") for w in _whs if isinstance(w, dict)]
                            _ids = [i for i in _ids if i]
                            for _wx in (_ids[:-2] if len(_ids) > 7 else []):
                                try:
                                    await client.delete(f"{self.base_url}/api/v1/webhooks/{_wx}", headers=dev_hdrs)
                                except Exception:
                                    pass
                        for _wslot in ("root_webhook_id", "root_webhook_del_id"):
                            cr = await client.post(
                                f"{self.base_url}/api/v1/webhooks",
                                headers={**dev_hdrs, "Content-Type": "application/json"},
                                json={"url": "https://example.com/api-tester-webhook",
                                      "events": ["agent.created"],
                                      "description": f"api-tester fixture ({_wslot})"},
                            )
                            if cr is not None and cr.status_code in (200, 201):
                                wid = cr.json().get("id") or cr.json().get("webhook_id")
                                if wid:
                                    self._dynamic_ids[_wslot] = str(wid)
                        logger.info(f"2026-07-15 T4: seeded root webhooks "
                                    f"{self._dynamic_ids.get('root_webhook_id')}/"
                                    f"{self._dynamic_ids.get('root_webhook_del_id')}")
                    except Exception as _rwe:
                        logger.warning(f"root webhook seed skipped: {_rwe}")

                # ---- pending enforcement action: record a low-severity offense
                # against the counterparty (sandbox is disposable; resume/reinstate
                # live in the same category) and capture the REAL action_id so
                # pending/{action_id}/approve has a target ----
                if not self._dynamic_ids.get("action_id") and developer_token:
                    try:
                        _off_did = self._dynamic_ids.get("agent_002_did") or self._dynamic_ids.get("agent_did")
                        # §SUITES1018 batch 7: a fixture offense still pending against the counterparty serves this
                        # instance too (the list is newest first). Recorded anew for every tester instance it left
                        # 2,989 pending actions on sbx-alpha on 2026-10-18 and escalated the counterparty each time.
                        # The approve and reject rows consume one each; the next instance then records a new one.
                        if _off_did:
                            r = await _get("/api/v1/admin/enforcement/pending?per_page=100", dev_hdrs)
                            if r is not None and r.status_code == 200:
                                _id, _ = self._extract_first_id(
                                    r.json(), id_fields=("id", "action_id"),
                                    predicate=lambda _a: (_a.get("agent_did") == _off_did
                                                          and _a.get("trigger_reference") == "api-tester fixture offense"))
                                if _id is not None:
                                    self._dynamic_ids["action_id"] = str(_id)
                        if _off_did and not self._dynamic_ids.get("action_id"):
                            cr = await client.post(
                                f"{self.base_url}/api/v1/admin/enforcement/agents/{_off_did}/record-offense",
                                headers={**dev_hdrs, "Content-Type": "application/json"},
                                # severity 1 = minimal: creates the pending action
                                # (so approve/{action_id} has a target) WITHOUT
                                # escalating to a suspension that would poison the
                                # shared agent's later economic categories.
                                json={"offense_type": "dispute_lost", "severity": 1,
                                      "reference": "api-tester fixture offense"},
                            )
                            if cr is not None and cr.status_code in (200, 201):
                                _aid = (cr.json() or {}).get("action_id")
                                if _aid:
                                    self._dynamic_ids["action_id"] = str(_aid)
                                    logger.info(f"2026-07-15 T4: seeded enforcement action {_aid}")
                    except Exception as _ofe:
                        logger.warning(f"offense seed skipped: {_ofe}")

                # ---- counterparty token from the BFF sandbox cache (lazy import
                # avoids a module cycle; covers every base_tester call-site) so
                # recipient-scoped chains can act as the payee ----
                if not self._dynamic_ids.get("agent_002_token"):
                    try:
                        from agentvault_registry.routers.admin_api_test import _sandbox_tokens as _st
                        if _st.get("agent_002_token"):
                            self._dynamic_ids["agent_002_token"] = _st["agent_002_token"]
                    except Exception:
                        pass

                # ---- TEG-direct stake: /teg/staking/unstake requires a REAL
                # stake_id (body shipped a placeholder). Seed a tiny TEG-direct
                # stake and capture its id. ----
                # §SUITES1018 batch 7: a locked fixture stake of the agent's own serves this instance too. Staked anew
                # for every tester instance it locked 3,303 one-unit stakes for 30 days on sbx-alpha on 2026-10-18; the
                # unstake row meets the lock on any of them (the refusal it is measured on), so none is ever consumed.
                # Only a stake of the fixture's own shape is taken: the agent's real stake carries its voting power.
                _st_did = self._dynamic_ids.get("agent_did")
                if agent_token and developer_token and _st_did and not self._dynamic_ids.get("teg_stake_id"):
                    try:
                        r = await _get(f"/api/v1/teg/staking/balance/{_st_did}", dev_hdrs)
                        _sb = r.json() if (r is not None and r.status_code == 200) else None
                        for _stk in ((_sb.get("active_stakes") or []) if isinstance(_sb, dict) else []):
                            try:
                                if (isinstance(_stk, dict) and _stk.get("is_locked") and _stk.get("stake_id")
                                        and int(_stk.get("lock_period_days") or 0) == 30
                                        and Decimal(str(_stk.get("amount"))) == Decimal("1")):
                                    self._dynamic_ids["teg_stake_id"] = str(_stk["stake_id"])
                                    break
                            except (InvalidOperation, TypeError, ValueError):
                                continue
                    except Exception as _sbe:  # noqa: BLE001 - no read: the seed below stakes, as before
                        logger.warning(f"teg stake lookup skipped: {_sbe}")
                if agent_token and not self._dynamic_ids.get("teg_stake_id"):
                    try:
                        cr = await client.post(
                            f"{self.base_url}/api/v1/teg/staking/stake",
                            headers={**ag_hdrs, "Content-Type": "application/json"},
                            json={"amount": "1", "lock_period_days": 30},
                        )
                        if cr is not None and cr.status_code in (200, 201):
                            _sj = cr.json() if isinstance(cr.json(), dict) else {}
                            _sid = _sj.get("stake_id") or _sj.get("id") or (_sj.get("stake") or {}).get("stake_id")
                            if _sid:
                                self._dynamic_ids["teg_stake_id"] = str(_sid)
                                logger.info(f"2026-07-15 T4: seeded TEG-direct stake {_sid}")
                    except Exception as _se:
                        logger.warning(f"teg stake seed skipped: {_se}")

                # ---- a2a payment tokens: verify/settle/release need REAL apt_
                # tokens from /a2a-payment/authorize (bodies shipped a static
                # placeholder → 422). Seed TWO: settle CONSUMES the first, so
                # release gets its own fresh token. Amounts are tiny and move
                # via the canonical a2a escrow — Δ-neutral. ----
                if agent_token and not self._dynamic_ids.get("payment_token"):
                    try:
                        _pay_to = self._dynamic_ids.get("agent_002_did") or self._dynamic_ids.get("agent_did")
                        for _slot in ("payment_token", "payment_token_2", "payment_token_3"):
                            cr = await client.post(
                                f"{self.base_url}/api/v1/a2a-payment/authorize",
                                headers={**ag_hdrs, "Content-Type": "application/json"},
                                json={"target_agent_did": _pay_to, "amount": "1",
                                      "ttl_seconds": 900},
                            )
                            if cr is not None and cr.status_code in (200, 201):
                                _tok = cr.json().get("token")
                                if _tok:
                                    self._dynamic_ids[_slot] = _tok
                            else:
                                logger.warning(
                                    f"2026-07-15 T4: a2a authorize for {_slot} failed "
                                    f"({getattr(cr, 'status_code', 'n/a')}): "
                                    f"{getattr(cr, 'text', '')[:160]}")
                        logger.info(
                            "2026-07-15 T4: a2a token slots seeded: "
                            + ",".join(s for s in ("payment_token", "payment_token_2", "payment_token_3")
                                       if self._dynamic_ids.get(s)))
                    except Exception as _pe:
                        logger.warning(f"a2a token seed skipped: {_pe}")

                did = self._dynamic_ids.get("agent_did")

                # P8.26b: Fetch pipeline_id, version_id, template_id for placeholder replacement
                did = self._dynamic_ids.get("agent_did")
                if did and developer_token:
                    # Fetch pipelines
                    try:
                        r = await client.get(f"{self.base_url}/api/v1/agents/{did}/pipelines", headers=dev_hdrs)
                        if r.status_code == 200:
                            pdata = r.json()
                            pipelines = pdata.get("pipelines", pdata if isinstance(pdata, list) else [])
                            if pipelines and isinstance(pipelines[0], dict):
                                self._dynamic_ids["pipeline_id"] = pipelines[0].get("id") or pipelines[0].get("pipeline_id")
                                logger.info(f"P8.26b: Got pipeline_id: {self._dynamic_ids['pipeline_id']}")
                    except Exception as e:
                        logger.warning(f"P8.26b: Failed to fetch pipelines: {e}")
                    
                    # Fetch versions
                    try:
                        r = await client.get(f"{self.base_url}/api/v1/agents/{did}/versions", headers=dev_hdrs)
                        if r.status_code == 200:
                            vdata = r.json()
                            versions = vdata.get("versions", vdata if isinstance(vdata, list) else [])
                            if versions and isinstance(versions[0], dict):
                                self._dynamic_ids["version_id"] = versions[0].get("id") or versions[0].get("version_id")
                                logger.info(f"P8.26b: Got version_id: {self._dynamic_ids['version_id']}")
                    except Exception as e:
                        logger.warning(f"P8.26b: Failed to fetch versions: {e}")
                
                # Fetch pipeline template_id
                if developer_token:
                    try:
                        r = await client.get(f"{self.base_url}/api/v1/pipeline-templates", headers=dev_hdrs)
                        if r.status_code == 200:
                            tdata = r.json()
                            templates = tdata.get("templates", tdata if isinstance(tdata, list) else [])
                            if templates and isinstance(templates[0], dict):
                                self._dynamic_ids["pipeline_template_id"] = templates[0].get("id") or templates[0].get("template_id")
                                logger.info(f"P8.26b: Got pipeline_template_id: {self._dynamic_ids['pipeline_template_id']}")
                    except Exception as e:
                        logger.warning(f"P8.26b: Failed to fetch templates: {e}")
                
        except Exception as e:
            logger.warning(f"OWL32: Failed to populate dynamic IDs: {e}")
        
    async def test_endpoint(
        self,
        method: str,
        path: str,
        auth_type: str = "none",
        body: Optional[Dict[str, Any]] = None,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        is_form_data: bool = False,
        test_path_override: Optional[str] = None,
        timeout: float = 60.0,
        headers: Optional[Dict[str, str]] = None  # Added headers parameter
    ) -> Dict[str, Any]:
        """
        Test a single API endpoint with intelligent auth handling.
        
        Returns test result dictionary with health status, response time, etc.
        """
        start_time = time.time()
        
        try:
            # P8.26: Pre-skip 2FA endpoints — manually tested & verified working by Commander
            # Too complex for automated testing (TOTP secrets, partial tokens, etc.)
            _2FA_SKIP_MAP = {
                "/auth/2fa/backup-codes": "2FA backup-codes: manually verified working (needs 2FA enabled)",
                "/auth/2fa/disable": "2FA disable: manually verified working (needs 2FA enabled)",
                "/auth/2fa/verify": "2FA verify: manually verified working (needs real TOTP code)",
                "/auth/2fa/recover": "2FA recover: manually verified working (needs partial_token)",
                "/auth/2fa/validate": "2FA validate: manually verified working (needs partial_token)",
            }
            if path in _2FA_SKIP_MAP:
                logger.info(f"P8.26 SKIP: {path} — {_2FA_SKIP_MAP[path]}")
                return not_measured_result(method, path, auth_type, "manual_only", _2FA_SKIP_MAP[path])
            
            # P8.26b: Skip deprecated/unimplemented endpoints
            _SKIP_ENDPOINTS = {
                "/teg/batch-transfer": "Batch transfer intentionally not implemented (501)",
            }
            if path in _SKIP_ENDPOINTS:
                logger.info(f"P8.26b SKIP: {path} — {_SKIP_ENDPOINTS[path]}")
                return not_measured_result(method, path, auth_type, "unbuilt", _SKIP_ENDPOINTS[path])

            # 2026-07-15 (Commander: "skip destructive ones so we don't destroy
            # sandbox federation etc"): skip genuinely DESTRUCTIVE operations —
            # they would tear down real sandbox/federation/operator/identity
            # state (and, run against the primary agent/self, cascade 401s
            # through the rest of the category). Conservative: only clear
            # destructive verbs + DELETE on core/federation/operator resources.
            # Recovery ops (reinstate/unblock/unquarantine/activate) are NOT
            # skipped. Non-destructive creates/updates still run for real.
            _launch = _classify_suite_launch(method, path)
            if _launch:
                logger.info(f"SUITE-LAUNCH-SKIP: {method} {path}")
                return not_measured_result(method, path, auth_type, "suite_launch", _launch)

            _destr_reason = _classify_destructive(method, path)
            if _destr_reason:
                logger.info(f"DESTRUCTIVE-SKIP: {method} {path} — {_destr_reason}")
                return not_measured_result(method, path, auth_type, "destructive", _destr_reason)

            _fc_kind, _fc_reason = _classify_frame_control(method, path)
            if _fc_kind:
                return not_measured_result(method, path, auth_type, _fc_kind, _fc_reason)

            # 2026-07-15 Wave E — infra-gated (peer/cross-frame) skip
            _infra_reason = _classify_infra_gated(method, path)
            if _infra_reason:
                logger.info(f"INFRA-GATED-SKIP: {method} {path} — {_infra_reason}")
                return not_measured_result(method, path, auth_type, "infra_gated", _infra_reason)

            # §SUITES1018: a peer-only write is called as a peer ONLY with the vetted body request_bodies holds for it;
            # without one it is not called at all (an empty or synthesized body can fund canary senders, move units or
            # send mail on a route that now authenticates the tester).
            if auth_type == "mtls" and (method or "GET").upper() not in _READ_METHODS and not body:
                return not_measured_result(method, path, auth_type, "peer_write",
                                           "a peer-only write with no vetted body: the sweep calls one as a peer only "
                                           "with a body that is refused before it acts (request_bodies)")

            # Handle WebSocket endpoints specially
            if path.startswith("/ws/") or path.endswith("/ws"):
                logger.info(f"Skipping WebSocket endpoint {method} {path} - not measured")
                return not_measured_result(method, path, auth_type, "websocket",
                                           "a WebSocket route: a request/response sweep cannot open one")
            
            # Handle verify-email endpoint specially - needs query param
            if path == "/auth/verify-email" and method == "GET":
                test_path_override = "/auth/verify-email?token=dummy-verification-token"

            # 2026-07-15: /discover requires a `query` (min_length=3) query param
            # (agent_discovery.py:434) → send one so it 200s instead of 422.
            if path == "/discover" and method == "GET":
                test_path_override = "/discover?query=test&limit=5"

            # §SUITES1018 batch 7: {key} is one of a closed set (routers/developers._PREF_KEYS); every other value is
            # 404 "Unknown pref key". The pulse feed's switch is read (its absence reads OFF); the PUT is not measured.
            if path == "/developers/me/prefs/{key}" and method == "GET":
                test_path_override = "/developers/me/prefs/pocket.pulse"
            
            # Prepare test path
            test_path = test_path_override or path
            # 2026-07-15 T4: populate on FIRST use regardless of path shape —
            # it was gated behind `"{" in test_path`, so brace-less endpoints
            # that need seeded state (a2a token bodies, rewards query, root
            # webhooks) ran before any seeding when they came first in a
            # category. _populated-guarded → still runs once per instance.
            if not self._dynamic_ids.get("_populated"):
                await self._populate_dynamic_ids(developer_token, agent_token)
            if "{" in test_path:
                # OWL32: Comprehensive placeholder replacement with real IDs
                did = self._dynamic_ids.get("agent_did", "did:cos:unknown")
                agent2_did = self._dynamic_ids.get("agent_002_did", did)
                # 2026-04-28 — destructive admin/agent paths route {agent_did}
                # to the COUNTERPARTY (agent_002, real onboarded agent). Hits
                # the real code path against a real but sacrificial agent;
                # next audit run rebootstraps fresh. Primary stays alive so
                # agent-token tests work. NOT a forged DID — agent_002 is a
                # real bootstrapped agent in sandbox A.
                _DESTRUCTIVE_AGENT_PATHS = (
                    "/admin/agents/{agent_did}",
                    "/admin/enforcement/agents/{agent_did}/suspend",
                    "/admin/agents/{agent_did}/rotate-credentials",
                    "/admin/ironhand/revoke/{agent_did}",
                    "/onboard/agents/{agent_did}/reset-credentials",
                    "/developers/me/agents/{agent_did}",
                    "/agents/{agent_did}/logs",
                )
                _is_destructive = any(
                    path.startswith(d) or path == d for d in _DESTRUCTIVE_AGENT_PATHS
                )
                if _is_destructive:
                    test_path = test_path.replace("{agent_did}", agent2_did)
                    test_path = test_path.replace("{did}", agent2_did)
                    test_path = test_path.replace("{agent_id}", agent2_did)
                else:
                    test_path = test_path.replace("{agent_did}", did)
                    test_path = test_path.replace("{did}", did)
                    test_path = test_path.replace("{agent_id}", did)
                # P8.26b: Use real UUIDs from dynamic ID population
                pipeline_id = self._dynamic_ids.get("pipeline_id", "00000000-0000-0000-0000-000000000001")
                version_id = self._dynamic_ids.get("version_id", "00000000-0000-0000-0000-000000000001")
                pt_id = self._dynamic_ids.get("pipeline_template_id", "00000000-0000-0000-0000-000000000001")
                test_path = test_path.replace("{pipeline_id}", str(pipeline_id))
                test_path = test_path.replace("{version_id}", str(version_id))
                test_path = test_path.replace("{deployment_id}", "00000000-0000-0000-0000-000000000001")
                # For {template_id}: use pipeline template for pipeline-templates paths, else agent template
                if "/pipeline-templates/" in test_path:
                    test_path = test_path.replace("{template_id}", str(pt_id))
                elif "/agents/templates/" in path:
                    test_path = test_path.replace("{template_id}", "web-scraper")
                else:
                    test_path = test_path.replace("{template_id}", str(pt_id))
                # 2026-07-15: prefer REAL ids fetched by _populate_dynamic_ids
                # (fall back to the old literal only when the sandbox truly has
                # no such row — that endpoint then honestly 404s).
                _di = self._dynamic_ids
                test_path = test_path.replace("{contract_id}", str(_di.get("contract_id", "1")))
                # §SUITES1018 batch 8 (part 7): dispute ids are integers and "1" is the frame's first dispute ever
                # filed: a write (the admin ruling closes a dispute and moves both parties' reputation) with none of the
                # sweep's own names an id no dispute holds; a read may still name the first
                test_path = test_path.replace("{dispute_id}", str(_di.get("dispute_id") or (
                    "1" if method.upper() == "GET" else "2147483647")))
                test_path = test_path.replace("{proposal_id}", str(_di.get("proposal_id", "1")))
                test_path = test_path.replace("{key_id}", str(_di.get("key_id", "1")))
                # /webhooks/* (root store) vs /developers/me/webhooks — two stores,
                # two id spaces (T4). The category's DELETE gets the SACRIFICIAL
                # webhook so the keeper survives for deliveries/test (which run
                # after delete in registry order).
                if test_path.startswith("/webhooks/"):
                    _wid = (_di.get("root_webhook_del_id") if method == "DELETE"
                            else _di.get("root_webhook_id")) or _di.get("webhook_id", "1")
                    test_path = test_path.replace("{webhook_id}", str(_wid))
                elif test_path.startswith("/developers/webhooks/"):
                    # dev store (/developers/webhooks/{id}) — a SEPARATE store +
                    # id-space from /developers/me/webhooks and /admin/webhooks.
                    # Uses the dedicated dev_webhook_id (2026-07-16 round 4);
                    # DELETE gets the sacrificial so the keeper survives for
                    # test/deliveries (which run after delete in registry order).
                    _wid = (_di.get("dev_webhook_del_id") if method == "DELETE"
                            else _di.get("dev_webhook_id")) or _di.get("webhook_id", "1")
                    test_path = test_path.replace("{webhook_id}", str(_wid))
                elif test_path.startswith("/admin/webhooks/"):
                    # 2026-07-17: /admin/webhooks/{id}/{test,disable,enable} act on
                    # ANY webhook and SHARE the /developers/webhooks store (verified
                    # live: admin test on a seeded dev webhook → 200). The generic
                    # webhook_id can resolve to a /api/v1/webhooks id the admin
                    # lookup can't find → "Webhook not found" 404 (admin_health -3
                    # in isolation / early-in-sweep). Pin to the freshly-seeded
                    # dev_webhook_id, which the admin endpoint DOES find.
                    _wid = _di.get("dev_webhook_id") or _di.get("webhook_id") or "1"
                    test_path = test_path.replace("{webhook_id}", str(_wid))
                else:
                    # any other {webhook_id} consumer keeps the generic webhook_id
                    # (unchanged — no regression).
                    _wid = (_di.get("webhook_del_id") if method == "DELETE"
                            else _di.get("webhook_id")) or "1"
                    test_path = test_path.replace("{webhook_id}", str(_wid))
                test_path = test_path.replace("{peer_id}", str(_di.get("peer_id", "1")))
                test_path = test_path.replace("{slug}", str(_di.get("slug", "apitest-none")))
                test_path = test_path.replace("{card_id}", "1")
                # f037: Use actual card_id for HRI lookup (cards store ID as HRI fallback)
                _hri = self.test_fixes.dynamic_values.get("card_id") or "test-hri"
                test_path = test_path.replace("{human_readable_id:path}", str(_hri))
                test_path = test_path.replace("{human_readable_id}", str(_hri))
                test_path = test_path.replace("{settlement_id}", "test-settlement-001")
                test_path = test_path.replace("{distribution_id}", "1")
                test_path = test_path.replace("{transaction_id}", str(_di.get("transaction_id", "txn_1")))
                test_path = test_path.replace("{policy_id}", str(_di.get("policy_id", "1")))
                test_path = test_path.replace("{dispute_log_id}", str(_di.get("dispute_log_id", "1")))
                test_path = test_path.replace("{registry_url:path}", "peer.example.com")
                test_path = test_path.replace("{registry_url}", "https://peer.example.com")
                test_path = test_path.replace("{token}", "dummy-invitation-token")  # Invitations need real token
                test_path = test_path.replace("{chain_id}", "ethereum")
                test_path = test_path.replace("{wallet_address}", "0x1234567890123456789012345678901234567890")
                # Audit-fix Batch 3 (2026-04-28) — additional placeholders so
                # templated paths resolve to real-looking IDs and the endpoint
                # returns a meaningful 404/200 instead of 404 on literal "{X}".
                test_path = test_path.replace(
                    "{application_id}", self._dynamic_ids.get("application_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{license_id}", self._dynamic_ids.get("license_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{admission_id}", self._dynamic_ids.get("admission_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{invitation_id}", self._dynamic_ids.get("invitation_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{request_id}", self._dynamic_ids.get("request_id", "1")
                )
                test_path = test_path.replace(
                    "{org_id}", self._dynamic_ids.get("org_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{team_id}", self._dynamic_ids.get("team_id", "00000000-0000-0000-0000-000000000001")
                )
                test_path = test_path.replace(
                    "{ticket_id}", self._dynamic_ids.get("ticket_id", "1")
                )
                test_path = test_path.replace(
                    "{broadcast_id}", self._dynamic_ids.get("broadcast_id", "1")
                )
                test_path = test_path.replace(
                    "{action_id}", self._dynamic_ids.get("action_id", "test-action-001")
                )
                test_path = test_path.replace(
                    "{target_id}", self._dynamic_ids.get("target_id", "sandbox-a")
                )
                test_path = test_path.replace(
                    "{operator_id}", self._dynamic_ids.get("operator_id", "sandbox-a")
                )
                # §SUITES1018 batch 8: a read may name any developer (the first non-admin one, _populate_dynamic_ids);
                # a WRITE names an id no account holds, so it can never suspend, revoke or rewrite another's account
                # (the router names the sweep's own throwaway before base is reached; this is base's own category run)
                test_path = test_path.replace(
                    "{developer_id}", self._dynamic_ids.get("developer_id", "1") if method.upper() == "GET"
                    else "2147483647"
                )
                test_path = test_path.replace(
                    "{member_id}", self._dynamic_ids.get("member_id", "1")
                )
                # target_agent_did substitutes the COUNTERPARTY (agent_002 —
                # a real onboarded agent from get_sandbox_tokens). Destructive
                # endpoints exercise their real code path against a disposable
                # but real agent. The fallback string is only used when
                # bootstrap hasn't populated agent_002_did yet, in which case
                # the test should fail honestly with 404 not-found.
                test_path = test_path.replace(
                    "{target_agent_did}",
                    self._dynamic_ids.get("agent_002_did", did),
                )
                test_path = test_path.replace(
                    "{peer_id_or_name}", self._dynamic_ids.get("peer_id", "1")
                )
                test_path = test_path.replace("{event_type}", "TokensTransferred")
                # §ZKV2: v1.0.0 is retired (no key, no metadata); v2.0.0 serves every route.
                test_path = test_path.replace("{circuit_id:path}", "fairMarkupPolicy/v2.0.0")
                test_path = test_path.replace("{circuit_id}", "fairMarkupPolicy")
                test_path = test_path.replace("{circuit_name}", "fairMarkupPolicy")
                test_path = test_path.replace("{schedule_id}", "1")
                test_path = test_path.replace("{revocation_id}", "1")
                test_path = test_path.replace("{snapshot_id}", "1")
                test_path = test_path.replace("{tx_id}", "00000000-0000-0000-0000-000000000001")
                test_path = test_path.replace("{bridge_tx_id}", "00000000-0000-0000-0000-000000000001")
                test_path = test_path.replace("{base_id}", "00000000-0000-0000-0000-000000000001")
                test_path = test_path.replace("{npc_id}", "1")
                test_path = test_path.replace("{match_id}", "1")
                test_path = test_path.replace("{slot_index}", "0")
                test_path = test_path.replace("{facility_type}", "harvester")
                test_path = test_path.replace("{hri}", "test-hri")
                test_path = test_path.replace("{peer_did}", "did:theprotocol:operator:sandbox-a")
                test_path = test_path.replace("{frame_invitation_id}", "00000000-0000-0000-0000-000000000001")
                test_path = test_path.replace("{funding_request_id}", "1")
                test_path = test_path.replace("{target_dev_id}", "2")
                test_path = test_path.replace("{code}", "AUDIT-CODE-001")
                test_path = test_path.replace("{id}", "1")  # Must be LAST (catch-all)
            
            # P8.26b: Body overrides — ensure correct fields regardless of body source
            import time as _bt
            _bts = int(_bt.time())
            if body is not None and isinstance(body, dict) and method in ["POST", "PUT", "PATCH"]:
                import copy as _bcopy
                body = _bcopy.deepcopy(body)
                
                # Fix #01: agent-builder/generate needs wrapper_model_name + correct type
                if path == "/agent-builder/generate":
                    body["agent_builder_type"] = body.get("agent_builder_type", "simple_wrapper")
                    body["wrapper_model_name"] = body.get("wrapper_model_name", "gpt-4")
                    body["wrapper_llm_backend_type"] = body.get("wrapper_llm_backend_type", "openai_api")
                    body.pop("type", None)  # Remove wrong field if present
                    logger.info(f"P8.26b: Fixed agent-builder body: type={body['agent_builder_type']}, model={body['wrapper_model_name']}")
                
                # Fix #06: Pipeline POST — unique name per run
                if path == "/agents/{agent_did}/pipelines" and method == "POST":
                    body["pipeline_name"] = f"test-pipeline-{_bts}"
                    logger.info(f"P8.26b: Pipeline name → {body['pipeline_name']}")
                
                # Fix #09: Version POST — unique version per run
                if path == "/agents/{agent_did}/versions" and method == "POST":
                    body["version"] = f"1.0.{_bts % 10000}"
                    logger.info(f"P8.26b: Version → {body['version']}")
                
                # Fix #17: disputes/enhanced/log — correct reason_code
                if path == "/disputes/enhanced/log":
                    body["reason_code"] = "SERVICE_NOT_DELIVERED"
                    logger.info("P8.26b: Fixed dispute reason_code → SERVICE_NOT_DELIVERED")
                
                # Fix #18: federation/disputes/slash-request — unique settlement_id
                if path == "/federation/disputes/slash-request":
                    body["settlement_id"] = f"test-settlement-{_bts}"
                    logger.info(f"P8.26b: Slash request settlement_id → {body['settlement_id']}")
                
                # Fix #19: federation/sync-request — ensure all required fields
                if path == "/federation/sync-request":
                    body.setdefault("source_registry", "spiffe://agentvault.com/service/registry-test")
                    body.setdefault("sync_timestamp", datetime.now(timezone.utc).isoformat())
                    body.setdefault("agent_cards", [])
                    body.setdefault("sync_type", "full")
                    logger.info("P8.26b: Fixed sync-request body with source_registry=SPIFFE ID + sync_timestamp")
                
                # Fix #32: teg/policies POST — REMOVED (P8.26e: now handled by FORCE handler in admin_api_test.py)
                # base.py override was colliding with prereq handler in same second → 409
                # if path == "/teg/policies" and method == "POST":
                #     body["policy_code"] = f"GOV_POLICY_{_bts}"
                #     logger.info(f"P8.26b: TEG policy code → {body['policy_code']}")
                
                # Fix #32b: teg/policies/batch — unique codes
                if path == "/teg/policies/batch" and method == "POST":
                    for i, p in enumerate(body.get("policies", [])):
                        p["policy_code"] = f"BATCH_POLICY_{_bts}_{i}"
            
            # P8.26b: Ensure body exists for POST endpoints that need one
            if body is None and method == "POST":
                if path == "/agent-builder/generate":
                    body = {
                        "name": "Test Agent", "description": "Test agent",
                        "agent_builder_type": "simple_wrapper",
                        "wrapper_model_name": "gpt-4",
                        "wrapper_llm_backend_type": "openai_api",
                        "capabilities": [], "configuration": {}
                    }
                elif path == "/disputes/enhanced/log":
                    body = {
                        "defendant_agent_id": "did:cos:test-defendant-sandbox",
                        "reason_code": "SERVICE_NOT_DELIVERED",
                        "brief_description": "Test dispute from automated testing"
                    }
                elif path == "/federation/sync-request":
                    body = {
                        "source_registry": "https://peer-registry.example.com",
                        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent_cards": [], "sync_type": "full"
                    }
            
            # Prepare request
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Get headers with auth
                auth_headers = await self.auth_manager.get_headers(
                    auth_type=auth_type,
                    developer_token=developer_token,
                    agent_token=agent_token,
                    path=path
                )
                
                # Merge with custom headers if provided
                final_headers = auth_headers.copy()
                if headers:
                    final_headers.update(headers)

                # 2026-07-15 T4 (always-on — placed OUTSIDE the "{"-placeholder
                # guard, which skipped brace-less paths entirely):
                _di4 = self._dynamic_ids
                # /teg/rewards/claim takes agent_did as a QUERY param (no body);
                # without it FastAPI 422s before the handler.
                if test_path.endswith("/teg/rewards/claim") and "?" not in test_path and _di4.get("agent_did"):
                    test_path = f"{test_path}?agent_did={_di4.get('agent_did')}"
                # (a2a settle/release are PAYER-scoped per the router docstring —
                # "Must be called by the CALLER agent (the payer)" — so no actor
                # swap; each endpoint instead gets its OWN fresh token below,
                # because verify CONSUMES whatever token it checks.)
                # /teg/staking/unstake needs the REAL stake_id of the seeded
                # TEG-direct stake (body shipped a placeholder → "not found").
                if path == "/teg/staking/unstake" and isinstance(body, dict) and _di4.get("teg_stake_id"):
                    body = {**body, "stake_id": _di4["teg_stake_id"]}
                # a2a verify/settle/release — the API field is `token`, and only
                # a REAL apt_ token from the _populate seeds passes the hash
                # lookup. MUST live here in the always-on block: these paths
                # carry no "{...}" placeholder, so the brace-guarded chain never
                # sees them (the original bug). verify CONSUMES its token, so
                # each endpoint gets its own seed.
                if isinstance(body, dict) and "/a2a-payment/" in (path or ""):
                    body = dict(body)
                    body.pop("payment_token", None)
                    _a2a_slot = {"/a2a-payment/verify": "payment_token",
                                 "/a2a-payment/settle": "payment_token_2",
                                 "/a2a-payment/release": "payment_token_3"}.get(path)
                    if _a2a_slot and _di4.get(_a2a_slot):
                        body["token"] = _di4[_a2a_slot]

                # §pass63 follow-up (2026-05-22) — `/.well-known/*` lives at
                # nginx root, NOT under /api/v1. Without this guard the inline
                # dispatcher would 404 on registry-card.json / registry-jwks.json
                # / registry-card-schema.json. Mirrors core/contract.py:255 guard.
                if test_path.startswith("/.well-known/"):
                    request_url = f"{self.base_url}{test_path}"
                else:
                    request_url = f"{self.base_url}/api/v1{test_path}"
                # Prepare request kwargs
                kwargs = {
                    "method": method,
                    "url": request_url,
                    "headers": final_headers,
                }

                # 2026-07-15: a few POST mutators take an OPTIONAL/empty JSON body
                # but 422 when sent no content at all. Default those to {} (safe
                # allowlist — endpoints requiring fields still 422, unchanged).
                if body is None and method == "POST":
                    _EMPTY_BODY_OK = (
                        "/rewards/claim", "/webhooks/", "/cross-teg-balance-sync",
                        "/force-mtls-enroll", "/heartbeat", "/reverify", "/tally",
                        "/claim", "/acknowledge", "/sync",
                    )
                    if any(seg in path for seg in _EMPTY_BODY_OK):
                        body = {}

                # f037: Substitute token placeholders in request bodies
                if isinstance(body, dict) and developer_token:
                    for k, v in body.items():
                        if v == "SANDBOX_DEV_TOKEN_PLACEHOLDER":
                            body[k] = developer_token

                # Add body if needed
                # PC (2026-04-22 Pass 2): include DELETE so admin endpoints that
                # require a confirm body (e.g. DELETE /admin/developers/{id} needs
                # confirm_email + reason) receive the body template. Previously
                # DELETE never sent a body → 422 "Field required".
                if body is not None and method in ["POST", "PUT", "PATCH", "DELETE"]:
                    if is_form_data:
                        kwargs["data"] = body
                    else:
                        # Handle special case for string-only bodies
                        if isinstance(body, str):
                            kwargs["content"] = body
                            if "Content-Type" not in final_headers:
                                final_headers["Content-Type"] = "text/plain"
                        else:
                            kwargs["content"] = json.dumps(body)
                            if "Content-Type" not in final_headers:
                                final_headers["Content-Type"] = "application/json"
                
                # Make initial request — with a transient-blip retry for idempotent
                # GET reads (2026-07-16). A single sequential sweep on a loaded box
                # occasionally sees a 502/503/504 (e.g. "Event Store unreachable" on
                # a heavy /teg/transactions/export) or a read timeout that is NOT an
                # endpoint fault — it clears on retry. Retry GET up to 3x on those
                # transient conditions with a short backoff. A genuinely-down
                # endpoint still fails (all retries fail → surfaces) → honest. Non-GET
                # (mutating) requests are never retried — preserves exactly-once.
                _is_get = (method or "GET").upper() == "GET"
                response = None
                for _attempt in range(3 if _is_get else 1):
                    try:
                        response = await client.request(**kwargs)
                        if not (_is_get and response.status_code in (502, 503, 504)):
                            break
                    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
                        if not _is_get or _attempt == 2:
                            raise
                    if _is_get and _attempt < 2:
                        await asyncio.sleep(1.5 * (_attempt + 1))
                response_time = int((time.time() - start_time) * 1000)

                # Parse response
                response_data = await self._parse_response(response)

                # Check if response is healthy
                healthy = await self._check_health(response, response_data)

                # 2026-07-15 Wave C — expected-4xx: a correct rejection (dup 409,
                # non-party/non-arbiter 403) with a well-formed error body.
                # Only flips fail→EF, never masks a 5xx or an unexpected code.
                # §SUITES1018 (2026-10-18): such a refusal is an EXPECTED FAILURE, no longer a pass. It shows the route
                # refusing correctly, not the route doing its work: the 2026-10-18 sweep counted 157 rows answering 4xx
                # as passes ("no arena match on a clean sandbox: 404"), which is the same inflation the consoles' own
                # summary warns about (EF counted before healthy). The contract layer has always stamped a matched
                # FailureMode this way (healthy, expected_failure); the inline chain now agrees with it.
                _ef_flag = False
                _ef_reason = None
                _ef_bucket = None
                if healthy and response.status_code >= 400:
                    _ef_flag, _ef_bucket = True, "accepted_refusal"
                    if response.status_code == 501:
                        # §SUITES1018 batch 8: a capability this node does not host says so first (the OAuth surface
                        # fails closed with no trusted registry: 501 by design, not an unbuilt route)
                        _cap501, _cb501 = _classify_capability_gate(path, 501)
                        _ef_reason = _cap501 or "the route answers 501 Not Implemented: declared unbuilt"
                        if _cap501:
                            _ef_bucket = _cb501
                    elif response.status_code == 503:
                        _ef_reason = "the attestation service is unavailable here (a TEG dependency): 503 is its answer"
                    else:
                        _ef_reason = f"a business-rule refusal ({response.status_code}) the harness accepts"
                if not healthy and response.status_code == 410 and isinstance(response_data, dict) and (
                        "error" in response_data or "detail" in response_data):
                    # §SUITES1018: 410 Gone is a deliberate answer, never an accident: a retired route that stays to tell
                    # old callers so (two contract routes since §TWOAGENT), or a single-use link the sweep does not hold
                    # (the frame kit's). An expected failure with the route's own sentence.
                    healthy = True
                    _ef_flag, _ef_bucket = True, "accepted_refusal"
                    _ef_reason = "410 Gone, a deliberate answer (a retired route or a spent single-use link): " + str(
                        response_data.get("detail") or (response_data.get("error") or {}).get("detail") or "")[:160]
                if healthy and response.status_code < 300 and isinstance(response_data, dict) \
                        and response_data.get("ok") is False and any(k in path for k in _OK_FALSE_REFUSALS):
                    _ef_flag, _ef_bucket = True, "accepted_refusal"
                    _ef_reason = (f"the route refused in its body (ok:false: "
                                  f"{str(response_data.get('error') or response_data.get('reason') or '')[:160]})")
                if not healthy:
                    _pw = _classify_peer_write_refusal(method, path, response.status_code, response_data) \
                        or _classify_sentence_refusal(method, path, response.status_code, response_data)
                    if _pw:
                        healthy = True
                        _ef_flag, _ef_reason, _ef_bucket = True, _pw, "accepted_refusal"
                if not healthy:
                    # §MCPTEST: capability gates first — a node that deliberately
                    # does not host the feature is EF, never a silent pass.
                    _cap, _cbucket = _classify_capability_gate(path, response.status_code)
                    if _cap:
                        logger.info(
                            f"CAPABILITY-ABSENT EF: {method} {path} "
                            f"{response.status_code} — {_cap}")
                        healthy = True
                        _ef_flag, _ef_reason, _ef_bucket = True, _cap, _cbucket
                    else:
                        _exp = _classify_expected_4xx(method, path, response.status_code, response_data)
                        if _exp:
                            logger.info(f"EXPECTED-4XX EF: {method} {path} {response.status_code} — {_exp}")
                            healthy = True
                            _ef_flag, _ef_reason, _ef_bucket = True, _exp, "accepted_refusal"

                # Handle 401 with token retry
                if response.status_code == 401 and developer_token and agent_token:
                    retry_result = await self._retry_with_alternate_token(
                        client, kwargs, final_headers, auth_type,
                        developer_token, agent_token, start_time
                    )
                    if retry_result:
                        return retry_result
                
                # Log auth failures
                if response.status_code in [401, 403] and not healthy:
                    logger.warning(
                        f"Auth failed for {method} {path}: {response.status_code}, "
                        f"auth_type={auth_type}, had_token={bool(final_headers.get('Authorization'))}"
                    )
                
                return {
                    "path": path,
                    "method": method,
                    "authRequired": auth_type,
                    "healthy": healthy,
                    "statusCode": response.status_code,
                    "responseTime": response_time,
                    "responseData": response_data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": None if healthy else f"HTTP {response.status_code}",
                    "actualAuthUsed": auth_type,
                    "expected_failure": _ef_flag,
                    "expected_failure_reason": _ef_reason,
                    "failure_bucket": _ef_bucket,
                }
                
        except httpx.TimeoutException:
            # §MCPTEST 2026-08-06 — SSE endpoints are StreamingResponse with
            # media_type="text/event-stream": they deliberately never terminate,
            # so a request-completion timeout is the CORRECT observation, not a
            # defect. Stamped EF (never a pass) — proving the stream carries the
            # right events needs a streaming client, which is a flow-suite job.
            _stream_ef = any(k in (path or "") for k in _STREAMING_PATHS)
            return {
                "path": path,
                "method": method,
                "authRequired": auth_type,
                "healthy": bool(_stream_ef),
                "statusCode": None,
                "responseTime": int(timeout * 1000),
                "responseData": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": None if _stream_ef else f"Timeout ({timeout}s)",
                "expected_failure": bool(_stream_ef),
                "expected_failure_reason": (
                    "server-sent-events stream never terminates — a completion "
                    "timeout is the correct observation for text/event-stream"
                ) if _stream_ef else None,
                "failure_bucket": "bucket_1_impossible" if _stream_ef else None,
            }
        except Exception as e:
            return {
                "path": path,
                "method": method,
                "authRequired": auth_type,
                "healthy": False,
                "statusCode": None,
                "responseTime": int((time.time() - start_time) * 1000),
                "responseData": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e)
            }
    
    async def _parse_response(self, response: httpx.Response) -> Any:
        """Parse response data, handling JSON and text responses"""
        try:
            return response.json() if response.content else None
        except:
            return response.text if response.content else None
    
    async def _check_health(self, response: httpx.Response, response_data: Any) -> bool:
        """
        Check if response indicates a healthy endpoint.
        
        Handles special cases where 4xx responses are valid business logic.
        """
        # 2xx and 3xx are healthy
        if 200 <= response.status_code < 400:
            return True

        # 501 Not Implemented = intentionally-unbuilt endpoint (e.g. batch
        # transfer/transactions). Not a fault of the deployment — treat as
        # healthy-skip, mirroring the _SKIP_ENDPOINTS policy (2026-07-15).
        if response.status_code == 501:
            return True

        # Special case: Some 400 responses are valid business logic
        if response.status_code == 400 and response_data and isinstance(response_data, dict):
            error_info = response_data.get('error', {})
            error_detail = ""
            
            if isinstance(error_info, dict):
                error_detail = error_info.get('detail', '')
            else:
                error_detail = str(error_info)
            
            # Valid business logic errors
            valid_business_errors = [
                "No payouts to claim",
                "Stake is in cooldown period",
                "Cannot approve peer registry with status",
                "Cannot deactivate peer registry with status",
                "not found or not in PROPOSED status",
                "not found or not in correct status",
                "not found or not in PENDING_MERGE status"
            ]
            
            for valid_error in valid_business_errors:
                if valid_error in error_detail:
                    logger.info(f"Business logic response: {error_detail}")
                    return True
        
        # f037: Only attestation submission is expected to fail (TEG service dependency)
        if response.status_code == 503 and "/teg/attestations/submit" in str(response.url):
            logger.info("Expected failure: attestation service unavailable")
            return True

        return False

    async def _retry_with_alternate_token(
        self,
        client: httpx.AsyncClient,
        kwargs: Dict[str, Any],
        headers: Dict[str, str],
        auth_type: str,
        developer_token: str,
        agent_token: str,
        start_time: float
    ) -> Optional[Dict[str, Any]]:
        """
        Retry request with alternate token type on 401 error.
        
        This implements the intelligent token retry logic discovered in testing.
        """
        current_auth = headers.get("Authorization", "")
        
        # Determine which token to try next
        if auth_type == "agent" and f"Bearer {agent_token}" in current_auth:
            logger.info("Agent token failed, trying developer token...")
            headers["Authorization"] = f"Bearer {developer_token}"
            new_auth_type = "developer"
        elif auth_type == "developer" and f"Bearer {developer_token}" in current_auth:
            logger.info("Developer token failed, trying agent token...")
            headers["Authorization"] = f"Bearer {agent_token}"
            new_auth_type = "agent"
        else:
            return None
        
        # Update kwargs with new headers
        kwargs["headers"] = headers
        
        # Retry request
        response = await client.request(**kwargs)
        
        if 200 <= response.status_code < 400:
            logger.info(f"SUCCESS: {new_auth_type} token worked!")
            response_time = int((time.time() - start_time) * 1000)
            response_data = await self._parse_response(response)
            
            return {
                "path": kwargs["url"].split("/api/v1")[-1],
                "method": kwargs["method"],
                "authRequired": auth_type,
                "healthy": True,
                "statusCode": response.status_code,
                "responseTime": response_time,
                "responseData": response_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": None,
                "actualAuthUsed": new_auth_type
            }
        
        # §MCPTEST 2026-08-06 — THE SUITE SUSPENDS ITS OWN FIXTURE AGENT.
        # /admin/enforcement/agents/{agent_did}/suspend and
        # /admin/agents/bulk/suspend resolve {agent_did} to the runner's OWN
        # agent, so every later agent-authed call 403s "Agent account is
        # suspended" until the ~30-min token refresh. Measured 2026-08-06:
        # 43 fixture agents suspended in a single sweep.
        #
        # It surfaces HERE, not at the caller: the endpoint registry marks these
        # auth=developer, so the dev token 401s first and this retry is what
        # actually meets the 403. Returning a bare None threw that away and the
        # 401 got stamped "requires agent JWT" — a real, self-inflicted, and
        # RECOVERABLE condition reported as an endpoint property.
        # Clearing the cache makes the next call re-onboard a FRESH agent
        # (get_sandbox_tokens bootstraps new ones), the same recovery the
        # revoked-agent path already relies on.
        try:
            _detail = ""
            try:
                _detail = str(await self._parse_response(response)).lower()
            except Exception:
                pass
            if response.status_code == 403 and (
                "suspended" in _detail or "revoked" in _detail
            ):
                from agentvault_registry.routers.admin_api_test import (
                    _sandbox_tokens as _st,
                )
                _st["developer"] = None
                _st["agent"] = None
                _st["acquired_at"] = 0
                try:
                    await _st.clear_redis()
                except Exception:
                    pass
                logger.warning(
                    "[FixtureAgentDown] alternate-token retry hit "
                    f"{response.status_code} ({_detail[:60]}) — cleared sandbox "
                    "token cache; next call re-onboards a fresh agent."
                )
        except Exception as _fa_exc:  # never let recovery break a test result
            logger.debug(f"[FixtureAgentDown] handler failed: {_fa_exc!r}")

        logger.warning("Both tokens failed")
        return None
    
    async def test_category_endpoints(
        self,
        category: str,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        priority_only: bool = False
    ) -> Dict[str, Any]:
        """Test all endpoints in a category"""
        await self.setup_category(category)
        
        # Get endpoints for category
        endpoints = self.endpoints_registry.get_category_endpoints(category)
        if not endpoints:
            raise ValueError(f"No endpoints found for category: {category}")
        
        # Filter for priority if requested
        if priority_only and hasattr(self, 'PRIORITY_ENDPOINTS'):
            priority_paths = getattr(self, 'PRIORITY_ENDPOINTS', [])
            endpoints = [ep for ep in endpoints if ep['path'] in priority_paths]
        
        # OWL32: Pre-populate dynamic IDs before parallel test execution
        # (avoids race condition in asyncio.gather where multiple tasks
        # check _populated flag before the HTTP call completes)
        await self._populate_dynamic_ids(developer_token, agent_token)

        # 2026-07-15: switch request bodies to SANDBOX mode with the REAL DIDs we
        # just resolved, so module-path bodies stop shipping the static fakes
        # (did:cos:test-recipient / did:cos:fbf7393c…) that 404. Best-effort.
        try:
            self.request_bodies.enable_sandbox_mode(
                agent_did=self._dynamic_ids.get("agent_did"),
                agent_002_did=self._dynamic_ids.get("agent_002_did"),
            )
        except Exception as _e:
            logger.warning(f"enable_sandbox_mode skipped: {_e}")

        # Resolve per-endpoint call specs up-front (body/form) so execution is
        # a clean loop regardless of concurrency mode.
        specs = []
        for endpoint in endpoints:
            # Get request body if needed. 2026-07-15: DELETE included — several
            # deletes require a confirm body (registered in request_bodies) that
            # was never being fetched → 422.
            body = None
            if endpoint['method'] in ['POST', 'PUT', 'PATCH', 'DELETE']:
                body = self.request_bodies.get_body(endpoint['path'])
            # 2026-07-15 T4: inject the REAL seeded a2a payment tokens (static
            # placeholder bodies 422'd). settle CONSUMES the first token, so
            # release rides the second.
            _p = endpoint['path']
            if _p in ("/a2a-payment/verify", "/a2a-payment/settle") and self._dynamic_ids.get("payment_token"):
                body = {**(body or {}), "token": self._dynamic_ids["payment_token"]}
            elif _p == "/a2a-payment/release" and self._dynamic_ids.get("payment_token_2"):
                body = {**(body or {}), "token": self._dynamic_ids["payment_token_2"]}
            is_form_data = self.request_bodies.is_form_data(endpoint['path'])
            specs.append((endpoint, body, is_form_data))

        async def _run_one(_endpoint, _body, _is_form):
            return await self.test_endpoint(
                method=_endpoint['method'],
                path=_endpoint['path'],
                auth_type=_endpoint['auth'],
                body=_body,
                developer_token=developer_token,
                agent_token=agent_token,
                is_form_data=_is_form,
            )

        # 2026-07-15: run endpoints SEQUENTIALLY by default. Firing a whole
        # category (admin = 55 endpoints) concurrently via asyncio.gather
        # saturated the sandbox pgbouncer/asyncpg pool → connections dropped
        # mid-query (ConnectionDoesNotExistError) → healthy endpoints TIMED OUT
        # and were counted red (e.g. /auth/api-keys returns 200 in 3s direct but
        # timed out at 60s inside a 55-wide gather). Sequential keeps the DB
        # stable so the harness measures the ENDPOINT, not the pool — and it also
        # kills the OWL32 _populated race entirely. Tunable via
        # API_TEST_CATEGORY_CONCURRENCY (default 1 = sequential; >1 = bounded).
        try:
            _conc = max(1, int(os.getenv("API_TEST_CATEGORY_CONCURRENCY", "1")))
        except ValueError:
            _conc = 1

        if _conc == 1:
            results = []
            for _spec in specs:
                results.append(await _run_one(*_spec))
        else:
            _sem = asyncio.Semaphore(_conc)

            async def _guarded(_spec):
                async with _sem:
                    return await _run_one(*_spec)

            results = await asyncio.gather(*[_guarded(s) for s in specs])
        self.results = results
        return {
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": _summarize_results(results),
            "results": results
        }
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Alias for test_category_endpoints — called by runner and subclass overrides."""
        return await self.test_category_endpoints(
            category=self.category_name,
            developer_token=developer_token,
            agent_token=agent_token,
        )

    def get_failed_endpoints(self) -> List[Dict[str, Any]]:
        """Get list of failed endpoints from last test run (a row not measured is not a failure)"""
        return [r for r in self.results if not r['healthy'] and not r.get('not_measured')]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of last test run"""
        if not self.results:
            return {"error": "No test results available"}
        return {
            "category": self.category_name,
            **_summarize_results(self.results),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
