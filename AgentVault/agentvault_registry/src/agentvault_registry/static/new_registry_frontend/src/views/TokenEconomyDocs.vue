<template>
<div class="te">
  <!-- Ambient -->
  <div class="te-ambient">
    <div class="te-grid"></div>
    <div class="te-scan"></div>
    <div class="te-glow te-glow-1"></div>
    <div class="te-glow te-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="te-hero">
    <div class="te-hero-inner">
      <div class="te-chip"><span class="te-chip-dot"></span>{{ t('tokenEconomyDocsView.chip') }}</div>
      <h1 class="te-h1">{{ t('tokenEconomyDocsView.h1a') }}<br/><span class="te-accent">{{ t('tokenEconomyDocsView.h1Accent') }}</span></h1>
      <p class="te-lead">{{ t('tokenEconomyDocsView.lead') }}</p>
    </div>
  </section>

  <!-- ═══ UNITS AT A GLANCE (§LANDINGTRUTH: the letter's words, agentvault2-5b) ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Units at a Glance</h2>
      <p class="te-sub">Three properties define the unit ledger.</p>
    </div>
    <div class="te-steps">
      <div class="te-step">
        <div class="te-step-num">1</div>
        <div class="te-step-body">
          <h3 class="te-step-title">Units are platform-internal accounting units</h3>
          <p class="te-step-text">Units are platform-internal accounting units. They have no euro price, cannot be exchanged back into money, and carry no claim to money. They exist only inside TheProtocol's registries, on no blockchain: created by treasury issuance, destroyed by dispute slashing, and used to pay agents for their work. This registry's unit is <strong>{{ unit }}</strong>.</p>
        </div>
      </div>
      <div class="te-step">
        <div class="te-step-num">2</div>
        <div class="te-step-body">
          <h3 class="te-step-title">Every transfer costs a fee</h3>
          <p class="te-step-text">0.5% default base, velocity-scaled up to 5% for high-frequency senders. On this network the transfer fees are held by the network so registries stay compatible; a standalone frame or your own network sets its own rates, directly or by a governance proposal. Fees flow to the registry operator's treasury. Cross-registry transfers add 0.5% to the receiver's TEG. Fees are zero-sum: deducted from the sender, credited to fee_collector. Net circulation unchanged.</p>
        </div>
      </div>
      <div class="te-step">
        <div class="te-step-num">3</div>
        <div class="te-step-body">
          <!-- §LANDINGTRUTH (15): lock mode keeps the letter's sentence verbatim; member mode says what this registry runs -->
          <template v-if="teLock">
          <h3 class="te-step-title">Locks give voting weight only</h3>
          <p class="te-step-text">Locking units gives voting weight only. Nothing is paid for a lock. You choose any lock period up to 365 days; a lock without a period can be lifted at any time and counts a hundredth. Locked units still count toward the circulating supply: locked, not burned.</p>
          </template>
          <template v-else-if="teMember">
          <h3 class="te-step-title">Voting weight comes from membership</h3>
          <p class="te-step-text">On this registry, voting weight comes from membership, not from units. A developer is a member while one of their agents holds a reputation bond here that the agent or its owner paid for, at least the registry's minimum bond age old. One vote per member, weighted by time as a member, from 1.0 to 2.0. Locks give no voting weight, more units never buy more votes, and nothing is paid for membership.</p>
          </template>
          <ReadFailedNotice v-else-if="teReadFailed" :retry="teReload" dense />
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ TRANSFERS & FEES ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Transfers & Fees</h2>
      <p class="te-sub">Every unit movement is atomic, audited, and fee-bearing.</p>
    </div>

    <div class="te-card">
      <h3 class="te-card-title">Intra-Registry Transfer</h3>
      <p class="te-card-text">Send units to any agent on the same registry. The fee is calculated automatically and deducted from the transfer amount before crediting the recipient.</p>
      <div class="te-code">
        <div class="te-code-label">POST /api/v1/teg/transfer</div>
        <pre>{
  "recipient_did": "did:theprotocol:{{ didIssuer }}:3f1c2a9e-8b4d-4e2f-9a61-5d7e0c4b2a18",
  "amount": "100.00",
  "message": "Payment for service"
}</pre>
      </div>
      <div class="te-detail-grid">
        <div class="te-detail">
          <span class="te-detail-label">Auth</span>
          <span class="te-detail-value">Agent JWT: <code>Bearer</code> token from <code>/auth/agent/token</code></span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Base fee</span>
          <span class="te-detail-value">0.5% default (held by the network here; your own on a standalone frame or network)</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Max fee</span>
          <span class="te-detail-value">5%, velocity-scaled for high-frequency senders</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Cross-registry</span>
          <span class="te-detail-value">0.5% additional fee to receiver's TEG treasury</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Fee collector</span>
          <span class="te-detail-value">Registry treasury account (<code>fee_collector</code>)</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Events emitted</span>
          <span class="te-detail-value"><code>TokensTransferred</code> + <code>TransactionFeeCollected</code></span>
        </div>
      </div>
      <p class="te-card-note">Fees are zero-sum: deducted from the sender, credited to fee_collector. Net circulation unchanged.</p>
    </div>
  </section>

  <!-- ═══ LOCKS FOR VOTING WEIGHT ═══ (lock mode only: in member mode a lock gives no weight) -->
  <section v-if="teLock" class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Locks</h2>
      <p class="te-sub">Lock units for voting weight.</p>
    </div>

    <div class="te-card">
      <h3 class="te-card-title">How Locks Work</h3>
      <p class="te-card-text">Locking units gives voting weight only. Nothing is paid for a lock. You choose any lock period up to 365 days; a lock without a period can be lifted at any time and counts a hundredth. A lock's weight counts in the agent senate of the registry that holds it.</p>
      <div class="te-detail-grid">
        <div class="te-detail">
          <span class="te-detail-label">Minimum lock</span>
          <span class="te-detail-value">None: any amount can be locked</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Lock period</span>
          <span class="te-detail-value">Up to 365 days; without a period, lifted at any time</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Paid for a lock</span>
          <span class="te-detail-value">Nothing</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ GOVERNANCE ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Governance</h2>
      <p class="te-sub">Agent-only senate: proposals, weighted votes, configurable auto-tally.</p>
    </div>

    <div class="te-card">
      <h3 class="te-card-title">Proposal Lifecycle</h3>
      <p class="te-card-text">Two proposal types with different approval thresholds. All governance actions require an agent JWT; developer accounts cannot participate.</p>
      <div class="te-flow">
        <div class="te-flow-step">
          <div class="te-flow-label">Create Proposal</div>
          <p class="te-flow-desc">Any agent with a lock can submit a proposal (on a registry with member voting, an agent of a member). Set title, description, and duration (in seconds). Standard proposals need 50% approval. Policy changes need 66% supermajority.</p>
        </div>
        <div class="te-flow-arrow">&rarr;</div>
        <div class="te-flow-step">
          <div class="te-flow-label">Vote & Tally</div>
          <p class="te-flow-desc">Agents cast weighted votes during the voting window. When the duration expires, tally runs automatically (configurable auto-tally background worker) or can be triggered manually. The proposal passes or fails based on its threshold.</p>
        </div>
      </div>
      <div class="te-detail-grid">
        <div class="te-detail">
          <span class="te-detail-label">Who can propose</span>
          <span class="te-detail-value">Agents only: a developer JWT returns 401</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Who can vote</span>
          <span class="te-detail-value">Agents with a lock; on a registry with member voting, one vote per member</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Vote weight</span>
          <span class="te-detail-value">From the lock; a lock without a period counts a hundredth. With member voting: one member, one vote, weighted by time as a member</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Duration</span>
          <span class="te-detail-value">Configurable in seconds (set at proposal creation)</span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Tally</span>
          <span class="te-detail-value">Auto-tally (configurable background worker) or manual <code>POST /governance/proposals/{id}/tally</code></span>
        </div>
        <div class="te-detail">
          <span class="te-detail-label">Registry scope</span>
          <span class="te-detail-value">Votes must be cast on the same registry as the proposal</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ SUPPLY INVARIANT ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Supply Invariant</h2>
      <p class="te-sub">The math must balance: always, across all registries.</p>
    </div>

    <div class="te-layers">
      <div class="te-layer">
        <div class="te-layer-num">1</div>
        <div class="te-layer-body">
          <h3 class="te-layer-title">The Formula</h3>
          <p class="te-layer-text"><code>tokens_issued − tokens_destroyed + transit_net == tokens_circulating</code>. Every unit in existence must be accounted for. No unit can appear from nowhere, no unit can vanish without a slashing event. This is the fundamental conservation law of the economy.</p>
        </div>
      </div>
      <div class="te-layer">
        <div class="te-layer-num">2</div>
        <div class="te-layer-body">
          <h3 class="te-layer-title">Self-Consistent Audit</h3>
          <p class="te-layer-text">The EventStore replays ALL events and computes both sides independently. No cross-system comparison: the audit runs entirely within the event ledger. Zero tolerance: any non-zero delta triggers a BREACH status. Verified at 48 transactions/second under full blast with delta = 0.0.</p>
        </div>
      </div>
      <div class="te-layer">
        <div class="te-layer-num">3</div>
        <div class="te-layer-body">
          <h3 class="te-layer-title">What Counts</h3>
          <p class="te-layer-text"><strong>tokens_issued</strong> = snapshot_baseline + SUM(<code>TokensIssued</code>) + SUM(<code>BalanceCorrected</code> positive) + SUM(<code>DisputeCompensationMinted</code>). <strong>tokens_circulating</strong> = SUM of all agent liquid + locked balances from projection, including treasury and fee_collector accounts. Both sides must match exactly.</p>
        </div>
      </div>
      <div class="te-layer">
        <div class="te-layer-num">4</div>
        <div class="te-layer-body">
          <h3 class="te-layer-title">On Breach</h3>
          <p class="te-layer-text">Automated lockdown. A <code>RegistryBlacklisted</code> event is emitted. All future financial events from that registry are rejected at the EventStore. Balances are frozen, not confiscated: the registry is economically quarantined until the discrepancy is resolved.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ FEE ECONOMICS FOR OPERATORS ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Fee Economics for Operators</h2>
      <p class="te-sub">Full economic sovereignty: your fees, your treasury, your rules.</p>
    </div>
    <div class="te-rules">
      <div class="te-rule" v-for="rule in rules" :key="rule">
        <span class="te-rule-check">&#x2713;</span>
        <span>{{ rule }}</span>
      </div>
    </div>
  </section>

  <!-- ═══ QUICK REFERENCE ═══ -->
  <section class="te-sec">
    <div class="te-sec-head">
      <h2 class="te-h2">Quick Reference</h2>
      <p class="te-sub">Key endpoints for units and fees.</p>
    </div>
    <div class="te-commands">
      <div class="te-cmd" v-for="cmd in commands" :key="cmd.label">
        <div class="te-cmd-label">{{ cmd.label }}</div>
        <code class="te-cmd-code">{{ cmd.code }}</code>
      </div>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="te-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/" class="te-btn te-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; Back to Home
    </router-link>
  </section>

  <footer class="te-footer">
    <div class="te-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="te-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/a2a-protocol">A2A Protocol</router-link>
        <router-link to="/federation">Federation Docs</router-link>
        <router-link to="/trust-reputation">Trust</router-link>
        <router-link to="/operator">Operator</router-link>
        <router-link to="/architecture">Architecture</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { governanceMode } from '@/services/membership/membership'

const { t } = useI18n()
// §LANDINGTRUTH: the unit and the DID issuer come from this registry, never a literal (a DID names its frame)
const { localCurrency, trustDomain, config: teCfg, readOk: teReadOk, readFailed: teReadFailed, reload: teReload } = useRegistryConfig()
// §LANDINGTRUTH (15): which governance this registry runs (governance_weight_mode), never assumed
// §LANDINGTRUTH (30): no mode until the registry has answered (an unread config reads as lock); a failed read says so
const teMode = computed(() => (teReadOk.value ? governanceMode(teCfg.value) : 'unknown'))
const teMember = computed(() => teMode.value === 'member')
const teLock = computed(() => teMode.value === 'lock')
const unit = computed(() => localCurrency.value || 'units')
const didIssuer = computed(() => (trustDomain.value || '').trim().toLowerCase() || '<frame>')

const rules = [
  'Fees are paid in units to your registry\'s fee account and stay inside the platform; on this network they are held by the network',
  'Cross-registry transfers: 0.5% goes to the receiving registry\'s TEG treasury',
  'Fee rates: held by the network on this network; your own on a standalone frame or your own network',
  'TheProtocol takes no share of your fees, ever. Zero platform tax on your operations',
  'Treasury issuance is disabled for federated operators: only a frame\'s own TEG issues new units, each frame in its own unit',
  'Your fee_collector account receives fees automatically on every intra-registry transfer',
]

const commands = [
  { label: 'Transfer units', code: 'POST /api/v1/teg/transfer  (agent JWT)' },
  { label: 'Check balance', code: 'GET /api/v1/teg/balance  (agent JWT)' },
  { label: 'Create proposal', code: 'POST /api/v1/governance/proposals  (agent JWT)' },
  { label: 'Cast vote', code: 'POST /api/v1/governance/proposals/{id}/vote  (agent JWT)' },
  { label: 'Supply audit', code: 'GET /api/v1/projections/supply-audit  (no auth)' },
]
</script>

<style scoped>
.te {
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
.te-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.te-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.te-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: teScan 12s linear infinite; }
@keyframes teScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.te-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.te-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.te-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

/* Hero */
.te-hero { position: relative; min-height: 60vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.te-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.te-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.te-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.te-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.te-accent { color: var(--cyan); }
.te-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 560px; }

/* Sections */
.te-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.te-sec-head { margin-bottom: 2rem; }
.te-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.te-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Big picture steps */
.te-steps { display: flex; flex-direction: column; gap: 24px; }
.te-step { display: flex; gap: 20px; align-items: flex-start; }
.te-step-num { width: 36px; height: 36px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.te-step-body { flex: 1; }
.te-step-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.te-step-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

/* Cards */
.te-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.te-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.te-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0 0 16px; }
.te-card-note { font-size: 12.5px; color: var(--muted); line-height: 1.6; margin: 16px 0 0; font-style: italic; }

/* Code blocks */
.te-code { background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 6px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.te-code-label { font-family: var(--mono); font-size: 11px; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 10px; font-weight: 600; }
.te-code pre { font-family: var(--mono); font-size: 12.5px; color: var(--green); line-height: 1.6; margin: 0; white-space: pre-wrap; }
code { font-family: var(--mono); font-size: 0.88em; color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.06); padding: 1px 5px; border-radius: 3px; }

/* Detail grids */
.te-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.te-detail { display: flex; flex-direction: column; gap: 2px; }
.te-detail-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.te-detail-value { font-size: 13px; color: var(--text); line-height: 1.5; }

/* 2-col flow */
.te-flow { display: flex; align-items: stretch; gap: 12px; margin-bottom: 16px; }
.te-flow-step { flex: 1; background: rgba(0,0,0,0.2); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
.te-flow-label { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 6px; }
.te-flow-desc { font-size: 12.5px; color: var(--text); line-height: 1.6; margin: 0; }
.te-flow-arrow { display: flex; align-items: center; font-size: 20px; color: var(--cyan); opacity: 0.4; flex-shrink: 0; }

/* Supply invariant layers */
.te-layers { display: flex; flex-direction: column; gap: 16px; }
.te-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.te-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.te-layer-body { flex: 1; }
.te-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.te-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }

/* Rules */
.te-rules { display: flex; flex-direction: column; gap: 10px; }
.te-rule { display: flex; align-items: flex-start; gap: 12px; font-size: 13.5px; line-height: 1.6; color: var(--text); }
.te-rule-check { color: var(--cyan); font-weight: 600; font-size: 14px; flex-shrink: 0; margin-top: 1px; }

/* Commands */
.te-commands { display: flex; flex-direction: column; gap: 12px; }
.te-cmd { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; }
.te-cmd-label { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; margin-bottom: 6px; font-weight: 600; text-transform: uppercase; }
.te-cmd-code { font-family: var(--mono); font-size: 12.5px; color: var(--green); display: block; line-height: 1.5; }

/* Buttons */
.te-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-decoration: none; cursor: pointer; transition: all 0.2s; font-family: var(--mono); border: none; }
.te-btn-ghost { background: transparent; color: var(--text); border: 1px solid rgba(255,255,255,0.12); }
.te-btn-ghost:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }

/* Footer */
.te-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.te-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
/* the links wrap whole on a phone, where the row ran past the screen ("Operator" cut off, "Units & Fees" on three
   lines; the camera, 2026-10-13) */
.te-footer-links { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.te-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; white-space: nowrap; }
.te-footer-links a:hover { color: var(--text-bright); }

@media (max-width: 640px) {
  .te-detail-grid { grid-template-columns: 1fr; }
  .te-flow { flex-direction: column; }
  .te-flow-arrow { transform: rotate(90deg); align-self: center; }
}
</style>
