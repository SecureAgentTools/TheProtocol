"""§MCPTEST30 V0639 (agentvault2-aa, 2026-10-24): on a registry that is not a sovereign mainframe, the hygiene probe
reads core/mainframe_gate.py's refusal as the gate's, never as the route's server error.

agentvault2-66's operator sweeps on V0637 read seven hygiene rows red per operator (getAdminFrameInvitation,
getAdminOperatorApplication, getBridgeStatus, getCloudOperatorHealth, getCloudOperatorLogs, getFederationLicenseDetail,
listAdminOperatorApplications): each route answered the gate's deliberate 503, "This feature runs on sovereign
mainframes only", before the hostile value reached it (sbxalphaop's own log, agentvault2-d6's read; the same values
on sbx-alpha answered 404 or 422). A gated route's hygiene cannot be measured there: the row is NOT MEASURED, naming
the gate. A real server error beside it stays the finding, and a 503 without the gate's words stays a server error.
The first two tests fail on V0637's module (the control).
"""
from __future__ import annotations

import inspect

from agentvault_registry.api_tests.contracts import input_hygiene as IH
from agentvault_registry.core import mainframe_gate

GATE = ("Error: getAdminFrameInvitation returned HTTP 503: This feature runs on sovereign mainframes only. "
        "Cloud-operators federate through their mainframe.")
answered = lambda ok, inner, code: bool(ok)  # noqa: E731


def test_the_gates_503_is_read_as_the_gate():
    assert IH.answer_kind(False, {"_text": GATE}, "503", answered) == ("gated", 503, None)
    # the admin GET helpers hand a refusal back as {status_code, upstream_error}
    assert IH.answer_kind(True, {"status_code": 503, "upstream_error": GATE[7:]}, "200", answered) == ("gated", 503, None)
    # the same words on a 404 (agentvault2-d6's V0639 gate) are still the gate's, never the route's refusal
    gate404 = GATE.replace("HTTP 503", "HTTP 404")
    assert IH.answer_kind(False, {"_text": gate404}, "404", answered) == ("gated", 404, None)


def test_a_route_only_its_gate_answered_is_not_measured():
    healthy, sentence, ev = IH.verdict({"nul": ("refused", 400, None), "escape": ("gated", 503, None),
                                        "long": ("gated", 503, None)})
    assert healthy is None and "mainframes only" in sentence and sentence.startswith("NOT MEASURED")
    assert ev["escape"] == "gated HTTP 503"


def test_a_503_without_the_gates_words_stays_a_server_error():
    assert IH.answer_kind(False, {"_text": "Error: x returned HTTP 503: upstream unavailable"}, "503",
                          answered)[:2] == ("server_error", 503)


def test_a_real_server_error_beside_the_gate_stays_the_finding():
    healthy, sentence, _ev = IH.verdict({"nul": ("server_error", 500, None), "escape": ("gated", 503, None),
                                         "long": ("gated", 503, None)})
    assert healthy is False and sentence.startswith("BUG-FIND: hygiene:")


def test_the_sentence_is_the_gates_own():
    assert IH.GATE_SENTENCE in inspect.getsource(mainframe_gate)
