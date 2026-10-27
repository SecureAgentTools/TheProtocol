"""
MCP Prompts (spec 2025-11-25) — guided workflow templates.

Turns the 400-tool surface into journeys: each prompt renders a precise,
tool-by-tool brief the client model can follow, teaching the gateway verbs
(searchTools/describeTools/invokeTool) along the way. Also hosts the
completion/complete vocabulary for prompt arguments.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# name → {title, description, arguments, template}
# {placeholders} in template are substituted from prompts/get arguments.
_PROMPTS: Dict[str, Dict[str, Any]] = {
    "onboard_agent": {
        "title": "Onboard a New Agent",
        "description": "Create an agent identity end to end: developer auth, bootstrap token, create the agent, keep the one-time client_secret, first agent JWT.",
        "arguments": [
            {"name": "agent_name", "description": "Human-readable name for the new agent", "required": True},
        ],
        "template": (
            "Onboard a new agent named '{agent_name}' on TheProtocol registry.\n"
            "1. Call theprotocol_createAgent with name='{agent_name}' (developer auth via your bridge/API key).\n"
            "2. SAVE the returned client_id AND client_secret immediately: the secret is shown exactly once.\n"
            "3. Mint the agent's first JWT: theprotocol_getAgentToken(client_id, client_secret).\n"
            "4. Verify identity: theprotocol_getMyAgentInfo with that JWT, then theprotocol_getMyBalance.\n"
            "If any tool is missing from your list, find it with theprotocol_searchTools and call it via theprotocol_invokeTool."
        ),
    },
    "fund_agent": {
        "title": "Fund an Agent from the Treasury (administrators)",
        "description": "Move units from the registry treasury to an agent: an administrator's action (the admin_treasury flag), with the balance read before and after.",
        "arguments": [
            {"name": "agent_did", "description": "DID of the agent to fund", "required": True},
            {"name": "amount", "description": "Amount to fund, in the frame's units", "required": True},
        ],
        "template": (
            "Fund agent {agent_did} with {amount} units from the registry treasury.\n"
            "This needs an administrator with the admin_treasury flag. Without one, ask instead: as the agent, "
            "theprotocol_submitFundingRequest(amount={amount}, reason=...) and wait for an administrator's answer.\n"
            "1. Read the current balance: theprotocol_getMyBalance (as the agent).\n"
            "2. As the administrator: POST /api/v1/teg/treasury/fund-agent with the body "
            "target_agent_did={agent_did}, amount={amount}, reason=admin_grant (the admin MCP server's "
            "adminRequest tool, or the console).\n"
            "3. Re-read the balance and confirm the change equals {amount}.\n"
            "Never edit balances directly: the treasury route records the ledger events that keep the supply audit at Δ=0."
        ),
    },
    "transfer_tokens": {
        "title": "Transfer Units (same registry or another one)",
        "description": "Move units between agents: smartSend picks the route (local or cross-registry); transferUnits and tegCrossRegistryTransferDirect take an idempotency key for a safe retry.",
        "arguments": [
            {"name": "recipient", "description": "Recipient agent DID (or name to resolve first)", "required": True},
            {"name": "amount", "description": "Amount to send", "required": True},
        ],
        "template": (
            "Transfer {amount} units to {recipient}.\n"
            "1. Resolve the recipient if needed: theprotocol_discoverAgents(query='{recipient}').\n"
            "2. theprotocol_smartSend(receiver_did, amount='{amount}', dry_run=true) shows the route first; call it again "
            "with dry_run=false to send. It routes through /teg/transfer (local) or /teg/cross-registry-transfer "
            "(another registry); the registry's fees apply.\n"
            "3. smartSend takes no idempotency key, and a memo does not make a retry safe. For a retry-safe send use "
            "theprotocol_transferUnits (local) or theprotocol_tegCrossRegistryTransferDirect (another registry) with "
            "an idempotency_key, and reuse the key on the retry.\n"
            "4. Confirm with theprotocol_getMyTegTransactions (look for the new transaction_id) and a fresh getMyBalance."
        ),
    },
    "lock_units": {
        "title": "Lock Units and Check the Lock",
        "description": "Lock units, understand the lock period and check the lock (locking, and any payout on locked units, are switches per registry; this prompt is listed only where locking is on).",
        "arguments": [
            {"name": "amount", "description": "Amount to lock", "required": True},
        ],
        "template": (
            "Lock {amount} units on this registry.\n"
            "1. theprotocol_lockUnits(amount={amount}). Each lock's period decides when it can be released.\n"
            "2. Verify: theprotocol_getMyLocks and theprotocol_getMyLockStatus.\n"
            "3. Release when the period has passed: theprotocol_unlockUnits.\n"
            "4. Only where this registry pays a payout on locked units (its registry-config says so): "
            "theprotocol_getMyPayoutHistory, and theprotocol_updatePayoutRelock to lock each payout as it comes."
        ),
    },
    "post_guild_task": {
        "title": "Post a Guild Work Order",
        "description": "Post a bountied task on THE GUILD work exchange: escrowed bounty → bids → award → verify → payout.",
        "arguments": [
            {"name": "task_description", "description": "What work needs doing", "required": True},
            {"name": "bounty", "description": "Bounty amount to escrow", "required": True},
        ],
        "template": (
            "Post a Guild work order: '{task_description}' with a bounty of {bounty} units.\n"
            "1. theprotocol_guildPostOrder(title='{task_description}', bounty='{bounty}', spec=<what done looks like>): "
            "the bounty is escrowed from your balance.\n"
            "2. Watch bids: theprotocol_guildListOrders / theprotocol_guildGetOrder.\n"
            "3. Award the best bid: theprotocol_guildAward.\n"
            "4. On delivery, theprotocol_guildVerify releases escrow + writes the work credential; rate the worker.\n"
            "A rejected delivery goes to the dispute flow, which splits the escrow; never abandon a funded order."
        ),
    },
    "trade_on_agora": {
        "title": "Trade on the AGORA market",
        "description": "Read the book, place a bounded limit order, and verify settlement on the AGORA organization market.",
        "arguments": [
            {"name": "ticker", "description": "Listing symbol, e.g. $SYBIL", "required": True},
        ],
        "template": (
            "Trade {ticker} on AGORA.\n"
            "1. Discover: theprotocol_getAgoraListings, then theprotocol_getAgoraOrderBook(listing='{ticker}') "
            "and theprotocol_getAgoraCandles(listing='{ticker}') for price context.\n"
            "2. Place a LIMIT order with an explicit price (a market order answers 409 on a book with no trade yet): "
            "theprotocol_placeAgoraOrder(listing='{ticker}', side, qty, price, order_type='limit').\n"
            "3. Track: theprotocol_getMyAgoraOrders → filled/partial; funds move via TEG escrow atomically.\n"
            "4. Holdings check: theprotocol_getMyAgoraHoldings. Cancel stale orders with theprotocol_cancelAgoraOrder."
        ),
    },
    "diagnose_failed_transfer": {
        "title": "Diagnose a Failed or Missing Transfer",
        "description": "Trace a transfer end-to-end: balances → transaction detail → ledger events, distinguishing user error from rail faults.",
        "arguments": [
            {"name": "transaction_ref", "description": "Transaction id or memo reference (optional)", "required": False},
        ],
        "template": (
            "Diagnose transfer issue (ref: {transaction_ref}).\n"
            "1. theprotocol_getMyBalance: is the debit or credit visible?\n"
            "2. theprotocol_getMyTegTransactions: find the row; theprotocol_getTegTransactionDetail(id) for its status and error text.\n"
            "3. An async cross-registry leg settles later: a PENDING row minutes old is normal; stuck legs are swept server-side.\n"
            "4. Recent ledger events: theprotocol_getPublicEventStoreRecent (a short seed of this frame's newest events, "
            "not a history; a transfer older than the ring is not in it).\n"
            "5. If units left your agent and did not arrive after the sweep window, file a support ticket "
            "(theprotocol_submitSupportTicket) with the transaction id; theprotocol_submitDispute is for a disagreement "
            "with another agent."
        ),
    },
}


# W3 (2026-10-25): a renamed prompt still answers under its old name, and is listed only under the new one
_PROMPT_ALIASES: Dict[str, str] = {"stake_and_earn": "lock_units"}


def _prompt(name: str) -> Optional[Dict[str, Any]]:
    return _PROMPTS.get(_PROMPT_ALIASES.get(name, name))


def list_prompts() -> Dict[str, Any]:
    from .tool_switches import prompt_listed
    return {
        "prompts": [
            {
                "name": name,
                "title": p["title"],
                "description": p["description"],
                "arguments": p["arguments"],
            }
            for name, p in _PROMPTS.items() if prompt_listed(name)
        ]
    }


def missing_required(name: str, arguments: Optional[Dict[str, Any]]) -> List[str]:
    """§MCPTEST30 (2026-10-01): the required arguments a prompts/get call left out (empty strings count as absent).
    MCP answers a missing required argument with -32602; this server used to render the prompt with empty holes."""
    p = _prompt(name)
    if p is None:
        return []
    given = {k for k, v in (arguments or {}).items() if v is not None and str(v).strip() != ""}
    return [a["name"] for a in p["arguments"] if a.get("required") and a["name"] not in given]


def get_prompt(name: str, arguments: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    p = _prompt(name)
    if p is None:
        return None
    args = {a["name"]: "" for a in p["arguments"]}
    args.update({k: str(v) for k, v in (arguments or {}).items()})
    try:
        text = p["template"].format(**args)
    except KeyError:
        text = p["template"]
    return {
        "description": p["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


# ---------------------------------------------------------------------------
# completion/complete vocabulary (prompt arguments + toolset names)
# ---------------------------------------------------------------------------

_COMPLETION_VOCAB: Dict[str, List[str]] = {
    "ticker": ["$SYBIL", "$EAST", "$BSEA", "$HERALD", "$MOIRA", "$VERID", "$CRUCB"],
    "amount": ["10", "100", "1000"],
    "bounty": ["25", "50", "100"],
}


def complete(ref: Dict[str, Any], argument: Dict[str, Any], toolset_names: List[str]) -> Dict[str, Any]:
    """Best-effort argument completion for prompts (and toolset names for
    anything asking about 'toolsets'). Unknown → empty values, never an error."""
    arg_name = (argument or {}).get("name", "")
    prefix = str((argument or {}).get("value", "") or "").lower()
    values: List[str] = []
    if arg_name in _COMPLETION_VOCAB:
        values = _COMPLETION_VOCAB[arg_name]
    elif "toolset" in arg_name.lower():
        values = sorted(toolset_names)
    if prefix:
        values = [v for v in values if v.lower().startswith(prefix)] or values[:5]
    return {"completion": {"values": values[:25], "total": len(values), "hasMore": False}}
