# HTTPS for a Standalone Registry

The registry serves plain HTTP on port 8000. **Any internet-facing deployment must put
TLS in front of it** — browsers and the web UI expect a valid certificate on your domain.

Federated operators already get this: the `nginx-federation` mTLS sidecar handles the
federation channel, and you place your own proxy in front of the registry port. For
**standalone** self-hosters, this directory ships a ready-to-use Caddy overlay that
obtains and auto-renews a free Let's Encrypt certificate — no manual cert management.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.tls.yml` | Caddy service overlay (ports 80/443 → `registry:8000`) |
| `Caddyfile` | Caddy config: auto-TLS for `{$DOMAIN}`, security headers, gzip |

## Setup

1. **Point DNS at this server** — an `A`/`AAAA` record for e.g. `registry.example.com`.

2. **Set the domain** in `.env.operator`:
   ```
   DOMAIN=registry.example.com
   ACME_EMAIL=you@example.com          # optional, for renewal notices
   ```

3. **Boot with both compose files:**
   ```bash
   docker compose \
     -f docker-compose.standalone.yml \
     -f docker-compose.tls.yml \
     --env-file .env.operator up -d
   ```
   Caddy completes the Let's Encrypt HTTP-01 challenge on port 80 and serves HTTPS on 443
   within a few seconds. Your registry is now at `https://registry.example.com`.

4. **Harden (recommended)** — stop exposing raw HTTP to the internet. In
   `docker-compose.standalone.yml`, bind the registry port to loopback so only Caddy (on
   the internal Docker network) can reach it:
   ```yaml
   # registry service
   ports:
     - "127.0.0.1:8000:8000"     # was "8000:8000"
   ```
   Then open **only** ports 80 and 443 on your host firewall.

## Notes

- **Ports 80 and 443 must be free** on the host and reachable from the internet (Let's
  Encrypt validates over port 80).
- Certificates and ACME state persist in the `caddy_data` volume across restarts — you
  won't re-request a cert on every boot (and won't hit Let's Encrypt rate limits).
- Prefer your own proxy (nginx, Traefik, a cloud load balancer)? Skip this overlay and
  point your proxy at the registry's `8000:8000`. This Caddy setup is the batteries-included
  default, not a requirement.
- WebSocket endpoints (live ledger feed, metrics) upgrade transparently through the proxy.
