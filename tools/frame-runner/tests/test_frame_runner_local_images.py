"""§HELLOFRAME lane 6, measured on the first stack-phase job from a frame-up frame: the frame's client sends no pull
token when the operator's images are the export's LOCAL tag namespace (`images_local: true`), and the runner's own spec
check refused the job for the key it must not carry. The check honours the flag exactly as the one-shot does."""
import pytest

from test_frame_runner_caddy import _runner, fr  # noqa: E402  (the helper's module object: a second import would carry a second Refused)


def _spec(phase, **over):
    s = {"frame": "harbor", "operator_name": "Riga", "safe_name": "riga", "operator_did": "spiffe://harbor.example.org/service/op-riga",
         "phase": phase}
    if phase == "stack":
        s.update({"bundle_filename": "Riga.tar.gz", "compose": "services: {}",
                  "operator_secrets": {k: "x" * 32 for k in fr.Runner.OPERATOR_SECRET_KEYS}})
    s.update(over)
    return s


def test_a_local_images_stack_spec_needs_no_pull_token(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch)
    spec = _spec("stack", images_local=True)
    assert "docker_pull_token" not in spec
    out = runner._operator_spec({"spec": spec})
    assert out["safe_name"] == "riga"


def test_a_pulled_images_stack_spec_still_needs_its_pull_token(tmp_path, monkeypatch):
    runner, _ = _runner(tmp_path, monkeypatch)
    with pytest.raises(fr.Refused, match="docker_pull_token"):
        runner._operator_spec({"spec": _spec("stack")})
    with pytest.raises(fr.Refused, match="docker_pull_token"):
        runner._operator_spec({"spec": _spec("stack", images_local="yes")})   # only the boolean true lifts it
