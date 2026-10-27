"""§BATCH4 (2026-09-05): the buy rail's release-by-id leg must READ the release response.

A service's /verify consumes the token before the service can refuse the work; release-by-id then
answers 400 ("Cannot release token in status: consumed"). The leg used to set
settlement_status="released" on ANY response, so the caller was told a reservation was handed
back that was not. RED against the V0222 lineage and the first batch-4 canary (ebaecc7fcad3).
"""
import pathlib, re

HERE = pathlib.Path(__file__).resolve().parent
SRC = (HERE.parent / "src" / "agentvault_registry" / "routers" / "a2a_payment.py")
if not SRC.is_file():  # in-image layout: /w/tests + /w/src -> /app/src
    SRC = HERE.parent / "src" / "agentvault_registry" / "routers" / "a2a_payment.py"


def _leg() -> str:
    text = SRC.read_text(encoding="utf-8")
    m = re.search(r"release-by-id/\{token_id\}.*?except Exception as e:", text, re.S)
    assert m, "release-by-id leg not found"
    return m.group(0)


def test_release_by_id_leg_reads_the_status_code():
    leg = _leg()
    assert "status_code == 200" in leg, "the leg must gate 'released' on a 200"
    assert "release_refused" in leg, "a non-200 must be reported, never rendered as released"


def test_a_refused_release_is_counted_not_swallowed():
    leg = _leg()
    assert '_note_buy_leg_failed("release_by_id"' in leg
