"""Unit tests for Agent Evals deterministic scorers (services/eval_scoring.py).

Dependency-free — importable without the app/DB. Run direct (`python3 file.py`) or pytest.
"""
import importlib.util
import os

_HERE = os.path.dirname(__file__)
_MOD = os.path.abspath(os.path.join(
    _HERE, "..", "src", "agentvault_registry", "services", "eval_scoring.py"
))
_spec = importlib.util.spec_from_file_location("eval_scoring", _MOD)
eval_scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_scoring)
score_task = eval_scoring.score_task
aggregate = eval_scoring.aggregate


def test_status_ok():
    assert score_task("status_ok", None, status_code=200, body="", latency_ms=5) == (1.0, True)
    assert score_task("status_ok", None, status_code=204, body="", latency_ms=5) == (1.0, True)
    assert score_task("status_ok", None, status_code=500, body="", latency_ms=5) == (0.0, False)
    assert score_task("status_ok", None, status_code=None, body="", latency_ms=5) == (0.0, False)


def test_exact_and_contains():
    assert score_task("exact", {"value": "ok"}, status_code=200, body=" ok ", latency_ms=1) == (1.0, True)
    assert score_task("exact", {"value": "ok"}, status_code=200, body="nope", latency_ms=1) == (0.0, False)
    assert score_task("contains", {"value": "pong"}, status_code=200, body="ping pong", latency_ms=1) == (1.0, True)
    assert score_task("contains", {"value": "zzz"}, status_code=200, body="ping", latency_ms=1) == (0.0, False)


def test_regex_including_bad_pattern():
    assert score_task("regex", {"value": r"^v\d+"}, status_code=200, body="v12 hi", latency_ms=1) == (1.0, True)
    assert score_task("regex", {"value": r"^v\d+"}, status_code=200, body="hi", latency_ms=1) == (0.0, False)
    # Malformed regex must not raise — scores 0.
    assert score_task("regex", {"value": "["}, status_code=200, body="x", latency_ms=1) == (0.0, False)


def test_latency():
    s, p = score_task("latency_under_ms", {"value": 1000}, status_code=200, body="", latency_ms=200)
    assert p and s > 0.5
    s, p = score_task("latency_under_ms", {"value": 100}, status_code=200, body="", latency_ms=500)
    assert not p and s == 0.0
    s, p = score_task("latency_under_ms", {"value": None}, status_code=200, body="", latency_ms=None)
    assert not p and s == 0.0


def test_unknown_scorer_is_zero():
    assert score_task("nope", None, status_code=200, body="", latency_ms=1) == (0.0, False)


def test_aggregate():
    assert abs(aggregate([(1.0, 1), (0.0, 1)]) - 0.5) < 1e-9
    assert abs(aggregate([(1.0, 3), (0.0, 1)]) - 0.75) < 1e-9
    assert aggregate([]) == 0.0
    assert aggregate([(0.5, 0)]) == 0.0  # zero total weight


if __name__ == "__main__":
    for fn in [test_status_ok, test_exact_and_contains, test_regex_including_bad_pattern,
               test_latency, test_unknown_scorer_is_zero, test_aggregate]:
        fn()
    print("ALL PASS")
