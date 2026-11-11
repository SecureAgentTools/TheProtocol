"""The core's own actions: a signed fact (attestation), an A2A task (a2a_task), a payment under a Cockpit mandate
(payment), a contract milestone's evidence (milestone_evidence) and a chat message (chat_message). Each sends the
record's key as its Idempotency-Key and reads a repeat's answer as done; the first one is described here:

    actions:
      attest:
        type: attestation
        config:
          attestation_type: tos.gate_out     # what kind of fact (the registry keeps it with the attestation)
          target_agent_did: did:...          # whom the fact is about (default: the proxy's own agent)
          evidence_field: photo_url          # optional: a mapped field that is the evidence's address
        limits: {per_minute: 60}

The call is POST /api/v1/teg/attestations/submit as the proxy's agent, which needs the IRONKEY permission
reputation.signal (the `attestor` role carries it and nothing else). The ledger keeps a hash of the attestation's data;
the data is the mapped record plus the record's exactly-once key, so two records that say the same thing are two
attestations, and the same record sent again is the same one: the registry answers a repeat with its first answer
(the call's Idempotency-Key), and the ledger refuses a second copy of the same hash (409, "already submitted"), which
this action reads as done. The proxy's outbox keeps the data the hash commits to.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .plugins import Action, Outcome, PluginError, Refused, Retry
from .registry import retry_after

PATH = "/api/v1/teg/attestations/submit"


def _answer(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return {"text": (r.text or "")[:300]}


def _detail(body: Any) -> str:
    if isinstance(body, Mapping):
        d = body.get("detail") or body.get("title") or body.get("message")
        if isinstance(d, str):
            return d
        if d is not None:
            return str(d)[:300]
    return str(body)[:300]


class AttestationAction(Action):
    name = "attestation"
    description = "Submit one attestation per record: a signed fact on TheProtocol, its data hashed onto the ledger"
    needs = frozenset({"reputation.signal"})
    moves_value = False
    config_schema = {
        "type": "object",
        "required": ["attestation_type"],
        "additionalProperties": False,
        "properties": {
            "attestation_type": {"type": "string", "minLength": 1, "maxLength": 120},
            "target_agent_did": {"type": "string", "pattern": "^did:"},
            "evidence_field": {"type": "string", "minLength": 1},
        },
    }

    def request(self, mapped: Mapping[str, Any], key: str) -> dict:
        claim = dict(mapped)
        evidence = None
        field = self.config.get("evidence_field")
        if field:
            evidence = claim.pop(field, None)
        body = {
            "target_agent_did": self.config.get("target_agent_did") or self.ctx.agent_did,
            "attestation_type": self.config["attestation_type"],
            # the record's key is part of what is hashed: one attestation per record, never one per identical claim
            "attestation_data": {"claim": claim, "record": key},
            "metadata": {"proxy": self.ctx.proxy_name, "record": key},
        }
        if evidence:
            body["evidence_url"] = str(evidence)
        return body

    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        body = self.request(mapped, key)
        if dry_run:
            return Outcome.dry(f"would attest {body['attestation_type']} about {body['target_agent_did']}",
                               method="POST", path=PATH, request=body)
        r = await self.ctx.call("POST", PATH, json=body, idempotency_key=key)
        answer = _answer(r)
        st = r.status_code
        if st in (200, 201):
            ref = str(answer.get("attestation_id") or "") if isinstance(answer, Mapping) else ""
            return Outcome.done(ref, f"attested {body['attestation_type']}",
                                status=answer.get("status", "") if isinstance(answer, Mapping) else "")
        detail = _detail(answer)
        if st == 409 and "already submitted" in detail.lower():
            # the ledger holds this exact attestation (its hash includes this record's key): an earlier attempt landed
            return Outcome.done("", "already on the ledger: an earlier attempt of this record landed")
        if st in (408, 425, 429) or st >= 500:
            raise Retry(f"HTTP {st}: {detail}", after=retry_after(r), status=st)
        if st == 422 and "idempotency-key" in detail.lower() and "claimed" in detail.lower():
            # the registry still holds an earlier attempt's claim on this key: it frees itself, then answers
            raise Retry(f"HTTP {st}: {detail}", after=retry_after(r) or 30.0, status=st)
        raise Refused(f"HTTP {st}: {detail}", status=st, answer=answer)


# ── V0659 (c): an A2A task, a payment under a mandate, a milestone's evidence, a chat message ───────────────────────

def _status_error(r: Any, what: str) -> Exception:
    """The exception for a non-2xx answer: Retry for one that may change, Refused for one that will not."""
    st = r.status_code
    detail = _detail(_answer(r))
    if st in (408, 425, 429) or st >= 500:
        return Retry(f"{what}: HTTP {st}: {detail}", after=retry_after(r), status=st)
    return Refused(f"{what}: HTTP {st}: {detail}", status=st, answer=_answer(r))


def _decimal(v: Any, what: str):
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        raise Refused(f"the {what} {v!r} is not a number")
    if not d.is_finite():
        raise Refused(f"the {what} {v!r} is not a number")
    return d


class A2ATaskAction(Action):
    """A task for a named agent (A2A message/send), through the registry, for a FREE agent only: an agent that charges
    is refused here (pay it with the payment action, under a mandate). The message's messageId is the record's key."""
    name = "a2a_task"
    description = "Send a task to a named agent (A2A message/send) through the registry; free agents only"
    needs = frozenset({"a2a.pay"})          # what the registry's buy route asks of its caller, paid or free
    moves_value = False
    config_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "agent": {"type": "string", "pattern": "^did:"},
            "timeout_s": {"type": "number", "exclusiveMinimum": 0},
        },
    }
    PATH = "/api/v1/a2a-payment/buy"

    def request(self, mapped: Mapping[str, Any], key: str) -> dict:
        m = dict(mapped)
        agent = self.config.get("agent") or m.pop("agent", None)
        if not agent:
            raise Refused("an A2A task needs its agent: the config's agent, or a mapped field agent")
        text = m.pop("text", None)
        parts = [{"kind": "text", "text": str(text)}] if text is not None else []
        if m:
            parts.append({"kind": "data", "data": m})
        if not parts:
            raise Refused("an A2A task needs a text or data to send")
        payload = {"jsonrpc": "2.0", "id": key, "method": "message/send",
                   "params": {"message": {"role": "user", "messageId": key, "parts": parts}}}
        return {"target_agent_did": str(agent), "payload": payload, "settle": True, "free_only": True}

    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        body = self.request(mapped, key)
        if dry_run:
            return Outcome.dry(f"would send a task to {body['target_agent_did']}", method="POST", path=self.PATH,
                               request=body)
        r = await self.ctx.call("POST", self.PATH, json=body, idempotency_key=key)
        if r.status_code != 200:
            raise _status_error(r, "the task")
        ans = _answer(r)
        if isinstance(ans, Mapping) and ans.get("ok"):
            result = ans.get("result") or {}
            ref = ""
            if isinstance(result, Mapping):
                inner = result.get("result") if isinstance(result.get("result"), Mapping) else result
                ref = str(inner.get("id") or inner.get("taskId") or "")
            return Outcome.done(ref, f"the agent answered ({ans.get('stage')})", result=result)
        stage = (ans or {}).get("stage") if isinstance(ans, Mapping) else None
        err = (ans or {}).get("error") if isinstance(ans, Mapping) else str(ans)
        if stage in ("quoted", "authorized") or "charges" in str(err).lower():
            # nothing was sent to the agent: the agent cannot be reached this way (it charges, it has no card)
            raise Refused(f"the task was not sent: {err}", answer=ans)
        raise Retry(f"the agent did not deliver: {err}")


class PaymentAction(Action):
    """A payment authorization and its settle, ONLY under a Cockpit mandate. Every authorize names the mandate
    (X-Liability-Mandate), so the registry checks it for the call even where it runs liability off; the proxy's own
    limits (max_amount per payment, per_day) sit under the mandate's, and the action refuses to start while the agent
    has no IRONKEY spend cap or one above the mandate's limits."""
    name = "payment"
    description = "Authorize and settle a payment to an agent, under a Cockpit mandate and inside its limits"
    needs = frozenset({"a2a.pay"})
    moves_value = True
    config_schema = {
        "type": "object",
        "required": ["mandate", "max_amount"],
        "additionalProperties": False,
        "properties": {
            "mandate": {"type": "string", "pattern": "^lm_[A-Za-z0-9]+$"},
            "payee": {"type": "string", "pattern": "^did:"},
            "max_amount": {"type": ["number", "string"]},
            "per_day": {"type": ["number", "string"]},
            "ttl_seconds": {"type": "integer", "minimum": 60},
        },
    }
    AUTHORIZE, SETTLE = "/api/v1/a2a-payment/authorize", "/api/v1/a2a-payment/settle"

    @property
    def max_amount(self):
        return _decimal(self.config["max_amount"], "max_amount")

    @property
    def per_day(self):
        return _decimal(self.config["per_day"], "per_day") if self.config.get("per_day") is not None else None

    async def start(self) -> None:
        try:
            if self.max_amount <= 0:
                raise PluginError("the payment action's max_amount must be above 0")
        except Refused as e:
            raise PluginError(f"the payment action's {e.detail}") from None
        if self.ctx.dry_run:
            return
        await self.check_limits()

    async def check_limits(self) -> dict:
        """The mandate and the agent's spend cap, as the registry answers them; PluginError for what may not run."""
        mid = self.config["mandate"]
        r = await self.ctx.call("GET", f"/api/v1/liability/mandates/{mid}/for-agent")
        if r.status_code == 404 and _detail(_answer(r)).strip().lower() == "not found":
            raise PluginError("this registry cannot show an agent its mandate (the route is not there): a payment "
                              "action needs a registry from V0659 on")
        if r.status_code != 200:
            raise PluginError(f"the mandate {mid} is not this agent's to pay under (HTTP {r.status_code}): "
                              f"{_detail(_answer(r))}")
        m = _answer(r)
        if not m.get("valid") or "a2a.pay" not in (m.get("effective_scope") or []):
            raise PluginError(f"the mandate {mid} does not cover payments now: "
                              f"{', '.join(m.get('reasons') or []) or 'a2a.pay is not in its scope'}")
        limits = m.get("limits") or {}
        cap = _decimal(limits["max_per_tx"], "mandate max_per_tx") if limits.get("max_per_tx") is not None else None
        if cap is not None and self.max_amount > cap:
            raise PluginError(f"the payment action's max_amount {self.max_amount} is above the mandate's "
                              f"max_per_tx {cap}")
        a = await self.ctx.call("GET", "/api/v1/agents/me/authz")
        if a.status_code != 200:
            raise PluginError(f"the agent's spend cap cannot be read (HTTP {a.status_code}): {_detail(_answer(a))}")
        sp = (_answer(a) or {}).get("spend_policy") or {}
        per_tx, per_day = sp.get("max_per_tx"), sp.get("max_per_day")
        if per_tx is None and per_day is None:
            raise PluginError("the agent has no spend cap: its owner sets one (max_per_tx, max_per_day) before a proxy "
                              "pays, at or under the mandate's limits")
        if cap is not None and per_tx is not None and _decimal(per_tx, "spend max_per_tx") > cap:
            raise PluginError(f"the agent's spend cap max_per_tx {per_tx} is above the mandate's max_per_tx {cap}")
        if limits.get("currency") and sp.get("allowed_currencies") and \
                limits["currency"] not in sp["allowed_currencies"]:
            raise PluginError(f"the mandate is in {limits['currency']}, the agent may spend only "
                              f"{', '.join(sp['allowed_currencies'])}")
        return {"mandate": m, "spend_policy": sp}

    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        m = dict(mapped)
        payee = self.config.get("payee") or m.get("payee")
        if not payee:
            raise Refused("a payment needs its payee: the config's payee, or a mapped field payee")
        amount = _decimal(m.get("amount"), "amount")
        if amount <= 0:
            raise Refused(f"the amount {amount} is not above 0")
        if amount > self.max_amount:
            raise Refused(f"the amount {amount} is above the proxy's max_amount {self.max_amount}")
        body = {"target_agent_did": str(payee), "amount": str(amount),
                "ttl_seconds": int(self.config.get("ttl_seconds") or 900)}
        headers = {"X-Liability-Mandate": self.config["mandate"]}
        if dry_run:
            return Outcome.dry(f"would pay {amount} to {payee} under {self.config['mandate']}", method="POST",
                               path=self.AUTHORIZE, request=body, headers=headers)
        if self.per_day is not None:
            from datetime import datetime, timedelta, timezone
            day = datetime.now(timezone.utc).date().isoformat()
            spent = _decimal(await self.ctx.state.get(f"spent:{day}") or 0, "spent")
            if await self.ctx.state.get(f"paid:{key}") is None and spent + amount > self.per_day:
                tomorrow = datetime.combine(datetime.now(timezone.utc).date() + timedelta(days=1),
                                            datetime.min.time(), tzinfo=timezone.utc)
                raise Retry(f"the proxy's per_day {self.per_day} is reached ({spent} paid today)",
                            after=(tomorrow - datetime.now(timezone.utc)).total_seconds())
        chid = await self.ctx.state.get(f"presence:{key}")
        if chid:
            # the owner was asked to confirm this payment on their phone: the retry cites that challenge
            headers["X-Presence-Proof"] = json.dumps({"method": "challenge", "challenge_id": chid})
        r = await self.ctx.call("POST", self.AUTHORIZE, json=body, idempotency_key=key, headers=headers)
        if r.status_code == 403:
            detail = _detail(_answer(r))
            m = re.search(r"presence challenge (lch_[A-Za-z0-9]+) pushed", detail)
            if m:
                await self.ctx.state.set(f"presence:{key}", m.group(1))
                raise Retry(f"waiting for the owner to confirm the payment on their phone (challenge {m.group(1)})",
                            after=30.0, status=403)
            if "human_away" in detail:
                raise Retry("the payment needs the owner's confirmation and nobody is at a desk or phone now",
                            after=120.0, status=403)
        if r.status_code != 200:
            raise _status_error(r, "the authorization")
        auth = _answer(r)
        s = await self.ctx.call("POST", self.SETTLE, json={"token": auth.get("token"), "task_id": key,
                                                           "success": True}, idempotency_key=key)
        if s.status_code != 200:
            raise _status_error(s, "the settlement")
        st = _answer(s)
        if self.per_day is not None and await self.ctx.state.get(f"paid:{key}") is None:
            from datetime import datetime, timezone
            day = datetime.now(timezone.utc).date().isoformat()
            spent = _decimal(await self.ctx.state.get(f"spent:{day}") or 0, "spent")
            await self.ctx.state.set(f"spent:{day}", str(spent + amount))
            await self.ctx.state.set(f"paid:{key}", day)
        return Outcome.done(str(st.get("settlement_tx_id") or st.get("token_id") or ""),
                            f"paid {st.get('amount')} {st.get('currency')} to {payee}",
                            token_id=st.get("token_id") or auth.get("token_id"), status=st.get("status"),
                            amount=st.get("amount"), currency=st.get("currency"))


class MilestoneEvidenceAction(Action):
    """A contract milestone's evidence, delivered by the provider (the proxy's agent). The deliverable carries the
    record's key, so a delivery repeated after a lost answer is recognised in the contract and taken as done."""
    name = "milestone_evidence"
    description = "Deliver a contract milestone with the record as its evidence (the provider's submit)"
    needs = frozenset()
    moves_value = False
    config_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"contract_id": {"type": "string", "minLength": 1}, "seq": {"type": "integer", "minimum": 0}},
    }

    def target(self, mapped: Mapping[str, Any]) -> tuple:
        m = dict(mapped)
        cid = self.config.get("contract_id") or m.pop("contract_id", None)
        seq = self.config.get("seq") if self.config.get("seq") is not None else m.pop("seq", None)
        m.pop("contract_id", None)
        m.pop("seq", None)
        if not cid or seq is None:
            raise Refused("a milestone needs its contract_id and seq (the config's, or mapped fields)")
        return str(cid), int(seq), m

    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        cid, seq, evidence = self.target(mapped)
        path = f"/api/v1/contracts/v2/{cid}/milestones/{seq}/submit"
        body = {"deliverable": {"evidence": evidence, "record": key, "proxy": self.ctx.proxy_name}}
        if dry_run:
            return Outcome.dry(f"would deliver milestone {seq} of {cid}", method="POST", path=path, request=body)
        r = await self.ctx.call("POST", path, json=body, idempotency_key=key)
        if r.status_code == 200:
            return Outcome.done(f"{cid}#{seq}", "delivered")
        if r.status_code == 409:
            g = await self.ctx.call("GET", f"/api/v1/contracts/v2/{cid}")
            doc = _answer(g) if g.status_code == 200 else {}
            for ms in (doc.get("milestones") or []) if isinstance(doc, Mapping) else []:
                if int(ms.get("seq", -1)) == seq and ((ms.get("deliverable") or {}).get("record") == key):
                    return Outcome.done(f"{cid}#{seq}", "already delivered: an earlier attempt of this record landed")
        raise _status_error(r, f"milestone {seq} of {cid}")


class ChatMessageAction(Action):
    """A message (text, or a card from the chat's closed vocabulary) into a thread or room the proxy's agent is in.
    Its client_ref is the record's key, so a repeat is the same message."""
    name = "chat_message"
    description = "Post a message or a card into a chat thread or room (idempotent on the record's key)"
    needs = frozenset()
    moves_value = False
    config_schema = {
        "type": "object",
        "required": ["conversation_id"],
        "additionalProperties": False,
        "properties": {"conversation_id": {"type": "string", "minLength": 8}},
    }

    async def perform(self, mapped: Mapping[str, Any], *, key: str, dry_run: bool) -> Outcome:
        m = dict(mapped)
        card = m.get("card")
        if card is not None and not isinstance(card, Mapping):
            raise Refused("a mapped card is an object with its type")
        body = {"kind": "card" if card else "text", "body": str(m["body"]) if m.get("body") is not None else None,
                "card": dict(card) if card else None, "client_ref": key}
        if not body["card"] and not body["body"]:
            raise Refused("a chat message needs a body or a card")
        path = f"/api/v1/chat/conversations/{self.config['conversation_id']}/messages"
        if dry_run:
            return Outcome.dry("would post to the conversation", method="POST", path=path, request=body)
        r = await self.ctx.call("POST", path, json=body, idempotency_key=key)
        if r.status_code in (200, 201):
            ans = _answer(r)
            return Outcome.done(str((ans or {}).get("id") or (ans or {}).get("message_id") or "")
                                if isinstance(ans, Mapping) else "", "posted")
        raise _status_error(r, "the message")
