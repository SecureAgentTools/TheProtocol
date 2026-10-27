"""§FRAMEFORM rebuild (his word 2026-09-13: the request form "needs complete rework ... no advanced settings"): the rail
behind the public frame request form.

The body keeps every existing client valid (the old form and the MCP tool post the legacy minimal shape) while a new
request maps into a spec the host frame runner can provision; `answers` takes five known groups, each shape-checked and
stored normalized, never a blob store; the commander notice reads every group; the admin review router is
admin_federation behind the mainframe gate and refuses a status filter or a review field it does not know.
No database and no mail: a fake session and a captured mailer stand in.
"""
import datetime
import json
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentvault_registry import models, security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import frame_requests as review
from agentvault_registry.routers import operator_self_service as oss

LEGACY = {"accept_terms": True,  # §LEGALKIT: the applicant accepts the Terms and the Operator Terms (the form and the tool send it)
    "organization": "Sovereign Org GmbH", "contact_name": "Ada Lovelace", "email": "ada@org.example",
          "trust_domain": "frame-x.org.example", "pair_with": "frame-a",
          "use_case": "Our regulator requires identity issuance inside our jurisdiction.",
          "notes": "Timeline: Q4.", "create_account": False}

FULL = {"accept_terms": True,  # §LEGALKIT: the applicant accepts the Terms and the Operator Terms (the form and the tool send it)
    
    "organization": "Acme Logistics AG", "contact_name": "Grace Hopper", "email": "grace@acme.example",
    "use_case": "Cross-border freight agents need their own treasury and identity root.",
    "frame_name": "acme-frame", "display_name": "Acme Sovereign Frame", "ticker": "ACME", "currency_name": "Acme Unit",
    "federation_choice": "A",
    "answers": {
        "features": {"guild": "no", "agent_permissions": "enforce"},
        "treasury": {"mint": "2500000", "genesis_grant": 1000},
        "card": {"description": " A logistics frame. ", "website": "https://acme.example", "location": "Munich, Bavaria",
                 "lat": 48.14, "lng": 11.58, "tags": "robotics, eu , logistics, eu", "theme": "sovereign"},
        "network": {"intent": "federate_later", "partners": ["eu", "asia", "eu"]},
        "provisioning": {"hosting": "theprotocol", "posture": "pilot", "operators": 2},
    },
}
NOW = datetime.datetime(2026, 9, 13, 9, 0, tzinfo=datetime.timezone.utc)
REQUEST_ID = "11111111-2222-3333-4444-555555555555"
BASE = "/api/v1/admin/frame-requests"


def body(**changes):
    return oss.FrameRequestBody.model_validate({**LEGACY, **changes})


# ---- the body and its answers contract ---------------------------------------------------------------------------------

def test_the_full_request_is_accepted_and_normalized_as_stored():
    b = oss.FrameRequestBody.model_validate(FULL)
    a = b.answers.normalized()
    assert set(a) == {"features", "treasury", "card", "network", "provisioning"}
    # §FESUITE V0595: the features are checked against the configuration catalog (services/env_catalog.py), where agent
    # permissions and delegation move together (PART 14's pairing rule): a request naming one half takes its partner
    assert a["features"] == {"guild": "no", "agent_permissions": "enforce", "delegation": "enforce"}
    assert a["treasury"] == {"mint": "2500000", "genesis_grant": "1000"}
    assert a["card"] == {"description": "A logistics frame.", "website": "https://acme.example",
                         "location": "Munich, Bavaria", "lat": 48.14, "lng": 11.58,
                         "tags": ["robotics", "eu", "logistics"], "theme": "sovereign"}
    assert a["network"] == {"intent": "federate_later", "partners": ["eu", "asia"]}
    assert a["provisioning"] == {"hosting": "theprotocol", "posture": "pilot", "operators": 2}
    assert b.pair_with is None and b.trust_domain is None


def test_the_legacy_minimal_request_of_the_old_form_and_the_mcp_tool_still_validates():
    b = body()
    assert b.pair_with == "frame-a" and b.answers.normalized() == {}
    bare = oss.FrameRequestBody.model_validate({k: v for k, v in LEGACY.items() if k not in ("pair_with", "trust_domain")})
    assert bare.pair_with is None and bare.trust_domain is None and bare.answers.normalized() == {}
    # empty groups still mean "defaults everywhere"
    assert body(answers={"features": {}, "card": {"website": "", "tags": ""}}).answers.normalized() == {}


def test_a_page_loaded_before_v0364_that_still_sends_sandbox_is_stored_as_pilot():
    # V0364 calls the first stage "pilot"; a V0363 page still open in a browser sends "sandbox"
    assert body(answers={"provisioning": {"posture": "sandbox"}}).answers.normalized() == {"provisioning": {"posture": "pilot"}}
    assert body(answers={"provisioning": {"posture": "production"}}).answers.normalized() == {"provisioning": {"posture": "production"}}
    for word in ("Sandbox", "SANDBOX", " sandbox"):
        with pytest.raises(ValidationError):
            body(answers={"provisioning": {"posture": word}})


@pytest.mark.parametrize("slug", ["Acme", "acme-", "ab", "a" * 32, "1acme", "acme_frame"])
def test_a_frame_name_the_runner_could_not_provision_is_refused(slug):
    with pytest.raises(ValidationError):
        body(frame_name=slug)


@pytest.mark.parametrize("slug", ["abc", "a" * 31, "acme-frame-2"])
def test_a_provisionable_frame_name_passes(slug):
    assert body(frame_name=slug).frame_name == slug


def test_a_ticker_label_or_currency_name_longer_than_the_runner_takes_is_refused():
    with pytest.raises(ValidationError):
        body(ticker="ABCDEFG")
    with pytest.raises(ValidationError):
        body(display_name="x" * 61)
    with pytest.raises(ValidationError):
        body(currency_name="x" * 41)
    assert body(ticker="ABCDEF").ticker == "ABCDEF"


def test_an_unknown_answers_group_is_refused_naming_the_known_ones():
    with pytest.raises(ValidationError) as exc:
        body(answers={"features": {"guild": "no"}, "blob": {"x": "y"}})
    text = str(exc.value)
    assert "blob" in text and all(group in text for group in oss.FRAME_ANSWER_GROUPS)


def test_an_unknown_field_inside_a_group_is_refused():
    with pytest.raises(ValidationError):
        body(answers={"card": {"logo": "https://acme.example/logo.png"}})


def test_an_oversized_answers_payload_is_refused():
    with pytest.raises(ValidationError) as exc:
        body(answers={"card": {"description": "x" * 9000}})
    assert "8 KB" in str(exc.value)


def test_a_coordinate_alone_or_out_of_range_is_refused_and_a_pair_passes():
    for card in ({"lat": 48.1}, {"lng": 11.5}, {"lat": 91, "lng": 0}, {"lat": True, "lng": 0}, {"lat": "48", "lng": 11}):
        with pytest.raises(ValidationError):
            body(answers={"card": card})
    assert body(answers={"card": {"lat": 0, "lng": 0}}).answers.normalized()["card"] == {"lat": 0.0, "lng": 0.0}


@pytest.mark.parametrize("site", ["http://acme.example", "https://acme example.org", "ftp://acme.example", "https://"])
def test_a_website_that_is_not_https_is_refused(site):
    with pytest.raises(ValidationError):
        body(answers={"card": {"website": site}})


def test_tags_given_as_one_string_are_split_trimmed_and_bounded():
    assert body(answers={"card": {"tags": " a, b ,,c "}}).answers.normalized()["card"]["tags"] == ["a", "b", "c"]
    with pytest.raises(ValidationError):
        body(answers={"card": {"tags": ",".join(f"t{i}" for i in range(9))}})
    with pytest.raises(ValidationError):
        body(answers={"card": {"tags": ["x" * 25]}})


@pytest.mark.parametrize("answers", [
    {"treasury": {"mint": "0"}}, {"treasury": {"mint": "1e6"}}, {"treasury": {"mint": 1000000001}},
    {"treasury": {"genesis_grant": "-5"}}, {"treasury": {"mint": True}},
    {"features": {"Guild": "no"}}, {"features": {"guild": "<b>no</b>"}}, {"features": {"guild": 1}},
    {"features": {f"switch_{'x' * i}": "no" for i in range(41)}},
    {"network": {"intent": "federate_now"}}, {"network": {"partners": ["eu; drop"]}},
    {"network": {"partners": [f"f{i}" for i in range(9)]}},
    {"provisioning": {"operators": 5}}, {"provisioning": {"operators": "2"}}, {"provisioning": {"hosting": "aws"}},
    {"provisioning": {"posture": "live"}}, {"card": {"theme": "pink"}}, {"card": "not an object"},
])
def test_each_group_refuses_what_its_contract_does_not_take(answers):
    with pytest.raises(ValidationError):
        body(answers=answers)


def test_the_commander_summary_reads_every_group():
    line = oss._summarise_frame_answers(oss.FrameRequestBody.model_validate(FULL).answers.normalized())
    for part in ("card: description=A logistics frame., lat=48.14, lng=11.58, location=Munich, Bavaria, "
                 "tags=[robotics, eu, logistics], theme=sovereign, website=https://acme.example",
                 "features: agent_permissions=enforce, delegation=enforce, guild=no",
                 "network: intent=federate_later, partners=[eu, asia]",
                 "provisioning: hosting=theprotocol, operators=2, posture=pilot",
                 "treasury: genesis_grant=1000, mint=2500000"):
        assert part in line, line
    assert oss._summarise_frame_answers({}) == "defaults everywhere"
    assert oss._summarise_frame_answers({"features": {}}) == "defaults everywhere"


# ---- the public submit, through the route --------------------------------------------------------------------------------

class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value[0] if isinstance(self.value, list) else self.value

    def all(self):
        return self.value if isinstance(self.value, list) else ([] if self.value is None else [self.value])

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    """Answers each execute() with the next queued value; records the statements, the rows added and the commits."""

    def __init__(self, *answers):
        self.answers, self.statements, self.added, self.commits = list(answers), [], [], 0

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.answers.pop(0) if self.answers else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):  # §LEGALKIT: the rail flushes before it records the acceptance beside the row
        self.flushed = getattr(self, 'flushed', 0) + 1

    async def rollback(self):
        pass

    async def refresh(self, obj):
        pass


def _submit_app(monkeypatch, session, redis=None):
    mails = []
    monkeypatch.setattr(oss, "_send_frame_notification_email", lambda **kw: mails.append(kw))

    async def _redis():      # the receipt budget's counter; None is a node without Redis, which sends no receipt
        return redis

    monkeypatch.setattr(leader, "get_redis", _redis)
    app = FastAPI()
    app.include_router(oss.router)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    return TestClient(app), mails


def test_a_full_request_is_stored_normalized_and_the_commander_notice_reads_it(monkeypatch):
    session = FakeSession(None, None)          # no pending duplicate, no developer with that email
    http, mails = _submit_app(monkeypatch, session)
    r = http.post("/api/v1/operators/request-frame", json=FULL)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert set(doc) == {"submitted", "account_created", "magic_link_sent", "receipt_sent", "review_eta", "request_id"}
    row = session.added[0]
    assert isinstance(row, models.FrameRequest) and doc["request_id"] == row.id and session.commits == 1
    assert row.answers == oss.FrameRequestBody.model_validate(FULL).answers.normalized()
    assert row.frame_name == "acme-frame" and row.ticker == "ACME"
    assert len(mails) == 1
    rows = dict(mails[0]["context"]["rows"])
    assert "Pair with" not in rows
    assert rows["Hosting"] == "we host it" and rows["Posture"] == "pilot, 2 operator(s)"
    assert rows["Theme"] == "sovereign" and rows["Location"] == "Munich, Bavaria (48.14, 11.58)"
    assert rows["Partners (later, bilateral)"] == "eu, asia"
    assert rows["Federation"] == "federated · federate later, bilateral"
    assert rows["Currency"] == "ACME (Acme Unit)" and rows["Request id"] == row.id
    assert mails[0]["context"]["headline_text"] == "Acme Logistics AG → Acme Sovereign Frame"


def test_a_legacy_request_keeps_its_pairing_row_and_stores_empty_answers(monkeypatch):
    session = FakeSession(None, None)
    http, mails = _submit_app(monkeypatch, session)
    r = http.post("/api/v1/operators/request-frame", json=LEGACY)
    assert r.status_code == 200, r.text
    rows = dict(mails[0]["context"]["rows"])
    assert rows["Pair with"] == "frame-a" and rows["Changed"] == "defaults everywhere"
    assert rows["Hosting"] == "not given" and rows["Partners (later, bilateral)"] == "none named"
    assert session.added[0].answers == {} and r.json()["request_id"] == session.added[0].id


def test_a_malformed_request_is_refused_before_anything_is_stored_or_mailed(monkeypatch):
    session = FakeSession()
    http, mails = _submit_app(monkeypatch, session)
    r = http.post("/api/v1/operators/request-frame", json={**FULL, "answers": {"blob": {}}})
    assert r.status_code == 422 and session.statements == [] and mails == []


# ---- the requester hears back once (his word 2026-09-14: every requester gets a receipt) --------------------------------

class FakeRedis:
    """incr, expire and ttl: enough to count a budget."""

    def __init__(self):
        self.counts, self.ttls = {}, {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds

    async def ttl(self, key):
        return self.ttls.get(key, -1)


def _submit(monkeypatch, redis, payload, *answers):
    session = FakeSession(*answers)
    http, mails = _submit_app(monkeypatch, session, redis=redis)
    r = http.post("/api/v1/operators/request-frame", json=payload)
    assert r.status_code == 200, r.text
    return r.json(), mails, session


def test_a_request_gets_one_receipt_that_says_only_what_we_wrote(monkeypatch):
    doc, mails, session = _submit(monkeypatch, FakeRedis(), FULL, None, None)
    assert doc["receipt_sent"] is True and doc["magic_link_sent"] is False and len(mails) == 2
    notice, receipt = mails
    assert "to_address" not in notice and receipt["to_address"] == FULL["email"]
    rows = dict(receipt["context"]["rows"])
    assert rows["Request id"] == session.added[0].id == doc["request_id"] and rows["Frame name"] == "acme-frame"
    said = json.dumps(receipt, default=str)
    for written in (FULL["organization"], FULL["contact_name"], FULL["use_case"], FULL["display_name"],
                    FULL["currency_name"], "Munich"):
        assert written not in said, written


def test_a_repeat_while_the_request_is_pending_mails_no_second_receipt(monkeypatch):
    doc, mails, session = _submit(monkeypatch, FakeRedis(), FULL, _row())
    assert doc["request_id"] == REQUEST_ID and doc["receipt_sent"] is False
    assert len(mails) == 1 and "to_address" not in mails[0] and session.added == []


def test_an_account_request_gets_the_welcome_instead_and_it_links_the_console(monkeypatch):
    monkeypatch.setenv("PUBLIC_UI_URL", "https://console.example")
    monkeypatch.setattr(oss.security, "hash_password", lambda password: "hashed")
    doc, mails, _ = _submit(monkeypatch, FakeRedis(), {**FULL, "create_account": True}, None, None, None, None)
    assert (doc["account_created"], doc["magic_link_sent"], doc["receipt_sent"]) == (True, True, False)
    assert len(mails) == 2 and mails[1]["to_address"] == FULL["email"]
    text = mails[1]["context"]["body_text"]
    assert "https://console.example/#/reset-password?token=" in text and "api.theprotocol.cloud" not in text


def test_the_receipt_budget_holds_per_source_and_per_hour_and_no_counter_means_no_receipt(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setenv("FRAME_REQUEST_RECEIPTS_PER_SOURCE_PER_HOUR", "2")
    sent = []
    for i in range(3):
        doc, mails, _ = _submit(monkeypatch, redis, {**FULL, "email": f"person{i}@acme.example"}, None, None)
        sent.append(doc["receipt_sent"])
        assert len(mails) == (2 if doc["receipt_sent"] else 1)      # the commander's notice goes out either way
    assert sent == [True, True, False] and set(redis.ttls.values()) == {3600}
    monkeypatch.setenv("FRAME_REQUEST_RECEIPTS_PER_SOURCE_PER_HOUR", "10")
    monkeypatch.setenv("FRAME_REQUEST_RECEIPTS_PER_HOUR", "2")
    doc, mails, _ = _submit(monkeypatch, redis, {**FULL, "email": "fourth@acme.example"}, None, None)
    assert doc["receipt_sent"] is False and len(mails) == 1          # the hour's budget of 2 is spent
    doc, mails, session = _submit(monkeypatch, None, {**FULL, "email": "late@acme.example"}, None, None)
    assert doc["receipt_sent"] is False and len(mails) == 1 and session.commits == 1


# ---- the admin review router ---------------------------------------------------------------------------------------------

def _row(**changes):
    values = dict(id=REQUEST_ID, status="pending", contact_name="Grace Hopper", contact_email="grace@acme.example",
                  organization="Acme Logistics AG", frame_name="acme-frame", display_name="Acme Sovereign Frame",
                  ticker="ACME", currency_name="Acme Unit", answers={}, created_at=NOW, updated_at=NOW)
    values.update(changes)
    return models.FrameRequest(**values)


def _review_app(session, is_admin=False, **flags):
    """The router alone; the REAL admin_federation gate runs against this developer."""
    developer = types.SimpleNamespace(id=7, email="ops@example.test", is_admin=is_admin, must_change_password=False,
                                      **flags)
    app = FastAPI()
    app.include_router(review.router)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: developer
    return TestClient(app)


@pytest.mark.parametrize("flags", [{}, {"admin_platform": True}, {"admin_support": True}])
def test_the_review_rail_refuses_a_developer_without_admin_federation(flags):
    session = FakeSession(_row())
    http = _review_app(session, **flags)
    assert http.get(BASE).status_code == 403
    assert http.get(f"{BASE}/{REQUEST_ID}").status_code == 403
    assert http.patch(f"{BASE}/{REQUEST_ID}", json={"status": "reviewed"}).status_code == 403
    assert session.statements == [] and session.commits == 0


def test_the_review_rail_lists_reads_and_reviews_with_admin_federation():
    row = _row()
    session = FakeSession([row], [row], row, None, row)
    http = _review_app(session, admin_federation=True)
    r = http.get(BASE)
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [REQUEST_ID]
    assert "WHERE" not in str(session.statements[-1])
    r = http.get(BASE, params={"status": "pending"})
    assert r.status_code == 200 and "WHERE frame_requests.status" in str(session.statements[-1])
    assert http.get(f"{BASE}/{REQUEST_ID}").json()["frame_name"] == "acme-frame"
    assert http.get(f"{BASE}/unknown").status_code == 404
    r = http.patch(f"{BASE}/{REQUEST_ID}", json={"status": "reviewed", "review_notes": "looks right"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reviewed" and r.json()["reviewed_by"] == 7 and session.commits == 1


def test_a_superadmin_passes_the_review_gate():
    session = FakeSession([_row()])
    assert _review_app(session, is_admin=True).get(BASE).status_code == 200


def test_an_unknown_status_filter_is_refused_not_answered_empty():
    session = FakeSession([_row()])
    http = _review_app(session, admin_federation=True)
    r = http.get(BASE, params={"status": "accepted"})   # §HELLOFRAME made "approved" a real status (self-hosted, the kit)
    assert r.status_code == 422 and session.statements == []


def test_a_review_with_a_field_or_status_it_does_not_know_is_refused():
    session = FakeSession(_row(), _row())
    http = _review_app(session, admin_federation=True)
    assert http.patch(f"{BASE}/{REQUEST_ID}", json={"status": "reviewed", "frame_name": "other"}).status_code == 422
    assert http.patch(f"{BASE}/{REQUEST_ID}", json={"status": "accepted"}).status_code == 422
    assert session.commits == 0


def test_a_request_without_the_acceptance_is_refused_and_says_why(monkeypatch):
    """§LEGALKIT control: the rail records an acceptance for every request, so a body without it is a 422 that names
    the two documents, and nothing is stored (Operator Terms § 1.2, Terms § 1.4)."""
    session = FakeSession(None, None)
    http, mails = _submit_app(monkeypatch, session)
    body_no = {k: v for k, v in FULL.items() if k != "accept_terms"}
    r = http.post("/api/v1/operators/request-frame", json=body_no)
    assert r.status_code == 422, r.text
    assert "Terms of Service" in r.text and "Federation Operator Terms" in r.text
    assert session.added == [] and session.commits == 0 and mails == []
    # and the accepted request records BOTH documents beside the row, in the same transaction
    session2 = FakeSession(None, None)
    http2, _ = _submit_app(monkeypatch, session2)
    r2 = http2.post("/api/v1/operators/request-frame", json=FULL)
    assert r2.status_code == 200, r2.text
    docs = sorted(getattr(a, "document", "") for a in session2.added if type(a).__name__ == "LegalAcceptance")
    assert docs == ["operators", "terms"] and session2.commits == 1
