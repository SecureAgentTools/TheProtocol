"""
Distributed Transaction Coordinator for Cross-TEG Transfers.

Implements two-phase commit protocol with compensation support.
"""

import asyncio
import logging
from typing import Dict, Optional, List, Callable, Awaitable, Any
from datetime import datetime, timedelta, timezone
from enum import Enum
import uuid

from decimal import Decimal

from sqlalchemy import select, text

from .messages import (
    CrossTEGTransferRequest,
    CrossTEGTransferResponse,
    TransferAcceptRequest,
    TransferStatus,
    TransferStatusUpdate
)
from .protocol import CrossTEGTransferProtocol, TransferState
from .coordination_store import CoordinationStore

logger = logging.getLogger(__name__)

# §SECFIX-13 (2026-09-25): the remote prepare, commit and abort carried the SENDING AGENT'S TEG JWT as their bearer. The
# peer never validates it (protocol.accept_transfer: "For now, we'll assume it's valid"; the caller is authenticated by
# its mTLS SVID), and the token is live at this TEG's own /cross-teg/transfer for 15 minutes, which a peer can reach
# through this frame's nginx-federation. A fixed placeholder keeps every receiver working (a pre-V0452 receiver slices
# `authorization[7:]` and stores the result unread) and no longer hands a peer a credential.
PEER_BEARER_PLACEHOLDER = "mtls-authenticated"

# §MONEY-R31 — Prometheus (lazy, best-effort; mirrors core/balance_outbox.py).
# A PARTIAL COMMIT is the most serious state this module can reach: some participants
# committed their leg and others did not, so balances are inconsistent ACROSS TEGs and no
# reconciler can decide the truth on its own. It used to be a logger.error() beside the
# comment "In production, this would trigger manual intervention" — and nothing triggered
# anything. A comment is not an operator action.
try:
    from prometheus_client import Counter as _C

    CROSS_TEG_PARTIAL_COMMIT_TOTAL = _C(
        "teg_cross_teg_partial_commit_total",
        "2PC transfers that committed on some participants and not others (needs a human)",
        ["teg_id"],
    )
except Exception:  # pragma: no cover
    CROSS_TEG_PARTIAL_COMMIT_TOTAL = None


def _build_audit_payload(row, expired_at: datetime, *, prior_status: str) -> Dict[str, Any]:
    """Shape the audit payload for sweeper-emitted events. Shared between
    CrossTEGCoordinationAbortedByExpiry and CrossTEGCoordinationCommitResumed."""
    return {
        "transfer_id": row.transfer_id,
        "correlation_id": row.correlation_id,
        "source_agent_id": row.source_agent_id,
        "target_agent_id": row.target_agent_id,
        "source_teg_id": row.source_teg_id,
        "target_teg_id": row.target_teg_id,
        "amount": str(row.amount),
        "currency": row.currency,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "expired_by_sweep_at": expired_at.isoformat(),
        "prior_status": prior_status,
    }


class CoordinatorRole(str, Enum):
    """Role of the coordinator in a transfer."""
    SOURCE = "source"      # Initiating the transfer
    TARGET = "target"      # Receiving the transfer
    OBSERVER = "observer"  # Monitoring only


class TransferPhase(str, Enum):
    """Phases of the two-phase commit protocol."""
    PREPARE = "prepare"
    COMMIT = "commit"
    ABORT = "abort"
    COMPENSATE = "compensate"


class DistributedTransactionCoordinator:
    """
    Coordinates distributed transactions across TEG layers.
    
    Implements a two-phase commit protocol with compensation:
    1. Prepare Phase: All participants prepare the transaction
    2. Commit Phase: If all prepared, commit; otherwise abort
    3. Compensation: Rollback in case of failures
    """
    
    def __init__(
        self,
        teg_id: str,
        protocol: CrossTEGTransferProtocol,
        teg_client_factory: Callable[..., any],
        db_session_factory=None,
    ):
        self.teg_id = teg_id
        self.protocol = protocol
        self.teg_client_factory = teg_client_factory

        # DB-backed coordination store (cross-worker visibility)
        self.store = CoordinationStore(
            db_session_factory or protocol.db_session_factory,
            teg_id,
        )

        # Local cache for active request lifecycle (fast reads within one request)
        self.active_coordinations: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
        self.phase_timeouts = {
            TransferPhase.PREPARE: timedelta(seconds=30),
            TransferPhase.COMMIT: timedelta(seconds=60),
            TransferPhase.COMPENSATE: timedelta(seconds=120)
        }
        
        # Message handlers
        self.message_handlers = {
            "prepare_request": self._handle_prepare_request,
            "prepare_response": self._handle_prepare_response,
            "commit_request": self._handle_commit_request,
            "commit_response": self._handle_commit_response,
            "abort_request": self._handle_abort_request,
            "status_update": self._handle_status_update
        }
    
    async def coordinate_transfer(
        self,
        request: CrossTEGTransferRequest
    ) -> CrossTEGTransferResponse:
        """
        Coordinate a cross-TEG transfer as the source coordinator.
        
        This implements the full two-phase commit protocol:
        1. Local prepare (lock funds)
        2. Remote prepare (notify target)
        3. Decision (commit or abort)
        4. Execute decision on all participants
        """
        coordination_id = request.transfer_id

        # ── §P2 (2026-06-09): source-side idempotent-replay guard ──────────────────
        # A re-POST of /cross-teg/transfer with the SAME transfer_id (the registry retries on 5xx,
        # and the FX route legs now retry connection drops — both with a stable transfer_id) must
        # NOT re-prepare/re-commit: the commit legs are not individually idempotent, so a re-drive
        # would surface a false PARTIAL_COMMIT and trick the caller into refunding money that
        # already moved (double-spend). A connection-drop retry typically arrives ~100ms later,
        # WHILE the first attempt is still mid-2PC, so the in-flight branch briefly polls for
        # COMPLETED and replays the success rather than refusing.
        def _row_status(row) -> str:
            s = row.status
            return (s.value if hasattr(s, "value") else str(s)).lower()

        _existing = self.store.get_coordination(coordination_id)
        if _existing is not None and getattr(_existing, "role", None) == "source":
            _st = _row_status(_existing)
            if _st.endswith("completed"):
                logger.info(f"[SOURCE] idempotent replay — {coordination_id} already COMPLETED")
                return CrossTEGTransferResponse(
                    transfer_id=request.transfer_id, correlation_id=request.correlation_id,
                    status=TransferStatus.COMPLETED, processing_teg_id=self.teg_id, success=True,
                    message="Transfer already completed (idempotent replay)",
                    transaction_hash=_existing.transfer_id,
                )
            if not _st.endswith(("failed", "compensated")):
                # In-flight (initiated/funds_locked/prepared/committed). Poll ~10s for the first
                # attempt to finish, then replay. Only refuse if it never resolves (rare; the
                # caller dead-letters and the saga-timeout sweeper resolves the stuck row).
                for _ in range(40):  # 40 × 0.25s = 10s
                    await asyncio.sleep(0.25)
                    _cur = self.store.get_coordination(coordination_id)
                    if _cur is None:
                        break
                    _cst = _row_status(_cur)
                    if _cst.endswith("completed"):
                        logger.info(f"[SOURCE] idempotent replay (after in-flight wait) — {coordination_id}")
                        return CrossTEGTransferResponse(
                            transfer_id=request.transfer_id, correlation_id=request.correlation_id,
                            status=TransferStatus.COMPLETED, processing_teg_id=self.teg_id, success=True,
                            message="Transfer completed (idempotent replay after in-flight wait)",
                            transaction_hash=_cur.transfer_id,
                        )
                    if _cst.endswith(("failed", "compensated")):
                        break
                else:
                    logger.warning(f"[SOURCE] {coordination_id} still in-flight after wait — refusing re-drive")
                    return self._create_failure_response(
                        request, f"transfer {coordination_id} already in progress", "IN_FLIGHT")
            # FAILED / COMPENSATED (or resolved-to-failed) → a prior attempt aborted cleanly
            # (funds released) → fall through to a fresh re-drive of the same transfer_id.
        # ───────────────────────────────────────────────────────────────────────────

        # Persist coordination to DB (visible to all workers)
        try:
            self.store.save_source_coordination(
                transfer_id=coordination_id,
                correlation_id=request.correlation_id,
                source_agent_id=request.source_agent_id,
                target_agent_id=request.target_agent_id,
                target_teg_id=request.target_teg_id,
                target_registry_id=request.target_registry_id,
                source_registry_id=request.source_registry_id,
                amount=request.amount,
                currency=request.currency,
                expires_at=request.expires_at,
                memo=request.memo or "",
            )
        except Exception as e:
            logger.error(f"Failed to persist coordination {coordination_id}: {e}")
            return self._create_failure_response(request, str(e), "DB_ERROR")

        # Local cache for this request's lifecycle
        async with self._lock:
            self.active_coordinations[coordination_id] = {
                "role": CoordinatorRole.SOURCE,
                "request": request,
                "phase": TransferPhase.PREPARE,
                "participants": {
                    self.teg_id: {"status": "preparing", "prepared_at": None},
                    request.target_teg_id: {"status": "waiting", "prepared_at": None}
                },
                "decision": None,
                "started_at": datetime.now(timezone.utc),
                "completed_at": None
            }

        try:
            # Phase 1: Prepare
            logger.info(f"Starting prepare phase for transfer {coordination_id}")
            
            # Local prepare (lock funds)
            local_prepared = await self._prepare_local(request)
            if not local_prepared:
                # Read the captured reason BEFORE _abort_coordination clears state.
                _perr = (self.active_coordinations.get(coordination_id) or {}).get("prepare_error", "") or ""
                await self._abort_coordination(coordination_id, "Local prepare failed")
                # Insufficient balance is a business/client condition → surface it distinctly
                # so the router returns 402 (not 500). _lock_funds error text starts with
                # "Insufficient balance. Available: …".
                if "insufficient balance" in _perr.lower():
                    return self._create_failure_response(request, _perr, "INSUFFICIENT_BALANCE")
                return self._create_failure_response(
                    request, "Failed to lock funds", "PREPARE_FAILED"
                )
            
            # Remote prepare (notify target TEG)
            remote_prepared = await self._prepare_remote(request)
            if not remote_prepared:
                await self._abort_coordination(coordination_id, "Remote prepare failed")
                return self._create_failure_response(
                    request, "Target TEG rejected transfer", "REMOTE_PREPARE_FAILED"
                )
            
            # Phase 2: Decision — persist to DB
            logger.info(f"All participants prepared for transfer {coordination_id}")
            self.active_coordinations[coordination_id]["decision"] = "commit"
            self.active_coordinations[coordination_id]["phase"] = TransferPhase.COMMIT
            from ...database.models import CrossTEGTransferStatus as _CTTS
            self.store.update_phase(coordination_id, "commit", _CTTS.COMMITTED)

            # Phase 3: Commit
            commit_success = await self._commit_all_participants(coordination_id)
            if not commit_success:
                # §MONEY-R31: some participants committed and others did not. This is not a
                # failure the caller can retry away — the money is already inconsistent across
                # TEGs. Surface it on a counter an alert can watch; the log line alone was
                # invisible to every instrument.
                if CROSS_TEG_PARTIAL_COMMIT_TOTAL is not None:
                    try:
                        CROSS_TEG_PARTIAL_COMMIT_TOTAL.labels(teg_id=str(self.teg_id)).inc()
                    except Exception:  # noqa: BLE001 — never let telemetry mask the money state
                        logger.exception("[CROSS-TEG] partial-commit counter failed")
                logger.critical(
                    "[CROSS-TEG] PARTIAL COMMIT for transfer %s — some participants committed, "
                    "others did not; balances are inconsistent across TEGs and this needs a human. "
                    "Reconcile from cross_teg_transfers and the participants' journals.",
                    coordination_id,
                )
                return self._create_failure_response(
                    request, "Partial commit - manual intervention required", "PARTIAL_COMMIT"
                )
            
            # Success! — persist to DB
            self.active_coordinations[coordination_id]["completed_at"] = datetime.now(timezone.utc)
            self.store.mark_completed(coordination_id)
            
            return CrossTEGTransferResponse(
                transfer_id=request.transfer_id,
                correlation_id=request.correlation_id,
                status=TransferStatus.COMPLETED,
                processing_teg_id=self.teg_id,
                success=True,
                message="Transfer completed successfully",
                # §PlanB-②: canonical cross-TEG id = bare transfer_id (== ES
                # TokensTransferred.data.transaction_id == both leg rows). Dropped the
                # cosmetic "tx_" prefix so getTegTransactionDetail resolves the listed leg id.
                transaction_hash=request.transfer_id
            )
            
        except asyncio.TimeoutError:
            logger.error(f"Coordination timeout for transfer {coordination_id}")
            await self._abort_coordination(coordination_id, "Coordination timeout")
            return self._create_failure_response(
                request, "Transfer coordination timeout", "TIMEOUT"
            )
            
        except Exception as e:
            logger.error(f"Unexpected error in coordination {coordination_id}: {str(e)}")
            await self._abort_coordination(coordination_id, f"Unexpected error: {str(e)}")
            return self._create_failure_response(
                request, str(e), "UNEXPECTED_ERROR"
            )
            
        finally:
            # Cleanup coordination state
            async with self._lock:
                self.active_coordinations.pop(coordination_id, None)
    
    async def _prepare_local(self, request: CrossTEGTransferRequest) -> bool:
        """Prepare local resources (lock funds)."""
        try:
            lock_result = await self.protocol._lock_funds(
                transfer_id=request.transfer_id,
                agent_id=request.source_agent_id,
                amount=request.amount,
                expires_at=request.expires_at
            )
            
            if lock_result.locked:
                coordination = self.active_coordinations[request.transfer_id]
                coordination["participants"][self.teg_id] = {
                    "status": "prepared",
                    "prepared_at": datetime.now(timezone.utc)
                }
                return True

            # Capture WHY the local lock failed so coordinate_transfer can classify it
            # (insufficient-balance is a client/business condition → 402, not a 500).
            # _lock_funds returns locked=False WITHOUT raising for insufficient balance,
            # so this is the only place the reason is visible.
            _co = self.active_coordinations.get(request.transfer_id)
            if _co is not None:
                _co["prepare_error"] = getattr(lock_result, "error", None) or "local prepare failed"
            return False

        except Exception as e:
            _co = self.active_coordinations.get(request.transfer_id)
            if _co is not None:
                _co["prepare_error"] = f"exception: {e}"
            logger.error(f"Local prepare failed: {str(e)}")
            return False
    
    async def _prepare_remote(self, request: CrossTEGTransferRequest) -> bool:
        """Request remote TEG to prepare for incoming transfer."""
        try:
            target_client = self.teg_client_factory(
                request.target_teg_id,
                url_hint=getattr(request, 'target_teg_url', None)
            )

            request_data = {
                "source_teg_id": request.source_teg_id,
                "source_registry_id": request.source_registry_id,
                "source_agent_id": request.source_agent_id,
                "target_agent_id": request.target_agent_id,
                "amount": str(request.amount),
                "currency": request.currency,
                "correlation_id": request.correlation_id,
                "memo": request.memo,
                "expires_at": request.expires_at.isoformat(),
            }

            logger.info(
                f"Sending prepare to target TEG {request.target_teg_id} "
                f"for transfer {request.transfer_id}"
            )

            result = await target_client.prepare_transfer(
                transfer_id=request.transfer_id,
                request_data=request_data,
                auth_token=PEER_BEARER_PLACEHOLDER
            )

            if result.get("status") == "prepared":
                coordination = self.active_coordinations[request.transfer_id]
                coordination["participants"][request.target_teg_id] = {
                    "status": "prepared",
                    "prepared_at": datetime.now(timezone.utc)
                }
                logger.info(f"Remote TEG {request.target_teg_id} prepared for transfer {request.transfer_id}")
                return True

            logger.error(f"Remote prepare rejected for transfer {request.transfer_id}: {result}")
            return False

        except Exception as e:
            logger.error(f"Remote prepare failed for TEG {request.target_teg_id}: {str(e)}")
            return False
    
    async def _commit_all_participants(self, coordination_id: str) -> bool:
        """Send commit request to all participants."""
        coordination = self.active_coordinations[coordination_id]
        request = coordination["request"]
        
        commit_tasks = []
        
        # Commit local
        commit_tasks.append(self._commit_local(request))
        
        # Commit remote
        commit_tasks.append(self._commit_remote(request))
        
        # Wait for all commits with timeout
        timeout = self.phase_timeouts[TransferPhase.COMMIT]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*commit_tasks, return_exceptions=True),
                timeout=timeout.total_seconds()
            )
            
            # Check if all commits succeeded
            for i, result in enumerate(results):
                if isinstance(result, Exception) or result is False:
                    logger.error(f"Commit failed for participant {i}: {result}")
                    return False
            
            return True
            
        except asyncio.TimeoutError:
            logger.error(f"Commit phase timeout for {coordination_id}")
            return False
    
    async def _commit_local(self, request: CrossTEGTransferRequest) -> bool:
        """Commit local changes (complete the transfer)."""
        try:
            await self.protocol._complete_transfer(request)
            return True
        except Exception as e:
            logger.error(f"Local commit failed: {str(e)}")
            return False
    
    async def _commit_remote(self, request: CrossTEGTransferRequest) -> bool:
        """Request remote TEG to commit the transfer (credit recipient)."""
        try:
            target_client = self.teg_client_factory(
                request.target_teg_id,
                url_hint=getattr(request, 'target_teg_url', None)
            )

            logger.info(
                f"Sending commit to target TEG {request.target_teg_id} "
                f"for transfer {request.transfer_id}"
            )

            result = await target_client.commit_transfer(
                transfer_id=request.transfer_id,
                auth_token=PEER_BEARER_PLACEHOLDER
            )

            if result.get("status") == "committed":
                logger.info(f"Remote TEG {request.target_teg_id} committed transfer {request.transfer_id}")
                return True

            logger.error(f"Remote commit rejected for transfer {request.transfer_id}: {result}")
            return False

        except Exception as e:
            logger.error(f"Remote commit failed for TEG {request.target_teg_id}: {str(e)}")
            return False
    
    async def _abort_coordination(self, coordination_id: str, reason: str):
        """Abort the coordination and compensate all prepared participants."""
        coordination = self.active_coordinations.get(coordination_id)
        if not coordination:
            return

        logger.warning(f"Aborting coordination {coordination_id}: {reason}")
        self.store.mark_failed(coordination_id, reason)
        
        coordination["phase"] = TransferPhase.ABORT
        coordination["decision"] = "abort"
        
        # Compensate all prepared participants
        request = coordination["request"]
        for teg_id, participant in coordination["participants"].items():
            if participant["status"] == "prepared":
                if teg_id == self.teg_id:
                    # Compensate local
                    await self.protocol._compensate_transfer(
                        transfer_id=request.transfer_id,
                        agent_id=request.source_agent_id,
                        amount=request.amount,
                        reason=reason
                    )
                else:
                    # Send abort to remote TEG
                    try:
                        remote_client = self.teg_client_factory(teg_id)
                        await remote_client.abort_transfer(
                            transfer_id=request.transfer_id,
                            reason=reason,
                            auth_token=PEER_BEARER_PLACEHOLDER
                        )
                        logger.info(f"Abort sent to remote TEG {teg_id}")
                    except Exception as abort_err:
                        logger.error(f"Failed to send abort to TEG {teg_id}: {str(abort_err)}")

        # Clean up coordination state to prevent memory leak
        self.active_coordinations.pop(coordination_id, None)

    def _create_failure_response(
        self,
        request: CrossTEGTransferRequest,
        message: str,
        error_code: str
    ) -> CrossTEGTransferResponse:
        """Create a failure response."""
        return CrossTEGTransferResponse(
            transfer_id=request.transfer_id,
            correlation_id=request.correlation_id,
            status=TransferStatus.FAILED,
            processing_teg_id=self.teg_id,
            success=False,
            message=message,
            error_code=error_code
        )
    
    async def handle_incoming_message(self, message_type: str, message: Dict):
        """Handle incoming coordination messages from other TEGs."""
        handler = self.message_handlers.get(message_type)
        if handler:
            await handler(message)
        else:
            logger.warning(f"Unknown message type: {message_type}")
    
    async def _handle_prepare_request(self, message: Dict):
        """Handle incoming prepare request as target TEG.

        Validates the transfer data and stores it as a pending coordination
        so the subsequent commit can credit the recipient.
        """
        transfer_id = message["transfer_id"]
        data = message.get("data", {})

        logger.info(f"[TARGET] Received prepare request for transfer {transfer_id}")

        # Persist to DB (visible to all workers for the commit phase)
        try:
            self.store.save_target_coordination(transfer_id, data)
        except Exception as e:
            logger.error(f"[TARGET] Failed to persist prepare for {transfer_id}: {e}")

        # Also cache locally for fast access within this worker
        async with self._lock:
            self.active_coordinations[transfer_id] = {
                "role": CoordinatorRole.TARGET,
                "data": data,
                "auth_token": message.get("auth_token"),
                "phase": TransferPhase.PREPARE,
                "participants": {
                    data.get("source_teg_id", "unknown"): {"status": "prepared"},
                    self.teg_id: {"status": "prepared", "prepared_at": datetime.now(timezone.utc)}
                },
                "decision": None,
                "started_at": datetime.now(timezone.utc),
                "completed_at": None
            }

        logger.info(
            f"[TARGET] Prepared for incoming transfer {transfer_id}: "
            f"{data.get('amount')} from {data.get('source_agent_id')} "
            f"to {data.get('target_agent_id')}"
        )

    async def _handle_prepare_response(self, message: Dict):
        """Handle prepare response from participant (source coordinator only)."""
        transfer_id = message.get("transfer_id")
        coordination = self.active_coordinations.get(transfer_id)
        if coordination:
            teg_id = message.get("teg_id", "unknown")
            coordination["participants"][teg_id] = {
                "status": "prepared",
                "prepared_at": datetime.now(timezone.utc)
            }
            logger.info(f"[SOURCE] Prepare response received from {teg_id} for {transfer_id}")

    async def _handle_commit_request(self, message: Dict):
        """Handle incoming commit request — credit the recipient via accept_transfer.

        This is the critical step where the target TEG actually credits
        the recipient's balance, completing the distributed transaction.

        DB-backed: if the in-memory cache doesn't have the coordination
        (prepare was on a different worker), load it from the DB.
        """
        transfer_id = message["transfer_id"]

        coordination = self.active_coordinations.get(transfer_id)

        if not coordination:
            # Cross-worker scenario: prepare was on a different worker.
            # Load coordination from DB.
            db_record = self.store.get_coordination(transfer_id)
            if db_record and db_record.role == "target":
                logger.info(f"[TARGET] Loaded coordination from DB for {transfer_id} (cross-worker)")
                coordination = {
                    "role": CoordinatorRole.TARGET,
                    "data": {
                        "source_teg_id": db_record.source_teg_id,
                        "source_agent_id": db_record.source_agent_id,
                        "target_agent_id": db_record.target_agent_id,
                        "amount": str(db_record.amount),
                        "correlation_id": db_record.correlation_id,
                        "currency": db_record.currency,
                    },
                    "auth_token": message.get("auth_token"),
                    "phase": TransferPhase.PREPARE,
                }
            else:
                raise Exception(f"No prepared coordination found for transfer {transfer_id} (checked local + DB)")

        if coordination.get("role") != CoordinatorRole.TARGET:
            raise Exception(f"Unexpected commit request — this TEG is {coordination.get('role')}, not TARGET")

        data = coordination["data"]

        logger.info(f"[TARGET] Committing transfer {transfer_id}: crediting {data.get('target_agent_id')}")

        # Build the accept request and credit the recipient
        accept_request = TransferAcceptRequest(
            transfer_id=transfer_id,
            correlation_id=data.get("correlation_id", transfer_id),
            source_teg_id=data.get("source_teg_id", "unknown"),
            amount=Decimal(data["amount"]),
            recipient_agent_id=data["target_agent_id"],
            authorization_token=message.get("auth_token", "")
        )

        result = await self.protocol.accept_transfer(accept_request)

        if not result.accepted:
            raise Exception(f"Failed to accept transfer {transfer_id}: {result.error}")

        # Mark completed — DB + local cache
        coordination["phase"] = TransferPhase.COMMIT
        coordination["decision"] = "commit"
        coordination["completed_at"] = datetime.now(timezone.utc)
        self.store.mark_completed(transfer_id)
        async with self._lock:
            self.active_coordinations.pop(transfer_id, None)

        logger.info(
            f"[TARGET] Successfully committed transfer {transfer_id}: "
            f"credited {data['amount']} to {data['target_agent_id']}"
        )

    async def _handle_commit_response(self, message: Dict):
        """Handle commit response from participant (source coordinator only)."""
        transfer_id = message.get("transfer_id")
        coordination = self.active_coordinations.get(transfer_id)
        if coordination:
            teg_id = message.get("teg_id", "unknown")
            coordination["participants"][teg_id] = {
                "status": "committed",
                "committed_at": datetime.now(timezone.utc)
            }
            logger.info(f"[SOURCE] Commit response received from {teg_id} for {transfer_id}")

    async def _handle_abort_request(self, message: Dict):
        """Handle incoming abort request — clean up any prepared state."""
        transfer_id = message["transfer_id"]
        reason = message.get("reason", "Unknown")

        coordination = self.active_coordinations.get(transfer_id)
        if coordination:
            coordination["phase"] = TransferPhase.ABORT
            coordination["decision"] = "abort"
            async with self._lock:
                self.active_coordinations.pop(transfer_id, None)
            logger.info(f"[TARGET] Aborted transfer {transfer_id}: {reason}")
        else:
            logger.warning(f"[TARGET] Abort for unknown transfer {transfer_id} (already cleaned up?)")

    async def _handle_status_update(self, message: Dict):
        """Handle status update from participant."""
        transfer_id = message.get("transfer_id")
        new_status = message.get("new_status")
        updated_by = message.get("updated_by_teg")

        coordination = self.active_coordinations.get(transfer_id)
        if coordination:
            logger.info(
                f"Status update for {transfer_id}: {new_status} (from TEG {updated_by})"
            )
        else:
            logger.debug(f"Status update for unknown/completed transfer {transfer_id}")
    
    async def get_coordination_status(self, coordination_id: str) -> Optional[Dict]:
        """Get the current status of a coordination."""
        return self.active_coordinations.get(coordination_id)
    
    async def sweep_expired_coordinations(
        self,
        batch_limit: int = 100,
        emit_audit: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> Dict[str, int]:
        """DB-backed sweep for expired source-side coordinations (§pass26).

        Replaces the in-memory `cleanup_expired_coordinations` stub. Queries
        the `cross_teg_transfers` table for source-side rows past expires_at
        that never reached terminal state, then routes by status:

          INITIATED → `protocol._compensate_transfer` (releases locked_balance,
                      marks row COMPENSATED). Emits CrossTEGCoordinationAbortedByExpiry.
          COMMITTED → marks row FAILED with an operator-review note.
                      (Auto-retrying remote commit requires the original
                       authorization_token which is not persisted; safer to
                       capture the audit event than risk double-debit.)
                      Emits CrossTEGCoordinationCommitResumed.

        Per-row errors are isolated and emit CrossTEGSweepErrored.

        Args:
            batch_limit: maximum rows to process per cycle
            emit_audit: async callback (event_type, aggregate_id, data) for
                audit event emission. None disables emission (useful for tests).

        Returns:
            Dict with keys: checked, aborted, resumed, errors (all int).
        """
        from ...database.models import CrossTEGTransfer, CrossTEGTransferStatus

        stats: Dict[str, int] = {"checked": 0, "aborted": 0, "resumed": 0, "errors": 0}
        cutoff = datetime.now(timezone.utc)

        # 1. Snapshot expired source-side rows (this TEG's rows only).
        db_factory = self.store._db_factory
        gen = db_factory()
        session = next(gen)
        try:
            result = session.execute(
                select(CrossTEGTransfer)
                .where(
                    CrossTEGTransfer.role == "source",
                    CrossTEGTransfer.source_teg_id == self.teg_id,
                    CrossTEGTransfer.expires_at < cutoff,
                    CrossTEGTransfer.status.in_([
                        CrossTEGTransferStatus.INITIATED,
                        CrossTEGTransferStatus.COMMITTED,
                    ]),
                    CrossTEGTransfer.completed_at.is_(None),
                )
                .order_by(CrossTEGTransfer.expires_at.asc())
                .limit(batch_limit)
            )
            expired_rows = []
            for row in result.scalars():
                # Detach so attributes remain accessible after session close.
                session.expunge(row)
                expired_rows.append(row)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

        stats["checked"] = len(expired_rows)

        # 2. Process each row.
        for row in expired_rows:
            try:
                if row.status == CrossTEGTransferStatus.INITIATED:
                    await self.protocol._compensate_transfer(
                        transfer_id=row.transfer_id,
                        agent_id=row.source_agent_id,
                        amount=row.amount,
                        reason="expired_by_sweep",
                    )
                    stats["aborted"] += 1
                    logger.info(
                        f"[CrossTegSweeper] Aborted expired INITIATED transfer "
                        f"{row.transfer_id} (agent={row.source_agent_id}, amount={row.amount})"
                    )
                    if emit_audit:
                        await emit_audit(
                            "CrossTEGCoordinationAbortedByExpiry",
                            row.source_agent_id,
                            _build_audit_payload(row, cutoff, prior_status="initiated"),
                        )
                elif row.status == CrossTEGTransferStatus.COMMITTED:
                    # Partial-commit case — flag for operator review rather than
                    # risk auto-retry without persisted auth_token.
                    self.store.mark_failed(
                        row.transfer_id,
                        "expired_in_commit_phase_operator_review_required",
                    )
                    stats["resumed"] += 1
                    logger.warning(
                        f"[CrossTegSweeper] Flagged expired COMMITTED transfer "
                        f"{row.transfer_id} for operator review "
                        f"(debit_local={row.debit_transaction_id is not None})"
                    )
                    if emit_audit:
                        payload = _build_audit_payload(row, cutoff, prior_status="committed")
                        payload["debit_recorded_locally"] = row.debit_transaction_id is not None
                        payload["resolution"] = "marked_failed_for_operator_review"
                        await emit_audit(
                            "CrossTEGCoordinationCommitResumed",
                            row.source_agent_id,
                            payload,
                        )
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    f"[CrossTegSweeper] Failed to sweep {row.transfer_id}: {e}",
                    exc_info=True,
                )
                if emit_audit:
                    try:
                        await emit_audit(
                            "CrossTEGSweepErrored",
                            row.source_agent_id,
                            {
                                "transfer_id": row.transfer_id,
                                "source_agent_id": row.source_agent_id,
                                "amount": str(row.amount),
                                "prior_status": (
                                    row.status.value
                                    if hasattr(row.status, "value")
                                    else str(row.status)
                                ),
                                "error": str(e)[:1000],
                            },
                        )
                    except Exception:
                        pass

        return stats

    async def sweep_stale_bookkeeping(
        self,
        batch_limit: int = 2000,
        age_hours: int = 24,
    ) -> Dict[str, int]:
        """Status-only write-down of stale FUNDS_LOCKED bookkeeping rows (§V0050).

        The async lock leg (`/cross-teg/lock-async`) debits the sender into the
        cross-frame escrow system account and records a FUNDS_LOCKED row
        (expires_at=+5min) -- but no source-side code ever advances that row,
        even on successful settlement, so every async cross-registry transfer
        leaks one permanent row (~7k/day; 268k backlog found 2026-06-10). The
        VALUE is settled or refunded by the escrow/refund machinery; only the
        coordination row is stale.

        Rows expired for more than `age_hours` are marked SWEPT. Deliberately
        STATUS-ONLY: this path never touches locked_balance, so routing rows
        through `_compensate_transfer` would decrement locks that were never
        taken (the F1 failure class). The escrow_lock_reconciler already
        excludes expired rows (`expires_at > now()` filter in its in-flight
        CTE), so this changes its arithmetic by exactly zero. Replay guards
        are unaffected: lock-async idempotency keys on row EXISTENCE, credit
        dedup keys on COMPLETED.

        Returns:
            Dict with keys: swept (rows written down this call), remaining
            (rows still matching the stale predicate after the write-down).
        """
        stats: Dict[str, int] = {"swept": 0, "remaining": 0}
        db_factory = self.store._db_factory
        gen = db_factory()
        session = next(gen)
        try:
            result = session.execute(
                text("""
                    WITH c AS (
                        SELECT transfer_id FROM cross_teg_transfers
                         WHERE role = 'source'
                           AND source_teg_id = :teg
                           AND status = 'FUNDS_LOCKED'
                           AND completed_at IS NULL
                           AND expires_at < now() - make_interval(hours => :age)
                         ORDER BY expires_at ASC
                         LIMIT :batch
                         FOR UPDATE SKIP LOCKED
                    )
                    UPDATE cross_teg_transfers t
                       SET status = 'SWEPT',
                           completed_at = now(),
                           updated_at = now(),
                           error_message = '[STALE-SWEEP V0050] async-leg bookkeeping; value settled/refunded via escrow ledger'
                      FROM c
                     WHERE t.transfer_id = c.transfer_id
                """),
                {"teg": self.teg_id, "age": age_hours, "batch": batch_limit},
            )
            session.commit()
            stats["swept"] = int(result.rowcount or 0)

            remaining = session.execute(
                text("""
                    SELECT count(*) FROM cross_teg_transfers
                     WHERE role = 'source'
                       AND source_teg_id = :teg
                       AND status = 'FUNDS_LOCKED'
                       AND completed_at IS NULL
                       AND expires_at < now() - make_interval(hours => :age)
                """),
                {"teg": self.teg_id, "age": age_hours},
            ).scalar()
            stats["remaining"] = int(remaining or 0)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
        return stats

    async def sweep_stale_exchange_legs(
        self,
        batch_limit: int = 500,
        age_hours: int = 24,
    ) -> Dict[str, int]:
        """Status-only write-down of ORPHANED `exref:ord-...` deposit legs (2026-07-29).

        `/admin/exchange/move` already writes down a stale PENDING row — but only when a
        NEW attempt arrives with the same idempotency key. An order that was rejected is
        terminal: no retry ever comes, so its pending leg sits forever. Four such rows
        were found on frame-a, the oldest from 2026-06-13, totalling 86.79 AVT NOMINAL —
        and moving no money at all.

        That last point is the whole safety argument and it was MEASURED, not assumed:
        the escrow invariant read exactly 0 (nothing extra had landed in escrow) and the
        supply delta read 0.0 (nothing had vanished), so these legs never touched a
        balance. Hence status-only. A refund here would invent money and break Δ=0 —
        the opposite of a fix.

        Rows are matched on the `exref:ord-` prefix so this can use the index, and only
        those older than `age_hours` (a live leg is written down by the endpoint's own
        120-second rule long before this).
        """
        stats: Dict[str, int] = {"swept": 0, "remaining": 0}
        db_factory = self.store._db_factory
        gen = db_factory()
        session = next(gen)
        try:
            result = session.execute(
                text("""
                    WITH c AS (
                        SELECT transaction_id FROM teg_transactions
                         WHERE attached_message LIKE 'exref:ord-%'
                           AND status = 'pending'
                           AND timestamp < now() - make_interval(hours => :age)
                         ORDER BY timestamp ASC
                         LIMIT :batch
                         FOR UPDATE SKIP LOCKED
                    )
                    UPDATE teg_transactions t
                       SET status = 'failed',
                           error_message = LEFT(
                               COALESCE(t.error_message, '')
                               || ' | ORPHAN-EXREF-SWEEP: order terminal, no retry will come; '
                                  'status-only, balances untouched',
                               256)
                      FROM c
                     WHERE t.transaction_id = c.transaction_id
                """),
                {"age": age_hours, "batch": batch_limit},
            )
            session.commit()
            stats["swept"] = int(result.rowcount or 0)
            remaining = session.execute(
                text("""
                    SELECT count(*) FROM teg_transactions
                     WHERE attached_message LIKE 'exref:ord-%'
                       AND status = 'pending'
                       AND timestamp < now() - make_interval(hours => :age)
                """),
                {"age": age_hours},
            ).scalar()
            stats["remaining"] = int(remaining or 0)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
        return stats

    async def sweep_stale_outflows(
        self,
        batch_limit: int = 500,
        age_hours: int = 72,
    ) -> Dict[str, int]:
        """Status-only write-down of stale cross-TEG fund-send rows (2026-07-29).

        `/admin/treasury/cross-teg-fund-send` debits the treasury and inserts the
        TEGTransaction in ONE commit, then calls the peer. Three ways to end up
        with a permanent `pending` row:
          - peer 5xx / network → left pending ON PURPOSE for a retry (Phase 3c);
          - peer 4xx → the compensation path re-credits and marks the row, but
            for a long time that write could not commit at all (invalid enum,
            then a VARCHAR(256) overflow) and took the re-credit down with it;
          - peer 2xx → the success write hit the same overflow, so a transfer the
            peer HAD already settled stayed recorded as `pending`.
        13 such rows were found fleet-wide on 2026-07-29 (frame-a 8, b 2, c 3),
        the oldest from 2026-05-16, and nothing had ever swept them.

        Rows older than `age_hours` are marked `failed`. Deliberately STATUS-ONLY:
        it never re-credits. Re-crediting would ADD to circulating without a
        matching issuance and BREAK Δ=0 — returning that value is a supply
        operation, not a sweep, and must be done deliberately.

        The age floor is generous (default 72h) precisely because the transient
        path leaves rows pending on purpose; a swept row is one no retry came
        back for. Sweeping is NOT terminal for retryability: the fund-send resume
        branch treats `failed` like `pending` (re-attempt delivery, no re-debit),
        so a swept row can still be driven to completion later.

        Returns:
            Dict with keys: swept (rows written down this call), remaining
            (rows still matching the stale predicate afterwards).
        """
        stats: Dict[str, int] = {"swept": 0, "remaining": 0}
        db_factory = self.store._db_factory
        gen = db_factory()
        session = next(gen)
        try:
            result = session.execute(
                text("""
                    WITH c AS (
                        SELECT transaction_id FROM teg_transactions
                         WHERE transaction_type LIKE 'cross_teg_outflow%'
                           AND status = 'pending'
                           AND timestamp < now() - make_interval(hours => :age)
                         ORDER BY timestamp ASC
                         LIMIT :batch
                         FOR UPDATE SKIP LOCKED
                    )
                    UPDATE teg_transactions t
                       SET status = 'failed',
                           attached_message = LEFT(
                               COALESCE(t.attached_message, '')
                               || ' | STALE-SWEEP: no terminal outcome recorded; status-only, balances untouched',
                               256)
                      FROM c
                     WHERE t.transaction_id = c.transaction_id
                """),
                {"age": age_hours, "batch": batch_limit},
            )
            session.commit()
            stats["swept"] = int(result.rowcount or 0)

            remaining = session.execute(
                text("""
                    SELECT count(*) FROM teg_transactions
                     WHERE transaction_type LIKE 'cross_teg_outflow%'
                       AND status = 'pending'
                       AND timestamp < now() - make_interval(hours => :age)
                """),
                {"age": age_hours},
            ).scalar()
            stats["remaining"] = int(remaining or 0)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
        return stats
