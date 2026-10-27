"""§REPATLANE (V0603): a STRICT in-memory double of exchange_gateway_credits for the AGORA payout lane
(services/exchange_service.py: the per-credit pass, the aggregated pass and the store settlement).

The first fakes for the lane answered every UPDATE with rowcount=len(ids), so no guard was ever tested: not the claim's
own tx_ref, not the status a write expects, not RETURNING, not a race. This double holds real rows and applies each
statement the lane issues with the WHERE clause the lane wrote: a write that the database would not apply finds nothing
here either, and a statement this double does not know raises (a double that accepts everything proves nothing).

Hooks for the races: `before_claim(table, ids)` runs inside a bundle claim before it applies (another pass takes rows
first), and a test's fake /teg/send can change rows while a send is in flight (another pass settles a claim).
"""
from __future__ import annotations

import re
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

_APPLY_WHERE = " WHERE id = ANY(:ids) AND status=:claim_status AND tx_ref=:claim"
_SENDABLE = "((attempts = 0 AND rearm_count = 0) OR tx_ref LIKE :retry_mark)"


class Credit(SimpleNamespace):
    """One row; the per-credit pass's ORM select hands these out and the pass sets attributes on them."""


def credit(id: int, *, did: str = "", amount: str = "2", status: str = "pending", attempts: int = 0,
           rearm_count: int = 0, tx_ref: Optional[str] = None, home: str = "sandbox-b", currency: str = "SBXA",
           origin: str = "refund") -> Credit:
    return Credit(id=id, did=did or f"did:theprotocol:trader-{id}", home_registry=home, currency=currency,
                  amount=Decimal(amount), origin=origin, ref=f"r{id}", status=status, attempts=attempts,
                  rearm_count=rearm_count, tx_ref=tx_ref, created_at=id, paid_at=None)


def ref_epoch(tx_ref: Optional[str]) -> int:
    """The lane's _REF_EPOCH_SQL: the third '|' field when it is 1 to 12 digits, else 0."""
    parts = str(tx_ref or "").split("|")
    third = parts[2] if len(parts) >= 3 else ""
    return int(third) if re.fullmatch(r"[0-9]{1,12}", third) else 0


def _like_prefix(value: Optional[str], pattern: str) -> bool:
    assert pattern.endswith("%") and "%" not in pattern[:-1] and "_" not in pattern, pattern
    return value is not None and value.startswith(pattern[:-1])


def sendable(r: Credit, retry_mark: str) -> bool:
    return (r.attempts == 0 and r.rearm_count == 0) or _like_prefix(r.tx_ref, retry_mark)


class _Res:
    def __init__(self, rowcount: int = 0, rows: Optional[list] = None, scalars: Optional[list] = None, one: Any = None):
        self.rowcount, self._rows, self._scalars, self._one = rowcount, rows or [], scalars or [], one

    def all(self):
        return list(self._rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def scalar_one_or_none(self):
        return self._one


class CreditsTable:
    def __init__(self, rows: List[Credit], *, dust: Decimal, max_attempts: int, batch: int = 20):
        self.rows: Dict[int, Credit] = {r.id: r for r in rows}
        self.dust, self.max_attempts, self.batch = dust, max_attempts, batch
        self.commits = 0
        self.log: List[str] = []
        self.before_claim: Optional[Callable[["CreditsTable", List[int]], None]] = None

    # ── the session surface the lane uses ─────────────────────────────────────────────────────────────────────────
    async def commit(self):
        self.commits += 1

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        self.log.append(sql)
        if "FROM agents" in sql:
            return _Res(one=SimpleNamespace(id=7))
        if sql.startswith("UPDATE exchange_gateway_credits SET status='unresolved', tx_ref=:tr WHERE status IN"):
            return self._legacy_hold(sql, p)
        if sql.startswith("SELECT status, tx_ref, array_agg(id ORDER BY id) ids"):
            return self._stale_claims(sql, p)
        if sql.startswith("SELECT tx_ref, array_agg(id ORDER BY id) ids"):
            return self._recent_holds(sql, p)
        if sql.startswith("SELECT did, home_registry, array_agg(id ORDER BY id) ids, sum(amount) total"):
            return self._buckets(sql, p)
        if sql.startswith("UPDATE exchange_gateway_credits SET status='batched', tx_ref=:claim"):
            return self._claim_bundle(sql, p)
        if sql.startswith("UPDATE exchange_gateway_credits SET ") and sql.endswith(_APPLY_WHERE):
            return self._apply(sql, p)
        if sql.startswith("SELECT exchange_gateway_credits.") and "FROM exchange_gateway_credits" in sql:
            return self._per_credit_select(sql, p)
        raise AssertionError(f"the credits double does not know this statement: {sql[:200]}")

    # ── statements ────────────────────────────────────────────────────────────────────────────────────────────────
    def _legacy_hold(self, sql, p):
        assert ("WHERE status IN ('pending', 'failed') AND (attempts > 0 OR rearm_count > 0)"
                " AND (tx_ref IS NULL OR tx_ref NOT LIKE :retry_mark)") in sql, sql
        n = 0
        for r in self.rows.values():
            if (r.status in ("pending", "failed") and (r.attempts > 0 or r.rearm_count > 0)
                    and (r.tx_ref is None or not _like_prefix(r.tx_ref, p["retry_mark"]))):
                r.status, r.tx_ref = "unresolved", p["tr"]
                n += 1
        return _Res(rowcount=n)

    def _stale_claims(self, sql, p):
        assert "WHERE status IN ('sending', 'batched') AND tx_ref IS NOT NULL AND CASE" in sql and "< :stale" in sql, sql
        assert "GROUP BY status, tx_ref ORDER BY min(id) LIMIT 100" in sql, sql
        groups: Dict[tuple, List[int]] = {}
        for r in sorted(self.rows.values(), key=lambda x: x.id):
            if r.status in ("sending", "batched") and r.tx_ref is not None and ref_epoch(r.tx_ref) < p["stale"]:
                groups.setdefault((r.status, r.tx_ref), []).append(r.id)
        out = [SimpleNamespace(status=k[0], tx_ref=k[1], ids=v) for k, v in groups.items()]
        return _Res(rows=sorted(out, key=lambda g: min(g.ids))[:100])

    def _recent_holds(self, sql, p):
        assert "WHERE status='unresolved' AND split_part(tx_ref, '|', 1) <> '' AND CASE" in sql and ">= :cutoff" in sql
        assert "DESC LIMIT 500" in sql, sql
        groups: Dict[str, List[int]] = {}
        for r in sorted(self.rows.values(), key=lambda x: x.id):
            if (r.status == "unresolved" and str(r.tx_ref or "").split("|")[0] != ""
                    and ref_epoch(r.tx_ref) >= p["cutoff"]):
                groups.setdefault(r.tx_ref, []).append(r.id)
        out = [SimpleNamespace(tx_ref=k, ids=v) for k, v in groups.items()]
        return _Res(rows=sorted(out, key=lambda g: ref_epoch(g.tx_ref), reverse=True)[:500])

    def _buckets(self, sql, p):
        assert "WHERE status='pending' AND amount < :dust AND attempts < :ma AND " + _SENDABLE in sql, sql
        dust, ma = Decimal(p["dust"]), p["ma"]
        groups: Dict[tuple, List[Credit]] = {}
        for r in sorted(self.rows.values(), key=lambda x: x.id):
            if r.status == "pending" and r.amount < dust and r.attempts < ma and sendable(r, p["retry_mark"]):
                groups.setdefault((r.did, r.home_registry), []).append(r)
        out = []
        for (did, home), rs in groups.items():
            total = sum((x.amount for x in rs), Decimal("0"))
            if total >= dust:
                out.append(SimpleNamespace(did=did, home_registry=home, ids=[x.id for x in rs], total=total))
        return _Res(rows=sorted(out, key=lambda b: b.total, reverse=True)[:p["b"]])

    def _claim_bundle(self, sql, p):
        assert sql.endswith(" WHERE id = ANY(:ids) AND status='pending' AND amount < :dust AND attempts < :ma AND "
                            + _SENDABLE + " RETURNING id"), sql
        if self.before_claim is not None:
            hook, self.before_claim = self.before_claim, None
            hook(self, list(p["ids"]))
        dust, took = Decimal(p["dust"]), []
        for i in p["ids"]:
            r = self.rows.get(i)
            if (r is not None and r.status == "pending" and r.amount < dust and r.attempts < p["ma"]
                    and sendable(r, p["retry_mark"])):
                r.status, r.tx_ref = "batched", p["claim"]
                took.append(i)
        return _Res(rowcount=len(took), scalars=took)

    def _apply(self, sql, p):
        sets = sql[len("UPDATE exchange_gateway_credits SET "):-len(_APPLY_WHERE)]
        n = 0
        for i in p["ids"]:
            r = self.rows.get(i)
            if r is None or r.status != p["claim_status"] or r.tx_ref != p["claim"]:
                continue
            if sets == "status='unresolved', tx_ref=:tr":
                r.status, r.tx_ref = "unresolved", p["tr"]
            elif sets == "status='paid', paid_at=now(), tx_ref=:tr":
                r.status, r.tx_ref, r.paid_at = "paid", p["tr"], "now"
            elif sets == "status='pending', tx_ref=:tr":
                r.status, r.tx_ref = "pending", p["tr"]
            elif sets == ("attempts=attempts+1, tx_ref=:tr, "
                          "status=CASE WHEN attempts + 1 >= :ma THEN 'failed' ELSE 'pending' END"):
                r.status = "failed" if r.attempts + 1 >= p["ma"] else "pending"  # the CASE reads the old attempts
                r.attempts, r.tx_ref = r.attempts + 1, p["tr"]
            elif sets == "status='pending', tx_ref=CASE WHEN attempts > 0 OR rearm_count > 0 THEN :tr ELSE NULL END":
                r.status, r.tx_ref = "pending", (p["tr"] if (r.attempts > 0 or r.rearm_count > 0) else None)
            else:
                raise AssertionError(f"the credits double does not know this write: {sets}")
            n += 1
        return _Res(rowcount=n)

    def _per_credit_select(self, sql, p):
        # the ORM statement: its WHERE must carry the same sendable clause the double applies
        assert "exchange_gateway_credits.rearm_count" in sql and "LIKE" in sql and "FOR UPDATE" in sql, sql
        mark = next((v for v in p.values() if isinstance(v, str) and v.endswith("%")), "r|%")
        rows = [r for r in sorted(self.rows.values(), key=lambda x: x.created_at)
                if r.status == "pending" and r.amount >= self.dust and r.attempts < self.max_attempts
                and sendable(r, mark)]
        return _Res(scalars=rows[:self.batch])
