# Change Management Policy

| Field       | Value                          |
|-------------|--------------------------------|
| Version     | 2.1.2                          |
| Status      | DRAFT: self-assessment (not independently audited) |
| Date        | 2026-10-17                     |
| Owner       | Commander ruFFa                |
| Review Cycle| Quarterly                      |

---

## 1. Purpose

This policy defines how changes to TheProtocol production environment are categorized, approved, tested, deployed, and rolled back. It ensures that all modifications preserve system integrity, particularly the supply invariant (delta=0.0), and that changes are traceable through version control and documentation.

---

## 2. Scope

This policy applies to all changes affecting:
- Production containers (the frames' and cloud operators' compose stacks, and docker-compose.production.yml)
- Source code (AgentVault/, agentvault-event-store/, identity-fabric/, theprotocol-sdk/)
- Database schemas (the registry's Alembic migrations)
- Configuration (.env.production, nginx, SPIRE, OPA policies)
- Frontend (Vue 3 + Pinia, built assets baked into Docker images)
- Documentation (PRODUCTION_DOCS/, CLAUDE.md)
- Federation parameters (fee rates, enforcement thresholds<!-- on: staking_rewards -->, and the payout curve on locked units; payouts on locked units are switched off on the production frames<!-- /on -->)
- MCP server tools and bridge configuration

---

## 3. Change Categories

### 3.1 STANDARD

Low-risk changes that do not alter API contracts, financial flows, or data schemas.

| Examples                                          | Approval       | Testing Required               |
|---------------------------------------------------|----------------|--------------------------------|
| Bug fixes (non-financial)                         | Developer       | Unit tests + supply audit      |
| Dependency updates (patch/minor)                  | Developer       | Unit tests + supply audit      |
| UI polish (CSS, copy, layout)                     | Developer       | Visual verification            |
| Documentation updates                             | Developer       | Accuracy review                |
| Log message improvements                          | Developer       | Supply audit post-deploy       |

**Process**: Implement -> Deploy -> Verify supply audit delta=0.0

### 3.2 SIGNIFICANT

Changes that introduce new functionality, alter API behavior, or modify database schemas.

| Examples                                          | Approval        | Testing Required                    |
|---------------------------------------------------|-----------------|-------------------------------------|
| New API endpoints                                 | Commander       | Full API tester (650+ endpoints, ~89 categories) |
| Schema migrations (new Alembic revision)          | Commander       | Migration up/down + full test suite |
| New background task                               | Commander       | Integration test + stress test      |
| New MCP tool                                      | Commander       | MCP bridge verification             |
| Fee calculation changes                           | Commander       | Stress test (16-sim) + supply audit |
| New agent service deployment                      | Commander       | A2A protocol verification           |

**Process**: Planning mode -> Commander approval -> Implement -> Deploy (canary-first: the sandbox frames -> EU -> ASIA -> cloud operators, each step health/version/supply-gated) -> Verify the full API test suite passes + supply delta=0.0

### 3.3 CRITICAL

Security-sensitive changes or fixes to supply-affecting code. May bypass normal planning to address immediate risk.

| Examples                                          | Approval         | Testing Required                    |
|---------------------------------------------------|------------------|-------------------------------------|
| Security vulnerability patch                      | Immediate deploy | Post-deploy review within 24h       |
| Supply invariant fix                              | Immediate deploy | Supply audit (verify delta=0.0)     |
| mTLS/SPIRE configuration change                   | Immediate deploy | Certificate verification            |
| Rate limiting bypass fix                          | Immediate deploy | Stress test verification            |
| Credential rotation                               | Immediate deploy | Service connectivity check          |

**Process**: Deploy immediately -> Post-deploy verification -> Retroactive documentation within 24h

### 3.4 POLICY

Changes to federation-wide economic or governance parameters that affect all registries and agents.

| Examples                                          | Approval                              | Testing Required               |
|---------------------------------------------------|---------------------------------------|--------------------------------|
| Fee rate adjustment (base or max)                 | Governance proposal (66% supermajority) + Commander veto window | Simulation |
<!-- on: staking_rewards -->| Payout curve parameters on locked units (switched off on the production frames) | Governance proposal + Commander veto  | Curve calculation verification |<!-- /on -->
| Enforcement threshold changes                     | Governance proposal + Commander veto  | Affected agent impact analysis |
| New event emission policy                         | Commander (emission policies are critical) | Supply audit               |
| Federation license terms                          | Commander                             | Legal review                   |

**Process**: Governance proposal -> 66% supermajority vote -> 7-day Commander veto window -> Implement -> Deploy -> Verify

---

## 4. Testing Requirements

### 4.1 Test Types

| Test Type       | Tool              | Scope                                    | When Required            |
|-----------------|-------------------|------------------------------------------|--------------------------|
| Unit tests      | pytest / Vitest   | Individual functions, components          | All changes              |
| Integration     | API Tester        | 650+ endpoints (~89 categories), full request/response | SIGNIFICANT and above    |
| Stress test     | EigenTrust 16-sim | ~275 tx/s intra-registry, ~114 tx/s end-to-end, concurrent operations | Financial flow changes   |
| Supply audit    | /supply-audit     | EventStore supply invariant (delta=0.0)   | All changes              |
| Frontend build  | npm build-quick   | Vue compilation, no broken imports        | Frontend changes         |
| Security scan   | Docker scan       | Container image vulnerabilities           | Dependency updates       |

### 4.2 Pass Criteria

| Criterion                          | Threshold                          |
|------------------------------------|------------------------------------|
| API Tester pass rate               | 100% of the full API test suite (650+ endpoints) |
| Supply invariant delta             | 0.0 (zero tolerance)              |
| Stress test error rate             | 0 errors under 16-sim blast        |
| Unit test coverage                 | No regression (existing tests pass) |

---

## 5. Deployment Procedure

### 5.1 Standard Deployment

```
1. Frontend build (if frontend changes):
   cd AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend
   npm run build-quick

2. Docker rebuild:
   docker compose -f docker-compose.production.yml --env-file .env.production up -d --build <service>

3. Health verification:
   docker ps --format "table {{.Names}}\t{{.Status}}"
   # Verify all containers are Up and healthy

4. Supply audit:
   GET /api/v1/projections/supply-audit
   # Verify: status="OK", delta=0.0

5. API test (if SIGNIFICANT+):
   # Run via frontend sidebar -> Run All Tests
   # Verify: the full API test suite passes
```

### 5.2 Multi-Service Deployment

When changes span multiple services (e.g., registry + TEG + EventStore):
1. Deploy in dependency order: EventStore -> TEG -> Registry
2. Verify inter-service connectivity after each step
3. Run full API test suite after all services are up

### 5.3 Database Migration

```
1. Backup current DB state (pg_dump)
2. Apply migration: alembic upgrade head (inside container)
3. Verify migration: alembic current
4. Test affected endpoints
5. Supply audit verification
```

---

## 6. Rollback Procedure

### 6.1 Docker Image Rollback

```
1. Identify previous working image:
   docker images | grep <service>

2. Update docker-compose.production.yml with previous image tag (or git revert)

3. Redeploy:
   docker compose -f docker-compose.production.yml --env-file .env.production up -d <service>

4. Verify health and supply audit
```

### 6.2 Database Migration Rollback

```
1. Identify target revision:
   docker exec <container> alembic history

2. Downgrade:
   docker exec <container> alembic downgrade <revision>

3. Verify schema state and test affected endpoints
```

### 6.3 Nginx Configuration Rollback

```
1. Restore previous nginx config from backup or git
2. Test config: nginx -t
3. Reload: systemctl reload nginx
4. Verify external access to all public endpoints
```

### 6.4 Rollback Decision Criteria

Initiate rollback if any of the following occur post-deploy:
- Supply invariant delta != 0.0
- API tester pass rate drops below 100%
- Any container enters restart loop
- mTLS handshake failures between services
- Financial endpoints returning errors

---

## 7. Version Tracking

| Artifact               | Versioning Method                              | Location                    |
|------------------------|------------------------------------------------|-----------------------------|
| Database schema        | The registry's Alembic migration revisions     | alembic/versions/           |
| Docker images          | SHA digest + build timestamp                   | docker images               |
| Source code            | Git commit history                             | Git repository              |
| Documentation          | Versioned headers (Version, Date, Status)      | PRODUCTION_DOCS/            |
| CLAUDE.md              | Last updated timestamp in header               | Project root                |
| API contracts          | Endpoint count tracking (650+ across ~89 categories, as of June 2026) | API Tester results          |
| Event emission policies| DB table (event_emission_policies)             | Each registry's database    |

---

## 8. Emergency Change Procedure

For P1 incidents (service down, security breach, supply invariant breach):

1. **Assess**: Confirm the incident and identify root cause (or likely cause)
2. **Deploy**: Apply fix immediately without planning mode approval
3. **Verify**: Run supply audit + health checks immediately post-deploy
4. **Notify**: Alert Commander if not already aware
5. **Document**: Create retroactive change record within 24 hours including:
   - Incident description and timeline
   - Root cause analysis
   - Change applied
   - Verification results
   - Preventive measures for recurrence

---

## 9. Change Record Template

Each SIGNIFICANT or higher change should be recorded:

| Field              | Content                                        |
|--------------------|------------------------------------------------|
| Change ID          | Incrementing or date-based identifier          |
| Category           | STANDARD / SIGNIFICANT / CRITICAL / POLICY     |
| Description        | What was changed and why                       |
| Requestor          | Who initiated the change                       |
| Approver           | Who approved (Commander for SIGNIFICANT+)      |
| Date implemented   | Deployment timestamp                           |
| Services affected  | Container names                                |
| Testing performed  | Which test types and results                   |
| Supply audit result| Delta value post-deploy                        |
| Rollback plan      | How to revert if needed                        |

---

## 10. Policy Review

This policy is reviewed quarterly or upon:
- Major infrastructure change (new server, new hosting provider)
- Incident that exposed a gap in the change management process
- Addition of new service categories (e.g., new pillar)
- Changes to the deployment toolchain

---

*End of Change Management Policy v2.1.2*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected the API test-suite size (650+ endpoints), stress figures, migration references and topology to the live system, and made the canary-first fleet rollout explicit in the deployment process. Self-assessed; not independently audited._

_v2.1.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; the rollout order is the sandbox frames, then EU, ASIA and their cloud operators. Self-assessed; not independently audited._

_v2.1.1 (2026-10-16): the status line without an em dash; the federation parameters read as one list where the payout curve is shown. Self-assessed; not independently audited._

_v2.1.2 (2026-10-17): the database schema named as the registry's Alembic migrations, without a stale revision number. Self-assessed; not independently audited._
