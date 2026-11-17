"""V0667 (order gwo_4d55fcc1535962f55866740c, session-volume): the driver scratchpad/deps/logkeep_v0667.py (check, apply, verify, rollback) that writes 5 x 50 MB of logs into the LIVE composes of the
frames and the operators, as a step of V0667's chain (the recreate then makes it live). Tests first, on temporary stacks:

  the edit     a frame's registry and TEG move to the explicit 50m x 5 anchor and nothing else changes byte for byte; an operator's registry and teg-layer get the written block; both are
               idempotent, and an existing smaller block is replaced, never doubled
  apply        each file is backed up first, written with its own mode, validated by `docker compose config` (a file that does not validate is put back and the run stops), and recorded in a state file
  verify       reads the compose the way compose will: the two services say 50m x 5; with --live the running containers too
  rollback     puts every recorded file back from its backup, byte for byte
  check        read-only: says per service what the file says and what the container runs now, and what apply would change; it writes nothing
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import stat

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("logkeep_v0667", ROOT / "scratchpad" / "deps" / "logkeep_v0667.py")
lk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lk)
_cspec = importlib.util.spec_from_file_location("frame_template_contract_lk", ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(contract)

FRAME = """# a rendered frame compose
x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  eu-db:
    image: postgres:18
    container_name: eu-db
    restart: unless-stopped
    logging: *default-logging

  eu-teg:
    image: teg
    container_name: eu-teg
    restart: unless-stopped
    logging: *default-logging

  eu-registry:
    image: registry
    container_name: eu-registry
    restart: unless-stopped
    logging: *default-logging

  eu-nginx-teg:
    image: nginx
    container_name: eu-nginx-teg
    restart: unless-stopped
    logging: *default-logging

networks:
  default: {}
"""

OPERATOR = """services:
  registry:
    image: registry
    container_name: ${REGISTRY_NAME:-operator}-registry
    restart: unless-stopped
    ports:
      - "12000:8000"

  teg-layer:
    image: teg-layer
    container_name: ${REGISTRY_NAME:-operator}-teg
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    ports:
      - "12080:8080"

  db:
    image: postgres:18
    restart: unless-stopped
"""


def test_a_frames_registry_and_teg_move_to_the_keep_anchor_and_nothing_else_changes():
    new, changes = lk.keep_frame_compose(FRAME, "eu")
    assert changes == ["x-logging-keep anchor added", "eu-registry: logging -> *keep-logging", "eu-teg: logging -> *keep-logging"]
    assert contract.log_keep_contract(new, ("eu-registry", "eu-teg")) == []
    # every other line is as it was, in order: the diff is the anchor and two alias lines
    old_lines, new_lines = FRAME.split("\n"), new.split("\n")
    removed = [l for l in old_lines if l not in new_lines]
    assert removed == []                                   # the alias line text still stands for the services that keep it
    assert new.count("logging: *default-logging") == 2 and new.count("logging: *keep-logging") == 2     # eu-db and eu-nginx-teg keep the small anchor
    for name in ("eu-db", "eu-nginx-teg"):
        blk = dict(contract._compose_blocks(new))[name]
        assert "*default-logging" in blk and "*keep-logging" not in blk, name


def test_the_frame_edit_is_idempotent_and_a_second_run_changes_nothing():
    once, _ = lk.keep_frame_compose(FRAME, "eu")
    twice, changes = lk.keep_frame_compose(once, "eu")
    assert twice == once and changes == []


def test_a_frame_service_with_no_logging_gets_the_alias_and_one_with_another_alias_is_moved():
    bare = FRAME.replace("  eu-registry:\n    image: registry\n    container_name: eu-registry\n    restart: unless-stopped\n    logging: *default-logging\n",
                         "  eu-registry:\n    image: registry\n    container_name: eu-registry\n    restart: unless-stopped\n")
    new, changes = lk.keep_frame_compose(bare, "eu")
    assert "eu-registry: logging -> *keep-logging" in changes and contract.log_keep_contract(new, ("eu-registry", "eu-teg")) == []
    assert new.count("logging: *keep-logging") == 2


def test_a_frame_compose_that_lacks_the_service_is_refused_not_silently_passed():
    with pytest.raises(lk.Refused) as e:
        lk.keep_frame_compose(FRAME.replace("eu-teg", "eu-gone"), "eu")
    assert "eu-teg" in str(e.value)


def test_an_operators_registry_and_teg_layer_get_the_written_block_and_a_small_one_is_replaced():
    new, changes = lk.keep_operator_compose(OPERATOR)
    assert changes == ["registry: logging written (50m x 5)", "teg-layer: logging 10m x 3 -> 50m x 5"]
    assert contract.log_keep_contract(new, ("registry", "teg-layer")) == []
    assert new.count("max-size") == 2 and '"10m"' not in new, "the small block was replaced, not doubled"
    db = dict(contract._compose_blocks(new))["db"]
    assert "logging" not in db, "the operator's database keeps the daemon default"
    again, changes2 = lk.keep_operator_compose(new)
    assert again == new and changes2 == []


def _stack(tmp_path, kind="frame"):
    d = tmp_path / ("eu-1788764190" if kind == "frame" else "cloud-op-amsterdam")
    d.mkdir()
    f = d / ("docker-compose.frame-test.yml" if kind == "frame" else "docker-compose.operator.yml")
    f.write_text(FRAME if kind == "frame" else OPERATOR)
    f.chmod(0o640)
    (d / (".env.frame-test" if kind == "frame" else ".env.operator")).write_text("X=1\n")
    return d, f


def _driver(tmp_path, monkeypatch, config_ok=True, live=None):
    stacks = [{"dir": str(tmp_path / "eu-1788764190"), "kind": "frame", "name": "eu", "file": "docker-compose.frame-test.yml", "env": ".env.frame-test"},
              {"dir": str(tmp_path / "cloud-op-amsterdam"), "kind": "operator", "name": "amsterdam", "file": "docker-compose.operator.yml", "env": ".env.operator"}]
    calls = []

    def config(path, env):
        calls.append(path)
        return (config_ok, "rendered" if config_ok else "service x: boom")
    d = lk.Driver(stacks=stacks, state_path=str(tmp_path / "state.json"), docker_config=config, inspect_logconfig=(lambda c: live.get(c) if live is not None else None),
                  now=lambda: "20261116T200000Z")
    return d, calls


def test_apply_backs_up_first_keeps_the_mode_validates_and_records(tmp_path, monkeypatch):
    _, ffile = _stack(tmp_path)
    _, ofile = _stack(tmp_path, "operator")
    before = {p: p.read_bytes() for p in (ffile, ofile)}
    d, calls = _driver(tmp_path, monkeypatch)
    assert d.apply() == 0
    for p in (ffile, ofile):
        bak = pathlib.Path(str(p) + ".bak-pre-logkeep-v0667-20261116T200000Z")
        assert bak.read_bytes() == before[p], "the backup is the file as it was"
        assert stat.S_IMODE(p.stat().st_mode) == 0o640 and stat.S_IMODE(bak.stat().st_mode) == 0o640
        assert p.read_bytes() != before[p]
    assert calls == [str(ffile), str(ofile)], "docker compose config ran per stack"
    state = json.loads(pathlib.Path(tmp_path / "state.json").read_text())
    assert sorted(state["files"]) == sorted([str(ffile), str(ofile)]) and state["files"][str(ffile)].endswith(".bak-pre-logkeep-v0667-20261116T200000Z")


def test_a_file_that_does_not_validate_is_put_back_and_the_run_stops(tmp_path, monkeypatch, capsys):
    _, ffile = _stack(tmp_path)
    _, ofile = _stack(tmp_path, "operator")
    before = ffile.read_bytes()
    d, _ = _driver(tmp_path, monkeypatch, config_ok=False)
    assert d.apply() == 1
    assert ffile.read_bytes() == before and "boom" in capsys.readouterr().out
    assert ofile.read_text() == OPERATOR, "the run stopped at the first refusal: the next file was never touched"


def test_apply_twice_is_a_second_run_that_changes_and_backs_up_nothing(tmp_path, monkeypatch):
    _, ffile = _stack(tmp_path)
    _stack(tmp_path, "operator")
    d, _ = _driver(tmp_path, monkeypatch)
    d.apply()
    once = ffile.read_bytes()
    d2, calls2 = _driver(tmp_path, monkeypatch)
    assert d2.apply() == 0 and ffile.read_bytes() == once
    assert len(list(tmp_path.rglob("*.bak-pre-logkeep-v0667-*"))) == 2, "no second backup: nothing changed"


def test_rollback_puts_every_recorded_file_back_byte_for_byte(tmp_path, monkeypatch):
    _, ffile = _stack(tmp_path)
    _, ofile = _stack(tmp_path, "operator")
    d, _ = _driver(tmp_path, monkeypatch)
    d.apply()
    assert ffile.read_text() != FRAME
    assert d.rollback() == 0
    assert ffile.read_text() == FRAME and ofile.read_text() == OPERATOR
    assert stat.S_IMODE(ffile.stat().st_mode) == 0o640
    assert d.rollback() == 1, "nothing recorded to roll back is said, not done quietly"


def test_check_is_read_only_and_says_what_each_service_runs_and_what_apply_would_do(tmp_path, monkeypatch, capsys):
    _, ffile = _stack(tmp_path)
    _, ofile = _stack(tmp_path, "operator")
    snapshot = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (ffile, ofile)}
    live = {"eu-registry": {"max-size": "10m", "max-file": "3"}, "eu-teg": {"max-size": "10m", "max-file": "3"},
            "cloud-op-amsterdam-registry": {"max-size": "50m", "max-file": "5"}}
    d, calls = _driver(tmp_path, monkeypatch, live=live)
    assert d.check() == 1, "something would change: the exit says so"
    out = capsys.readouterr().out
    assert "eu-registry" in out and "runs 10m x 3" in out and "file: 10m x 3 (anchor default-logging)" in out and "apply WOULD change" in out
    assert "cloud-op-amsterdam-registry" in out and "runs 50m x 5" in out and "file: not written" in out
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (ffile, ofile)} == snapshot and not (tmp_path / "state.json").exists() and calls == []


def test_check_exits_clean_when_everything_is_already_kept(tmp_path, monkeypatch, capsys):
    _stack(tmp_path)
    _stack(tmp_path, "operator")
    d, _ = _driver(tmp_path, monkeypatch)
    d.apply()
    capsys.readouterr()
    assert d.check() == 0 and "apply would change nothing" in capsys.readouterr().out


def test_verify_reads_the_compose_and_with_live_the_running_containers(tmp_path, monkeypatch, capsys):
    _stack(tmp_path)
    _stack(tmp_path, "operator")
    d, _ = _driver(tmp_path, monkeypatch)
    assert d.verify() == 1, "before apply the files do not keep: verify says so"
    d.apply()
    assert d.verify() == 0
    live_small = {"eu-registry": {"max-size": "10m", "max-file": "3"}, "eu-teg": {"max-size": "50m", "max-file": "5"}}
    d2, _ = _driver(tmp_path, monkeypatch, live=live_small)
    capsys.readouterr()
    assert d2.verify(live=True) == 1 and "eu-registry" in capsys.readouterr().out, "a container not yet recreated runs the old size"
    all_live = {"eu-registry": {"max-size": "50m", "max-file": "5"}, "eu-teg": {"max-size": "50m", "max-file": "5"},
                "cloud-op-amsterdam-registry": {"max-size": "50m", "max-file": "5"}, "cloud-op-amsterdam-teg": {"max-size": "50m", "max-file": "5"}}
    d3, _ = _driver(tmp_path, monkeypatch, live=all_live)
    assert d3.verify(live=True) == 0


def test_the_default_stacks_are_the_four_frames_and_the_six_operators_and_name_their_files():
    names = [s["dir"].rsplit("/", 1)[-1] for s in lk.STACKS]
    assert names == ["eu-1788764190", "asia-1788764426", "sbx-alpha-1788462456", "sbx-beta-1788464843", "cloud-op-amsterdam", "cloud-op-lisbon", "cloud-op-shenzhen", "cloud-op-hochiminh",
                     "cloud-op-sbxalphaop", "cloud-op-sbxbetaop"]
    assert {s["kind"] for s in lk.STACKS} == {"frame", "operator"} and [s["name"] for s in lk.STACKS if s["kind"] == "frame"] == ["eu", "asia", "sbx-alpha", "sbx-beta"]
