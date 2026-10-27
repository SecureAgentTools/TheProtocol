"""§DEPS (2026-09-27): a client certificate travels INSIDE the SSLContext httpx is given as `verify`.

httpx 0.28 builds a connection's context from `verify` and `cert`, and when `verify` is a CA file or directory PATH
it returns the context built from that path BEFORE it reaches the client-certificate step: `cert=` is dropped, and
the only trace is a DeprecationWarning, hidden by default. Every mTLS client here that passed the SPIRE bundle path
and the SVID pair would dial a peer that requires a client certificate with none. (Measured: a client built with a
CA path and a certificate that does not exist builds without error on 0.28; on 0.27 it refuses, because it reads it.)

A context that already holds the chain is honoured by every httpx version and is the only form httpx 1.0 accepts.
Only that one combination is converted; `verify` True, False or an SSLContext beside a certificate is left as it is,
because httpx 0.28 still loads the certificate in those cases.
"""
from __future__ import annotations

import os
import ssl
from typing import Any


def client_cert_verify(verify: Any, cert: Any) -> Any:
    """What to pass as httpx `verify=` beside a client `cert`.

    `verify` is a CA path and `cert` is set: an SSLContext that verifies the server against that path (exactly the
    context httpx 0.28 builds from a path) and presents `cert`. Any other combination: `verify` unchanged.
    """
    if not cert or not isinstance(verify, str):
        return verify
    ctx = ssl.create_default_context(capath=verify) if os.path.isdir(verify) else ssl.create_default_context(cafile=verify)
    if isinstance(cert, (tuple, list)):
        ctx.load_cert_chain(*cert)  # (certfile, keyfile) or (certfile, keyfile, password), as httpx takes them
    else:
        ctx.load_cert_chain(cert)
    return ctx
