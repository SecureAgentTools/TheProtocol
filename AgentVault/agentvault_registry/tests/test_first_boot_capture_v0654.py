"""V0654 recut (agentvault2-14, 2026-11-02): the provisioners read the first-boot password from the file the banner names.

V0654 (aq) folded in CodeQL #381: operator_seed writes a generated first admin password to a 0600 file and its banner
names the FILE, never the password (prod_seed does the same since V0653 (am) item 4). Three provisioners read the banner
from the container's log with `FIRST-BOOT ADMIN PASSWORD:\\s*(\\S+)`, which also matches the new line and takes the word
"in" for the password: V0654's first pair proof (2026-11-02 22:21Z) failed because the pair's new operator admin could not
log in with it, so every operator provisioned on V0654 would have handed its owner a wrong first login.
core/first_boot asks the file form first; host_work (the frame runner's one-shot, the docker CLI) and cloud_provisioner and
frame_test_provisioner (the docker SDK) read the file, then remove it; an older image's printed password still reads.
Red on the cut ddab16e89 (core/first_boot does not exist, the readers return "in"); green on the recut."""
from __future__ import annotations

import importlib.util
import pathlib
import re
import types

import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "agentvault_registry"
FILE = "/app/data/first-boot-admin-password"
OLD = r"FIRST-BOOT ADMIN PASSWORD:\s*(\S+)"
# the banner line exactly as operator_seed and prod_seed print it (pinned against their source below)
NEW_LINE = f"  FIRST-BOOT ADMIN PASSWORD: in {FILE} (mode 600), inside the registry's container"
SECRET = "Zq7-generated-first-boot-pw"   # a test value, not a real secret


def _host_work():
    spec = importlib.util.spec_from_file_location("_v0654_hostwork", SRC / "host_work.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_both_seeds_print_the_line_the_reader_expects():
    for f in ("operator_seed.py", "prod_seed.py"):
        text = (SRC / f).read_text()
        assert 'FIRST-BOOT ADMIN PASSWORD: in {password_file} (mode 600)' in text, f


def test_the_old_pattern_takes_the_word_in_for_the_password():
    """The control: what the three readers did on V0654's banner."""
    assert re.search(OLD, NEW_LINE).group(1) == "in"


def test_the_banner_names_the_file_or_the_printed_password_or_nothing():
    from agentvault_registry.core import first_boot
    assert first_boot.banner(f"boot\n{NEW_LINE}\n  Email: x\n") == ("file", FILE)
    assert first_boot.banner(f"boot\n  FIRST-BOOT ADMIN PASSWORD: {SECRET}\n") == ("printed", SECRET)
    assert first_boot.banner("boot\nno banner here\n") is None
    assert first_boot.banner("") is None


class _Exec:
    def __init__(self, logs, files):
        self._logs, self.files, self.calls = logs, dict(files), []

    def logs(self, tail=None):
        return self._logs.encode()

    def exec_run(self, argv):
        self.calls.append(list(argv))
        if argv[0] == "cat":
            return (0, self.files[argv[1]].encode()) if argv[1] in self.files else (1, b"cat: no such file")
        if argv[:2] == ["rm", "-f"]:
            self.files.pop(argv[2], None)
            return 0, b""
        return 1, b""


def test_the_sdk_reader_reads_the_file_then_removes_it():
    from agentvault_registry.core import first_boot
    c = _Exec(f"boot\n{NEW_LINE}\n", {FILE: SECRET + "\n"})
    pw, how = first_boot.from_sdk_container(c)
    assert pw == SECRET and "0600 file" in how and "removed" in how
    assert c.calls == [["cat", FILE], ["rm", "-f", FILE]] and FILE not in c.files
    assert SECRET not in how


def test_the_sdk_reader_says_why_when_the_file_cannot_be_read_and_takes_an_older_printed_password():
    from agentvault_registry.core import first_boot
    pw, how = first_boot.from_sdk_container(_Exec(f"{NEW_LINE}\n", {}))
    assert pw == "" and FILE in how
    c = _Exec(f"  FIRST-BOOT ADMIN PASSWORD: {SECRET}\n", {})
    pw, how = first_boot.from_sdk_container(c)
    assert pw == SECRET and "older" in how and c.calls == []
    assert first_boot.from_sdk_container(_Exec("nothing\n", {}))[0] == ""


def _fake_cli(logs, files, calls):
    def run(cmd, *a, **k):
        calls.append(list(cmd))
        if cmd[:2] == ["docker", "logs"]:
            return types.SimpleNamespace(stdout=logs, stderr="", returncode=0)
        if cmd[:2] == ["docker", "exec"] and cmd[3] == "cat":
            ok = cmd[4] in files
            return types.SimpleNamespace(stdout=files.get(cmd[4], ""), stderr="" if ok else "no such file",
                                         returncode=0 if ok else 1)
        if cmd[:2] == ["docker", "exec"] and cmd[3:5] == ["rm", "-f"]:
            files.pop(cmd[5], None)
            return types.SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"unexpected call {cmd}")
    return run


def test_host_work_reads_the_file_the_banner_names_then_removes_it(monkeypatch):
    mod = _host_work()
    files, calls, notes = {FILE: SECRET + "\n"}, [], []
    monkeypatch.setattr(mod, "subprocess", types.SimpleNamespace(run=_fake_cli(f"boot\n{NEW_LINE}\n", files, calls)))
    out = mod._first_boot_admin("cloud-op-x-registry", notes)
    assert out == {"admin_password": SECRET}
    assert ["docker", "exec", "cloud-op-x-registry", "cat", FILE] in calls
    assert ["docker", "exec", "cloud-op-x-registry", "rm", "-f", FILE] in calls and FILE not in files
    assert any("0600 file" in n and "removed" in n for n in notes) and not any(SECRET in n for n in notes)


def test_host_work_never_hands_back_the_word_in(monkeypatch):
    mod = _host_work()
    calls, notes = [], []
    monkeypatch.setattr(mod, "subprocess", types.SimpleNamespace(run=_fake_cli(f"{NEW_LINE}\n", {}, calls)))
    assert mod._first_boot_admin("cloud-op-x-registry", notes) == {"admin_password": ""}
    assert any(FILE in n for n in notes)


def test_host_work_still_reads_an_older_image_s_printed_password(monkeypatch):
    mod = _host_work()
    calls, notes = [], []
    monkeypatch.setattr(mod, "subprocess",
                        types.SimpleNamespace(run=_fake_cli(f"  FIRST-BOOT ADMIN PASSWORD: {SECRET}\n", {}, calls)))
    assert mod._first_boot_admin("cloud-op-x-registry", notes) == {"admin_password": SECRET}
    assert all(c[:2] == ["docker", "logs"] for c in calls)


@pytest.mark.parametrize("f", ["host_work.py", "services/cloud_provisioner.py", "services/frame_test_provisioner.py"])
def test_no_reader_keeps_the_old_pattern(f):
    text = (SRC / f).read_text()
    assert "FIRST-BOOT ADMIN PASSWORD:\\s*(\\S+)" not in text, f
    assert "first_boot" in text, f


def test_no_reader_of_the_banner_is_left_outside_first_boot():
    """session-lead (the sessions' room seq 1170): no reader of the banner may take the word after the colon as the
    password. The banner text appears only in the two seeds that print it and in core/first_boot, the one reader."""
    allowed = {"operator_seed.py", "prod_seed.py", "core/first_boot.py"}
    found = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                   if "FIRST-BOOT ADMIN PASSWORD" in p.read_text(errors="replace"))
    assert set(found) == allowed, found


def test_no_console_doc_sends_a_person_to_the_log_for_the_password():
    """The console's docs say to read the file the log names (docker exec, then delete it), never to grep the log for
    the password (the journal posts in views/BlogView.vue are dated history and stay as published)."""
    docs = SRC / "static" / "new_registry_frontend" / "src" / "assets" / "docs"
    left = sorted(str(p.relative_to(docs)) for p in docs.rglob("*.md") if "FIRST-BOOT ADMIN PASSWORD" in p.read_text())
    assert left == [], left
    for f in ("operator/00_quickstart.md", "operator/14_setup_manual.md", "oracle/17_operators.md"):
        assert f"docker exec my-registry-registry cat {FILE}" in (docs / f).read_text(), f
