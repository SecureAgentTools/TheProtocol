"""§MCPTEST30 (V0541): the settlement probe judges the receiver's half by the receiver's own ledger row, not its balance.

Round 11's strict run (186f01a3a7794b12) marked transferUnits a BUG-FIND: "the receiver's balance moved +0.020000, not
+0.010000". The TEG held two 0.01 transfers from the run's sentinel to that receiver 0.68 s apart, the idempotency probe's
(2c1d4c6a) and this probe's own (e10e4e9d): other probes pay the same receiver while this one reads its balance twice, so
a balance cannot attribute a movement (round 7 met the same race in the concurrent idempotency pair). The probe sends a
message only it sends and counts the receiver's ledger rows that carry it: one is the verdict, the balance is evidence.
"""
from __future__ import annotations

import json

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


def _ok(payload):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}, "200"


class Ledger:
    """A fake registry: `rows_per_transfer` ledger rows per transfer, and `interfere` = another probe pays the receiver."""

    def __init__(self, rows_per_transfer=1, interfere=False):
        self.balance, self.rows = 475103, []          # hundredths
        self.rows_per_transfer, self.interfere = rows_per_transfer, interfere

    async def rpc(self, tool, args, jwt="", timeout=20):
        if tool == "theprotocol_getMyTegTransactions":
            return _ok({"transactions": [{"transaction_id": t, "attached_message": m} for t, m in self.rows]})
        if tool == "theprotocol_getMyBalance":
            return _ok({"liquid_balance": f"{self.balance / 100:.2f}", "staked_balance": "0"})
        if tool == "theprotocol_transferUnits":
            for _ in range(self.rows_per_transfer):
                self.rows.append((f"tx-{len(self.rows)}", args.get("message")))
                self.balance += 1
            if self.interfere:
                self.rows.append(("tx-other", "MCP tester: an idempotent replay 0a1b2c3d4e5f"))
                self.balance += 1
            return _ok({"transaction_id": "e10e4e9d-47d9-4830-b424-57b64197fc4a", "status": "completed", "amount": "0.01"})
        return _ok({})


class Bag:
    developer_jwt, sentinel_jwt, sentinel_did = "dev", "sentinel-jwt", "did:theprotocol:sentinel"
    flow_values = {"second_agent_did": "did:theprotocol:second", "second_agent_jwt": "second-jwt"}

    def get(self, k, d=None):
        return self.flow_values.get(k, d)


async def _row(ledger):
    out = {}
    await L.lifecycle_transfer_settlement(ledger.rpc, _parse_rpc_result, Bag(), out)
    return out["theprotocol_transferUnits"]


async def test_another_probe_paying_the_receiver_is_not_a_bug_find():
    ledger = Ledger(interfere=True)
    row = await _row(ledger)
    assert row["healthy"] is True, row.get("fail_reason")
    assert ledger.balance == 475105, "the receiver's balance moved +0.02, as round 11's did"


async def test_a_transfer_the_receivers_ledger_does_not_hold_is_a_bug_find():
    """The control: the row is red when the receiver's ledger holds no transaction carrying the transfer."""
    row = await _row(Ledger(rows_per_transfer=0))
    assert row["healthy"] is False and "holds 0 transactions carrying this transfer's message" in row["fail_reason"]


async def test_a_transfer_the_receivers_ledger_holds_twice_is_a_bug_find():
    row = await _row(Ledger(rows_per_transfer=2))
    assert row["healthy"] is False and "holds 2 transactions carrying this transfer's message" in row["fail_reason"]
