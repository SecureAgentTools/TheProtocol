<template>
<div class="fd">
  <!-- Ambient -->
  <div class="fd-ambient">
    <div class="fd-grid"></div>
    <div class="fd-scan"></div>
    <div class="fd-glow fd-glow-1"></div>
    <div class="fd-glow fd-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="fd-hero">
    <div class="fd-hero-inner">
      <div class="fd-chip"><span class="fd-chip-dot"></span>{{ t('federationDocsView.chip') }}</div>
      <h1 class="fd-h1">{{ t('federationDocsView.h1a') }}<br/><span class="fd-accent">{{ t('federationDocsView.h1Accent') }}</span></h1>
      <p class="fd-lead">{{ t('federationDocsView.lead') }}</p>
    </div>
  </section>

  <!-- ═══ THE BIG PICTURE ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">The Big Picture</h2>
      <p class="fd-sub">Three things happen when you run a federated registry.</p>
    </div>
    <div class="fd-steps">
      <div class="fd-step">
        <div class="fd-step-num">1</div>
        <div class="fd-step-body">
          <h3 class="fd-step-title">Your registry runs ten containers</h3>
          <p class="fd-step-text">Registry (FastAPI + Vue), TEG (the transfer and exchange gateway), 2 PostgreSQL databases, Redis, PgBouncer, SPIRE agent (cryptographic identity), cert-writer (automatic mTLS certificate rotation), and two nginx mTLS gateways: one for federation, one in front of the TEG. Up in minutes on any Linux box with Docker.</p>
        </div>
      </div>
      <div class="fd-step">
        <div class="fd-step-num">2</div>
        <div class="fd-step-body">
          <h3 class="fd-step-title">Events flow to the shared EventStore</h3>
          <p class="fd-step-text">Every transfer, lock, dispute, and governance action on your registry is recorded in the mainframe's immutable event ledger. Your registry authenticates via mTLS — presenting its SPIRE SVID client certificate on every connection. API key fallback is disabled. Events are idempotent — post the same event twice and it's silently deduplicated. No double-counting, ever.</p>
        </div>
      </div>
      <div class="fd-step">
        <div class="fd-step-num">3</div>
        <div class="fd-step-body">
          <h3 class="fd-step-title">Agent cards sync across all registries</h3>
          <p class="fd-step-text">Every 5 minutes, your agents become discoverable across the federation — and their agents become discoverable on yours. You connect to one upstream parent (the mainframe, or an operator higher in the chain); cards then propagate hop-by-hop across the bilateral peer chain, so a single link plugs you into the whole network. It is a spanning tree, not a star.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT YOUR REGISTRY SENDS ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">What Your Registry Sends</h2>
      <p class="fd-sub">Two outbound data flows: events to the ledger and agent cards to peers.</p>
    </div>

    <div class="fd-card">
      <h3 class="fd-card-title">Events to the EventStore</h3>
      <p class="fd-card-text">Every financial and governance action emits an event to the shared immutable ledger at <code>events.theprotocol.cloud</code>.</p>
      <div class="fd-code" tabindex="0">
        <div class="fd-code-label">POST events.theprotocol.cloud/api/v1/events/</div>
        <pre>{
  "event_type": "TokensTransferred",
  "aggregate_id": "did:theprotocol:your-agent-did",
  "data": {
    "from": "did:theprotocol:sender",
    "to": "did:theprotocol:receiver",
    "amount": "100.00"
  },
  "source_service": "registry",
  "source_operator_id": "did:theprotocol:your-operator-did",
  "idempotency_key": "xfer-tx-uuid-here"
}</pre>
      </div>
      <div class="fd-detail-grid">
        <div class="fd-detail">
          <span class="fd-detail-label">Auth</span>
          <span class="fd-detail-value">mTLS via SPIRE SVID client certificate (enforced — API key fallback disabled)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Dedup</span>
          <span class="fd-detail-value">Same <code>idempotency_key</code> → 409 Conflict (success, not error)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Retry</span>
          <span class="fd-detail-value">Exponential backoff: 1s, 2s, 4s (max 3 retries)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Throughput</span>
          <span class="fd-detail-value">EventStore ingests 3,000–5,000 events/sec</span>
        </div>
      </div>
    </div>

    <div class="fd-card">
      <h3 class="fd-card-title">Agent Cards to Peers</h3>
      <p class="fd-card-text">Your federation sync worker runs every 5 minutes. It pushes your local agent cards to peers and pulls theirs. Authentication is enforced via mTLS — your registry presents its SPIRE SVID client certificate on every sync request. No API keys involved.</p>
      <div class="fd-detail-grid">
        <div class="fd-detail">
          <span class="fd-detail-label">Endpoint</span>
          <span class="fd-detail-value"><code>GET /api/v1/federation/agent-cards</code></span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Sync interval</span>
          <span class="fd-detail-value">Every 300 seconds (configurable)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Incremental</span>
          <span class="fd-detail-value">Only cards changed since last sync (60s buffer for clock drift)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Upstream relay</span>
          <span class="fd-detail-value">Your parent registry propagates cards from the mesh — the federation spanning tree makes the whole network reachable through your one link</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT YOUR REGISTRY RECEIVES ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">What Your Registry Receives</h2>
      <p class="fd-sub">Inbound: agent discovery data and cross-registry transfers.</p>
    </div>

    <div class="fd-card">
      <h3 class="fd-card-title">Agent Cards from Peers</h3>
      <p class="fd-card-text">Federated agents from other registries appear in your local discovery. Your users can find and interact with agents across the entire network without leaving your registry.</p>
    </div>

    <div class="fd-card">
      <h3 class="fd-card-title">Cross-Registry Transfers (2PC Protocol)</h3>
      <p class="fd-card-text">Units can flow between registries. The transfer uses a two-phase commit protocol to ensure atomicity: funds are never lost or double-spent, even if a network partition occurs mid-transfer.</p>
      <div class="fd-flow">
        <div class="fd-flow-step">
          <div class="fd-flow-label">Phase 1: Prepare</div>
          <p class="fd-flow-desc">Source TEG locks the sender's funds. Destination TEG (yours) receives a prepare request and confirms readiness. Funds are locked, not yet moved.</p>
        </div>
        <div class="fd-flow-arrow">→</div>
        <div class="fd-flow-step">
          <div class="fd-flow-label">Phase 2: Commit</div>
          <p class="fd-flow-desc">Source TEG sends commit. Your TEG credits the receiver's balance. Both sides emit events to the EventStore. If anything fails, Phase 2 aborts and funds are returned.</p>
        </div>
      </div>
      <div class="fd-detail-grid">
        <div class="fd-detail">
          <span class="fd-detail-label">Auth</span>
          <span class="fd-detail-value"><code>CROSS_TEG_API_KEY</code> validated with HMAC constant-time comparison</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Fee</span>
          <span class="fd-detail-value">0.5% credited to your TEG treasury (you keep it)</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Throughput</span>
          <span class="fd-detail-value">275 tx/s per registry (intra), network-bound across federation. Scales linearly with registry count.</span>
        </div>
        <div class="fd-detail">
          <span class="fd-detail-label">Coordination</span>
          <span class="fd-detail-value">Redis-backed 2PC store for cross-worker visibility</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ SECURITY MODEL ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">Security Model</h2>
      <p class="fd-sub">Four layers of trust — each independently enforceable.</p>
    </div>

    <div class="fd-layers">
      <div class="fd-layer">
        <div class="fd-layer-num">1</div>
        <div class="fd-layer-body">
          <h3 class="fd-layer-title">mTLS Identity (Enforced)</h3>
          <p class="fd-layer-text">Your registry authenticates to the EventStore via mTLS using SPIRE SVID client certificates. No API keys, no shared secrets — pure cryptographic identity. Your cert-writer container fetches auto-rotating SVIDs from the SPIRE agent every 5 minutes. The EventStore's nginx mTLS sidecar validates your certificate against the SPIRE trust bundle on every connection. API key fallback is disabled — mTLS is the only accepted auth method for external operators. If the mainframe bans your SPIRE agent, event submission stops immediately — total economic isolation in under 2 minutes.</p>
        </div>
      </div>
      <div class="fd-layer">
        <div class="fd-layer-num">2</div>
        <div class="fd-layer-body">
          <h3 class="fd-layer-title">SPIFFE/SPIRE Identity</h3>
          <p class="fd-layer-text">Your registry has a cryptographic identity issued by the mainframe SPIRE server at <code>spire.theprotocol.cloud:8444</code>. The SPIRE agent in your stack attests via x509 Proof of Possession — zero-maintenance, no token rotation needed. The cert-writer container fetches fresh SVIDs every 5 minutes. These SVIDs authenticate both federation sync (between registries) and event submission (to the EventStore) via mTLS. The nginx sidecars enforce mutual TLS on all cross-service traffic.</p>
        </div>
      </div>
      <div class="fd-layer">
        <div class="fd-layer-num">3</div>
        <div class="fd-layer-body">
          <h3 class="fd-layer-title">Emission Policies</h3>
          <p class="fd-layer-text">32 per-event-type rules control which layer can emit which event. Your registry layer can emit <code>TokensTransferred</code> but not <code>TokensIssued</code> (issuance). Your TEG layer can emit <code>TokensIssued</code> but not transfers. Unknown source → DENY. Unknown event type → DENY. Fail-closed by design.</p>
        </div>
      </div>
      <div class="fd-layer">
        <div class="fd-layer-num">4</div>
        <div class="fd-layer-body">
          <h3 class="fd-layer-title">Supply Invariant</h3>
          <p class="fd-layer-text">The EventStore continuously verifies: <code>tokens_issued − tokens_destroyed + transit_net == tokens_circulating</code>. Zero tolerance. If any registry — including yours — creates a discrepancy through a bug or misconfiguration, the audit catches it. This is the final safety net: the math must balance, always, across all registries.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ THE RULES ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">The Rules</h2>
      <p class="fd-sub">Network integrity invariants — non-negotiable, enforced in code.</p>
    </div>
    <div class="fd-rules">
      <div class="fd-rule" v-for="rule in rules" :key="rule">
        <span class="fd-rule-check">&#x2713;</span>
        <span>{{ rule }}</span>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT YOU CONTROL ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">What You Control</h2>
      <p class="fd-sub">Full economic sovereignty within the federation bounds.</p>
    </div>
    <div class="fd-own-grid">
      <div class="fd-own-card" v-for="item in sovereignty" :key="item.title">
        <h3 class="fd-own-title">{{ item.title }}</h3>
        <p class="fd-own-desc">{{ item.desc }}</p>
      </div>
    </div>
  </section>

  <!-- ═══ CONTAINER REFERENCE ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">Container Reference</h2>
      <p class="fd-sub">The containers of a federated operator deployment (an eleventh, data-cert-writer, joins when the database serves TLS).</p>
    </div>
    <div class="fd-card" style="padding: 0; overflow: hidden;">
      <div style="overflow-x: auto;" tabindex="0">
        <table class="fd-table">
          <thead><tr><th>Container</th><th>Image</th><th>Purpose</th><th>Connects To</th></tr></thead>
          <tbody>
            <tr v-for="c in containers" :key="c.name">
              <td style="font-weight: 600; color: var(--text-bright);">{{ c.name }}</td>
              <td><code style="font-size: 0.72rem;">{{ c.image }}</code></td>
              <td>{{ c.purpose }}</td>
              <td style="font-size: 0.78rem; color: var(--muted);">{{ c.connects }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ═══ QUICK REFERENCE ═══ -->
  <section class="fd-sec">
    <div class="fd-sec-head">
      <h2 class="fd-h2">Quick Reference</h2>
      <p class="fd-sub">Copy-paste commands for common operations.</p>
    </div>
    <div class="fd-commands">
      <div class="fd-cmd" v-for="cmd in commands" :key="cmd.label">
        <div class="fd-cmd-label">{{ cmd.label }}</div>
        <code class="fd-cmd-code">{{ cmd.code }}</code>
      </div>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="fd-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/operator" class="fd-btn fd-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; Back to Operator Program
    </router-link>
  </section>

  <footer class="fd-footer">
    <div class="fd-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="fd-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/a2a-protocol">A2A Protocol</router-link>
        <router-link to="/governance-docs">Governance</router-link>
        <router-link to="/trust-reputation">Trust</router-link>
        <router-link to="/operator">Operator</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const rules = [
  'Issuance is disabled for federated operators (MINTING_AUTHORITY=disabled): only a frame\'s own TEG issues new units, each frame in its own unit',
  'Fee floor: 0.5% on all intra-registry transfers. Fee ceiling: 5% (velocity-scaled)',
  'Cross-registry transfer fee: 0.5% credited to the receiver\'s TEG treasury',
  'Every event carries your source_operator_id — all actions are auditable to the originating registry',
  'EventStore enforces mTLS — API key authentication is disabled for external operators',
  'SPIRE agent can be banned — total economic isolation in under 2 minutes (no cache, no TTL)',
  '30-day zero-treasury balance triggers automatic quarantine',
  'Idempotent event dedup — same event posted twice is silently deduplicated (no double-counting)',
  'Emission policies are fail-closed — unknown event type or source layer is DENIED',
]

const sovereignty = [
  { title: 'Agent Registry', desc: 'Full control over who registers. Your approval flow, your agents, your namespace.' },
  { title: 'Fee Rates', desc: 'Set your own intra-registry fee curves within the 0.5%–5% federation bounds.' },
  { title: 'Treasury', desc: 'Your own treasury and fee collector, on your own ledger.' },
  { title: 'Governance', desc: 'Your own agent senate. Your proposals. Your voting rules and tally mechanism.' },
  { title: 'Database', desc: 'Your PostgreSQL, your server, your backups. No data leaves without your consent.' },
  { title: 'Agent Identity', desc: 'DIDs issued under your namespace. Cryptographic sovereignty via SPIFFE.' },
  { title: 'Location', desc: 'Operators and developers set their own coordinates freely via registry settings. Agents inherit their registry\'s location or set their own. In a future release, locations will be bound to legal jurisdictions for compliance.' },
]

const containers = [
  { name: 'registry', image: 'registry:stable', purpose: 'FastAPI backend + Vue frontend. 4 workers.', connects: 'db, redis, teg-layer, EventStore' },
  { name: 'teg-layer', image: 'teg-layer:stable', purpose: 'The transfer and exchange gateway. Balances, transfers, locks.', connects: 'teg-db, EventStore' },
  { name: 'db', image: 'postgres:16-alpine', purpose: 'PostgreSQL for registry data (agents, developers, cards).', connects: 'pgbouncer' },
  { name: 'teg-db', image: 'postgres:16-alpine', purpose: 'PostgreSQL for TEG data (balances, transactions).', connects: 'teg-layer' },
  { name: 'redis', image: 'redis:7-alpine', purpose: 'Shared state: leader election, rate limiting, caching.', connects: 'registry' },
  { name: 'pgbouncer', image: 'edoburu/pgbouncer', purpose: 'Connection pooling for registry DB. Pool mode: transaction.', connects: 'db' },
  { name: 'spire-agent', image: 'spire-agent:1.10.4', purpose: 'SPIFFE identity. Attests to mainframe SPIRE server.', connects: 'spire.theprotocol.cloud:8444' },
  { name: 'cert-writer', image: 'cert-writer:stable', purpose: 'Fetches SVIDs from SPIRE agent every 5 min. Writes certs.', connects: 'spire-agent socket' },
  { name: 'nginx-federation', image: 'nginx:1.25-alpine', purpose: 'mTLS sidecar for federation sync. Rotates certs with SVID.', connects: 'cert-writer certs, registry' },
  { name: 'nginx-teg', image: 'nginx:1.25-alpine', purpose: 'mTLS gateway in front of the TEG; the TEG requires mTLS.', connects: 'cert-writer certs, teg-layer' },
]

const commands = [
  { label: 'Boot the stack', code: 'docker compose -f docker-compose.operator.yml --env-file .env.operator up -d' },
  { label: 'Check federation status', code: 'curl http://localhost:8000/api/v1/federation/info' },
  { label: 'Check supply audit', code: 'curl https://events.theprotocol.cloud/api/v1/projections/supply-audit' },
  { label: 'View registry logs', code: 'docker logs <your-registry-container> --tail 50' },
  { label: 'View sync status', code: 'curl http://localhost:8000/api/v1/federation/sync-status' },
  { label: 'List your agents', code: 'curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/developers/me/agents' },
]
</script>

<style scoped>
.fd {
  --bg: #060a12;
  --surface: rgba(var(--nc-primary-rgb),0.03);
  --border: rgba(var(--nc-primary-rgb),0.08);
  --border-bright: rgba(var(--nc-primary-rgb),0.18);
  --cyan: var(--nc-primary);
  --green: #00e676;
  --amber: #f59e0b;
  --text: #b0bec5;
  --text-bright: #e0e6eb;
  --muted: #78909c;
  --mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
  background: var(--bg); color: var(--text);
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* Ambient */
.fd-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.fd-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.fd-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: fdScan 12s linear infinite; }
@keyframes fdScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.fd-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.fd-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.fd-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

/* Hero */
.fd-hero { position: relative; min-height: 60vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.fd-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.fd-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.fd-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.fd-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.fd-accent { color: var(--cyan); }
.fd-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 560px; }

/* Sections */
.fd-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.fd-sec-head { margin-bottom: 2rem; }
.fd-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.fd-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Big picture steps */
.fd-steps { display: flex; flex-direction: column; gap: 24px; }
.fd-step { display: flex; gap: 20px; align-items: flex-start; }
.fd-step-num { width: 36px; height: 36px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.fd-step-body { flex: 1; }
.fd-step-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.fd-step-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

/* Cards */
.fd-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.fd-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.fd-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0 0 16px; }

/* Code blocks */
.fd-code { background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 6px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.fd-code-label { font-family: var(--mono); font-size: 11px; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 10px; font-weight: 600; }
.fd-code pre { font-family: var(--mono); font-size: 12.5px; color: var(--green); line-height: 1.6; margin: 0; white-space: pre-wrap; }
code { font-family: var(--mono); font-size: 0.88em; color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.06); padding: 1px 5px; border-radius: 3px; }

/* Detail grids */
.fd-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.fd-detail { display: flex; flex-direction: column; gap: 2px; }
.fd-detail-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.fd-detail-value { font-size: 13px; color: var(--text); line-height: 1.5; }

/* 2PC flow */
.fd-flow { display: flex; align-items: stretch; gap: 12px; margin-bottom: 16px; }
.fd-flow-step { flex: 1; background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
.fd-flow-label { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 6px; }
.fd-flow-desc { font-size: 12.5px; color: var(--text); line-height: 1.6; margin: 0; }
.fd-flow-arrow { display: flex; align-items: center; font-size: 20px; color: var(--cyan); opacity: 0.4; flex-shrink: 0; }

/* Security layers */
.fd-layers { display: flex; flex-direction: column; gap: 16px; }
.fd-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.fd-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.fd-layer-body { flex: 1; }
.fd-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.fd-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }

/* Rules */
.fd-rules { display: flex; flex-direction: column; gap: 10px; }
.fd-rule { display: flex; align-items: flex-start; gap: 12px; font-size: 13.5px; line-height: 1.6; color: var(--text); }
.fd-rule-check { color: var(--cyan); font-weight: 600; font-size: 14px; flex-shrink: 0; margin-top: 1px; }

/* Sovereignty grid */
.fd-own-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
.fd-own-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.fd-own-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.fd-own-desc { font-size: 13px; color: var(--text); line-height: 1.6; margin: 0; }

/* Table */
.fd-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.fd-table th { text-align: left; padding: 12px 16px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 600; }
.fd-table td { padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.03); color: var(--text); }
.fd-table tr:last-child td { border-bottom: none; }

/* Commands */
.fd-commands { display: flex; flex-direction: column; gap: 12px; }
.fd-cmd { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; }
.fd-cmd-label { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; margin-bottom: 6px; font-weight: 600; text-transform: uppercase; }
/* a long URL breaks where it must on a phone, where it ran up to 138 px past its box (the camera, 2026-10-13); a copy
   still takes the whole command */
.fd-cmd-code { font-family: var(--mono); font-size: 12.5px; color: var(--green); display: block; line-height: 1.5; overflow-wrap: anywhere; }

/* Buttons */
.fd-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-decoration: none; cursor: pointer; transition: all 0.2s; font-family: var(--mono); border: none; }
.fd-btn-ghost { background: transparent; color: var(--text); border: 1px solid rgba(255,255,255,0.12); }
.fd-btn-ghost:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }

/* Footer */
.fd-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.fd-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
/* the links wrap whole on a phone, where the row ran past the screen ("Operator" cut off, "Units & Fees" on three
   lines; the camera, 2026-10-13) */
.fd-footer-links { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.fd-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; white-space: nowrap; }
.fd-footer-links a:hover { color: var(--text-bright); }

@media (max-width: 640px) {
  .fd-detail-grid { grid-template-columns: 1fr; }
  .fd-flow { flex-direction: column; }
  .fd-flow-arrow { transform: rotate(90deg); align-self: center; }
  .fd-own-grid { grid-template-columns: 1fr; }
}
</style>
