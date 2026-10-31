"""FederationTestRig — single orchestrator for multi-registry MCP test scenarios.

Holds MCP clients for every sandbox registry (mainframe + cloud-op, public +
admin tier). Tests use `rig.mcp(label).call(tool, **args)` to invoke any tool
against any registry. The `assert_within` poller wraps eventual-consistency
assertions with a configurable budget.

Networking model:
  Each registry has its own container. The runner runs INSIDE the TARGET
  registry (API_TEST_TARGET_URL) — to reach all 4 sandbox registries,
  the rig uses `docker exec <target_container> curl localhost:8000/mcp/rpc`.
  Same pattern as flow_mcp_lifecycle._mcp_rpc_call.

Auth model:
  - sandbox-A + sandbox-B: commander admin developer (API_TEST_FED_{A,B}_EMAIL and
    _PASSWORD, by default core/sandbox_creds' SANDBOX_ADMIN_*): login via /auth/login to mint dev JWT
  - sandboxalpha + sandboxdelta: cloud-op admin (admin@cloud-op-<op>.dev),
    password from API_TEST_FED_{ALPHA,DELTA}_PASSWORD — NO literal default and
    none written here; an unset var refuses at login by name.

  MCP API keys can also be used (per [[reference_sandbox_cloudop_creds]]) but
  the dev JWT path is simpler + avoids key drift.

Failure model:
  - MCP errors bubble up as MCPError exceptions
  - assert_within returns AssertionResult — never raises (so tests can wrap)
  - Each test catches its own exceptions; rig propagates infrastructure errors
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import datetime as _dt
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agentvault_registry.api_tests.multiframe_helpers import (
    exec_in_container, _split_http_body_code, _HTTP_MARKER,
)
from agentvault_registry.api_tests.probe_meter import record_transport_lost
# §SBROTATE — sandbox fixture creds (no secret default; unset ⇒ login fails loudly).
# §MCPTEST-MCP10: this line previously sat INSIDE the parenthesised import above,
# which is a SyntaxError — the module has not compiled since §SBROTATE. It went
# unseen because nothing ran `compileall` over api_tests/ and pyflakes reports a
# syntax error without failing the undefined-name gate the CI keys on.
from agentvault_registry.core.sandbox_creds import (
    SANDBOX_ADMIN_PASSWORD,
    SANDBOX_TUTORIAL_PASSWORD,
)

logger = logging.getLogger(__name__)

# ─── Target overrides (§FEDTARGETS 2026-09-04) ─────────────────────────────
# This suite named the RETIRED sandbox tier by literal in eight places and had
# no env hook at all. On a fresh tier every `docker exec` therefore addressed a
# container that still EXISTS but is Exited — which Docker answers with
# `APIError 409`, not a clean "no such container". That is the identical
# failure that made the cloud-op MCP sweep report "0 tools in 0.36 s", so it
# reads as an empty run rather than a broken one.
#
# Every name is now env-overridable with the ORIGINAL literal as its default:
# the retired tier behaves exactly as before, and a fresh tier is one env block
# away. Same remedy as §APITEST applied to the five api_tests literals.
#
# ⚠ These are read by the process that EXECUTES the suite, which is the TARGET
# registry — mcp_tester POSTs to {API_TEST_TARGET_URL}/admin/api-test/test-flow
# (mcp_tester.py:1266) — NOT the caller. Set them on the sandbox frame's
# compose, never only on registry-a.

def _env(name: str, default: str) -> str:
    return os.getenv(name, default) or default


def _env_secret(name: str) -> Optional[str]:
    """Read a SECRET from the environment. No literal default, ever.

    §SBROTATE's rule, applied here late: a secret default is worse than no
    default, because it turns "not configured" into "configured wrong, quietly".
    Both operator passwords used to fall back to a repo literal, so after a
    rotation a missing or stale env would log in with a dead string and the
    operator legs would report a CREDENTIAL failure as some other kind of red —
    three sessions later, with no clue pointing at the env.

    Returns None when unset/blank; `_require_secret` turns that into a loud
    refusal at LOGIN time. Deliberately not at import time: a tier that does not
    exercise the operators should still be able to import the rig.
    """
    v = os.getenv(name)
    return v.strip() if v and v.strip() else None


def _require_secret(value: Optional[str], env_name: str, label: str) -> str:
    """Refuse to attempt a login with an unset secret, and say which var."""
    if not value:
        raise MCPError(
            label, "_login", "000",
            f"{env_name} is not set — refusing to log in with no credential. "
            f"This used to fall back to a repo literal, which turned a missing "
            f"env into a silent wrong-password 401. Set {env_name} on the "
            f"runner (sbx-alpha-registry's compose env) for this tier.",
        )
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("[fed-rig] %s=%r is not an int — falling back to %d",
                       name, raw, default)
        return default


_FED_MAINFRAME_EMAIL = _env("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox")

_FED_A_CONTAINER = _env("API_TEST_FED_A_CONTAINER", "agentvault_registry_test")
_FED_A_PORT      = _env_int("API_TEST_FED_A_PORT", 8002)
_FED_B_CONTAINER = _env("API_TEST_FED_B_CONTAINER", "agentvault_registry_test_b")
_FED_B_PORT      = _env_int("API_TEST_FED_B_PORT", 8003)
# §FEDTARGETS: the rig assumed ONE mainframe credential for BOTH frames. That
# holds only where the two frames were provisioned from the same fixture; a
# fresh Frame B has its own admin, and the shared login 401s. Per-frame now,
# defaulting to the shared values so the old tier is unchanged.
_FED_B_EMAIL     = _env("API_TEST_FED_B_EMAIL", _FED_MAINFRAME_EMAIL)
_FED_B_PASSWORD  = _env("API_TEST_FED_B_PASSWORD", SANDBOX_ADMIN_PASSWORD or "")
# §EVTYPES 2026-09-05: §FEDTARGETS split the credential per-frame for B and left A
# hardcoded to the shared SANDBOX_ADMIN_* pair. That silently pins the whole suite to
# the frame those globals belong to: run it from the OTHER frame and `sandbox-A` dials
# that frame with the first frame's login, 401s on every probe, and each test burns its
# full budget before reporting "budget exhausted" — 403 of 557 rows, none of which names
# a credential. (Measured 2026-09-05 running the suite from sbx-beta; the env there
# already carried API_TEST_FED_A_EMAIL/PASSWORD, which nothing read.) Mirror B exactly.
_FED_A_EMAIL     = _env("API_TEST_FED_A_EMAIL", _FED_MAINFRAME_EMAIL)
_FED_A_PASSWORD  = _env("API_TEST_FED_A_PASSWORD", SANDBOX_ADMIN_PASSWORD or "")

_FED_ALPHA_CONTAINER = _env("API_TEST_FED_ALPHA_CONTAINER",
                            "cloud-op-sandboxalpha-registry")
_FED_ALPHA_PORT      = _env_int("API_TEST_FED_ALPHA_PORT", 30000)
_FED_ALPHA_EMAIL     = _env("API_TEST_FED_ALPHA_EMAIL",
                            "admin@cloud-op-sandboxalpha.dev")
# ⚠ THE LITERAL IS GONE (2026-09-05). It was kept as "a stale string, not a
# credential in use" with excision noted as a follow-up; this is that follow-up,
# done the day the operator admins actually rotated. A stale secret default is
# not harmless — it converts an unset env into a quiet 401 that reads like a
# product refusal. Unset now fails loudly, by variable name, at login.
_FED_ALPHA_PASSWORD  = _env_secret("API_TEST_FED_ALPHA_PASSWORD")

_FED_DELTA_CONTAINER = _env("API_TEST_FED_DELTA_CONTAINER",
                            "cloud-op-sandboxdelta-registry")
_FED_DELTA_PORT      = _env_int("API_TEST_FED_DELTA_PORT", 30100)
_FED_DELTA_EMAIL     = _env("API_TEST_FED_DELTA_EMAIL",
                            "admin@cloud-op-sandboxdelta.dev")
_FED_DELTA_PASSWORD  = _env_secret("API_TEST_FED_DELTA_PASSWORD")



# ─── Registry topology ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegistrySpec:
    """One sandbox registry endpoint."""
    label: str
    container: str
    host_port: int
    rpc_path: str           # "/mcp/rpc" or "/mcp/admin/rpc"
    admin_email: str
    admin_password: Optional[str]
    frame: str              # "frame-a" | "frame-b"
    role: str               # "mainframe" | "cloud-op"
    # ⚠ Defaulted field LAST: a dataclass cannot put a defaulted field before a
    # required one, and putting it beside admin_password raised TypeError at
    # IMPORT — which the boot-import gate would have caught, but only after a
    # build. Cheaper to keep the ordering rule in view here.
    password_env: str = ""      # the env var that supplies it, named in refusals


SANDBOX_REGISTRIES: Dict[str, RegistrySpec] = {
    # Mainframes
    "sandbox-A": RegistrySpec(
        label="sandbox-A",
        container=_FED_A_CONTAINER,
        host_port=_FED_A_PORT,
        rpc_path="/mcp/rpc",
        admin_email=_FED_A_EMAIL,
        admin_password=_FED_A_PASSWORD,
        frame="frame-a",
        role="mainframe",
        password_env="API_TEST_FED_A_PASSWORD",
    ),
    "sandbox-A-admin": RegistrySpec(
        label="sandbox-A-admin",
        container=_FED_A_CONTAINER,
        host_port=_FED_A_PORT,
        rpc_path="/mcp/admin/rpc",
        admin_email=_FED_A_EMAIL,
        admin_password=_FED_A_PASSWORD,
        frame="frame-a",
        role="mainframe",
        password_env="API_TEST_FED_A_PASSWORD",
    ),
    "sandbox-B": RegistrySpec(
        label="sandbox-B",
        container=_FED_B_CONTAINER,
        host_port=_FED_B_PORT,
        rpc_path="/mcp/rpc",
        admin_email=_FED_B_EMAIL,
        admin_password=_FED_B_PASSWORD,
        frame="frame-b",
        role="mainframe",
        password_env="API_TEST_FED_B_PASSWORD",
    ),
    "sandbox-B-admin": RegistrySpec(
        label="sandbox-B-admin",
        container=_FED_B_CONTAINER,
        host_port=_FED_B_PORT,
        rpc_path="/mcp/admin/rpc",
        admin_email=_FED_B_EMAIL,
        admin_password=_FED_B_PASSWORD,
        frame="frame-b",
        role="mainframe",
        password_env="API_TEST_FED_B_PASSWORD",
    ),
    # Cloud-ops (§pass73.3 topology — alpha (frame-a child) + delta (frame-b child))
    "sandboxalpha": RegistrySpec(
        label="sandboxalpha",
        container=_FED_ALPHA_CONTAINER,
        host_port=_FED_ALPHA_PORT,
        rpc_path="/mcp/rpc",
        admin_email=_FED_ALPHA_EMAIL,
        admin_password=_FED_ALPHA_PASSWORD,
        password_env="API_TEST_FED_ALPHA_PASSWORD",
        frame="frame-a",
        role="cloud-op",
    ),
    "sandboxalpha-admin": RegistrySpec(
        label="sandboxalpha-admin",
        container=_FED_ALPHA_CONTAINER,
        host_port=_FED_ALPHA_PORT,
        rpc_path="/mcp/admin/rpc",
        admin_email=_FED_ALPHA_EMAIL,
        admin_password=_FED_ALPHA_PASSWORD,
        password_env="API_TEST_FED_ALPHA_PASSWORD",
        frame="frame-a",
        role="cloud-op",
    ),
    "sandboxdelta": RegistrySpec(
        label="sandboxdelta",
        container=_FED_DELTA_CONTAINER,
        host_port=_FED_DELTA_PORT,
        rpc_path="/mcp/rpc",
        admin_email=_FED_DELTA_EMAIL,
        admin_password=_FED_DELTA_PASSWORD,
        password_env="API_TEST_FED_DELTA_PASSWORD",
        frame="frame-b",
        role="cloud-op",
    ),
    "sandboxdelta-admin": RegistrySpec(
        label="sandboxdelta-admin",
        container=_FED_DELTA_CONTAINER,
        host_port=_FED_DELTA_PORT,
        rpc_path="/mcp/admin/rpc",
        admin_email=_FED_DELTA_EMAIL,
        admin_password=_FED_DELTA_PASSWORD,
        password_env="API_TEST_FED_DELTA_PASSWORD",
        frame="frame-b",
        role="cloud-op",
    ),
}


# ─── Errors + results ──────────────────────────────────────────────────────

class PreconditionUnmet(Exception):
    """The environment cannot supply what this test needs to measure anything.

    Raised by a test whose FIXTURE is absent — not by a test whose subject
    misbehaved. `execute_test` maps it to state="skipped" with the reason
    attached, so the run reports a third state instead of a red row.

    This exists because the alternative is worse in both directions: a test
    that polls a dead fixture until its budget expires reports a product
    defect that is not there (and 7 rows of this baseline were exactly that),
    while a test that silently passes when its fixture is missing measures
    nothing at all. Neither is acceptable; "not measured, here is why" is.

    ⚠ Raise this ONLY for an absent fixture. A fixture that EXISTS but is
    wrong is a real failure and must stay red.
    """


# ── Fixture agent containers ───────────────────────────────────────────────
# The long-running sidecars that onboard themselves and persist creds.json;
# four test modules read an agent DID out of them. The defaults name the
# RETIRED tier's containers (`Exited (137)`), which is why those tests skip on
# a fresh tier — override per tier rather than editing four files. ONE
# definition, because three of the four used to hardcode the literal and a
# fifth spelling is how a rename half-lands.
FED_AGENT_A = os.getenv("API_TEST_FED_AGENT_A", "sandbox-a-fed-test-agent")
FED_AGENT_B = os.getenv("API_TEST_FED_AGENT_B", "sandbox-b-fed-test-agent")


def container_exists_and_runs(name: str) -> tuple:
    """(exists, running) for a container name — distinguishes 'never provisioned'
    from 'provisioned but stopped'. Docker answers `exec` on a STOPPED container
    with APIError 409, which reads like a transport error rather than the plain
    fact that the thing is not running."""
    import subprocess
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return (False, False)
    if r.returncode != 0:
        return (False, False)
    return (True, r.stdout.strip() == "true")


def require_running_container(name: str) -> None:
    """PreconditionUnmet unless `name` is a container that EXISTS and is RUNNING.

    The three tests that read an agent DID out of a fixture container did the
    exec directly, got a non-zero rc, returned "" and reported `missing_did:
    True` — a red row that says nothing about why. On this tier the reason is
    plain: `sandbox-a-fed-test-agent` and its sibling are `Exited (137)` from
    three months ago, left behind by the retired sandbox. Seven neighbouring
    tests in `test_agent_card_lifecycle.py` already skip on exactly that with
    `container_exists_and_runs`; these three failed instead. Same absent
    fixture, two behaviours, and the inconsistent one is the failing one.

    Distinguishes the two states because they call for different action: a
    container that was never created is a provisioning gap, one that exists and
    is stopped is a fixture someone can start.
    """
    exists, running = container_exists_and_runs(name)
    if not exists:
        raise PreconditionUnmet(
            f"fixture container {name!r} does not exist on this tier — the test "
            f"needs an agent DID and there is nowhere to read one from")
    if not running:
        raise PreconditionUnmet(
            f"fixture container {name!r} exists but is NOT RUNNING — docker "
            f"answers exec on a stopped container with a 409 that reads like a "
            f"transport error, not like the plain fact that it is stopped")


# ── Reputation bond (§REPBOND 2026-09-05) ─────────────────────────────────
# A tier running REPUTATION_BOND_MODE=enforce refuses an UNBONDED agent at six
# sites: discovery, listing, pricing, guild_bid, contract_accept, a2a_payee.
# Agent creation does NOT bond — not under any setting — so every fixture this
# suite mints is born refused, and a test that creates an agent and then asserts
# on any of those six is measuring the bond gate instead of its own subject.
#
# The bond is therefore part of MAKING a fixture, not a thing to assert. It
# lives here rather than in each module because six `_new_agent`s exist and a
# seventh spelling is how the rule half-lands.
_BOND_CONFIG: Dict[str, Any] = {}


# ── §EVTYPES7 2026-09-06 — choosing a propagation subject ────────────────────
# The agent-card pull-sync worker runs every 6 h
# (`AGENT_CARD_PULLSYNC_INTERVAL_SEC`, default 21600; unset on both sandbox
# operators, measured). Three tests waited 20 SECONDS for a card to appear on a
# child and called that a pull-sync assertion. They passed only when the subject
# had already propagated in some earlier cycle, and they FAILED the moment a busy
# evening of sweeps filled the head of `discoverAgents` with fresh agents — a
# lottery over a population the rest of the suite changes.
#
# Waiting is the wrong instrument at that cadence. The honest assertion is STEADY
# STATE: an agent old enough to have been through at least one cycle IS mirrored.
# So the subject is chosen BY AGE, from `created_at`, which discoverAgents
# returns — never by the position of a row in an unordered page.
#
# It lives here, not in one of the three test modules, because two modules ask
# the same question and a second copy is a second thing to get wrong.
PULL_CYCLE_SEC = int(os.getenv("AGENT_CARD_PULLSYNC_INTERVAL_SEC", "21600"))


def jwt_seconds_left(jwt: Optional[str]) -> Optional[float]:
    """Seconds until a JWT's `exp`, or None when the token or its claim cannot be read.

    §MCPTEST30 (2026-09-30): the suite runs inside a long-lived gunicorn worker, so a MODULE-level cache of a test
    developer's JWT outlives the run that minted it. The 03:10Z nightly of 2026-09-30 landed on a worker an earlier run
    had used, presented five RBAC tokens and a candidate's token that had expired (ACCESS_TOKEN_EXPIRE_MINUTES is 90),
    and scored every 401 as "foreign cluster returned non-403": seven hard failures that were the instrument's own
    stale credential. A cache of a credential must ask this before it hands the credential out.
    """
    if not jwt or not isinstance(jwt, str) or jwt.count(".") != 2:
        return None
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return float(exp) - time.time() if exp is not None else None
    except Exception:                                        # noqa: BLE001 — unreadable means "do not trust it"
        return None


def jwt_usable(jwt: Optional[str], margin_sec: float = 300.0) -> bool:
    """True only when the token's own `exp` is more than `margin_sec` away. An unreadable token is not usable."""
    left = jwt_seconds_left(jwt)
    return left is not None and left > margin_sec


def agent_age_sec(a: Dict[str, Any]) -> float:
    """Seconds since this agent was created, or -1 when the row does not say."""
    raw = a.get("created_at") or a.get("createdAt") or ""
    if not isinstance(raw, str) or not raw:
        return -1.0
    try:
        dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - dt).total_seconds()
    except Exception:                                        # noqa: BLE001
        return -1.0


def pick_propagated_did(agents, min_age_sec: float = PULL_CYCLE_SEC):
    """(did, age_sec, eligible_count) for the oldest agent past one pull cycle.

    A canary-named agent wins when one is eligible — those are the deliberate
    cross-frame subjects; otherwise the oldest eligible one, which is the least
    likely to be mid-flight for reasons that have nothing to do with pull-sync.
    """
    eligible = [a for a in agents
                if isinstance(a, dict) and (a.get("did") or a.get("agent_did"))
                and agent_age_sec(a) >= min_age_sec]
    if not eligible:
        return "", 0.0, 0
    named = [a for a in eligible
             if "canary" in (a.get("name") or a.get("humanReadableId") or "").lower()]
    pick = max(named or eligible, key=agent_age_sec)
    return (pick.get("did") or pick.get("agent_did")), agent_age_sec(pick), len(eligible)


def agents_of(resp: Any) -> List[Any]:
    """The agent rows of a discoverAgents answer: a bare list, or the first list under a collection key."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("agents", "items", "cards", "agent_cards", "data", "results"):
            v = resp.get(k)
            if isinstance(v, list):
                return v
    return []


async def propagated_subject(rig, label: str, min_age_sec: float = PULL_CYCLE_SEC, page: int = 50,
                             pages: int = 6) -> Tuple[str, float, int, int]:
    """(did, age_sec, eligible_count, rows_seen): pick_propagated_did over discoverAgents read page by page.

    The first page is the NEWEST agents, and a busy day fills it with agents younger than one pull cycle: the V0614
    round (2026-10-14 16:17Z) read 50 of 50 younger than 6 h on sandbox-A after a day of suite runs, and skipped two
    pull-sync tests whose subject sat one page further down. So the read goes on, page by page, until the rows read so
    far hold an eligible subject (the canary preference and the oldest-first rule apply to everything read), at most
    `pages` pages, and stops early at a short page (the end of the list). ('', 0.0, 0, seen) when none qualifies.
    """
    rows: List[Any] = []
    for i in range(pages):
        batch = agents_of(await rig.mcp(label).call("discoverAgents", {"limit": page, "offset": i * page}))
        rows.extend(batch)
        did, age, eligible = pick_propagated_did(rows, min_age_sec)
        if did:
            return did, age, eligible, len(rows)
        if len(batch) < page:
            break
    return "", 0.0, 0, len(rows)


async def bond_config(rig, label: str) -> Dict[str, Any]:
    """This registry's bond posture, cached per label. {} when unreadable.

    Read from the tier rather than assumed, so the same suite is honest on an
    enforcing tier and on one with the gate off.
    """
    admin = label if label.endswith("-admin") else label + "-admin"
    if admin in _BOND_CONFIG:
        return _BOND_CONFIG[admin]
    cfg: Dict[str, Any] = {}
    try:
        r = await rig.mcp(admin).call(
            "adminRequest",
            {"method": "GET", "endpoint": "/api/v1/reputation-bond/config"},
            timeout=30,
        )
        body = r.get("response") if isinstance(r, dict) and "response" in r else r
        if isinstance(body, dict):
            cfg = body
    except Exception:                                        # noqa: BLE001
        cfg = {}
    _BOND_CONFIG[admin] = cfg
    return cfg


# §MCPTEST30 (V0550): the switches a registry reports in its public registry-config (§BAFIN's staking, rewards and AGORA
# distributions; §MEMBERSHIP's governance weight and presence modes). Cached on the RUN's rig, per label, and only when
# read: a later run asks again (a recreate can flip a switch), and an unreadable config is asked again next time instead
# of switching nothing for the rest of the run.
_SWITCH_KEYS = ("staking_enabled", "staking_rewards_enabled", "agora_distributions_enabled", "governance_weight_mode",
                "governance_presence_mode")


async def target_switches(rig, label: str) -> Dict[str, Any]:
    """The switch keys the label's registry reports; {} when unreadable or reported by none (an image before §BAFIN),
    which switches nothing: a test then reads exactly as before."""
    base = label[:-len("-admin")] if label.endswith("-admin") else label
    cache = getattr(rig, "_switch_cache", None)
    if cache is None:
        cache = {}
        try:
            setattr(rig, "_switch_cache", cache)
        except Exception:                                    # noqa: BLE001 — a rig that takes no attribute reads uncached
            pass
    if base in cache:
        return cache[base]
    out: Dict[str, Any] = {}
    try:
        r = await rig.mcp(base).call("getPublicRegistryConfig", timeout=30)
        if isinstance(r, dict):
            out = {k: r[k] for k in _SWITCH_KEYS if k in r}
    except Exception:                                        # noqa: BLE001
        out = {}
    if out:
        cache[base] = out
    return out


def member_mode(switches: Dict[str, Any]) -> bool:
    return switches.get("governance_weight_mode") == "member"


def staking_off(switches: Dict[str, Any]) -> bool:
    return switches.get("staking_enabled") is False


def rewards_off(switches: Dict[str, Any]) -> bool:
    return switches.get("staking_rewards_enabled") is False


async def ensure_bonded(rig, label: str, did: str) -> Optional[str]:
    """Bond a fresh fixture when the tier ENFORCES. No-op otherwise.

    Uses the TREASURY BACKSTOP rail deliberately: a backstopped bond moves no
    money (the treasury keeps its own escrow), so a suite that runs many times a
    day does not drain a wallet agent 250 at a time. The funder rail
    (`{"funder_did": ...}`) DOES move value and is left to tests that mean to.

    Returns the rail's reported status, "skipped:<why>" when nothing was needed
    or possible, or None when the tier could not be read at all — three states,
    because "did not bond" and "could not tell" must not collapse.

    ⚠ PreconditionUnmet only when the tier enforces AND offers no way to bond:
    then the fixture genuinely cannot be made usable, and every downstream
    assertion would be about the gate.
    """
    cfg = await bond_config(rig, label)
    if not cfg:
        return None
    if (cfg.get("mode") or "off") != "enforce":
        return "skipped:mode=%s" % (cfg.get("mode") or "off")
    if not cfg.get("treasury_backstop"):
        return await _bond_from_own_funds(rig, label, did, cfg)
    admin = label if label.endswith("-admin") else label + "-admin"
    try:
        r = await rig.mcp(admin).call(
            "adminRequest",
            {"method": "POST",
             "endpoint": f"/api/v1/developers/me/agents/{did}/reputation-bond/backstop"},
            timeout=60,
        )
    except Exception as e:                                   # noqa: BLE001
        raise PreconditionUnmet(f"bond backstop failed for {did} on {label}: {e}")
    body = r.get("response") if isinstance(r, dict) and "response" in r else r
    status_str = body.get("status") if isinstance(body, dict) else None
    if status_str not in ("locked", "matured"):
        raise PreconditionUnmet(
            f"bond backstop for {did} on {label} left status={status_str!r} "
            f"(bonded statuses are locked/matured): {str(body)[:200]}")
    return status_str


async def _bond_from_own_funds(rig, label: str, did: str, cfg: Dict[str, Any]) -> str:
    """A tier that enforces the bond WITHOUT the treasury backstop (production's posture from V0649 on; the sandbox's
    once sbx-beta follows it): the fixture is funded with its bond from the treasury (the canonical fund-agent rail,
    reason admin_grant) and bonds itself from that balance (the developer's own deposit rail, funder_did = the agent).
    V0650 (tester batch 1 item 4, agentvault2-d3, Guild order gwo_2015b757c94ce69138500df6): before it, this suite raised
    PreconditionUnmet on such a tier, so it could not measure a frame posed as production is. Moves units: treasury to
    the agent (TokensTransferred), the agent to the treasury's escrow (the bond); both legs conserve supply. The funding
    carries a 1 % margin, so a fee on the deposit could not strand the fixture short of its bond."""
    try:
        bond = Decimal(str(cfg.get("amount")))
    except (InvalidOperation, ValueError, TypeError):
        bond = Decimal(0)
    if bond <= 0:
        raise PreconditionUnmet(f"{label} enforces the reputation bond without the treasury backstop and its bond "
                                f"config names no amount ({cfg.get('amount')!r}), so no fixture can be funded for it")
    admin = label if label.endswith("-admin") else label + "-admin"
    fund = (bond + bond / 100).quantize(Decimal("0.000001"))
    try:
        r = await rig.mcp(admin).call("adminRequest", {
            "method": "POST", "endpoint": "/api/v1/teg/treasury/fund-agent",
            "body": {"target_agent_did": did, "amount": str(fund), "reason": "admin_grant",
                     "reference_id": f"fedsuite-bond-{did.rsplit(':', 1)[-1][:40]}"}}, timeout=60)
    except Exception as e:                                   # noqa: BLE001
        raise PreconditionUnmet(f"funding {did}'s bond on {label} failed: {e}")
    body = r.get("response") if isinstance(r, dict) and "response" in r else r
    if isinstance(r, dict) and (r.get("ok") is False or int(r.get("status_code") or 200) >= 400):
        raise PreconditionUnmet(f"funding {did}'s bond on {label} was refused: {str(body)[:200]}")
    try:
        r = await rig.mcp(admin).call("adminRequest", {
            "method": "POST", "endpoint": f"/api/v1/developers/me/agents/{did}/reputation-bond",
            "body": {"funder_did": did}}, timeout=60)
    except Exception as e:                                   # noqa: BLE001
        raise PreconditionUnmet(f"the bond deposit for {did} on {label} failed: {e}")
    body = r.get("response") if isinstance(r, dict) and "response" in r else r
    status_str = body.get("status") if isinstance(body, dict) else None
    if status_str not in ("locked", "matured"):
        raise PreconditionUnmet(
            f"the bond deposit for {did} on {label} left status={status_str!r} "
            f"(bonded statuses are locked/matured): {str(body)[:200]}")
    return status_str


async def require_readable_eventstore(rig, label: str) -> None:
    """PreconditionUnmet when `label`'s registry cannot READ its own EventStore.

    Broadcast federation is ES-driven: `reactor_admin_broadcast_received`
    subscribes to the local EventStore and materializes any broadcast whose
    `source_frame` is foreign. A registry that cannot reach an EventStore can
    therefore never receive one, and asserting that it did measures the wiring,
    not the product.

    ⚠ MEASURED ON THIS TIER, and it is a provisioning defect worth its own line:
    both sandbox cloud operators carry `EVENT_STORE_URL=https://hetzner-es.
    theprotocol.cloud` — the RETIRED Hetzner frame's EventStore — inherited from
    the operator template. Their reactors reconnect to it in a permanent loop
    (~8,600 attempts in six hours, `WS error: 400`), so every event-driven
    reactor on those operators is silently dead. The operators sit on their own
    isolated docker network and cannot reach their parent frame's ES at all, so
    this is a topology fix (shared net or a TLS vhost), not an env edit.

    The discriminator is cheap and direct: an ES read through the registry's own
    admin proxy answers 200 on a wired registry and 400 on these operators.
    A registry whose ES IS readable and still does not receive a broadcast is a
    real failure and stays RED.
    """
    try:
        r = await rig.mcp(label).call(
            "adminQueryEventStore", {"path": "/api/v1/projections/stats"}, timeout=30)
    except Exception as e:
        raise PreconditionUnmet(
            f"{label}: EventStore unreadable ({type(e).__name__}: {e})")
    code = r.get("status_code") if isinstance(r, dict) else None
    if code != 200:
        raise PreconditionUnmet(
            f"{label} cannot read its own EventStore (admin ES proxy answered "
            f"{code}) — ES-driven broadcast federation cannot reach a registry "
            f"with no readable EventStore, so there is nothing to measure here")


async def require_crossframe_es_replication(rig, label: str) -> None:
    """PreconditionUnmet when `label`'s EventStore has NEVER synced from a peer.

    Cross-frame broadcast federation rides EventStore replication: the receiving
    frame's ES pulls a peer's events, and `reactor_admin_broadcast_received`
    materializes any whose `source_frame` is foreign. If the ES has never pulled
    anything, the reactor is healthy and idle and the broadcast never had a road
    to travel.

    ⚠ MEASURED ON THIS TIER, and my FIRST reading of it was wrong. The peer row
    names `sandbox-events-{a,b}.theprotocol.cloud`, which SOUNDS like the retired
    sandbox and is not: those vhosts proxy 127.0.0.1:8261/8361, which are the
    CURRENT frames' EventStores. I filed "points at the retired tier" from the
    hostname's provenance without checking where it proxies — the same read-the-
    name-not-the-wiring error this file exists to catch.

    The URL is right and the row still reads `status: active` with
    `last_timestamp` null and `last_seq` 0. Two real blockers, both measured:
      1. the replicator verifies the peer's TLS against `/certs/bundle.0.pem`
         (SPIRE roots ONLY) while the vhost serves Let's Encrypt →
         CERTIFICATE_VERIFY_FAILED. The registry side already fixed this class
         with a dual-trust context (`es_ssl_helper`); the ES replicator still
         has the old either/or.
      2. even with correct TLS, `/api/v1/events/export` answers 403 to a peer
         frame — cross-frame authorization is not established.
    Both are ES-side work for the standup program, not test bugs.
    Status is a claim; last_timestamp is the measurement.

    ⚠ THE DISCRIMINATOR IS *NEVER SYNCED*, NOT *NO EVENTS*. A peer that has
    synced before and stopped is a real failure and must stay RED — that is the
    difference between "this was never wired" and "this broke".
    """
    try:
        r = await rig.mcp(label).call("getEventStoreCrossFramePeers", {}, timeout=30)
    except Exception as e:
        raise PreconditionUnmet(
            f"{label}: cross-frame peer list unreadable ({type(e).__name__}: {e})")
    body = r.get("response") if isinstance(r, dict) and "response" in r else r
    peers = (body or {}).get("peers") if isinstance(body, dict) else None
    if not isinstance(peers, list):
        raise PreconditionUnmet(
            f"{label}: cross-frame peer list has no usable shape — could not check")
    if not peers:
        raise PreconditionUnmet(
            f"{label} has NO cross-frame ES peer configured — nothing can replicate to it")
    if all(not p.get("last_timestamp") for p in peers if isinstance(p, dict)):
        urls = ", ".join(str(p.get("url")) for p in peers if isinstance(p, dict))
        raise PreconditionUnmet(
            f"{label}'s EventStore has NEVER synced from any cross-frame peer "
            f"(last_timestamp null on all {len(peers)}; configured: {urls}) — "
            f"the URL is correct; the replicator cannot USE it (SPIRE-only TLS "
            f"verify against a Let's Encrypt vhost, and export answers 403 to a "
            f"peer frame). A broadcast has no road to travel, so a red here "
            f"would be about ES-side federation work, not this test")


async def require_canary_subsystem(rig, label: str = "sandbox-A-admin") -> dict:
    """The canary status body — or PreconditionUnmet when this tier HAS no canaries.

    A tier reporting `total_paths: 0` is not a broken canary fleet; it is a tier
    where canaries were never provisioned. On the sandbox that is deliberate:
    canary paths dispatch REAL currency, and the standup plan keeps them off.
    Ten rows of this suite nonetheless asserted "a canary path is active and
    passed recently" and went red for it on every run — a third of the failing
    column, all one environmental cause, and exactly the shape that teaches a
    reader to skim past red.

    ⚠ THE DISCRIMINATOR IS ZERO PATHS, NOT A FAILING PATH. If the subsystem is
    configured and the specific path is missing, inactive or failing, that is a
    real finding and stays RED — per `PreconditionUnmet`'s own rule that an
    absent fixture skips while a wrong one fails. This helper only ever fires on
    the "never provisioned" reading, and returns the body it already fetched so
    a caller needs one round trip, not two.
    """
    try:
        r = await rig.mcp(label).call(
            "adminRequest",
            {"method": "GET", "endpoint": "/api/v1/admin/canary/status"},
            timeout=40,
        )
    except Exception as e:
        raise PreconditionUnmet(f"canary status unreadable ({type(e).__name__}: {e})")
    body = r.get("response") if isinstance(r, dict) and "response" in r else r
    if not isinstance(body, dict):
        # Unreadable is its own state: do not let a wrapper shape read as "no canaries".
        raise PreconditionUnmet(
            f"canary status returned no usable body (got {type(body).__name__})")
    summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
    total = summary.get("total_paths")
    if total == 0:
        raise PreconditionUnmet(
            "this tier has NO canary paths configured (total_paths=0) — canaries "
            "dispatch real currency and are deliberately unprovisioned on the "
            "sandbox; nothing to measure, and a red here would be about the tier")
    return body


def canary_path_leaves_registry(path: dict) -> bool:
    """True when a canary path's far end is another registry, read off the path's OWN row.

    `frame_pair` is "<sender frame>-><receiver frame>" in the status payload and a local path repeats the same name; a
    row without it falls back to the backend, where anything but `intra` crosses a registry boundary. §CANARYONBOARD
    (2026-09-23): the multi-hop test used to name two path ids from the legacy topology and went red on a tier that
    carries neither. Derived, so a tier that renames its paths or changes their number stays measurable.
    """
    pair = str(path.get("frame_pair") or "")
    if "->" in pair:
        left, _, right = pair.partition("->")
        return left.strip() != right.strip()
    return str(path.get("backend") or "intra").strip().lower() != "intra"


def canary_paths_fired_but_inactive(body: dict) -> list:
    """The path ids that FIRED inside the status window and are no longer active — the honest "someone switched a live
    canary off" signal.

    §CANARYONBOARD (2026-09-23): `active_paths >= 10` (and `>= 11`) pinned the legacy tier's count, and `active ==
    total` is not the invariant either, because a RETIRED row is legitimate: EU keeps two from its standup, inactive on
    purpose. A path that fired in the window and is now off is a different thing from one that has been quiet for a
    day, and the window is what tells them apart.
    """
    return [p.get("path_id") for p in (body.get("paths") or [])
            if isinstance(p, dict)
            and ((p.get("stats_24h") or {}).get("total", 0) or 0) >= 1
            and not p.get("is_active")]


def read_only_tool(tool: str) -> bool:
    """True when the server's own annotation for `tool` says it only reads (mcp/tool_metadata.derive_annotations, the
    hint tools/list publishes); False when it cannot be read, so a write is never taken for a read."""
    try:
        from agentvault_registry.mcp.tool_metadata import derive_annotations
        return bool(derive_annotations(tool).get("readOnlyHint"))
    except Exception:  # noqa: BLE001
        return False


class MCPError(Exception):
    """Raised when an MCP call fails (HTTP non-2xx, RPC error, parse failure)."""
    def __init__(self, registry: str, tool: str, http_status: str, detail: str):
        self.registry = registry
        self.tool = tool
        self.http_status = http_status
        self.detail = detail
        super().__init__(f"MCP {registry}/{tool} → HTTP {http_status}: {detail[:200]}")


# ─── §B6 shape normalisation (V0221) ───────────────────────────────────────
# WHAT CHANGED. From V0221 the admin proxy tools (adminRequest,
# adminQueryEventStore, adminGrafanaQuery) answer an upstream NON-2XX as a
# plain-text line — "Error: upstream HTTP 404: Agent not-a-uuid not found" —
# instead of the `{status_code, response, ok}` envelope they still return for a
# 2xx. Richer for a human; invisible to a caller that reads `status_code`.
#
# WHAT IT COST. Every test in this suite that asserts on a REFUSAL — 401, 403,
# 404, 405, 422, the bond gates, the RBAC matrices, the IronKey clamps — got
# `status_code=None`, scored -1, and polled until its budget died. 38 of the
# suite's 40 reds on the V0221 image were this one shape change, and they read
# as "the product broke" rather than "the harness cannot see the answer".
#
# WHY IT IS FIXED HERE AND NOT IN THE TESTS. Thirteen files carry their own
# `_rest`, and the tests that broke hardest do not use it at all — they call
# adminRequest directly with a private extractor each. Normalising at the ONE
# chokepoint restores the documented envelope for every caller at once, which is
# the same reason the probe meter lives in exec_in_container.
#
# The guard is the SENTENCE, not the tool name: only a `_text`-only dict whose
# text matches this exact upstream-error form is rewritten, so a tool that
# legitimately returns prose is untouched. The original line is preserved in
# `_error_text` — it carries detail the old envelope never had.
# ⚠ the space after the colon is OPTIONAL: the text is stripped before
# matching, so an error with an EMPTY detail ("...HTTP 401: ") arrives
# without it and would otherwise fall through unrecognised as a 401.
_UPSTREAM_ERROR = re.compile(r"\AError: upstream HTTP (\d{3}):\s?(.*)\Z", re.S)

# ⚠ THIS SHIM MUST NEVER BE SILENT. It rewrites a response shape that a
# DISPATCHER BUG produced (`server_admin.py::_format_result` short-circuits any
# dict carrying an `error` key and discards status_code/response/ok, so B6's
# added `error` flattened the whole envelope). Adapting to that quietly would
# hide someone else's regression behind a green suite — the exact failure this
# session was built to catch. So every rewrite is counted and the total is
# published in the run summary: when the envelope is restored upstream the
# count falls to zero on its own, and until then the number is on screen.
_UPSTREAM_ERROR_REWRITES = [0]


def upstream_error_rewrites() -> int:
    """How many responses this run arrived flattened and had to be rebuilt."""
    return _UPSTREAM_ERROR_REWRITES[0]


def reset_upstream_error_rewrites() -> None:
    _UPSTREAM_ERROR_REWRITES[0] = 0


def normalize_upstream_error(result: Any) -> Any:
    """Rewrite a V0221 plain-text upstream error back into the {status_code,
    response, ok} envelope the suite was written against. Idempotent; anything
    that does not match is returned unchanged."""
    if not (isinstance(result, dict) and set(result) == {"_text"}):
        return result
    text = result.get("_text")
    if not isinstance(text, str):
        return result
    m = _UPSTREAM_ERROR.match(text.strip())
    if not m:
        return result
    _UPSTREAM_ERROR_REWRITES[0] += 1
    return {
        "status_code": int(m.group(1)),
        "response": m.group(2),
        "ok": False,
        "_error_text": text,
    }


@dataclass
class AssertionResult:
    """Outcome of an assert_within poll loop."""
    passed: bool
    description: str
    budget_sec: float
    elapsed_sec: float
    polling_attempts: int
    last_state: Any = None
    failure_detail: Optional[str] = None

    @property
    def budget_remaining_sec(self) -> float:
        return max(0.0, self.budget_sec - self.elapsed_sec)

    @property
    def budget_pct_used(self) -> float:
        return min(100.0, (self.elapsed_sec / self.budget_sec * 100.0)) if self.budget_sec else 0.0


@dataclass
class DeferredCheck:
    """What a `start_first` test returns once it has ACTED (§SENDEARLY, 2026-09-26).

    His words: "fix the test so the transfer goes out at the beginning of the test run and success is measured later
    in the test run". The runner starts such a test before every other one, keeps this object while the rest of the
    suite runs, and awaits `check()` once they are all done: the row's verdict is that AssertionResult. The act and the
    verdict stay ONE row, so the nightly history and its expected-red list read the same. `started_at` is set by the
    runner, so the row's timing spans the act, the wait and the verdict.
    """
    check: Callable[[], Awaitable[AssertionResult]]
    started_at: float = 0.0


# ─── MCP client (per registry) ─────────────────────────────────────────────

class MCPClient:
    """Thin MCP JSON-RPC client for one registry endpoint.

    Uses docker exec to curl localhost:8000 inside the target container —
    same pattern as flow_mcp_lifecycle._mcp_rpc_call. Caches dev JWT once
    minted; refreshes on 401.
    """

    def __init__(self, spec: RegistrySpec):
        self.spec = spec
        self._jwt: Optional[str] = None
        self._jwt_minted_at: float = 0.0

    async def _ensure_jwt(self) -> str:
        """Mint a fresh dev JWT (cache for ~85 min then refresh).

        §pass73.3.5 — bumped 540s → 5100s to align with the cluster-wide
        ACCESS_TOKEN_EXPIRE_MINUTES bump (30→90 min). The cache TTL stays
        ~5 min below the server token lifetime so the rig refreshes before
        the server-issued token actually expires.
        """
        if self._jwt and (time.time() - self._jwt_minted_at) < 5100:
            return self._jwt
        password = _require_secret(
            self.spec.admin_password,
            self.spec.password_env or "the tier's admin-password env var",
            self.spec.label,
        )
        rc, out = await asyncio.to_thread(
            exec_in_container, self.spec.container, [
                "sh", "-c",
                f"curl -sS -X POST "
                f"-H 'Content-Type: application/x-www-form-urlencoded' "
                f"--data-urlencode 'username={self.spec.admin_email}' "
                f"--data-urlencode 'password={password}' "
                f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
                "http://localhost:8000/api/v1/auth/login",
            ], 15,
        )
        body, code = _split_http_body_code(out)
        if rc != 0 or not code.startswith("2"):
            raise MCPError(self.spec.label, "_login", code, body[:200])
        try:
            self._jwt = json.loads(body)["access_token"]
            self._jwt_minted_at = time.time()
        except Exception as e:
            raise MCPError(self.spec.label, "_login", code, f"parse error: {e}")
        return self._jwt

    async def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None,
                    *, timeout: int = 30, expect_error: bool = False,
                    _retry_attempted: bool = False, _transport_retried: bool = False) -> Dict[str, Any]:
        """Call MCP tool, return parsed inner result dict.

        Raises MCPError on HTTP non-2xx or RPC `error` envelope (unless
        expect_error=True, in which case the error envelope is returned).

        On 401, the cached JWT is invalidated and the call is retried ONCE
        (with `_retry_attempted=True` to prevent unbounded recursion when the
        tool genuinely requires higher-tier auth than the bridge can satisfy
        — e.g. tier-2 tools called via public bridge without an agent_jwt).
        """
        if not tool.startswith("theprotocol_"):
            tool = f"theprotocol_{tool}"
        jwt = await self._ensure_jwt()
        rpc_body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
            "id": int(time.time() * 1000) % 1_000_000,
        }
        body_b64 = base64.b64encode(json.dumps(rpc_body).encode()).decode()
        rc, out = await asyncio.to_thread(
            exec_in_container, self.spec.container, [
                "sh", "-c",
                f"echo '{body_b64}' | base64 -d | "
                f"curl -sS -X POST -H 'Authorization: Bearer {jwt}' "
                f"-H 'Content-Type: application/json' "
                f"--data-binary @- "
                f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
                f"http://localhost:8000{self.spec.rpc_path}",
            ], timeout,
        )
        body, code = _split_http_body_code(out)
        if rc != 0:
            raise MCPError(self.spec.label, tool, code, f"exec rc={rc} body={body[:200]}")
        if not code and not _transport_retried and read_only_tool(tool):
            # §MCPTEST30 (2026-10-01): a READ whose answer the transport lost is asked once more. The suite marks a test
            # that lost an answer NOT MEASURED (below), and rounds 5 and 6 from EU's console each lost one; a read asked
            # twice cannot change what it measures. A write is never repeated: its lost answer stays NOT MEASURED.
            logger.info("[FedRig] %s: an answer was lost in transit on a read; asking once more", tool)
            return await self.call(tool, arguments, timeout=timeout, expect_error=expect_error,
                                   _retry_attempted=_retry_attempted, _transport_retried=True)
        if not code:
            # §MCPSWEEP 2026-09-28: rc 0 and no status marker means the exec captured no answer at all. It used to
            # surface as "HTTP : " with an empty detail, which reads like a product failure; the server may have
            # answered (its audit row can show it). Named here so a reader can tell the transport from the tool.
            # Counted per test: the decorator turns a test that lost an answer into NOT MEASURED (§MCPSWEEP).
            record_transport_lost()
            raise MCPError(self.spec.label, tool, "none",
                           f"no HTTP status captured: the exec returned rc 0 with {len(out or '')} chars and no "
                           "status marker, so no answer was read (the server may still have answered)")
        if code == "401":
            if _retry_attempted:
                # Already retried once — surface the 401 cleanly. This prevents
                # the infinite retry storm when a tool genuinely requires higher
                # auth tier (tier-2 from public bridge without agent_jwt, etc.).
                raise MCPError(
                    self.spec.label, tool, code,
                    f"401 after fresh-JWT retry — tool likely requires higher auth tier",
                )
            # Refresh JWT once + retry
            self._jwt = None
            return await self.call(
                tool, arguments, timeout=timeout, expect_error=expect_error, _transport_retried=_transport_retried,
                _retry_attempted=True,
            )
        if not code.startswith("2"):
            raise MCPError(self.spec.label, tool, code, body[:200])
        try:
            parsed = json.loads(body) if body else {}
        except Exception as e:
            raise MCPError(self.spec.label, tool, code, f"parse error: {e}")
        if isinstance(parsed, dict) and "error" in parsed:
            if expect_error:
                return parsed
            raise MCPError(self.spec.label, tool, code, json.dumps(parsed["error"])[:200])
        # Unwrap the standard MCP JSON-RPC content envelope
        result = parsed.get("result") if isinstance(parsed, dict) else {}
        content = (result or {}).get("content") or []
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text") or ""
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except Exception:
                    return normalize_upstream_error({"_text": text})
        return result if isinstance(result, dict) else {}


# ─── Rig ───────────────────────────────────────────────────────────────────

class FederationTestRig:
    """Multi-registry MCP orchestrator.

    Holds a cached MCPClient per registry label. Tests call:
        result = await rig.mcp("sandbox-A-admin").call("composeBroadcast", {...})

    The `assert_within` method runs an eventual-consistency poll with a budget.
    """

    def __init__(self):
        self._clients: Dict[str, MCPClient] = {}

    def mcp(self, label: str) -> MCPClient:
        """Lazily instantiate + cache an MCP client for the given registry label."""
        if label not in SANDBOX_REGISTRIES:
            raise KeyError(
                f"Unknown registry label {label!r}. "
                f"Known: {list(SANDBOX_REGISTRIES)}"
            )
        if label not in self._clients:
            self._clients[label] = MCPClient(SANDBOX_REGISTRIES[label])
        return self._clients[label]

    async def assert_within(
        self,
        *,
        budget_sec: float,
        predicate: Callable[[], Awaitable[bool]],
        description: str,
        poll_interval_sec: float = 1.0,
        capture_state: Optional[Callable[[], Awaitable[Any]]] = None,
    ) -> AssertionResult:
        """Poll predicate every poll_interval until True or budget exhausted.

        Args:
          budget_sec: max wall-time to wait for predicate to become True
          predicate: async callable returning bool
          description: human-readable description for the report
          poll_interval_sec: sleep between attempts
          capture_state: optional async callable returning a state dump for
            failure detail (e.g., snapshot the receiver's DB row)

        Returns AssertionResult — never raises (so tests can wrap multiple).
        """
        async def _resolve_state():
            """Accept both sync `lambda: dict` and `async def` capture_state."""
            if not capture_state:
                return None
            r = capture_state()
            if asyncio.iscoroutine(r):
                return await r
            return r

        t0 = time.time()
        attempts = 0
        last_exception: Optional[BaseException] = None
        while True:
            attempts += 1
            # §NIGHTLYTRUTH (2026-09-14): what the LAST attempt did decides the verdict. A predicate that
            # raises PreconditionUnmet is kept polling (a fixture can still arrive inside the budget), but
            # if the budget ends on an unmet precondition the row is NOT MEASURED, not FAILED: the decorator's
            # third state exists for exactly this, and this loop used to swallow the exception into
            # "budget exhausted; last_exception=PreconditionUnmet(...)" — a red row about the environment.
            # Measured on the nightly: `fx_route_refund_claim_matches_the_money` was red every night because
            # the evidence was out of the page's window, which nothing here can judge either way.
            attempt_raised: Optional[BaseException] = None
            try:
                if await predicate():
                    elapsed = time.time() - t0
                    state = await _resolve_state()
                    return AssertionResult(
                        passed=True,
                        description=description,
                        budget_sec=budget_sec,
                        elapsed_sec=elapsed,
                        polling_attempts=attempts,
                        last_state=state,
                    )
            except Exception as e:
                last_exception = e
                attempt_raised = e
                logger.debug(
                    f"[assert_within] predicate raised attempt {attempts}: {e!r}"
                )
            elapsed = time.time() - t0
            if elapsed >= budget_sec:
                if isinstance(attempt_raised, PreconditionUnmet):
                    raise attempt_raised
                state = None
                if capture_state:
                    try:
                        state = await _resolve_state()
                    except Exception as e:
                        state = {"_capture_error": str(e)}
                # V0614: the detail names what the LAST attempt did. A False after an earlier exception used to read
                # "last_exception=<that earlier exception>": the V0613 round's red row said "PreconditionUnmet(... Not
                # a defect — re-run.)" while its last attempt had failed on something else, which only its captured
                # state named. The state's own `why`, when the test wrote one, is that reason.
                detail = f"budget {budget_sec}s exhausted after {attempts} attempts"
                if attempt_raised is not None:
                    detail += f"; last_exception={attempt_raised!r}"
                else:
                    detail += "; the last attempt returned False"
                    if last_exception is not None:
                        detail += f" (an earlier attempt raised {last_exception!r})"
                    why = state.get("why") if isinstance(state, dict) else None
                    if why:
                        detail += f"; why: {why}"
                return AssertionResult(
                    passed=False,
                    description=description,
                    budget_sec=budget_sec,
                    elapsed_sec=elapsed,
                    polling_attempts=attempts,
                    last_state=state,
                    failure_detail=detail,
                )
            await asyncio.sleep(poll_interval_sec)
