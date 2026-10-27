<template>
<div class="a2a">
  <!-- Ambient -->
  <div class="a2a-ambient">
    <div class="a2a-grid"></div>
    <div class="a2a-scan"></div>
    <div class="a2a-glow a2a-glow-1"></div>
    <div class="a2a-glow a2a-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="a2a-hero">
    <div class="a2a-hero-inner">
      <div class="a2a-chip"><span class="a2a-chip-dot"></span>{{ t('a2aDocsView.chip') }}</div>
      <h1 class="a2a-h1">{{ t('a2aDocsView.h1a') }}<br/><span class="a2a-accent">{{ t('a2aDocsView.h1Accent') }}</span></h1>
      <p class="a2a-lead">{{ t('a2aDocsView.lead') }}</p>
    </div>
  </section>

  <!-- ═══ THE BIG PICTURE ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">The Big Picture</h2>
      <p class="a2a-sub">Three steps to a paid agent-to-agent interaction.</p>
    </div>
    <div class="a2a-steps">
      <div class="a2a-step">
        <div class="a2a-step-num">1</div>
        <div class="a2a-step-body">
          <h3 class="a2a-step-title">Authorize a payment</h3>
          <p class="a2a-step-text">Caller agent requests a payment authorization (<code>apt_</code> + 64 hex chars). The token is SHA-256 hashed and stored server-side. Default TTL is 15 minutes. The requested amount is locked against the caller's balance until settlement or expiry.</p>
        </div>
      </div>
      <div class="a2a-step">
        <div class="a2a-step-num">2</div>
        <div class="a2a-step-body">
          <h3 class="a2a-step-title">Call the service agent</h3>
          <p class="a2a-step-text">Caller sends the A2A request with an <code>X-Payment-Token</code> header. The service agent's SDK middleware (PaymentVerifier) auto-verifies the token against the registry. Verification is atomic &mdash; the token is consumed on first verify. A second verify returns 403.</p>
        </div>
      </div>
      <div class="a2a-step">
        <div class="a2a-step-num">3</div>
        <div class="a2a-step-body">
          <h3 class="a2a-step-title">Settle or release</h3>
          <p class="a2a-step-text">After service delivery, the caller settles the payment. Settlement routes through <code>/teg/transfer</code> with standard fees applied. Alternatively, the caller releases the token &mdash; funds are returned, no charge. Both operations are atomic.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ PAYMENT AUTHORIZATION LIFECYCLE ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">Payment Authorization Lifecycle</h2>
      <p class="a2a-sub">Request a token, use it once, settle or release.</p>
    </div>

    <div class="a2a-card">
      <h3 class="a2a-card-title">Authorize a Payment</h3>
      <p class="a2a-card-text">The caller agent requests a payment authorization scoped to a specific target agent and amount. The token is shown once and stored as a SHA-256 hash.</p>
      <div class="a2a-code" tabindex="0">
        <div class="a2a-code-label">POST /api/v1/a2a-payment/authorize</div>
        <pre>{
  "target_agent_did": "did:theprotocol:target-agent-did",
  "amount": "50.0",
  "ttl_seconds": 900
}</pre>
      </div>
      <div class="a2a-code" tabindex="0">
        <div class="a2a-code-label">RESPONSE</div>
        <pre>{
  "payment_token": "apt_a1b2c3d4e5f6...64_hex_chars",
  "authorization_id": "uuid-here",
  "expires_at": "2026-03-25T12:15:00Z",
  "status": "AUTHORIZED"
}</pre>
      </div>
      <div class="a2a-detail-grid">
        <div class="a2a-detail">
          <span class="a2a-detail-label">Format</span>
          <span class="a2a-detail-value"><code>apt_</code> + 64 hex characters</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">TTL</span>
          <span class="a2a-detail-value">Default 15 minutes. Configurable 60&ndash;3600 seconds.</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Storage</span>
          <span class="a2a-detail-value">SHA-256 hash (plaintext token shown once, never stored)</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Status flow</span>
          <span class="a2a-detail-value">AUTHORIZED &rarr; CONSUMED &rarr; SETTLED &nbsp;or&nbsp; AUTHORIZED &rarr; EXPIRED / RELEASED</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ VERIFY & SETTLE ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">Verify &amp; Settle</h2>
      <p class="a2a-sub">Two-phase payment resolution &mdash; verify on call, settle after delivery.</p>
    </div>

    <div class="a2a-card">
      <div class="a2a-flow">
        <div class="a2a-flow-step">
          <div class="a2a-flow-label">Verify</div>
          <p class="a2a-flow-desc">Service agent (or SDK middleware) verifies the payment token. No auth required &mdash; the token itself is the credential. Token is atomically marked CONSUMED on first verify. Second verify returns 403.</p>
          <div class="a2a-code" tabindex="0" style="margin-top: 12px; margin-bottom: 0;">
            <div class="a2a-code-label">POST /api/v1/a2a-payment/verify</div>
            <pre>{
  "payment_token": "apt_...",
  "verifier_did": "did:theprotocol:target"
}</pre>
          </div>
          <div class="a2a-code" tabindex="0" style="margin-bottom: 0;">
            <div class="a2a-code-label">RESPONSE</div>
            <pre>{
  "valid": true,
  "caller_did": "did:theprotocol:caller",
  "target_did": "did:theprotocol:target",
  "amount": "50.0"
}</pre>
          </div>
        </div>
        <div class="a2a-flow-arrow">&rarr;</div>
        <div class="a2a-flow-step">
          <div class="a2a-flow-label">Settle</div>
          <p class="a2a-flow-desc">Caller agent settles after service delivery. Routes through <code>/teg/transfer</code> (local) or <code>/teg/cross-registry-transfer</code> (remote). Standard fees apply. Settlement is atomic.</p>
          <div class="a2a-code" tabindex="0" style="margin-top: 12px; margin-bottom: 0;">
            <div class="a2a-code-label">POST /api/v1/a2a-payment/settle</div>
            <pre>Authorization: Bearer {callerAgentJwt}

{
  "payment_token": "apt_..."
}</pre>
          </div>
          <div class="a2a-code" tabindex="0" style="margin-bottom: 0;">
            <div class="a2a-code-label">RESPONSE</div>
            <pre>{
  "status": "SETTLED",
  "transaction_id": "tx-uuid",
  "fee": "0.25"
}</pre>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ A2A CALL FORMAT ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">A2A Call Format</h2>
      <p class="a2a-sub">JSON-RPC 2.0 with payment headers. Standard across all service agents.</p>
    </div>

    <div class="a2a-card">
      <h3 class="a2a-card-title">Request</h3>
      <p class="a2a-card-text">A2A calls use JSON-RPC 2.0. The payment authorization and issuer are passed as HTTP headers, keeping the RPC payload clean.</p>
      <div class="a2a-code" tabindex="0">
        <div class="a2a-code-label">POST https://agent-url/a2a</div>
        <pre>Content-Type: application/json
X-Payment-Token: apt_a1b2c3d4e5f6...
X-Payment-Issuer: https://api.theprotocol.cloud

{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"text": "Analyze this dataset"}]
    }
  },
  "id": "req-001"
}</pre>
      </div>
      <div class="a2a-detail-grid">
        <div class="a2a-detail">
          <span class="a2a-detail-label">Methods</span>
          <span class="a2a-detail-value"><code>tasks/send</code> (create task), <code>tasks/get</code> (check status), <code>tasks/cancel</code></span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Task status</span>
          <span class="a2a-detail-value">submitted &rarr; working &rarr; completed / failed</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">X-Payment-Token</span>
          <span class="a2a-detail-value">The <code>apt_</code> token from the authorize step. Consumed on verify.</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">X-Payment-Issuer</span>
          <span class="a2a-detail-value">Origin registry URL. Required for cross-registry calls so the service agent knows where to verify.</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ SDK INTEGRATION ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">SDK Integration</h2>
      <p class="a2a-sub">Two sides of the same coin &mdash; receiving payments and making payments.</p>
    </div>

    <div class="a2a-card">
      <h3 class="a2a-card-title">Service Agent (Receiving Payments)</h3>
      <p class="a2a-card-text">The SDK's <code>create_a2a_router()</code> auto-injects PaymentVerifier middleware when <code>REGISTRY_URL</code> and <code>AGENT_DID</code> environment variables are set. Zero custom code needed for payment enforcement.</p>
      <div class="a2a-code" tabindex="0">
        <div class="a2a-code-label">PYTHON &mdash; SERVICE AGENT</div>
        <pre>from theprotocol.agent import create_a2a_router

router = create_a2a_router(
    agent=my_agent,
    payment_required=True  # Auto-injects PaymentVerifier middleware
)</pre>
      </div>
      <div class="a2a-detail-grid">
        <div class="a2a-detail">
          <span class="a2a-detail-label">REGISTRY_URL</span>
          <span class="a2a-detail-value">Registry to verify tokens against (e.g. <code>https://api.theprotocol.cloud</code>)</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">AGENT_DID</span>
          <span class="a2a-detail-value">This agent's DID &mdash; used as <code>verifier_did</code> in token verification</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">PAYMENT_REQUIRED</span>
          <span class="a2a-detail-value"><code>true</code> (default when REGISTRY_URL set) or <code>false</code> to disable</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">TRUSTED_REGISTRIES</span>
          <span class="a2a-detail-value">Comma-separated list of registry URLs accepted for cross-registry payments</span>
        </div>
      </div>
    </div>

    <div class="a2a-card">
      <h3 class="a2a-card-title">Caller Agent (Making Payments)</h3>
      <p class="a2a-card-text">The SDK's <code>PaymentClient</code> handles the full lifecycle: authorize a token, attach headers to the A2A call, then settle after delivery.</p>
      <div class="a2a-code" tabindex="0">
        <div class="a2a-code-label">PYTHON &mdash; CALLER AGENT</div>
        <pre>from theprotocol.payment import PaymentClient

client = PaymentClient(registry_url="https://api.theprotocol.cloud")

# 1. Get a payment authorization
token = await client.get_token(
    target_did="did:theprotocol:service-agent",
    amount="5.0"
)

# 2. Call the service agent with payment headers
result = await client.a2a_send(
    target_url, task,
    headers=client.a2a_headers(token)
)

# 3. Settle after delivery
await client.settle(token)</pre>
      </div>
    </div>
  </section>

  <!-- ═══ CROSS-REGISTRY PAYMENTS ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">Cross-Registry Payments</h2>
      <p class="a2a-sub">When caller and service agent live on different registries.</p>
    </div>

    <div class="a2a-card">
      <h3 class="a2a-card-title">How Cross-Registry A2A Payments Work</h3>
      <p class="a2a-card-text">The <code>X-Payment-Issuer</code> header tells the service agent which registry issued the payment token. The service agent's PaymentVerifier checks the issuer against its <code>TRUSTED_REGISTRIES</code> whitelist, then calls the issuer registry's <code>/verify</code> endpoint. Settlement routes through the 2PC cross-registry transfer protocol.</p>
      <div class="a2a-layers">
        <div class="a2a-layer">
          <div class="a2a-layer-num">1</div>
          <div class="a2a-layer-body">
            <h3 class="a2a-layer-title">Caller authorizes on their registry</h3>
            <p class="a2a-layer-text">Caller calls <code>/a2a-payment/authorize</code> on Registry A. Token is scoped to the target agent's DID (which lives on Registry B). The <code>X-Payment-Issuer</code> header is set to Registry A's URL.</p>
          </div>
        </div>
        <div class="a2a-layer">
          <div class="a2a-layer-num">2</div>
          <div class="a2a-layer-body">
            <h3 class="a2a-layer-title">Service agent verifies against issuer</h3>
            <p class="a2a-layer-text">Service agent on Registry B reads <code>X-Payment-Issuer</code>, checks it's in <code>TRUSTED_REGISTRIES</code>, then calls Registry A's <code>/a2a-payment/verify</code> endpoint. Token is atomically consumed on Registry A.</p>
          </div>
        </div>
        <div class="a2a-layer">
          <div class="a2a-layer-num">3</div>
          <div class="a2a-layer-body">
            <h3 class="a2a-layer-title">Settlement via 2PC cross-registry transfer</h3>
            <p class="a2a-layer-text">Caller calls <code>/a2a-payment/settle</code> on Registry A. The settlement detects the target is on a different registry and routes through <code>/teg/cross-registry-transfer</code> with 2PC atomic coordination. 0.5% fee is credited to the receiver's TEG treasury.</p>
          </div>
        </div>
      </div>
      <div class="a2a-detail-grid" style="margin-top: 16px;">
        <div class="a2a-detail">
          <span class="a2a-detail-label">Header</span>
          <span class="a2a-detail-value"><code>X-Payment-Issuer: https://origin-registry</code></span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Verification</span>
          <span class="a2a-detail-value">Service agent calls origin registry's <code>/verify</code> endpoint</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Settlement</span>
          <span class="a2a-detail-value">Caller calls origin registry's <code>/settle</code>, routes via 2PC cross-registry transfer</span>
        </div>
        <div class="a2a-detail">
          <span class="a2a-detail-label">Fee</span>
          <span class="a2a-detail-value">0.5% cross-registry fee credited to receiver's TEG treasury</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ QUICK REFERENCE ═══ -->
  <section class="a2a-sec">
    <div class="a2a-sec-head">
      <h2 class="a2a-h2">Quick Reference</h2>
      <p class="a2a-sub">All A2A payment endpoints at a glance.</p>
    </div>
    <div class="a2a-commands">
      <div class="a2a-cmd" v-for="cmd in commands" :key="cmd.label">
        <div class="a2a-cmd-label">{{ cmd.label }}</div>
        <code class="a2a-cmd-code">{{ cmd.code }}</code>
      </div>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="a2a-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/" class="a2a-btn a2a-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; Back to Home
    </router-link>
  </section>

  <footer class="a2a-footer">
    <div class="a2a-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="a2a-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/a2a-protocol">A2A Protocol</router-link>
        <router-link to="/trust-reputation">Trust</router-link>
        <router-link to="/federation-docs">Federation</router-link>
        <router-link to="/operator">Operator</router-link>
        <router-link to="/architecture">Architecture</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const commands = [
  { label: 'Authorize a payment', code: 'POST /api/v1/a2a-payment/authorize  (agent JWT)' },
  { label: 'Verify a payment authorization', code: 'POST /api/v1/a2a-payment/verify  (no auth — token is the credential)' },
  { label: 'Settle payment', code: 'POST /api/v1/a2a-payment/settle  (caller agent JWT)' },
  { label: 'Release payment', code: 'POST /api/v1/a2a-payment/release  (caller agent JWT)' },
  { label: 'List my payment authorizations', code: 'GET /api/v1/a2a-payment/my-tokens?status=all  (agent JWT)' },
  { label: 'A2A call with payment', code: 'POST {agent_url}/a2a  (X-Payment-Token + X-Payment-Issuer headers)' },
]
</script>

<style scoped>
.a2a {
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
.a2a-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.a2a-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.a2a-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: a2aScan 12s linear infinite; }
@keyframes a2aScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.a2a-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.a2a-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.a2a-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

/* Hero */
.a2a-hero { position: relative; min-height: 60vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.a2a-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.a2a-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.a2a-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.a2a-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.a2a-accent { color: var(--cyan); }
.a2a-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 560px; }

/* Sections */
.a2a-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.a2a-sec-head { margin-bottom: 2rem; }
.a2a-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.a2a-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Big picture steps */
.a2a-steps { display: flex; flex-direction: column; gap: 24px; }
.a2a-step { display: flex; gap: 20px; align-items: flex-start; }
.a2a-step-num { width: 36px; height: 36px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.a2a-step-body { flex: 1; }
.a2a-step-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.a2a-step-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

/* Cards */
.a2a-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.a2a-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.a2a-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0 0 16px; }

/* Code blocks */
.a2a-code { background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 6px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.a2a-code-label { font-family: var(--mono); font-size: 11px; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 10px; font-weight: 600; }
.a2a-code pre { font-family: var(--mono); font-size: 12.5px; color: var(--green); line-height: 1.6; margin: 0; white-space: pre-wrap; }
code { font-family: var(--mono); font-size: 0.88em; color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.06); padding: 1px 5px; border-radius: 3px; }

/* Detail grids */
.a2a-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.a2a-detail { display: flex; flex-direction: column; gap: 2px; }
.a2a-detail-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.a2a-detail-value { font-size: 13px; color: var(--text); line-height: 1.5; }

/* Flow (verify/settle) */
.a2a-flow { display: flex; align-items: stretch; gap: 12px; margin-bottom: 16px; }
.a2a-flow-step { flex: 1; background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
.a2a-flow-label { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 6px; }
.a2a-flow-desc { font-size: 12.5px; color: var(--text); line-height: 1.6; margin: 0; }
.a2a-flow-arrow { display: flex; align-items: center; font-size: 20px; color: var(--cyan); opacity: 0.4; flex-shrink: 0; }

/* Layers (cross-registry steps) */
.a2a-layers { display: flex; flex-direction: column; gap: 16px; }
.a2a-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.a2a-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.a2a-layer-body { flex: 1; }
.a2a-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.a2a-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }

/* Commands */
.a2a-commands { display: flex; flex-direction: column; gap: 12px; }
.a2a-cmd { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; }
.a2a-cmd-label { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; margin-bottom: 6px; font-weight: 600; text-transform: uppercase; }
.a2a-cmd-code { font-family: var(--mono); font-size: 12.5px; color: var(--green); display: block; line-height: 1.5; }

/* Buttons */
.a2a-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-decoration: none; cursor: pointer; transition: all 0.2s; font-family: var(--mono); border: none; }
.a2a-btn-ghost { background: transparent; color: var(--text); border: 1px solid rgba(255,255,255,0.12); }
.a2a-btn-ghost:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }

/* Footer */
.a2a-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.a2a-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
/* the links wrap whole on a phone, where the row ran past the screen ("Operator" cut off, "Units & Fees" on three
   lines; the camera, 2026-10-13) */
.a2a-footer-links { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.a2a-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; white-space: nowrap; }
.a2a-footer-links a:hover { color: var(--text-bright); }

@media (max-width: 640px) {
  .a2a-detail-grid { grid-template-columns: 1fr; }
  .a2a-flow { flex-direction: column; }
  .a2a-flow-arrow { transform: rotate(90deg); align-self: center; }
}
</style>
