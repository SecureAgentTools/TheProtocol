"""V0659 (e), the release: the SDK's version is written in three places, and they agree.

pyproject.toml names the version a build stamps into the wheel, theprotocol.__version__ is what a running program reads,
and the README's changelog opens with the release a reader is looking at. 0.7.6 was uploaded on 2026-10-20 while the
changelog still called it "not built or uploaded yet", and nothing compared the three: this does.
"""
import re
from pathlib import Path

import theprotocol

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    m = re.search(r'^version = "([^"]+)"$', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml names no version"
    return m.group(1)


def _changelog_versions() -> list:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("\n## Changelog\n", 1)[1]
    return re.findall(r"^\*\*(\d+\.\d+\.\d+|Unreleased)\*\*", section, re.M)


def test_the_package_reports_the_version_it_is_built_as():
    assert theprotocol.__version__ == _pyproject_version()


def test_the_changelog_opens_with_the_version_being_built():
    versions = _changelog_versions()
    assert versions, "the README's changelog names no release"
    assert versions[0] == _pyproject_version(), f"the changelog opens with {versions[0]}, the build is {_pyproject_version()}"


def test_the_changelog_names_each_release_once_newest_first():
    released = [v for v in _changelog_versions() if v != "Unreleased"]
    assert len(released) == len(set(released)), released
    keys = [tuple(int(p) for p in v.split(".")) for v in released]
    assert keys == sorted(keys, reverse=True), released
