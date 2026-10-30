"""D6-808 (2026-10-17): a repeated idempotency key on the two system-account movers is answered from the row it names.

/admin/exchange/move (exref:<key>) and /admin/fx/move (fxref:<key>) replay a COMPLETED row that carries the request's
key instead of moving again. They used to answer that replay from the REQUEST's own from/to/amount and never compared
them with the row, so a key used a second time for a different move was told "completed" for a move that never ran.
A replay is now answered only when the request is the row's own move (same source, same target, same amount as the
column stores it), and from the row; a different move under a used key is refused, and nothing moves for it.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from .error_handling import TEGException, ErrorCode

logger = logging.getLogger(__name__)

# teg_transactions.amount is NUMERIC(36, 18): the row holds the amount rounded to 18 places (half away from zero, as
# Postgres rounds a numeric), so the request's amount is compared at that scale.
_SCALE = Decimal("1e-18")


def _as_stored(amount) -> Decimal:
    return Decimal(str(amount)).quantize(_SCALE, rounding=ROUND_HALF_UP)


def same_move(txn, from_did: str, to_did: str, amount) -> bool:
    """True when the stored row moved exactly this: the same source, the same target and the same amount."""
    return (txn.sender_agent_id == from_did and txn.receiver_agent_id == to_did
            and _as_stored(txn.amount) == _as_stored(amount))


def refuse_other_move(path: str, key: str, txn, from_did: str, to_did: str, amount) -> TEGException:
    """The refusal of a different move under a key a completed move already holds: 422, nothing moved for this request.
    The answer names the row's transaction id; the log line also names both moves."""
    logger.warning(
        "[%s] idempotency key %s already settled transaction %s (%s -> %s, %s); a different move under it is refused "
        "(%s -> %s, %s): nothing moved", path, key, txn.transaction_id, txn.sender_agent_id, txn.receiver_agent_id,
        txn.amount, from_did, to_did, amount,
    )
    return TEGException(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        error_code=ErrorCode.IDEM_CONFLICTING_REQUEST,
        message=(f"{path}: this idempotency key already settled a different move (transaction {txn.transaction_id}); "
                 f"nothing moved for this request"),
    )
