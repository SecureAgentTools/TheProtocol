"""
A2A Payment Verifier — FastAPI middleware for agent-side payment enforcement.

Agents add this as a dependency to their A2A router. It verifies the
X-Payment-Token header against the issuing registry before allowing the request.

Supports cross-registry verification: if the token was issued by a different
registry (indicated via X-Payment-Issuer header), the verifier checks the
issuer against a trusted registries whitelist and verifies with that registry.

    verifier = PaymentVerifier(
        registry_url="https://api.theprotocol.cloud",
        agent_did="did:theprotocol:my-agent",
        required=True,
        min_amount="0.1",
        trusted_registries=["https://registry-b.theprotocol.cloud"],
    )
    router = create_a2a_router(agent, dependencies=[Depends(verifier)])
"""
import logging
import time
from collections import OrderedDict
from decimal import Decimal
from typing import Optional, Dict, Any, List

import httpx

try:
    from starlette.requests import Request as StarletteRequest
except ImportError:  # the SDK without its server extra
    StarletteRequest = Any  # type: ignore

logger = logging.getLogger(__name__)

# Bounded TTL cache: {cache_key: (result_dict, expire_time)}
_verify_cache: Dict[str, tuple] = {}
_CACHE_TTL = 5  # seconds — short to prevent replay of released tokens
_CACHE_MAX = 200  # max entries — prevents unbounded memory growth


class PaymentVerifier:
    """
    FastAPI dependency that verifies A2A payment tokens.

    On each incoming A2A request:
    1. Extracts X-Payment-Token and optional X-Payment-Issuer headers
    2. Determines which registry to verify against (local or issuer)
    3. Calls POST /api/v1/a2a-payment/verify on the issuing registry
    4. Validates response (valid, target matches, not expired)
    5. Stores payment info in request.state.payment

    Cross-registry flow:
    - Caller on Registry A gets token from Registry A
    - Caller sends to agent on Registry B with X-Payment-Issuer: https://api.theprotocol.cloud
    - Agent B's verifier sees issuer != local, checks trusted_registries whitelist
    - If trusted, verifies against Registry A's /a2a-payment/verify endpoint
    """

    def __init__(
        self,
        registry_url: str,
        agent_did: str,
        required: bool = True,
        min_amount: Optional[str] = None,
        cache_ttl: int = _CACHE_TTL,
        trusted_registries: Optional[List[str]] = None,
        reject_reused_tokens: bool = False,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.agent_did = agent_did
        self.required = required
        self.min_amount = Decimal(min_amount) if min_amount else None
        self.cache_ttl = cache_ttl
        # Build trusted set: always trust own registry + any explicitly listed
        self._trusted = {self.registry_url}
        if trusted_registries:
            for url in trusted_registries:
                self._trusted.add(url.rstrip("/"))
        # P25-001 refinement (opt-in): the registry deliberately keeps verify-on-CONSUMED
        # valid so legitimate retries of the SAME delivery work. Services that bill per
        # call can set reject_reused_tokens=True to refuse a token this PROCESS has
        # already accepted once (in-memory, bounded — not shared across replicas).
        self.reject_reused_tokens = reject_reused_tokens
        self._seen_tokens: "OrderedDict[str, float]" = OrderedDict()

    async def __call__(self, request: StarletteRequest) -> Dict[str, Any]:
        """FastAPI Depends() entry point.

        ``request`` must be annotated as a Request: FastAPI reads any other annotation as a query
        parameter, and until 0.7.6 (annotated ``Any``) every call through a router carrying this
        dependency was refused with 422 (the request "parameter" missing).
        """
        from fastapi import HTTPException

        token = (
            request.headers.get("X-Payment-Token")
            or request.headers.get("x-payment-token")
        )

        if not token:
            if self.required:
                raise HTTPException(status_code=402, detail="Payment Required — include X-Payment-Token header")
            request.state.payment = {"verified": False}
            return {"verified": False}

        # Determine issuing registry
        issuer = (
            request.headers.get("X-Payment-Issuer")
            or request.headers.get("x-payment-issuer")
            or ""
        ).rstrip("/")

        if issuer and issuer != self.registry_url:
            # Cross-registry token — check whitelist
            if issuer not in self._trusted:
                if self.required:
                    raise HTTPException(402, f"Payment issuer not trusted: {issuer}")
                request.state.payment = {"verified": False, "error": "untrusted_issuer"}
                return {"verified": False}
            verify_url = issuer
        else:
            verify_url = self.registry_url

        # Check cache (bounded, short TTL)
        cache_key = f"{verify_url}:{token}"
        now = time.time()
        cached = _verify_cache.get(cache_key)
        if cached and cached[1] > now:
            result = cached[0]
        else:
            result = await self._verify_with_registry(verify_url, token)
            if result.get("valid"):
                # Prune if at capacity
                if len(_verify_cache) >= _CACHE_MAX:
                    expired = [k for k, v in _verify_cache.items() if v[1] <= now]
                    for k in expired:
                        del _verify_cache[k]
                    if len(_verify_cache) >= _CACHE_MAX:
                        _verify_cache.clear()
                _verify_cache[cache_key] = (result, now + self.cache_ttl)

        if not result.get("valid"):
            if self.required:
                raise HTTPException(
                    status_code=402,
                    detail=f"Payment token invalid: {result.get('error', 'verification failed')}",
                )
            request.state.payment = {"verified": False, "error": result.get("error")}
            return {"verified": False}

        # Verify target DID
        if result.get("target_agent_did") != self.agent_did:
            if self.required:
                raise HTTPException(402, "Payment token not issued for this agent")
            request.state.payment = {"verified": False, "error": "wrong_target"}
            return {"verified": False}

        # Check minimum amount
        if self.min_amount and Decimal(result.get("amount", "0")) < self.min_amount:
            if self.required:
                raise HTTPException(402, f"Payment insufficient: {result['amount']} < {self.min_amount}")
            request.state.payment = {"verified": False, "error": "insufficient_amount"}
            return {"verified": False}

        # Opt-in single-use enforcement (this process only; see __init__ note).
        if self.reject_reused_tokens:
            seen_key = result.get("token_id") or token
            if seen_key in self._seen_tokens:
                if self.required:
                    raise HTTPException(402, "Payment token already used for a delivered task (reject_reused_tokens)")
                request.state.payment = {"verified": False, "error": "token_reused"}
                return {"verified": False}
            self._seen_tokens[seen_key] = now
            while len(self._seen_tokens) > 5000:
                self._seen_tokens.popitem(last=False)

        payment_info = {
            "verified": True,
            "token": token,
            "token_id": result.get("token_id"),
            "caller_did": result.get("caller_did"),
            "target_agent_did": result.get("target_agent_did"),
            "amount": result.get("amount"),
            "contract_id": result.get("contract_id"),
            "issuer_registry": verify_url,
        }
        request.state.payment = payment_info
        return payment_info

    async def _verify_with_registry(self, registry_url: str, token: str) -> dict:
        """Call a registry's verify endpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{registry_url}/api/v1/a2a-payment/verify",
                    json={"token": token, "target_agent_did": self.agent_did},
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"valid": False, "error": f"Registry returned {resp.status_code}"}
        except Exception as e:
            logger.error(f"[PaymentVerifier] Verification failed ({registry_url}): {e}")
            return {"valid": False, "error": str(e)}
