# Compliance Audit Procedures

| Field       | Value                          |
|-------------|--------------------------------|
| Version     | 2.2.2                          |
| Status      | DRAFT: self-assessment (not independently audited) |
| Date        | 2026-10-17                     |
| Owner       | Commander ruFFa                |
| Review Cycle| Quarterly                      |

---

## 1. Purpose

This document defines the audit cadences, procedures, and evidence collection methods used to verify TheProtocol's ongoing compliance with its own policies, ISO 42001 requirements, and operational commitments. Audits range from real-time automated checks to quarterly manual reviews.

---

## 2. Automated Continuous Audits

These audits run without human intervention and raise alerts on failure.

| Audit                    | Frequency | Component                 | Alert Mechanism                        | Pass Criterion                     |
|--------------------------|-----------|---------------------------|----------------------------------------|------------------------------------|
| Supply invariant         | 60 seconds| supply_auditor.py         | Prometheus alert -> Alertmanager email | delta = 0.0 (zero tolerance)       |
| Container health         | 10 seconds| Docker healthchecks       | Prometheus container_up metric         | All containers UP                  |
| Certificate rotation     | 5 minutes | SPIRE agent               | SVID expiry metric                     | SVID TTL > 0                       |
| Rate limiting            | Real-time | Redis shared counters     | 429 response logging                  | No bypass detected                 |
| A2A payment authorization expiry | 60 seconds| a2a_payment_expiry.py     | Expired token count metric             | Stale payment authorizations cleaned       |
| Leader election          | Heartbeat | Redis-based leader.py     | Leader loss metric                     | Exactly 1 leader per task          |
| WebSocket metrics        | Continuous| ws_metrics background task| Connection count, message throughput   | No stale connections               |

---

## 3. Daily Audits

| Audit                      | Responsible     | Procedure                                              | Evidence Location                    |
|----------------------------|-----------------|--------------------------------------------------------|--------------------------------------|
| Collusion detection        | Automated       | Tarjan SCC on directed trust graph; flag rings with >=75% internal ratio | AuditorFlagLog table (registry DB) |
| Bayesian trust decay       | Automated       | Inactivity decay applied to peer registry discounts    | PeerRegistry.bayesian_discount       |
<!-- on: staking_rewards -->| Payout distribution (locked units) | Automated       | Switched off on the production frames (the distributor pays nothing and records a skip); where a registry switches payouts on, calculate and make the payouts per lock position | RewardsDistributed events (ES)       |<!-- /on -->
| A2A payment authorization cleanup | Automated       | Expire payment authorizations past TTL, mark EXPIRED           | a2a_payment_authorizations table     |
| Settlement reconciliation  | Automated       | Verify pending settlements resolved within timeout     | Saga coordination store              |

---

## 4. Weekly Audits

| Audit                        | Responsible  | Procedure                                                 | Evidence Location                    |
|------------------------------|--------------|-----------------------------------------------------------|--------------------------------------|
| Security audit log review    | Commander    | Review security_audit_logs table for anomalies            | security_audit_logs (registry DB)    |
| Federation sync health       | Commander    | Check peer_registries status, last_synced timestamps      | peer_registries table, container logs|
| Prometheus alert review      | Commander    | Review fired alerts for the week in Alertmanager          | Alertmanager UI / API                |
| CrowdSec threat review       | Commander    | `cscli alerts list` and `cscli decisions list`            | CrowdSec local DB                    |
| fail2ban status              | Commander    | `fail2ban-client status sshd`                             | fail2ban logs                        |

---

## 5. Monthly Audits

| Audit                        | Responsible  | Procedure                                                 | Evidence Location                    |
|------------------------------|--------------|-----------------------------------------------------------|--------------------------------------|
| Full API test suite          | Commander    | Run the full API test suite (650+ endpoints, ~89 categories) via the API Tester | API Tester results (frontend)      |
| Stress test                  | Commander    | EigenTrust 16-sim nuclear blast test                      | Stress test output logs              |
| Capacity review              | Commander    | Check CPU/RAM/disk utilization against thresholds         | Prometheus / Grafana dashboards      |
| Docker image vulnerability scan | Commander | `docker scan` or equivalent on all custom images          | Scan reports                         |
| Credential rotation review   | Commander    | Verify no credentials older than rotation policy          | .env.production audit                |
| Event emission policy review | Commander    | GET /api/v1/admin/event-emission-policies; verify 32 policies match expected | API response |

---

## 6. Quarterly Audits

| Audit                          | Responsible  | Procedure                                                | Evidence Location                    |
|--------------------------------|--------------|----------------------------------------------------------|--------------------------------------|
| Risk assessment review         | Commander    | Review and update Risk_Assessment_Framework.md           | PRODUCTION_DOCS/11_COMPLIANCE/       |
| Tabletop exercise              | Commander    | Simulate P1 scenario (supply breach, key compromise, etc.) and walk through response | Exercise report |
| Documentation accuracy review  | Commander    | Verify PRODUCTION_DOCS match actual system behavior      | PRODUCTION_DOCS/ vs live system      |
| CLAUDE.md update               | Commander    | Update CLAUDE.md to reflect current container count, tool count, migration count | CLAUDE.md |
| Sub-processor review           | Commander    | Verify sub-processor list is current and DPIAs valid     | Data_Protection_Policy.md            |
| DPIA refresh                   | Commander    | Review completed DPIAs, update if processing changed     | DPIA records                         |

---

## 7. ISO 42001 Self-Assessment Checklist

| Clause | Question | Evidence Location | Status |
|--------|----------|-------------------|--------|
| 4: Context of the organization | Are interested parties and their requirements identified? | PRODUCTION_DOCS/01_SYSTEM_OVERVIEW/ | DRAFT |
| 5: Leadership | Is there a documented AI policy with management commitment? | ISO_42001_Alignment.md (Section 5.2, AI Policy), this document | DRAFT |
| 6: Planning | Are AI risks identified and assessed? | Risk_Assessment_Framework.md | DRAFT |
| 7: Support | Are resources, competence, and awareness documented? | CLAUDE.md, PRODUCTION_DOCS/09_DEVELOPER_GUIDES/ | DRAFT |
| 8: Operation | Are AI system development and deployment processes defined? | Change_Management_Policy.md, AI_System_Lifecycle.md | DRAFT |
| 9: Performance evaluation | Are monitoring and audit procedures in place? | This document, Prometheus/Grafana | DRAFT |
| 10: Improvement | Is there a non-conformity and corrective action process? | Section 10 of this document | DRAFT |
| A.2: AI impact assessment | Are impact assessments conducted for AI components? | Data_Protection_Policy.md (DPIA section) | DRAFT |
| A.3: AI system lifecycle | Are lifecycle stages documented for each AI component? | AI_System_Lifecycle.md | DRAFT |
| A.4: Data management | Is data classification and handling documented? | Data_Protection_Policy.md | DRAFT |

---

## 8. Evidence Collection Guide

### 8.1 Evidence Sources

Recent executed deep-audit records (evidence the programme is practiced, not aspirational): the user-funds conservation audit (2026-06-09, `sessionlogs2026/SESSION_LOG_2026-06-09_USER_FUNDS_CONSERVATION_AUDIT.md`), the shadow-bookkeeping audit (2026-06-10, `sessionlogs2026/SHADOW_BOOKKEEPING_AUDIT_2026-06-10.md`), and the compliance-documentation accuracy audit (2026-06-12, `sessionlogs2026/SESSION_LOG_2026-06-12_COMPLIANCE_ZKP_DOCS.md`).

| Evidence Type          | Source                           | Access Method                              | Retention            |
|------------------------|----------------------------------|--------------------------------------------|----------------------|
| Financial events       | EventStore                       | GET /api/v1/events/ (internal network)     | Immutable, permanent |
| Supply audit results   | EventStore                       | GET /api/v1/projections/supply-audit       | Point-in-time query  |
| Performance metrics    | Prometheus                       | PromQL queries, Grafana dashboards         | 30 days hot (Prometheus), 60 days cold (VictoriaMetrics) |
| Container logs         | Docker daemon                    | `docker logs <container>` or ./monitor.sh  | Per Docker config    |
| Policy documents       | PRODUCTION_DOCS/                 | File system, Git history                   | Git versioned        |
| Code changes           | Git repository                   | `git log`, `git diff`                      | Permanent            |
| Incident records       | Alertmanager                     | Alertmanager API / UI                      | Configurable         |
| Security events        | security_audit_logs table        | SQL query via docker exec                  | Persistent           |
| API test results       | Frontend API Tester              | Browser / screenshot                       | Per-run              |
| Reputation data        | Registry DB                      | agent_reputation table                     | Persistent           |
| Audit flags            | Registry DB                      | AuditorFlagLog table                       | Persistent           |

### 8.2 Evidence Preservation

For audit purposes, evidence should be:
- **Timestamped**: All events, metrics, and logs include UTC timestamps
- **Immutable**: EventStore events cannot be modified after creation
- **Attributable**: Events include agent DIDs, developer IDs, or system identifiers
- **Exportable**: All evidence sources support programmatic export (API, SQL dump, file copy)

---

## 9. External Audit Preparation

### 9.1 Auditor Access Provisioning

| Access Level           | Method                                    | Scope                                      |
|------------------------|-------------------------------------------|--------------------------------------------|
| Read-only API key      | `POST /api/v1/auth/api-keys` (scoped)    | Public endpoints, discovery, network stats |
| EventStore query       | Read-only access via adminQueryEventStore | Event history, supply audit, projections   |
| Grafana viewer         | Grafana viewer role (no edit)             | Dashboards, metrics visualization          |
| Documentation export   | File system copy of PRODUCTION_DOCS/      | All policy and architecture documents      |

### 9.2 Auditor Access Restrictions

- No admin access (no treasury operations, no emission policy changes)
- No write access to any database
- No Docker exec or container shell access
- No access to .env.production or credential files
- No access to SPIRE private keys or JWT signing secrets

### 9.3 Audit Package Preparation

When preparing for an external audit, assemble:

1. **Policy documents**: All files from PRODUCTION_DOCS/11_COMPLIANCE/
2. **Architecture overview**: PRODUCTION_DOCS/01_SYSTEM_OVERVIEW/ and 02_ARCHITECTURE/
3. **Supply audit snapshot**: Current output of /api/v1/projections/supply-audit
4. **API test results**: Latest full API test-suite run (650+ endpoints; screenshot or export)
5. **Stress test results**: Latest EigenTrust 16-sim output
6. **Incident log**: Alertmanager history for the audit period
7. **Change log**: Git history for the audit period
8. **Sub-processor list**: Current Data_Protection_Policy.md Section 10

---

## 10. Non-Conformity Handling

### 10.1 Process

```
1. LOG:         Record the non-conformity with timestamp, description, and discoverer
2. CLASSIFY:    Severity: CRITICAL (supply breach, security) / MAJOR (compliance gap) / MINOR (documentation)
3. ASSIGN:      Designate owner (Commander for CRITICAL/MAJOR)
4. REMEDIATE:   Implement corrective action
5. VERIFY:      Confirm fix via appropriate test (supply audit, API test, manual review)
6. CLOSE:       Document resolution and close the non-conformity record
7. UPDATE:      Update risk register and relevant policies if the root cause reveals a systemic gap
```

### 10.2 Severity Response Times

| Severity  | Initial Response | Remediation Target | Review Required |
|-----------|------------------|--------------------|-----------------|
| CRITICAL  | 1 hour           | 24 hours           | Post-incident within 7 days |
| MAJOR     | 24 hours         | 7 days             | Next quarterly review |
| MINOR     | 7 days           | 30 days            | Next quarterly review |

### 10.3 Non-Conformity Register

Maintained as a running log with fields:
- NC-ID, Date discovered, Severity, Description, Root cause, Owner, Remediation action, Date resolved, Verification method, Preventive measure

---

## 11. Continuous Improvement

Findings from all audit types feed into:
- **Risk register updates** (Risk_Assessment_Framework.md)
- **Policy revisions** (versioned headers track changes)
- **CLAUDE.md updates** (operational doctrine reflects current reality)
- **Alerting rule improvements** (new Prometheus rules for detected gaps)
- **Training materials** (developer guide updates for recurring issues)

---

## 12. Policy Review

This document is reviewed quarterly or upon:
- Completion of an external audit
- Discovery of a CRITICAL non-conformity
- Significant change to system architecture
- Regulatory change affecting audit requirements

---

*End of Compliance Audit Procedures v2.2.2*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected API test-suite size (650+ endpoints across ~89 categories), audit references and counts to the live system. Self-assessed; not independently audited._

_v2.1.0 (2026-06-12): added executed deep-audit records to §8.1 (evidence for ISO 42001 clause 9.2)._

_v2.2.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; the header now carries the version of the latest note. Self-assessed; not independently audited._

_v2.2.1 (2026-10-16): the text without em dashes: the checklist names each clause with a colon, and the non-conformity steps and the emission policy review read without a dash. Self-assessed; not independently audited._

_v2.2.2 (2026-10-17): the checklist's improvement row points at section 10, and the metrics retention reads as configured (30 days in Prometheus, 60 days in VictoriaMetrics). Self-assessed; not independently audited._
