"""§FRAMEPROV P1 (2026-09-13): a run a machine can follow, and a resume that never issues twice.

StepTracker is post_boot's do(): it must answer exactly what the inline do() answered, and add the progress events,
steps_done, and the one new refusal (a step that issues, completed by an earlier pass, never runs again). The two issuances
are pinned at their functions with the host faked: mint=False never POSTs, mint=True records the issuance the moment it
answers 200.
"""
import argparse
from decimal import Decimal
import importlib.util
import json
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("standup_driver_progress", HERE.parent / "standup_driver.py")
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

STEPS = ["compose", "spire", "seed", "login", "emission", "vhosts", "admin", "jurisdiction", "federate", "operators",
         "canary", "wire", "mtls"]


def _events(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def test_the_driver_still_names_the_same_steps():
    src = (HERE.parent / "standup_driver.py").read_text()
    assert f"_STEPS = {json.dumps(STEPS)}" in src


def test_a_full_run_opens_and_closes_every_step_it_asks_in_order(tmp_path):
    prog = drv.Progress(str(tmp_path / "progress.jsonl"))
    persisted = []
    t = drv.StepTracker(STEPS, progress=prog, on_done=persisted.append)
    for step in ["compose", "compose", "spire", "seed", "emission", "vhosts", "vhosts", "admin", "mtls"]:
        assert t.do(step) is True
    t.finish()
    ev = _events(prog.path)
    pairs = [(e["step"], e["event"]) for e in ev]
    expected = []
    for step in ["compose", "spire", "seed", "emission", "vhosts", "admin", "mtls"]:
        expected += [(step, "start"), (step, "end")]
    assert pairs == expected
    assert all(e["verdict"] == "ok" for e in ev if e["event"] == "end")
    assert t.done == ["compose", "spire", "seed", "emission", "vhosts", "admin", "mtls"] and persisted[-1] == t.done


def test_a_resume_skips_what_came_before_and_says_why_once(tmp_path):
    prog = drv.Progress(str(tmp_path / "progress.jsonl"))
    t = drv.StepTracker(STEPS, resume_from="federate", progress=prog)
    answers = [t.do(s) for s in ["compose", "compose", "jurisdiction", "federate", "operators"]]
    assert answers == [False, False, False, True, True]
    skips = [e for e in _events(prog.path) if e["event"] == "skip"]
    assert [s["step"] for s in skips] == ["compose", "jurisdiction"]
    assert skips[0]["sentence"] == "before --resume-from federate"


def test_resume_until_stops_after_the_named_step():
    t = drv.StepTracker(STEPS, resume_from="spire", until="spire")
    assert [t.do(s) for s in ["compose", "spire", "seed"]] == [False, True, False]


@pytest.mark.parametrize("step", ["emission", "admin"])
def test_a_minting_step_an_earlier_pass_completed_never_runs_again(tmp_path, step):
    prog = drv.Progress(str(tmp_path / "progress.jsonl"))
    t = drv.StepTracker(STEPS, resume_from="compose", done=["compose", step], progress=prog)
    assert t.do("compose") is True, "a completed step that issues nothing re-runs on a resume from it"
    assert t.do(step) is False
    skip = [e for e in _events(prog.path) if e["event"] == "skip"][0]
    assert skip["step"] == step and "it issues units" in skip["sentence"]


def test_the_old_inline_do_answers_are_unchanged_when_nothing_is_done():
    def old(step, resume_from, until):
        if until and STEPS.index(step) > STEPS.index(until):
            return False
        return resume_from is None or STEPS.index(step) >= STEPS.index(resume_from)
    for resume_from in [None] + STEPS:
        for until in [None] + STEPS:
            t = drv.StepTracker(STEPS, resume_from=resume_from, until=until)
            for step in STEPS:
                assert (t._refusal(step) == "") == old(step, resume_from, until), (resume_from, until, step)


def test_die_records_the_refusal_against_the_open_step(tmp_path, monkeypatch, capsys):
    prog = drv.Progress(str(tmp_path / "progress.jsonl"))
    prog.start("emission")
    monkeypatch.setattr(drv, "PROGRESS", prog)
    with pytest.raises(SystemExit):
        drv.die("emission gate: EventStore not healthy")
    last = _events(prog.path)[-1]
    assert (last["step"], last["event"], last["verdict"]) == ("emission", "fail", "refused")
    assert "EventStore not healthy" in last["sentence"] and "EventStore not healthy" in capsys.readouterr().err


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, body=None, headers=None, timeout=20, form=False):
        self.calls.append((method, url))
        if url.endswith("/api/v1/projections/supply-audit"):
            return 200, {"tokens_issued": 1.0}
        return 200, {}

    def mints(self):
        return [u for _, u in self.calls if u.endswith("/api/v1/teg/treasury/mint")]


def _args():
    return argparse.Namespace(name="juice", ticker="JUC", frame_label="Juice", mint="1000000", description="d",
                              operator_label="o", location_label="l", lat=1.0, lng=2.0, website="https://example.org",
                              card_json=None, theme="neural", flare_encirclement="", flare_overlay="", logo=None)


@pytest.mark.parametrize("mint", [True, False])
def test_the_canary_is_minted_at_most_once_and_recorded_the_moment_it_is(monkeypatch, mint):
    monkeypatch.setattr(drv, "wait_for", lambda desc, fn, tries=60, sleep=3: True)
    monkeypatch.setattr(drv, "_exec_http", lambda container, url, **kw: (True, "HTTP 200"))

    def fake_run(cmd, *a, **kw):
        if "rpk" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "Healthy: true\n", "")
        if "psql" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "t\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(drv.subprocess, "run", fake_run)
    rec = Recorder()
    monkeypatch.setattr(drv, "http", rec)
    minted = []
    drv.emission_gate(_args(), "jwt", mint=mint, on_minted=lambda: minted.append(1))
    assert len(rec.mints()) == (1 if mint else 0) and len(minted) == (1 if mint else 0)


class MintRail(Recorder):
    """The registry's issuance rail as its validator answers: a piece above the ceiling is refused 422, and the `refuse_at`-th
    call answers 503 (a TEG gone half way). `ledger` is the frame's own ledger: the canary plus every accepted piece."""

    def __init__(self, ceiling="1000000", refuse_at=None, earlier="0"):
        super().__init__()
        self.ceiling, self.refuse_at = Decimal(ceiling), refuse_at
        self.minted, self.bodies = Decimal(earlier), []

    def __call__(self, method, url, body=None, headers=None, timeout=20, form=False):
        if not url.endswith("/api/v1/teg/treasury/mint"):
            return super().__call__(method, url, body, headers, timeout, form)
        self.calls.append((method, url))
        self.bodies.append(body)
        if Decimal(body["amount"]) > self.ceiling:
            return 422, {"detail": f"Amount exceeds maximum ({self.ceiling:,})"}
        if self.refuse_at == len(self.bodies):
            return 503, {"detail": "TEG Layer unavailable for the issuance"}
        self.minted += Decimal(body["amount"])
        return 200, {"transaction_id": f"tx-{len(self.bodies)}"}

    def ledger(self, name):
        return (Decimal("0"), Decimal("1") + self.minted), ""


def _mint_fakes(monkeypatch, rail):
    monkeypatch.setattr(drv, "http", rail)
    monkeypatch.setattr(drv, "resolve_logo", lambda path: None)
    monkeypatch.setattr(drv.extras, "card_extras", lambda path: {})
    monkeypatch.setattr(drv.extras, "registry_mint_ceiling", lambda name: (rail.ceiling, "the registry (profile)"))
    monkeypatch.setattr(drv, "_ledger_read", rail.ledger)
    monkeypatch.setattr(drv, "wait_for", lambda desc, fn, tries=60, sleep=3: fn()[0])


def _mint_args(amount):
    return argparse.Namespace(**{**vars(_args()), "mint": amount})


@pytest.mark.parametrize("mint", [True, False])
def test_the_show_mint_is_made_at_most_once_and_recorded_the_moment_it_is(monkeypatch, mint):
    rail = MintRail(earlier="0" if mint else "1000000")
    _mint_fakes(monkeypatch, rail)
    minted = []
    drv.admin_pass(_args(), "jwt", mint=mint, on_minted=minted.append)
    assert len(rail.mints()) == (1 if mint else 0) and minted == ([Decimal("1000000")] if mint else [])


def test_the_control_the_old_single_call_of_the_whole_amount_is_what_the_rail_refuses():
    rail = MintRail()
    assert rail("POST", "http://r/api/v1/teg/treasury/mint", {"amount": "5000000", "reason": "x"})[0] == 422
    assert rail.minted == 0


def test_a_mint_above_the_ceiling_lands_whole_in_pieces(monkeypatch):
    rail = MintRail()
    _mint_fakes(monkeypatch, rail)
    totals = []
    drv.admin_pass(_mint_args("5000000"), "jwt", on_minted=totals.append)
    assert [b["amount"] for b in rail.bodies] == ["1000000"] * 5 and rail.minted == Decimal("5000000")
    assert totals == [Decimal(n * 1000000) for n in range(1, 6)] and rail.bodies[-1]["reason"].endswith("(part 5 of 5)")


def test_a_refused_piece_stops_the_step_and_the_resume_mints_only_the_rest(monkeypatch):
    rail = MintRail(refuse_at=3)
    _mint_fakes(monkeypatch, rail)
    totals = []
    with pytest.raises(SystemExit):
        drv.admin_pass(_mint_args("5000000"), "jwt", on_minted=totals.append)
    assert rail.minted == Decimal("2000000") and totals == [Decimal("1000000"), Decimal("2000000")]
    resumed = MintRail(earlier=str(rail.minted))
    _mint_fakes(monkeypatch, resumed)
    drv.admin_pass(_mint_args("5000000"), "jwt", minted_before=str(totals[-1]), on_minted=totals.append)
    assert [b["amount"] for b in resumed.bodies] == ["1000000"] * 3 and resumed.minted == Decimal("5000000")
    assert totals[-1] == Decimal("5000000")


def test_a_mint_the_ledger_does_not_show_stops_the_step(monkeypatch):
    rail = MintRail()
    _mint_fakes(monkeypatch, rail)
    monkeypatch.setattr(drv, "_ledger_read", lambda name: ((Decimal("0"), Decimal("1")), ""))
    with pytest.raises(SystemExit):
        drv.admin_pass(_mint_args("2000000"), "jwt", on_minted=lambda total: None)


def test_post_boot_hands_the_run_meta_to_both_mints_and_uses_the_tracker():
    src = (HERE.parent / "standup_driver.py").read_text()
    assert 'emission_gate(args, jwt, mint=not meta.get("canary_minted")' in src
    assert 'admin_pass(args, jwt, mint=not meta.get("show_minted")' in src
    assert "do = tracker.do" in src and "tracker.finish()" in src
