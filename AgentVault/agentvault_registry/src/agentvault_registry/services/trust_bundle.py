"""This registry's own trust bundle, read by trust domain (§MCPTEST30).

The cert-writer keeps `bundle.0.pem` in the registry's certificate directory: this frame's SPIRE roots and every
federated frame's. Each SPIRE root names its trust domain in a `spiffe://<td>` URI SAN, so the file answers "which
frames does this registry trust, and until when" with no Docker socket and no SPIRE container (V0561: the compliance
page's trust matrix; V0562: the Command Center's own-frame check). Pure readers over the file's text, plus its path.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CERT_PEM_RE = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL)


def bundle_path() -> str:
    """This registry's own trust bundle (its root and every federated frame's, written by its cert-writer)."""
    return os.path.join(os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs")), "bundle.0.pem")


def svid_path() -> str:
    """This registry's own X509-SVID (the leaf it presents on every mTLS hop)."""
    return os.path.join(os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs")), "svid.0.pem")


def _certs(pem_text: str):
    from cryptography import x509
    for block in CERT_PEM_RE.findall(pem_text or ""):
        try:
            yield x509.load_pem_x509_certificate(block.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — skip an unparseable cert, keep the rest
            logger.debug(f"[trust-bundle] cert skipped: {exc}")


def _trust_domains(cert) -> List[str]:
    from cryptography import x509
    try:
        uris = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.UniformResourceIdentifier)
    except Exception:  # noqa: BLE001 — no SAN: the certificate names no trust domain
        return []
    out = []
    for uri in uris:
        if uri.startswith("spiffe://"):
            td = uri[len("spiffe://"):].split("/", 1)[0].strip().lower()
            if td:
                out.append(td)
    return out


def ca_sets_by_trust_domain(pem_text: str) -> Dict[str, set]:
    """{trust domain: {sha256 fingerprints}} of the CA certificates in `pem_text`, each placed by the `spiffe://<td>`
    URI SAN a SPIRE CA carries. A certificate with no such SAN is skipped (it names no trust domain)."""
    from cryptography.hazmat.primitives import hashes
    out: Dict[str, set] = {}
    for cert in _certs(pem_text):
        for td in _trust_domains(cert):
            out.setdefault(td, set()).add(cert.fingerprint(hashes.SHA256()).hex().lower())
    return out


def ca_expiry_by_trust_domain(pem_text: str) -> Dict[str, datetime]:
    """{trust domain: the LATEST notAfter among its CAs}: how long this registry can still trust the frame if its
    rotation stopped today (SPIRE rotates roots with an overlap, so the newest one is the one that matters)."""
    out: Dict[str, datetime] = {}
    for cert in _certs(pem_text):
        try:
            not_after = cert.not_valid_after_utc
        except AttributeError:   # cryptography < 42
            not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
        for td in _trust_domains(cert):
            if td not in out or not_after > out[td]:
                out[td] = not_after
    return out


def leaf_not_after(pem_text: str) -> Optional[datetime]:
    """notAfter of the FIRST certificate in `pem_text` (an SVID file lists its leaf first)."""
    for cert in _certs(pem_text):
        try:
            return cert.not_valid_after_utc
        except AttributeError:   # cryptography < 42
            return cert.not_valid_after.replace(tzinfo=timezone.utc)
    return None


def read(path: str) -> Tuple[Optional[str], Optional[str]]:
    """(text, None) or (None, why it could not be read)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, f"{path} could not be read ({exc.strerror or exc})"
