"""§MCPTEST30 (V0553): an answer the docker exec stream dropped is read back from the container, never asked for again.

Rounds 15-18 measured it: a docker exec now and then returns rc 0 with its output cut, so curl's status marker (which curl
prints even when a transfer fails) is missing although curl ran. A read was asked once more; a WRITE could not be, and its
row read NOT MEASURED. exec_in_container now runs every curl that reports its status with the whole answer kept in a
short-lived file in the container, and reads that file back when the stream comes back without the marker. Anything else
it runs is untouched. The wrapper is run here with a real shell: an `exit` in the script, a `#` comment on its last line
and its exit code must all survive it.
"""
from __future__ import annotations

import subprocess

import pytest

from agentvault_registry.api_tests import multiframe_helpers as H

CURL = ("echo 'e30=' | base64 -d | curl -sS -X POST -H 'Content-Type: application/json' --data-binary @- "
        f"-w '\\n{H._HTTP_MARKER}%{{http_code}}--' http://localhost:8000/mcp/rpc")
PSQL = "echo 'U0VMRUNUIDE=' | base64 -d | PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER -At"


def test_only_a_curl_that_reports_its_status_is_kept():
    assert H._kept_token(["sh", "-c", CURL])
    assert H._kept_token(["sh", "-c", PSQL]) is None
    assert H._kept_token(["python", "-c", CURL]) is None, "only sh -c scripts are rewritten"
    assert H._kept_token(["sh", "-c", CURL, "extra"]) is None
    a, b = H._kept_token(["sh", "-c", CURL]), H._kept_token(["sh", "-c", CURL])
    assert a != b, "each call keeps its own file"


def _sh(script: str, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=20)


@pytest.fixture()
def kept_dir(tmp_path, monkeypatch):
    d = tmp_path / "answers"
    monkeypatch.setattr(H, "_KEPT_DIR", str(d))
    return d


def test_the_wrapper_keeps_the_answer_prints_it_and_passes_the_exit_code_on(kept_dir, tmp_path):
    inner = f"echo body; printf '\\n{H._HTTP_MARKER}200--'"
    r = _sh(H.kept_answer_script(inner, "t1"), tmp_path)
    assert r.returncode == 0 and r.stdout.endswith(f"{H._HTTP_MARKER}200--")
    assert (kept_dir / "t1").read_text() == r.stdout, "the file holds exactly what the call printed"
    # an exit inside the script ends its subshell only: the answer is still printed and kept, the code passed on
    r = _sh(H.kept_answer_script("echo partial; exit 3", "t2"), tmp_path)
    assert r.returncode == 3 and r.stdout.strip() == "partial" and (kept_dir / "t2").read_text().strip() == "partial"
    # a comment on the script's last line cannot swallow the subshell's closing parenthesis
    r = _sh(H.kept_answer_script(f"printf 'ok\\n{H._HTTP_MARKER}201--' # the status", "t3"), tmp_path)
    assert r.returncode == 0 and r.stdout.endswith(f"{H._HTTP_MARKER}201--")
    # stderr is kept with stdout, as the exec captures both
    r = _sh(H.kept_answer_script("echo oops >&2; echo fine", "t4"), tmp_path)
    assert "oops" in r.stdout and "fine" in r.stdout


def test_old_answers_are_removed_by_the_next_call(kept_dir, tmp_path):
    kept_dir.mkdir(parents=True)
    old, young = kept_dir / "old", kept_dir / "young"
    old.write_text("x")
    young.write_text("y")
    subprocess.run(["touch", "-d", "10 minutes ago", str(old)], check=True)
    _sh(H.kept_answer_script("echo hi", "t5"), tmp_path)
    assert not old.exists() and young.exists() and (kept_dir / "t5").exists()


class _Fake:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, name, args):
        self.calls.append(args)
        return self.answers.pop(0)


@pytest.fixture()
def fake_exec(monkeypatch):
    def install(*answers):
        f = _Fake(answers)
        monkeypatch.setattr(H, "_exec_once", f)
        monkeypatch.setattr(H, "record_probe", lambda: None)
        H.KEPT_RECOVERIES.update(recovered=0, still_lost=0)
        return f
    return install


ANSWER = f'{{"jsonrpc": "2.0", "result": {{}}}}\n{H._HTTP_MARKER}200--'


def test_a_dropped_answer_is_read_back_from_the_container_not_asked_again(fake_exec):
    f = fake_exec((0, ""), (0, ANSWER))
    rc, out = H.exec_in_container("sbx-alpha-registry", ["sh", "-c", CURL])
    assert (rc, out) == (0, ANSWER) and H.KEPT_RECOVERIES["recovered"] == 1
    first, second = f.calls
    assert first[:2] == ["sh", "-c"] and "(\n" + CURL + "\n)" in first[2], "the call ran inside the keeping wrapper"
    assert second[0:2] == ["sh", "-c"] and second[2].startswith(f"cat {H._KEPT_DIR}/"), "the second exec only reads"
    assert CURL not in second[2], "the route is never asked twice"
    assert H._split_http_body_code(out)[1] == "200"


def test_an_answer_with_its_marker_is_taken_as_it_came(fake_exec):
    f = fake_exec((0, ANSWER))
    assert H.exec_in_container("c", ["sh", "-c", CURL]) == (0, ANSWER) and len(f.calls) == 1


def test_a_failed_curl_is_not_read_back(fake_exec):
    failed = (7, f"curl: (7) Failed to connect\n{H._HTTP_MARKER}000--")
    f = fake_exec(failed)
    assert H.exec_in_container("c", ["sh", "-c", CURL]) == failed and len(f.calls) == 1


def test_an_answer_lost_twice_stays_lost(fake_exec):
    f = fake_exec((0, ""), (0, ""))
    assert H.exec_in_container("c", ["sh", "-c", CURL]) == (0, "") and len(f.calls) == 2
    assert H.KEPT_RECOVERIES == {"recovered": 0, "still_lost": 1}


def test_anything_else_runs_exactly_as_asked(fake_exec):
    f = fake_exec((0, "1\n"))
    args = ["sh", "-c", PSQL]
    assert H.exec_in_container("db", args) == (0, "1\n") and f.calls == [args]
