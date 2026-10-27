"""§MTLSHOPS V0379 (2026-09-15): the store's outbound HTTPS calls present its SVID and trust the SPIRE bundle.

The store reads the registry's JWKS (EVENTSTORE_JWT_JWKS_URL) to verify the JWT-SVIDs its websocket clients present.
Today that URL is the registry's plain port. agentvault2-b5's registry terminator (b2) moves it behind nginx-registry,
which verifies client certificates, and a bare httpx.get presents nothing and trusts the system roots only.

client_tls_kwargs(url) is what httpx needs for one URL. It gives nothing for http, where TLS never happens, and nothing
when the store holds no SVID, which leaves httpx's default. Otherwise it gives one SSLContext that trusts the SPIRE bundle,
keeps the system roots (the replicator's dual trust of 2026-09-04) and carries the SVID key pair. It is built per call,
so a rotated SVID is read on the next fetch. A file that cannot be loaded raises, and the caller's own error path
reports it.
"""
import os
import ssl
from typing import Any, Dict


def client_tls_kwargs(url: str) -> Dict[str, Any]:
    if not (url or "").lower().startswith("https://"):
        return {}
    cert_dir = os.getenv("CERT_DIR", "/certs")
    cert_file = os.path.join(cert_dir, "svid.0.pem")
    key_file = os.path.join(cert_dir, "svid.0.key")
    bundle_file = os.path.join(cert_dir, "bundle.0.pem")
    if not (os.path.exists(cert_file) and os.path.exists(key_file)):
        return {}
    if os.path.exists(bundle_file):
        ctx = ssl.create_default_context(cafile=bundle_file)
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    else:
        ctx = ssl.create_default_context()
    ctx.load_cert_chain(cert_file, key_file)
    return {"verify": ctx}
