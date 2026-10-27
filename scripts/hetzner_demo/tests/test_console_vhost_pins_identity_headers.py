"""§FRAMELIC findings row 194 — the console vhost must pin every header the app treats as proof.

`mtls_auth.get_client_spiffe_id` parses `X-SSL-Client-Cert` OUT OF THE REQUEST HEADERS and trusts
the SPIFFE ID inside it. There is no CA verification on that path and no check of
`X-SSL-Client-Verify`: the certificate is believed because it arrived in a header. That is safe
only while the edge guarantees a client cannot supply it.

The frame template pinned none of them, so every frame it stood up accepted a SELF-SIGNED
certificate presented in a plain header as proof of identity, on public 443, for every route
guarded by `get_federation_identity` — federation sync, card sync, the token bridge, exchange
federation, chat federation, the mail relay, agent delegation, and `/teg/fx/route-hop`, which
moves money.

PROVEN on EU 2026-09-07 with a deliberately UNTRUSTED trust domain, so it could demonstrate the
hole without exercising it: the app answered "Client SPIFFE ID from untrusted domain", meaning it
had already parsed and accepted the header as a client certificate. A trusted domain in the SAN
would have authenticated. registry-a's vhost has pinned these headers since it was written — the
fresh cluster was born without it, which is this session's recurring class: a protection that
lives on the old nodes and in no template.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TMPL = (REPO / "templates/frame-test/vhosts/console.conf.tmpl").read_text()

# The headers the app will believe if it is handed them. Each must be OVERWRITTEN by the edge —
# either from the real nginx variable (so a client value cannot survive) or cleared outright.
IDENTITY_HEADERS = {
    "X-SSL-Client-Cert": "$ssl_client_escaped_cert",
    "X-SSL-Client-Verify": "$ssl_client_verify",
    "X-SSL-Client-S-DN": "$ssl_client_s_dn",
}
BEARER_HEADERS = ("X-Federation-Secret", "X-Federation-SPIFFE-ID", "X-Federation-License")


def _catch_all_block() -> str:
    """The `location / {}` that PROXIES everything, including /api/v1 — the one an internet
    request actually lands in.

    ⚠ There are two `location / {` in this file: the port-80 server's
    `return 301 https://...` and the real one. The first draft took the first match and went red
    against the fixed template as well as the broken one — a gate that fails everywhere is as
    useless as one that passes everywhere. Select by what the block DOES.
    """
    blocks = []
    for i in range(len(TMPL)):
        if not TMPL.startswith("location / {", i):
            continue
        depth = 0
        for j in range(i, len(TMPL)):
            if TMPL[j] == "{":
                depth += 1
            elif TMPL[j] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(TMPL[i:j + 1])
                    break
    proxying = [b for b in blocks if "proxy_pass" in b]
    assert len(proxying) == 1, f"expected exactly one proxying `location /`, found {len(proxying)}"
    return proxying[0]


def test_the_certificate_headers_are_set_from_nginx_not_the_client():
    block = _catch_all_block()
    for header, variable in IDENTITY_HEADERS.items():
        assert re.search(rf"proxy_set_header\s+{re.escape(header)}\s+{re.escape(variable)}\s*;", block), (
            f"{header} is not pinned to {variable} in the console catch-all — a client-supplied "
            f"value would reach the app, and the app believes it"
        )


def test_the_shared_bearer_headers_are_cleared():
    block = _catch_all_block()
    for header in BEARER_HEADERS:
        assert re.search(rf'proxy_set_header\s+{re.escape(header)}\s+""\s*;', block), (
            f"{header} is not cleared in the console catch-all — the internal-secret rail would "
            f"be presentable from the public host"
        )


def test_the_pinning_is_in_the_block_that_proxies_the_api():
    """The control on the control: it is only worth pinning in the location an API request
    actually lands in. If /api/ ever gets its own location, this test must move with it."""
    block = _catch_all_block()
    assert "proxy_pass" in block
    assert "{{PORT_REGISTRY}}" in block, "the catch-all must be the one proxying to the registry"
    # and nothing else in the file may proxy to the registry without the same pinning
    others = [b for b in re.findall(r"location [^\{]*\{[^}]*\}", TMPL, flags=re.S)
              if "{{PORT_REGISTRY}}" in b and "proxy_pass" in b and "X-SSL-Client-Cert" not in b]
    # the websocket locations proxy to the registry too, but a WS upgrade cannot carry a
    # federation-authed REST call; assert we have LOOKED at them rather than that there are none
    for b in others:
        assert "Upgrade" in b or "/mcp/" in b or "/directory/" in b, (
            "a non-websocket location proxies to the registry without pinning the identity "
            f"headers: {b[:120]}"
        )
