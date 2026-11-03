"""V0655 (aw), order gwo_22ba4784e0615b4537aefa21: no code comment or docstring in the paths the OSS export carries says
that a choice was made by the maintainer in person. The phrases are PHRASE's below, built from parts so that this file
holds none of them.

The strings that keep such a phrase are listed with their counts in tests/attribution_kept.json: the MCP tester's skip
and refusal reasons (tests pin several of them), two test titles and the tester's matching rule. Every other file holds
none, and a listed file holds exactly its count, so a stale line fails too and the list only shrinks. A comment or a
docstring says what the code does and why; who decided it belongs in the session log.

The stack's export reads the same list from the export itself (scripts/distribution/oss_export.py, gate G15) and refuses
a file that holds more than the list allows. The pattern is copied there, not imported, because that repository is not
beside this one in CI: change both together.

In a checkout this reads every path of the export's AgentVault set. In CI's staged layout (.forgejo/workflows/ci.yml) it
reads what the stage holds: the registry's tests, alembic, scripts, config and source (with the console's source linked
in), and the TEG's source. A hit names the file and the line.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
REG = TESTS.parent
REPO = TESTS.parents[1]
KEPT_FILE = TESTS / "attribution_kept.json"
_HIS = "h" + "is"
PHRASE = re.compile(rf"(?i)\b({_HIS} words?|on {_HIS} word|{_HIS} decision|{_HIS} call|{_HIS} order)\b".encode())
# the AgentVault half of the export's set (the stack's oss_export.py AV_SHIP)
AV_SHIP = ["agentvault_registry", "agentvault_teg_layer_mvp", "agentvault_library", "agentvault_circuit_registry",
           "agentvault_server_sdk", "agentvault_cli", ".forgejo", "pyproject.toml", "README.md", "LICENSE", ".dockerignore",
           "CONTRIBUTING.md", "SECURITY.md", "CLA.md"]
# build output and caches, which the export never carries; the journal's media (images and video) holds no text
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".git", ".pytest_cache", "htmlcov", ".venv", "venv", "build"}
JOURNAL_MEDIA = "static/new_registry_frontend/public/blog"
# the release build mounts the STACK's scripts/distribution inside the registry's scripts/ for the tests that read it;
# the registry has no such directory of its own, and the stack's own test (scripts/distribution/tests) reads that one
NOT_OURS = {"agentvault_registry/scripts/distribution"}
TEXT_MAX = 8 * 1024 * 1024          # oss_export.py's TEXT_MAX: larger files are not text the export's gates read


def _checkout() -> bool:
    return (REPO / "agentvault_registry" / "tests").resolve() == TESTS


def _roots() -> list:
    """(path to read, its name in the repository)"""
    if _checkout():
        return [(REPO / p, p) for p in AV_SHIP]
    return ([(REG / d, f"agentvault_registry/{d}") for d in ("tests", "alembic", "scripts", "config", "src")]
            + [(REPO / "agentvault_teg_layer_mvp" / "src", "agentvault_teg_layer_mvp/src")])


def _files():
    """(path, its name in the repository) for every file under the roots; links are followed (CI links the image's
    source and the console's source into the stage), each directory read once"""
    seen = set()
    for root, name in _roots():
        if root.is_file():
            yield root, name
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in seen:
                dirnames[:] = []
                continue
            seen.add(real)
            rel = os.path.relpath(dirpath, root)
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")
                                 and not f"{name}/{rel}/{d}".endswith(JOURNAL_MEDIA)
                                 and os.path.normpath(f"{name}/{rel}/{d}") not in NOT_OURS)
            for fn in sorted(filenames):
                yield pathlib.Path(dirpath) / fn, os.path.normpath(f"{name}/{rel}/{fn}")


def count(data: bytes) -> int:
    return len(PHRASE.findall(data))


def _census() -> tuple:
    """(the names of the files read, {name: phrases it holds}, {name: the lines they are on})"""
    read, found, lines = set(), {}, {}
    for p, name in _files():
        try:
            if p.stat().st_size > TEXT_MAX:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        read.add(name)
        n = count(data)
        if n:
            found[name] = n
            lines[name] = [data.count(b"\n", 0, m.start()) + 1 for m in PHRASE.finditer(data)]
    return read, found, lines


def _kept() -> dict:
    return {k: int(v) for k, v in json.loads(KEPT_FILE.read_text(encoding="utf-8"))["kept"].items()}


@pytest.fixture(scope="module")
def census():
    return _census()


def test_the_check_read_the_repository(census):
    read, _found, _lines = census
    floor = 4000 if _checkout() else 2000
    assert len(read) >= floor, f"read {len(read)} files, expected at least {floor}: the check measured too little"
    for part, at_least in (("agentvault_registry/tests/", 500), ("agentvault_registry/src/agentvault_registry/", 1000),
                           ("agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/", 500),
                           ("agentvault_teg_layer_mvp/src/", 50)):
        n = sum(1 for name in read if name.startswith(part))
        assert n >= at_least, f"read {n} files under {part}, expected at least {at_least}"


def test_no_comment_or_docstring_names_whose_choice_it_was(census):
    _read, found, lines = census
    kept = _kept()
    over = [f"{name}:{lines[name]} holds {n}, the list allows {kept.get(name, 0)}"
            for name, n in sorted(found.items()) if n > kept.get(name, 0)]
    assert not over, ("a comment or docstring attributes a choice to a person; say what the code does and why "
                      "(a string a test pins goes into tests/attribution_kept.json with its count):\n  " + "\n  ".join(over))


def test_the_kept_list_is_exact(census):
    _read, found, _lines = census
    kept = _kept()
    stale = [f"{name}: listed {n}, holds {found.get(name, 0)}" for name, n in sorted(kept.items()) if found.get(name, 0) < n]
    assert not stale, "tests/attribution_kept.json allows more than the file holds; lower or drop the line:\n  " + "\n  ".join(stale)


def test_the_kept_list_names_real_files():
    missing = [name for name in _kept() if not (REPO / name).is_file() and not _staged(name).is_file()]
    assert not missing, "tests/attribution_kept.json names files that do not exist:\n  " + "\n  ".join(missing)


def _staged(name: str) -> pathlib.Path:
    for root, prefix in _roots():
        if name.startswith(prefix + "/"):
            return root / name[len(prefix) + 1:]
    return REPO / name


@pytest.mark.parametrize("sample, n", [
    (b"# (" + _HIS.encode() + b" word 2026-10-27): published", 1),
    (b'"""' + _HIS.encode() + b" decision, " + _HIS.encode() + b" call and " + _HIS.encode() + b' order."""', 3),
    (b"// on " + _HIS.encode() + b" word", 1),
    (_HIS.upper().encode() + b" WORDS: x", 1),
])
def test_each_phrase_counts_on_its_control(sample, n):
    assert count(sample) == n, f"{sample!r} counted {count(sample)}, expected {n}: the check would pass blind"


@pytest.mark.parametrize("sample", [
    b"# t" + _HIS.encode() + b" word is reserved",          # inside a longer word
    b"# " + _HIS.encode() + b" wording, " + _HIS.encode() + b" orders",
    b"# the maintainer decided (2026-10-27)",
])
def test_other_words_stay_quiet(sample):
    assert count(sample) == 0
