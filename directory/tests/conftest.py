"""The reader-gate CI job (`.forgejo/workflows/hygiene.yml`, eventstore-sanity) runs these tests WITHOUT the registry package;
the Directory itself is built FROM the registry image and imports it (`directory/ingest.py`). A test module that needs the
registry says so with `REQUIRES_REGISTRY = True` in its own text. Where the package is absent, that module is not collected
and the run says which, in the terminal summary (shown under -q too): a test that cannot run here is named, never silently
counted as passed. In the directory image every module is collected.
"""
import importlib.util
import pathlib

HAVE_REGISTRY = importlib.util.find_spec("agentvault_registry") is not None
_NEEDS = sorted(p.name for p in pathlib.Path(__file__).parent.glob("test_*.py") if "REQUIRES_REGISTRY = True" in p.read_text())
collect_ignore = [] if HAVE_REGISTRY else list(_NEEDS)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if collect_ignore:
        terminalreporter.write_line(
            f"agentvault_registry absent: {len(collect_ignore)} registry test module(s) not collected here "
            f"(they run in the directory image): {', '.join(collect_ignore)}")
