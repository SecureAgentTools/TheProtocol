"""`tp update` exists (CB-342).

A registry's release page and its rollout reminder tell an operator to run `tp update --apply --to-version <v>`; the
umbrella had only `tp operator update`, so the printed command answered "No such command". `tp update` is now the
operator app's update with the same arguments. The channel is patched out.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.commands import update  # noqa: E402
from tp_operator.umbrella import umbrella  # noqa: E402


def test_tp_update_is_the_operator_update(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON", "TP_OPERATOR_REMOTE_AUDIT"):
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / ".env.operator").write_text("REGISTRY_NAME=cloud-op-x\nVERSION=1.0.0-beta.19\n")
    monkeypatch.setenv("TP_OPERATOR_HOME", str(d))
    monkeypatch.setattr(update, "_fetch_channel", lambda: (None, "test: no channel"))
    r = CliRunner().invoke(umbrella, ["update", "--check-only"])
    assert r.exit_code == 0, r.output
    assert "1.0.0-beta.19" in r.output and "test: no channel" in r.output
    h = CliRunner().invoke(umbrella, ["update", "--help"])
    assert h.exit_code == 0 and "--to-version" in h.output and "--apply" in h.output
