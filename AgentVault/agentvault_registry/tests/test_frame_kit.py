"""§HELLOFRAME (his word 2026-09-19: "build it behind the flag, off by default"): the frame kit rail.

The applicant's page lists only their own requests (by id, or by a VERIFIED email), each with a download window whose
state names the reason it is closed; the kit is the file a manifest names, served only when its size matches; a
download goes through a single-use link that works once and counts once; the whole rail answers 404 while the flag is
off; approving is for a self-hosted request and opens a new window. No database, no Redis, no mail: fakes stand in.
"""
import asyncio
import datetime
import hashlib
import json
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from agentvault_registry import models, security
from agentvault_registry.core.mainframe_gate import require_mainframe_only
from agentvault_registry.database import get_db
from agentvault_registry.routers import frame_kit as fk
from agentvault_registry.routers import frame_requests as review

UTC = datetime.timezone.utc
# The clock the app reads, not a date: the kit's routes take datetime.now() while the rows here are built from NOW,
# so a fixed NOW (2026-09-19 09:00Z) let the 30-day window close at 2026-10-18 09:00Z and four app-path tests read
# "expired" in every CI run after it (agentvault2-5b, 2026-10-18). Every age below is relative to NOW.
NOW = datetime.datetime.now(UTC).replace(microsecond=0)
RID = "11111111-2222-3333-4444-555555555555"


def row(**changes):
    values = dict(id=RID, status="pending", contact_name="Ada Lovelace", contact_email="Ada@Org.example",
                  organization="Northwind", frame_name="northwind", display_name="Northwind Frame",
                  hostname="frame.northwind.example", trust_domain="frame.northwind.example", ticker="NWD",
                  currency_name="Northwind Unit", developer_id=None, reviewed_at=None,
                  answers={"provisioning": {"hosting": "self", "posture": "production"},
                           "card": {"location": "Lisbon", "lat": "38.72", "lng": -9.14, "theme": "neural"}},
                  created_at=NOW - datetime.timedelta(days=3), updated_at=NOW,
                  kit_approved_at=None, kit_download_count=0, kit_last_download_at=None)
    values.update(changes)
    return models.FrameRequest(**values)


def approved(**changes):
    changes.setdefault("status", "approved")
    changes.setdefault("kit_approved_at", NOW - datetime.timedelta(days=1))
    return row(**changes)


def dev(**changes):
    values = dict(id=42, email="ada@org.example", is_verified=True, is_admin=False, must_change_password=False)
    values.update(changes)
    return types.SimpleNamespace(**values)


def publish(tmp_path, size=None, **manifest):
    body = b"a kit" * 20
    (tmp_path / "theprotocol-frame-kit-1.0.0.tar.gz").write_bytes(body)
    doc = {"name": "theprotocol-frame-kit", "version": "1.0.0", "filename": "theprotocol-frame-kit-1.0.0.tar.gz",
           "size_bytes": len(body) if size is None else size, "sha256": hashlib.sha256(body).hexdigest(),
           "published_at": "2026-09-19T08:00:00Z"}
    doc.update(manifest)
    (tmp_path / "manifest.json").write_text(json.dumps(doc))
    return body


# ── the published kit ───────────────────────────────────────────────────────────────────────────────────────────────

def test_a_published_kit_is_read_from_its_manifest(tmp_path):
    body = publish(tmp_path)
    release, why = fk.load_release(tmp_path)
    assert why == "" and release["filename"] == "theprotocol-frame-kit-1.0.0.tar.gz"
    assert release["size_bytes"] == len(body) and release["sha256"] == hashlib.sha256(body).hexdigest()
    assert release["top_dir"] == "theprotocol-frame-kit-1.0.0" and "path" not in fk.public_release(release)


@pytest.mark.parametrize("manifest,reason", [
    ({"filename": "../etc/passwd.tar.gz"}, "no plain .tar.gz"),
    ({"filename": "kit.zip"}, "no plain .tar.gz"),
    ({"sha256": "abc"}, "no sha256"),
    ({"size_bytes": "many"}, "no size"),
    ({"filename": "other-1.0.0.tar.gz"}, "not on this frame"),
])
def test_a_manifest_that_is_not_a_kit_is_refused_with_its_reason(tmp_path, manifest, reason):
    publish(tmp_path, **manifest)
    release, why = fk.load_release(tmp_path)
    assert release is None and reason in why


def test_a_kit_cut_short_is_not_served_and_nothing_published_says_so(tmp_path):
    publish(tmp_path, size=10_000)
    assert fk.load_release(tmp_path) == (None, "the kit file's size does not match its manifest")
    assert fk.load_release(tmp_path / "empty")[1] == "no kit is published on this frame yet"


# ── the window and the progress ─────────────────────────────────────────────────────────────────────────────────────

RELEASE = {"filename": "k.tar.gz"}


@pytest.mark.parametrize("r,release,state", [
    (row(answers={"provisioning": {"hosting": "theprotocol"}}), RELEASE, "not_self_hosted"),
    (row(answers={}), RELEASE, "not_self_hosted"),
    (row(status="rejected"), RELEASE, "rejected"),
    (row(status="pending"), RELEASE, "locked"),
    (row(status="reviewed"), RELEASE, "locked"),
    (row(status="approved", kit_approved_at=None), RELEASE, "locked"),
    (approved(kit_approved_at=NOW - datetime.timedelta(days=31)), RELEASE, "expired"),
    (approved(kit_download_count=5), RELEASE, "exhausted"),
    (approved(), None, "unpublished"),
    (approved(), RELEASE, "ready"),
    (approved(status="provisioned"), RELEASE, "ready"),
])
def test_the_window_names_the_reason_it_is_closed(r, release, state):
    w = fk.kit_window(r, release, NOW, days=30, limit=5)
    assert w["state"] == state
    assert (w["sentence"] is None) == (state == "ready")


def test_an_expired_window_outranks_an_unpublished_kit_and_counts_are_reported():
    w = fk.kit_window(approved(kit_approved_at=NOW - datetime.timedelta(days=40), kit_download_count=2), None, NOW, days=30, limit=5)
    assert w["state"] == "expired" and w["downloads_used"] == 2 and w["downloads_max"] == 5
    assert w["available_until"] == NOW - datetime.timedelta(days=10)


def _states(steps):
    return [(s["key"], s["state"]) for s in steps]


def test_a_self_hosted_request_walks_to_federated():
    assert _states(fk.progress(row())) == [("requested", "done"), ("approved", "current"), ("downloaded", "ahead"),
                                           ("invited", "ahead"), ("federated", "ahead")]
    got = approved(kit_last_download_at=NOW)
    pending_inv = types.SimpleNamespace(status="pending", created_at=NOW, completed_at=None)
    assert _states(fk.progress(got, pending_inv)) == [("requested", "done"), ("approved", "done"), ("downloaded", "done"),
                                                      ("invited", "done"), ("federated", "current")]
    done_inv = types.SimpleNamespace(status="completed", created_at=NOW, completed_at=NOW)
    steps = fk.progress(got, done_inv)
    assert all(s["state"] == "done" for s in steps) and steps[-1]["at"] == NOW


def test_a_hosted_request_and_a_declined_one_have_their_own_paths():
    hosted = row(status="reviewed", reviewed_at=NOW, answers={"provisioning": {"hosting": "theprotocol"}})
    assert _states(fk.progress(hosted)) == [("requested", "done"), ("reviewed", "done"), ("provisioned", "current")]
    assert _states(fk.progress(row(status="rejected", reviewed_at=NOW))) == [("requested", "done"), ("declined", "declined")]


def test_the_invitation_that_speaks_for_a_domain_is_the_completed_one():
    a = types.SimpleNamespace(initiator_trust_domain="Frame.Northwind.example", status="completed", created_at=NOW - datetime.timedelta(days=2))
    b = types.SimpleNamespace(initiator_trust_domain="frame.northwind.example", status="pending", created_at=NOW)
    assert fk.pick_invitations([b, a]) == {"frame.northwind.example": a}


# ── ownership ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_request_belongs_to_its_developer_id_or_to_a_verified_matching_email():
    assert fk.is_owner(row(developer_id=42), dev(email="someone@else.example"))
    assert fk.is_owner(row(), dev())                                  # case-insensitive email, verified
    assert not fk.is_owner(row(), dev(is_verified=False))             # an unverified address proves nothing
    assert not fk.is_owner(row(developer_id=7), dev(email="x@y.example"))


def test_the_owner_clause_asks_for_the_email_only_when_it_is_verified():
    sql = lambda d: str(fk.owner_clause(d).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "lower(frame_requests.contact_email) = 'ada@org.example'" in sql(dev())
    assert "contact_email" not in sql(dev(is_verified=False)) and "frame_requests.developer_id = 42" in sql(dev(is_verified=False))


# ── the routes ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value[0] if isinstance(self.value, list) else self.value

    def all(self):
        return self.value if isinstance(self.value, list) else ([] if self.value is None else [self.value])


class FakeSession:
    def __init__(self, *answers, developers=None):
        self.answers, self.statements, self.commits = list(answers), [], 0
        self.developers = developers or {}

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.answers.pop(0) if self.answers else None)

    async def get(self, model, key):
        return self.developers.get(key)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


class FakeRedis:
    def __init__(self):
        self.data, self.ttls = {}, {}

    async def set(self, key, value, ex=None):
        self.data[key], self.ttls[key] = value, ex

    async def getdel(self, key):
        return self.data.pop(key, None)


def kit_app(monkeypatch, tmp_path, session, developer=None, redis=None, enabled=True):
    monkeypatch.setenv("FRAME_KIT_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("FRAME_KIT_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.example")

    async def _redis():
        return redis

    monkeypatch.setattr(fk, "_redis", _redis)
    app = FastAPI()
    app.include_router(fk.router)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: (developer or dev())
    return TestClient(app)


def test_every_route_answers_404_while_the_flag_is_off(monkeypatch, tmp_path):
    session = FakeSession()
    http = kit_app(monkeypatch, tmp_path, session, enabled=False)
    for method, path in (("get", "/api/v1/frame-kit/me"), ("post", f"/api/v1/frame-kit/me/{RID}/link"),
                         ("get", "/api/v1/frame-kit/download?token=" + "x" * 40)):
        r = getattr(http, method)(path)
        assert r.status_code == 404 and fk.OFF_SENTENCE in r.text, (path, r.text)
    assert session.statements == []


def test_the_page_lists_the_callers_requests_with_the_kit_and_the_network(monkeypatch, tmp_path):
    publish(tmp_path)
    inv = types.SimpleNamespace(initiator_trust_domain="frame.northwind.example", status="pending", created_at=NOW, completed_at=None)
    session = FakeSession([approved()], [inv])
    r = kit_app(monkeypatch, tmp_path, session).get("/api/v1/frame-kit/me")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["release"]["filename"] == "theprotocol-frame-kit-1.0.0.tar.gz" and "path" not in doc["release"]
    assert doc["network"]["console"] == "https://theprotocol.example" and doc["release_note"] is None
    one = doc["requests"][0]
    assert one["kit"]["state"] == "ready" and one["hosting"] == "self" and one["lat"] == 38.72 and one["lng"] == -9.14
    assert [s["key"] for s in one["progress"] if s["state"] == "done"] == ["requested", "approved", "invited"]
    assert "review_notes" not in one and "source_ip" not in one
    assert "lower(frame_requests.contact_email)" in str(session.statements[0].compile(dialect=postgresql.dialect()))


def test_a_link_works_once_counts_once_and_serves_the_file(monkeypatch, tmp_path):
    body = publish(tmp_path)
    redis, the_row = FakeRedis(), approved()
    session = FakeSession(the_row, the_row, the_row, developers={42: dev()})
    http = kit_app(monkeypatch, tmp_path, session, redis=redis)
    link = http.post(f"/api/v1/frame-kit/me/{RID}/link")
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    token = url.split("token=", 1)[1]
    assert list(redis.data) == ["framekit:dl:" + hashlib.sha256(token.encode()).hexdigest()]   # the digest, never the token
    assert list(redis.ttls.values()) == [fk.LINK_TTL_S]
    got = http.get(url)
    assert got.status_code == 200 and got.content == body
    assert got.headers["x-content-sha256"] == hashlib.sha256(body).hexdigest()
    assert "attachment" in got.headers["content-disposition"] and got.headers["cache-control"] == "no-store"
    assert the_row.kit_download_count == 1 and the_row.kit_last_download_at is not None and session.commits == 1
    again = http.get(url)
    assert again.status_code == 410 and "already used" in again.json()["detail"]
    assert the_row.kit_download_count == 1


@pytest.mark.parametrize("the_row,status", [
    (row(), 409),                                        # locked
    (approved(kit_download_count=5), 409),               # exhausted
    (approved(answers={"provisioning": {"hosting": "theprotocol"}}), 409),
])
def test_a_link_is_refused_with_the_windows_sentence(monkeypatch, tmp_path, the_row, status):
    publish(tmp_path)
    r = kit_app(monkeypatch, tmp_path, FakeSession(the_row), redis=FakeRedis()).post(f"/api/v1/frame-kit/me/{RID}/link")
    assert r.status_code == status and r.json()["detail"] == fk.kit_window(the_row, {"x": 1}, NOW, days=30, limit=5)["sentence"]


def test_a_link_for_someone_elses_request_is_not_found_and_a_foreign_claim_cannot_download(monkeypatch, tmp_path):
    publish(tmp_path)
    assert kit_app(monkeypatch, tmp_path, FakeSession(None), redis=FakeRedis()).post(f"/api/v1/frame-kit/me/{RID}/link").status_code == 404
    redis = FakeRedis()
    redis.data["framekit:dl:" + hashlib.sha256(b"t" * 40).hexdigest()] = json.dumps({"request_id": RID, "developer_id": 99})
    session = FakeSession(approved(developer_id=42), developers={99: dev(id=99, email="mallory@evil.example")})
    r = kit_app(monkeypatch, tmp_path, session, redis=redis).get("/api/v1/frame-kit/download?token=" + "t" * 40)
    assert r.status_code == 404 and session.commits == 0


def test_no_redis_is_a_sentence_not_a_crash(monkeypatch, tmp_path):
    publish(tmp_path)
    r = kit_app(monkeypatch, tmp_path, FakeSession(approved()), redis=None).post(f"/api/v1/frame-kit/me/{RID}/link")
    assert r.status_code == 503 and "Redis" in r.json()["detail"]


# ── the approve (Frame Management) and its mail ─────────────────────────────────────────────────────────────────────

def review_app(session, monkeypatch, mails, enabled=True):
    monkeypatch.setenv("FRAME_KIT_ENABLED", "true" if enabled else "false")
    monkeypatch.setattr(review, "__name__", review.__name__)
    import agentvault_registry.routers.frame_kit as kit
    monkeypatch.setattr(kit, "send_approval_mail", lambda r: mails.append(r.id) or True)
    admin = types.SimpleNamespace(id=7, email="ops@example.test", is_admin=True, admin_federation=True, must_change_password=False)
    app = FastAPI()
    app.include_router(review.router)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_mainframe_only] = lambda: None
    app.dependency_overrides[security.get_current_developer] = lambda: admin
    return TestClient(app)


def test_approving_a_self_hosted_request_opens_a_new_window_and_mails_the_applicant(monkeypatch):
    mails, the_row = [], approved(kit_download_count=4, kit_last_download_at=NOW - datetime.timedelta(days=2))
    http = review_app(FakeSession(the_row), monkeypatch, mails)
    r = http.patch(f"/api/v1/admin/frame-requests/{RID}", json={"status": "approved"})
    assert r.status_code == 200, r.text
    assert the_row.kit_download_count == 0 and the_row.kit_approved_at is not None and the_row.kit_last_download_at is not None
    assert r.json()["kit_download_count"] == 0 and mails == [RID]


def test_approving_a_hosted_request_is_refused_and_changes_nothing(monkeypatch):
    mails, the_row = [], row(answers={"provisioning": {"hosting": "theprotocol"}})
    session = FakeSession(the_row)
    r = review_app(session, monkeypatch, mails).patch(f"/api/v1/admin/frame-requests/{RID}", json={"status": "approved"})
    assert r.status_code == 409 and "Frame Management" in r.json()["detail"]
    assert the_row.status == "pending" and session.commits == 0 and mails == []


def test_with_the_kit_off_approve_is_refused_and_review_still_works(monkeypatch):
    mails, the_row = [], row()
    session = FakeSession(the_row, the_row)   # one answer per query: the refused approve, then the review
    http = review_app(session, monkeypatch, mails, enabled=False)
    r = http.patch(f"/api/v1/admin/frame-requests/{RID}", json={"status": "approved"})
    assert r.status_code == 409 and "FRAME_KIT_ENABLED is off" in r.json()["detail"]
    assert the_row.status == "pending" and the_row.kit_approved_at is None and session.commits == 0 and mails == []
    r = http.patch(f"/api/v1/admin/frame-requests/{RID}", json={"status": "reviewed"})
    assert r.status_code == 200 and the_row.status == "reviewed" and session.commits == 1 and mails == []


def test_the_approval_mail_names_the_page_the_window_and_only_goes_when_it_should(monkeypatch):
    monkeypatch.setenv("FRAME_KIT_ENABLED", "true")
    mail = fk.approval_mail(approved(), "https://theprotocol.example/", days=30, limit=5)
    assert mail["recipients"] == ["Ada@Org.example"] and mail["template"] == "admin_notice"
    text = mail["context"]["body_text"]
    assert "https://theprotocol.example/#/frame-kit" in text and "30 days and 5 downloads" in text and "Northwind Frame" in mail["subject"]
    assert fk.approval_mail(approved(answers={"provisioning": {"hosting": "theprotocol"}}), "https://x.example", days=30, limit=5) is None
    assert fk.approval_mail(approved(), "", days=30, limit=5) is None
    monkeypatch.setenv("FRAME_KIT_ENABLED", "false")
    assert fk.approval_mail(approved(), "https://x.example", days=30, limit=5) is None


def test_the_public_config_carries_the_flag_and_the_status_filter_knows_approved():
    import pathlib
    main_src = pathlib.Path(fk.__file__).resolve().parents[1].joinpath("main.py").read_text()
    assert '"frame_kit_enabled": _os.environ.get("FRAME_KIT_ENABLED"' in main_src
    assert "app.include_router(frame_kit.router)" in main_src
    review_src = pathlib.Path(review.__file__).read_text()
    assert 'Literal["pending", "reviewed", "approved", "provisioned", "rejected"]' in review_src
