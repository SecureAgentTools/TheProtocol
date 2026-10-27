"""
TEG Layer Client for Registry Integration

This client enables the Registry Layer to communicate with the TEG Layer
for token balance queries and lock/unlock operations during staking.

Created as part of the staking integration fix.
"""
import asyncio
import os
import httpx
from typing import Optional, Dict, Any, Union
from decimal import Decimal
from pydantic import BaseModel
import logging

from .es_ssl_helper import get_httpx_verify, spire_trust_loaded, svid_stamp

logger = logging.getLogger(__name__)


class TEGClientError(Exception):
    """Base exception for TEG client errors"""
    pass


class TEGAuthError(TEGClientError):
    """Authentication error with TEG Layer"""
    pass


class TEGBalanceError(TEGClientError):
    """Balance-related error from TEG Layer"""
    pass


class TokenLockResponse(BaseModel):
    """Response from token lock operation"""
    transaction_id: str
    agent_id: str
    amount: Decimal
    locked: bool
    new_available_balance: Decimal
    new_locked_balance: Decimal
    

class TokenUnlockResponse(BaseModel):
    """Response from token unlock operation"""
    transaction_id: str
    agent_id: str
    amount: Decimal
    unlocked: bool
    new_available_balance: Decimal
    new_locked_balance: Decimal


class TEGClient:
    """
    Client for interacting with the TEG Layer API.
    
    This client handles:
    - Token balance queries
    - Token locking for staking
    - Token unlocking for unstaking
    - Authentication token management
    """
    
    def __init__(self, base_url: str = "http://teg-layer:8080"):
        """
        Initialize TEG client.

        Args:
            base_url: Base URL of the TEG Layer service (defaults to Docker service name)
        """
        self.base_url = base_url.rstrip('/')
        self.api_prefix = "/api/v1"
        # §pass69.6 — backing storage for the self-healing _client property below.
        # Deferred construction so the first access (after SVID is on disk) builds
        # the client with a valid SSL context.
        self._client_instance: Optional[httpx.AsyncClient] = None
        self._client_stamp: tuple = ()

    @property
    def _client(self) -> httpx.AsyncClient:
        # §pass69.6 — Closes the gap left by §pass69.2.
        # §pass69.2 added `verify=get_httpx_verify()` to the AsyncClient but the
        # client was still built ONCE in __init__ and bound the SSL context at
        # construction. After the first SPIRE SVID rotation (~4h TTL, cert-writer
        # refreshes every ~5 min) the cached client kept presenting the original
        # cert and nginx-teg's `ssl_verify_client on` rejected every call with
        # `400 The SSL certificate error` — silently killing the daily staking
        # distributor until the process restarted.
        # Mirrors the mtime self-healing pattern in routers/teg_integration.py
        # :_get_teg_client. As a property, it transparently fixes every cached
        # reference (e.g. services/staking_rewards_service.py captures the
        # singleton TEGClient at service-init time, so a singleton-level fix
        # alone would not reach those holders).
        # §SVIDRACE (V0639): keyed on the cert, the key and the bundle, and recorded only for a SPIRE context (the
        # rule of routers/teg_integration._get_teg_client).
        stamp = svid_stamp()

        rotated = (
            bool(stamp)
            and stamp != self._client_stamp
            and self._client_instance is not None
        )
        if rotated:
            try:
                asyncio.get_running_loop().create_task(self._client_instance.aclose())
            except RuntimeError:
                pass
            self._client_instance = None

        if self._client_instance is None or self._client_instance.is_closed:
            verify = get_httpx_verify()
            self._client_instance = httpx.AsyncClient(
                timeout=30.0,
                verify=verify,
            )
            self._client_stamp = stamp if spire_trust_loaded(verify, stamp) else ()
        return self._client_instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close the HTTP client"""
        # §pass69.6 — use the underlying instance directly so we don't trigger
        # the property to build a fresh client just to close it.
        if self._client_instance is not None and not self._client_instance.is_closed:
            await self._client_instance.aclose()
            self._client_instance = None
        
    def get_service_token(self) -> str:
        """
        Get the Registry service token for authenticating with TEG.
        
        Returns:
            Service token for Registry-to-TEG communication
        """
        # Read from environment so rotation doesn't break this.
        # Falls back to old hardcoded value only if env var is missing.
        return os.environ.get(
            'TEG_ADMIN_API_KEY',
            ''
        )

    async def get_balance(self, agent_did: str) -> Decimal:
        """
        Get the available (unlocked) token balance for an agent.
        
        Args:
            agent_did: DID of the agent
            
        Returns:
            Available token balance
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            # Use service token for Registry-to-TEG communication
            service_token = self.get_service_token()
            
            # Make request to TEG using the tokenomics balance endpoint
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/tokenomics/balance/{agent_did}",
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                # TEG returns balance field
                return Decimal(str(data.get("balance", 0)))
            else:
                logger.error(f"TEG balance query failed: {response.status_code} - {response.text}")
                raise TEGBalanceError(f"Failed to get balance: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
            
    async def check_reputation_signal(self, transaction_id: str, agent_did: str) -> Dict[str, Any]:
        """Check if an agent has already submitted a reputation signal for a transaction.
        
        Args:
            transaction_id: The TEG Layer transaction ID
            agent_did: DID of the agent to check
            
        Returns:
            Dictionary with signal status and details
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            service_token = self.get_service_token()
            
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/reputation/signal/{transaction_id}/{agent_did}",
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "has_signaled": data.get("has_signaled", False),
                    "signal_value": data.get("signal_value"),
                    "signal_timestamp": data.get("signal_timestamp"),
                    "can_signal": data.get("can_signal", False),
                    "reason": data.get("reason", "")
                }
            elif response.status_code == 404:
                # Transaction not found
                return {
                    "error": "Transaction not found",
                    "has_signaled": False,
                    "can_signal": False
                }
            else:
                logger.error(f"TEG reputation signal check failed: {response.status_code}")
                return {
                    "error": f"Failed to check signal: {response.status_code}",
                    "has_signaled": False,
                    "can_signal": False
                }
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
            
    async def submit_reputation_signal(self, transaction_id: str, signal_value: int, agent_did: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Submit a reputation signal for a transaction.
        
        Args:
            transaction_id: The TEG Layer transaction ID
            signal_value: +1 or -1
            agent_did: DID of the agent submitting the signal
            reason: Optional reason for the signal
            
        Returns:
            Dictionary with submission result
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            service_token = self.get_service_token()
            
            request_body = {
                "transaction_id": transaction_id,
                "signal_value": signal_value,
                "agent_did": agent_did
            }
            if reason:
                request_body["reason"] = reason
            
            response = await self._client.post(
                f"{self.base_url}{self.api_prefix}/reputation/signal",
                json=request_body,
                headers={
                    "X-Service-Token": service_token,
                    "X-Agent-DID": agent_did
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "transaction_id": transaction_id,
                    "signal_value": signal_value,
                    "affected_agent_did": data.get("affected_agent_did"),
                    "new_reputation_score": data.get("new_reputation_score"),
                    "timestamp": data.get("timestamp")
                }
            elif response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get("detail", "Bad request")
                return {
                    "success": False,
                    "error": error_msg
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "error": "Not authorized - only transaction sender can submit signals"
                }
            elif response.status_code == 404:
                return {
                    "success": False,
                    "error": "Transaction not found"
                }
            elif response.status_code == 409:
                return {
                    "success": False,
                    "error": "Already signaled this transaction"
                }
            else:
                logger.error(f"TEG reputation signal submission failed: {response.status_code}")
                return {
                    "success": False,
                    "error": f"Failed to submit signal: {response.status_code}"
                }
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
    
    async def stake_tokens(self, agent_id: str, amount: Decimal) -> Dict[str, Any]:
        """Stake tokens (wrapper around lock_tokens for compatibility)"""
        result = await self.lock_tokens(agent_id, amount)
        return {
            "stake_id": result.transaction_id,
            "transaction_id": result.transaction_id
        }
    
    async def unstake_tokens(self, agent_id: str, amount: Decimal) -> Dict[str, Any]:
        """Unstake tokens (wrapper around unlock_tokens for compatibility)"""
        result = await self.unlock_tokens(agent_id, amount)
        return {
            "transaction_id": result.transaction_id
        }

    async def fund_reward(
        self,
        agent_did: str,
        amount: Union[float, str, Decimal],
        reason: str,
        reference_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fund a reward via the configured waterfall (Phase 2, 2026-05-08).

        Replaces direct calls to /admin/treasury/transfer for reward / grant
        flows. The TEG resolves the per-reason waterfall policy and drains
        sources in order (typically fee_collector → treasury). Returns a
        legs[] list describing exactly which sources contributed.

        Args:
            agent_did: target agent DID
            amount: amount to fund (str/Decimal preserve precision; float
                accepted for legacy callers, converted via str())
            reason: looked up in the waterfall policy. Common reasons:
                staking_reward / dispute_compensation / tutorial_grant /
                achievement / funding_request / admin_grant
            reference_id: external correlation ID (distribution_id, dispute_id, …)
            idempotency_key: deterministic per-logical-op key — the TEG
                endpoint dedups on it, so a retried call pays exactly once
                (§REWARDEVENTS 2026-08-11)

        Returns:
            TEG response dict. Keys: status ("completed"|"exhausted"),
            funded_amount, shortfall, legs, new_target_balance, waterfall_used.

        Raises:
            TEGClientError: on connection failure or HTTP 400 with shortfall
            (the caller can inspect e.teg_response for partial-fund context).
        """
        admin_key = os.environ.get('TEG_ADMIN_API_KEY', '')
        payload: Dict[str, Any] = {
            "target_agent_id": agent_did,
            "amount": str(amount),
            "reason": reason,
        }
        if reference_id:
            payload["reference_id"] = reference_id
        headers = {"Authorization": f"Bearer {admin_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        try:
            response = await self._client.post(
                f"{self.base_url}{self.api_prefix}/admin/reward-fund",
                json=payload,
                headers=headers,
                timeout=30.0,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    f"[TEGClient.fund_reward] Funded {amount} AVT to {agent_did} "
                    f"(reason: {reason}, status: {data.get('status', '?')}, "
                    f"legs: {len(data.get('legs', []))})"
                )
                return data
            elif response.status_code == 400:
                # Check if it's an exhaustion (partial funding) vs hard error
                try:
                    body = response.json()
                except Exception:
                    body = {"detail": response.text[:300]}
                if body.get("status") == "exhausted":
                    logger.warning(
                        f"[TEGClient.fund_reward] EXHAUSTED for {agent_did}: "
                        f"funded {body.get('funded_amount')} of {body.get('total_amount')} "
                        f"(shortfall: {body.get('shortfall')}, waterfall: {body.get('waterfall_used')})"
                    )
                    err = TEGClientError(
                        f"fund_reward exhausted for {agent_did}: "
                        f"shortfall={body.get('shortfall')} of {body.get('total_amount')}"
                    )
                    err.teg_status_code = 400  # type: ignore[attr-defined]
                    err.teg_response = body  # type: ignore[attr-defined]
                    raise err
                logger.error(
                    f"[TEGClient.fund_reward] TEG rejected for {agent_did}: 400 — {body}"
                )
                err = TEGClientError(
                    f"fund_reward failed for {agent_did}: HTTP 400 — {body.get('detail', body)}"
                )
                err.teg_status_code = 400  # type: ignore[attr-defined]
                err.teg_response = body  # type: ignore[attr-defined]
                raise err
            else:
                error_body = response.text[:300]
                logger.error(
                    f"[TEGClient.fund_reward] TEG rejected for {agent_did}: "
                    f"{response.status_code} — {error_body}"
                )
                raise TEGClientError(
                    f"fund_reward failed for {agent_did}: "
                    f"HTTP {response.status_code} — {error_body}"
                )

        except httpx.RequestError as e:
            logger.error(
                f"[TEGClient.fund_reward] Connection error for {agent_did}: {e}"
            )
            raise TEGClientError(
                f"Failed to connect to TEG Layer for fund_reward: {e}"
            )

    async def issue_tokens(
        self,
        agent_did: str,
        amount: float,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Issue tokens to an agent from the TEG treasury.

        Used exclusively by StakingRewardsService for daily reward distribution.
        Calls POST /api/v1/admin/treasury/transfer using TEG_ADMIN_API_KEY.
        Same TEG endpoint used by teg_integration.py::fund_agent_from_treasury().

        Args:
            agent_did: DID of the agent to receive tokens
            amount: Amount to issue (float, converted to string for TEG)
            reason: Human-readable reason (e.g. "Staking reward distribution for 2026-03-09")
            metadata: Optional dict; distribution_id extracted as reference_id if present

        Returns:
            TEG response dict, expected keys: transaction_id, new_target_balance

        Raises:
            TEGClientError: If TEG rejects the request or is unreachable
        """
        admin_key = os.environ.get(
            'TEG_ADMIN_API_KEY',
            ''
        )

        # Build reference_id from metadata if provided
        reference_id = None
        if metadata:
            reference_id = metadata.get('distribution_id')

        payload: Dict[str, Any] = {
            "target_agent_id": agent_did,
            "amount": str(amount),
            "reason": reason,
        }
        if reference_id:
            payload["reference_id"] = reference_id

        try:
            response = await self._client.post(
                f"{self.base_url}{self.api_prefix}/admin/treasury/transfer",
                json=payload,
                headers={"Authorization": f"Bearer {admin_key}"},
                timeout=15.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    f"[TEGClient.issue_tokens] Issued {amount} AVT to {agent_did} "
                    f"(tx: {data.get('transaction_id', '?')})"
                )
                return data
            else:
                error_body = response.text[:300]
                logger.error(
                    f"[TEGClient.issue_tokens] TEG rejected issue for {agent_did}: "
                    f"{response.status_code} — {error_body}"
                )
                raise TEGClientError(
                    f"issue_tokens failed for {agent_did}: "
                    f"HTTP {response.status_code} — {error_body}"
                )

        except httpx.RequestError as e:
            logger.error(
                f"[TEGClient.issue_tokens] Connection error for {agent_did}: {e}"
            )
            raise TEGClientError(
                f"Failed to connect to TEG Layer for issue_tokens: {e}"
            )
    
    async def get_pending_rewards(self, agent_did: str) -> Dict[str, Any]:
        """Get pending rewards for an agent.
        
        Args:
            agent_did: DID of the agent
            
        Returns:
            Dictionary with pending rewards information
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            service_token = self.get_service_token()
            
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/tokenomics/rewards/{agent_did}",
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "pending_rewards": Decimal(str(data.get("pending_rewards", 0))),
                    "last_claim_timestamp": data.get("last_claim_timestamp"),
                    "reward_sources": data.get("reward_sources", [])
                }
            elif response.status_code == 404:
                # No rewards found is not an error
                return {"pending_rewards": Decimal("0")}
            else:
                logger.error(f"TEG pending rewards query failed: {response.status_code}")
                raise TEGClientError(f"Failed to get pending payouts: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
    
    async def get_recent_transactions(self, agent_did: str, limit: int = 10) -> list:
        """Get recent transactions for an agent.
        
        Args:
            agent_did: DID of the agent
            limit: Maximum number of transactions to return
            
        Returns:
            List of recent transactions
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            service_token = self.get_service_token()
            
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/tokenomics/transactions/{agent_did}",
                params={"limit": limit},
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                transactions = data.get("transactions", [])
                
                # Format transactions for consistency
                formatted_transactions = []
                for tx in transactions:
                    formatted_tx = {
                        "transaction_id": tx.get("transaction_id"),
                        "type": tx.get("transaction_type", "transfer"),
                        "amount": str(tx.get("amount", 0)),
                        "sender": tx.get("sender_agent_id"),
                        "receiver": tx.get("receiver_agent_id"),
                        "timestamp": tx.get("timestamp"),
                        "status": tx.get("status", "completed"),
                        "fee": str(tx.get("fee_amount", 0)),
                        "message": tx.get("attached_message")
                    }
                    formatted_transactions.append(formatted_tx)
                
                return formatted_transactions
            elif response.status_code == 404:
                # No transactions found is not an error
                return []
            else:
                logger.error(f"TEG transactions query failed: {response.status_code}")
                raise TEGClientError(f"Failed to get transactions: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
    
    async def get_treasury_info(self) -> Dict[str, Any]:
        """Get treasury information.
        
        Returns:
            Dictionary with treasury metrics
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            service_token = self.get_service_token()
            
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/tokenomics/treasury",
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "total_supply": str(data.get("total_supply", 0)),
                    "circulating_supply": str(data.get("circulating_supply", 0)),
                    "treasury_balance": str(data.get("treasury_balance", 0)),
                    "locked_supply": str(data.get("locked_supply", 0)),
                    "burned_supply": str(data.get("burned_supply", 0)),
                    "reward_pool": str(data.get("reward_pool", 0)),
                    "last_updated": data.get("last_updated")
                }
            else:
                # §MONEY-R27: this used to return INVENTED supply figures (1000000 /
                # 500000 / 300000) whenever the TEG could not answer. A supply surface that
                # fabricates when it cannot read is worse than one that fails: two public
                # routers serve this straight through, so "could not check" was rendered as a
                # confident, specific, wrong answer about how much money exists. Every OTHER
                # method on this client already raises TEGClientError — this one was the outlier.
                logger.error(f"TEG treasury query failed: {response.status_code}")
                raise TEGClientError(
                    f"TEG treasury query failed with status {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
            
    async def get_locked_balance(self, agent_did: str) -> Decimal:
        """
        Get the locked token balance for an agent.
        
        Args:
            agent_did: DID of the agent
            
        Returns:
            Locked token balance
            
        Raises:
            TEGClientError: If the request fails
        """
        try:
            # Use service token for Registry-to-TEG communication
            service_token = self.get_service_token()
            
            # Make request to TEG using the tokenomics balance endpoint
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/tokenomics/balance/{agent_did}",
                headers={
                    "X-Service-Token": service_token
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return Decimal(str(data.get("locked_balance", 0)))
            else:
                logger.error(f"TEG locked balance query failed: {response.status_code}")
                raise TEGBalanceError(f"Failed to get locked balance: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
            
    async def lock_tokens(self, agent_did: str, amount: Decimal) -> TokenLockResponse:
        """
        Lock tokens for staking.
        
        Args:
            agent_did: DID of the agent
            amount: Amount to lock
            
        Returns:
            Lock operation response
            
        Raises:
            TEGClientError: If the request fails
            TEGBalanceError: If insufficient balance
        """
        try:
            # Use service token for Registry-to-TEG communication
            service_token = self.get_service_token()
            
            # Make request to TEG
            response = await self._client.post(
                f"{self.base_url}{self.api_prefix}/tokenomics/lock",
                json={
                    "agent_did": agent_did,
                    "amount": str(amount),
                    "purpose": "staking"
                },
                headers={
                    "X-Service-Token": service_token,
                    "X-Agent-DID": agent_did
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return TokenLockResponse(**data)
            elif response.status_code == 400:
                error_data = response.json()
                # TEG Layer uses 'detail' field for error messages
                error_msg = error_data.get('detail') or error_data.get('message', 'Unknown error')
                if "insufficient" in str(error_msg).lower():
                    raise TEGBalanceError(f"Insufficient balance for locking: {error_msg}")
                raise TEGClientError(f"Lock request failed: {error_msg}")
            else:
                logger.error(f"TEG lock request failed: {response.status_code}")
                raise TEGClientError(f"Failed to lock units: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")
            
    async def get_locked_balance_admin(self, agent_did: str) -> Decimal:
        """§V0045 F2 — admin-key read of an agent's TEG locked_balance.

        Backs the staking reconciliation job (registry staked ↔ TEG locked drift);
        the agent-auth /tokenomics/locked_balance can't serve service-side recon.
        """
        import os as _os
        admin_key = _os.getenv("TEG_ADMIN_API_KEY", "")
        try:
            response = await self._client.get(
                f"{self.base_url}{self.api_prefix}/admin/agent-locked-balance",
                params={"agent_id": agent_did},
                headers={"Authorization": f"Bearer {admin_key}"},
            )
            if response.status_code == 200:
                return Decimal(str(response.json().get("locked_balance", "0")))
            raise TEGClientError(
                f"locked-balance read failed for {agent_did}: HTTP {response.status_code}"
            )
        except httpx.RequestError as e:
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")

    async def unlock_tokens(self, agent_did: str, amount: Decimal) -> TokenUnlockResponse:
        """
        Unlock tokens from staking.
        
        Args:
            agent_did: DID of the agent
            amount: Amount to unlock
            
        Returns:
            Unlock operation response
            
        Raises:
            TEGClientError: If the request fails
            TEGBalanceError: If insufficient locked balance
        """
        try:
            # Use service token for Registry-to-TEG communication
            service_token = self.get_service_token()
            
            # Make request to TEG
            response = await self._client.post(
                f"{self.base_url}{self.api_prefix}/tokenomics/unlock",
                json={
                    "agent_did": agent_did,
                    "amount": str(amount),
                    "purpose": "unstaking"
                },
                headers={
                    "X-Service-Token": service_token,
                    "X-Agent-DID": agent_did
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return TokenUnlockResponse(**data)
            elif response.status_code == 400:
                error_data = response.json()
                # TEG Layer uses 'detail' field for error messages
                error_msg = error_data.get('detail') or error_data.get('message', 'Unknown error')
                if "insufficient" in str(error_msg).lower():
                    raise TEGBalanceError(f"Insufficient locked balance for unlocking: {error_msg}")
                raise TEGClientError(f"Unlock request failed: {error_msg}")
            else:
                logger.error(f"TEG unlock request failed: {response.status_code}")
                raise TEGClientError(f"Failed to unlock units: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"TEG connection error: {str(e)}")
            raise TEGClientError(f"Failed to connect to TEG Layer: {str(e)}")


# Global client instance (initialized on first use)
_teg_client: Optional[TEGClient] = None


def get_teg_client() -> TEGClient:
    """
    Get or create the global TEG client instance.
    
    Returns:
        TEGClient instance
    """
    global _teg_client
    if _teg_client is None:
        # Get URL from environment variable set in docker-compose.yml
        teg_url = os.getenv('TEG_API_BASE_URL', 'http://teg-layer:8080')
        _teg_client = TEGClient(base_url=teg_url)
    return _teg_client
