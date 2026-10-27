"""§FXSTRAND-2 (2026-09-07) — A FRAME THAT CAN PARK FUNDS MUST BE ABLE TO UNPARK THEM.

agentvault2-eb measured route 511e702c sitting `pending / retries 0 / last_error null` for nine
minutes with 1.99 at the gateway's @fx_router and the sender 48 of 50. Nothing was retrying, and
two things made that invisible:

  * `fx_router_keeper._should_run` returned before REGISTERING, so `/admin/workers/status` (102 rows)
    listed no `fx_router_keeper` at all — and ABSENT reads exactly like NO SUCH WORKER;
  * `_cycle_once` returned early on `not cfg.enabled`, so the dead-letter drain sat behind the
    LIQUIDITY switch even though `dead_letter_refund_enabled` is its own column and defaults TRUE.
    The frame therefore read as configured-for-refunds while being silenced.

§FXSELFHEAL already carved remote recovery out of that switch ("a frame can hold other frames'
parked funds while its own float manager is off"). This is the same carve-out, third half: the
liquidity switch decides whether to MOVE TREASURY MONEY; returning someone's own parked funds is
not that decision.
"""
import ast
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "src" / "agentvault_registry" / "background_tasks" / "fx_router_keeper.py")


def _fn(name, tree=None):
    tree = tree or ast.parse(SRC.read_text())
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found")


def _env_names(node):
    """Every os.getenv("X", ...) key read inside a node."""
    out = set()
    for c in ast.walk(node):
        if (isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "getenv"
                and c.args and isinstance(c.args[0], ast.Constant)):
            out.add(c.args[0].value)
    return out


def test_running_the_route_engine_is_its_own_reason_to_run():
    """A frame holding an @fx_router with the engine on can park — so the worker must register."""
    assert "FX_ROUTE_ENABLED" in _env_names(_fn("_should_run")), (
        "_should_run ignores FX_ROUTE_ENABLED: a frame that parks funds would not register the "
        "worker that returns them, and an absent worker is indistinguishable from no such worker"
    )


def test_the_dead_letter_drain_is_reachable_when_liquidity_is_off():
    """The early-return branch (`not cfg.enabled`) must still call the drain."""
    cycle = _fn("_cycle_once")
    # the branch that returns on a disabled/absent config
    early = None
    for n in ast.walk(cycle):
        if isinstance(n, ast.If) and any(isinstance(x, ast.Return) for x in n.body):
            names = {a.attr for a in ast.walk(n.test)
                     if isinstance(a, ast.Attribute)}
            if "enabled" in names:
                early = n
                break
    assert early is not None, "the config-disabled early return was not found — re-read the cycle"
    called = {getattr(c.func, "attr", "") for c in ast.walk(early) if isinstance(c, ast.Call)}
    assert "_process_dead_letters" in called, (
        "the drain does not run while the liquidity switch is off — which is exactly the state that "
        "left 1.99 parked with dead_letter_refund_enabled: true beside it"
    )
    assert "_process_remote_parked" in called, "the §FXSELFHEAL carve-out must survive this change"


def test_the_drain_still_honours_its_own_column():
    """Reachable is not unconditional: `dead_letter_refund_enabled` still decides."""
    src = SRC.read_text()
    assert "cfg is None or cfg.dead_letter_refund_enabled" in src, (
        "the drain must be gated on its OWN column (absent config → the model default, True)"
    )


def test_the_drain_tolerates_a_missing_config_row():
    """It is now reachable with cfg=None, so it must not dereference one."""
    fn = _fn("_process_dead_letters")
    bare = [a.attr for a in ast.walk(fn)
            if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id == "cfg"]
    assert not bare, f"drain reads cfg.{bare} directly — a None config row would raise"


def test_control_the_old_shape_fails_both_gates():
    """RED control: the pre-fix source must be refused by the same two checks."""
    old = ast.parse('''
import os
class K:
    def _should_run(self):
        if not os.getenv("FX_ROUTER_DID", ""):
            return False
        if not os.getenv("FX_ENABLED", "false"):
            return False
        if os.getenv("FX_ROUTER_KEEPER_ENABLED", "false"):
            return True
        return _rr_keeper_enabled()
    async def _cycle_once(self):
        cfg = await self._load_config(db)
        if cfg is None or not cfg.enabled:
            rr_only = await self._process_remote_parked(db, cfg)
            return
        await self._process_dead_letters(db, cfg)
''')
    assert "FX_ROUTE_ENABLED" not in _env_names(_fn("_should_run", old))
    cycle = _fn("_cycle_once", old)
    early = next(n for n in ast.walk(cycle)
                 if isinstance(n, ast.If) and any(isinstance(x, ast.Return) for x in n.body)
                 and "enabled" in {a.attr for a in ast.walk(n.test) if isinstance(a, ast.Attribute)})
    called = {getattr(c.func, "attr", "") for c in ast.walk(early) if isinstance(c, ast.Call)}
    assert "_process_dead_letters" not in called, "the control must reproduce the silenced drain"
    assert "_process_remote_parked" in called, "the control must still show the §FXSELFHEAL half"


def test_the_status_rail_states_the_drains_own_truth():
    """§FXSTRAND-2b (eb's ask): `active` is the LIQUIDITY verdict; the drain needs its own field,
    and it must come from the worker's predicate rather than a second copy of the rule."""
    reg = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "agentvault_registry" / "routers" / "teg_integration.py")
    tree = ast.parse(reg.read_text())
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "fx_router_keeper_get":
            fn = n
    assert fn is not None, "fx_router_keeper_get not found"
    keys = {k.value for r in ast.walk(fn) if isinstance(r, ast.Return)
            and isinstance(r.value, ast.Dict)
            for k in r.value.keys if isinstance(k, ast.Constant)}
    assert "dead_letter_drain_active" in keys, (
        "the status payload cannot say whether parked funds can get home: `active` is env AND "
        "cfg.enabled, and the drain depends on neither"
    )
    calls = {getattr(c.func, "attr", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_should_run" in calls, (
        "the field re-derives the rule instead of asking the worker — a per-surface copy is how "
        "two truths drift apart"
    )
