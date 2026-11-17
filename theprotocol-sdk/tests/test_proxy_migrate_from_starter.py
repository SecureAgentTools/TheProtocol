"""V0665 (order gwo_93909c1e6870dea448fad760, session-lead's M9 decision, seq 4168): `tp-proxy migrate new --from-starter NAME`.

The three starter kits (sql-to-postgres, csv-to-postgres, sql-to-rest) are not in the 0.9.0 wheel; from 0.10 they ship inside the package
as package data, one command away and offline:

- ONE source: proxy/migrations/ stays the source and the wheel is built with the starters copied in (pyproject's force-include), so a
  test builds the wheel and fails when a starter's file differs from the repo's byte for byte;
- `new --from-starter NAME [DIR]` writes that kit (the same files the repo has) and never overwrites a non-empty folder without --force;
  `new --list-starters` lists the three with one line each; a wrong NAME exits 2 naming the three; --json for both;
- each starter written this way passes `migrate check` and `dry-run --sample` from the written folder, with no network and no account;
- the wheel built from the tree lists the starters, `twine check` passes, and a package unpacked from the wheel (no repo around it)
  writes the same kit.

Red before V0665: there is no --from-starter and no starters in the package.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("jsonschema")

SDK = Path(__file__).resolve().parents[1]
KITS = SDK / "proxy" / "migrations"
NAMES = ("sql-to-postgres", "csv-to-postgres", "sql-to-rest")
IN_WHEEL = "theprotocol/proxy/migrate/starter_kits"

# what each sample was made for (the same figures tests/test_proxy_migrations_starters.py pins)
EXPECT = {
    "sql-to-postgres": {"source": "legacy", "mapping": "customers", "rows": 480, "mapped": 473},
    "csv-to-postgres": {"source": "exports", "mapping": "orders", "rows": 360, "mapped": 355},
    "sql-to-rest": {"source": "legacy", "mapping": "products", "rows": 240, "mapped": 235},
}


def tp(argv, capsys):
    from theprotocol.proxy.cli import main
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def tpj(argv, capsys):
    code, out, err = tp([*argv, "--json"], capsys)
    try:
        return code, json.loads(out) if out.strip() else json.loads(err)
    except ValueError:
        raise AssertionError(f"not JSON (exit {code}): {out[:400]!r} {err[:400]!r}")


def tree(root: Path) -> dict:
    """path (relative, posix) -> bytes, for every file under root, the migrate state folder left out."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".migrate" not in p.relative_to(root).parts and "__pycache__" not in p.parts}


@pytest.fixture
def offline(monkeypatch):
    """No network at all: a connect raises. A starter needs no account and no system to be written, checked or tried."""
    def refused(*a, **k):
        raise AssertionError("a starter reached for the network")
    monkeypatch.setattr(socket.socket, "connect", refused)


# ── --list-starters ──────────────────────────────────────────────────────────────────────

def test_list_starters_names_the_three_with_one_line_each(capsys):
    code, out, err = tp(["migrate", "new", "--list-starters"], capsys)
    assert code == 0, err
    lines = [x for x in out.splitlines() if x.strip()]
    assert [x.split()[0] for x in lines] == list(NAMES), out
    for name, line in zip(NAMES, lines):
        title = __import__("yaml").safe_load((KITS / name / "migration.yaml").read_text(encoding="utf-8"))["title"]
        assert title in line, (name, line)


def test_list_starters_as_json(capsys):
    code, ans = tpj(["migrate", "new", "--list-starters"], capsys)
    assert code == 0 and ans["exit"] == 0
    assert [s["name"] for s in ans["starters"]] == list(NAMES)
    for s in ans["starters"]:
        assert s["title"] and s["summary"] and s["content_hash"]


# ── --from-starter writes the kit the repo has ──────────────────────────────────────────

@pytest.mark.parametrize("name", NAMES)
def test_from_starter_writes_exactly_the_files_the_repo_has(name, tmp_path, capsys):
    dest = tmp_path / "my-move"
    code, ans = tpj(["migrate", "new", "--from-starter", name, str(dest)], capsys)
    assert code == 0, ans
    assert tree(dest) == tree(KITS / name)
    assert ans["starter"] == name and ans["kit"] == str(dest.resolve())
    assert sorted(ans["files"]) == sorted(tree(KITS / name))
    assert ans["next"] == [f"tp-proxy migrate check {dest.resolve()}", f"tp-proxy migrate dry-run {dest.resolve()} --sample"]
    assert len(ans["content_hash"]) == 64


def test_from_starter_text_answer_names_the_next_steps(tmp_path, capsys):
    code, out, err = tp(["migrate", "new", "--from-starter", "sql-to-rest", str(tmp_path / "k")], capsys)
    assert code == 0, err
    assert "tp-proxy migrate dry-run" in out and "--sample" in out


def test_without_a_folder_it_writes_to_a_folder_named_for_the_starter(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, ans = tpj(["migrate", "new", "--from-starter", "csv-to-postgres"], capsys)
    assert code == 0, ans
    assert (tmp_path / "csv-to-postgres" / "migration.yaml").is_file()
    assert tree(tmp_path / "csv-to-postgres") == tree(KITS / "csv-to-postgres")


def test_out_names_the_folder_too_and_both_is_a_usage_error(tmp_path, capsys):
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-rest", "--out", str(tmp_path / "o")], capsys)
    assert code == 0 and (tmp_path / "o" / "migration.yaml").is_file()
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-rest", str(tmp_path / "a"), "--out", str(tmp_path / "b")], capsys)
    assert code == 2, ans
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_a_wrong_name_exits_2_and_names_the_three(tmp_path, capsys):
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-oracle", str(tmp_path / "x")], capsys)
    assert code == 2, ans
    text = " ".join(ans["problems"])
    for name in NAMES:
        assert name in text
    assert "sql-to-oracle" in text
    assert not (tmp_path / "x").exists()


def test_it_never_overwrites_a_non_empty_folder_without_force(tmp_path, capsys):
    dest = tmp_path / "k"
    dest.mkdir()
    (dest / "mine.txt").write_text("keep me", encoding="utf-8")
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-postgres", str(dest)], capsys)
    assert code == 1, ans
    assert "--force" in " ".join(ans["problems"])
    assert (dest / "mine.txt").read_text(encoding="utf-8") == "keep me" and not (dest / "migration.yaml").exists()
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-postgres", str(dest), "--force"], capsys)
    assert code == 0, ans
    assert (dest / "migration.yaml").is_file()


def test_a_file_where_the_folder_should_be_is_a_sentence_not_a_traceback(tmp_path, capsys):
    f = tmp_path / "in-the-way"
    f.write_text("a file", encoding="utf-8")
    for argv in (["migrate", "new", "--from-starter", "sql-to-rest", str(f)], ["migrate", "new", "my-kit", "--from", "sql", "--to", "sql", "--out", str(f)]):
        code, ans = tpj(argv, capsys)
        assert code == 1, ans
        assert "is a file, not a folder" in " ".join(ans["problems"])
        assert f.read_text(encoding="utf-8") == "a file"


@pytest.mark.parametrize("name", NAMES)
def test_the_kit_is_written_as_the_bytes_it_is_whatever_the_platform_does_to_a_line_feed(name, tmp_path, capsys, monkeypatch):
    """On Windows Path.write_text turns every line feed into a carriage return and a line feed, and the kit's content hash reads the raw
    bytes: a kit written there would not carry the hash it was published with. Simulated here: write_text does what Windows does."""
    real = Path.write_text

    def windows_write_text(self, data, encoding=None, errors=None, newline=None):
        return real(self, data.replace("\n", "\r\n"), encoding=encoding, errors=errors, newline=newline)
    monkeypatch.setattr(Path, "write_text", windows_write_text)
    dest = tmp_path / name
    code, ans = tpj(["migrate", "new", "--from-starter", name, str(dest)], capsys)
    assert code == 0, ans
    assert tree(dest) == tree(KITS / name)
    assert not any(b"\r\n" in data and b"\r\n" not in (KITS / name / rel).read_bytes() for rel, data in tree(dest).items())
    from theprotocol.proxy.migrate.schema import load_kit
    assert load_kit(dest).content_hash == ans["content_hash"] == load_kit(KITS / name).content_hash


def test_an_empty_existing_folder_is_fine(tmp_path, capsys):
    dest = tmp_path / "empty"
    dest.mkdir()
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-postgres", str(dest)], capsys)
    assert code == 0, ans


def test_the_old_forms_of_new_still_work_and_still_need_their_arguments(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, ans = tpj(["migrate", "new", "my-move", "--from", "sql", "--to", "sql"], capsys)
    assert code == 0 and (tmp_path / "my-move" / "migration.yaml").is_file()
    code, ans = tpj(["migrate", "new", "--from", "sql", "--to", "sql"], capsys)           # no name
    assert code == 2, ans
    code, ans = tpj(["migrate", "new", "my-move2"], capsys)                                # no kinds
    assert code == 2, ans
    code, ans = tpj(["migrate", "new", "--from-starter", "sql-to-rest", "--from", "sql", "--to", "sql"], capsys)
    assert code == 2, ans                                                                  # a starter has its own kinds


# ── each starter, written this way, checks and tries from where it was written ────────

@pytest.mark.parametrize("name", NAMES)
def test_a_written_starter_passes_check_and_dry_runs_on_its_sample_with_no_network(name, tmp_path, capsys, offline):
    dest = tmp_path / name
    code, ans = tpj(["migrate", "new", "--from-starter", name, str(dest)], capsys)
    assert code == 0, ans
    code, ans = tpj(["migrate", "check", str(dest)], capsys)
    assert code == 0 and ans["valid"] is True, ans
    e = EXPECT[name]
    code, rep = tpj(["migrate", "dry-run", str(dest), "--sample"], capsys)
    assert code == 0, rep
    assert rep["step"] == "dry_run" and rep["sample"] is True and rep["verdict"] == "pass"
    assert rep["sources"][e["source"]]["rows"] == e["rows"]
    assert rep["mappings"][e["mapping"]]["mapped"] == e["mapped"]


# ── packaging: the wheel carries the starters, byte for byte, and installs without the repo ───────

@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    hatchling = pytest.importorskip("hatchling.build", reason="hatchling is not installed here (pip install hatchling==1.27.0)")
    out = tmp_path_factory.mktemp("wheel")
    was = os.getcwd()
    os.chdir(SDK)
    try:
        name = hatchling.build_wheel(str(out))
    finally:
        os.chdir(was)
    return out / name


def test_the_wheel_lists_the_three_starters_and_each_file_matches_the_repo_byte_for_byte(wheel):
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        left = sorted(n for n in names if ".migrate" in n)
        assert not left, f"a starter was run in place and left its state folder: remove proxy/migrations/*/.migrate before building ({left[:2]})"
        for name in NAMES:
            repo = tree(KITS / name)
            assert repo, name
            for rel, data in repo.items():
                path = f"{IN_WHEEL}/{name}/{rel}"
                assert path in names, f"the wheel has no {path}"
                assert z.read(path) == data, f"{path} differs from proxy/migrations/{name}/{rel}"
            have = {n[len(f'{IN_WHEEL}/{name}/'):] for n in names if n.startswith(f"{IN_WHEEL}/{name}/") and not n.endswith("/")}
            assert have == set(repo), f"{name}: the wheel holds {sorted(have ^ set(repo))} that the repo does not (or the other way round)"
        # nothing else from proxy/migrations rides along (the folder's own README and the sample generator stay in the repo)
        stray = [n for n in names if n.startswith(f"{IN_WHEEL}/") and n.split("/")[4:5] and n.split("/")[4] not in NAMES]
        assert stray == [], stray
        assert not [n for n in names if "__pycache__" in n and "/starters/" in n]


def test_a_starter_dry_run_in_place_does_not_ride_into_a_wheel_built_from_that_tree(tmp_path):
    """The force-include names each starter file (not three folders): hatch copies a folder whole, .gitignore or not, so a starter run in place
    (its .migrate/ state folder beside it) would otherwise ship scratch into the wheel. Built from a copy of the SDK with a stray one planted."""
    import shutil
    hatchling = pytest.importorskip("hatchling.build", reason="hatchling is not installed here (pip install hatchling==1.27.0)")
    sdk = tmp_path / "sdk"
    shutil.copytree(SDK, sdk, ignore=shutil.ignore_patterns("dist_release", "__pycache__", ".pytest_cache", "tests"))
    stray = sdk / "proxy" / "migrations" / "sql-to-rest" / ".migrate" / "scratch"
    stray.mkdir(parents=True)
    (stray / "leak.txt").write_text("scratch", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    was = os.getcwd()
    os.chdir(sdk)
    try:
        name = hatchling.build_wheel(str(out))
    finally:
        os.chdir(was)
    with zipfile.ZipFile(out / name) as z:
        names = z.namelist()
    assert [n for n in names if ".migrate" in n] == []
    assert len([n for n in names if f"{IN_WHEEL}/" in n]) == sum(len(tree(KITS / k)) for k in NAMES)


def test_twine_check_passes_on_the_wheel(wheel):
    pytest.importorskip("twine", reason="twine is not installed here (pip install twine)")
    r = subprocess.run([sys.executable, "-m", "twine", "check", str(wheel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_package_unpacked_from_the_wheel_writes_the_same_kit_with_no_repo_around_it(wheel, tmp_path):
    unpacked = tmp_path / "site"
    with zipfile.ZipFile(wheel) as z:
        z.extractall(unpacked)
    code = (
        "import sys, json, theprotocol; from theprotocol.proxy.cli import main\n"
        "print('FROM', theprotocol.__file__)\n"
        "sys.exit(main(['migrate','new','--from-starter','sql-to-rest','out','--json']))\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=work,
                       env={**os.environ, "PYTHONPATH": str(unpacked)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"FROM {unpacked}" in r.stdout, r.stdout[:200]                 # it ran from the wheel's files, not the checkout
    assert tree(work / "out") == tree(KITS / "sql-to-rest")
    r = subprocess.run([sys.executable, "-c", code.replace("'sql-to-rest','out'", "'bogus','out2'")], capture_output=True, text=True,
                       cwd=work, env={**os.environ, "PYTHONPATH": str(unpacked)})
    assert r.returncode == 2 and all(n in r.stdout for n in NAMES), r.stdout + r.stderr
