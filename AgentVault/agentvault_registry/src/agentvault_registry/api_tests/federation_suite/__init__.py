"""Federation test suite — AAA+ multi-registry MCP-orchestrated assertions.

Tests real distributed-system claims federation makes:
  - Events emitted on registry A reach registry B within budget T
  - Reactors fire on receivers when federated events land
  - Trust scores converge across federated peers (EigenTrust, Bayesian)
  - Provisioning a new cloud-op is end-to-end correct
  - Supply invariant holds GLOBALLY across all federated frames
  - License revocation causes economic quarantine on the target operator
  - Compliance drift surfaces on the central registry

Architecture:
  - FederationTestRig — holds MCP clients for every sandbox registry
  - @federation_test decorator — registers tests with metadata
  - assert_within — eventual-consistency assertion with budget poller
  - Reporter — outcome aggregation, per-test latency, budget violations

See: sessionlogs2026/PLAN_2026-05-27_FEDERATION_TEST_SUITE_AAA.md

Sandbox-only by design — federation tests mutate state across multiple
registries and require the sandbox topology (sandbox-A + sandbox-B mainframes
+ sandboxalpha + sandboxdelta cloud-ops, all federated, all MCP-accessible).
"""
