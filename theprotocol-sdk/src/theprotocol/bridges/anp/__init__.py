"""
ANP (Agent Network Protocol) ↔ A2A Bridge.

ANP spec: https://agent-network-protocol.com/specs/
Wire format: JSON-RPC 2.0 over HTTPS with DIDWba authentication

Components:
  - did_wba: DID:WBA method implementation (create, resolve, sign, verify)
  - auth: DIDWba Authorization header creation and verification
  - translation: ANP ↔ A2A message/agent description conversion
  - bridge: ANPBridge class with FastAPI router factory
"""

from .bridge import ANPBridge
from .did_wba import (
    DIDDocument, KeyPair, create_did_wba, resolve_did_wba,
    did_wba_from_cos, native_did_from_wba,
)
from .auth import create_didwba_auth_header, verify_didwba_auth_header

__all__ = [
    "ANPBridge",
    "DIDDocument", "KeyPair", "create_did_wba", "resolve_did_wba",
    "did_wba_from_cos", "native_did_from_wba",
    "create_didwba_auth_header", "verify_didwba_auth_header",
]
