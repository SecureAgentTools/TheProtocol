"""Command Center diagnostics package.

Transport-agnostic probe + check architecture. Phase 1 ships LocalDockerProbe
running checks on the same Hetzner host. Phase 2 will add RemoteSpiffeProbe
for off-host operators, behind the same CheckResult contract.
"""
