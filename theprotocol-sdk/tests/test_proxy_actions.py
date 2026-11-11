"""V0659 (c): TheProtocol Proxy's actions on TheProtocol: an A2A task to a named agent (free agents only), a payment
authorization and its settle ONLY under a Cockpit mandate (the proxy's limits under the mandate's, the agent's spend
cap at or under them, a payment action refused while there is none), a contract milestone's evidence, and a message
into a chat thread. Each keeps the action contract (a dry run sends nothing, every write carries the record's key, a
4xx is Refused and a 5xx or 429 is Retry). Red before V0659 (c): none of these actions exist.
"""
from __future__ import annotations

import pytest

from theprotocol.proxy.plugins import PluginError, Refused, Retry
from theprotocol.proxy.testing import FakeContext, FakeResponse, check_action, check_action_refusals

PAYEE = "did:theprotocol:kestrel-chartering"
MANDATE = "lm_0a1b2c3d4e5f"


# ── the A2A task ─────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_a_task_goes_to_a_free_agent_with_the_records_key_as_its_message_id():
    from theprotocol.proxy.actions_builtin import A2ATaskAction
    ok = FakeResponse(200, {"ok": True, "stage": "called", "result": {"result": {"id": "task-77"}}})
    out = await check_action(A2ATaskAction, {"agent": PAYEE}, {"text": "quote a charter", "berth": 4}, answers=[ok])
    assert out.reference == "task-77"
    await check_action_refusals(A2ATaskAction, {"agent": PAYEE}, {"text": "x"})
    ctx = FakeContext(answers=[FakeResponse(200, {"ok": True, "stage": "called", "result": {}})])
    await A2ATaskAction({"agent": PAYEE}, ctx).perform({"text": "hello", "berth": 4}, key="tpx-1", dry_run=False)
    body = ctx.calls[0]["json"]
    msg = body["payload"]["params"]["message"]
    assert body["free_only"] is True and body["target_agent_did"] == PAYEE and msg["messageId"] == "tpx-1"
    assert msg["parts"] == [{"kind": "text", "text": "hello"}, {"kind": "data", "data": {"berth": 4}}]


async def test_an_agent_that_charges_is_refused_and_one_that_did_not_deliver_is_retried():
    from theprotocol.proxy.actions_builtin import A2ATaskAction
    charges = FakeResponse(200, {"ok": False, "stage": "quoted", "error": "this agent charges 5 ECU a call"})
    with pytest.raises(Refused, match="not sent"):
        await A2ATaskAction({"agent": PAYEE}, FakeContext(answers=[charges])).perform({"text": "x"}, key="k",
                                                                                     dry_run=False)
    failed = FakeResponse(200, {"ok": False, "stage": "failed", "error": "The agent did not deliver."})
    with pytest.raises(Retry, match="did not deliver"):
        await A2ATaskAction({"agent": PAYEE}, FakeContext(answers=[failed])).perform({"text": "x"}, key="k",
                                                                                    dry_run=False)


# ── the payment, under a mandate ─────────────────────────────────────────────────────────────────────────────────────

def _registry(*, mandate=None, spend=None, mandate_status=200, fail_settle=None):
    """Answers the payment action's calls the way the registry would."""
    m = {"mandate_id": MANDATE, "status": "signed", "valid": True, "effective_scope": ["a2a.pay"], "reasons": [],
         "limits": {"max_per_tx": "50", "currency": "ECU"}, **(mandate or {})}
    sp = {"max_per_tx": "25", "max_per_day": "200", "allowed_currencies": None, **(spend or {})}

    def answer(method, path, rec):
        if path.endswith("/for-agent"):
            return FakeResponse(mandate_status, m if mandate_status == 200 else {"detail": "Not your mandate"})
        if path == "/api/v1/agents/me/authz":
            return FakeResponse(200, {"spend_policy": sp})
        if path.endswith("/authorize"):
            return FakeResponse(200, {"token": "apt_" + "a" * 64, "token_id": "t-1", "amount": rec["json"]["amount"]})
        if path.endswith("/settle"):
            if fail_settle:
                return FakeResponse(fail_settle, {"detail": "settle trouble"})
            return FakeResponse(200, {"token_id": "t-1", "status": "settled", "settlement_tx_id": "tx-9",
                                      "amount": "12.5", "currency": "ECU", "caller_did": "did:x"})
        return FakeResponse(404, {"detail": "Not Found"})
    return answer


CFG = {"mandate": MANDATE, "payee": PAYEE, "max_amount": "30"}


async def test_a_payment_names_its_mandate_authorizes_then_settles_under_the_records_key():
    from theprotocol.proxy.actions_builtin import PaymentAction
    out = await check_action(PaymentAction, CFG, {"amount": "12.5"}, answers=_registry())
    assert out.reference == "tx-9" and out.data["token_id"] == "t-1"
    ctx = FakeContext(answers=_registry())
    await PaymentAction(CFG, ctx).perform({"amount": "12.5"}, key="tpx-7", dry_run=False)
    auth, settle = ctx.calls
    assert auth["path"] == "/api/v1/a2a-payment/authorize" and auth["headers"]["X-Liability-Mandate"] == MANDATE
    assert auth["json"] == {"target_agent_did": PAYEE, "amount": "12.5", "ttl_seconds": 900}
    assert settle["json"]["token"] == "apt_" + "a" * 64 and settle["json"]["task_id"] == "tpx-7"
    assert auth["idempotency_key"] == settle["idempotency_key"] == "tpx-7"
    await check_action_refusals(PaymentAction, CFG, {"amount": "1"})


async def test_a_payment_above_the_proxys_limit_or_not_above_zero_is_refused_before_any_call():
    from theprotocol.proxy.actions_builtin import PaymentAction
    for amount, why in (("30.01", "above the proxy's max_amount"), ("0", "not above 0"), ("x", "not a number")):
        ctx = FakeContext(answers=_registry())
        with pytest.raises(Refused, match=why):
            await PaymentAction(CFG, ctx).perform({"amount": amount}, key="k", dry_run=False)
        assert ctx.calls == []


async def test_a_payment_action_starts_only_under_a_mandate_and_a_spend_cap_at_or_under_it():
    from theprotocol.proxy.actions_builtin import PaymentAction

    async def start(cfg=CFG, **reg):
        await PaymentAction(cfg, FakeContext(answers=_registry(**reg))).start()

    await start()
    cases = [
        (dict(spend={"max_per_tx": None, "max_per_day": None}), "has no spend cap"),
        (dict(spend={"max_per_tx": "60"}), "spend cap max_per_tx 60 is above the mandate's"),
        (dict(mandate={"valid": False, "reasons": ["mandate_revoked"], "effective_scope": []}), "mandate_revoked"),
        (dict(mandate={"effective_scope": ["contracts.engage"]}), "a2a.pay is not in its scope"),
        (dict(mandate_status=403), "not this agent's to pay under"),
        (dict(mandate={"limits": {"currency": "ECU"}}, spend={"allowed_currencies": ["ACU"]}), "may spend only ACU"),
    ]
    for reg, why in cases:
        with pytest.raises(PluginError, match=why):
            await start(**reg)
    with pytest.raises(PluginError, match="above the mandate's max_per_tx 50"):
        await start({**CFG, "max_amount": "75"})
    with pytest.raises(PluginError, match="needs a registry from V0659 on"):
        await PaymentAction(CFG, FakeContext(answers=lambda m, p, r: FakeResponse(404, {"detail": "Not Found"}))).start()


async def test_the_proxys_per_day_waits_for_the_next_day_and_counts_a_payment_once():
    from theprotocol.proxy.actions_builtin import PaymentAction
    ctx = FakeContext(answers=_registry())
    a = PaymentAction({**CFG, "per_day": "20"}, ctx)
    await a.perform({"amount": "12.5"}, key="k1", dry_run=False)
    await a.perform({"amount": "12.5"}, key="k1", dry_run=False)        # the same record again: not counted twice
    with pytest.raises(Retry) as e:
        await a.perform({"amount": "12.5"}, key="k2", dry_run=False)
    assert "per_day 20 is reached (12.5 paid today)" in e.value.detail and 0 < e.value.after <= 86400


async def test_a_lost_settle_is_retried_and_a_refused_one_goes_to_the_dead_letters():
    from theprotocol.proxy.actions_builtin import PaymentAction
    with pytest.raises(Retry, match="the settlement: HTTP 503"):
        await PaymentAction(CFG, FakeContext(answers=_registry(fail_settle=503))).perform({"amount": "1"}, key="k",
                                                                                         dry_run=False)
    with pytest.raises(Refused, match="the settlement: HTTP 400"):
        await PaymentAction(CFG, FakeContext(answers=_registry(fail_settle=400))).perform({"amount": "1"}, key="k",
                                                                                         dry_run=False)


# ── a milestone's evidence, a chat message ───────────────────────────────────────────────────────────────────────────

async def test_a_milestones_evidence_carries_the_records_key_and_a_repeat_is_recognised():
    from theprotocol.proxy.actions_builtin import MilestoneEvidenceAction
    cfg = {"contract_id": "c-41", "seq": 2}
    out = await check_action(MilestoneEvidenceAction, cfg, {"photos": 3},
                             answers=[FakeResponse(200, {"ok": True, "status": "submitted"})])
    assert out.reference == "c-41#2"
    await check_action_refusals(MilestoneEvidenceAction, {"contract_id": "c-41", "seq": 2}, {"photos": 3})
    mine = lambda key: FakeResponse(200, {"milestones": [{"seq": 2, "status": "submitted",  # noqa: E731
                                                          "deliverable": {"record": key}}]})
    ctx = FakeContext(answers=[FakeResponse(409, {"detail": "Milestone is no longer pending"}), mine("tpx-5")])
    out = await MilestoneEvidenceAction(cfg, ctx).perform({"photos": 3}, key="tpx-5", dry_run=False)
    assert out.status == "done" and "already delivered" in out.detail
    assert ctx.calls[0]["json"]["deliverable"] == {"evidence": {"photos": 3}, "record": "tpx-5", "proxy": "test-proxy"}
    ctx = FakeContext(answers=[FakeResponse(409, {"detail": "Milestone is no longer pending"}), mine("someone-else")])
    with pytest.raises(Refused, match="no longer pending"):
        await MilestoneEvidenceAction(cfg, ctx).perform({"photos": 3}, key="tpx-5", dry_run=False)


async def test_a_chat_message_or_card_is_posted_with_the_records_key_as_its_client_ref():
    from theprotocol.proxy.actions_builtin import ChatMessageAction
    cfg = {"conversation_id": "269dd5af-room"}
    out = await check_action(ChatMessageAction, cfg, {"body": "gate 4 closed"},
                             answers=[FakeResponse(201, {"id": "msg-1"})])
    assert out.reference == "msg-1"
    await check_action_refusals(ChatMessageAction, cfg, {"body": "x"})
    ctx = FakeContext(answers=[FakeResponse(201, {"id": "msg-2"})])
    card = {"type": "progress", "title": "Berth 4", "steps": []}
    await ChatMessageAction(cfg, ctx).perform({"card": card}, key="tpx-9", dry_run=False)
    assert ctx.calls[0]["json"] == {"kind": "card", "body": None, "card": card, "client_ref": "tpx-9"}
    assert ctx.calls[0]["path"] == "/api/v1/chat/conversations/269dd5af-room/messages"
    with pytest.raises(Refused, match="needs a body or a card"):
        await ChatMessageAction(cfg, FakeContext()).perform({}, key="k", dry_run=False)


def test_every_new_action_and_sink_is_a_built_in_that_keeps_the_interface():
    from theprotocol.proxy import plugins
    from theprotocol.proxy.testing import check_class
    for kind, names in (("action", ("a2a_task", "payment", "milestone_evidence", "chat_message")),
                        ("sink", ("webhook", "journal", "calendar", "email_digest", "evidence")),
                        ("source", ("theprotocol_events",))):
        for name in names:
            check_class(plugins.load(kind, name), kind)
    assert plugins.load("action", "payment").moves_value is True
    assert not any(plugins.load("action", n).moves_value for n in ("a2a_task", "milestone_evidence", "chat_message"))


async def test_a_payment_that_needs_the_owners_confirmation_waits_and_cites_it_on_the_retry():
    from theprotocol.proxy.actions_builtin import PaymentAction
    asked = []

    def answer(method, path, rec):
        if path.endswith("/authorize"):
            asked.append(rec["headers"].get("X-Presence-Proof"))
            if len(asked) == 1:
                return FakeResponse(403, {"detail": "Liability mandate required for 'a2a.pay' (presence_required:"
                                                    "no_proof); presence challenge lch_9f8e7d pushed: approve it"})
            return FakeResponse(200, {"token": "apt_" + "b" * 64, "token_id": "t-2"})
        return FakeResponse(200, {"token_id": "t-2", "status": "settled", "settlement_tx_id": "tx-2",
                                  "amount": "40", "currency": "ECU"})
    ctx = FakeContext(answers=answer)
    a = PaymentAction({**CFG, "max_amount": "45"}, ctx)
    with pytest.raises(Retry) as e:
        await a.perform({"amount": "40"}, key="tpx-big", dry_run=False)
    assert "challenge lch_9f8e7d" in e.value.detail and e.value.after == 30.0
    out = await a.perform({"amount": "40"}, key="tpx-big", dry_run=False)
    assert out.reference == "tx-2" and asked == [None, '{"method": "challenge", "challenge_id": "lch_9f8e7d"}']
    away = FakeResponse(403, {"detail": "Liability mandate required for 'a2a.pay' (presence_required:no_proof, "
                                        "human_away); no confirmation was minted"})
    with pytest.raises(Retry, match="nobody is at a desk"):
        await PaymentAction(CFG, FakeContext(answers=[away])).perform({"amount": "1"}, key="k", dry_run=False)
    plain = FakeResponse(403, {"detail": "Liability mandate required for 'a2a.pay' (over_mandate_max_per_tx:50)"})
    with pytest.raises(Refused, match="over_mandate_max_per_tx"):
        await PaymentAction(CFG, FakeContext(answers=[plain])).perform({"amount": "1"}, key="k", dry_run=False)
