# Incident Response Procedures
**Version**: 2.1.3
**Status**: DRAFT: self-assessment (not independently audited)
**Last Updated**: 2026-10-17
**Contact**: SecurityAlerts@theprotocol.cloud

---

## Table of Contents

1. [Purpose](#purpose)
2. [Incident Classification](#incident-classification)
3. [Detection Mechanisms](#detection-mechanisms)
4. [Response Procedures](#response-procedures)
5. [Communication Matrix](#communication-matrix)
6. [Post-Incident Process](#post-incident-process)
7. [Runbook Quick Reference](#runbook-quick-reference)

---

## Purpose

This document defines how TheProtocol classifies, detects, responds to, and learns from security and operational incidents. All personnel with production access must be familiar with these procedures.

The primary objectives are:

1. **Protect supply integrity**: the unit ledger must never enter a state where delta != 0.0
2. **Minimize service disruption**: restore operations within defined SLA windows
3. **Preserve evidence**: logs, snapshots, and event records must be captured before remediation
4. **Prevent recurrence**: every incident produces monitoring improvements

---

## Incident Classification

| Priority | Severity | Response Time | Resolution Target | Examples |
|----------|----------|--------------|-------------------|----------|
| P1 CRITICAL | System integrity at risk | Immediate (< 15 min) | 4 hours | Supply invariant breach (delta != 0.0), mTLS CA compromise, EventStore data corruption, unauthorized issuance detected, complete platform outage |
| P2 HIGH | Service degradation or operator impact | < 1 hour | 8 hours | Operator quarantine triggered, mass dispute wave (> 10 in 1 hour), EventStore unavailable, federation sync failure (all peers), database replication failure |
| P3 MEDIUM | Single component affected | < 4 hours | 24 hours | Agent enforcement action, single peer sync failure, certificate rotation failure, PgBouncer pool exhaustion, single container crash loop |
| P4 LOW | Informational or self-resolving | < 24 hours | 72 hours | Rate limiting triggered, ZKP verification rejection (single), health check flap, EigenTrust convergence slow, disk usage warning |

### Escalation Rules

- Any P4 recurring 3+ times in 24 hours escalates to P3
- Any P3 affecting multiple components escalates to P2
- Any incident involving unit balance discrepancy automatically escalates to P1
- Commander may override classification at any time

---

## Detection Mechanisms

### Automated Detection

| Mechanism | Cycle | Scope | Alert Channel | Triggers |
|-----------|-------|-------|--------------|----------|
| Supply Auditor | 60 seconds | EventStore projection vs issuance | P1 immediate | delta != 0.0 |
| Prometheus + vmalert | 15-second scrape, vmalert rule evaluation | All containers, host metrics | SecurityAlerts@theprotocol.cloud via Alertmanager | more than 90 alerting rules, evaluated by vmalert (CPU, memory, disk, container health, response latency, error rates, supply/economic invariants) |
| CrowdSec | Continuous | Network traffic, application logs | CrowdSec console + firewall bouncer | Community threat intelligence matches, brute-force patterns, known bad IPs |
| fail2ban | Continuous | SSH logs | Automatic IP ban | 5 failed SSH attempts in 10 minutes |
| EigenTrust Collusion Worker | Daily | Agent interaction graph | Admin dashboard flag | Tarjan SCC detection, cosine similarity anomalies |
| A2A Payment Expiry Worker | 60 seconds | Payment authorization store | Application log | Stale payment authorizations cleaned, anomalous accumulation of authorizations flagged |
<!-- on: staking_rewards -->| Payout Distributor (locked units) | Daily | Lock positions | Application log | Switched off on the production frames (pays nothing, records a skip); where a registry switches payouts on, circuit breaker activation at a 75% locked share |<!-- /on -->
| Federation Sync | Configurable | Peer registry health | Application log + Prometheus | Peer unreachable, sync delta exceeds threshold |

### Manual Detection

| Method | Access | Use Case |
|--------|--------|----------|
| Admin Dashboard | `api.theprotocol.cloud/ui#/federation` (Operators tab) | Operator health, federation status, quarantine state |
| EventStore Query | MCP tool: `adminQueryEventStore` | Audit trail investigation, event sequence analysis |
| Docker Logs | `docker logs <container> --tail 50` | Container-level debugging, error trace |
| monitor.sh | `./monitor.sh` (tmux 6-pane) | Live multi-service log dashboard |
| Grafana | `grafana.theprotocol.cloud` | Historical metrics, dashboard correlation |
| Supply Audit Endpoint | `GET /api/v1/projections/supply-audit` (EventStore) | On-demand supply integrity check |
| Lynis | `lynis audit system --quick` | Host security posture assessment |

---

## Response Procedures

### P1 CRITICAL: Immediate Response

**Objective**: Contain, preserve evidence, restore integrity.

```
Timeline: 0-15 minutes (detection to containment)
```

1. **Verify the alert.** Confirm the incident is genuine, not a false positive.
   - Supply breach: `GET /api/v1/projections/supply-audit`, then check the delta value
   - Service outage: `docker ps`, then check the container states
   - Unauthorized access: review Alertmanager notification + CrowdSec decisions

2. **Contain the affected service** (if supply integrity is at risk):
   ```
   docker stop <implicated service>          # halts further writes from it (e.g. agentvault_teg_layer_a)
   POST /api/v1/admin/canary/fleet/pause     # pause synthetic canary traffic fleet-wide
   ```
   There is no single global "lockdown" endpoint; containment is per-service (stop the implicated container) plus pausing the canary fleet. This prevents further state change while you investigate.

3. **Notify Commander immediately.**
   Direct contact (SMS/call). Do not wait for email acknowledgment.

4. **Isolate affected containers:**
   ```bash
   docker stop <affected_container>
   ```
   If lateral spread is suspected:
   ```bash
   docker network disconnect agentvault_network <container>
   ```

5. **Preserve evidence** (before any remediation):
   ```bash
   docker logs <container> > /opt/theprotocol/stack/incident_logs/<container>_$(date +%s).log 2>&1
   docker exec agentvault_event_store_db pg_dump -U eventstore eventstore_db > /opt/theprotocol/stack/incident_logs/es_dump_$(date +%s).sql
   ```
   Take EventStore projection snapshot:
   ```
   POST /api/v1/admin/projection-snapshot   (Registry admin)
   ```

6. **Root cause analysis**: begin within 1 hour, complete within 4 hours.

7. **Remediate and verify:**
   - Apply fix (code patch, config change, container rebuild)
   - Verify supply audit: `GET /api/v1/projections/supply-audit` (delta must be 0.0)
   - Verify affected services operational: run targeted API tests
   - Lift circuit breaker if activated

8. **Post-incident report** within 24 hours (see Post-Incident Process).

### P2 HIGH: Urgent Response

**Objective**: Scope impact, contain spread, remediate within SLA.

```
Timeline: 0-60 minutes (detection to active response)
```

1. **Identify affected scope:**
   - Which frame (EU, ASIA, or both)?
   - Which operator (if federation-related)?
   - Which service (TEG, EventStore, Registry)?
   - How many users/agents impacted?

2. **Notify affected operators** via SecurityAlerts@theprotocol.cloud with:
   - Incident summary
   - Estimated impact
   - Expected resolution timeline

3. **Isolate if spreading:**
   ```bash
   docker network disconnect agentvault_network <container>
   ```
   For federation issues, consider temporary peer disconnection.

4. **Remediate within 4 hours:**
   - Apply targeted fix
   - Rebuild affected containers if necessary:
     ```bash
     docker compose -f docker-compose.production.yml --env-file .env.production up -d --build <service>
     ```

5. **Verify supply integrity:**
   ```
   GET /api/v1/projections/supply-audit
   ```
   Delta must be 0.0 after any financial-path incident.

6. **Update monitoring** if a detection gap was identified during the incident.

### P3 MEDIUM: Standard Response

**Objective**: Investigate and fix within SLA, prevent escalation.

1. Log the incident with timestamp, affected component, and symptoms.
2. Investigate root cause using logs, metrics, and EventStore queries.
3. Apply fix and verify.
4. Document in session log (`sessionlogs2026/`).
5. Review in weekly batch if pattern emerges.

### P4 LOW: Monitoring Response

**Objective**: Track and batch-review.

1. Log the event automatically (Prometheus/application logs).
2. No immediate action required unless escalation criteria met.
3. Review in weekly operations review.
4. Update alert thresholds if generating excessive noise.

---

## Communication Matrix

| Audience | Channel | P1 | P2 | P3 | P4 |
|----------|---------|----|----|----|----|
| Commander | Direct (SMS/call) | Immediate | < 1 hour | Daily summary | Weekly summary |
| Federated Operators | SecurityAlerts@theprotocol.cloud | < 30 min | < 2 hours | If affected | N/A |
| Developers (platform users) | In-app notification | < 1 hour | If feature affected | N/A | N/A |
| Public | Status page (future) | If extended outage (> 1 hour) | N/A | N/A | N/A |

### Communication Templates

**P1 Notification (to Operators):**
```
Subject: [P1 CRITICAL] TheProtocol Incident: {brief description}

Incident detected: {timestamp UTC}
Affected: {component/service}
Impact: {description of user-facing impact}
Status: {INVESTIGATING / CONTAINED / RESOLVED}
Next update: {time}

TheProtocol Security Team
SecurityAlerts@theprotocol.cloud
```

**P2 Notification (to Operators):**
```
Subject: [P2 HIGH] TheProtocol Service Advisory: {brief description}

Issue detected: {timestamp UTC}
Affected: {component/service}
Impact: {description}
ETA to resolution: {estimate}

TheProtocol Operations
SecurityAlerts@theprotocol.cloud
```

---

## Post-Incident Process

Every P1 and P2 incident requires a post-incident review. P3 incidents are reviewed if they recur or escalate.

### 1. Root Cause Analysis (5 Whys)

Document the causal chain from symptom to root cause. Example:

```
Why did delta != 0.0?
  Because a duplicate TokensTransferred event was recorded.
Why was it duplicated?
  Because the idempotency key was not set on the cross-registry path.
Why was it missing?
  Because the new endpoint bypassed the standard transfer flow.
Why did it bypass the standard flow?
  Because the developer created a parallel TEG admin call.
Why was that possible?
  Because the code review did not check the rule that new financial flows use the existing transfer endpoints.

Root cause: Code review gap for financial flow compliance.
```

### 2. Corrective Action Plan

| Action | Owner | Deadline | Verification |
|--------|-------|----------|-------------|
| {specific fix} | {name} | {date} | {how to verify} |
| {monitoring addition} | {name} | {date} | {alert test} |
| {process improvement} | {name} | {date} | {review method} |

### 3. Documentation Updates

- Update `PRODUCTION_DOCS/` if architecture or operational procedures changed
- Update `CLAUDE.md` if new operational rules emerged
- Update Risk Assessment Framework if new risk identified or scores changed
- Add session log entry in `sessionlogs2026/`

### 4. Monitoring Rule Addition

Every P1/P2 incident must produce at least one new or refined monitoring rule to prevent recurrence. The rule must be:

- Deployed to Prometheus/Alertmanager
- Tested with a synthetic trigger
- Documented in `PRODUCTION_DOCS/07_MONITORING/`

### 5. Tabletop Exercise

Quarterly tabletop exercises simulate incident scenarios to validate procedures. Scenarios rotate through:

- Supply invariant breach (unit issuance exploit)
- Federation operator compromise
- Complete server failure and recovery
- Credential leak and rotation
- Mass Sybil attack on governance

---

## Runbook Quick Reference

### Verify Supply Integrity
```bash
# Via EventStore API
curl -s http://localhost:8200/api/v1/projections/supply-audit | python3 -m json.tool

# Via MCP
# Use adminQueryEventStore with path="/api/v1/projections/supply-audit"
```

### Emergency Container Operations
```bash
# Stop a specific service
docker stop agentvault_registry_a

# Restart with rebuild
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build registry-a

# View recent logs
docker logs agentvault_registry_a --tail 100 --since 5m

# Full log dump for evidence
docker logs agentvault_registry_a > /opt/theprotocol/stack/incident_logs/registry_a_$(date +%s).log 2>&1
```

### Database Emergency Backup
```bash
# Registry A
docker exec agentvault_registry_db_a pg_dump -U postgres agentvault_registry_a > /opt/theprotocol/stack/incident_logs/reg_a_$(date +%s).sql

# EventStore
docker exec agentvault_event_store_db pg_dump -U postgres eventstore > /opt/theprotocol/stack/incident_logs/es_$(date +%s).sql
```

### CrowdSec Emergency Actions
```bash
# List active decisions (bans)
cscli decisions list

# Ban an IP immediately
cscli decisions add --ip <IP> --reason "Incident response" --duration 24h

# List recent alerts
cscli alerts list --since 1h
```

### Federation Emergency Isolation
```bash
# Disconnect a specific registry from the network
docker network disconnect agentvault_network agentvault_registry_b

# Reconnect after remediation
docker network connect agentvault_network agentvault_registry_b
```

---

*End of Incident Response Procedures*
*Cross-reference: Risk_Assessment_Framework.md, CLAUDE.md (Operational Doctrine)*

---

_v2.0.0 (2026-06-12): accuracy overhaul — corrected alerting-rule count (60+ via Prometheus/vmalert), detection and monitoring detail, and topology to the live system. Self-assessed; not independently audited._

_v2.1.0 (2026-10-03): wording follows the live network and the agreed public terms: the platform's units named as units (ECU on EU, ACU on ASIA), the production network named as the EU and ASIA frames with four cloud operators, votes counted by membership or by locks as each registry is set, and every surface that is switched off on the production frames named as switched off; the runbook commands in section 11 still name the containers of the retired first frames and are scheduled for their own revision. Self-assessed; not independently audited._

_v2.1.1 (2026-10-16): the text without em dashes or double-hyphen dashes: the objectives, the four response headings, the response steps and the notification templates read with colons, commas or parentheses. Self-assessed; not independently audited._

_v2.1.2 (2026-10-17): the root-cause example names the rule the review missed (new financial flows use the existing transfer endpoints) in place of a wrong rule number. Self-assessed; not independently audited._

_v2.1.3 (2026-10-17): the detection table counts the alerting rules as vmalert evaluates them (more than 90; Prometheus only scrapes). Self-assessed; not independently audited._
