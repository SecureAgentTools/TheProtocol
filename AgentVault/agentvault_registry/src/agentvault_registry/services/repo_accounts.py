"""Repository accounts on the public code host, linked to developers (V0666, order gwo_662c03447bcd627afa4a11e5; room seq
5003 and seq 5040; session-lead's answer seq 5029; sessionlogs2026/DESIGN_2026-11-16_PUBLIC_FORGEJO.md sections 3 and 4, measured in
section 9; DESIGN_2026-11-15_DISTRIBUTIONS.md section 11).

  * THE LINK IS NEVER AUTOMATIC. An account on code.theprotocol.cloud exists only because its developer asked for it in the console
    (`confirm: true`, after the console showed WHAT_IS_SHARED). One account per developer, one developer per account; only a
    verified developer in good standing; only while REPO_ACCOUNTS_ENABLED. The account's e-mail is an address of the host's own, never
    the developer's. The one-time password is answered once and stored nowhere.
  * ONE STANDING, TWO PLACES. A developer's suspension pauses the account (`prohibit_login`: no sign-in, no token, no push; what they
    published stays readable, measured on Forgejo 15.0.11) and records what it found first; reinstatement writes back exactly that
    record. A second pause keeps the FIRST record; a restore with no pause changes nothing; deletion closes the account
    (`prohibit_login`, never a delete) and a closed account is never restored.
  * NEVER A STRANDED LOCK. Every leg is a row of `repo_account_ops`, written in the caller's own transaction (the suspension and its
    leg commit together), drained by one leader-elected worker (background_tasks/repo_account_worker), one developer's legs in order,
    retried with backoff; past MAX_ATTEMPTS a leg is stuck, listed for the admin and told to the developer with its reason and next try.
  * THE SUBMIT GATE. With the switch on, proposing a code change needs a linked, active account (409 `repo_account_required`).
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import secrets
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
OPS = ("pause", "restore", "close")
STATES = ("active", "paused", "closed")
_USERNAME = re.compile(r"[a-z0-9][a-z0-9-]{1,37}[a-z0-9]")
RESERVED = frozenset({
    "admin", "administrator", "code-admin", "root", "system", "theprotocol", "the-protocol", "support", "security", "abuse",
    "postmaster", "noreply", "no-reply", "api", "assets", "avatars", "explore", "user", "users", "org", "orgs", "repo", "repos",
    "login", "logout", "settings", "notifications", "issues", "pulls", "milestones", "new", "help", "about", "ghost",
})

WHAT_IS_SHARED = (
    "Your username on code.theprotocol.cloud, which you choose here.",
    "The forks and branches you push, the commits in them (with the name and e-mail address your git records) and your comments "
    "are public, like the repository itself.",
    "The account's e-mail is <username>@users.code.theprotocol.cloud; your own address is never sent to the code host.",
    "While your developer account is suspended the code host account cannot sign in or push; reinstatement restores it as it was.",
    "Your git writes its configured e-mail into every commit: set it to the code host address before you push "
    "(git config user.email <username>@users.code.theprotocol.cloud); an address in a published commit stays in the history.",
    "Contributions are made under the project's licences: a sign-off (DCO) on every commit and, for code, the CLA.",
    "Deleting your developer account closes the code host account; contributions already made stay under your name.",
)


def enabled() -> bool:
    return (os.getenv("REPO_ACCOUNTS_ENABLED") or "").strip().lower() == "true"


def host_url() -> str:
    return (os.getenv("PUBLIC_CODE_HOST_URL") or "https://code.theprotocol.cloud").rstrip("/")


def email_domain() -> str:
    return (os.getenv("PUBLIC_CODE_HOST_EMAIL_DOMAIN") or "users.code.theprotocol.cloud").strip()


def backoff_seconds(attempts: int) -> int:
    return min(60 * (2 ** max(attempts - 1, 0)), 3600)


class HostError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def terms_version() -> str:
    """The Terms version the registry serves now (core/legal_versions): what a link accepts."""
    from ..core.legal_versions import current_version
    return current_version("terms") or ""


class RepoAccountRefusal(Exception):
    def __init__(self, status: int, code: str, sentence: str):
        super().__init__(sentence)
        self.status, self.code, self.sentence = status, code, sentence


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, dt.datetime) else v


class RepoAccounts:
    """The flow over a store (DbStore here, a fake in the tests) and a code host client (ForgejoClient, a fake in the tests)."""

    def __init__(self, store, client=None, now: Optional[Callable[[], dt.datetime]] = None):
        self.s, self.client = store, client
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    # --- the link -------------------------------------------------------------------------------------------------------

    async def link(self, developer_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        if not enabled():
            raise RepoAccountRefusal(404, "off", "repository accounts are not open on this registry")
        if body.get("confirm") is not True:
            raise RepoAccountRefusal(422, "confirm", "read what linking means, then confirm: the link is never made for you")
        # Terms § 10.2: the press accepts the Terms served now (the code host is their § 5.12); checked before anything exists on
        # the host, and the route records the acceptance in the link's own transaction
        served, offered = terms_version(), str(body.get("accept_terms") or "").strip()
        if not offered:
            raise RepoAccountRefusal(422, "terms", f"linking accepts the Terms, version {served} (the code host is their § 5.12): "
                                                   "accept them to link")
        if offered != served:
            raise RepoAccountRefusal(409, "legal_version_mismatch", f"the current Terms are version {served}; reload and accept "
                                                                    "that version to link")
        username = str(body.get("username") or "")
        if not _USERNAME.fullmatch(username) or "--" in username or username in RESERVED:
            raise RepoAccountRefusal(422, "username", "a username is 3 to 39 lowercase letters, digits and single hyphens, "
                                                      "not starting or ending with a hyphen, and not a reserved word")
        dev = await self.s.developer(developer_id)
        if not dev or dev.get("deleted_at"):
            raise RepoAccountRefusal(403, "deleted", "a deleted developer account links nothing")
        if dev.get("is_suspended"):
            raise RepoAccountRefusal(403, "suspended", "a suspended developer account cannot link a repository account")
        if not dev.get("is_verified"):
            raise RepoAccountRefusal(403, "not_verified", "verify your e-mail address first")
        if await self.s.account(developer_id):
            raise RepoAccountRefusal(409, "already_linked", "your developer account has its repository account already")
        if await self.s.account_by_username(username):
            raise RepoAccountRefusal(409, "username_taken", "that username is taken: choose another")
        password = secrets.token_urlsafe(24)
        try:
            # V0667 the passport: a contributor's host user names their home registry and their developer there (full_name)
            named = {"full_name": dev["full_name"]} if dev.get("full_name") else {}
            host_id = await self.client.create_user(username, f"{username}@{email_domain()}", password, **named)
        except HostError as exc:
            if exc.status in (409, 422):
                raise RepoAccountRefusal(409, "username_taken", "that username is taken on the code host: choose another")
            logger.warning("[repo_accounts] the code host refused or failed the link for developer %s: %s", developer_id, exc)
            raise RepoAccountRefusal(503, "host_unavailable", "the code host did not answer: nothing was created, try again later")
        now = self.now()
        try:
            await self.s.add_account({"developer_id": developer_id, "username": username, "host_user_id": int(host_id),
                                      "state": "active", "paused_before": None, "created_at": now, "updated_at": now})
        except Exception as exc:  # noqa: BLE001 - whatever stopped the record, the host user it was for must not stay
            logger.error("[repo_accounts] the link of developer %s could not be recorded (%s): removing %s from the code host",
                         developer_id, type(exc).__name__, username)
            await self.undo_link(username)
            raise RepoAccountRefusal(503, "not_recorded", "the link could not be recorded: nothing was kept, try again") from None
        return {"username": username, "host": host_url(), "password": password,
                "sign_in": f"{host_url()}/user/login", "change_password_on_first_sign_in": True,
                "git_config": f"git config user.email {username}@{email_domain()}", "terms_version": served}

    # --- the legs ---------------------------------------------------------------------------------------------------------

    async def enqueue(self, developer_id: int, op: str, cause: str) -> Optional[Dict[str, Any]]:
        """In the CALLER's transaction (no commit here): the leg commits with the suspension, reinstatement or deletion."""
        if op not in OPS:
            raise ValueError(op)
        if not await self.s.account(developer_id):
            return None
        pending = await self.s.pending_ops(developer_id)
        if pending and pending[-1]["op"] == op:
            return pending[-1]
        return await self.s.add_op({"developer_id": developer_id, "op": op, "cause": str(cause)[:64], "status": "pending",
                                    "attempts": 0, "last_error": None, "last_attempt_at": None, "next_attempt_at": None,
                                    "created_at": self.now(), "done_at": None})

    async def _apply(self, op: Dict[str, Any], account: Dict[str, Any]) -> None:
        name, state = account["username"], account["state"]
        if state == "closed":
            return
        if op["op"] == "pause":
            if state != "paused":
                cur = await self.client.get_user(name)
                before = {"prohibit_login": bool(cur.get("prohibit_login"))}
                await self.client.edit_user(name, {"prohibit_login": True})
                await self.s.update_account(account["developer_id"], state="paused", paused_before=before, updated_at=self.now())
            return
        if op["op"] == "restore":
            if state == "paused":
                before = account.get("paused_before") or {"prohibit_login": False}
                await self.client.edit_user(name, {"prohibit_login": bool(before.get("prohibit_login"))})
                await self.s.update_account(account["developer_id"], state="active", paused_before=None, updated_at=self.now())
            return
        if op["op"] == "close":
            await self.client.edit_user(name, {"prohibit_login": True})
            await self.s.update_account(account["developer_id"], state="closed", updated_at=self.now())

    async def drain_once(self, limit: int = 50) -> int:
        """One pass: for each developer, the OLDEST pending leg, if it is due. Later legs of that developer wait for it."""
        pending = await self.s.pending_ops()
        heads: Dict[int, Dict[str, Any]] = {}
        for op in sorted(pending, key=lambda o: o["id"]):
            heads.setdefault(op["developer_id"], op)
        done = 0
        now = self.now()
        for op in list(heads.values())[:limit]:
            if op.get("next_attempt_at") and op["next_attempt_at"] > now:
                continue
            account = await self.s.account(op["developer_id"])
            try:
                if account:
                    await self._apply(op, account)
                await self.s.update_op(op["id"], developer_id=op["developer_id"], status="done", done_at=now, last_attempt_at=now)
                done += 1
            except HostError as exc:
                attempts = int(op.get("attempts") or 0) + 1
                await self.s.update_op(op["id"], developer_id=op["developer_id"], attempts=attempts, last_error=str(exc)[:500],
                                       last_attempt_at=now,
                                       next_attempt_at=now + dt.timedelta(seconds=backoff_seconds(attempts)))
                log = logger.error if attempts >= MAX_ATTEMPTS else logger.warning
                log("[repo_accounts] %s for developer %s failed (attempt %d): %s", op["op"], op["developer_id"], attempts, exc)
            commit = getattr(self.s, "commit", None)
            if commit:
                await commit()
        return done

    async def stuck_ops(self) -> List[Dict[str, Any]]:
        return [o for o in await self.s.pending_ops() if int(o.get("attempts") or 0) >= MAX_ATTEMPTS]

    async def status(self, developer_id: int) -> Dict[str, Any]:
        account = await self.s.account(developer_id)
        pending = await self.s.pending_ops(developer_id)
        head = sorted(pending, key=lambda o: o["id"])[0] if pending else None
        return {
            "enabled": enabled(), "host": host_url(), "linked": bool(account), "terms_version": terms_version(),
            "username": (account or {}).get("username"), "state": (account or {}).get("state"),
            "shares": list(WHAT_IS_SHARED),
            "pending": None if not head else {
                "op": head["op"], "attempts": int(head.get("attempts") or 0), "last_error": head.get("last_error"),
                "last_attempt_at": _iso(head.get("last_attempt_at")), "next_attempt_at": _iso(head.get("next_attempt_at")),
                "stuck": int(head.get("attempts") or 0) >= MAX_ATTEMPTS},
        }

    async def undo_link(self, username: str) -> bool:
        """Remove the host user a link made when the registry could not record it (V0667, session-lead room seq 5217): the user
        is brand new, its one-time password was never handed out, so nothing of anyone's is lost. False (said, never raised)
        when the host does not answer: the caller refuses the link either way, and the verifier names an unknown account."""
        try:
            await self.client.delete_user(username)
            return True
        except HostError as exc:
            logger.error("[repo_accounts] %s could not be removed from the code host after a failed link: %s", username, exc)
            return False

    # --- the submit gate --------------------------------------------------------------------------------------------------

    async def require_linked(self, developer_id: int) -> None:
        if not enabled():
            return
        account = await self.s.account(developer_id)
        if not account:
            raise RepoAccountRefusal(409, "repo_account_required",
                                     "a code change needs your repository account: press Link repository account on the "
                                     "Code changes page first")
        if account["state"] == "paused":
            raise RepoAccountRefusal(409, "repo_account_paused", "your repository account is paused while your developer "
                                                                 "account is suspended")
        if account["state"] == "closed":
            raise RepoAccountRefusal(409, "repo_account_closed", "your repository account is closed")


# ---------------------------------------------------------------- the code host and the database

class ForgejoClient:
    """The code host's admin API, with the registry's own narrow token (PUBLIC_CODE_HOST_TOKEN: write:admin for user creation and
    prohibit_login, nothing else). The token is read by name and never logged."""

    def __init__(self, base: Optional[str] = None, token: Optional[str] = None):
        self.base = (base or os.getenv("PUBLIC_CODE_HOST_API_URL") or host_url()).rstrip("/") + "/api/v1"
        self.token = token if token is not None else (os.getenv("PUBLIC_CODE_HOST_TOKEN") or "")

    async def _call(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        import httpx
        if not self.token:
            raise HostError("the registry holds no code host token")
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.request(method, self.base + path, json=body,
                                    headers={"Authorization": "token " + self.token, "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise HostError(f"the code host did not answer ({type(exc).__name__})")
        if r.status_code >= 400:
            raise HostError(f"the code host answered {r.status_code}", status=r.status_code)
        return r.json() if r.content else None

    async def create_user(self, username: str, email: str, password: str, full_name: Optional[str] = None) -> int:
        body = await self._call("POST", "/admin/users", {"username": username, "email": email, "password": password,
                                                          "must_change_password": True, "visibility": "public",
                                                          "restricted": False, **({"full_name": full_name} if full_name else {})})
        return int(body["id"])

    async def get_user(self, username: str) -> Dict[str, Any]:
        return await self._call("GET", f"/users/{username}")

    async def edit_user(self, username: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return await self._call("PATCH", f"/admin/users/{username}", {"login_name": username, "source_id": 0, **fields})

    async def delete_user(self, username: str) -> None:
        """Only for a link the registry could not record (RepoAccounts.undo_link); the legs never delete. 204 removed, 404 gone
        already (measured on 15.0.11 with the registry's write:admin,read:user token)."""
        try:
            await self._call("DELETE", f"/admin/users/{username}")
        except HostError as exc:
            if exc.status != 404:
                raise


class DbStore:
    """The flow's store on the registry database (models.RepoAccount, models.RepoAccountOp). It never commits on its own except
    through commit(), which the worker calls per leg; enqueue writes into the caller's transaction.

    V0667 the passport, phase 4: a NEGATIVE key is a contributor from another registry (services/code_passport.contributor_key), whose
    account and legs live in contributor_repo_accounts and contributor_repo_account_ops under the same rules; every method answers them
    under the same negative key, so the flow above reads one kind of row. A contributor's ops have ids of their own: update_op is told
    the op's key (the drain passes it) to find the table."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _row(obj, cols) -> Dict[str, Any]:
        return {c: getattr(obj, c) for c in cols}

    _ACC = ("developer_id", "username", "host_user_id", "state", "paused_before", "created_at", "updated_at")
    _OP = ("id", "developer_id", "op", "cause", "status", "attempts", "last_error", "last_attempt_at", "next_attempt_at",
           "created_at", "done_at")

    @staticmethod
    def _elsewhere(key: Any) -> Optional[int]:
        return -key if isinstance(key, int) and not isinstance(key, bool) and key < 0 else None

    def _c_acc(self, a) -> Dict[str, Any]:
        return {**self._row(a, self._ACC_C), "developer_id": -a.contributor_id}

    def _c_op(self, o) -> Dict[str, Any]:
        return {**self._row(o, self._OP_C), "developer_id": -o.contributor_id}

    _ACC_C = ("username", "host_user_id", "state", "paused_before", "created_at", "updated_at")
    _OP_C = ("id", "op", "cause", "status", "attempts", "last_error", "last_attempt_at", "next_attempt_at", "created_at", "done_at")

    async def developer(self, developer_id: int) -> Optional[Dict[str, Any]]:
        from agentvault_registry import models
        cid = self._elsewhere(developer_id)
        if cid is not None:
            # a contributor: their home vouched for them on a card the governing registry verified (verified, in good standing);
            # paused reads as suspended, closed as deleted
            c = await self.db.get(models.CodeContributor, cid)
            if not c:
                return None
            from agentvault_registry.services.code_passport import host_full_name
            return {"id": developer_id, "is_verified": True, "is_suspended": c.standing == "paused",
                    "deleted_at": c.paused_at if c.standing == "closed" else None,
                    "full_name": host_full_name(c.display_name, c.home_registry, c.home_developer_id)}
        d = await self.db.get(models.Developer, developer_id)
        if not d:
            return None
        # good standing as the code change rail reads it (code_changes.DbStore.developers_in_good_standing): a deletion that is
        # pending, requested or done all count as deleted here
        gone = d.deleted_at or d.deletion_status or d.deletion_requested_at
        return {"id": d.id, "is_verified": bool(d.is_verified), "is_suspended": bool(d.is_suspended), "deleted_at": gone}

    async def account(self, developer_id: int):
        from sqlalchemy import select
        from agentvault_registry import models
        cid = self._elsewhere(developer_id)
        if cid is not None:
            a = await self.db.get(models.ContributorRepoAccount, cid)
            return self._c_acc(a) if a else None
        a = (await self.db.execute(select(models.RepoAccount).where(models.RepoAccount.developer_id == developer_id))).scalar_one_or_none()
        return self._row(a, self._ACC) if a else None

    async def account_by_username(self, username: str):
        """One username space on the code host: a member's account and a contributor's are read together."""
        from sqlalchemy import select
        from agentvault_registry import models
        a = (await self.db.execute(select(models.RepoAccount).where(models.RepoAccount.username == username))).scalar_one_or_none()
        if a:
            return self._row(a, self._ACC)
        c = (await self.db.execute(select(models.ContributorRepoAccount)
                                   .where(models.ContributorRepoAccount.username == username))).scalar_one_or_none()
        return self._c_acc(c) if c else None

    async def add_account(self, row: Dict[str, Any]) -> None:
        from agentvault_registry import models
        cid = self._elsewhere(row.get("developer_id"))
        if cid is not None:
            self.db.add(models.ContributorRepoAccount(**{k: v for k, v in row.items() if k != "developer_id"}, contributor_id=cid))
        else:
            self.db.add(models.RepoAccount(**row))
        await self.db.flush()

    async def update_account(self, developer_id: int, **fields) -> None:
        from sqlalchemy import update
        from agentvault_registry import models
        cid = self._elsewhere(developer_id)
        if cid is not None:
            C = models.ContributorRepoAccount
            await self.db.execute(update(C).where(C.contributor_id == cid).values(**fields))
            return
        await self.db.execute(update(models.RepoAccount).where(models.RepoAccount.developer_id == developer_id).values(**fields))

    async def add_op(self, row: Dict[str, Any]) -> Dict[str, Any]:
        from agentvault_registry import models
        cid = self._elsewhere(row.get("developer_id"))
        if cid is not None:
            obj = models.ContributorRepoAccountOp(**{k: v for k, v in row.items() if k != "developer_id"}, contributor_id=cid)
            self.db.add(obj)
            await self.db.flush()
            return self._c_op(obj)
        obj = models.RepoAccountOp(**row)
        self.db.add(obj)
        await self.db.flush()
        return self._row(obj, self._OP)

    async def pending_ops(self, developer_id: Optional[int] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        from agentvault_registry import models
        O, C = models.RepoAccountOp, models.ContributorRepoAccountOp
        cid = self._elsewhere(developer_id)
        out: List[Dict[str, Any]] = []
        if cid is None:
            q = select(O).where(O.status == "pending").order_by(O.id)
            if developer_id is not None:
                q = q.where(O.developer_id == developer_id)
            out = [self._row(o, self._OP) for o in (await self.db.execute(q)).scalars().all()]
        if developer_id is None or cid is not None:
            qc = select(C).where(C.status == "pending").order_by(C.id)
            if cid is not None:
                qc = qc.where(C.contributor_id == cid)
            out += [self._c_op(o) for o in (await self.db.execute(qc)).scalars().all()]
        return out

    async def update_op(self, op_id: int, **fields) -> None:
        """`developer_id` names the op's key (members and contributors number their ops apart): it picks the table, never a column
        to change."""
        from sqlalchemy import update
        from agentvault_registry import models
        key = fields.pop("developer_id", None)
        cid = self._elsewhere(key)
        if cid is not None:
            C = models.ContributorRepoAccountOp
            await self.db.execute(update(C).where(C.id == op_id, C.contributor_id == cid).values(**fields))
            return
        await self.db.execute(update(models.RepoAccountOp).where(models.RepoAccountOp.id == op_id).values(**fields))

    async def commit(self) -> None:
        await self.db.commit()


async def enqueue_in(db, developer_id: int, op: str, cause: str) -> None:
    """For the suspension, reinstatement and deletion paths: the leg in their own transaction; a failure here is logged loudly and
    never blocks the act it follows (the admin still wants the developer suspended)."""
    try:
        await RepoAccounts(DbStore(db)).enqueue(developer_id, op, cause)
    except Exception as exc:  # noqa: BLE001
        logger.error("[repo_accounts] could not queue %s for developer %s: %s", op, developer_id, exc)
