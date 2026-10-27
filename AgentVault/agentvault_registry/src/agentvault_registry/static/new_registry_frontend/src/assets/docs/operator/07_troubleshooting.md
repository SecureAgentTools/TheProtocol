# Operator Guide: Troubleshooting
**Audience**: Operators running the bundle's operator stack or a frame built from the kit, on their own host
**Checked against the source**: 2026-10-16 (the operator compose and its env generator in `scripts/distribution/nginx-templates/`; the kit's `templates/frame-test/docker-compose.frame-test.yml.tmpl` and `frame-test.env.tmpl`; the registry's `core/federation_auth.py`, `background_tasks/federation_sync.py`, `routers/onboarding.py`, `routers/staking_enhanced.py`, `routers/teg_integration.py` and `middleware/readonly_mode.py`; the event store's `routers/events.py`)

The commands below use the names the two stacks give their containers: `<name>-<role>`, where `<name>` is your registry's name (`REGISTRY_NAME`).

| Stack | Compose command, run in the stack's directory | Services |
|-------|-----------------------------------------------|----------|
| Operator stack | `docker compose -f docker-compose.operator.yml --env-file .env.operator ...` | `registry`, `teg-layer` (container `<name>-teg`), `db`, `teg-db`, `pgbouncer`, `redis`, `spire-agent`, `cert-writer`, `nginx-federation`, `nginx-teg` |
| Kit frame | `docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test ...` | named like their containers: `<name>-registry`, `<name>-teg`, `<name>-event-store`, ... |

Always pass the env file. The compose file reads the database passwords and keys from it; `up` without it recreates containers with blank values and the stack stops working.

---

## Common Issues

| # | Symptom | Cause | Fix |
|---|---------|-------|-----|
| 1 | The SPIRE agent does not start | its x509pop certificate or key is missing, unreadable or expired | `docker logs <name>-spire-agent` says which. Check that `spire/agent-attestation.crt` and `spire/agent-attestation.key` are in place and readable; `openssl x509 -enddate -noout -in spire/agent-attestation.crt` shows the expiry (the provisioner issues them for two years). The certificate survives restarts, so a stack that worked before usually has a permission or mount problem. |
| 2 | The cert-writer restarts or writes no certificates | the SPIRE agent is not healthy, or cannot reach the server in its `agent.conf` | Read `docker logs <name>-spire-agent` first. In `spire/agent.conf`, `trust_domain` and `server_address` must name your frame's SPIRE server (port 8444 by default), with `NodeAttestor "x509pop"`. Then restart both: `docker compose ... restart spire-agent cert-writer`. |
| 3 | The proxy in front answers 502 right after a start | the registry is not up yet: it runs its database migrations first, and it waits for the database, pgbouncer, Redis, the TEG, nginx-teg and the SPIRE agent | Wait a few minutes and follow `docker logs <name>-registry`. Startup Order, below, shows what waits for what. |
| 4 | A peer's federation call gets `400` from nginx | the caller sent no client certificate, or one `nginx-federation` cannot verify against your trust bundle | Check `docker logs <name>-cert-writer` on both sides. A certificate from another frame verifies only once your frame federates with it. |
| 5 | A federation call gets `403` | the registry's federation gate refused the caller | The detail names the reason: `Identity is not a valid peer registry` (the certificate is not a registry's), `Peer registry is not active` (no `ACTIVE` peer row for that identity; the operator stack sets `FEDERATION_REQUIRE_PEER_SPIFFE_BIND=true`) or `Operator federation license is not active` (the frame suspended or revoked the operator). |
| 6 | Ledger writes fail with `403` from the event store | the store did not accept the registry's certificate | The store's answer names it: `Authentication required` (no certificate arrived), `SPIFFE trust domain not trusted by this event store` or `Unknown SPIFFE ID ... Register as a federation operator first`. Check `docker logs <name>-cert-writer` for renewals. An operator's `EVENT_STORE_URL` must name its frame's store; in the bundle's compose it is a fixed line, which `.env.operator` cannot override. When the store does not answer at all, nothing is lost: events wait in the registry's outbox (`es_emit_outbox`) and are delivered later. If the certificate is fine, ask your frame whether your SPIRE entries or licence were revoked. |
| 7 | Agent cards from peers stop arriving | a peer refused the pull or did not answer, and your registry paused pulling from it | `GET /api/v1/admin/federation-sync/peers?stale=true` (admin flag `admin_platform`) lists the stale peers. A refused pull pauses that peer for 30 minutes, doubling up to 6 hours; one that does not answer, for 5 minutes, doubling up to an hour; never less than two sync intervals (`FEDERATION_CARD_PULL_BACKOFF=0` turns the pausing off). Check `docker logs <name>-nginx-federation` for TLS errors, and the peer's licence: a peer whose licence is not active is skipped. |
| 8 | "Connection pool exhausted" | PgBouncer (operator stack) or PostgreSQL is at its connection limit | Count the connections (Database Operations, below). Raise `max_client_conn` or the pool sizes in `pgbouncer.ini` and restart pgbouncer, or raise PostgreSQL's `max_connections`. |
| 9 | The registry answers `500` after an update | a database migration failed | Both stacks start the registry even when `alembic upgrade head` fails, and the operator stack discards the migration's error output, so the logs may not show it. Read the revision (`SELECT version_num FROM alembic_version;`, Database Operations below) and run the migration by hand to see the error: `docker exec <name>-registry sh -c 'cd /app && PYTHONPATH=/app/src alembic upgrade head'`. Keep the database volume across updates. |
| 10 | Creating an agent answers `409` | the bootstrap token was already used | A bootstrap token works once and lasts 5 minutes (`BOOTSTRAP_TOKEN_LIFETIME`): request a new one with `POST /api/v1/onboard/bootstrap/request-token` (developer login). An expired or unknown one answers `401`. |
| 11 | Releasing locked units answers `403` | the positions are still locked | There is no separate cooldown: only positions whose lock period has ended can be released, and the answer says how much is unlocked (`Insufficient unlocked balance. Available: ...`). With `position_id`, a locked position is refused with its unlock date. |
| 12 | A cross-registry transfer answers `403` | the target registry is not reachable in the federation, its federation licence is not active, or your registry holds it in quarantine | `Target registry '...' is not reachable in the federation` means no `ACTIVE` peer and no route through your peers: list them with `GET /api/v1/admin/federation/peers/all`. A licence refusal names the licence state. A quarantine refusal names the registry and its state (`quarantined` or `blacklisted`); your quarantines are listed by `GET /api/v1/admin/enforcement/registries/quarantined`. A `409` means the receiver's unit could not be determined; a `400`, that the receiver could not be placed (a local agent is paid with `POST /api/v1/teg/transfer`). |
| 13 | A transfer answers `400` "Insufficient balance" | the sender cannot cover it | Inside a registry the sender pays the amount plus the fee. `GET /api/v1/teg/balance` (agent token) shows the agent's balance; units locked in positions cannot be sent until they are released. |
| 14 | The supply audit reads `BREACH` | units on the ledger no longer add up | Do not correct anything by hand, and never write balances in a database. `GET /api/v1/public/supply-invariant` shows the delta; a kit frame's auditor raises `FrameSupplyInvariantBreach` (the Monitoring chapter, operator chapter 6). A cloud operator tells its frame at once. |
| 15 | Transfers to a known peer suddenly fail; the peer row is `INACTIVE` | a transient failure, such as a sync during a restart, deactivated the row (each deactivation records its reason) | The peer revival prober reactivates it on its own when the peer's certificate matches (every 120 seconds, after two matches). To act yourself: `GET /api/v1/admin/federation/peers/all`, then `POST /api/v1/admin/federation/peers/{peer_id}/reactivate` (admin flag `admin_federation`). Rows an admin or a guard deactivated stay down. Never change peer rows in the database. |

---

## Docker Commands Reference

The examples use the operator stack. On a kit frame, run the same commands in its stack directory with `-f docker-compose.frame-test.yml --env-file .env.frame-test` and the service names `<name>-registry`, `<name>-teg` and so on.

### View Containers

```bash
# Every service of the stack and its state
docker compose -f docker-compose.operator.yml --env-file .env.operator ps

# Every container on the host, with its ports
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### View Logs

```bash
# The registry's last 50 lines, or follow them
docker compose -f docker-compose.operator.yml --env-file .env.operator logs --tail 50 registry
docker compose -f docker-compose.operator.yml --env-file .env.operator logs -f registry

# With timestamps
docker logs <name>-registry --tail 50 -t

# Errors of the last hour (the registry writes plain text: <time> - <logger> - <LEVEL> - <message>)
docker logs <name>-registry --since 1h 2>&1 | grep -E ' - (ERROR|CRITICAL) - '
```

### Restart Services

```bash
# Restart one service (it keeps the environment it was created with)
docker compose -f docker-compose.operator.yml --env-file .env.operator restart registry

# Recreate one service after changing .env.operator, leaving the others running
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d --no-deps --force-recreate registry

# Stop and start the whole stack (named volumes, and your data with them, are kept; never add -v)
docker compose -f docker-compose.operator.yml --env-file .env.operator down
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d
```

### Update and Rebuild

The images are `${IMAGES_PREFIX}/registry`, `teg-layer` and `cert-writer` at the tag `VERSION` in `.env.operator` (`stable` when unset). A frame that hosts its operators updates them itself. On your own host, set the new `VERSION`, then pull and recreate; the Releases and Updates chapter (operator chapter 16) covers the release channel and the kit's own updater.

```bash
docker compose -f docker-compose.operator.yml --env-file .env.operator pull
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d
```

### Enter a Container

```bash
docker exec -it <name>-registry bash
docker exec -it <name>-teg bash
```

### Database Operations

| Database | Container | User | Database name (operator stack) | Database name (kit frame) |
|----------|-----------|------|--------------------------------|---------------------------|
| Registry | `<name>-db` | `registry` | `agentvault_registry` | `frame_test_registry` |
| TEG | `<name>-teg-db` | `teg` | `teg_layer` | `frame_test_teg` |
| Event store (kit frame only) | `<name>-es-db` | `eventstore` | | `frame_test_events` |

```bash
# Open the registry database
docker exec -it <name>-db psql -U registry -d agentvault_registry

# The migration revision
docker exec <name>-db psql -U registry -d agentvault_registry -c "SELECT version_num FROM alembic_version;"

# Active connections and the database's size
docker exec <name>-db psql -U registry -d agentvault_registry -c \
  "SELECT count(*) AS active FROM pg_stat_activity WHERE state = 'active';"
docker exec <name>-db psql -U registry -d agentvault_registry -c \
  "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

Read, never write: balances move only through the API, and a change made in a database is outside the ledger.

### Network Diagnostics

```bash
# Does the registry reach its ledger? "source": "eventstore" means yes, "unreachable" means no
curl -s https://<your-registry>/api/v1/public/supply-invariant

# Is the SPIRE agent healthy?
docker exec <name>-spire-agent /opt/spire/bin/spire-agent healthcheck -socketPath /opt/spire/sockets/agent.sock

# What did the cert-writer do last?
docker logs <name>-cert-writer --tail 10
```

---

## Startup Order

The operator stack starts in this order, set by the `depends_on` lines of its compose file. If a service is stuck, check the services it waits for.

```
1. db, teg-db, redis, spire-agent   (wait for nothing)
2. pgbouncer                        (after db is healthy)
   cert-writer                      (after spire-agent is healthy)
3. teg-layer                        (after teg-db, pgbouncer and redis are healthy)
4. nginx-teg                        (after teg-layer is healthy and cert-writer has started)
5. registry                         (after db, redis, pgbouncer, teg-layer, nginx-teg and spire-agent are healthy)
6. nginx-federation                 (after cert-writer and registry have started)
```

---

## Break-Glass: Freezing All Writes

If you suspect a leaked credential or a runaway automation and need it stopped now, set `READONLY_MODE=true` in your env file (`.env.operator`, or `.env.frame-test` on a kit frame) and recreate the registry:

```bash
docker compose -f docker-compose.operator.yml --env-file .env.operator up -d --no-deps --force-recreate registry
```

Every HTTP write then answers `503` (with `Retry-After`, `READONLY_RETRY_AFTER`, 300 seconds by default), the MCP routes are refused entirely, and the background workers that change state stop. Login and token routes and every read stay open, so you can still look, and the observers keep running: the supply auditor, the auditor worker and the licence drift monitor (`READONLY_EXEMPT_TASKS` adds more). The switch is read from the environment only: turning it off takes another recreate, so a stolen admin token cannot turn it back.

Investigate with writes frozen, rotate whatever leaked (the Security chapter, operator chapter 8), then remove the variable and recreate the registry again.

---

## When to Escalate

If you run a cloud operator, tell your frame's operator at once when you see:

- a supply audit reading `BREACH`
- your SPIRE attestation or federation licence revoked (`Operator federation license is not active`)
- mTLS failures that persist after the SPIRE agent restarts
- database corruption, or a migration that cannot complete
- anything that looks like units created, or balances changed, outside the API

Include in your report:
1. your registry's name and its SPIFFE ID (`identity.spiffe_id` in `/.well-known/registry-card.json`)
2. the logs of the affected service (the last 100 lines)
3. the output of `docker compose -f docker-compose.operator.yml --env-file .env.operator ps`
4. when the problem began (in UTC)
