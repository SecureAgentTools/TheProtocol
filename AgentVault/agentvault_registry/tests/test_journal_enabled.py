"""§HELLOFRAME (his word 2026-09-19, "Ship without it"): the journal is on where the served console carries its media,
off where it does not (an export frame ships none), and the only override is OFF: an override to ON over missing media
would render 46 posts of broken images."""
import ast
from pathlib import Path

from agentvault_registry.core.journal import journal_enabled, journal_media_present

MAIN = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "main.py"


def _dist(tmp_path, with_media: bool, empty_dir: bool = False) -> Path:
    d = tmp_path / "dist"
    d.mkdir(parents=True)
    if with_media or empty_dir:
        (d / "blog").mkdir()
    if with_media:
        (d / "blog" / "p46-1-lead.jpg").write_bytes(b"\xff\xd8")
    return d


def test_media_present_means_on(tmp_path):
    assert journal_enabled(_dist(tmp_path, True), env={}) is True


def test_no_media_means_off(tmp_path):
    assert journal_enabled(_dist(tmp_path, False), env={}) is False


def test_an_empty_blog_dir_is_no_media(tmp_path):
    d = _dist(tmp_path, False, empty_dir=True)
    assert journal_media_present(d) is False
    assert journal_enabled(d, env={}) is False


def test_off_overrides_media(tmp_path):
    for v in ("false", "0", "no", "off", " FALSE "):
        assert journal_enabled(_dist(tmp_path / v.strip(), True), env={"JOURNAL_ENABLED": v}) is False, v


def test_no_override_to_on_over_missing_media(tmp_path):
    # the control: a flag cannot claim what its precondition cannot supply
    for v in ("true", "1", "yes", "on"):
        assert journal_enabled(_dist(tmp_path / v, False), env={"JOURNAL_ENABLED": v}) is False, v


def test_an_unrecognised_value_is_derived(tmp_path):
    assert journal_enabled(_dist(tmp_path, True), env={"JOURNAL_ENABLED": "maybe"}) is True


def test_a_missing_dist_is_off(tmp_path):
    assert journal_enabled(tmp_path / "nowhere", env={}) is False


def test_registry_config_publishes_journal_enabled_from_the_served_dist():
    """The public registry-config carries `journal_enabled`, computed from STATIC_DIR (the directory the app serves),
    so the console's guard and links read the same answer the server derived."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config")
    keys = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = v
    assert "journal_enabled" in keys
    call = keys["journal_enabled"]
    assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_journal_enabled"
    assert [getattr(a, "id", None) for a in call.args] == ["STATIC_DIR"]
