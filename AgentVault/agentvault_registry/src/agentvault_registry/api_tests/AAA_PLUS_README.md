# AAA+ API Tester — Architecture Reference

> **Shipped:** 2026-05-21 (overnight autonomous execution per `AUDIT_2026-05-21_API_TESTER_OVERHAUL.md`)
> **Audit:** `sessionlogs2026/AUDIT_2026-05-21_API_TESTER_OVERHAUL.md`
> **Session log:** `sessionlogs2026/SESSION_LOG_2026-05-21_API_TESTER_OVERHAUL_FULL_VISION.md`
> **Memory:** `feedback_api_tester_aaa_architecture.md` + `feedback_test_runner.md`

## TL;DR

- **Catalog source:** live OpenAPI on sandbox-A + `overrides.yaml` glob excludes (MCP games, astraeus)
- **Per-endpoint specs:** declarative `@Endpoint` contracts in `contracts/*.py`
- **Fixtures:** pytest-style scoped fixtures in `fixtures/*.py` resolved by DAG
- **Failure modes:** typed `FailureMode` enum (BUCKET_1/2/3 + business_rule + impossible + not_implemented + …)
- **Dispatch:** contracts run FIRST, fall through to legacy inline FORCE/PD3/EF chain on unknown status (additive only)
- **Workers:** sandbox-A registry-test bumped 2→8; TEG + EventStore 2→4
- **Eager bootstrap:** `POST /admin/api-test/eager-bootstrap` pre-resolves 7 session fixtures in parallel
- **Three runs unified:** Tab 1 (660-endpoint catalog) + Tab 2 (chained-frame Test B) + Tab 3 (dual-frame+bridge)
- **Archive:** `/opt/theprotocol/backups_v2/api_tester_runs/<run_kind>/<timestamp>/`
- **Observability:** Grafana dashboard 29 (api_tester_health)

## Directory layout

```
api_tests/
├── core/                              Generic infrastructure
│   ├── catalog_sync.py                OpenAPI introspection + override merge
│   ├── contract.py                    @Endpoint decorator + execute() runner
│   ├── fixtures.py                    Scoped fixture engine (DAG resolution)
│   ├── failure_modes.py               FailureMode enum + classifier
│   ├── runner.py                      Bucket classification
│   ├── archive.py                     Run archive writer
│   └── snapshot.py                    Response signature diff
├── overrides.yaml                     paths_to_exclude + per-endpoint + tag_remap
├── fixtures/                          Reusable fixtures
│   ├── tokens.py                      admin_token, primary_agent, counterparty, *_token
│   └── financial.py                   funded_primary, funded_counterparty
├── contracts/                         Per-endpoint contracts (50+ files, 330+ contracts)
│   ├── __init__.py                    load_all() registers all
│   └── *.py                           Topic-grouped contracts (one file per logical group)
├── categories/                        Multi-step assertion flows
│   ├── flow_idempotency_key_dedup/    NEW — asserts §pass57
│   ├── flow_fiat_quote_roundtrip/     NEW — asserts §pass50 tier math
│   ├── flow_bundle_lifecycle/         NEW — asserts §pass51 CRUD
│   └── flow_jws_rotation/             NEW — asserts §pass36 key rotation
└── (legacy) endpoints_registry.py     Fallback when OpenAPI unreachable; safe to delete in Phase IV-B
```

## Authoring a new contract

```python
# api_tests/contracts/my_feature.py
from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="POST",
    path="/my/endpoint",
    auth="developer",  # or "agent" or "none" or "mtls"
    category="my_feature",
    idempotent=False,  # True = safe to run in parallel
    slow_timeout_sec=60.0,  # optional override of 30s default
)
class MyEndpoint:
    """One-line description (becomes contract.description)."""

    prereqs = []  # list of fixture names (advanced)

    def body(self, ctx):
        return {"key": "value"}  # or return None for no body

    expected_status = 200  # or list: [200, 201, 422]
    expected_events = []  # list of EventSpec (advanced)

    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="ID placeholder doesn't resolve",
        ),
    ]
```

## Adding an exclusion

Edit `api_tests/overrides.yaml`:

```yaml
paths_to_exclude:
  - "/my/path/*"  # fnmatch glob against full path (with /api/v1 stripped)
```

Restart registry-a — next `/admin/api-test/endpoints?refresh=true` skips matching paths.

## Running the suite

```bash
# Sequential (canonical, ~15-20 min)
python3 /tmp/api_baseline.py

# Parallel (Phase III-D, ~9-12 min, capped at 8 in-flight)
python3 /tmp/api_baseline_v4.py

# From UI
# https://api.theprotocol.cloud/ui#/api-tester → Run All Tests
```

## Run archive

After a baseline:
```bash
ls /opt/theprotocol/backups_v2/api_tester_runs/
```

Or via API:
```bash
curl -H "Authorization: Bearer $DEV_TOKEN" https://api.theprotocol.cloud/api/v1/admin/api-test/archive/runs
```

## Failure-mode bucket reference

| Bucket | When | Action |
|---|---|---|
| BUCKET_1_IMPOSSIBLE | mTLS, real TOTP, email round-trip, Stripe signature | Keep — EF is honest |
| BUCKET_2_PREREQ_GAP | Missing prereq | Fix with a fixture or FORCE handler |
| BUCKET_3_KNOWN_BUG | Backend has a real bug | File as real bug, EF is a TODO |
| BUSINESS_RULE | 4xx because rule fired correctly | Keep — proves the rule works |
| INTENTIONALLY_NOT_IMPLEMENTED | 501 | Use `FailureMode.not_implemented()` |

## Phase IV-B (deferred deletes)

Once contracts cover 100% of endpoints + we've baked for a week, the following can be deleted:
- `views/ApiTester.vue` (1722 LOC dead frontend)
- `services/ApiTesterLogic.ts` DEFAULT_BODIES (456 LOC; replace with server-provided body templates)
- `routers/admin_api_test.py` inline FORCE/PD3/EF chain (L2750-6713; ~4000 LOC; replace fully with contract dispatch)
- `api_tests/endpoints_registry.py` (1018 LOC; replaced by catalog_sync.py)
- `api_tests/request_bodies.py` (1569 LOC; replaced by per-contract body factories)
- `api_tests/test_fixes.py` + `test_fixes_extended.py` (replaced by FailureMode + body factories)

**Total reduction:** ~8,800 LOC. The replacement infrastructure (`core/*.py` + `contracts/*.py` + `fixtures/*.py`) is ~5,500 LOC. **Net reduction: ~3,300 LOC** plus better separation of concerns.
