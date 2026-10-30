"""§MONEY-R35 — account creation must not be a supply lever.

Three admin-key rails let a caller state an OPENING BALANCE for a TEG account:

    POST /api/v1/agent/initialize-teg-account
    POST /api/v1/agent/bulk-initialize
    POST /api/v1/admin/agents/bulk-initialize

They write `token_balance` and `audited_balance` DIRECTLY. No mint event, no
`teg.entry_type`, no idempotency, no Commander in the loop — money simply
appears, and the supply invariant is blind to it because an untagged balance
write books as transit (§MONEY-R18).

Both real callers — the registry's two `initialize-teg-account` sites in
auth.py and auth_secure.py — pass "0". Nobody has ever used the capability. It
is a door left open behind a shared admin key, and the fresh network's whole
premise (D9: the only mint is a Commander action through the registry proxy) is
incompatible with it.

So the rails keep working and lose the lever: an account is created at ZERO, and
a non-zero opening balance is refused with 400. This is deliberately NOT a
retirement — unmounting the rails is decision D8 and the Commander's; a refusal
is reversible, a deletion is a release decision.

Funding an agent has one correct path and it already exists: the registry's
reward-funding waterfall (`/admin/reward-fund` → treasury or fee_collector),
which emits the events the invariant reads.
"""
from decimal import Decimal, InvalidOperation

from starlette.status import HTTP_400_BAD_REQUEST

from .error_handling import TEGException, ErrorCode


def refuse_nonzero_opening_balance(value, *, rail: str) -> Decimal:
    """Return the opening balance as Decimal("0"), or raise 400.

    An unparseable value is refused too: "abc" is not zero, and quietly
    treating it as zero would hide a caller that believes it is funding.
    """
    if value is None or value == "":
        return Decimal("0")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="Invalid initial_balance",
            detail=f"initial_balance must be a number; {rail} creates accounts at zero.",
            metadata={"rail": rail},
        )
    if amount != 0:
        raise TEGException(
            status_code=HTTP_400_BAD_REQUEST,
            error_code=ErrorCode.VALIDATION_INVALID_INPUT,
            message="initial_balance must be 0",
            detail=(
                "Account creation does not move money (§MONEY-R35). This rail writes "
                "token_balance directly, with no mint event and no idempotency, so a "
                "non-zero opening balance creates supply that the audit cannot see. "
                "Create the account at 0 and fund it through the registry's "
                "treasury funding rail, which emits the events the invariant reads."
            ),
            metadata={"rail": rail, "requested": str(amount)},
        )
    return Decimal("0")
