"""The facts the verifier reads itself (V0666 layer C): never a fact the code under test wrote for it.

  - a node's environment: `docker inspect` through ONE runner, keeping only the names of ENV_ALLOW (a value outside the list never
    leaves the function: a DSN, a key or a secret is not a fact the verifier needs);
  - a node's database: SELECT only, in a read-only transaction the server enforces (default_transaction_read_only);
  - a node's published route list (its openapi.json).
A fact that cannot be read raises Unmeasured: the run counts it, apart from a pass and apart from a violation.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# the live switch of each feature a jurisdiction profile can deny (the five of identity-fabric's profile_coherent)
FLAG_OF = {"exchange": "EXCHANGE_ENABLED", "fx": "FX_ENABLED", "guild": "GUILD_ENABLED", "forge": "FORGE_ENABLED",
           "fiat": "FIAT_ONRAMP_ENABLED"}

ENV_ALLOW: Tuple[str, ...] = ("AGENT_RBAC_MODE", "AGENT_DELEGATION_MODE", *FLAG_OF.values(), "CODE_CHANGE_VETO_HOURS",
                              "ACCOUNT_DELETION_COOLING_OFF_DAYS", "ACCOUNT_DELETION_INTERVAL_SECONDS")

# a route that could pay fiat out ("no fiat-out endpoint exists, ever": Fiat_Rails_Strategy.md). A refund of a card payment is
# the buyer's own money back through Stripe and is not named here.
FIAT_OUT = re.compile(r"/fiat\b.*(payout|withdraw|cash-?out|redeem|disburse|sell|fiat-?out)", re.I)

MERGED_SQL = ("SELECT id, repository, paths, commit, state, sensitive, proposer_developer_id, acceptance, passed_at, veto, go, "
              "merged, code_distribution_id, ballot_result, proposal_id FROM code_changes WHERE state = 'merged' ORDER BY created_at")
PROPOSALS_SQL = "SELECT id, status FROM governance_proposals WHERE id = ANY(:ids)"
REVIEWS_SQL = ("SELECT code_change_id, reviewer_developer_id, verdict, commit, EXTRACT(EPOCH FROM created_at) AS at "
               "FROM code_change_reviews WHERE code_change_id = ANY(:ids)")
PENDING_SQL = ("SELECT id, deletion_status, deletion_requested_at, anonymized_at FROM developers "
               "WHERE deletion_status = 'pending_deletion'")
PROFILE_SQL = "SELECT value FROM exchange_flags WHERE key = 'jurisdiction_profile'"
FIAT_SQL = "SELECT id FROM fiat_purchases"
FIAT_NOT_IN_SQL = "SELECT count(*) AS n FROM fiat_purchases WHERE amount_eur <= 0 OR amount_avt <= 0"
ISSUED_SQL = ("SELECT count(*) AS n FROM events WHERE event_type IN ('TokensIssued', 'UnitsIssued') "
              "AND (idempotency_key LIKE 'fiat-%' OR aggregate_id = ANY(:ids))")


# every connection the verifier opens: the SERVER refuses a write on it, whatever SQL reaches it
READ_ONLY = {"server_settings": {"default_transaction_read_only": "on"}}


class Unmeasured(Exception):
    """A fact the verifier could not read: counted apart from a pass and apart from a violation."""


def pick_env(lines: Iterable[str]) -> Dict[str, str]:
    """NAME=value lines to {name: value} for the allow-list only."""
    out: Dict[str, str] = {}
    for line in lines:
        name, sep, value = str(line).partition("=")
        if sep and name in ENV_ALLOW:
            out[name] = value
    return out


def _run(cmd: List[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30).stdout


def docker_env(container: str, runner: Optional[Callable[[List[str]], str]] = None) -> Dict[str, str]:
    """The allow-listed environment of one container. The whole environment is parsed and dropped inside this function."""
    try:
        raw = (runner or _run)(["docker", "inspect", "--format", "{{json .Config.Env}}", container])
        return pick_env(json.loads(raw) or [])
    except Exception as exc:  # noqa: BLE001: the reason is the exception's class, never its text (an env value may sit in it)
        raise Unmeasured(f"{container}: the environment could not be read ({type(exc).__name__})") from None


class Sources:
    """What a run asks: the nodes, the time, and for each rule and node the subjects it judges, each with its facts. A source
    answers with a list or an awaitable list; one that cannot read a fact raises Unmeasured."""

    def nodes(self) -> List[str]:
        raise NotImplementedError

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def subjects(self, rule: str, node: str):
        raise NotImplementedError


class NodeSources(Sources):
    """The real sources. `nodes` is a list of {name, container, db_env, es_env, base_url}: db_env and es_env are the NAMES of
    variables of this process that hold the DSNs (a secret never sits in the config file)."""

    def __init__(self, nodes: List[Dict[str, Any]], *, environ: Optional[Dict[str, str]] = None,
                 runner: Optional[Callable[[List[str]], str]] = None, fetch: Optional[Callable[[str], Any]] = None,
                 query: Optional[Callable[..., Any]] = None) -> None:
        self.cfg = {n["name"]: n for n in nodes}
        self.environ = environ if environ is not None else {}
        self.runner, self._fetch, self._query = runner, fetch, query

    def nodes(self) -> List[str]:
        return list(self.cfg)

    # -- readers ------------------------------------------------------------------------------------------------------
    def env(self, node: str) -> Dict[str, str]:
        return docker_env(self.cfg[node]["container"], self.runner)

    async def rows(self, node: str, which: str, sql: str, **params: Any) -> List[Dict[str, Any]]:
        dsn = self.environ.get(self.cfg[node].get(which + "_env") or "")
        if not dsn:
            raise Unmeasured(f"{node}: no {which} database is configured")
        try:
            if self._query is not None:
                return list(await self._query(dsn, sql, params))
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine
            engine = create_async_engine(dsn, connect_args=READ_ONLY)
            try:
                async with engine.connect() as conn:
                    res = await conn.execute(text(sql), params)
                    return [dict(r._mapping) for r in res]
            finally:
                await engine.dispose()
        except Unmeasured:
            raise
        except Exception as exc:  # noqa: BLE001: the class, never the text (a DSN can sit in it)
            raise Unmeasured(f"{node}: the {which} database could not be read ({type(exc).__name__})") from None

    def paths(self, node: str) -> List[str]:
        url = (self.cfg[node].get("base_url") or "").rstrip("/") + "/openapi.json"
        try:
            doc = (self._fetch or _http_json)(url)
            return sorted(doc["paths"])
        except Exception as exc:  # noqa: BLE001
            raise Unmeasured(f"{node}: the route list could not be read ({type(exc).__name__})") from None

    # -- the subjects of each rule ------------------------------------------------------------------------------------
    async def subjects(self, rule: str, node: str):
        env = self.env(node) if rule in {"iron_pairing", "jurisdiction_coherent", "merge_needs_the_record", "deletion_on_schedule"} else {}
        if rule == "iron_pairing":
            return [(node, {"env": env})]
        if rule == "jurisdiction_coherent":
            rows = await self.rows(node, "db", PROFILE_SQL)
            profile = None
            if rows and rows[0].get("value"):
                try:
                    parsed = json.loads(rows[0]["value"])
                    profile = parsed if isinstance(parsed, dict) else None
                except (TypeError, ValueError):
                    raise Unmeasured(f"{node}: the stored profile is not JSON") from None
            return [(node, {"profile": profile, "env": env})]
        if rule == "fiat_buy_only":
            ids = [r["id"] for r in await self.rows(node, "db", FIAT_SQL)]
            not_in = (await self.rows(node, "db", FIAT_NOT_IN_SQL))[0]["n"]
            issued = (await self.rows(node, "es", ISSUED_SQL, ids=ids))[0]["n"]
            return [(node, {"paths": self.paths(node), "purchases_not_in": int(not_in), "purchases_issued": int(issued)})]
        if rule == "merge_needs_the_record":
            changes = await self.rows(node, "db", MERGED_SQL)
            if not changes:
                return []
            ids = [c["id"] for c in changes]
            pids = [c["proposal_id"] for c in changes if c.get("proposal_id") is not None]
            status = {p["id"]: p["status"] for p in (await self.rows(node, "db", PROPOSALS_SQL, ids=pids) if pids else [])}
            reviews = await self.rows(node, "db", REVIEWS_SQL, ids=ids)
            out = []
            for c in changes:
                c = {**c, "proposal_status": status.get(c.get("proposal_id"))}
                out.append((c["id"], {"change": c, "reviews": [r for r in reviews if r["code_change_id"] == c["id"]], "env": env}))
            return out
        if rule == "deletion_on_schedule":
            now = self.now()
            return [(f"developer:{a['id']}", {"account": a, "env": env, "now": now})
                    for a in await self.rows(node, "db", PENDING_SQL)]
        raise Unmeasured(f"{rule}: no reader")


def _http_json(url: str) -> Any:
    import urllib.request
    with urllib.request.urlopen(url, timeout=20) as r:    # a GET: the verifier never writes
        return json.loads(r.read().decode("utf-8"))
