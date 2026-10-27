"""§FRAMEPROV P5 (2026-09-13): the frame runner's DNS, the four names a frame's vhosts and certificate need.

His words 2026-09-13: "automation would be cool" (decision 4), then "push both, then go for p5". Before a standup the
runner creates an A record for each of the four hosts `standup_extras.issue_cert` puts on the certificate, marks each one
with a comment naming the frame and the job, and waits until the resolver answers them all. A teardown deletes only the
records whose ids the runner wrote down AND whose comment still carries its mark. A host that already has a record, or
already resolves without one, is refused and never adopted.

The credential is a narrow token of the runner's own (Zone · DNS · Edit on theprotocol.cloud, IP-restricted), read from
a root-only file on every call and never logged, printed or written anywhere else. Stdlib only, like the runner.
"""
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
MARK = "frame-runner:"


class DNSError(Exception):
    """The provider, the token or the resolver failed. The sentence names which, never the token."""


def names(name, domain):
    """The four hosts standup_extras.issue_cert puts on the frame's certificate, in its order (a driver test pins this
    against dns_readiness, so the two lists cannot drift)."""
    return [f"{name}.{domain}", f"{name}-es.{domain}", f"{name}-spire.{domain}", f"{name}-push.{domain}"]


def mark(name, job):
    return f"{MARK}{name}:{job}"


def carries_mark(record, name):
    return str(record.get("comment") or "").startswith(f"{MARK}{name}:")


def resolve(host, resolver="1.1.1.1", dig="dig", timeout=15):
    """The A and CNAME answers, asked the way standup_extras.issue_cert asks (`dig +short @1.1.1.1`)."""
    answers = []
    for rtype in ("A", "CNAME"):
        try:
            out = subprocess.run([dig, "+short", f"@{resolver}", host, rtype], capture_output=True, text=True,
                                 timeout=timeout).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        answers += [line.strip() for line in (out or "").splitlines() if line.strip() and not line.startswith(";")]
    return answers


class Cloudflare:
    """The four calls the runner needs, on one zone. Every error sentence carries the method, the path and Cloudflare's
    own error codes; the Authorization header is built per call and appears in nothing else."""

    def __init__(self, token_file, zone_id, api=API, timeout=20):
        self.token_file = token_file
        self.zone_id = zone_id
        self.api = api.rstrip("/")
        self.timeout = timeout

    def _token(self):
        """A bare token file, or certbot's credential file read in place (`dns_cloudflare_api_token = ...`). His word
        2026-09-13: the runner uses the token that already issues the operators' certificates, so there is one carrier
        and a rotation reaches both."""
        try:
            with open(self.token_file) as f:
                text = f.read()
        except OSError:
            raise DNSError(f"no readable Cloudflare token at {self.token_file} (root, 0600)")
        found = re.search(r"^\s*dns_cloudflare_api_token\s*=\s*(\S+)\s*$", text, re.M)
        token = found.group(1) if found else text.strip()
        if len(token) < 20 or any(c.isspace() for c in token):
            raise DNSError(f"{self.token_file} does not hold one Cloudflare token")
        return token

    @staticmethod
    def _errors(doc):
        errs = doc.get("errors") if isinstance(doc, dict) else None
        text = "; ".join(f"{e.get('code')} {e.get('message')}" for e in (errs or []) if isinstance(e, dict))
        return text[:300] or "no error detail"

    def _call(self, method, path, body=None):
        where = f"Cloudflare {method} {path.split('?')[0]}"
        request = urllib.request.Request(
            self.api + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                doc = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                doc = json.loads(exc.read() or b"{}")
            except ValueError:
                doc = {}
            raise DNSError(f"{where} answered HTTP {exc.code}: {self._errors(doc)}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise DNSError(f"{where} failed: {type(exc).__name__}")
        if not isinstance(doc, dict) or doc.get("success") is not True:
            raise DNSError(f"{where} refused: {self._errors(doc)}")
        return doc.get("result")

    def records(self, host):
        """Every record with exactly this name, of any type (an AAAA or CNAME blocks a host as surely as an A)."""
        query = urllib.parse.urlencode({"name": host, "per_page": 100})
        return self._call("GET", f"/zones/{self.zone_id}/dns_records?{query}") or []

    def create_a(self, host, ipv4, comment):
        return self._call("POST", f"/zones/{self.zone_id}/dns_records",
                          {"type": "A", "name": host, "content": ipv4, "ttl": 1, "proxied": False, "comment": comment})

    def delete(self, record_id):
        return self._call("DELETE", f"/zones/{self.zone_id}/dns_records/{urllib.parse.quote(str(record_id))}")
