"""The core's own sinks: TheProtocol's events delivered to the old systems.

    webhook        POST each event to a system's API (an ERP), with the record's key as Idempotency-Key
    journal        accounting lines: a CSV journal per day, or an ISO 20022 camt.053 statement per day
    calendar       an ICS calendar: one event per delivery, its UID the record's key
    email_digest   a digest mail of the events every interval (SMTP)
    evidence       (theprotocol.proxy.evidence) hash-chained JSONL and a signed manifest, checked offline

Every sink delivers one key once: an HTTP sink sends the key as Idempotency-Key (the other side keeps it), a file sink
writes a key's line once (its state remembers the keys it wrote), a calendar names the event by the key, a digest
spools a key once. In a dry run nothing is written or sent; the outcome shows what would be.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from xml.sax.saxutils import escape

import httpx

from .evidence import event_doc
from .plugins import Event, Outcome, PluginError, Refused, Retry, Sink
from .registry import retry_after
from .spec import is_ref

_CREDENTIAL_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key"}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _when(event: Event) -> datetime:
    return event.occurred_at or datetime.now(timezone.utc)


# ── webhook ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class WebhookSink(Sink):
    name = "webhook"
    description = "POST each event to a system's API, the record's key as its Idempotency-Key"
    config_schema = {
        "type": "object",
        "required": ["url"],
        "additionalProperties": False,
        "properties": {
            "url": {"type": "string", "pattern": "^https?://"},
            "method": {"enum": ["POST", "PUT"]},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "bearer": {"type": "string", "x-secret": True},
            "secret": {"type": "string", "x-secret": True},
            "timeout_s": {"type": "number", "exclusiveMinimum": 0},
        },
    }
    #: tests set an httpx transport here
    transport: Optional[httpx.AsyncBaseTransport] = None

    async def start(self) -> None:
        for name, value in (self.config.get("headers") or {}).items():
            if name.lower() in _CREDENTIAL_HEADERS:
                raise PluginError(f"the webhook's header {name} carries a credential: put it in bearer (a reference)")
            if is_ref(value):
                raise PluginError(f"the webhook's header {name} names a reference: credentials go in bearer")

    def _request(self, event: Event, key: str) -> tuple:
        body = json.dumps({"key": key, "event": event_doc(event)}, sort_keys=True, ensure_ascii=False)
        headers = {"Content-Type": "application/json", "Idempotency-Key": key,
                   "X-TheProtocol-Proxy": self.ctx.proxy_name, "X-TheProtocol-Event": event.event_type,
                   **(self.config.get("headers") or {})}
        if self.config.get("secret"):
            sig = hmac.new(self.ctx.secret(self.config["secret"]).encode(), body.encode(), hashlib.sha256)
            headers["X-Signature-256"] = "sha256=" + sig.hexdigest()
        if self.config.get("bearer"):
            headers["Authorization"] = f"Bearer {self.ctx.secret(self.config['bearer'])}"
        return body, headers

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        body, headers = self._request(event, key)
        method, url = self.config.get("method") or "POST", self.config["url"]
        if dry_run:
            return Outcome.dry(f"would {method} {url}", method=method, url=url, body=json.loads(body))
        try:
            async with httpx.AsyncClient(transport=type(self).transport,
                                         timeout=float(self.config.get("timeout_s") or 30)) as http:
                r = await http.request(method, url, content=body.encode("utf-8"), headers=headers)
        except httpx.TimeoutException as e:
            raise Retry(f"{url}: no answer in time ({type(e).__name__})") from None
        except httpx.HTTPError as e:
            raise Retry(f"{url}: could not be reached ({type(e).__name__})") from None
        st = r.status_code
        if 200 <= st < 300:
            ref = ""
            try:
                doc = r.json()
                ref = str(doc.get("id") or doc.get("reference") or "") if isinstance(doc, dict) else ""
            except ValueError:
                pass
            return Outcome.done(ref or key, f"HTTP {st}", status=st)
        text = (r.text or "")[:300]
        if st in (408, 425, 429) or st >= 500:
            raise Retry(f"{url}: HTTP {st}: {text}", after=retry_after(r), status=st)
        raise Refused(f"{url}: HTTP {st}: {text}", status=st, answer=text)


# ── accounting lines ─────────────────────────────────────────────────────────────────────────────────────────────────

CSV_COLUMNS = ["date", "value_date", "direction", "amount", "currency", "counterparty", "text", "event_id",
               "event_type", "key"]
CAMT_NS = {"001.02": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02",
           "001.08": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"}


def _dec(v: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise Refused(f"the {what} {v!r} is not a number")
    if not d.is_finite():
        raise Refused(f"the {what} {v!r} is not a number")
    return d


class JournalSink(Sink):
    name = "journal"
    description = "Accounting lines: a CSV journal per day, or an ISO 20022 camt.053 statement per day"
    config_schema = {
        "type": "object",
        "required": ["dir", "account"],
        "additionalProperties": False,
        "properties": {
            "dir": {"type": "string", "minLength": 1},
            "format": {"enum": ["csv", "camt053"]},
            "camt_version": {"enum": list(CAMT_NS)},
            "account": {"type": "object", "required": ["id", "currency"], "additionalProperties": False,
                        "properties": {"id": {"type": "string", "minLength": 1},
                                       "currency": {"type": "string", "pattern": "^[A-Z0-9]{2,10}$"},
                                       "name": {"type": "string"}, "servicer": {"type": "string"}}},
            "opening_balance": {"type": ["number", "string"]},
        },
    }

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self.dir = Path(self.config["dir"])
        self.format = self.config.get("format") or "csv"

    async def start(self) -> None:
        if not self.ctx.dry_run:
            self.dir.mkdir(parents=True, exist_ok=True)

    def line(self, event: Event, key: str) -> Dict[str, str]:
        d = dict(event.data)
        if "amount" not in d:
            raise Refused("an accounting line needs an amount: map one (fields: {amount: $.payload...})")
        amount = _dec(d["amount"], "amount")
        direction = str(d.get("direction") or ("debit" if amount < 0 else "credit")).lower()
        if direction not in ("credit", "debit"):
            raise Refused(f"the direction {direction!r} is not credit or debit")
        ccy = str(d.get("currency") or self.config["account"]["currency"])
        if ccy != self.config["account"]["currency"]:
            raise Refused(f"the line is in {ccy}, the journal's account in {self.config['account']['currency']}")
        when = _when(event)
        value = d.get("value_date") or when.date().isoformat()
        return {"date": when.date().isoformat(), "value_date": str(value)[:10], "direction": direction,
                "amount": str(abs(amount)), "currency": ccy, "counterparty": str(d.get("counterparty") or ""),
                "text": str(d.get("text") or event.event_type), "event_id": event.event_id,
                "event_type": event.event_type, "key": key}

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        ln = self.line(event, key)
        if dry_run:
            return Outcome.dry(f"would book {ln['direction']} {ln['amount']} {ln['currency']}", line=ln)
        if await self.ctx.state.get(f"key:{key}") is not None:
            return Outcome.done(key, "already booked")
        day = ln["date"]
        lines: List[Dict[str, str]] = list(await self.ctx.state.get(f"day:{day}") or [])
        lines.append(ln)
        if self.format == "csv":
            path = self.dir / f"journal-{day}.csv"
            new = not path.exists()
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
            if new:
                w.writeheader()
            w.writerow(ln)
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(buf.getvalue())
                f.flush()
                os.fsync(f.fileno())
        else:
            opening = await self._opening(day)
            path = self.dir / f"camt053-{day}.xml"
            _atomic_write(path, self.camt053(day, lines, opening))
        await self.ctx.state.set(f"day:{day}", lines)
        await self.ctx.state.set(f"key:{key}", day)
        return Outcome.done(key, f"booked in {path.name}")

    async def _opening(self, day: str) -> Decimal:
        """The day's opening balance: the configured opening plus every earlier day's net, fixed the first time the day
        is booked."""
        kept = await self.ctx.state.get(f"opening:{day}")
        if kept is not None:
            return Decimal(kept)
        total = _dec(self.config.get("opening_balance") or 0, "opening balance")
        for d in sorted(await self.ctx.state.get("days") or []):
            if d < day:
                total += self._net(await self.ctx.state.get(f"day:{d}") or [])
        await self.ctx.state.set(f"opening:{day}", str(total))
        days = sorted(set(await self.ctx.state.get("days") or []) | {day})
        await self.ctx.state.set("days", days)
        return total

    @staticmethod
    def _net(lines: List[Mapping[str, str]]) -> Decimal:
        return sum((Decimal(l["amount"]) if l["direction"] == "credit" else -Decimal(l["amount"]) for l in lines),
                   Decimal(0))

    def camt053(self, day: str, lines: List[Mapping[str, str]], opening: Decimal) -> str:
        acct = self.config["account"]
        ns = CAMT_NS[self.config.get("camt_version") or "001.02"]
        ccy = acct["currency"]
        closing = opening + self._net(lines)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        stmt_id = f"{self.ctx.proxy_name}-{day}"

        def bal(code: str, amount: Decimal) -> str:
            ind = "CRDT" if amount >= 0 else "DBIT"
            return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>"
                    f"<Amt Ccy=\"{escape(ccy)}\">{abs(amount):.2f}</Amt><CdtDbtInd>{ind}</CdtDbtInd>"
                    f"<Dt><Dt>{day}</Dt></Dt></Bal>")

        entries = []
        for l in lines:
            ind = "CRDT" if l["direction"] == "credit" else "DBIT"
            counter = (f"<RltdPties><{'Dbtr' if ind == 'CRDT' else 'Cdtr'}><Nm>{escape(l['counterparty'][:140])}</Nm>"
                       f"</{'Dbtr' if ind == 'CRDT' else 'Cdtr'}></RltdPties>") if l["counterparty"] else ""
            entries.append(
                f"<Ntry><Amt Ccy=\"{escape(ccy)}\">{Decimal(l['amount']):.2f}</Amt><CdtDbtInd>{ind}</CdtDbtInd>"
                f"<Sts>BOOK</Sts><BookgDt><Dt>{l['date']}</Dt></BookgDt><ValDt><Dt>{l['value_date']}</Dt></ValDt>"
                f"<AcctSvcrRef>{escape(l['event_id'][:35])}</AcctSvcrRef>"
                f"<BkTxCd><Prtry><Cd>{escape(l['event_type'][:35])}</Cd></Prtry></BkTxCd>"
                f"<NtryDtls><TxDtls><Refs><EndToEndId>{escape(l['key'][:35])}</EndToEndId></Refs>{counter}"
                f"<RmtInf><Ustrd>{escape(l['text'][:140])}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
        servicer = (f"<Svcr><FinInstnId><Nm>{escape(acct['servicer'])}</Nm></FinInstnId></Svcr>"
                    if acct.get("servicer") else "")
        name = f"<Nm>{escape(acct['name'])}</Nm>" if acct.get("name") else ""
        return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                f"<Document xmlns=\"{ns}\"><BkToCstmrStmt>"
                f"<GrpHdr><MsgId>{escape(stmt_id[:35])}</MsgId><CreDtTm>{now}</CreDtTm></GrpHdr>"
                f"<Stmt><Id>{escape(stmt_id[:35])}</Id><CreDtTm>{now}</CreDtTm>"
                f"<FrToDt><FrDtTm>{day}T00:00:00</FrDtTm><ToDtTm>{day}T23:59:59</ToDtTm></FrToDt>"
                f"<Acct><Id><Othr><Id>{escape(acct['id'][:34])}</Id></Othr></Id><Ccy>{escape(ccy)}</Ccy>{name}"
                f"{servicer}</Acct>{bal('OPBD', opening)}{bal('CLBD', closing)}"
                f"<TxsSummry><TtlNtries><NbOfNtries>{len(lines)}</NbOfNtries></TtlNtries></TxsSummry>"
                f"{''.join(entries)}</Stmt></BkToCstmrStmt></Document>\n")


# ── a calendar ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _ics_text(v: str) -> str:
    return (v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _fold(line: str) -> str:
    """RFC 5545: lines of at most 75 octets, continued with a space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 75:
            out.append(cur.decode("utf-8"))
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def _ics_time(v: Any) -> str:
    dt = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class CalendarSink(Sink):
    name = "calendar"
    description = "An ICS calendar file: one event per delivery (start, end, summary from the mapping)"
    config_schema = {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "pattern": r"\.ics$"},
            "name": {"type": "string"},
            "duration_minutes": {"type": "integer", "minimum": 1},
            "keep": {"type": "integer", "minimum": 1},
        },
    }

    def vevent(self, event: Event, key: str) -> Dict[str, str]:
        d = dict(event.data)
        try:
            start = _ics_time(d.get("start") or _when(event))
            end = _ics_time(d["end"]) if d.get("end") else _ics_time(
                datetime.strptime(start, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                + timedelta(minutes=int(self.config.get("duration_minutes") or 60)))
        except (ValueError, TypeError) as e:
            raise Refused(f"the event's start or end is not a time: {e}")
        return {"uid": f"{key}@theprotocol-proxy", "start": start, "end": end,
                "summary": str(d.get("summary") or event.event_type), "description": str(d.get("description") or ""),
                "location": str(d.get("location") or "")}

    def render(self, events: List[Mapping[str, str]]) -> str:
        stamp = _ics_time(datetime.now(timezone.utc))
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TheProtocol//Proxy//EN", "CALSCALE:GREGORIAN"]
        if self.config.get("name"):
            lines.append(f"X-WR-CALNAME:{_ics_text(self.config['name'])}")
        for e in events:
            lines += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{stamp}", f"DTSTART:{e['start']}",
                      f"DTEND:{e['end']}", f"SUMMARY:{_ics_text(e['summary'])}"]
            if e.get("description"):
                lines.append(f"DESCRIPTION:{_ics_text(e['description'])}")
            if e.get("location"):
                lines.append(f"LOCATION:{_ics_text(e['location'])}")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")
        return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        ve = self.vevent(event, key)
        if dry_run:
            return Outcome.dry(f"would put {ve['summary']!r} at {ve['start']} in the calendar", vevent=ve)
        events: List[Dict[str, str]] = [e for e in (await self.ctx.state.get("events") or []) if e["uid"] != ve["uid"]]
        events.append(ve)
        events = events[-int(self.config.get("keep") or 5000):]
        path = Path(self.config["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, self.render(events))
        await self.ctx.state.set("events", events)
        return Outcome.done(ve["uid"], f"in {path.name}")


# ── a digest mail ────────────────────────────────────────────────────────────────────────────────────────────────────

class EmailDigestSink(Sink):
    name = "email_digest"
    description = "Spools each event and mails a digest of them every interval (SMTP)"
    config_schema = {
        "type": "object",
        "required": ["smtp", "from", "to"],
        "additionalProperties": False,
        "properties": {
            "smtp": {"type": "object", "required": ["host"], "additionalProperties": False, "properties": {
                "host": {"type": "string"}, "port": {"type": "integer"}, "starttls": {"type": "boolean"},
                "ssl": {"type": "boolean"}, "username": {"type": "string"},
                "password": {"type": "string", "x-secret": True}}},
            "from": {"type": "string", "minLength": 3},
            "to": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 3}},
            "subject": {"type": "string"},
            "interval_s": {"type": "number", "minimum": 1},
            "max_events": {"type": "integer", "minimum": 1},
        },
    }

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self._task: Optional[asyncio.Task] = None
        self.sent = 0

    async def start(self) -> None:
        if not self.ctx.dry_run:
            self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        item = {"key": key, "at": _when(event).isoformat(), "event_type": event.event_type,
                "event_id": event.event_id, "data": dict(event.data)}
        if dry_run:
            return Outcome.dry("would add the event to the next digest", item=item)
        spool: List[Dict[str, Any]] = list(await self.ctx.state.get("spool") or [])
        if not any(i["key"] == key for i in spool):
            spool.append(item)
            await self.ctx.state.set("spool", spool)
        return Outcome.done(key, "in the next digest")

    def message(self, items: List[Mapping[str, Any]]) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.config["from"]
        msg["To"] = ", ".join(self.config["to"])
        msg["Subject"] = self.config.get("subject") or f"{self.ctx.proxy_name}: {len(items)} events"
        body = [f"{len(items)} events from {self.ctx.proxy_name} ({self.ctx.agent_did}):", ""]
        for i in items:
            data = ", ".join(f"{k}={v}" for k, v in sorted(i["data"].items()))
            body.append(f"{i['at']}  {i['event_type']}  {i['event_id']}  {data}")
        msg.set_content("\n".join(body) + "\n")
        return msg

    def _send(self, msg: EmailMessage) -> None:
        s = self.config["smtp"]
        port = int(s.get("port") or (465 if s.get("ssl") else 587))
        cls = smtplib.SMTP_SSL if s.get("ssl") else smtplib.SMTP
        with cls(s["host"], port, timeout=30) as smtp:
            if s.get("starttls") and not s.get("ssl"):
                smtp.starttls()
            if s.get("username"):
                smtp.login(s["username"], self.ctx.secret(s["password"]) if s.get("password") else "")
            smtp.send_message(msg)

    async def flush(self) -> int:
        """Mail what is spooled (up to max_events); answers how many were sent."""
        spool = list(await self.ctx.state.get("spool") or [])
        if not spool:
            return 0
        batch = spool[: int(self.config.get("max_events") or 500)]
        await asyncio.to_thread(self._send, self.message(batch))
        sent = {i["key"] for i in batch}
        rest = [i for i in (await self.ctx.state.get("spool") or []) if i["key"] not in sent]
        await self.ctx.state.set("spool", rest)
        self.sent += len(batch)
        return len(batch)

    async def _loop(self) -> None:
        interval = float(self.config.get("interval_s") or 3600)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the spool keeps the events for the next interval
                self.ctx.logger.warning("the digest could not be sent; it is tried again next interval",
                                        extra={"proxy": {"why": f"{type(e).__name__}: {e}"}})
