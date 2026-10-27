"""§OPDIST (2026-09-16, his answer "Both links first"): AGORA venues get the carrier and the reload FRAMES got at §FRAMEKIT P3.1.

Measured the day this was written: the fleet auditor's VENUE_REG_DSNS_JSON held 13 venues, every one an operator stopped
weeks earlier, 0 reachable, and none of the 6 operators that actually run. Only two files mention the key and nothing
writes it, because VENUES was built at IMPORT from env: changing it cost the recreate that re-audits every tier (load 120),
the exact cost FRAMES shed when it gained a file and POST /api/auditor/admin/reload-frames. So nobody changed it.

The carrier is `venues.json` BESIDE the extra-frames file: that file already lives in a DIRECTORY mount (so a replaced
inode is seen), which means a frame's kit auditor gains the carrier with no compose change and no new mount.

RED on the base (none of these exist or behave so there):
  1. venues.json beside the frames file is read, and wins over the env (one carrier, the frames precedence);
  2. POST reload-venues re-applies it IN PLACE (main holds VENUES by name), answers added/removed/replaced, and terminates
     the registry pools of removed and changed venues only;
  3. an UNPARSABLE file on reload changes nothing and says so. This deliberately differs from reload-frames, which applies
     an empty list: a venue that silently vanishes from an audit is the blindspot the venue block exists to close;
  4. an entry with no dsn is skipped AND named.
CONTROL that passes on the base: the env carrier alone still works. The admin-token refusal is NEW (the endpoint is
absent on the base), and it keeps the reload behind the same gate as reload-frames.
"""
import asyncio
import importlib
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE
TOKEN = "admin-token-for-venue-tests"


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


def _venue(dsn, **kw):
    return {"dsn": dsn, "currency": kw.get("currency", "LNT"), "frame": kw.get("frame", "lantern")}


class FakePool:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


@pytest.fixture()
def boot(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (frames_dir / "frames.json").write_text("[]")

    def _boot(venues_file=None, env_venues=None):
        _purge()
        for k in list(os.environ):
            if (k.endswith("_EVENT_STORE_URL") or k.endswith("_ES_DSN") or k.endswith("_REG_DSN")
                    or k == "VENUE_REG_DSNS_JSON" or (k.startswith("AUDITOR_") and k != "AUDITOR_TREE")):
                monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("FRONTEND_DIR", os.path.join(TREE, "frontend"))
        monkeypatch.setenv("AUDITOR_SOLO", "true")
        monkeypatch.setenv("AUDITOR_ADMIN_TOKEN", TOKEN)
        monkeypatch.setenv("AUDITOR_EXTRA_FRAMES_FILE", str(frames_dir / "frames.json"))
        if env_venues is not None:
            monkeypatch.setenv("VENUE_REG_DSNS_JSON", json.dumps(env_venues))
        vf = frames_dir / "venues.json"
        if venues_file is None:
            if vf.exists():
                vf.unlink()
        else:
            vf.write_text(venues_file if isinstance(venues_file, str) else json.dumps(venues_file))
        monkeypatch.syspath_prepend(TREE)
        return importlib.import_module("src.auditor.main"), vf

    return _boot


def names(main):
    return [v["name"] for v in main.VENUES]


def test_control_the_env_carrier_alone_still_works(boot):
    main, _ = boot(env_venues={"op-berlin": _venue("postgresql://registry:x@cloud-op-op-berlin-db:5432/agentvault_registry")})
    assert names(main) == ["op-berlin"]
    assert main.VENUES[0]["id"] == "venue:op-berlin"


def test_red_venues_json_beside_the_frames_file_is_the_carrier_and_wins_over_the_env(boot):
    main, vf = boot(venues_file={"tartu": _venue("postgresql://auditor_ro:x@cloud-op-tartu-db:5432/agentvault_registry")},
                    env_venues={"op-berlin": _venue("postgresql://registry:x@cloud-op-op-berlin-db:5432/agentvault_registry")})
    assert names(main) == ["tartu"], "the file beside frames.json must be the one carrier when it exists"
    from src.auditor import config
    assert config.VENUES_SOURCE == str(vf)


def test_red_reload_venues_applies_in_place_and_terminates_only_the_changed_pools(boot):
    main, vf = boot(venues_file={"a": _venue("postgresql://ro:x@a-db:5432/r"), "b": _venue("postgresql://ro:x@b-db:5432/r"),
                                 "keep": _venue("postgresql://ro:x@keep-db:5432/r")})
    held = main.VENUES
    pools = {vid: FakePool() for vid in ("venue:a", "venue:b", "venue:keep")}
    main._reg_pools.update(pools)
    main._venue_shares_cache.update({"a": {"reachable": True}, "keep": {"reachable": True}})
    vf.write_text(json.dumps({"b": _venue("postgresql://ro:x@b-db-moved:5432/r"),
                              "keep": _venue("postgresql://ro:x@keep-db:5432/r"),
                              "c": _venue("postgresql://ro:x@c-db:5432/r")}))
    out = asyncio.run(main.api_reload_venues(x_auditor_admin=TOKEN))
    assert out["added"] == ["venue:c"] and out["removed"] == ["venue:a"] and out["replaced"] == ["venue:b"], out
    assert main.VENUES is held, "main holds VENUES by name, so a reload must mutate the list, never rebind it"
    assert sorted(names(main)) == ["b", "c", "keep"]
    assert pools["venue:a"].terminated and pools["venue:b"].terminated and not pools["venue:keep"].terminated
    assert "venue:a" not in main._reg_pools and "venue:keep" in main._reg_pools
    assert "a" not in main._venue_shares_cache and "keep" in main._venue_shares_cache


def test_red_an_unparsable_file_on_reload_changes_nothing_and_says_so(boot):
    main, vf = boot(venues_file={"a": _venue("postgresql://ro:x@a-db:5432/r")})
    vf.write_text("{ this is not json")
    out = asyncio.run(main.api_reload_venues(x_auditor_admin=TOKEN))
    assert getattr(out, "status_code", None) == 422, out
    body = json.loads(out.body)
    assert "nothing applied" in body["error"], body
    assert names(main) == ["a"], "a bad write must not make every venue vanish from the audit"


def test_red_an_entry_with_no_dsn_is_skipped_and_named(boot, capsys):
    main, _ = boot(venues_file={"empty": {"dsn": ""}, "good": _venue("postgresql://ro:x@g-db:5432/r")})
    assert names(main) == ["good"]
    assert "empty" in capsys.readouterr().out, "a skipped venue must be named, not silently dropped"


def test_control_reload_venues_refuses_without_the_admin_token(boot):
    main, _ = boot(venues_file={"a": _venue("postgresql://ro:x@a-db:5432/r")})
    fn = getattr(main, "api_reload_venues", None)
    if fn is None:
        pytest.fail("api_reload_venues does not exist (RED on the base, as expected)")
    out = asyncio.run(fn(x_auditor_admin="wrong"))
    assert getattr(out, "status_code", None) == 401
