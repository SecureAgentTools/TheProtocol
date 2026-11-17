"""V0666 (order gwo_f8c2c213092640ead451a723, session-tester; found by session-volume, room seq 4959): the whole-suite
database helper, and the gate that no `*_TEST_DB` variable goes unknown to it.

Eight real-Postgres test files skip on every ordinary run (their `*_TEST_DB` variable unset), so a whole-suite line
counted them as skipped and two of them (orgs v2) failed for a long time before anyone ran them. The helper
(scripts/test_databases.py) starts ONE throwaway Postgres 18.6 (production's), makes a database for every variable, per
shard (the tests DROP SCHEMA public: shards sharing a database would wipe each other), and writes one env file per shard
(mode 600, the password in no output). The gate below fails when a test file reads a `*_TEST_DB` variable the helper
does not know, so a new one cannot hide the same way. Red before: the helper does not exist.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import stat
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
HELPER = HERE.parent / "scripts" / "test_databases.py"


def load():
    spec = importlib.util.spec_from_file_location("test_databases", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeDocker:
    """Records every docker call and answers success; `ready_after` makes pg_isready fail that many times first."""

    def __init__(self, ready_after=0):
        self.calls, self._notready = [], ready_after

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if "pg_isready" in args and self._notready:
            self._notready -= 1
            return subprocess.CompletedProcess(args, 2, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")


# --- the gate ---------------------------------------------------------------------------------------------------------

def test_every_database_name_starts_with_test_the_guard_some_tests_apply_before_they_wipe_a_schema():
    """test_code_changes_bootstrap_hold_pg_v0666 refuses a database whose name does not start with test_ (it drops its public schema); the helper
    named them code_changes_s0, so the whole-suite run ERRORED twice on the cut (session-code's find, room seq 5122)."""
    h = load()
    for v in h.KNOWN:
        for i in range(6):
            assert h.database_name(v, i).startswith("test_"), (v, i, h.database_name(v, i))


def test_every_test_db_variable_a_test_reads_is_known_to_the_helper():
    h = load()
    found = h.scan(HERE)
    unknown = h.unknown_variables(found)
    assert not unknown, ("a test reads a *_TEST_DB variable the whole-suite helper does not know: "
                         + "; ".join(f"{v} (in {', '.join(sorted(found[v])[:2])})" for v in unknown)
                         + ". Add it to KNOWN in scripts/test_databases.py, so a whole-suite run creates its database and counts it")


def test_the_scan_sees_the_population_it_is_about(tmp_path):
    h = load()
    found = h.scan(HERE)
    assert {"MEMBERSHIP_TEST_DB", "ORGS_TEST_DB", "ORGS_TEST_PEER_DB", "CODE_DISTRIBUTIONS_TEST_DB"} <= set(found), sorted(found)
    assert len(found) >= 8
    # a control: a variable the helper does not know is named
    new = "BRAND_NEW_" + "TEST_DB"                  # built here so THIS file never names an unknown variable to the gate above
    (tmp_path / "test_x.py").write_text(f'import os\nX = os.environ.get("{new}")\nY = os.environ.get("MEMBERSHIP_TEST_DB")\n')
    found2 = h.scan(tmp_path)
    assert h.unknown_variables(found2) == [new]
    assert set(found2) == {new, "MEMBERSHIP_TEST_DB"}


def test_the_helper_already_knows_the_variables_of_the_unmerged_branches():
    h = load()
    for v in ("FLARE_WEAR_TEST_DB", "CODE_CHANGES_TEST_DB", "FIRMS_TEST_DB", "ANCHOR_TEST_DB", "DISPUTES_TEST_DB", "OWNER_READS_TEST_DB"):
        assert v in h.KNOWN, v


# --- the names and the env ----------------------------------------------------------------------------------------------

def test_every_variable_gets_its_own_database_in_every_set_and_no_two_sets_share_one():
    h = load()
    names = {(v, i): h.database_name(v, i) for v in h.KNOWN for i in range(6)}
    assert len(set(names.values())) == len(names), "two (variable, set) pairs share a database: the tests DROP SCHEMA public"
    for n in names.values():
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,62}", n), n
    assert h.database_name("ORGS_TEST_DB", 2) != h.database_name("ORGS_TEST_PEER_DB", 2), "the orgs pair is two databases"


def test_the_env_file_of_a_set_names_every_variable_with_an_asyncpg_url_and_only_that_sets_databases():
    h = load()
    lines = h.env_lines(3, "postgres", "S3CRET", "dbhost")
    env = dict(l.split("=", 1) for l in lines)
    assert set(env) == set(h.KNOWN)
    for v, url in env.items():
        assert url == f"postgresql+asyncpg://postgres:S3CRET@dbhost:5432/{h.database_name(v, 3)}", v
        assert url.endswith("_s3")


# --- up and down, against a fake docker ---------------------------------------------------------------------------------

def test_up_starts_postgres_18_6_creates_every_database_and_writes_private_env_files_without_printing_a_password(tmp_path, capsys):
    h = load()
    d = FakeDocker(ready_after=2)
    out = h.up(sets=2, name="tdb-x", outdir=tmp_path, docker=d, sleep=lambda s: None)
    assert h.IMAGE == "postgres:18.6"
    flat = [" ".join(c) for c in d.calls]
    assert any(c.startswith("docker run -d") and "postgres:18.6" in c and "--name tdb-x" in c for c in flat), flat
    assert sum("pg_isready" in c for c in flat) == 3, "it waits for the server (2 refusals, then ready)"
    created = " ".join(flat)
    for v in h.KNOWN:
        for i in range(2):
            assert f"CREATE DATABASE {h.database_name(v, i)}" in created, (v, i)
    for i in range(2):
        f = tmp_path / f"set{i}.env"
        assert f.exists() and stat.S_IMODE(f.stat().st_mode) == 0o600
        txt = f.read_text()
        assert all(f"{v}=postgresql+asyncpg://" in txt for v in h.KNOWN)
    pw = re.search(r":([0-9a-f]{32})@", (tmp_path / "set0.env").read_text()).group(1)
    shown = capsys.readouterr().out + " ".join(flat) + str(out)
    assert pw not in shown.replace(f"POSTGRES_PASSWORD={pw}", ""), "the password is in no output (it reaches docker only as an environment value)"
    assert out["network"] == "tdb-x-net" and out["container"] == "tdb-x" and out["sets"] == 2


def test_down_removes_the_container_with_its_volumes_and_the_network(tmp_path):
    h = load()
    d = VolumeDocker()
    h.up(sets=1, name="tdb-x", outdir=tmp_path, docker=d, sleep=lambda s: None)
    d.calls.clear()
    h.down("tdb-x", docker=d)
    flat = [" ".join(c) for c in d.calls]
    assert "docker rm -f -v tdb-x" in flat and "docker network rm tdb-x-net" in flat      # -v: the image's anonymous volume goes with the container (see below)


def test_up_gives_up_loudly_when_the_server_never_answers(tmp_path):
    h = load()
    d = FakeDocker(ready_after=10_000)
    with pytest.raises(RuntimeError, match="did not answer"):
        h.up(sets=1, name="tdb-y", outdir=tmp_path, docker=d, sleep=lambda s: None, attempts=5)


# --- the volume the Postgres image declares (V0667 follow-up, order gwo_4acc4907e6449b63de57c4de; found by session-volume's disk census) -------------------------------
# postgres:18.6 declares a VOLUME, so every container made from it carries an anonymous volume. `docker rm -f NAME` removes the container and leaves that volume behind: ~2 GB
# per run, 92 of them (68.6 GB) in 19 hours. `docker rm -f -v NAME` removes the anonymous volumes with it.

class VolumeDocker(FakeDocker):
    """A fake that models the leak: `up` gives the container one anonymous volume; only `rm -v` takes it, and `volume rm` takes any one."""

    def __init__(self):
        super().__init__()
        self.volumes, self.mounts, self.labels, self.net_labels = set(), {}, {}, {}

    def __call__(self, args, **kw):
        a = list(args)
        self.calls.append(a)
        ok = subprocess.CompletedProcess(a, 0, "", "")
        if a[:3] == ["docker", "network", "create"]:
            self.net_labels[a[-1]] = dict(x.split("=", 1) for x in [a[i + 1] for i, v in enumerate(a) if v == "--label"])
            return ok
        if a[:3] == ["docker", "network", "inspect"]:
            return subprocess.CompletedProcess(a, 0 if a[3] in self.net_labels else 1, self.net_labels.get(a[3], {}).get("theprotocol.test-databases", ""), "")
        if a[:2] == ["docker", "run"] and "-d" in a:
            name = a[a.index("--name") + 1]
            self.labels[name] = dict(x.split("=", 1) for x in [a[i + 1] for i, v in enumerate(a) if v == "--label"])
            vol = ("%064x" % (len(self.volumes) + 1)) if "--anon" not in a else "a" * 63 + str(len(self.volumes))
            self.volumes.add(vol)
            self.mounts[name] = [vol]
            return subprocess.CompletedProcess(a, 0, vol, "")
        if a[:2] == ["docker", "inspect"]:
            name = a[2]
            if any("Labels" in x for x in a):
                return subprocess.CompletedProcess(a, 0 if name in self.mounts else 1, self.labels.get(name, {}).get("theprotocol.test-databases", ""), "")
            return subprocess.CompletedProcess(a, 0 if name in self.mounts else 1, " ".join(self.mounts.get(name, [])), "")
        if a[:2] == ["docker", "rm"]:
            name = a[-1]
            if "-v" in a or "-fv" in a:
                self.volumes -= set(self.mounts.get(name, []))
            self.mounts.pop(name, None)
            return ok
        if a[:3] == ["docker", "volume", "inspect"]:
            return subprocess.CompletedProcess(a, 0 if a[3] in self.volumes else 1, "", "")
        if a[:3] == ["docker", "volume", "rm"]:
            self.volumes.discard(a[3])
            return ok
        return super().__call__(args, **kw)


def test_up_records_the_containers_volumes_and_down_leaves_none_of_them(tmp_path):
    h = load()
    d = VolumeDocker()
    out = h.up(sets=1, name="tdb-v", outdir=tmp_path, docker=d, sleep=lambda s: None)
    assert out["volumes"] == list(d.mounts["tdb-v"]) and len(out["volumes"]) == 1, "the volumes the container carries are recorded after up"
    left = h.down("tdb-v", docker=d)
    assert left == [] and d.volumes == set(), f"a volume survived down: {d.volumes}"


def test_down_removes_the_container_with_its_volumes_and_says_so():
    h = load()
    d = VolumeDocker()
    d.volumes.add("1" * 64)
    d.mounts["tdb-w"] = ["1" * 64]
    d.labels["tdb-w"] = {"theprotocol.test-databases": "1"}
    d.net_labels["tdb-w-net"] = {"theprotocol.test-databases": "1"}
    h.down("tdb-w", docker=d)
    flat = [" ".join(c) for c in d.calls]
    assert "docker rm -f -v tdb-w" in flat, flat
    assert not any(c == "docker rm -f tdb-w" for c in flat), "a plain rm -f is the leak"
    assert "docker network rm tdb-w-net" in flat


def test_a_volume_the_removal_left_is_removed_by_name_and_reported():
    """If `rm -v` ever misses one (an older docker, a named mount of the image), down takes it by name and returns it."""
    h = load()

    class Stubborn(VolumeDocker):
        def __call__(self, args, **kw):
            if list(args)[:2] == ["docker", "rm"]:
                self.calls.append(list(args))
                self.mounts.pop(list(args)[-1], None)         # the container goes, its volume stays
                return subprocess.CompletedProcess(args, 0, "", "")
            return super().__call__(args, **kw)

    d = Stubborn()
    d.volumes.add("2" * 64)
    d.mounts["tdb-x"] = ["2" * 64]
    d.labels["tdb-x"] = {"theprotocol.test-databases": "1"}
    left = h.down("tdb-x", docker=d)
    assert left == ["2" * 64] and d.volumes == set(), "the leftover is named and removed"


def test_down_of_a_container_that_is_gone_removes_the_network_and_returns_nothing():
    h = load()
    d = VolumeDocker()
    d.net_labels["tdb-gone-net"] = {"theprotocol.test-databases": "1"}          # up made the network; the container is already gone
    assert h.down("tdb-gone", docker=d) == []
    flat = [" ".join(c) for c in d.calls]
    assert "docker network rm tdb-gone-net" in flat and not any(c.startswith("docker rm") for c in flat)


# --- the safety gap (session-lead, room seq 5777): down takes any --name ------------------------------------------------------------------------------------------------
# A mistyped name must not remove a real database container, and the fallback must never take a NAMED volume (the old down never touched one).

def test_up_labels_the_container_and_its_network():
    h = load()
    d = VolumeDocker()
    h.up(sets=1, name="tdb-l", outdir=pathlib.Path("/tmp") / "tdb-l-out", docker=d, sleep=lambda s: None)
    assert d.labels["tdb-l"] == {"theprotocol.test-databases": "1"} and d.net_labels["tdb-l-net"] == {"theprotocol.test-databases": "1"}


def test_down_refuses_a_container_that_is_not_a_test_databases_container_and_touches_nothing():
    h = load()
    d = VolumeDocker()
    d.mounts["prod-db"] = ["pgdata"]                  # a real database container, no label, one NAMED data volume
    d.volumes.add("pgdata")
    with pytest.raises(h.NotATestDatabase):
        h.down("prod-db", docker=d)
    flat = [" ".join(c) for c in d.calls]
    assert not any(c.startswith(("docker rm", "docker network rm", "docker volume rm")) for c in flat), flat
    assert "prod-db" in d.mounts and d.volumes == {"pgdata"}


def test_a_label_with_another_value_is_refused_too():
    h = load()
    d = VolumeDocker()
    d.mounts["x"] = []
    d.labels["x"] = {"theprotocol.test-databases": "0"}
    with pytest.raises(h.NotATestDatabase):
        h.down("x", docker=d)


def test_the_fallback_removes_only_anonymous_volumes_never_a_named_one():
    h = load()

    class Stubborn(VolumeDocker):
        def __call__(self, args, **kw):
            if list(args)[:2] == ["docker", "rm"]:
                self.calls.append(list(args))
                self.mounts.pop(list(args)[-1], None)
                return subprocess.CompletedProcess(args, 0, "", "")
            return super().__call__(args, **kw)

    d = Stubborn()
    anon, named = "3" * 64, "pgdata"
    d.volumes |= {anon, named}
    d.mounts["tdb-n"] = [anon, named]
    d.labels["tdb-n"] = {"theprotocol.test-databases": "1"}
    left = h.down("tdb-n", docker=d)
    assert left == [anon] and named in d.volumes and anon not in d.volumes, "a named volume survives: only 64-hex anonymous ones are taken"


def test_the_cli_exits_nonzero_and_says_why_when_down_is_refused(capsys):
    h = load()
    d = VolumeDocker()
    d.mounts["prod-db"] = []
    assert h.main(["down", "--name", "prod-db"], docker=d) == 3
    assert "not a test-databases container" in capsys.readouterr().err
    assert not any(c[:2] == ["docker", "rm"] for c in d.calls)
