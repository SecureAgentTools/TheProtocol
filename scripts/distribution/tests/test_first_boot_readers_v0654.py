"""V0654 recut (agentvault2-14, 2026-11-02): the stack's readers of the first-boot banner.

operator_seed (V0654 (aq), CodeQL #381) writes its generated first admin password to a 0600 file and its banner names the
FILE, never the password. The printed-password pattern matches that line too and takes the word "in" (V0654's first pair
proof, 2026-11-02 22:21Z). In the stack: operator-setup.sh's hint sent a person to grep the log, and the standup driver's
operator fallback read the banner. session-lead (the sessions' room seq 1169-1170) named both and asked for a check that no
reader takes the word after the colon. Red on master 8073b196 (both files read the old way); green on this branch."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
FILE = "/app/data/first-boot-admin-password"
LINE = f"  FIRST-BOOT ADMIN PASSWORD: in {FILE} (mode 600), inside the registry's container"   # operator_seed's line
OLD = r"FIRST-BOOT ADMIN PASSWORD:\s*(\S+)"


def test_the_setup_hint_reads_the_file_then_deletes_it():
    text = (ROOT / "scripts/distribution/operator-setup.sh").read_text()
    assert "FIRST-BOOT ADMIN PASSWORD" not in text
    assert f"docker exec ${{NAME}}-registry cat {FILE}" in text
    assert f"docker exec ${{NAME}}-registry rm {FILE}" in text


def test_the_standup_driver_asks_the_file_form_first():
    text = (ROOT / "scripts/hetzner_demo/standup_driver.py").read_text()
    new = 'r"FIRST-BOOT ADMIN PASSWORD: in (/\\S+) \\(mode 600\\)"'
    old = 'r"FIRST-BOOT ADMIN PASSWORD:\\s*(\\S+)"'
    assert new in text and old in text
    assert text.index(new) < text.index(old), "the file form must be asked before the printed one"
    assert '"cat", _f.group(1)' in text and '"rm", "-f", _f.group(1)' in text


def test_the_old_pattern_takes_the_word_in_and_the_file_form_takes_the_path():
    assert re.search(OLD, LINE).group(1) == "in"
    assert re.search(r"FIRST-BOOT ADMIN PASSWORD: in (/\S+) \(mode 600\)", LINE).group(1) == FILE


def test_no_other_stack_script_reads_the_banner():
    allowed = {"scripts/hetzner_demo/standup_driver.py"}
    found = set()
    for pat in ("*.py", "*.sh"):
        for p in (ROOT / "scripts").rglob(pat):
            if "/tests/" in str(p) or "/node_modules/" in str(p):
                continue
            try:
                if "FIRST-BOOT ADMIN PASSWORD" in p.read_text(errors="replace"):
                    found.add(str(p.relative_to(ROOT)))
            except OSError:
                pass
    assert found == allowed, sorted(found)
