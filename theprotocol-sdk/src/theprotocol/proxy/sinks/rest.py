"""The `rest` writer: each mapped record is sent to a system's HTTP API.

    sinks:
      crm:
        type: rest
        config:
          url: https://crm.example.org/api/customers/{id}   # {field} placeholders are filled from the mapped fields
          method: PUT                                       # POST (default), PUT or PATCH
          bearer: env:CRM_TOKEN                             # a reference, never the credential itself
          reference_path: $.data.uid                        # where the id the other side made is in its answer ($.id)

Unlike the webhook sink, which wraps a TheProtocol event in an envelope, the MAPPED FIELDS ARE THE BODY: a migration's mapping
already makes the shape the new system wants. A placeholder's value goes in the url URL-encoded (a missing or null one refuses
the record, naming the field); the field stays in the body too. The record's key goes out as an idempotency header
(`Idempotency-Key` by default; `idempotency_header: ""` sends none), which is how a system that keeps it makes a repeat a
no-op. Statuses are the webhook's: 2xx done; 408, 425, 429 and 5xx a Retry (Retry-After honoured); anything else a Refused
carrying up to 300 characters of the answer.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Mapping, Optional

import httpx

from ..plugins import Event, Outcome, PluginError, Refused, Retry, Sink
from ..registry import retry_after
from ..sinks_builtin import _CREDENTIAL_HEADERS
from ._json import dumps as _dumps
from ..spec import is_ref

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _at(doc: Any, path: str) -> Optional[str]:
    """A value of a JSON answer by a dotted path ($.id, $.data.uid): None when it is not there."""
    cur = doc
    for part in path.lstrip("$").lstrip(".").split("."):
        if not part:
            continue
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return None if cur is None or isinstance(cur, (Mapping, list)) else str(cur)


class RestSink(Sink):
    name = "rest"
    description = "Send each mapped record to a system's HTTP API: the fields are the body, the key the Idempotency-Key"
    config_schema = {
        "type": "object",
        "required": ["url"],
        "additionalProperties": False,
        "properties": {
            "url": {"type": "string", "pattern": r"^https?://[^/\s]+",
                    "description": "The address; {field} placeholders are filled from the mapped fields, URL-encoded."},
            "method": {"enum": ["POST", "PUT", "PATCH"]},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "bearer": {"type": "string", "x-secret": True},
            "timeout_s": {"type": "number", "exclusiveMinimum": 0},
            "idempotency_header": {"type": "string",
                                   "description": "The header that carries the record's key (default Idempotency-Key); "
                                                  "empty sends none."},
            "reference_path": {"type": "string",
                               "description": "Where the id the other side made is in its JSON answer (default $.id)."},
        },
    }
    #: tests set an httpx transport here
    transport: Optional[httpx.AsyncBaseTransport] = None

    async def start(self) -> None:
        for name, value in (self.config.get("headers") or {}).items():
            if str(name).lower() in _CREDENTIAL_HEADERS:
                raise PluginError(f"the rest sink's header {name} carries a credential: put it in bearer (a reference)")
            if is_ref(value):
                raise PluginError(f"the rest sink's header {name} names a reference: credentials go in bearer")
        header = self.config.get("idempotency_header")
        if header not in (None, "") and not _HEADER_NAME.match(str(header)):
            raise PluginError(f"the rest sink's idempotency_header {header!r} is not a header name")

    def _url(self, data: Mapping[str, Any]) -> str:
        def fill(m: "re.Match[str]") -> str:
            field = m.group(1)
            if field not in data or data[field] is None:
                raise Refused(f"the url names the field {field}, which this record does not carry")
            return urllib.parse.quote(str(data[field]), safe="")
        return _PLACEHOLDER.sub(fill, self.config["url"])

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        data = dict(event.data)
        url = self._url(data)
        method = self.config.get("method") or "POST"
        if dry_run:
            return Outcome.dry(f"would {method} {url}", method=method, url=url, body=json.loads(self._body(data)))
        headers = {"Content-Type": "application/json", "X-TheProtocol-Proxy": self.ctx.proxy_name,
                   **(self.config.get("headers") or {})}
        idem = self.config.get("idempotency_header", "Idempotency-Key")
        if idem:
            headers[idem] = key
        if self.config.get("bearer"):
            headers["Authorization"] = f"Bearer {self.ctx.secret(self.config['bearer'])}"
        try:
            async with httpx.AsyncClient(transport=type(self).transport,
                                         timeout=float(self.config.get("timeout_s") or 30)) as http:
                r = await http.request(method, url, content=self._body(data).encode("utf-8"), headers=headers)
        except httpx.TimeoutException as e:
            raise Retry(f"{self._where(self.config['url'])}: no answer in time ({type(e).__name__})") from None
        except httpx.HTTPError as e:
            raise Retry(f"{self._where(self.config['url'])}: could not be reached ({type(e).__name__})") from None
        st = r.status_code
        if 200 <= st < 300:
            ref = ""
            try:
                ref = _at(r.json(), self.config.get("reference_path") or "$.id") or ""
            except ValueError:
                pass
            return Outcome.done(ref or key, f"HTTP {st}", status=st)
        text = (r.text or "")[:300]
        if st in (408, 425, 429) or st >= 500:
            raise Retry(f"{self._where(self.config['url'])}: HTTP {st}: {text}", after=retry_after(r), status=st)
        raise Refused(f"{self._where(self.config['url'])}: HTTP {st}: {text}", status=st, answer=text)

    @staticmethod
    def _body(data: Mapping[str, Any]) -> str:
        return _dumps(data, sort_keys=True, ensure_ascii=False)     # a Decimal from a transform: its exact digits

    @staticmethod
    def _where(template: str) -> str:
        """The configured address, placeholders unfilled and without its query: what a record's values fill in is not what a
        log line or a dead letter should carry."""
        p = urllib.parse.urlsplit(template)
        return f"{p.scheme}://{p.netloc}{p.path}"
