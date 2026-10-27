"""§pass57: Generic Idempotency-Key request-level cache.

Promoted from `services/bundles/service.py` (where the pattern has been
running in production since §pass51 / 2026-05-20 for bundles export/import).

Pattern: every financial endpoint wraps its work with `lookup()` + `store()`.
On replay (same Idempotency-Key + same body), returns the cached response
without re-executing the underlying TEG transfer / event emit.

Two-layer defense against double-execution:
  - REQUEST-LEVEL (this module): catches client double-submit via Redis cache
  - EVENT-LEVEL (EventStore UNIQUE on idempotency_key): catches emit-side retries

See INVESTIGATION_2026-05-20_PR8_IDEMPOTENCY_DEEP_DIVE.md for context.
"""
from .cache import idempotency_lookup, idempotency_store, IdempotencyError

__all__ = ["idempotency_lookup", "idempotency_store", "IdempotencyError"]
