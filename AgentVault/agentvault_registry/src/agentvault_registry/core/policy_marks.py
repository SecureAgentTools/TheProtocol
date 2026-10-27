"""
Shared markers for test-harness outcome classification.

§MCPTEST-MCP10 (2026-08-08). This constant is read by TWO modules that live in
different import graphs:

  * the runner  — ``api_tests/categories/flow_mcp_lifecycle/test_flow_mcp_lifecycle.py``
    stamps it onto the ``skip_reason`` of a tool it refuses to invoke, and
    counts the split (``policy_denied`` vs ``skipped``).
  * the router  — ``routers/mcp_tester.py`` re-derives the same split when it
    normalises a finished run into the persisted summary + lists.

It lives here, in a leaf module of the already-imported ``core`` package,
because the alternative shapes are both wrong:

  * duplicating the literal in the router is the drift class — the two halves
    would agree today and silently disagree the first time the wording changes,
    and the symptom (a policy-denied tool filed as a coverage hole) looks like
    a data problem rather than a constant problem.
  * importing the runner from the router would drag the whole ``api_tests``
    package into every registry's boot path for one string.

**Semantics.** A skip_reason containing this marker means *"a standing
operating rule forbids the tester from invoking this tool"* (frame/registry
provisioning, teardown, self-provision, simulation start/stop, canary fleet
pause). That is NOT the same fact as *"we could not test this"* — a coverage
hole is work owed; a policy denial is work declined on purpose. Reporting them
under one heading overstates the gap.
"""

# Substring test, not equality: the runner appends per-tool context after it.
POLICY_DENIED_MARK = "never invoked by tester"

__all__ = ["POLICY_DENIED_MARK"]
