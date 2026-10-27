"""§PUSH (2026-10-06): a frame's public push vhost is SUBSCRIBE-ONLY by PATH, as the template renders it.

`limit_except GET` alone is not subscribe-only: ntfy publishes on GET too (<topic>/publish?message=, /send, /trigger,
measured 2026-09-15) and since v2.16 deletes and clears on GET (<topic>/<id>/delete|read|clear). The live EU/ASIA vhosts
carried the measured allowlist from 2026-09-29, while the template still rendered the method-only shape, so the next frame
stood up from it would have let anyone who learned a topic name push to a paired phone. These pin the template's shape
against the live one, and the certificate it serves.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))

import standup_extras as extras  # noqa: E402

PORTS = {"registry": 8350, "es": 8461, "spire_bundle": 8445, "push": 8399}
ALLOW = r'location ~ "^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$"'


def _blocks(text):
    """location -> its body, for the server's locations (one level of braces inside each)."""
    out, cur, depth, buf = {}, None, 0, []
    for line in text.splitlines():
        s = line.strip()
        if cur is None and s.startswith("location ") and s.endswith("{"):
            cur, depth, buf = s[:-1].strip(), 1, []
            continue
        if cur is not None:
            depth += s.count("{") - s.count("}")
            if depth <= 0:
                out[cur] = "\n".join(buf)
                cur = None
            else:
                buf.append(s)
    return out


def test_only_health_and_the_subscribe_streams_reach_ntfy():
    body = extras.render_vhost("push", "eu", PORTS)
    locs = _blocks(body)
    assert set(locs) == {"location = /v1/health", ALLOW, "location /"}, sorted(locs)
    for name in ("location = /v1/health", ALLOW):
        assert "proxy_pass http://127.0.0.1:8399;" in locs[name] and "limit_except GET { deny all; }" in locs[name]
    assert locs["location /"].strip() == "return 403;", "every other path, the GET publish forms included, is refused"
    assert body.count("proxy_pass") == 2


def test_the_allowlist_does_not_admit_a_publish_or_delete_form():
    rx = re.compile(r"^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$")
    for path in ("/alerts/json", "/a,b/sse", "/t/ws", "/t/raw", "/t/auth"):
        assert rx.match(path), path
    for path in ("/t/publish", "/t/send", "/t/trigger", "/t/abc123/delete", "/t/abc123/read", "/t/abc123/clear",
                 "/t", "/v1/account", "/t/json/x", "/../t/json"):
        assert not rx.match(path), path


def test_the_certificate_defaults_to_the_frames_own_and_can_be_named():
    own = extras.render_vhost("push", "eu", PORTS)
    assert "ssl_certificate     /etc/letsencrypt/live/eu.theprotocol.cloud/fullchain.pem;" in own
    named = extras.render_vhost("push", "sandbox-a", {**PORTS, "push": 8199}, cert_name="sandbox-a-push.theprotocol.cloud")
    assert "ssl_certificate_key /etc/letsencrypt/live/sandbox-a-push.theprotocol.cloud/privkey.pem;" in named
    assert "server_name sandbox-a-push.theprotocol.cloud;" in named and "proxy_pass http://127.0.0.1:8199;" in named
