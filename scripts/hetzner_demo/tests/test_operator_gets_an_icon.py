"""§FRAMELIC findings row 188 — an operator without an icon renders a plain orb forever.

The FE's peer chain is flare -> `visual.icon_url` -> plain orb. A frame gets its mark uploaded
post-boot (`--logo`, row 153); the operator provisioner never did, so every operator this
cluster stood up was iconless BY CONSTRUCTION. His report was "registries logos not displaying",
and fixing only the card-validation half (row 187) would have made the cards store and left the
orbs plain — "the fix worked, the symptom remains", which is the most expensive shape there is.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DRIVER = (REPO / "scripts/hetzner_demo/standup_driver.py").read_text()


def test_the_driver_uploads_an_operator_icon_before_the_provisioned_step_returns():
    assert "_op_icon(" in DRIVER
    i = DRIVER.index('_op_icon(f"http://127.0.0.1:{op_port}"')
    # the MAIN return (the provisioned one) — NOT the first `return {"application_id"` in the
    # file, which is the prestage early-out below. My first draft used index() and found that
    # one, which is how this test discovered the second path at all.
    j = DRIVER.index('return {"application_id": app_id, "slug": slug, "port": op_port,')
    assert i < j, "the icon must be uploaded before the provisioned step returns"


def test_the_PRESTAGE_early_return_is_deliberately_exempt():
    """--prestage-operator activated stops BEFORE provisioning ("Nothing container-side has
    happened yet"), so there is no operator serving a card to upload to. An icon step there
    would dial a port nobody is listening on. This leg exists so a future reader does not
    'fix' the exemption — the two returns are two different states, not a missed branch."""
    pre = DRIVER.index('return {"application_id": app_id, "slug": slug, "prestaged": "activated"')
    icon = DRIVER.index('_op_icon(f"http://127.0.0.1:{op_port}"')
    assert pre < icon, "the prestage path must return before the icon step is reached"
    assert '"containers": 0' in DRIVER[pre:pre + 300], "prestage means nothing is running yet"


def test_it_verifies_by_reading_the_SERVED_card_not_the_upload_status():
    """Row 153's lesson: the console reads visual.icon_url off the served card and nothing else,
    so an HTTP 200 on the upload is not proof."""
    body = DRIVER[DRIVER.index("def _op_icon("):]
    body = body[:body.index("\ndef ", 1)]
    assert "/.well-known/registry-card.json" in body
    assert "icon_url" in body


def test_the_multipart_post_passes_form_true():
    """Without it, http() runs json.dumps over multipart BYTES and raises OUTSIDE its try block,
    killing the standup — the frame path learned this the hard way."""
    body = DRIVER[DRIVER.index("def _op_icon("):]
    body = body[:body.index("\ndef ", 1)]
    m = re.search(r"registry-card/icon\"[^\n]*\n?[^\n]*", body)
    assert m and "form=True" in m.group(0), "the icon POST must pass form=True"


def test_a_missing_icon_never_fails_a_working_standup_but_is_always_NAMED():
    """Cosmetic must not abort a provisioned operator — but a SILENT skip is exactly how this
    gap survived, so every failure path logs 'NO ICON' with its reason."""
    body = DRIVER[DRIVER.index("def _op_icon("):]
    body = body[:body.index("\ndef ", 1)]
    # the function has exactly two refusal RETURNS (asset missing, admin login failed) and both
    # name themselves; the verify line then names MISSING when the upload did not publish. That
    # is full coverage of its exits — asserting an arbitrary count instead would be a number
    # chosen to pass rather than a property.
    assert body.count("NO ICON") == 2, "both refusal returns must say NO ICON and why"
    assert body.count("return") == 2, "exactly two refusal returns; the success path falls off the end"
    assert "MISSING" in body, "a published-but-empty icon must be named too"
    call = DRIVER[DRIVER.index("_icon_admin = "):]
    call = call[:call.index('return {"application_id": app_id, "slug": slug, "port": op_port,')]
    assert "except Exception" in call, "a cosmetic step must never abort a provisioned operator"
    assert "NO ICON" in call, "and the failure must still be named, not swallowed"


def test_the_mark_follows_the_frame_theme():
    """--logo follows --theme for the frame (row 153); an operator of a sovereign frame must not
    get the neural mark."""
    body = DRIVER[DRIVER.index("def _op_icon("):]
    body = body[:body.index("\ndef ", 1)]
    assert 'protocol-mark-{theme}.png' in body
