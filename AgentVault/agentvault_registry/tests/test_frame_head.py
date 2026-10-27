"""§FEFRAME W2: the console's head and web manifest name the frame that serves them (core/frame_head.py).

The control in each case is the page as built: before W2 every registry served the flagship's title, canonical and
og:url, so ASIA's console previewed as theprotocol.cloud."""
import json

from agentvault_registry.core import frame_head as fh

BUILT = """<!DOCTYPE html><html><head>
    <title>TheProtocol — Sovereign AI Agent Registry</title>
    <meta name="description" content="Sovereign AI agent orchestration platform with AVT token economy.">
    <link rel="canonical" href="https://theprotocol.cloud/">
    <meta property="og:title" content="TheProtocol — Sovereign AI Agent Registry">
    <meta property="og:description" content="old">
    <meta property="og:url" content="https://api.theprotocol.cloud/ui">
    <meta property="og:image" content="https://api.theprotocol.cloud/static/og-image.jpg">
    <meta name="twitter:title" content="TheProtocol — Sovereign AI Agent Registry">
    <meta name="twitter:description" content="old">
    <meta name="twitter:image" content="https://api.theprotocol.cloud/static/og-image.jpg">
</head><body></body></html>"""

ASIA = {"key": "asia", "name": "ASIA", "display_name": "ASIA", "role": "frame", "theme": "sovereign",
        "public_url": "https://asia.theprotocol.cloud", "console_url": "https://asia.theprotocol.cloud",
        "currency": "ACU", "currency_name": "Asian Compute Unit"}


def test_asia_renders_its_own_head():
    out = fh.render_index(BUILT, ASIA)
    assert "<title>ASIA — TheProtocol</title>" in out
    assert '<link rel="canonical" href="https://asia.theprotocol.cloud/">' in out
    assert '<meta property="og:url" content="https://asia.theprotocol.cloud/">' in out
    assert '<meta property="og:image" content="https://asia.theprotocol.cloud/static/og-image.jpg">' in out
    assert '<meta name="tp-frame-theme" content="sovereign">' in out
    assert "settling in Asian Compute Unit" in out
    # nothing of the flagship's addresses survives
    assert "api.theprotocol.cloud" not in out and 'href="https://theprotocol.cloud/"' not in out


def test_an_operator_says_what_it_is():
    ams = {**ASIA, "key": "amsterdam", "display_name": "Amsterdam", "role": "operator", "theme": "neural",
           "public_url": "https://amsterdam.op.theprotocol.cloud", "console_url": "https://amsterdam.op.theprotocol.cloud",
           "currency": "ECU", "currency_name": None}
    out = fh.render_index(BUILT, ams)
    assert "a cloud operator of the TheProtocol federation, settling in ECU" in out
    assert '<meta name="tp-frame-theme" content="neural">' in out


def test_no_manifest_serves_the_page_as_built():
    assert fh.render_index(BUILT, None) == BUILT
    assert fh.render_index(BUILT, {"key": "x"}) == BUILT              # no display name: nothing to say


def test_values_are_escaped():
    evil = {**ASIA, "display_name": 'A"><script>x</script>'}
    out = fh.render_index(BUILT, evil)
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;" in out or "&quot;" in out


def test_a_missing_tag_is_skipped_not_invented():
    bare = "<html><head><title>x</title></head></html>"
    out = fh.render_index(bare, ASIA)
    assert "<title>ASIA — TheProtocol</title>" in out and "canonical" not in out


def test_the_web_manifest_names_the_frame():
    raw = json.dumps({"id": "/ui/", "name": "TheProtocol — POCKET FRAME", "short_name": "Pocket",
                      "start_url": "/ui/#/pocket/home", "theme_color": "#07090d"})
    m = json.loads(fh.render_webmanifest(raw, ASIA))
    assert m["name"] == "ASIA — TheProtocol POCKET FRAME"
    assert m["short_name"] == "Pocket" and m["start_url"] == "/ui/#/pocket/home" and m["theme_color"] == "#07090d"
    assert fh.render_webmanifest(raw, None) == raw
    assert fh.render_webmanifest("not json", ASIA) == "not json"
