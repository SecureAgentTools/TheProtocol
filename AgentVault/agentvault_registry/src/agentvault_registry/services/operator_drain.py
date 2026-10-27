"""The genesis drain a PURGE runs before an operator's ledger is destroyed, on the socket route.

§OPPROV (2026-09-27). The frame runner's operator_purge (tools/frame-runner/frame_runner.py, _drain_operator_treasury) and
this module are the two halves of one rule, kept byte-compatible on purpose: they read and write the SAME record file in
the operator's stack dir, so an operator whose purge started on one route and is retried on the other resumes rather than
forgets. What the socket route did before, measured against the runner's measurements of 2026-09-27 on sbx-beta:

  * it read the treasury with the TEG admin key, which every operator TEG answers 403 since §SECFIX ("mTLS identity
    required"); the 403 body carries no balance, the parse defaulted it to "0", and the purge went on as if nothing was
    there. So every socket purge destroyed an undrained treasury;
  * it sent to the frame's own TEG id as the socket route names it, which is not necessarily the one partner the
    operator's TEG knows (PARTNER_TEGS), so a send could be refused as an unknown partner;
  * its correlation id was `teardown-drain-<op>`, constant across incarnations of a name, and the TEG answers a repeated
    id with the prior success and sends nothing;
  * and the purge continued whatever the drain said.

Now: the read and the send run where the operator's registry talks to its TEG (in its registry container, with the app's
own SVID context, through its nginx-teg sidecar), to the one partner in PARTNER_TEGS, under
`td-<op[:12]>-<incarnation[:8]>-<n>` (at most 29 characters: the TEG keeps it in a VARCHAR(36)); every send is written to the record BEFORE it goes out; an unconfirmed send is
re-sent first, with its own id and amount, before the balance is read at all (a stalled send leaves the TEG holding a
PENDING row with the treasury debited, so the balance reads zero while the value is in flight); and the caller refuses the
purge, with nothing removed, unless this answers ok.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DRAIN_RECORD = ".teardown-drain.json"
DRAIN_DUST = Decimal("0.000001")
DRAIN_MARK = "DRAIN-JSON "
AMOUNT_RE = re.compile(r"\d{1,15}(\.\d{1,18})?")              # an amount as the drain sends it (the runner's rule)
TEG_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,62}")               # a TEG id as PARTNER_TEGS names it (the runner's rule)
DRAIN_ID_RE = re.compile(r"td-[a-z0-9-]{1,12}-[0-9a-f]{8}-[0-9]{1,4}")
DRAIN_ID_MAX = 36   # teg_transactions.transaction_id is VARCHAR(36) on both sides of the send
COMPLETED_RESULTS = ("completed", "success", "sent", "ok", "settled")

# Run by the app's python in the operator's REGISTRY container. The body travels in an environment variable because an
# SDK exec cannot write to stdin; it carries an amount, a TEG id, a correlation id and a reason, nothing secret.
DRAIN_PY_READ = (
    "import os,json,httpx\n"
    "from agentvault_registry.es_ssl_helper import get_httpx_verify\n"
    "b=(os.environ.get('TEG_API_BASE_URL') or os.environ.get('TEG_LAYER_URL') or '').rstrip('/')\n"
    "r=httpx.get(b+'/api/v1/admin/treasury/info',verify=get_httpx_verify(),timeout=10)\n"
    "d=r.json() if 'json' in r.headers.get('content-type','') else {}\n"
    "print('DRAIN-JSON '+json.dumps({'status':r.status_code,'treasury_balance':str(d.get('treasury_balance',''))}))\n")
# The parent's address is the one the operator's own registry dials it at: its MAINFRAME_PUBLIC_URL through the app's
# _teg_dial_url (V0457's rule for the operator -> parent hop), sent as the fund-send's target_url, which the TEG prefers
# over PARTNER_TEGS. Measured 2026-09-27 on sbx-beta: every socket-route operator since §REDERIVE ships PARTNER_TEGS=[] and
# the older ones name teg-layer-test with an EMPTY url, so a drain that took its target from PARTNER_TEGS had none. A
# PARTNER_TEGS id is only the send's label now (PARENT_LABEL when there is none). The receiver accepts only a source in
# its own trust domain, so an address naming anything else is refused there and the TEG re-credits (502).
PARENT_LABEL = "teg-parent"   # the frame runner's DRAIN_PARENT_LABEL
DRAIN_PY_SEND = (
    "import os,json,httpx\n"
    "from urllib.parse import urlparse\n"
    "from agentvault_registry.es_ssl_helper import get_httpx_verify\n"
    "b=(os.environ.get('TEG_API_BASE_URL') or os.environ.get('TEG_LAYER_URL') or '').rstrip('/')\n"
    "body=json.loads(os.environ['DRAIN_BODY'])\n"
    "m=(os.environ.get('MAINFRAME_PUBLIC_URL') or '').strip()\n"
    "if m and not body.get('target_url'):\n"
    "    try:\n"
    "        from agentvault_registry.routers.teg_integration import _teg_dial_url\n"
    "        body['target_url']=_teg_dial_url(m)\n"
    "    except Exception:\n"
    "        u=urlparse(m)\n"
    "        body['target_url']=('https://%s:%s'%(u.hostname,u.port or 8443)) if u.hostname else ''\n"
    "r=httpx.post(b+'/api/v1/admin/treasury/cross-teg-fund-send',json=body,verify=get_httpx_verify(),timeout=30)\n"
    "d=r.json() if 'json' in r.headers.get('content-type','') else {}\n"
    "print('DRAIN-JSON '+json.dumps({'status':r.status_code,'result':str(d.get('status',''))[:40],"
    "'target_host':urlparse(body.get('target_url') or '').hostname}))\n")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def treasury_amount(raw) -> Optional[Decimal]:
    """A treasury balance as the TEG prints it ('0E-18' and '12.5' alike), or None when not a finite non-negative number."""
    try:
        d = Decimal(str(raw if raw is not None else "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d >= 0 else None


def drain_outcome(answer: dict) -> str:
    """completed | reversed (502: the peer refused, the TEG re-credited) | refused (other 4xx: nothing debited) | uncertain."""
    status = answer.get("status")
    result = str(answer.get("result") or "").lower()
    if status in (200, 201) and result in COMPLETED_RESULTS:
        return "completed"
    if status == 502:
        return "reversed"
    if isinstance(status, int) and 400 <= status < 500:
        return "refused"
    return "uncertain"


def partner_of(env: list) -> Tuple[Optional[str], Optional[str]]:
    """(the drain's label: the ONE partner TEG id the operator TEG's PARTNER_TEGS names, or PARENT_LABEL when it names
    none, None) or (None, why) when it names several. Only ids are read, never a URL or a key."""
    raw = next((e.partition("=")[2] for e in (env or []) if str(e).startswith("PARTNER_TEGS=")), "")
    try:
        doc = json.loads(raw) if raw else {}
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        ids = list(doc.keys())
    elif isinstance(doc, list):
        ids = [str(x.get("teg_id") or x.get("id") or "") for x in doc if isinstance(x, dict)]
    else:
        return None, "the operator TEG's PARTNER_TEGS is not a JSON object or list"
    ids = [i for i in ids if TEG_ID_RE.fullmatch(i or "")]
    if not ids:
        return PARENT_LABEL, None      # the address comes from the operator's own registry (DRAIN_PY_SEND)
    if len(ids) != 1:
        return None, f"the operator TEG's partner is not unique ({len(ids)} partner ids), so the drain has no one target"
    return ids[0], None


def read_record(stack_dir: str) -> Tuple[Optional[str], Optional[dict], Optional[str]]:
    """(path, record, None) | (None, None, why) with no real stack dir | (path, None, why) when it cannot be read."""
    if not stack_dir or not os.path.isdir(stack_dir) or os.path.islink(stack_dir):
        return None, None, "the operator has no stack dir to keep its drain record in"
    path = os.path.join(stack_dir, DRAIN_RECORD)
    if not os.path.lexists(path):
        return path, {"drains": []}, None
    doc = None
    if os.path.isfile(path) and not os.path.islink(path):
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, ValueError):
            doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("drains"), list):
        return path, None, (f"its drain record {path} cannot be read, and it may hold a drain whose delivery was never "
                            f"confirmed")
    return path, doc, None


def write_record(path: str, record: dict) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def plan_resumes(record: Optional[dict], slug: str, partner: Optional[str],
                 incarnation: str = "") -> Tuple[list, Optional[dict]]:
    """(the unconfirmed drains to re-send first, in order, None) or ([], refusal) when one of them does not read as a
    drain this purge could have sent: its id is another operator's or malformed, its amount is not an amount, or its
    target is not the operator's one partner. A record the frame can write must not become a way to send elsewhere."""
    todo = []
    for d in (record or {}).get("drains", []):
        if not isinstance(d, dict) or d.get("state") not in ("sending", "uncertain"):
            continue
        cid, amt, tgt = str(d.get("correlation_id") or ""), str(d.get("amount") or ""), str(d.get("target") or "")
        if (not DRAIN_ID_RE.fullmatch(cid) or len(cid) > DRAIN_ID_MAX
                or not cid.startswith(f"td-{slug[:12]}-{incarnation[:8]}-")
                or not AMOUNT_RE.fullmatch(amt) or tgt != (partner or "")):
            return [], {"ok": False, "drained": False, "amount": amt[:40], "correlation_id": cid[:100],
                        "note": f"an unconfirmed drain in the operator's drain record does not read as one this purge "
                                f"sent to {partner or 'the operator TEG partner'}, so it was not re-sent"}
        todo.append(d)
    return todo, None


def drain_id(slug: str, incarnation: str, n: int) -> str:
    """The n-th drain of this incarnation of the operator, in at most 29 characters (the frame runner's drain_id).
    Measured 2026-09-27 on opprova: the TEG keeps the correlation id in teg_transactions.transaction_id, VARCHAR(36), and
    refused (400, nothing debited) the 37-character teardown-drain-opprova-<12 hex>-1."""
    return f"td-{slug[:12]}-{incarnation[:8]}-{n}"


def next_correlation_id(record: dict, slug: str, incarnation: str) -> str:
    return drain_id(slug, incarnation, len(record["drains"]) + 1)


def incarnation_of(slug: str, created: str) -> str:
    """The runner's _operator_incarnation: this provisioning of the name, from its registry container's creation instant."""
    return hashlib.sha256(f"{slug}|{created}".encode()).hexdigest()[:12]


class _Docker:
    """The four things the drain asks of Docker, behind one seam so a test can stand in for all of them."""

    def __init__(self, client=None):
        if client is None:
            import docker as _dk
            client = _dk.from_env()
        self.client = client

    def containers(self, slug: str, service: str) -> list:
        return self.client.containers.list(all=True, ignore_removed=True, filters={"label": [
            f"com.docker.compose.project=cloud-op-{slug}", f"com.docker.compose.service={service}"]})

    def ledger_volumes(self, slug: str) -> list:
        return [v.name for v in self.client.volumes.list(filters={"label": [
            f"com.docker.compose.project=cloud-op-{slug}", "com.docker.compose.volume=teg-data"]})]

    def registry_python(self, container, code: str, body: Optional[str] = None) -> dict:
        env = {"PYTHONPATH": "/app/src"}
        if body is not None:
            env["DRAIN_BODY"] = body
        rc, out = container.exec_run(["python", "-c", code], workdir="/app", environment=env, demux=True)
        text = ((out or (b"", b""))[0] or b"").decode("utf-8", "replace")
        line = next((ln[len(DRAIN_MARK):] for ln in reversed(text.splitlines()) if ln.startswith(DRAIN_MARK)), "")
        try:
            answer = json.loads(line) if rc == 0 and line else {}
        except ValueError:
            answer = {}
        return answer if isinstance(answer, dict) else {}


def drain_operator_treasury(slug: str, stack_dir: str, docker: Optional[_Docker] = None) -> dict:
    """{"ok": bool, "drained": bool, ...}: ok False means the treasury holds value (or a send in flight) that did not
    move, and the purge must not go on. The same answers, for the same states, as the runner's operator_purge drain."""
    dk = docker or _Docker()
    try:
        tegs = dk.containers(slug, "teg-layer")
    except Exception as exc:  # noqa: BLE001 — a listing that failed is a treasury nobody can read
        return {"ok": False, "drained": False,
                "note": f"the operator's TEG containers could not be listed ({type(exc).__name__}), so the treasury "
                        f"cannot be read and a purge would strand whatever it holds"}
    if len(tegs) != 1:
        why = f"the operator runs {len(tegs)} TEG container(s), not one"
        ledger = None
        if not tegs:
            try:
                ledger = dk.ledger_volumes(slug)
            except Exception:  # noqa: BLE001
                ledger = None
        if not tegs and ledger == []:
            return {"ok": True, "drained": False, "note": f"nothing to drain: {why}, and no TEG ledger volume"}
        return {"ok": False, "drained": False,
                "note": f"{why}{' while its TEG ledger volume remains' if ledger else ''}, so the treasury cannot be "
                        f"read and a purge would strand whatever it holds; start its TEG (or drain it by hand) first"}
    partner, why = partner_of(((tegs[0].attrs or {}).get("Config") or {}).get("Env") or [])
    regs = dk.containers(slug, "registry")
    if len(regs) != 1:
        return {"ok": False, "drained": False,
                "note": f"the operator runs {len(regs)} registry container(s), not one, and the drain reads and sends "
                        f"through its registry, so the treasury cannot be read"}
    reg = regs[0]
    path, record, rec_why = read_record(stack_dir)
    if path is not None and record is None:
        return {"ok": False, "drained": False, "note": rec_why}

    inc = incarnation_of(slug, str((reg.attrs or {}).get("Created") or ""))
    todo, refusal = plan_resumes(record, slug, partner, inc)
    if refusal:
        return refusal
    completed_now = []
    for d in todo:
        body = json.dumps({"amount": d["amount"], "target_teg_id": d["target"], "correlation_id": d["correlation_id"],
                           "reason": "teardown_genesis_drain"})
        answer = dk.registry_python(reg, DRAIN_PY_SEND, body)
        outcome = drain_outcome(answer)
        d.update(state=("uncertain" if outcome == "refused" else outcome), answered=answer.get("status"),
                 result=str(answer.get("result") or "")[:40] or None, at=_now())
        try:
            write_record(path, record)
        except OSError as exc:
            return {"ok": False, "drained": False, "amount": d["amount"], "correlation_id": d["correlation_id"],
                    "note": f"the drain record {path} could not be written ({type(exc).__name__}) after re-sending a "
                            f"drain; nothing was removed"}
        if d["state"] == "uncertain":
            return {"ok": False, "drained": False, "amount": d["amount"], "target": d["target"],
                    "correlation_id": d["correlation_id"], "status": d.get("result"),
                    "note": f"a drain of {d['amount']} sent earlier (correlation id {d['correlation_id']}) is still "
                            f"unconfirmed: its re-delivery answered {answer.get('status') or 'nothing'}, and the "
                            f"operator's TEG may hold it pending, which a purge would destroy"}
        if d["state"] == "completed":
            completed_now.append(d)

    read = dk.registry_python(reg, DRAIN_PY_READ)
    dec = treasury_amount(read.get("treasury_balance")) if read.get("status") == 200 else None
    if dec is None:
        return {"ok": False, "drained": False, "note": f"the operator treasury could not be read (its TEG answered "
                                                      f"{read.get('status') or 'nothing'}), so a purge would strand "
                                                      f"whatever it holds"}
    bal = format(dec, "f")
    if dec <= DRAIN_DUST:
        out = {"ok": True, "drained": bool(completed_now), "amount": bal,
               "note": "the operator treasury holds nothing to drain"}
        if completed_now:
            out["resumed"] = [d["correlation_id"] for d in completed_now]
        return out
    if partner is None:
        return {"ok": False, "drained": False, "amount": bal, "note": why}
    if not AMOUNT_RE.fullmatch(bal):
        return {"ok": False, "drained": False, "amount": bal[:40],
                "note": "the treasury balance is not a shape the drain sends; nothing was sent"}
    if path is None:
        return {"ok": False, "drained": False, "amount": bal,
                "note": f"{rec_why}, so a drain that stalled could not be resumed by a retry; nothing was sent"}
    cid = next_correlation_id(record, slug, inc)
    d = {"correlation_id": cid, "amount": bal, "target": partner, "state": "sending", "at": _now()}
    record["drains"].append(d)
    try:
        write_record(path, record)   # BEFORE the send: a purge that dies mid-send leaves "sending", re-sent first next time
    except OSError as exc:
        return {"ok": False, "drained": False, "amount": bal,
                "note": f"the drain record {path} could not be written ({type(exc).__name__}); nothing was sent"}
    answer = dk.registry_python(reg, DRAIN_PY_SEND, json.dumps({"amount": bal, "target_teg_id": partner,
                                                                  "correlation_id": cid,
                                                                  "reason": "teardown_genesis_drain"}))
    outcome = drain_outcome(answer)
    d.update(state=outcome, answered=answer.get("status"), result=str(answer.get("result") or "")[:40] or None,
             at=_now())
    try:
        write_record(path, record)
    except OSError:
        pass   # the record still says "sending", so the next purge re-sends it first (a completed id is answered as done)
    ok = outcome == "completed"
    logger.info(f"[CLOUD-TEARDOWN] {slug}: drain {cid} of {bal} -> {partner}: {outcome} "
                f"(answered {answer.get('status')})")
    if ok:
        # §OPPROV (2026-09-27): "completed" is the TEG's word, and the TEG answers a correlation id it already completed
        # with that prior success while moving nothing (its idempotency). A drain whose record was lost could reuse an id
        # at the same amount and be told "completed" with the value still in the treasury, which the purge would then
        # destroy. The drain is done only when the treasury READS empty after it; a remainder waits for a retried purge.
        after = dk.registry_python(reg, DRAIN_PY_READ)
        dec_after = treasury_amount(after.get("treasury_balance")) if after.get("status") == 200 else None
        if dec_after is None or dec_after > DRAIN_DUST:
            seen = "could not be re-read" if dec_after is None else f"still reads {format(dec_after, 'f')}"
            logger.warning(f"[CLOUD-TEARDOWN] {slug}: drain {cid} answered completed, but the treasury {seen}")
            return {"ok": False, "drained": False, "amount": bal, "target": partner, "correlation_id": cid,
                    "outcome": outcome, "after": None if dec_after is None else format(dec_after, "f"),
                    "note": f"the drain {cid} was answered completed, but the operator treasury {seen}, so nothing was "
                            f"removed; a retried purge drains what remains"}
    return {"ok": ok, "drained": ok, "amount": bal, "target": partner, "status": d.get("result"),
            "correlation_id": cid, "outcome": outcome,
            "note": None if ok else {"reversed": "the parent refused the drain and the operator's TEG re-credited its "
                                                 "treasury, so it still holds the value",
                                     "refused": "the operator's TEG refused the drain before debiting anything",
                                     }.get(outcome, "the drain was not confirmed, so the operator's TEG may hold it "
                                                    "pending; a retried purge re-sends it first")}
