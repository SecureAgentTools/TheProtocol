"""§FRAMELIC (2026-09-07, findings row 153) — A FRAME MUST NOT BE BORN WEARING SOMEONE ELSE'S LOGO.

His report: *"eu and asia have hetzner logo instead of protocol logo as we agreed. this is bad."*

This driver was born as the Hetzner demo standup, so `--logo` defaulted to
`assets/hetzner-logo.png`. Every frame ever stood up from it published that PNG on its registry
card and on the globe. It was corrected by hand on the previous EU/ASIA pair; the teardown took
the correction with it and the next standup reproduced the defect — the same class as the SNI
line, the bundle cron and the AIO ceiling before it. So the fix is a DRIVER DEFAULT with a test,
not a runbook step: *"update the driver. so if we might have to reprovision clean we can do it
again smoothly, not like this."*

The mark follows `--theme`, which the driver already carries (row 62: two frames born from one
driver wore the same face until his eye caught it). Nothing here stops an operator naming their
own file with `--logo`; it stops the DEFAULT being a third party's brand.
"""
import pathlib
import re

DRIVER = pathlib.Path(__file__).resolve().parents[1] / "standup_driver.py"
ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
SRC = DRIVER.read_text()


def test_logo_has_no_hardcoded_default():
    """The argparse default must not name any file — it is resolved from the theme."""
    m = re.search(r'ap\.add_argument\("--logo",\s*default=([^,\n]+)', SRC)
    assert m, "--logo argument not found"
    assert m.group(1).strip() == "None", (
        f"--logo still carries a hardcoded default: {m.group(1)!r}")


def test_the_default_is_the_protocol_mark_for_the_theme():
    assert re.search(r'args\.logo\s*=\s*f".*protocol-mark-\{args\.theme\}\.png"', SRC), (
        "the resolved default must be the Protocol mark matching --theme")


def test_both_marks_are_actually_on_disk():
    """A default naming a file that does not exist degrades to the fallback sweep,
    which is how `hetzner-logo-PLACEHOLDER.png` once made five frames stand up bare."""
    for theme in ("neural", "sovereign"):
        p = ASSETS / f"protocol-mark-{theme}.png"
        assert p.is_file(), f"missing {p}"
        assert p.stat().st_size > 1024, f"{p} is suspiciously small"
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{p} is not a PNG"


def test_no_third_party_logo_is_reachable_as_a_default():
    """CONTROL — the Hetzner asset may stay in the tree (that frame is retired, not deleted),
    but nothing may point at it without the caller asking."""
    for line in SRC.splitlines():
        if "hetzner-logo" in line and "default=" in line:
            raise AssertionError(f"a third-party logo is a default again: {line.strip()}")
