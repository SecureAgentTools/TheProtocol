"""V0651 (u) (2026-10-31, agentvault2-14, from the dev machine's beta.29 findings 9 and 10): agent mTLS on a kit frame
needs its frame runner, and the runner comes with a fresh standup.

Order gwo_ac0afc009bba4c9d3210041a. On the dev machine a beta.29 frame stood up without --with-runner answered
enable-mtls with 503 naming the runner, and frame-up refused to add the runner to the standing frame: the way there is a
fresh standup (frame-down, then frame-up.py --with-runner; the frame's accounts and agents go). The registry's sentence
and the console's operator pages (15_frame_federation, 21_ai_operations_brief) now say so. Each case fails on 48d07ecf2
(V0650), whose sentence and pages name --with-runner but not the fresh standup.
"""
from __future__ import annotations

import pathlib

from agentvault_registry.routers import agent_mtls
from agentvault_registry.routers.agent_mtls import _runner_unavailable_detail

DOCS = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "static" /
        "new_registry_frontend" / "src" / "assets" / "docs" / "operator")


def test_the_503_sentence_says_the_runner_comes_with_a_fresh_standup():
    s = _runner_unavailable_detail(RuntimeError("connection refused"))
    for words in ("frame-up.py --with-runner", "fresh standup", "frame-down, then frame-up.py --with-runner",
                  "the frame's accounts and agents go with the old one", "agent JWTs meanwhile",
                  "connection refused"):
        assert words in s, words


def test_both_operator_pages_name_the_runner_and_the_fresh_standup():
    for page in ("15_frame_federation.md", "21_ai_operations_brief.md"):
        text = " ".join((DOCS / page).read_text().split())
        assert "frame-up.py --with-runner" in text and "fresh standup" in text, page
        assert "enable-mtls" in text and "503" in text, page


def test_the_on_box_answer_says_the_first_fetch_can_wait_for_its_entry(monkeypatch):
    # the dev machine's beta.29 finding 11 (2026-10-31): after an on-box enable-mtls (HTTP 200, delivery workload_api)
    # the labelled container's first fetch answered "PermissionDenied: no identity issued" and 15 s later "Received 1
    # svid": the answer now says the first fetch can be refused for a few seconds, and to retry
    monkeypatch.setattr(agent_mtls, "_socket_volume", lambda mount_dir, text=None: "devframe29_spire-agent-socket")
    r = agent_mtls._attach_delivery({}, None, "did:theprotocol:test:0000", "did_theprotocol_test_0000",
                                     deployment="onbox", signal="test")
    assert r["delivery"] == "workload_api"
    s = " ".join(r["instructions"].split())
    assert "no identity issued" in s and "a few seconds" in s and "retry" in s, s


def test_undoing_your_half_dissociates_the_bundle_and_names_beta30s_own_undo():
    # session-lead's correction (2026-10-31, seq 224): SPIRE's default bundle delete mode (restrict) refuses a bundle the
    # workload entries step 3 federated still name; `-mode dissociate` takes it off them. And from kit beta.30
    # frame-federate.py takes its half back itself on a refusal (--keep-trust-on-refusal keeps it).
    text = " ".join((DOCS / "15_frame_federation.md").read_text().split())
    assert "bundle delete -id spiffe://<peer trust domain> -mode dissociate" in text
    assert "--keep-trust-on-refusal" in text and "1.0.0-beta.30" in text
