"""§FRAMEFORM showcase (2026-09-14): the certificate step waits for public DNS instead of asking once.

hansa's standup stopped at `vhosts` a minute after its runner had seen all four names answer: an anycast node behind
1.1.1.1 still served the negative answer a plan had seeded before the record existed (the zone's negative TTL is
1800 s). `issue_cert` now asks until each name answers, inside FRAME_DNS_WAIT_S. Every host command is faked: nothing
is resolved, issued or slept for real.

The control: run against the pre-fix copy (EXTRAS_UNDER_TEST=standup_extras.py.bak-pre-dnspoll-20260914) and the first
test must fail.
"""
import importlib.machinery
import importlib.util
import os
import pathlib
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
UNDER_TEST = pathlib.Path(os.environ.get("EXTRAS_UNDER_TEST") or HERE.parent / "standup_extras.py")
LIVE_PREFIX = "/etc/letsencrypt/live/"


def load():
    loader = importlib.machinery.SourceFileLoader("standup_extras_under_test", str(UNDER_TEST))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


class Host:
    """dig answers per name, one per question (the last one repeats); certbot issues; the clock only moves by sleep."""

    def __init__(self, mod, monkeypatch, answers):
        self.answers = {name: list(seq) for name, seq in answers.items()}
        self.asked, self.certbot, self.issued, self.clock = {}, 0, False, [0.0]

        def run(cmd, *args, **kwargs):
            done = types.SimpleNamespace(stdout="", stderr="", returncode=0)
            if cmd[0] == "dig" and cmd[-1] == "A":
                name = cmd[-2]
                self.asked[name] = self.asked.get(name, 0) + 1
                seq = self.answers.get(name, ["203.0.113.10"])
                done.stdout = (seq.pop(0) if len(seq) > 1 else seq[0]) + "\n"
            elif cmd[0] == "certbot":
                self.certbot += 1
                self.issued = True
            return done

        real_exists = pathlib.Path.exists
        monkeypatch.setattr(mod.subprocess, "run", run)
        monkeypatch.setattr(mod.time, "sleep", lambda seconds: self.clock.__setitem__(0, self.clock[0] + seconds))
        monkeypatch.setattr(mod.time, "monotonic", lambda: self.clock[0])
        monkeypatch.setattr(mod.Path, "exists", lambda p: self.issued if str(p).startswith(LIVE_PREFIX) else real_exists(p))
        monkeypatch.setattr(mod, "log", lambda *a, **k: None)


def test_a_name_that_answers_on_a_later_question_does_not_stop_the_standup(monkeypatch):
    mod = load()
    stale = f"hansa-es.{mod.DOMAIN}"
    host = Host(mod, monkeypatch, {stale: ["", "", "203.0.113.10"]})
    live = mod.issue_cert("hansa")
    assert live.endswith(f"{LIVE_PREFIX.rstrip('/')}/hansa.{mod.DOMAIN}/fullchain.pem".split("/etc", 1)[1])
    assert host.asked[stale] == 3 and host.certbot == 1


def test_a_name_that_never_answers_still_stops_it_inside_the_bound(monkeypatch):
    mod = load()
    monkeypatch.setenv("FRAME_DNS_WAIT_S", "30")
    missing = f"hansa-push.{mod.DOMAIN}"
    host = Host(mod, monkeypatch, {missing: [""]})
    with pytest.raises(AssertionError, match="does not resolve at 1.1.1.1"):
        mod.issue_cert("hansa")
    assert host.certbot == 0 and host.clock[0] <= 35


def test_a_certificate_already_issued_asks_nothing(monkeypatch):
    mod = load()
    host = Host(mod, monkeypatch, {})
    host.issued = True
    mod.issue_cert("hansa")
    assert host.asked == {} and host.certbot == 0
