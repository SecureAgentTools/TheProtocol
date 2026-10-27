"""§HELLOFRAME: the one-shot loads the provisioner from its compiled sibling when a release image ships no source."""
import os
import py_compile
import shutil

import pytest

from agentvault_registry import host_work


def _tree(tmp_path, with_source):
    src = os.path.join(os.path.dirname(host_work.__file__), "services", "operator_provisioner.py")
    d = tmp_path / "services"; d.mkdir()
    py = d / "operator_provisioner.py"; shutil.copy(src, py)
    py_compile.compile(str(py), cfile=str(d / "operator_provisioner.pyc"))
    if not with_source:
        py.unlink()
    return str(tmp_path)


def test_the_source_is_preferred_when_present(tmp_path):
    base = _tree(tmp_path, with_source=True)
    assert host_work.provisioner_module_path(base).endswith("operator_provisioner.py")
    assert hasattr(host_work._load_provisioner(base), "provision_operator")


def test_a_bytecode_only_tree_loads_the_compiled_sibling(tmp_path):
    base = _tree(tmp_path, with_source=False)
    assert host_work.provisioner_module_path(base).endswith("operator_provisioner.pyc")
    assert hasattr(host_work._load_provisioner(base), "provision_operator")


def test_neither_present_names_both(tmp_path):
    (tmp_path / "services").mkdir()
    with pytest.raises(FileNotFoundError, match="operator_provisioner.pyc"):
        host_work.provisioner_module_path(str(tmp_path))
