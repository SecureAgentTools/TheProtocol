"""V0666 repository accounts on the public code host (order gwo_662c03447bcd627afa4a11e5; room seq 5003 and seq 5040;
session-lead's answer seq 5029; sessionlogs2026/DESIGN_2026-11-16_PUBLIC_FORGEJO.md sections 3 and 4, measured in section 9;
DESIGN_2026-11-15_DISTRIBUTIONS.md section 11, read whole).

The rules, as pure flow over a store and a code host client (both fakes here; the real Postgres and the real Forgejo have their
own tests):
  - the link is never automatic: it exists only after the developer's own request with `confirm: true`, one account per developer
    and one developer per account, only for a verified developer in good standing, only while REPO_ACCOUNTS_ENABLED
  - a suspension pauses the account (prohibit_login) and records what it found first; reinstatement restores EXACTLY that record;
    a second pause keeps the FIRST record; a restore with no pause changes nothing; a developer with no account touches nothing
  - every leg is an outbox row, retried with backoff; a leg past MAX_ATTEMPTS is stuck and visible; a reinstated developer whose
    restore is pending sees why and when
  - deletion closes the account (prohibit_login, never a delete); a closed account is never restored
  - with the switch on, a code change needs a linked account: refused with its sentence, never silently
RED on 633f06b42: services/repo_accounts does not exist.
"""
from __future__ import annotations

import datetime as dt

import pytest

from agentvault_registry.services import repo_accounts as ra

NOW = dt.datetime(2026, 11, 16, 1, 0, tzinfo=dt.timezone.utc)


class FakeClient:
    """The code host: users by name, each with its settings; can be told to fail."""

    def __init__(self):
        self.users = {}
        self.fail = None
        self.calls = []

    async def create_user(self, username, email, password):
        self.calls.append(("create", username))
        if self.fail:
            raise ra.HostError(self.fail)
        if username in self.users:
            raise ra.HostError("taken", status=422)
        self.users[username] = {"id": len(self.users) + 10, "login": username, "email": email, "prohibit_login": False}
        return self.users[username]["id"]

    async def get_user(self, username):
        self.calls.append(("get", username))
        if self.fail:
            raise ra.HostError(self.fail)
        return dict(self.users[username])

    async def edit_user(self, username, fields):
        self.calls.append(("edit", username, dict(fields)))
        if self.fail:
            raise ra.HostError(self.fail)
        self.users[username].update(fields)
        return dict(self.users[username])

    async def delete_user(self, username):
        self.calls.append(("delete", username))
        if self.fail:
            raise ra.HostError(self.fail)
        self.users.pop(username, None)


class FakeStore:
    def __init__(self):
        self.devs = {}
        self.accounts = {}          # developer_id -> dict
        self.ops = []               # dicts
        self.next_op = 1

    def dev(self, i, **kw):
        self.devs[i] = {"id": i, "is_verified": True, "is_suspended": False, "deleted_at": None, **kw}

    async def developer(self, developer_id):
        return self.devs.get(developer_id)

    async def account(self, developer_id):
        return self.accounts.get(developer_id)

    async def account_by_username(self, username):
        return next((a for a in self.accounts.values() if a["username"] == username), None)

    async def add_account(self, row):
        self.accounts[row["developer_id"]] = dict(row)

    async def update_account(self, developer_id, **fields):
        self.accounts[developer_id].update(fields)

    async def add_op(self, row):
        row = {"id": self.next_op, **row}
        self.next_op += 1
        self.ops.append(row)
        return row

    async def pending_ops(self, developer_id=None):
        return [o for o in self.ops if o["status"] == "pending" and (developer_id is None or o["developer_id"] == developer_id)]

    async def update_op(self, op_id, **fields):
        next(o for o in self.ops if o["id"] == op_id).update(fields)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "true")
    store, client = FakeStore(), FakeClient()
    store.dev(7)
    return store, client, ra.RepoAccounts(store, client, now=lambda: NOW)


async def _link(flow, dev=7, username="ada-lovelace"):
    return await flow.link(dev, {"username": username, "confirm": True, "accept_terms": ra.terms_version()})


# --- the Terms at the press (session-lead room seq 5175: Terms § 10.2, "whoever presses Link repository account accepts 2.6 at
# the press") -----------------------------------------------------------------------------------------------------------------

async def test_the_link_accepts_the_terms_served_now_and_nothing_else(env):
    store, client, flow = env
    served = ra.terms_version()
    assert served
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.link(7, {"username": "ada-lovelace", "confirm": True})
    assert (e.value.status, e.value.code) == (422, "terms") and served in e.value.sentence
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.link(7, {"username": "ada-lovelace", "confirm": True, "accept_terms": "1.0"})
    assert (e.value.status, e.value.code) == (409, "legal_version_mismatch") and served in e.value.sentence
    assert client.calls == [] and store.accounts == {}                  # refused before anything exists on the host
    out = await _link(flow)
    assert out["terms_version"] == served


async def test_the_status_names_the_terms_a_link_accepts(env):
    store, client, flow = env
    assert (await flow.status(7))["terms_version"] == ra.terms_version()


# --- the link -------------------------------------------------------------------------------------------------------------

async def test_the_link_needs_the_developers_own_confirmation(env):
    store, client, flow = env
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.link(7, {"username": "ada-lovelace"})
    assert e.value.code == "confirm" and not client.calls and not store.accounts


async def test_a_link_creates_one_account_on_the_host_and_records_it(env):
    store, client, flow = env
    out = await _link(flow)
    assert out["username"] == "ada-lovelace" and out["host"] == "https://code.theprotocol.cloud"
    assert len(out["password"]) >= 20 and out["password"] not in str(store.accounts)       # shown once, never stored
    u = client.users["ada-lovelace"]
    assert u["email"] == "ada-lovelace@users.code.theprotocol.cloud"                        # never the developer's address
    a = store.accounts[7]
    assert a["username"] == "ada-lovelace" and a["host_user_id"] == u["id"] and a["state"] == "active"


async def test_one_account_per_developer_and_one_developer_per_account(env):
    store, client, flow = env
    await _link(flow)
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow, username="ada-two")
    assert e.value.code == "already_linked"
    store.dev(8)
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow, dev=8)
    assert e.value.code == "username_taken"


@pytest.mark.parametrize("name", ["a", "ab", "Ada", "ada_lovelace", "-ada", "ada-", "a" * 40, "admin", "code-admin",
                                  "theprotocol", "explore", "api", "ada lovelace", "ada.lovelace"])
async def test_a_username_outside_the_rule_is_refused(env, name):
    _store, client, flow = env
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow, username=name)
    assert e.value.code == "username" and not client.calls


@pytest.mark.parametrize("kw,code", [({"is_verified": False}, "not_verified"), ({"is_suspended": True}, "suspended"),
                                     ({"deleted_at": NOW}, "deleted")])
async def test_only_a_developer_in_good_standing_links(env, kw, code):
    store, client, flow = env
    store.dev(9, **kw)
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow, dev=9)
    assert e.value.code == code and not client.calls


async def test_with_the_switch_off_nothing_links(env, monkeypatch):
    _store, client, flow = env
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "false")
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow)
    assert e.value.code == "off" and not client.calls


async def test_a_host_failure_at_link_records_nothing(env):
    store, client, flow = env
    client.fail = "connection refused"
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow)
    assert e.value.code == "host_unavailable" and not store.accounts


# --- the legs ----------------------------------------------------------------------------------------------------------------

async def test_a_developer_with_no_account_enqueues_nothing(env):
    store, _client, flow = env
    assert await flow.enqueue(7, "pause", "developer_suspended") is None and not store.ops


async def test_suspend_then_reinstate_leaves_the_account_exactly_as_before(env):
    store, client, flow = env
    await _link(flow)
    before = dict(client.users["ada-lovelace"])
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    assert client.users["ada-lovelace"]["prohibit_login"] is True and store.accounts[7]["state"] == "paused"
    assert store.accounts[7]["paused_before"] == {"prohibit_login": False}
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert client.users["ada-lovelace"] == before and store.accounts[7]["state"] == "active"


async def test_a_restore_writes_back_what_the_pause_found_even_when_that_was_already_prohibited(env):
    store, client, flow = env
    await _link(flow)
    client.users["ada-lovelace"]["prohibit_login"] = True          # an admin had prohibited it before the suspension
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert client.users["ada-lovelace"]["prohibit_login"] is True    # exactly what it found, never more and never less


async def test_a_second_pause_keeps_the_first_record(env):
    store, client, flow = env
    await _link(flow)
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    assert store.accounts[7]["paused_before"] == {"prohibit_login": False}


async def test_a_restore_with_no_pause_changes_nothing(env):
    store, client, flow = env
    await _link(flow)
    client.calls.clear()
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert not [c for c in client.calls if c[0] == "edit"] and store.ops[-1]["status"] == "done"


async def test_a_pending_pause_is_not_queued_twice(env):
    store, _client, flow = env
    await _link(flow)
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.enqueue(7, "pause", "developer_suspended")
    assert len([o for o in store.ops if o["op"] == "pause"]) == 1


async def test_legs_of_one_developer_land_in_order(env):
    store, client, flow = env
    await _link(flow)
    client.fail = "connection refused"
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert all(o["status"] == "pending" for o in store.ops) and store.ops[1]["attempts"] == 0    # the restore waits its pause
    client.fail = None
    flow.now = lambda: NOW + dt.timedelta(hours=2)
    await flow.drain_once()
    await flow.drain_once()
    assert [o["status"] for o in store.ops] == ["done", "done"] and client.users["ada-lovelace"]["prohibit_login"] is False


async def test_a_failed_leg_is_retried_with_backoff_and_shown_when_stuck(env):
    store, client, flow = env
    await _link(flow)
    client.fail = "connection refused"
    await flow.enqueue(7, "pause", "developer_suspended")
    t = NOW
    for i in range(ra.MAX_ATTEMPTS):
        flow.now = lambda t=t: t
        await flow.drain_once()
        op = store.ops[0]
        assert op["attempts"] == i + 1 and op["last_error"] == "connection refused" and op["next_attempt_at"] > t
        t = op["next_attempt_at"]
    assert (await flow.stuck_ops())[0]["developer_id"] == 7
    st = await flow.status(7)
    assert st["pending"]["op"] == "pause" and st["pending"]["stuck"] is True and st["pending"]["last_error"] == "connection refused"


async def test_a_reinstated_developer_whose_restore_is_pending_is_told_why_and_when(env):
    store, client, flow = env
    await _link(flow)
    await flow.enqueue(7, "pause", "developer_suspended")
    await flow.drain_once()
    client.fail = "the code host answered 502"
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    st = await flow.status(7)
    assert st["state"] == "paused" and st["pending"]["op"] == "restore"
    assert st["pending"]["last_error"] == "the code host answered 502" and st["pending"]["next_attempt_at"]


async def test_deletion_closes_the_account_and_a_closed_account_is_never_restored(env):
    store, client, flow = env
    await _link(flow)
    await flow.enqueue(7, "close", "developer_deleted")
    await flow.drain_once()
    assert client.users["ada-lovelace"]["prohibit_login"] is True and store.accounts[7]["state"] == "closed"
    await flow.enqueue(7, "restore", "developer_reinstated")
    await flow.drain_once()
    assert client.users["ada-lovelace"]["prohibit_login"] is True and store.accounts[7]["state"] == "closed"
    assert not [c for c in client.calls if c[0] == "delete"]
    # the client can delete since V0667 (only to remove a link it could not record); the legs never do
    import inspect
    assert "delete_user" not in inspect.getsource(ra.RepoAccounts._apply)


# --- the code change gate --------------------------------------------------------------------------------------------------

async def test_with_the_switch_on_a_code_change_needs_a_linked_account(env):
    store, _client, flow = env
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.require_linked(7)
    assert e.value.code == "repo_account_required" and e.value.status == 409
    assert "Link repository account" in e.value.sentence
    await _link(flow)
    await flow.require_linked(7)


async def test_with_the_switch_off_the_gate_asks_nothing(env, monkeypatch):
    _store, _client, flow = env
    monkeypatch.setenv("REPO_ACCOUNTS_ENABLED", "false")
    await flow.require_linked(7)


async def test_a_paused_account_cannot_propose_either(env):
    store, _client, flow = env
    await _link(flow)
    await store.update_account(7, state="paused")
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await flow.require_linked(7)
    assert e.value.code == "repo_account_paused"


def test_what_the_link_shares_is_one_list_the_console_shows():
    shares = ra.WHAT_IS_SHARED
    assert any("username" in s for s in shares) and any("public" in s for s in shares)
    assert any("suspend" in s for s in shares) and any("licen" in s.lower() for s in shares)
    assert not any("@" in s and "users.code.theprotocol.cloud" not in s for s in shares)


async def test_the_link_answers_the_one_git_line_that_sets_the_author_e_mail(env):
    """session-lead, room seq 5097: a commit carries whatever e-mail the developer's own git records, so the dialog shows the one
    line that sets it to the code host's address before the first push."""
    _store, _client, flow = env
    out = await _link(flow)
    assert out["git_config"] == "git config user.email ada-lovelace@users.code.theprotocol.cloud"
    assert any("git config user.email" in s for s in ra.WHAT_IS_SHARED)



# --- a link that cannot be recorded leaves nothing behind (session-lead room seq 5217, V0667 follow-up 2) ------------------

async def test_a_link_the_store_cannot_record_removes_the_host_user_it_made(env, monkeypatch):
    store, client, flow = env

    async def broken(row):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(store, "add_account", broken)
    with pytest.raises(ra.RepoAccountRefusal) as e:
        await _link(flow)
    assert (e.value.status, e.value.code) == (503, "not_recorded")
    assert client.users == {} and ("delete", "ada-lovelace") in client.calls


async def test_the_route_undoes_the_host_user_when_its_commit_fails(env):
    store, client, flow = env
    await _link(flow)
    assert "ada-lovelace" in client.users
    assert await flow.undo_link("ada-lovelace") is True
    assert client.users == {}
    client.fail = "connection refused"
    assert await flow.undo_link("ada-lovelace") is False           # said, never raised: the caller still refuses the link
