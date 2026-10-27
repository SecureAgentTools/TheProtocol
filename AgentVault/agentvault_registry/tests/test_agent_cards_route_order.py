"""§BATCH9 (2026-09-06, eb's finding) — GET /agent-cards/by-hri was shadowed by GET /agent-cards/{card_id}.

FastAPI matches in registration order and `card_id` is a str, so the literal "by-hri" was swallowed by the
catch-all and answered "Agent Card not found" for every input; the sibling path form /id/{hri} worked, which
proved it was the route table, not the lookup. Pin: every LITERAL GET route registers before /{card_id}."""
from agentvault_registry.routers import agent_cards


def _get_paths():
    out = []
    for r in agent_cards.router.routes:
        methods = getattr(r, "methods", None) or set()
        if "GET" in methods:
            out.append(r.path)
    return out


def test_by_hri_registers_before_the_card_id_catch_all():
    paths = _get_paths()
    assert "/by-hri" in paths and "/{card_id}" in paths
    assert paths.index("/by-hri") < paths.index("/{card_id}")


def test_every_literal_top_level_get_precedes_the_catch_all():
    paths = _get_paths()
    catch = paths.index("/{card_id}")
    shadowed = [p for i, p in enumerate(paths) if i > catch and p.count("/") == 1 and "{" not in p]
    assert shadowed == [], f"literal routes registered after /{{card_id}} can never match: {shadowed}"


def test_the_path_form_sibling_still_exists():
    assert "/id/{hri}" in _get_paths() or any(p.startswith("/id/") for p in _get_paths())
