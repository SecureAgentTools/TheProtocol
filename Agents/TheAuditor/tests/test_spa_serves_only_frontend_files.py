"""The auditor's catch-all route serves files of the built frontend and nothing beside it (code scanning, 2026-11-01):
a request path whose resolved file lies outside FRONTEND_DIR gets the frontend's index, never that file."""
import asyncio
import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.getenv("AUDITOR_TREE") or HERE


def _purge():
    for name in [n for n in sys.modules if n == "src" or n.startswith("src.")]:
        del sys.modules[name]


@pytest.fixture
def main(tmp_path, monkeypatch):
    front = tmp_path / "frontend"
    front.mkdir()
    (front / "index.html").write_text("<html>the index</html>")
    (front / "app.js").write_text("console.log('app')")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.txt").write_text("not for the web")
    _purge()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONTEND_DIR", str(front))
    monkeypatch.syspath_prepend(TREE)
    module = importlib.import_module("src.auditor.main")
    yield module
    _purge()


def body(resp):
    return resp.body.decode()


def test_a_frontend_file_is_served(main):
    assert main._frontend_file("app.js") is not None
    assert body(asyncio.run(main.serve_spa("app.js"))) == "console.log('app')"


@pytest.mark.parametrize("path", ["../outside/secret.txt", "assets/../../outside/secret.txt"])
def test_a_path_outside_the_frontend_gets_the_index(main, path):
    assert main._frontend_file(path) is None
    assert body(asyncio.run(main.serve_spa(path))) == "<html>the index</html>"


def test_an_absolute_path_outside_the_frontend_gets_the_index(main, tmp_path):
    outside = str(tmp_path / "outside" / "secret.txt")
    assert main._frontend_file(outside) is None
    assert body(asyncio.run(main.serve_spa(outside))) == "<html>the index</html>"


def test_a_missing_file_gets_the_index(main):
    assert main._frontend_file("nope.js") is None
    assert body(asyncio.run(main.serve_spa("nope.js"))) == "<html>the index</html>"
