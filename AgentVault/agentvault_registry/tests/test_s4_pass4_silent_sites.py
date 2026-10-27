"""§S4 pass 4 (2026-09-05) — three money files' silent handlers now leave a trace. Source-pinned, RED on the pre-pass tree:
  guild.py: the bid-race stake refund no longer fails into a bare `pass`; the guild emit is a WARNING + counted
  exchange_service.py: the treasury participant provisioning error at approval speaks; order_filled notify is a WARNING
  treasury_market_maker.py: the seven DEBUG "skip" lines are one counted WARNING helper
"""
import pathlib
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")

def test_guild_stake_refund_and_emit_are_not_silent():
    s = (SRC / "routers/guild.py").read_text()
    assert "except Exception: pass  # noqa: BLE001" not in s, "the bid-race stake refund still fails silently"
    assert s.count('_count_silent("stake_refund_failed")') == 1
    assert 'logger.debug("[GUILD] emit %s skipped"' not in s and '_count_silent(f"emit_failed:{event_type}")' in s
    assert "guild_silent_failure_total" in s

def test_exchange_approval_and_notify_speak():
    s = (SRC / "services/exchange_service.py").read_text()
    assert "pass  # enforcement errors don't apply to the treasury grant itself" not in s
    assert "treasury participant for %s not provisioned at approval" in s
    assert 'logger.debug("[NOTIFY] exchange.order_filled emit failed"' not in s
    assert "order_filled emit failed for trade" in s

def test_market_maker_skips_are_counted():
    s = (SRC / "background_tasks/treasury_market_maker.py").read_text()
    assert 'logger.debug(f"[treasury_mm]' not in s, "a DEBUG skip survived"
    assert s.count("_note_skip(") == 8 and "treasury_mm_op_failed_total" in s   # 7 sites + the def
