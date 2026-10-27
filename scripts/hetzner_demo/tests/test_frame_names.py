"""§TESTBED P0 a (2026-09-19): a frame's stack dirs, containers, volumes and networks are decided EXACTLY, by the compose
project label, so `frame-down --name a` leaves a frame named `a-b` (and one named `ab`) alone.

Pinned on fixture inventories; the live control (throwaway names on a real docker) is a proof run, not here.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("frame_names", os.path.join(os.path.dirname(HERE), "frame_names.py"))
fn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fn)

# three frames on one host: a, a-b (a prefix collision with `a-`), ab (a prefix collision with `a` alone)
INVENTORY = {
    "containers": [("a-registry", "a-111"), ("a-edge", "a-edge"), ("a-b-registry", "a-b-222"), ("a-b-edge", "a-b-edge"),
                   ("ab-registry", "ab-333"), ("a-helper", ""), ("a-b-helper", ""), ("cloud-op-x-registry", "cloud-op-x")],
    "volumes": [("a_pg_registry_111", "a-111"), ("a-edge_edge_data", "a-edge"), ("a_b_pg_registry_222", "a-b-222"),
                ("ab_pg_registry_333", "ab-333"), ("a_stray", ""), ("a_b_stray", "")],
    "networks": [("a_network", "a-111"), ("a_network_edge", "a-111"), ("a_b_network", "a-b-222"), ("ab_network", "ab-333"),
                 ("a_old_network", "a-100")],
}


def test_the_frame_is_its_projects_not_its_prefix():
    got = fn.select(INVENTORY, "a")
    assert got["containers"] == ["a-edge", "a-helper", "a-registry"]
    assert got["volumes"] == ["a-edge_edge_data", "a_pg_registry_111", "a_stray"]
    assert got["networks"] == ["a_network", "a_network_edge", "a_old_network"]   # an older stack of the same frame is its own
    assert got["projects"] == {"a-111", "a-edge", "a-100"}


def test_the_longer_named_frame_keeps_its_own():
    got = fn.select(INVENTORY, "a-b")
    assert got["containers"] == ["a-b-edge", "a-b-helper", "a-b-registry"]
    assert got["volumes"] == ["a_b_pg_registry_222", "a_b_stray"]
    assert got["networks"] == ["a_b_network"]
    assert fn.select(INVENTORY, "ab")["containers"] == ["ab-registry"]


def test_control_the_old_prefix_rule_took_the_other_frame():
    """The rule this replaces (`startswith(name + "-")`, volumes `name_`): for `a` it took a-b's containers and volumes."""
    old = [n for n, _ in INVENTORY["containers"] if n.startswith("a-")]
    assert "a-b-registry" in old and "a-b-registry" not in fn.select(INVENTORY, "a")["containers"]
    old_v = [v for v, _ in INVENTORY["volumes"] if v.startswith("a_")]
    assert "a_b_pg_registry_222" in old_v and "a_b_pg_registry_222" not in fn.select(INVENTORY, "a")["volumes"]


def test_stack_dirs_are_name_then_digits(tmp_path):
    for d in ("a-111", "a-b-222", "ab-333", "a-backup", "a-99"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "docker-compose.frame-test.yml").write_text("services: {}\n")
    (tmp_path / "a-444").mkdir()   # no compose file: not a stack
    assert fn.stack_dirs(str(tmp_path), "a") == ["a-99", "a-111"]   # numeric order, oldest first
    assert fn.stack_dirs(str(tmp_path), "a", need_file=None) == ["a-99", "a-111", "a-444"]
    assert fn.stack_dirs(str(tmp_path), "a-b") == ["a-b-222"]
    assert fn.stack_dirs(str(tmp_path / "missing"), "a") == []


def test_a_stack_dir_names_another_frame_for_unlabelled_strays(tmp_path):
    """A frame known only by its stack dir (no labelled resource left) still claims its longer prefix."""
    (tmp_path / "a-b-222").mkdir()
    (tmp_path / "a-b-222" / "docker-compose.frame-test.yml").write_text("services: {}\n")
    inv = {"containers": [("a-b-helper", ""), ("a-helper", "")], "volumes": [], "networks": []}
    assert fn.select(inv, "a", str(tmp_path))["containers"] == ["a-helper"]
    assert fn.select(inv, "a")["containers"] == ["a-b-helper", "a-helper"]   # without the dir nothing names a-b: the prefix rule


def test_project_labels():
    assert fn.owns_project("a-111", "a") and fn.owns_project("a-edge", "a")
    assert not fn.owns_project("a-b-222", "a") and not fn.owns_project("ab-111", "a") and not fn.owns_project("", "a")
    assert fn.frame_of_project("a-b-222") == "a-b" and fn.frame_of_project("a-edge") == "a"
    assert fn.frame_of_project("cloud-op-x") is None and fn.frame_of_project("agentvault2") is None
