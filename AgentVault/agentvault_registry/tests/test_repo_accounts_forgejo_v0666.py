"""V0667 repository accounts against a REAL Forgejo (gwo_662c03447bcd627afa4a11e5; session-lead seq 5029: "the suspension legs
against a real Forgejo in a throwaway container"). The flow runs with the real ForgejoClient; only the store is in memory.

  - the link creates the user on the host with the host's own e-mail and must_change_password
  - the user's own token works; after the pause leg the SAME token is refused by the API (measured, not assumed) and the user
    still exists; after the restore leg it works again and the account's settings are exactly as before
  - a pause of an account an admin had prohibited before keeps it prohibited after the restore (exactly what the pause found)
  - the close leg leaves the user in place and prohibited: nothing on the host is deleted
  - a host that does not answer is a leg that waits, never a lost one

Skipped unless FORGEJO_TEST_URL names a throwaway Forgejo it may write to and FORGEJO_TEST_TOKEN an admin token of it (an
all-scope token of its admin). Skipped, never silently passed.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.error
import urllib.request
import uuid

import pytest

URL = os.environ.get("FORGEJO_TEST_URL")
TOKEN = os.environ.get("FORGEJO_TEST_TOKEN")
if not (URL and TOKEN):
    pytest.skip("needs a REAL throwaway Forgejo: set FORGEJO_TEST_URL and FORGEJO_TEST_TOKEN. Skipped, never silently passed.",
                allow_module_level=True)

from agentvault_registry.services import repo_accounts as ra  # noqa: E402

NOW = dt.datetime(2026, 11, 16, 1, 0, tzinfo=dt.timezone.utc)


class MemStore:
    def __init__(self):
        self.devs, self.accounts, self.ops, self.next_op = {}, {}, [], 1

    async def developer(self, i):
        return self.devs.get(i)

    async def account(self, i):
        return self.accounts.get(i)

    async def account_by_username(self, u):
        return next((a for a in self.accounts.values() if a["username"] == u), None)

    async def add_account(self, row):
        self.accounts[row["developer_id"]] = dict(row)

    async def update_account(self, i, **f):
        self.accounts[i].update(f)

    async def add_op(self, row):
        row = {"id": self.next_op, **row}
        self.next_op += 1
        self.ops.append(row)
        return row

    async def pending_ops(self, i=None):
        return [o for o in self.ops if o["status"] == "pending" and (i is None or o["developer_id"] == i)]

    async def update_op(self, op_id, **f):
        next(o for o in self.ops if o["id"] == op_id).update(f)


def _req(method, path, body=None, token=None, basic=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "token " + token
    if basic:
        h["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
    rq = urllib.request.Request(URL.rstrip("/") + "/api/v1" + path, method=method,
                                data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(rq, timeout=30) as r:
            t = r.read()
            return r.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        return e.code, None


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_CODE_HOST_URL", URL.rstrip("/"))
    store = MemStore()
    store.devs[7] = {"id": 7, "is_verified": True, "is_suspended": False, "deleted_at": None}
    flow = ra.RepoAccounts(store, ra.ForgejoClient(base=URL, token=TOKEN), now=lambda: NOW)
    return store, flow, "t" + uuid.uuid4().hex[:10]


def _user_token(username, password):
    """The developer's own first sign-in: the one-time password changed, then a token of their own."""
    new = "Aa1-" + uuid.uuid4().hex
    st, _ = _req("PATCH", f"/admin/users/{username}", {"login_name": username, "source_id": 0, "password": new,
                                                        "must_change_password": False}, token=TOKEN)
    assert st == 200, st
    st, tok = _req("POST", f"/users/{username}/tokens", {"name": "push", "scopes": ["write:repository", "read:user"]},
                   basic=f"{username}:{new}")
    assert st == 201, st
    return tok["sha1"]


async def test_link_pause_restore_on_the_real_host(setup):
    store, flow, name = setup
    out = await flow.link(7, {"username": name, "confirm": True, "accept_terms": ra.terms_version()})
    st, u = _req("GET", f"/users/{name}", token=TOKEN)
    assert st == 200 and store.accounts[7]["host_user_id"] == u["id"]
    assert out["git_config"].endswith(f"{name}@users.code.theprotocol.cloud")
    tok = _user_token(name, out["password"])
    assert _req("GET", "/user", token=tok)[0] == 200
    before = {k: u.get(k) for k in ("prohibit_login", "restricted", "visibility")}
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    assert store.accounts[7]["state"] == "paused"
    assert _req("GET", "/user", token=tok)[0] == 403                    # the same token refused while paused
    assert _req("GET", f"/users/{name}", token=TOKEN)[0] == 200          # and the user is still there
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert _req("GET", "/user", token=tok)[0] == 200
    after = _req("GET", f"/users/{name}", token=TOKEN)[1]
    assert {k: after.get(k) for k in before} == before and store.accounts[7]["state"] == "active"


async def test_an_admins_own_prohibition_survives_a_suspension(setup):
    store, flow, name = setup
    await flow.link(7, {"username": name, "confirm": True, "accept_terms": ra.terms_version()})
    _req("PATCH", f"/admin/users/{name}", {"login_name": name, "source_id": 0, "prohibit_login": True}, token=TOKEN)
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert _req("GET", f"/users/{name}", token=TOKEN)[1]["prohibit_login"] is True


async def test_close_deletes_nothing(setup):
    store, flow, name = setup
    await flow.link(7, {"username": name, "confirm": True, "accept_terms": ra.terms_version()})
    await flow.enqueue(7, "close", "developer_deleted")
    await flow.drain_once()
    st, u = _req("GET", f"/users/{name}", token=TOKEN)
    assert st == 200 and u["prohibit_login"] is True and store.accounts[7]["state"] == "closed"


async def test_a_host_that_does_not_answer_is_a_leg_that_waits(setup):
    store, flow, name = setup
    await flow.link(7, {"username": name, "confirm": True, "accept_terms": ra.terms_version()})
    flow.client = ra.ForgejoClient(base="http://127.0.0.1:9", token=TOKEN)      # nothing listens there
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    op = store.ops[0]
    assert op["status"] == "pending" and op["attempts"] == 1 and "did not answer" in op["last_error"]
    assert _req("GET", f"/users/{name}", token=TOKEN)[1]["prohibit_login"] is False


async def test_a_link_that_cannot_be_recorded_leaves_no_user_on_the_real_host(setup, monkeypatch):
    # V0667 (session-lead room seq 5217): the store fails after the host made the user; the link removes it again
    store, flow, name = setup

    async def broken(row):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(store, "add_account", broken)
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.link(7, {"username": name, "confirm": True, "accept_terms": ra.terms_version()})
    assert e.value.code == "not_recorded"
    assert _req("GET", f"/users/{name}", token=TOKEN)[0] == 404            # gone from the host
    assert await flow.undo_link(name) is True                               # a second removal finds nothing and is fine
