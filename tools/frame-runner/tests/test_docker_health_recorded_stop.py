"""The host health collector's recorded-stop convention, proven both ways (V0660 (j)).

monitoring/scripts/docker-health-textfile.sh is what turns docker's health into
`docker_container_health`, and ContainerUnhealthy fires on a 0. It skips a container that is not running ONLY when
its restart policy is "no" — §LEGACYSTOP's recorded stop. V0657 (f) stopped a revoked operator's agent and left the
policy alone, so the revoke's own deliberate stop alerted every night; V0660 (j) records it.

This is the control for that change, and the second case is the one that matters: a stop that nobody recorded must
STILL be reported (§CANARYFIX — ten canary workloads once sat dead for 44 hours behind a stop nobody had written
down). A convention that hid every stop would hide a real one.
"""
import os
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "monitoring" / "scripts" / "docker-health-textfile.sh"


def run_collector(tmp_path, containers):
    """Run the real script with a fake `docker` first on PATH.

    `containers` is name -> (health, restarts, state, policy). The rows go in a FILE the shim reads line by line:
    my first shim piped them with `printf %s`, whose last line has no newline, so `read` dropped it and the
    collector saw an empty fleet — and the absence assertion in the first test would have passed on that empty
    output. An absence check alone cannot fail; the presence checks beside it are what caught my own instrument.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rows = bin_dir / "rows.txt"
    rows.write_text("".join(
        f"{name}|{health}|{restarts}|{state}|{policy}\n"
        for name, (health, restarts, state, policy) in containers.items()))
    (bin_dir / "docker").write_text(
        "#!/bin/sh\n"
        f'ROWS="{rows}"\n'
        'if [ "$1" = "ps" ]; then\n'
        '  while IFS="|" read -r n h r s p; do [ -n "$n" ] && echo "$n"; done < "$ROWS"\n'
        '  exit 0\n'
        'fi\n'
        'if [ "$1" = "inspect" ]; then\n'
        '  while IFS="|" read -r n h r s p; do\n'
        '    if [ "$n" = "$2" ]; then printf "%s|%s|%s|%s\\n" "$h" "$r" "$s" "$p"; fi\n'
        '  done < "$ROWS"\n'
        '  exit 0\n'
        'fi\n'
        'exit 1\n')
    (bin_dir / "docker").chmod(0o755)
    out_dir = tmp_path / "textfile"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", OUTDIR=str(out_dir))
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    text = (out_dir / "docker_health.prom").read_text()
    # the fleet must not be empty: otherwise every "is not reported" assertion below passes for the wrong reason.
    # It is deliberately NOT a count of what SHOULD appear -- that would re-implement the very rule under test here
    # and measure itself; each test names the rows it expects instead.
    assert "docker_container_health{" in text, f"the collector reported nothing at all: {text!r}"
    return text


@pytest.mark.skipif(not SCRIPT.exists(), reason=f"the collector is not beside this checkout ({SCRIPT}) — NOT MEASURED")
def test_a_recorded_stop_is_not_reported_and_a_bare_stop_still_is(tmp_path):
    text = run_collector(tmp_path, {
        # what a revoke leaves behind since V0660 (j): stopped, and the stop written down
        "cloud-op-ntop-spire-agent": ("none", 0, "exited", "no"),
        # a stop nobody recorded: still visible, deliberately (§CANARYFIX)
        "cloud-op-ntop-teg": ("none", 0, "exited", "unless-stopped"),
        "cloud-op-ntop-registry": ("healthy", 0, "running", "unless-stopped"),
        "cloud-op-ntop-db": ("unhealthy", 3, "running", "unless-stopped"),
    })
    assert "cloud-op-ntop-spire-agent" not in text, "the recorded stop is skipped"
    assert 'docker_container_health{name="cloud-op-ntop-teg",state="exited"} -2' in text, "a bare stop stays visible"
    assert 'docker_container_health{name="cloud-op-ntop-registry",state="running"} 1' in text
    assert 'docker_container_health{name="cloud-op-ntop-db",state="running"} 0' in text


@pytest.mark.skipif(not SCRIPT.exists(), reason=f"the collector is not beside this checkout ({SCRIPT}) — NOT MEASURED")
def test_a_container_on_policy_no_that_is_still_running_is_reported(tmp_path):
    # the convention is about a STOP, not about the policy on its own: an agent left running on "no" is a thing
    # somebody should see, not something the convention hides.
    text = run_collector(tmp_path, {"cloud-op-ntop-spire-agent": ("unhealthy", 0, "running", "no")})
    assert 'docker_container_health{name="cloud-op-ntop-spire-agent",state="running"} 0' in text
