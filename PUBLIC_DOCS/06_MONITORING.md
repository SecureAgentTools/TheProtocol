<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/06_monitoring.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Operator Guide: Monitoring
**Audience**: Operators of a frame built from the kit, of a standalone registry, or of a cloud operator
**Checked against the source**: 2026-10-16 (the kit's `templates/frame-test/kit/` (Prometheus, its rules, Alertmanager, Grafana) and its compose; `scripts/distribution/docker-compose.monitoring.yml` and `scripts/distribution/monitoring/`; the operator compose in `scripts/distribution/nginx-templates/`; the registry's and the TEG's `/health` and `/metrics`; the registry's `routers/admin_health.py`)

Every registry serves its own health and metrics. Whether a Prometheus, an Alertmanager and a Grafana come with it depends on how you run it. This page says what each setup ships, what it watches and alerts on, and where to look when you have nothing but the registry.

---

## Overview

| Setup | Monitoring stack | How it runs |
|-------|------------------|-------------|
| A frame built from the kit (`frame-up.py`) | Prometheus, Alertmanager and Grafana, running | inside the frame's own stack, started with it |
| A standalone registry | the same three, as an overlay you add | `docker compose -f docker-compose.standalone.yml -f docker-compose.monitoring.yml --env-file .env.operator up -d` |
| A cloud operator | none in its stack | its registry and TEG serve `/metrics` for a Prometheus you run (A Cloud Operator, below) |

Both the kit and the overlay load the same alert rules (`rules/frames.yml`) and the same Grafana dashboard, Frame Overview.

---

## The Monitoring Stack

### What Prometheus Scrapes

Prometheus scrapes every 15 seconds, evaluates the rules every 30 seconds and keeps 30 days of data (`FT_PROM_RETENTION` in the kit, `PROMETHEUS_RETENTION` in the overlay). Every target carries the labels the rules select on: `component` and `frame`.

| Job (kit name) | Component | What it reads |
|----------------|-----------|---------------|
| `<name>-registry` | `registry` | the registry's `/metrics` |
| `<name>-teg` | `teg` | the TEG's `/metrics`, through its mTLS terminator |
| `<name>-event-store` | `event-store` | the event store's `/metrics`, through its mTLS terminator |
| `<name>-auditor` | `auditor` | the frame's own auditor, which checks the supply invariant independently |
| `<name>-opa` | `opa` | OPA, which the registry consults in shadow mode |
| `<name>-alertmanager`, `<name>-prometheus` | `alertmanager`, `prometheus` | the monitoring stack itself |

In the kit, Prometheus, Alertmanager and OPA serve TLS on the kit's SPIFFE certificate and publish no port on the host; Prometheus answers only clients holding the kit's or the registry's certificate. Grafana is your window. In the overlay, the jobs are named after the compose services (`registry`, `teg-layer`, `event-store`, `auditor`, `opa`), scraped over plain HTTP, and the `frame` label is the fixed word `operator`: change it in `monitoring/prometheus.yml` if several stacks report to one Prometheus.

### Alert Rules

| Alert | Severity | Fires when |
|-------|----------|------------|
| `FrameComponentDown` | warning | the registry, TEG or event store cannot be scraped for 3 minutes |
| `FrameRegistryDown` | critical | the registry cannot be scraped for 10 minutes |
| `FrameSupplyInvariantBreach` | critical | the auditor's verdict is BREACH (`auditor_status` 0) for 5 minutes |
| `FrameAuditorStale` | warning | the auditor has completed no cycle in 4 hours |
| `FrameCardPullSyncStale` | warning | no agent-card pull cycle has completed in 8 hours |
| `FrameBalanceOutboxBacklog` | warning | more than 50 balance events wait in the TEG's outbox to the ledger for 15 minutes |
| `FrameTreasuryLow` | page | the treasury is below its notification floor for 10 minutes |
| `FrameWorkerFailingPersistently` | warning | a background worker has not succeeded in 3 hours and is still failing |
| `FrameFederationPeersUnreachable` | warning | fewer than 90% of the federation peers are reachable for 30 minutes |
| `FrameOpaDown` | warning | OPA cannot be scraped for 5 minutes |
| `FrameOpaShadowMismatch` | warning | OPA disagreed with the registry's own decision in the last 30 minutes |
| `FrameOpaQueryErrors` | warning | more than 5% of the registry's OPA queries got no decision for 15 minutes |

### Alertmanager

Alerts are grouped by alert name, frame and severity. `page` and `critical` go to the receiver `page` (repeated every hour), `warning` to the receiver `warning`, and anything else to `everything-else` (repeated every 4 hours).

**The three receivers ship without a destination**: an alert fires and shows in Alertmanager, but nobody is notified until you add an email, webhook or other target to each receiver. Edit `kit/alertmanager/alertmanager.yml` in the frame's stack directory (kit) or `monitoring/alertmanager.yml` (overlay), then restart Alertmanager (`docker restart <name>-alertmanager`).

### Grafana

Grafana is provisioned with Prometheus as its data source and the Frame Overview dashboard, in six rows: Availability (registry, TEG, event store; request rate, p95 latency, 5xx ratio), Money (the auditor's delta, verdict and cycle age, TEG transfers, the balance outbox, the registry's own supply-audit delta), Ledger (events ingested, ledger freshness, agents in the ledger), Federation (peers known and reachable, the age of the last card pull, SVID bundle roots), Workers (workers failing persistently, worker cycles by outcome) and OPA (shadow decisions, mismatches, query errors, latency). Its panel for operators shows no data on a kit frame: the kit's Prometheus scrapes the frame's own services, not its operators.

- **Kit frame**: Grafana listens on a socket that the frame's edge container publishes on the host's loopback. `docker port <name>-nginx-edge 3000` shows the port; reach it through an SSH tunnel. The user is `admin`; the password is `FT_GRAFANA_ADMIN_PASSWORD` in the stack's `.env.frame-test`.
- **Overlay**: `127.0.0.1:3000` (`GRAFANA_HTTP_PORT`), with Prometheus on `127.0.0.1:9090` and Alertmanager on `127.0.0.1:9093`. The user is `GRAFANA_ADMIN_USER` (`admin` by default); `GRAFANA_ADMIN_PASSWORD` must be set in the env file.

Sign-up and usage reporting are off in both.

---

## A Cloud Operator

The operator stack ships no Prometheus, and the frame's kit Prometheus does not scrape its operators. Run one beside the stack: the registry serves `/metrics` on port 8000 and the TEG on port 8080, on the stack's own network (compose services `registry` and `teg-layer`). The repository's `docker-compose.monitoring.yml` and `monitoring/` work as an overlay of the operator compose once you remove the `event-store`, `auditor` and `opa` jobs from `monitoring/prometheus.yml`: an operator runs none of them, and their empty targets would keep `FrameComponentDown` firing. The minimal scrape configuration:

```yaml
scrape_configs:
  - job_name: 'registry'
    static_configs:
      - targets: ['registry:8000']
        labels: { component: 'registry', frame: '<your registry name>' }
  - job_name: 'teg-layer'
    static_configs:
      - targets: ['teg-layer:8080']
        labels: { component: 'teg', frame: '<your registry name>' }
```

The frame's own monitoring watches the ledger your registry writes to; ask your frame if you see a ledger or supply problem.

---

## Health Check Endpoints

| Service | Address | Answer |
|---------|---------|--------|
| Registry | `GET /health`, port 8000 in the container, or your public address | `{"status": "ok", "event_store": {...}}`; on an image built by the kit's `build.sh` also `build` (the kit version and the source digest) |
| TEG | `GET /health`, port 8080 in the operator and standalone stacks (a socket on a kit frame) | `status` (`healthy`, or `degraded` when the database check fails), `service`, `version`, `environment`, `checks.database` (with its latency), `checks.configuration`, `checks.event_store`, and `mtls`, `federation_licence` and `ledger` (the ledger gate's mode and reading) |
| nginx-federation, nginx-teg | `GET /health` on port 8080 inside the container (8443 is the mTLS listener) | `200` |

The registry's `event_store` block repeats part of its configuration (`enabled`, `source_service`, `events_supported`; not the store's address); it does not test the store. To see whether the registry reaches its ledger, ask `GET /api/v1/public/supply-invariant`: `"source": "eventstore"` with a delta means it does, `"source": "unreachable"` with `"status": "UNKNOWN"` means it does not.

```bash
curl -s https://<your-registry>/health
curl -s https://<your-registry>/api/v1/public/supply-invariant
```

---

## Application Metrics

The registry and the TEG serve `/metrics` in Prometheus text format. The registry serves it on its own address, to whoever can reach that address, unless its `METRICS_ENABLED` is `false` (chapter 02): then the route does not exist and nothing can scrape the registry, your own Prometheus included, so remove the registry's job from the scrape configuration as well, or `FrameComponentDown` reports the registry down. To keep the metrics for your Prometheus alone, leave the switch on and refuse `/metrics` at the reverse proxy in front of the registry: the kit's Prometheus scrapes the registry on the frame's own network, not through the console's address.

Both carry the request metrics of `prometheus-fastapi-instrumentator`, among them `http_requests_total` and `http_request_duration_seconds`, labelled with the route (`handler`), the method and the status class (`2xx`, `4xx`, `5xx`). `/metrics`, `/health` and the API docs are not counted.

Beside them, each service exports its own metrics. The ones the rules and the dashboard read:

| Service | Metrics |
|---------|---------|
| Registry | `worker_last_success_unixtime`, `worker_cycles_total`, `agent_card_pullsync_last_cycle_unixtime`, `federation_peers_total`, `federation_peers_reachable_ratio`, `registry_svid_bundle_roots`, `registry_treasury_low_active`, `supply_audit_last_delta`, `opa_decisions_total`, `opa_decision_latency_seconds` |
| TEG | `teg_balance_outbox_backlog`, `teg_transfer_amount_avt` |
| Event store | `eventstore_events_ingested_total`, `eventstore_ledger_freshness_seconds`, `eventstore_unique_agents` |
| Auditor | `auditor_delta`, `auditor_status` (1 OK, 0 breach or error), `auditor_last_cycle_age_seconds` |

---

## Docker Health Monitoring

```bash
# Container status (operator stack; on a kit frame use -f docker-compose.frame-test.yml --env-file .env.frame-test in its stack directory)
docker compose -f docker-compose.operator.yml --env-file .env.operator ps

# The registry's last 50 lines, or follow them
docker logs <name>-registry --tail 50
docker logs <name>-registry -f

# Resource use of every container
docker stats --no-stream

# The host CLI's checks (chapter 12): an operator stack, or a kit frame's stack directory
tp-operator doctor
tp-operator --frame <stack directory> doctor
```

---

## Log Format

The registry writes plain text: one line per record, `<time> - <logger> - <LEVEL> - <message>`, plus gunicorn's access lines. The TEG writes its own records as JSON-shaped lines by default (`LOG_FORMAT`, `json` or `text`): `{"time": ..., "level": ..., "name": ..., "message": ..., "app_name": ..., "app_version": ..., "environment": ...}`. The message inside is not escaped, so search the lines rather than parse them:

```bash
docker logs <name>-registry --since 1h 2>&1 | grep -E ' - (ERROR|CRITICAL) - '
docker logs <name>-teg --since 1h 2>&1 | grep -F '"level": "ERROR"'
```

---

## What Your Registry Already Ships In-App

The registry watches itself and shows it in the console and through admin routes, all with the admin flag `admin_platform`:

| Endpoint | What it shows |
|----------|---------------|
| `GET /api/v1/admin/dashboard` | platform totals: developers, agents, activity |
| `GET /api/v1/admin/workers/status` | every background worker, its leadership and its last run |
| `GET /api/v1/admin/workers/vitals` | each worker's verdict and its last error (what `FrameWorkerFailingPersistently` points to) |
| `GET /api/v1/admin/reactor/status` | the event reactors: health and lag per reactor |
| `GET /api/v1/admin/health-check` | a short health summary of the registry |
| `GET /api/v1/admin/system-resources` | CPU, memory and disk as the container sees them |
| `GET /api/v1/admin/docker-stats` | resource use per container; `503` where the registry holds no Docker socket, as on an operator stack |
| `GET /api/v1/admin/system-activity` | recent activity from the ledger |

The console shows the same data on its health monitor (`#/health-monitor`), the reactor page (`#/admin/reactors`) and the Federation view (`#/federation`). An assistant connected over MCP (the AI Assistants chapter, operator chapter 13) can read the same routes and summarize them on demand.
