"""V0666 OPA layer C: an independent verifier that reads what already exists and alerts, never blocks
(sessionlogs2026/DESIGN_2026-11-15_OPA_BACKSTOP.md sections 4, 5, 8 and 10; order gwo_bec4b18190831482a6463d46).

It is built from separate code on purpose: nothing in this package imports the registry (a test reads every import), so a change that
reaches the registry's code cannot reach it through a shared helper, and it is in the policy backstop's forbidden paths (a change
to it is the platform maintainer's, on an approval card). It reads facts itself (a container's environment through an allow-list of
names, a node's database through a read-only transaction, the node's published route list), builds each rule's input with ONE
builder (inputs.py: no literal inputs), asks OPA, and turns a verdict of false into a metric, a vmalert rule and a recorded finding.
It has no write verb to any service.
"""
