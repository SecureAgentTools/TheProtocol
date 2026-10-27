"""§DOCKERLISTRACE (2026-09-29) — no container listing in the registry can be failed whole by one container that goes
away while it is being listed.

docker-py's `containers.list()` asks the daemon for the list and then INSPECTS every entry; a container removed in between
raises `NotFound` out of the list call itself, so the caller loses every row, not just the gone one. §DOCKERSTATSRACE
(V0490) closed the docker-stats route with a sparse listing; eleven more sites had the same shape, among them the two
teardown paths that list containers and then remove them (cloud_provisioner, frame_test_provisioner), which is where a
container disappearing mid-listing is most likely. `ignore_removed=True` is the SDK's own switch for this race (it skips
the gone entry and keeps the full inspect data the callers read: `.name`, `.status`, `.attrs`); `sparse=True` never
inspects at all. Every call must carry one of the two, and this gate reads the AST, never the text.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
SAFE = {"sparse", "ignore_removed"}


def _listing_calls(tree):
    """Every `<something>.containers.list(...)` call in a module."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "list"
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "containers"):
            yield node


def _is_guarded(call) -> bool:
    return any(k.arg in SAFE and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords)


def _scan():
    found, unguarded = 0, []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for call in _listing_calls(tree):
            found += 1
            if not _is_guarded(call):
                unguarded.append(f"{path.relative_to(SRC)}:{call.lineno}")
    return found, unguarded


def test_every_container_listing_survives_a_container_that_goes_away():
    found, unguarded = _scan()
    assert found >= 12, f"the scan found {found} listings; it measured 12 when written, so it is looking in the wrong place"
    assert not unguarded, ("a container removed while it is being listed fails the WHOLE listing: pass "
                           "ignore_removed=True (or sparse=True) at " + ", ".join(unguarded))


def test_the_detector_flags_a_bare_listing_and_accepts_both_guards():
    """Control: without this the gate could pass by recognising nothing."""
    tree = ast.parse("a = c.containers.list()\nb = c.containers.list(all=True, ignore_removed=True)\n"
                     "d = c.containers.list(sparse=True)\ne = c.containers.list(ignore_removed=False)\n")
    verdicts = [_is_guarded(call) for call in sorted(_listing_calls(tree), key=lambda n: n.lineno)]
    assert verdicts == [False, True, True, False]
