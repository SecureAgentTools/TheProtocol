"""§FRAMELIC (2026-09-07, findings row 164) — THE BALANCE CACHE MUST FOLLOW EVERY MOVEMENT.

`agents.liquid_balance` is a cache of a number the TEG owns, and every console, agent list and
admin view reads the cache. The syncer subscribed to `TokensTransferred` alone — one of several
events a balance movement can produce, and not the one produced for a reputation bond, a
cross-frame debit, or (on the receiving frame) a cross-frame credit at all.

MEASURED on the reprovisioned EU/ASIA pair:

    ConverterHub (EU)    registry 1000.000000   TEG 750         250 bond → ReputationBondDeposited
    dust sender  (EU)    registry  100.000000   TEG  90         cross-frame debit → FxSwapSettled
    dust receiver(ASIA)  registry    0.000000   TEG   9.949005  credit → LedgerBalanceChanged ONLY

Δ was 0.0 throughout and correctly so — the LEDGER held every movement. Only the cache was wrong,
which is why nothing that watches money noticed. The reactor's own health was perfect while it did
nothing: 16 dispatches, 0 errors, 0 updates, because the handler read `from`/`to` off an event that
never arrives for these movements and the sync helper ended in `except Exception: pass`.

`LedgerBalanceChanged` is the event the supply invariant itself classifies, so a movement invisible
there is invisible to Δ — which makes it the right subscription for a cache that must not drift.
The `TokensTransferred` subscription is KEPT: the sync is a re-read, so a doubled trigger costs one
HTTP call, while dropping a subscription could lose a movement nobody has thought of yet.
"""
import asyncio
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

MOD = SRC / "agentvault_registry" / "background_tasks" / "eventstore_balance_sync.py"

# Captured verbatim from EU's EventStore — the cross-frame debit that left the cache stale.
LEDGER_EVENT = {
    "net": "0E-18",
    "kind": "transfer",
    "txid": 967,
    "frame": "teg-layer",
    "entries": [
        {"agent_did": "did:theprotocol:eu.theprotocol.cloud:8fad1ffd-383d-4e3d-820f-9a83031ea806",
         "delta_liquid": "-10.000000000000000000", "delta_staked": "0"},
        {"agent_did": "did:theprotocol:teg_system_fx_reserve",
         "delta_liquid": "10.000000000000000000", "delta_staked": "0"},
    ],
}


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _drive(reactor_cls, event):
    """Run the real handler with the sync helper spied, and return the DIDs it asked for."""
    from agentvault_registry.background_tasks import eventstore_balance_sync as m

    asked = []

    async def _spy(did):
        asked.append(did)

    real = m._sync_agent_from_teg
    m._sync_agent_from_teg = _spy
    try:
        r = reactor_cls.__new__(reactor_cls)          # no base __init__: we only want handle_event
        _run(r.handle_event(event))
    finally:
        m._sync_agent_from_teg = real
    return asked


def test_a_ledger_movement_syncs_the_agent_it_names():
    from agentvault_registry.background_tasks.eventstore_balance_sync import LedgerBalanceSyncReactor

    asked = _drive(LedgerBalanceSyncReactor, LEDGER_EVENT)
    assert "did:theprotocol:eu.theprotocol.cloud:8fad1ffd-383d-4e3d-820f-9a83031ea806" in asked, asked


def test_the_ledger_reactor_is_subscribed_to_the_universal_event():
    from agentvault_registry.background_tasks.eventstore_balance_sync import LedgerBalanceSyncReactor

    assert LedgerBalanceSyncReactor.event_type == "LedgerBalanceChanged"
    # a distinct lock, or the two reactors fight over one leadership key
    from agentvault_registry.background_tasks.eventstore_balance_sync import BalanceSyncReactor
    assert LedgerBalanceSyncReactor.leader_key != BalanceSyncReactor.leader_key


def test_the_transfer_reactor_still_works():
    """CONTROL — the subscription that already worked must keep working."""
    from agentvault_registry.background_tasks.eventstore_balance_sync import BalanceSyncReactor

    asked = _drive(BalanceSyncReactor,
                   {"from": "did:theprotocol:eu.x:aaa", "to": "did:theprotocol:eu.x:bbb"})
    assert asked == ["did:theprotocol:eu.x:aaa", "did:theprotocol:eu.x:bbb"], asked


def test_system_accounts_are_skipped_and_the_old_guard_would_not_have_skipped_them():
    """The live system DIDs are `did:theprotocol:teg_system_treasury` / `…_fx_reserve`.

    The previous guard tested `startswith("teg:system:")`, which matches NEITHER — so every
    treasury leg spent an HTTP call to look up an agent that does not exist. This pins both the
    fix and the reason it was needed.
    """
    from agentvault_registry.background_tasks.eventstore_balance_sync import _is_system

    for did in ("did:theprotocol:teg_system_treasury",
                "did:theprotocol:teg_system_fx_reserve",
                "teg:system:exchange_escrow"):
        assert _is_system(did), did
        assert not did.startswith("teg:system:") or did == "teg:system:exchange_escrow"
    assert not _is_system("did:theprotocol:eu.theprotocol.cloud:8fad1ffd")


def test_the_helper_no_longer_swallows_silently():
    """A handler that cannot fail out loud is why this survived two frames."""
    src = MOD.read_text()
    assert "except Exception:\n        # Swallow" not in src
    assert "pass\n" not in src.split("async def _sync_agent_from_teg")[1].split("class ")[0] \
        or "_count(" in src, "every failure path must count and log"
    assert src.count("_count(") >= 5, "outcomes must be counted, not inferred from silence"
    assert "row 164" in src, "the finding that earned this must be named at the fix"


def test_both_reactors_are_started():
    """A reactor nobody starts is a subscription that does not exist."""
    src = MOD.read_text()
    body = src.split("async def start()")[1].split("async def stop()")[0]
    assert "BalanceSyncReactor()" in body and "LedgerBalanceSyncReactor()" in body, body
    stop_body = src.split("async def stop()")[1]
    assert stop_body.count(".stop()") >= 2, "both must be stopped too"
