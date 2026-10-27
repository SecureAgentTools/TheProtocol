#!/usr/bin/env python3
"""
EigenTrust Trade Simulation Script — TheProtocol (v2)
=====================================================
Full-spectrum agent economy simulation across dual federated registries.

Simulated activities per cycle:
  - Token transfers (intra + cross-registry, balance-aware)
  - Reputation signals (+1/-1 after transfers)
  - Staking (lock_period 0-365 days, builds governance power)
  - Governance (proposals → votes → tally)
  - Contract lifecycle (create → accept → submit → approve, cross-registry)
  - Disputes (enhanced DDR filing)
  - ZKP attestations (optional, requires nargo + bb): v2.0.0 fair markup and
    accurate resource usage proofs, made in a temporary directory

Daemon mode:
  python3 scripts/eigentrust_simulation.py --daemon --cycle-interval 120
  Runs indefinitely with pauses between cycles. Each cycle picks a random
  subset of pairs and activities. Supply invariant is checked after each cycle.

One-shot mode (default):
  python3 scripts/eigentrust_simulation.py --skip-zkp --pairs 10 --seed 99

Architecture:
  - 10 agents from scripts/eigentrust_agents.json (5 on A, 5 on B)
  - Registry A: https://api.theprotocol.cloud
  - Registry B: http://localhost:8001
"""

import argparse
import base64
import hashlib
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_REGISTRY_A    = "https://api.theprotocol.cloud"
DEFAULT_REGISTRY_B    = "http://localhost:8001"
DEV_EMAIL             = "commander@theprotocol.cloud"
DEV_PASSWORD          = os.environ.get("TP_ADMIN_PASSWORD", "")

DEFAULT_PAIRS         = 0        # 0 = all permutations
MIN_ROUNDS_PER_PAIR   = 3
MAX_ROUNDS_PER_PAIR   = 7
MIN_AMOUNT            = 60       # must be divisible by 6 (for ZKP fair markup)
MAX_AMOUNT            = 240      # must be divisible by 6
AMOUNT_STEP           = 6        # all amounts are multiples of this

# Contract simulation parameters
CONTRACT_PAYMENT_MIN  = 100
CONTRACT_PAYMENT_MAX  = 500

# Staking parameters
STAKE_MIN             = 200
STAKE_MAX             = 1000
LOCK_PERIODS          = [0, 30, 90, 180, 365]

# Governance parameters
PROPOSAL_DURATION_MIN = 3600     # 1 hour
PROPOSAL_DURATION_MAX = 7200     # 2 hours (short for simulation)

# Activity probabilities per pair (one-shot mode)
PROB_CONTRACT         = 0.30
PROB_DISPUTE          = 0.30     # raised from 0.10 → generate negative signal data
PROB_REPUTATION       = 0.80     # raised from 0.70 → more reputation data
PROB_STAKING          = 0.15     # chance of staking after a pair completes
PROB_GOVERNANCE       = 0.08     # chance of creating a governance proposal
PROB_NEGATIVE_SIGNAL  = 0.25     # 25% of reputation signals are negative (was 15%)

# Daemon mode defaults
DEFAULT_CYCLE_INTERVAL = 120     # seconds between cycles
DAEMON_PAIRS_PER_CYCLE = 5       # pairs per daemon cycle

# Auto-refund: treasury tops up depleted agents so the simulation never stalls
REFUND_THRESHOLD      = 2000     # refund when liquid balance drops below this (was 500 — too low)
REFUND_AMOUNT         = 10000    # AVT to grant from treasury per refund (was 5000 — insufficient)
TREASURY_MIN_BALANCE  = 50000    # auto-mint when treasury falls below this
TREASURY_MINT_AMOUNT  = 200000   # mint this much to replenish treasury

# ZKP circuit parameters (v2.0.0: public limits, checked against the registry policy)
MAX_MARKUP_BPS        = 3000     # markup cap; the shipped policy allows at most 3000
MAX_DISCREPANCY_BPS   = 100      # usage tolerance; the shipped policy allows at most 100

BB_BINARY    = os.environ.get("BB_BINARY",    "/usr/local/bin/bb")
NARGO_BINARY = os.environ.get("NARGO_BINARY", "/usr/local/bin/nargo")

CREDENTIALS_FILE = Path(os.environ.get(
    "EIGENTRUST_CREDENTIALS",
    Path(__file__).parent / "eigentrust_agents.json"
))

CIRCUIT_REGISTRY = Path(os.environ.get("CIRCUIT_REGISTRY_PATH", "/app/agentvault_circuit_registry")) / "policies"
CIRCUITS: Dict[str, Dict] = {
    "fairMarkupPolicy/v2.0.0": {
        "dir":  CIRCUIT_REGISTRY / "fairMarkupPolicy"            / "v2.0.0",
        "name": "fair_markup",
    },
    "accurateResourceUsagePolicy/v2.0.0": {
        "dir":  CIRCUIT_REGISTRY / "accurateResourceUsagePolicy" / "v2.0.0",
        "name": "accurate_resource_usage",
    },
}

# Dispute reason codes (must match EnhancedDisputeCreate enum)
DISPUTE_REASONS = [
    "UNFAIR_FEE",
    "SERVICE_NOT_DELIVERED",
    "POOR_QUALITY",
    "MISREPRESENTATION",
    "CONTRACT_VIOLATION",
    "UNAUTHORIZED_USE",
]

# Supply invariant check config
ES_URL = "http://172.16.0.24:8200"
ES_KEY = os.environ.get("EVENT_STORE_INTERNAL_API_KEY", "")  # §RELEASE-P3 (2026-09-05): env ONLY. This line carried
# Frame A's live EventStore internal key as a literal, in a tracked file, for months (live on 12 containers when found).
if not ES_KEY:
    print("  [warn] EVENT_STORE_INTERNAL_API_KEY not set — direct EventStore reads will be refused (401)")
SUPPLY_TOLERANCE = 10.0  # AVT — matches auditor tolerance for fee rounding


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (stdlib — no external deps)
# ─────────────────────────────────────────────────────────────────────────────

def http_post_json(url: str, data: Dict, headers: Dict = {}) -> Dict:
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json", **headers
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_form(url: str, form_data: str) -> Dict:
    payload = form_data.encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get(url: str, headers: Dict = {}) -> Dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_try(method: str, url: str, data: Dict = None, headers: Dict = {},
             quiet: bool = False) -> Optional[Dict]:
    """HTTP request that returns None on error instead of raising."""
    try:
        if method == "POST":
            return http_post_json(url, data or {}, headers)
        else:
            return http_get(url, headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        if not quiet:
            print(f"    HTTP {e.code}: {body}")
        return None
    except Exception as e:
        if not quiet:
            print(f"    Error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Registry URL resolution
# ─────────────────────────────────────────────────────────────────────────────

def registry_url_for(agent: Dict, registry_a: str, registry_b: str) -> str:
    return registry_a if agent["registry"] == "A" else registry_b


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

def get_agent_jwt(registry_url: str, agent: Dict) -> str:
    data = (
        f"grant_type=password"
        f"&username={urllib.parse.quote(agent['client_id'])}"
        f"&password={urllib.parse.quote(agent['client_secret'])}"
    )
    resp = http_post_form(f"{registry_url}/api/v1/auth/agent/token", data)
    return resp["access_token"]


def get_dev_jwt(registry_url: str) -> Optional[str]:
    try:
        resp = http_post_form(
            f"{registry_url}/api/v1/auth/login",
            f"username={urllib.parse.quote(DEV_EMAIL)}&password={urllib.parse.quote(DEV_PASSWORD)}"
        )
        return resp.get("access_token")
    except Exception:
        return None


def get_agent_info(registry_url: str, did: str, dev_jwt: str) -> Optional[Dict]:
    try:
        return http_get(
            f"{registry_url}/api/v1/agents/by-did/{did}",
            headers={"Authorization": f"Bearer {dev_jwt}"}
        )
    except Exception:
        return None


def get_agent_balance(registry_url: str, agent_jwt: str) -> Optional[int]:
    """Get agent's liquid balance via TEG balance endpoint."""
    resp = http_try("GET", f"{registry_url}/api/v1/teg/balance",
                    headers={"Authorization": f"Bearer {agent_jwt}"}, quiet=True)
    if resp:
        try:
            return int(float(resp.get("balance", 0)))
        except (ValueError, TypeError):
            return None
    return None


def refund_agent_from_treasury(registry_url: str, dev_jwt: str,
                               agent_did: str, amount: int) -> bool:
    """Top up an agent from the treasury. Requires admin dev JWT.
    Note: TEG may return 400 yet still process the transfer (known issue),
    so we verify the balance afterwards."""
    resp = http_try(
        "POST", f"{registry_url}/api/v1/teg/treasury/fund-agent",
        data={
            "target_agent_did": agent_did,
            "amount": str(amount),
            "reason": f"EigenTrust auto-refund: balance below {REFUND_THRESHOLD} AVT",
        },
        headers={"Authorization": f"Bearer {dev_jwt}"},
        quiet=True,
    )
    # Even if resp is None (400), the TEG may have processed it — caller should verify balance
    return True


def check_and_refund_depleted_agents(
    agents: List[Dict], jwts: Dict[str, str], balance_cache: Dict[str, int],
    registry_a: str, registry_b: str,
    dev_jwt_a: str, dev_jwt_b: str,
) -> int:
    """Check all agents and refund any whose liquid balance < REFUND_THRESHOLD.
    Returns the number of agents refunded."""
    refunded = 0
    for agent in agents:
        url = registry_url_for(agent, registry_a, registry_b)
        jwt = jwts.get(agent["did"])
        if not jwt:
            continue
        bal = get_agent_balance(url, jwt)
        if bal is None:
            continue
        balance_cache[agent["did"]] = bal
        if bal < REFUND_THRESHOLD:
            dev_jwt = dev_jwt_a if agent["registry"] == "A" else dev_jwt_b
            print(f"    {agent['label']} ({agent['registry']}): {bal} AVT < {REFUND_THRESHOLD} — "
                  f"refunding {REFUND_AMOUNT} AVT from treasury")
            refund_agent_from_treasury(url, dev_jwt, agent["did"], REFUND_AMOUNT)
            # Verify the new balance (TEG may return 400 but still process)
            time.sleep(1)
            new_bal = get_agent_balance(url, jwt)
            if new_bal is not None and new_bal > bal:
                balance_cache[agent["did"]] = new_bal
                refunded += 1
                print(f"    {agent['label']}: refund confirmed → {new_bal} AVT")
            else:
                print(f"    {agent['label']}: refund unconfirmed (balance: {new_bal})")
    return refunded


# ─────────────────────────────────────────────────────────────────────────────
# Transfers (intra-registry and cross-registry)
# ─────────────────────────────────────────────────────────────────────────────

def execute_transfer(sender_url: str, sender_jwt: str, receiver: Dict,
                     amount: int, message: str, registry_a: str, registry_b: str) -> Dict:
    """Execute transfer — automatically chooses intra vs cross-registry."""
    receiver_did = receiver["did"]
    receiver_url = registry_url_for(receiver, registry_a, registry_b)

    if sender_url == receiver_url:
        return http_post_json(
            f"{sender_url}/api/v1/teg/transfer",
            data={"receiver_agent_id": receiver_did, "amount": str(amount), "message": message},
            headers={"Authorization": f"Bearer {sender_jwt}"},
        )
    else:
        resp = http_post_json(
            f"{sender_url}/api/v1/teg/cross-registry-transfer",
            data={"receiver_did": receiver_did, "amount": str(amount), "message": message},
            headers={"Authorization": f"Bearer {sender_jwt}"},
        )
        # Cross-reg endpoint returns 200 even on failure — check status field
        if resp.get("status") == "failed":
            raise RuntimeError(f"Cross-reg transfer failed: {resp.get('error_message', 'unknown')}")
        return resp


# ─────────────────────────────────────────────────────────────────────────────
# Reputation signals
# ─────────────────────────────────────────────────────────────────────────────

def submit_reputation_signal(registry_url: str, sender_jwt: str,
                             tx_id: str, signal_value: int) -> Optional[Dict]:
    """Submit +1 or -1 reputation signal for a completed transfer."""
    url = f"{registry_url}/api/v1/teg/transactions/{tx_id}/reputation-signal"
    result = http_try("POST", url,
                    {"signal_value": signal_value},
                    {"Authorization": f"Bearer {sender_jwt}"},
                    quiet=True)
    if result is None:
        # Debug: try without /teg/ prefix (direct registry endpoint)
        url2 = f"{registry_url}/api/v1/transactions/{tx_id}/reputation-signal"
        result = http_try("POST", url2,
                        {"signal_value": signal_value},
                        {"Authorization": f"Bearer {sender_jwt}"},
                        quiet=True)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Staking
# ─────────────────────────────────────────────────────────────────────────────

def stake_tokens(registry_url: str, agent_jwt: str,
                 amount: int, lock_period: int = 0) -> Optional[Dict]:
    """Stake tokens. lock_period in days (0=flexible)."""
    return http_try("POST", f"{registry_url}/api/v1/staking/stake",
                    {"amount": str(amount), "lock_period": lock_period},
                    {"Authorization": f"Bearer {agent_jwt}"})


def get_staking_balance(registry_url: str, agent_jwt: str) -> Optional[Dict]:
    """Get staking balance (liquid + staked)."""
    return http_try("GET", f"{registry_url}/api/v1/staking/balance",
                    headers={"Authorization": f"Bearer {agent_jwt}"}, quiet=True)


# ─────────────────────────────────────────────────────────────────────────────
# Governance
# ─────────────────────────────────────────────────────────────────────────────

def create_proposal(registry_url: str, agent_jwt: str,
                    title: str, description: str,
                    duration_seconds: int) -> Optional[Dict]:
    """Create a governance proposal (requires staked balance > 0)."""
    return http_try("POST", f"{registry_url}/api/v1/governance/proposals", {
        "title": title,
        "description": description,
        "duration_seconds": duration_seconds,
        "proposal_type": "standard",
    }, {"Authorization": f"Bearer {agent_jwt}"})


def cast_vote(registry_url: str, agent_jwt: str,
              proposal_id: int, vote_in_favor: bool,
              reason: str = None) -> Optional[Dict]:
    """Cast a vote on a proposal (requires staked balance > 0)."""
    body = {"vote_in_favor": vote_in_favor}
    if reason:
        body["reason"] = reason
    return http_try("POST",
                    f"{registry_url}/api/v1/governance/proposals/{proposal_id}/vote",
                    body, {"Authorization": f"Bearer {agent_jwt}"})


def tally_proposal(registry_url: str, proposer_jwt: str,
                   proposal_id: int) -> Optional[Dict]:
    """Tally a proposal (proposer only, after expiry)."""
    return http_try("POST",
                    f"{registry_url}/api/v1/governance/proposals/{proposal_id}/tally",
                    {}, {"Authorization": f"Bearer {proposer_jwt}"})


def get_proposals(registry_url: str, include_closed: bool = False) -> Optional[Dict]:
    """List governance proposals."""
    url = f"{registry_url}/api/v1/governance/proposals"
    if include_closed:
        url += "?include_closed=true"
    return http_try("GET", url, quiet=True)


# ─────────────────────────────────────────────────────────────────────────────
# Contracts — full lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def create_contract(registry_url: str, client_jwt: str, client_did: str,
                    payment: int, scope: str) -> Optional[Dict]:
    return http_try("POST", f"{registry_url}/api/v1/contracts/", {
        "client_agent_did": client_did,
        "scope_description": scope,
        "source_code_repo_url": "https://git.example.org/theprotocol/eigentrust-sim",
        "source_code_branch": "main",
        "acceptance_criteria": {
            "type": "bilateral_trade_validation",
            "min_transfers": 3,
            "quality_threshold": 0.8
        },
        "payment_amount": payment,
    }, {"Authorization": f"Bearer {client_jwt}"})


def accept_contract(registry_url: str, upgrader_jwt: str,
                    contract_id: int, upgrader_did: str) -> Optional[Dict]:
    return http_try("POST", f"{registry_url}/api/v1/contracts/{contract_id}/accept", {
        "upgrader_agent_did": upgrader_did,
    }, {"Authorization": f"Bearer {upgrader_jwt}"})


def accept_contract_cross_registry(upgrader_url: str, upgrader_jwt: str,
                                   target_registry_url: str, contract_id: int,
                                   upgrader_did: str) -> Optional[Dict]:
    return http_try("POST", f"{upgrader_url}/api/v1/contracts/cross-registry/proxy", {
        "target_registry_url": target_registry_url,
        "contract_id": contract_id,
        "action": "accept",
        "upgrader_agent_did": upgrader_did,
    }, {"Authorization": f"Bearer {upgrader_jwt}"})


def submit_contract(registry_url: str, upgrader_jwt: str,
                    contract_id: int) -> Optional[Dict]:
    return http_try("POST", f"{registry_url}/api/v1/contracts/{contract_id}/submit", {
        "pr_url": f"https://git.example.org/theprotocol/eigentrust-sim/pull/{contract_id}",
    }, {"Authorization": f"Bearer {upgrader_jwt}"})


def submit_contract_cross_registry(upgrader_url: str, upgrader_jwt: str,
                                   target_registry_url: str,
                                   contract_id: int) -> Optional[Dict]:
    return http_try("POST", f"{upgrader_url}/api/v1/contracts/cross-registry/proxy", {
        "target_registry_url": target_registry_url,
        "contract_id": contract_id,
        "action": "submit",
        "pr_url": f"https://git.example.org/theprotocol/eigentrust-sim/pull/{contract_id}",
    }, {"Authorization": f"Bearer {upgrader_jwt}"})


def approve_contract(registry_url: str, client_jwt: str,
                     contract_id: int) -> Optional[Dict]:
    return http_try("POST", f"{registry_url}/api/v1/contracts/{contract_id}/approve-completion",
                    {}, {"Authorization": f"Bearer {client_jwt}"})


def run_contract_lifecycle(client: Dict, upgrader: Dict, jwts: Dict,
                           registry_a: str, registry_b: str, stats: Dict) -> None:
    client_url = registry_url_for(client, registry_a, registry_b)
    upgrader_url = registry_url_for(upgrader, registry_a, registry_b)
    client_jwt = jwts[client["did"]]
    upgrader_jwt = jwts[upgrader["did"]]

    payment = random.randint(CONTRACT_PAYMENT_MIN, CONTRACT_PAYMENT_MAX)
    scope = (f"Bilateral trade validation: {client['label']} contracts "
             f"{upgrader['label']} for {upgrader['type']} services")

    is_cross_reg = (client["registry"] != upgrader["registry"])
    if is_cross_reg:
        # Cross-registry contract payments are broken: money stays in client's TEG,
        # upgrader's home TEG never receives it. Skip until cross-TEG treasury is fixed.
        print(f"    Contract: {client['label']} -> {upgrader['label']} SKIP (cross-reg)")
        return

    print(f"    Contract: {client['label']} -> {upgrader['label']} "
          f"({payment} AVT, {client['registry']}->{upgrader['registry']})")

    resp = create_contract(client_url, client_jwt, client["did"], payment, scope)
    if not resp:
        stats["contracts_failed"] += 1
        return
    contract_id = resp.get("id")
    print(f"      Created: id={contract_id}")

    if False:  # dead code — cross-reg handled above
        resp = accept_contract_cross_registry(
            upgrader_url, upgrader_jwt, client_url, contract_id, upgrader["did"])
    else:
        resp = accept_contract(client_url, upgrader_jwt, contract_id, upgrader["did"])
    if not resp:
        stats["contracts_failed"] += 1
        print(f"      Accept failed")
        return
    print(f"      Accepted by {upgrader['label']}{' [CROSS-REG]' if is_cross_reg else ''}")

    if is_cross_reg:
        resp = submit_contract_cross_registry(
            upgrader_url, upgrader_jwt, client_url, contract_id)
    else:
        resp = submit_contract(client_url, upgrader_jwt, contract_id)
    if not resp:
        stats["contracts_failed"] += 1
        return
    print(f"      Work submitted{' [CROSS-REG]' if is_cross_reg else ''}")

    resp = approve_contract(client_url, client_jwt, contract_id)
    if not resp:
        stats["contracts_failed"] += 1
        return
    print(f"      Approved - {payment} AVT paid to {upgrader['label']}")
    stats["contracts_completed"] += 1


# ─────────────────────────────────────────────────────────────────────────────
# Disputes — enhanced DDR filing
# ─────────────────────────────────────────────────────────────────────────────

def file_dispute(registry_url: str, complainant_jwt: str,
                 defendant_did: str, reason_code: str,
                 description: str) -> Optional[Dict]:
    return http_try("POST", f"{registry_url}/api/v1/teg/disputes/log", {
        "defendant_agent_did": defendant_did,
        "reason_code": reason_code,
        "brief_description": description,
    }, {"Authorization": f"Bearer {complainant_jwt}"})


def run_dispute(complainant: Dict, defendant: Dict, jwts: Dict,
                registry_a: str, registry_b: str, stats: Dict) -> None:
    comp_url = registry_url_for(complainant, registry_a, registry_b)
    comp_jwt = jwts[complainant["did"]]
    reason = random.choice(DISPUTE_REASONS)
    desc = (f"EigenTrust sim dispute: {complainant['label']} alleges {reason} "
            f"by {defendant['label']} during bilateral trade")

    print(f"    Dispute: {complainant['label']} vs {defendant['label']} ({reason})")
    resp = file_dispute(comp_url, comp_jwt, defendant["did"], reason, desc)
    if resp:
        dispute_id = resp.get("id", "?")
        print(f"      Filed: id={dispute_id}, status={resp.get('status', '?')}")
        stats["disputes_filed"] += 1
    else:
        stats["disputes_failed"] += 1


# ─────────────────────────────────────────────────────────────────────────────
# Staking lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def run_staking(agent: Dict, jwts: Dict, registry_a: str, registry_b: str,
                stats: Dict, balance_cache: Dict) -> None:
    """Have an agent stake some tokens if they have enough balance."""
    url = registry_url_for(agent, registry_a, registry_b)
    jwt = jwts[agent["did"]]

    balance = balance_cache.get(agent["did"])
    if balance is None:
        balance = get_agent_balance(url, jwt)
        if balance is not None:
            balance_cache[agent["did"]] = balance

    if balance is None or balance < STAKE_MIN + 1000:  # keep 1000 AVT liquid (prevent dry-out)
        return

    amount = min(random.randint(STAKE_MIN, STAKE_MAX), balance - 1000)
    if amount < STAKE_MIN:
        return

    lock_period = random.choice(LOCK_PERIODS)
    print(f"    Stake: {agent['label']} staking {amount} AVT "
          f"(lock={lock_period}d)")

    resp = stake_tokens(url, jwt, amount, lock_period)
    if resp:
        new_staked = resp.get("new_staked_balance", "?")
        print(f"      Staked OK — new staked balance: {new_staked}")
        stats["stakes_completed"] += 1
        # Update balance cache
        if agent["did"] in balance_cache:
            balance_cache[agent["did"]] = max(0, balance_cache[agent["did"]] - amount)
    else:
        stats["stakes_failed"] += 1


# ─────────────────────────────────────────────────────────────────────────────
# Governance lifecycle
# ─────────────────────────────────────────────────────────────────────────────

PROPOSAL_TOPICS = [
    ("Increase staking rewards for long-term lockers",
     "Proposal to increase APY by 2% for 365-day lock positions to incentivize long-term commitment."),
    ("Add new agent type: DevOps Orchestrator",
     "Proposal to formally recognize DevOps Orchestrator as an agent type with specialized capabilities."),
    ("Reduce minimum stake for governance voting",
     "Current minimum stake is too high for new agents. Proposal to lower the barrier to participation."),
    ("Implement cross-registry dispute arbitration panel",
     "Create a panel of high-reputation agents to arbitrate disputes involving agents from different registries."),
    ("Quarterly reputation score reset for inactive agents",
     "Inactive agents accumulate stale reputation. Proposal to decay reputation for agents with no activity in 90 days."),
    ("Increase transaction fee transparency",
     "Require all fee structures to be published in agent cards before transactions."),
    ("Create agent mentorship program",
     "High-reputation agents mentor new registrants, earning bonus reputation for successful onboarding."),
    ("Establish minimum quality standards for code-reviewer agents",
     "Code reviewers must maintain 90%+ satisfaction rate or face temporary suspension."),
]


def run_governance_cycle(agents: List[Dict], jwts: Dict,
                         registry_a: str, registry_b: str,
                         stats: Dict, active_proposals: List[Dict]) -> None:
    """Create a proposal, have agents vote, tally if expired."""

    # Phase 1: Tally any expired proposals
    tallied = []
    for prop in active_proposals:
        end_ts = prop.get("end_timestamp")
        if end_ts:
            # Parse ISO timestamp
            try:
                end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                now = datetime.now(end_dt.tzinfo) if end_dt.tzinfo else datetime.utcnow()
                if now >= end_dt:
                    proposer = prop["proposer_agent"]
                    url = registry_url_for(proposer, registry_a, registry_b)
                    jwt = jwts[proposer["did"]]
                    print(f"    Tally: proposal #{prop['id']} '{prop['title'][:40]}...'")
                    resp = tally_proposal(url, jwt, prop["id"])
                    if resp:
                        print(f"      Result: {resp.get('status', '?')} "
                              f"(for={resp.get('votes_for', 0)}, "
                              f"against={resp.get('votes_against', 0)})")
                        stats["proposals_tallied"] += 1
                    tallied.append(prop)
            except Exception:
                pass
    for t in tallied:
        active_proposals.remove(t)

    # Phase 2: Create a new proposal (pick a random agent with staked balance > 0)
    staked_agents = []
    for a in agents:
        sb = get_staking_balance(
            registry_url_for(a, registry_a, registry_b),
            jwts[a["did"]]
        )
        if sb and float(sb.get("staked_balance", 0)) > 0:
            staked_agents.append(a)

    if not staked_agents:
        print("    No agents have staked balance — skipping governance this cycle")
        return

    proposer = random.choice(staked_agents)
    url = registry_url_for(proposer, registry_a, registry_b)
    jwt = jwts[proposer["did"]]

    topic = random.choice(PROPOSAL_TOPICS)
    title = topic[0]
    desc = topic[1]
    duration = random.randint(PROPOSAL_DURATION_MIN, PROPOSAL_DURATION_MAX)

    print(f"    Propose: {proposer['label']} — '{title[:50]}...'")
    resp = create_proposal(url, jwt, title, desc, duration)
    if not resp:
        stats["proposals_failed"] += 1
        return

    prop_id = resp.get("id")
    end_ts = resp.get("end_timestamp")
    print(f"      Created: id={prop_id}, expires in {duration}s")
    stats["proposals_created"] += 1

    active_proposals.append({
        "id": prop_id,
        "title": title,
        "end_timestamp": end_ts,
        "proposer_agent": proposer,
        "proposer_url": url,
    })

    # Phase 3: Have other agents vote — ON THE PROPOSER'S REGISTRY (where the proposal lives)
    # Only agents on the same registry as the proposer can vote (cross-registry voting not supported)
    same_reg_voters = [a for a in agents
                       if a["did"] != proposer["did"]
                       and a["registry"] == proposer["registry"]]
    random.shuffle(same_reg_voters)
    # 40-80% of same-registry agents vote
    n_voters = random.randint(max(1, len(same_reg_voters) * 4 // 10),
                              max(2, len(same_reg_voters) * 8 // 10))
    for voter in same_reg_voters[:n_voters]:
        v_url = url  # Use the PROPOSER's registry URL (where the proposal lives)
        v_jwt = jwts[voter["did"]]
        in_favor = random.random() < 0.65  # slight bias toward approval
        reason = random.choice([
            None,
            f"Supported by {voter['type']} perspective",
            f"{'Beneficial' if in_favor else 'Harmful'} to network stability",
            f"Based on {voter['label']}'s experience with similar proposals",
        ])
        resp = cast_vote(v_url, v_jwt, prop_id, in_favor, reason)
        if resp:
            power = resp.get("voting_power", "?")
            tag = "FOR" if in_favor else "AGAINST"
            print(f"      Vote: {voter['label']} -> {tag} (power={power})")
            stats["votes_cast"] += 1
        # Don't print failures — agent may not have staked balance


# ─────────────────────────────────────────────────────────────────────────────
# ZKP input derivation from real transaction data (v2.0.0 circuits)
# ─────────────────────────────────────────────────────────────────────────────

def derive_reference(agent_did: str, label: str) -> str:
    """The reference the registry requires (core/zkp_verifier.derive_reference): the
    first 31 bytes of SHA-256("tp.attestation.ref.v1|" + agent DID + "|" + label).
    The registry derives it again from the submitting agent's DID and
    public_inputs["reference_label"], so a proof names the agent that made it."""
    digest = hashlib.sha256(b"tp.attestation.ref.v1|" + agent_did.encode() + b"|" + label.encode()).digest()
    return str(int.from_bytes(digest[:31], "big"))


def derive_fair_markup_inputs(amount: int, tx_id_str: str, agent_did: str) -> Tuple[Dict, Dict]:
    """
    fairMarkupPolicy/v2.0.0 inputs from the actual transfer amount.

    Pricing model: the agent charges 20% above its cost.
      offered_price = amount                (public)
      total_cost    = amount * 5 // 6       (private: only its commitment is published)
      context       = derive_reference(agent_did, "offer:<tx id>")  (public, names the offer and the agent)
      max_markup_bps = MAX_MARKUP_BPS       (public, checked against the registry policy)

    Constraint: offered_price * 10000 <= total_cost * (10000 + max_markup_bps).
    """
    costs = amount * 5 // 6
    if amount * 10000 > costs * (10000 + MAX_MARKUP_BPS):
        raise ValueError(f"amount={amount} is above cost {costs} plus {MAX_MARKUP_BPS} bps")
    public = {
        "max_markup_bps": MAX_MARKUP_BPS,
        "offered_price":  amount,
        "context":        derive_reference(agent_did, f"offer:{tx_id_str}"),
        "reference_label": f"offer:{tx_id_str}",
    }
    private = {
        "total_cost": costs,
        "salt":       hex(secrets.randbits(248)),
    }
    return public, private


def derive_resource_usage_inputs(amount: int, tx_id_str: str, agent_did: str) -> Tuple[Dict, Dict]:
    """
    accurateResourceUsagePolicy/v2.0.0 inputs from the transfer.

    Resource model: resource_units == transfer_amount (exact 1:1 reporting).
    transaction_ref = derive_reference(agent_did, "tx:<tx id>") (public); the
    logged units stay private behind the log commitment.
    """
    public = {
        "max_discrepancy_bps": MAX_DISCREPANCY_BPS,
        "transaction_ref":     derive_reference(agent_did, f"tx:{tx_id_str}"),
        "reported_units":      amount,
        "reference_label":     f"tx:{tx_id_str}",
    }
    private = {
        "logged_units": amount,
        "salt":         hex(secrets.randbits(248)),
    }
    return public, private


# ─────────────────────────────────────────────────────────────────────────────
# ZKP proof generation: nargo execute, then bb prove, in a temporary directory
# (the circuit registry is never written to)
# ─────────────────────────────────────────────────────────────────────────────

def write_prover_toml(work_dir: Path, inputs: Dict) -> None:
    lines = ["# Generated for one proof"]
    for key, val in inputs.items():
        lines.append(f'{key} = "{val}"')
    (work_dir / "Prover.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(cmd: List[str], cwd: Path, what: str) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed:\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )


def generate_proof(
    circuit_id: str,
    public_inputs: Dict,
    private_inputs: Dict,
) -> Tuple[bytes, str]:
    """Prove in a fresh temporary directory; give back the proof bytes and the commitment it carries (0x)."""
    circuit = CIRCUITS[circuit_id]
    source = circuit["dir"]
    with tempfile.TemporaryDirectory(prefix="zkp_sim_") as tmp:
        work = Path(tmp)
        (work / "src").mkdir()
        shutil.copy(source / "Nargo.toml", work / "Nargo.toml")
        shutil.copy(source / "src" / "main.nr", work / "src" / "main.nr")
        circuit_inputs = {k: v for k, v in public_inputs.items() if k != "reference_label"}
        write_prover_toml(work, {**circuit_inputs, **private_inputs})
        _run([NARGO_BINARY, "execute", "witness"], work, "nargo execute")
        artifact = json.loads((source / "circuit.json").read_text())
        bytecode = work / f"{circuit['name']}.bin"
        bytecode.write_bytes(base64.b64decode(artifact["bytecode"]))
        out_dir = work / "proof_out"
        out_dir.mkdir()
        _run([BB_BINARY, "prove", "-s", "ultra_honk", "-b", str(bytecode),
              "-w", str(work / "target" / "witness.gz"), "-o", str(out_dir)], work, "bb prove")
        proof = (out_dir / "proof").read_bytes()
    # A bb 0.82.2 proof carries a 4-byte field count, the public inputs in ABI
    # order, then the commitment the circuit outputs.
    n_public = len([k for k in public_inputs if k != "reference_label"])
    if len(proof) < 4 + 32 * (n_public + 1):
        raise RuntimeError("proof is too short to carry its public values")
    commitment = proof[4 + 32 * n_public: 36 + 32 * n_public].hex()
    return proof, "0x" + commitment


# ─────────────────────────────────────────────────────────────────────────────
# Attestation submission
# ─────────────────────────────────────────────────────────────────────────────

def submit_attestation(registry_url: str, agent_jwt: str, circuit_id: str,
                       proof_bytes: bytes, public_inputs: Dict) -> Dict:
    return http_post_json(
        f"{registry_url}/api/v1/attestations/submit",
        data={
            "circuit_id":    circuit_id,
            "proof_data":    {"proof_bytes": base64.b64encode(proof_bytes).decode("ascii"),
                              "format": "ultra_honk"},
            "public_inputs": {k: str(v) for k, v in public_inputs.items()},
        },
        headers={"Authorization": f"Bearer {agent_jwt}"},
    )


def attest_agent(registry_url: str, agent: Dict, agent_jwt: str,
                 amount: int, tx_id: str, stats: Dict) -> None:
    label = agent["label"]
    for circuit_id, derive_fn in [
        ("fairMarkupPolicy/v2.0.0",           lambda: derive_fair_markup_inputs(amount, tx_id, agent["did"])),
        ("accurateResourceUsagePolicy/v2.0.0", lambda: derive_resource_usage_inputs(amount, tx_id, agent["did"])),
    ]:
        short = circuit_id.split("/")[0]
        print(f"    [{label}] {short}: generating ...", end=" ", flush=True)
        t0 = time.time()
        pub, priv = derive_fn()
        try:
            proof_bytes, _commitment = generate_proof(circuit_id, pub, priv)
        except Exception as e:
            print(f"FAILED ({e})")
            stats["proof_failed"] += 1
            continue
        gen_ms = int((time.time() - t0) * 1000)
        print(f"done ({gen_ms}ms) -> submitting ...", end=" ", flush=True)
        t0 = time.time()
        try:
            resp = submit_attestation(registry_url, agent_jwt, circuit_id, proof_bytes, pub)
        except Exception as e:
            print(f"SUBMIT FAILED ({e})")
            stats["submit_failed"] += 1
            continue
        sub_ms  = int((time.time() - t0) * 1000)
        status  = resp.get("status", "?")
        atid    = (resp.get("attestation_id") or "?")[:8]
        rdelta  = resp.get("reputation_delta")
        print(f"[{status}]  id={atid}...  rep_delta={rdelta}  ({sub_ms}ms)")
        if status != "verified" and resp.get("reason"):
            print(f"      reason: {resp['reason']}")
        stats["proofs_generated"] += 1
        if status == "verified":
            stats["proofs_verified"] += 1
            stats["rep_deltas"][agent["did"]] = \
                stats["rep_deltas"].get(agent["did"], 0) + (rdelta or 0)


# ─────────────────────────────────────────────────────────────────────────────
# Supply invariant check
# ─────────────────────────────────────────────────────────────────────────────

def check_supply_invariant() -> Tuple[bool, str]:
    """Check supply invariant for both registries. Returns (ok, message)."""
    try:
        # Get ES balances
        req = urllib.request.Request(
            f"{ES_URL}/api/v1/projections/balances",
            headers={"X-Internal-Key": ES_KEY})
        with urllib.request.urlopen(req, timeout=15) as resp:
            es_data = json.loads(resp.read().decode())

        es_bals = {}
        for a in es_data.get("agents", []):
            did = a.get("agent_did", "")
            if did.startswith(("did:theprotocol:teg_system_treasury", "system", "treasury")):
                continue
            es_bals[did] = float(a.get("liquid_balance", 0)) + float(a.get("staked_balance", 0))

        results = []
        for reg_name, container in [("A", "agentvault_registry_a"), ("B", "agentvault_registry_b")]:
            code = """
import os, json
from sqlalchemy import create_engine, text
# the sync driver NAMED (psycopg2): a plain postgresql:// is psycopg 3 on SQLAlchemy 2.1 (§DEPS sqla-driver-pin)
_s, _, _r = os.environ['DATABASE_URL'].partition('://')
db_url = ('postgresql+psycopg2://' + _r) if _s in ('postgresql', 'postgresql+asyncpg') else os.environ['DATABASE_URL']
engine = create_engine(db_url)
with engine.connect() as c:
    rows = c.execute(text('SELECT did, liquid_balance, staked_balance FROM agents')).fetchall()
    out = {}
    for r in rows:
        out[r[0]] = float(r[1] or 0) + float(r[2] or 0)
    print(json.dumps(out))
"""
            result = subprocess.run(
                ["docker", "exec", container, "python3", "-c", code],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return False, f"DB query failed for {reg_name}: {result.stderr[:200]}"

            db_bals = json.loads(result.stdout.strip())
            es_total = sum(es_bals.get(d, 0) for d in db_bals)
            db_total = sum(db_bals.values())
            delta = abs(es_total - db_total)
            results.append((reg_name, db_total, es_total, delta))

        msg_parts = []
        all_ok = True
        for reg_name, db_t, es_t, delta in results:
            status = "OK" if delta <= SUPPLY_TOLERANCE else "BREACH"
            if status == "BREACH":
                all_ok = False
            msg_parts.append(f"Reg {reg_name}: DB={db_t:.0f} ES={es_t:.0f} delta={delta:.0f} [{status}]")

        return all_ok, " | ".join(msg_parts)

    except Exception as e:
        return False, f"Check failed: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Random helpers
# ─────────────────────────────────────────────────────────────────────────────

def random_amount() -> int:
    steps = (MAX_AMOUNT - MIN_AMOUNT) // AMOUNT_STEP
    return MIN_AMOUNT + random.randint(0, steps) * AMOUNT_STEP


def fresh_stats() -> Dict[str, Any]:
    return {
        "transfers":            0,
        "transfers_cross":      0,
        "transfer_failed":      0,
        "contracts_completed":  0,
        "contracts_failed":     0,
        "disputes_filed":       0,
        "disputes_failed":      0,
        "stakes_completed":     0,
        "stakes_failed":        0,
        "proposals_created":    0,
        "proposals_failed":     0,
        "proposals_tallied":    0,
        "votes_cast":           0,
        "rep_signals_sent":     0,
        "rep_signals_failed":   0,
        "negative_signals":     0,
        "proofs_generated":     0,
        "proofs_verified":      0,
        "proof_failed":         0,
        "submit_failed":        0,
        "rep_deltas":           {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="EigenTrust simulation: full agent economy (transfers, staking, governance, contracts, disputes, reputation)"
    )
    p.add_argument("--pairs",    type=int, default=DEFAULT_PAIRS,
                   help="Number of pair permutations to run. 0 = all (default)")
    p.add_argument("--registry-a", type=str, default=DEFAULT_REGISTRY_A)
    p.add_argument("--registry-b", type=str, default=DEFAULT_REGISTRY_B)
    p.add_argument("--registry", type=str, default=None,
                   help="Legacy: set both registries to same URL")
    p.add_argument("--seed",     type=int, default=None)
    p.add_argument("--skip-zkp", action="store_true",
                   help="Skip ZKP proof generation")
    p.add_argument("--skip-contracts", action="store_true")
    p.add_argument("--skip-disputes", action="store_true")
    p.add_argument("--skip-staking", action="store_true")
    p.add_argument("--skip-governance", action="store_true")
    p.add_argument("--skip-reputation", action="store_true")
    p.add_argument("--credentials", type=str, default=str(CREDENTIALS_FILE))

    # Daemon mode
    p.add_argument("--daemon", action="store_true",
                   help="Run continuously with pauses between cycles")
    p.add_argument("--cycle-interval", type=int, default=DEFAULT_CYCLE_INTERVAL,
                   help=f"Seconds between daemon cycles (default: {DEFAULT_CYCLE_INTERVAL})")
    p.add_argument("--daemon-pairs", type=int, default=DAEMON_PAIRS_PER_CYCLE,
                   help=f"Pairs per daemon cycle (default: {DAEMON_PAIRS_PER_CYCLE})")
    p.add_argument("--max-cycles", type=int, default=0,
                   help="Max daemon cycles (0=infinite)")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Run one cycle of the simulation
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(agents: List[Dict], all_possible_pairs: List[Tuple[Dict, Dict]],
              jwts: Dict, registry_a: str, registry_b: str,
              args: argparse.Namespace, stats: Dict,
              balance_cache: Dict, active_proposals: List[Dict],
              num_pairs: int, cycle_num: int = 0) -> None:
    """Run one simulation cycle."""

    zkp_enabled      = not args.skip_zkp
    contracts_enabled = not args.skip_contracts
    disputes_enabled  = not args.skip_disputes
    staking_enabled   = not args.skip_staking
    gov_enabled       = not args.skip_governance
    rep_enabled       = not args.skip_reputation

    # Pick pairs for this cycle
    pairs = list(all_possible_pairs)
    random.shuffle(pairs)
    if num_pairs > 0:
        pairs = pairs[:num_pairs]

    total_pairs = len(pairs)
    cross_pairs = sum(1 for s, r in pairs if s["registry"] != r["registry"])
    intra_pairs = total_pairs - cross_pairs

    cycle_tag = f" (cycle {cycle_num})" if cycle_num > 0 else ""
    print(f"\nRotation: {total_pairs} pairs "
          f"({intra_pairs} intra, {cross_pairs} cross){cycle_tag}\n")

    # ── Trade loop ──────────────────────────────────────────────────────────
    for pair_idx, (sender, receiver) in enumerate(pairs, 1):
        rounds = random.randint(MIN_ROUNDS_PER_PAIR, MAX_ROUNDS_PER_PAIR)
        is_cross = sender["registry"] != receiver["registry"]
        xr_tag = " [CROSS-REG]" if is_cross else ""

        # Check sender balance before starting pair
        sender_url = registry_url_for(sender, registry_a, registry_b)
        sender_jwt = jwts[sender["did"]]

        bal = get_agent_balance(sender_url, sender_jwt)
        if bal is not None:
            balance_cache[sender["did"]] = bal
            # Adapt rounds to available balance
            max_affordable = bal // (MIN_AMOUNT + 10)  # +10 for fees
            if max_affordable < 1:
                print(f"  [{pair_idx}/{total_pairs}] {sender['label']} -> "
                      f"{receiver['label']}: SKIP (balance={bal} AVT){xr_tag}")
                continue
            rounds = min(rounds, max(1, max_affordable))

        print(f"{'~' * 70}")
        print(f" Pair {pair_idx}/{total_pairs}: "
              f"{sender['label']} ({sender['registry']}) -> "
              f"{receiver['label']} ({receiver['registry']})  "
              f"({rounds} rounds){xr_tag}")
        print(f"{'~' * 70}")

        tx_ids_this_pair = []

        for rnd in range(1, rounds + 1):
            amount = random_amount()

            # Balance check — reduce amount if needed
            cached_bal = balance_cache.get(sender["did"])
            if cached_bal is not None:
                if cached_bal < amount + 10:
                    amount = max(MIN_AMOUNT, cached_bal - 10)
                    if amount < MIN_AMOUNT:
                        print(f"\n  Round {rnd}/{rounds}: SKIP (low balance)")
                        continue
                    # Round to AMOUNT_STEP
                    amount = (amount // AMOUNT_STEP) * AMOUNT_STEP
                    if amount < MIN_AMOUNT:
                        continue

            print(f"\n  Round {rnd}/{rounds}  ({amount} AVT)")

            t0 = time.time()
            try:
                tx_resp = execute_transfer(
                    sender_url, sender_jwt, receiver, amount,
                    f"EigenTrust sim pair={pair_idx} round={rnd}",
                    registry_a, registry_b,
                )
                tx_id = tx_resp.get("transaction_id") or tx_resp.get("transfer_id") or f"sim-{pair_idx}-{rnd}"
                tx_ms = int((time.time() - t0) * 1000)
                stats["transfers"] += 1
                if is_cross:
                    stats["transfers_cross"] += 1
                print(f"  Transfer OK: tx_id={tx_id}  ({tx_ms}ms)")
                tx_ids_this_pair.append(tx_id)

                # Update balance cache
                if sender["did"] in balance_cache:
                    balance_cache[sender["did"]] = max(0, balance_cache[sender["did"]] - amount - 5)

            except Exception as e:
                print(f"  Transfer FAILED: {e}")
                stats["transfer_failed"] += 1
                continue

            # Reputation signal (sender rates receiver)
            # Skip for cross-registry transfers — tx_id doesn't exist on sender's TEG
            if rep_enabled and not is_cross and random.random() < PROB_REPUTATION:
                # Generate both positive and negative signals for EigenTrust calibration
                signal = 1 if random.random() < (1.0 - PROB_NEGATIVE_SIGNAL) else -1
                resp = submit_reputation_signal(sender_url, sender_jwt, tx_id, signal)
                if resp and (resp.get("status") == "applied" or resp.get("signal_value") is not None):
                    new_rep = resp.get("new_receiver_reputation", resp.get("new_reputation_score", "?"))
                    tag = "+1" if signal == 1 else "-1"
                    print(f"  Rep signal: {tag} -> {receiver['label']} (rep={new_rep})")
                    stats["rep_signals_sent"] += 1
                    if signal == -1:
                        stats.setdefault("negative_signals", 0)
                        stats["negative_signals"] += 1
                else:
                    stats["rep_signals_failed"] += 1

            # ZKP attestation
            if zkp_enabled:
                attest_agent(sender_url, sender, sender_jwt, amount, tx_id, stats)

        # ── Post-pair activities ────────────────────────────────────────────

        # Contract phase (~30% of pairs)
        if contracts_enabled and random.random() < PROB_CONTRACT:
            print(f"\n  -- Contract Phase --")
            run_contract_lifecycle(sender, receiver, jwts, registry_a, registry_b, stats)

        # Dispute phase (~10% of pairs)
        if disputes_enabled and random.random() < PROB_DISPUTE:
            print(f"\n  -- Dispute Phase --")
            run_dispute(sender, receiver, jwts, registry_a, registry_b, stats)

        # Staking phase (~15% of pairs — sender stakes)
        if staking_enabled and random.random() < PROB_STAKING:
            print(f"\n  -- Staking Phase --")
            run_staking(sender, jwts, registry_a, registry_b, stats, balance_cache)

        print()

    # ── Governance (once per cycle, if enabled) ─────────────────────────────
    if gov_enabled and random.random() < PROB_GOVERNANCE * total_pairs:
        print(f"{'~' * 70}")
        print(f" Governance Phase")
        print(f"{'~' * 70}")
        run_governance_cycle(agents, jwts, registry_a, registry_b, stats, active_proposals)
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Print summary
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(stats: Dict, elapsed: float, agents: List[Dict],
                  jwts: Dict, registry_a: str, registry_b: str,
                  start_bal: Dict, start_rep: Dict,
                  dev_jwt_a: str, dev_jwt_b: str) -> None:
    print("=" * 70)
    print(" CYCLE COMPLETE")
    print("=" * 70)
    print(f"  Elapsed:              {elapsed:.1f}s")
    print(f"  Transfers OK:         {stats['transfers']} ({stats['transfers_cross']} cross-registry)")
    if stats['transfer_failed']:
        print(f"  Transfers FAILED:     {stats['transfer_failed']}")
    if stats['rep_signals_sent'] or stats['rep_signals_failed']:
        print(f"  Reputation signals:   {stats['rep_signals_sent']} sent, {stats['rep_signals_failed']} failed")
    if stats['stakes_completed'] or stats['stakes_failed']:
        print(f"  Stakes:               {stats['stakes_completed']} OK, {stats['stakes_failed']} failed")
    if stats['proposals_created'] or stats['votes_cast']:
        print(f"  Governance:           {stats['proposals_created']} proposals, "
              f"{stats['votes_cast']} votes, {stats['proposals_tallied']} tallied")
    if stats['contracts_completed'] or stats['contracts_failed']:
        print(f"  Contracts:            {stats['contracts_completed']} OK, {stats['contracts_failed']} failed")
    if stats['disputes_filed'] or stats['disputes_failed']:
        print(f"  Disputes:             {stats['disputes_filed']} filed, {stats['disputes_failed']} failed")
    if stats['proofs_generated']:
        print(f"  ZKP proofs:           {stats['proofs_verified']}/{stats['proofs_generated']} verified")
    print()

    def dev_jwt_for(agent):
        return dev_jwt_a if agent["registry"] == "A" else dev_jwt_b

    print(f"  {'Agent':<25} {'Reg':>3} {'Start bal':>12} {'End bal':>12} "
          f"{'Start rep':>10} {'End rep':>10}")
    print(f"  {'~'*25} {'~'*3} {'~'*12} {'~'*12} {'~'*10} {'~'*10}")
    for agent in agents:
        url = registry_url_for(agent, registry_a, registry_b)
        dj = dev_jwt_for(agent)
        info    = get_agent_info(url, agent["did"], dj) if dj else None
        end_rep = info.get("reputation_score", "?") if info else "?"
        end_bal = info.get("liquid_balance",   "?") if info else "?"
        print(f"  {agent['label']:<25} {agent['registry']:>3} "
              f"{str(start_bal.get(agent['did'], '?')):>12} {str(end_bal):>12} "
              f"{str(start_rep.get(agent['did'], '?')):>10} {str(end_rep):>10}")
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    registry_a = args.registry or args.registry_a
    registry_b = args.registry or args.registry_b

    # ── Load credentials ──────────────────────────────────────────────────
    creds_path = Path(args.credentials)
    if not creds_path.exists():
        print(f"ERROR: Credentials file not found: {creds_path}")
        sys.exit(1)

    with creds_path.open(encoding="utf-8") as f:
        agents: List[Dict] = json.load(f)

    if not agents:
        print("ERROR: No agents in credentials file")
        sys.exit(1)

    agents_a = [a for a in agents if a["registry"] == "A"]
    agents_b = [a for a in agents if a["registry"] == "B"]
    n = len(agents)

    mode = "DAEMON" if args.daemon else "ONE-SHOT"

    print("=" * 70)
    print(f" EigenTrust Simulation v2 — TheProtocol [{mode}]")
    print("=" * 70)
    print(f"  Registry A  : {registry_a} ({len(agents_a)} agents)")
    print(f"  Registry B  : {registry_b} ({len(agents_b)} agents)")
    print(f"  Total agents: {n}")
    features = []
    if not args.skip_zkp:       features.append("ZKP")
    if not args.skip_contracts:  features.append("Contracts")
    if not args.skip_disputes:   features.append("Disputes")
    if not args.skip_staking:    features.append("Staking")
    if not args.skip_governance: features.append("Governance")
    if not args.skip_reputation: features.append("Reputation")
    print(f"  Features    : {', '.join(features) if features else 'transfers only'}")
    if args.daemon:
        print(f"  Cycle interval: {args.cycle_interval}s")
        print(f"  Pairs/cycle   : {args.daemon_pairs}")
        if args.max_cycles:
            print(f"  Max cycles    : {args.max_cycles}")
    if args.seed is not None:
        print(f"  Seed        : {args.seed}")
    print()
    for a in agents:
        tag = "A" if a["registry"] == "A" else "B"
        print(f"    [{tag}] {a['label']:<25} {a['did']}  ({a.get('type', '?')})")
    print()

    # ── Pre-flight: ZKP ──────────────────────────────────────────────────
    if not args.skip_zkp:
        for binary, name in [(NARGO_BINARY, "nargo"), (BB_BINARY, "bb")]:
            if not Path(binary).exists():
                print(f"ERROR: {name} not found at '{binary}'.")
                print("  Use --skip-zkp for host execution.")
                sys.exit(1)
        for cid, c in CIRCUITS.items():
            artifact = c["dir"] / "circuit.json"
            if not artifact.exists():
                print(f"ERROR: compiled circuit missing for {cid}: {artifact}")
                sys.exit(1)
        print("Pre-flight: nargo OK, bb OK, compiled circuits present\n")

    # ── Authenticate ────────────────────────────────────────────────────
    print("Authenticating all agents ...")
    jwts: Dict[str, str] = {}
    for agent in agents:
        url = registry_url_for(agent, registry_a, registry_b)
        try:
            jwts[agent["did"]] = get_agent_jwt(url, agent)
            print(f"  [{agent['registry']}] {agent['label']:<25} OK")
        except Exception as e:
            print(f"  [{agent['registry']}] {agent['label']:<25} FAILED: {e}")
            sys.exit(1)
    print()

    dev_jwt_a = get_dev_jwt(registry_a)
    dev_jwt_b = get_dev_jwt(registry_b)

    def dev_jwt_for(agent):
        return dev_jwt_a if agent["registry"] == "A" else dev_jwt_b

    # ── Build all possible pairs ────────────────────────────────────────
    all_possible_pairs = [
        (agents[i], agents[j])
        for i in range(n)
        for j in range(n)
        if i != j
    ]

    # Shared state across daemon cycles
    balance_cache: Dict[str, int] = {}
    active_proposals: List[Dict] = []
    cumulative_stats = fresh_stats()

    # ── Snapshot starting state ─────────────────────────────────────────
    print("Starting state:")
    start_rep: Dict[str, Any] = {}
    start_bal: Dict[str, Any] = {}
    for agent in agents:
        url = registry_url_for(agent, registry_a, registry_b)
        dj = dev_jwt_for(agent)
        info = get_agent_info(url, agent["did"], dj) if dj else None
        rep  = info.get("reputation_score", "?") if info else "?"
        bal  = info.get("liquid_balance",   "?") if info else "?"
        start_rep[agent["did"]] = rep
        start_bal[agent["did"]] = bal
        balance_cache[agent["did"]] = int(bal) if isinstance(bal, (int, float)) else 0
        print(f"  [{agent['registry']}] {agent['label']:<25} balance={bal}  rep={rep}")
    print()

    # ── Prerequisite: ensure all agents have staked (required for governance) ──
    if not args.skip_governance and not args.skip_staking:
        print("Ensuring all agents have staked balance (governance prerequisite) ...")
        for agent in agents:
            url = registry_url_for(agent, registry_a, registry_b)
            jwt = jwts[agent["did"]]
            sb = get_staking_balance(url, jwt)
            staked = 0
            if sb:
                staked = int(float(sb.get("staked_balance", 0)))
            if staked == 0:
                liquid = balance_cache.get(agent["did"], 0)
                stake_amount = min(1000, max(0, liquid - 2000))  # keep 2000 liquid
                if stake_amount >= STAKE_MIN:
                    print(f"  [{agent['registry']}] {agent['label']:<25} staked=0 — staking {stake_amount} AVT ...")
                    resp = stake_tokens(url, jwt, stake_amount, lock_period=0)
                    if resp:
                        print(f"    Staked OK — new staked: {resp.get('new_staked_balance', '?')}")
                        balance_cache[agent["did"]] = max(0, liquid - stake_amount)
                    else:
                        print(f"    Staking FAILED")
                else:
                    print(f"  [{agent['registry']}] {agent['label']:<25} staked=0, insufficient liquid ({liquid}) — skipping")
            else:
                print(f"  [{agent['registry']}] {agent['label']:<25} staked={staked} — OK")
        print()

    if args.daemon:
        # ── Daemon mode ─────────────────────────────────────────────────
        cycle = 0
        try:
            while True:
                cycle += 1
                if args.max_cycles and cycle > args.max_cycles:
                    print(f"\nMax cycles ({args.max_cycles}) reached. Exiting.")
                    break

                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n{'#' * 70}")
                print(f" CYCLE {cycle} — {ts}")
                print(f"{'#' * 70}")

                stats = fresh_stats()
                t0 = time.time()

                # Re-authenticate every 10 cycles (JWTs expire)
                if cycle % 10 == 0:
                    print("  Re-authenticating agents ...")
                    for agent in agents:
                        url = registry_url_for(agent, registry_a, registry_b)
                        try:
                            jwts[agent["did"]] = get_agent_jwt(url, agent)
                        except Exception as e:
                            print(f"    {agent['label']} auth failed: {e}")
                    dev_jwt_a = get_dev_jwt(registry_a)
                    dev_jwt_b = get_dev_jwt(registry_b)
                    print("  Done.\n")

                # Auto-refund depleted agents every cycle (was every 5 — too infrequent,
                # agents would drain dry between checks)
                if True:
                    # f038: Auto-mint treasury if running low
                    for teg_label, teg_admin_key, reg_url in [
                        ("A", os.environ.get("TEG_ADMIN_API_KEY_A", ""), registry_a),
                        ("B", os.environ.get("TEG_ADMIN_API_KEY_B", ""), registry_b),
                    ]:
                        try:
                            # §RELEASE-P3 (2026-09-05): the TEG admin key comes from the environment ONLY. This
                            # line carried frame-a's LIVE key as a literal fallback, in a tracked file. Unset ⇒
                            # the auto-mint leg is skipped, loudly (direct TEG mints are refused under
                            # TEG_MINT_REQUIRE_PROXY anyway — §MINTSECRET).
                            admin_key = teg_admin_key
                            if not admin_key:
                                print(f"  [skip] TEG_ADMIN_API_KEY_{teg_label} not set — auto-mint leg disabled for TEG {teg_label}")
                                continue
                            # Check treasury balance via registry proxy
                            dev_jwt = dev_jwt_a if teg_label == "A" else dev_jwt_b
                            tb = http_try("GET", f"{reg_url}/api/v1/teg/treasury/balance",
                                         headers={"Authorization": f"Bearer {dev_jwt}"}, quiet=True)
                            if tb:
                                tbal = int(float(tb.get("balance", 0)))
                                if tbal < TREASURY_MIN_BALANCE:
                                    # Mint via TEG admin API
                                    teg_url = "http://teg-layer:8080" if teg_label == "A" else "http://teg-layer-b:8080"
                                    # Use docker exec to reach TEG internal network
                                    container = "agentvault_registry_a" if teg_label == "A" else "agentvault_registry_b"
                                    mint_cmd = subprocess.run(
                                        ["docker", "exec", container, "curl", "-s",
                                         f"{teg_url}/api/v1/admin/token/issue",
                                         "-X", "POST", "-H", "Content-Type: application/json",
                                         "-H", f"Authorization: Bearer {admin_key}",
                                         "-d", json.dumps({"target_agent_id": f"did:theprotocol:teg_system_treasury{'_b' if teg_label == 'B' else ''}",
                                                           "amount": TREASURY_MINT_AMOUNT,
                                                           "reason": "EigenTrust auto-mint: treasury below threshold"})],
                                        capture_output=True, text=True, timeout=15
                                    )
                                    print(f"  Treasury {teg_label}: {tbal} AVT < {TREASURY_MIN_BALANCE} — minted {TREASURY_MINT_AMOUNT} AVT")
                        except Exception as e:
                            pass  # Non-fatal

                    print("  Checking agent balances for auto-refund ...")
                    n = check_and_refund_depleted_agents(
                        agents, jwts, balance_cache,
                        registry_a, registry_b, dev_jwt_a, dev_jwt_b,
                    )
                    if n:
                        print(f"  Refunded {n} agent(s).\n")
                    else:
                        print("  All agents above threshold.\n")

                run_cycle(agents, all_possible_pairs, jwts,
                          registry_a, registry_b, args, stats,
                          balance_cache, active_proposals,
                          args.daemon_pairs, cycle)

                elapsed = time.time() - t0

                # Accumulate stats
                for k in stats:
                    if k == "rep_deltas":
                        for d, v in stats[k].items():
                            cumulative_stats[k][d] = cumulative_stats[k].get(d, 0) + v
                    elif k in cumulative_stats:
                        cumulative_stats[k] += stats[k]
                    else:
                        cumulative_stats[k] = stats[k]

                # Print cycle summary
                print(f"\n  Cycle {cycle} summary: {stats['transfers']} transfers, "
                      f"{stats['rep_signals_sent']} rep signals, "
                      f"{stats['stakes_completed']} stakes, "
                      f"{stats['votes_cast']} votes, "
                      f"{stats['contracts_completed']} contracts, "
                      f"{stats['disputes_filed']} disputes  ({elapsed:.1f}s)")

                # Supply invariant check
                print(f"  Supply check: ", end="", flush=True)
                # Wait a moment for ES cache to update
                time.sleep(3)
                ok, msg = check_supply_invariant()
                print(msg)
                if not ok:
                    print(f"  WARNING: Supply invariant breach detected!")

                # Cumulative totals
                print(f"  Cumulative: {cumulative_stats['transfers']} transfers, "
                      f"{cumulative_stats['rep_signals_sent']} rep signals, "
                      f"{cumulative_stats['stakes_completed']} stakes, "
                      f"{cumulative_stats['votes_cast']} votes")

                print(f"\n  Sleeping {args.cycle_interval}s until next cycle...")
                time.sleep(args.cycle_interval)

        except KeyboardInterrupt:
            print(f"\n\nDaemon stopped after {cycle} cycles.")

        # Final summary
        print_summary(cumulative_stats, time.time() - t0, agents, jwts,
                      registry_a, registry_b, start_bal, start_rep,
                      dev_jwt_a, dev_jwt_b)

    else:
        # ── One-shot mode ───────────────────────────────────────────────
        stats = fresh_stats()
        t0 = time.time()
        num_pairs = args.pairs if args.pairs > 0 else 0  # 0 = all

        run_cycle(agents, all_possible_pairs, jwts,
                  registry_a, registry_b, args, stats,
                  balance_cache, active_proposals,
                  num_pairs)

        elapsed = time.time() - t0
        print_summary(stats, elapsed, agents, jwts,
                      registry_a, registry_b, start_bal, start_rep,
                      dev_jwt_a, dev_jwt_b)

        # Supply invariant check
        print("\nSupply invariant check ...")
        time.sleep(3)
        ok, msg = check_supply_invariant()
        print(f"  {msg}")
        if not ok:
            print("  WARNING: Supply invariant breach detected")
        else:
            print("  Supply invariant: CLEAN")

        if not args.skip_zkp and stats["proofs_verified"] < stats["proofs_generated"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
