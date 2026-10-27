"""§FRAMEPROV P0 (2026-09-13): a frame lifecycle script names its frame, and never a protected one.

The admin UI's Tear down posted no target, and teardown_hetzner_frame.sh / start_hetzner_frame.sh fell back to the
newest hetzner-frame-* dir: the RETIRED Hetzner stack. Both also fell back to the NAME hetzner-frame for a dir with no
run meta. frame_guard.sh is the one rule both scripts now ask first.

Pinned on fixture dirs and a fixture list under tmp_path, never on this host's live ones. The real scripts are
EXECUTED only in the two cases that cannot name any frame (no argument, a path that does not exist), only after the
structural check proves they ask the guard before anything else, and under stub docker/python3/nginx/systemctl/rm/
sed/curl that record any call: an old checkout of the teardown (which falls back to the Hetzner stack and calls its
venv python by absolute path) is never run by this file.
"""
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)
GUARD = os.path.join(DRIVER_DIR, "frame_guard.sh")
SCRIPTS = {
    "teardown": os.path.join(DRIVER_DIR, "teardown_hetzner_frame.sh"),
    "start": os.path.join(DRIVER_DIR, "start_hetzner_frame.sh"),
}


def _frame_dir(tmp_path, dirname, meta_name=None):
    d = tmp_path / dirname
    d.mkdir()
    if meta_name is not None:
        (d / "hetzner-demo-run.json").write_text(json.dumps({"name": meta_name, "ts": 1}))
    return str(d)


def _plist(tmp_path, *lines):
    p = tmp_path / "protected-frames.list"
    p.write_text("# fixture list\n\n" + "".join(f"{line}\n" for line in lines))
    return str(p)


def _guard(verb, arg, **env_extra):
    env = {"PATH": os.environ["PATH"], "ARG": arg, **env_extra}
    return subprocess.run(["bash", "-c", f'. "{GUARD}"; frame_guard {verb} "$ARG"'],
                          env=env, capture_output=True, text=True)


def test_no_argument_is_refused(tmp_path):
    r = _guard("teardown", "", FRAME_PROTECTED_LIST=_plist(tmp_path, "eu"))
    assert r.returncode == 2 and r.stdout == ""
    assert "REFUSED" in r.stderr and "no default frame" in r.stderr


def test_a_path_that_is_not_a_directory_is_refused(tmp_path):
    r = _guard("start", str(tmp_path / "juice-1"), FRAME_PROTECTED_LIST=_plist(tmp_path, "eu"))
    assert r.returncode == 2 and "not a directory" in r.stderr


def test_a_dir_without_a_run_meta_name_is_refused(tmp_path):
    d = _frame_dir(tmp_path, "juice-1")  # no meta: the scripts used to fall back to the NAME hetzner-frame
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=_plist(tmp_path, "eu"))
    assert r.returncode == 2 and "no run meta" in r.stderr


def test_a_protected_meta_name_is_refused(tmp_path):
    d = _frame_dir(tmp_path, "hetzner-frame-1785128860", "hetzner-frame")
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=_plist(tmp_path, "eu", "hetzner-frame"))
    assert r.returncode == 2 and "protected frame" in r.stderr and r.stdout == ""


def test_a_protected_dir_name_is_refused_even_when_the_meta_disagrees(tmp_path):
    d = _frame_dir(tmp_path, "eu-1788764190", "impostor")
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=_plist(tmp_path, "eu"))
    assert r.returncode == 2 and "eu is a protected frame" in r.stderr


def test_list_comments_and_whitespace_do_not_hide_a_name(tmp_path):
    d = _frame_dir(tmp_path, "sbx-alpha-1788462456", "sbx-alpha")
    r = _guard("start", d, FRAME_PROTECTED_LIST=_plist(tmp_path, "   sbx-alpha   # the tester's home"))
    assert r.returncode == 2 and "protected frame" in r.stderr


def test_an_unprotected_frame_passes_and_prints_its_name(tmp_path):
    d = _frame_dir(tmp_path, "juice-1788000000", "juice")
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=_plist(tmp_path, "eu", "asia", "hetzner-frame"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "juice" and "REFUSED" not in r.stderr


def test_a_missing_list_fails_closed_and_dev_null_declares_none(tmp_path):
    d = _frame_dir(tmp_path, "juice-1", "juice")
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=str(tmp_path / "no-such.list"))
    assert r.returncode == 2 and "missing or unreadable" in r.stderr
    r = _guard("teardown", d, FRAME_PROTECTED_LIST="/dev/null")
    assert r.returncode == 0 and r.stdout.strip() == "juice"


def test_the_override_must_name_the_protected_frame(tmp_path):
    d = _frame_dir(tmp_path, "hetzner-frame-1785128860", "hetzner-frame")
    lst = _plist(tmp_path, "eu", "hetzner-frame")
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=lst, FRAME_I_MEAN_IT="eu")
    assert r.returncode == 2 and "protected frame" in r.stderr
    r = _guard("teardown", d, FRAME_PROTECTED_LIST=lst, FRAME_I_MEAN_IT="hetzner-frame")
    assert r.returncode == 0 and "WARNING" in r.stderr and r.stdout.strip() == "hetzner-frame"


# structural: the scripts ask the guard before anything with a side effect

SIDE_EFFECT = re.compile(r'(^|[\s;&|(])(python3|"\$PY"|docker|rm|sed\s+-i|nginx|systemctl|curl|cd\s+"\$STACK_DIR")(\s|$)')
GUARD_CALL = re.compile(r'frame_guard\s+(teardown|start)\s+"\$\{1:-\}"')


def guard_problems(text):
    code = [(i, line) for i, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.strip().startswith("#")]
    problems = []
    if any("ls -dt /opt/theprotocol/stack/hetzner-frame-*" in line for _, line in code):
        problems.append("the no-argument fallback to the newest hetzner-frame-* dir is still there")
    if any(re.search(r'\|\|\s*echo\s+"?hetzner-frame"?\s*\)', line) for _, line in code):
        problems.append("the NAME fallback to hetzner-frame is still there")
    call = next((i for i, line in code if GUARD_CALL.search(line)), None)
    if call is None:
        problems.append("frame_guard is never called")
    else:
        first = next((i for i, line in code if SIDE_EFFECT.search(line)), None)
        if first is not None and first < call:
            problems.append(f"line {first} has a side effect before the guard (line {call})")
    return problems


OLD_TEARDOWN_HEAD = r'''#!/usr/bin/env bash
set -euo pipefail
STACK_DIR="${1:-$(ls -dt /opt/theprotocol/stack/hetzner-frame-* 2>/dev/null | head -1 || true)}"
[ -n "$STACK_DIR" ] && [ -d "$STACK_DIR" ] || { echo "no hetzner-frame stack dir found"; exit 1; }
META="$STACK_DIR/hetzner-demo-run.json"
NAME=$(python3 -c "import json;print(json.load(open('$META'))['name'])" 2>/dev/null || echo "hetzner-frame")
'''

LATE_GUARD = r'''#!/usr/bin/env bash
docker compose ps
FRAME_NAME="$(frame_guard teardown "${1:-}")" || exit 2
'''


def test_the_structural_check_can_fail():
    old = guard_problems(OLD_TEARDOWN_HEAD)
    assert len(old) == 3, old
    assert any("before the guard" in p for p in guard_problems(LATE_GUARD))


def test_both_scripts_ask_the_guard_before_anything_else():
    for verb, path in SCRIPTS.items():
        with open(path) as f:
            assert guard_problems(f.read()) == [], verb


# live: the real scripts, only where no frame can be named

STUBS = ("docker", "python3", "nginx", "systemctl", "rm", "sed", "curl")


def test_the_real_scripts_refuse_without_a_frame_and_call_nothing(tmp_path):
    for verb, path in SCRIPTS.items():  # never execute a script that does not ask the guard first
        with open(path) as f:
            assert guard_problems(f.read()) == [], verb
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "stub-calls.log"
    for name in STUBS:
        p = stubs / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\nexit 1\n')
        p.chmod(0o755)
    env = {"PATH": f"{stubs}:{os.environ['PATH']}", "FRAME_PROTECTED_LIST": _plist(tmp_path, "eu")}
    for verb, path in SCRIPTS.items():
        for args in ([], [str(tmp_path / "no-such-frame-1")]):
            r = subprocess.run(["bash", path, *args], env=env, capture_output=True, text=True, cwd=str(tmp_path))
            assert r.returncode in (2, 3), (verb, args, r.returncode, r.stderr)
            assert "REFUSED" in r.stderr, (verb, args, r.stderr)
    assert not calls.exists(), calls.read_text()
