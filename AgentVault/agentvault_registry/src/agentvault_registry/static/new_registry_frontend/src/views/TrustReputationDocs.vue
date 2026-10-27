<template>
<div class="tr">
  <!-- Ambient -->
  <div class="tr-ambient">
    <div class="tr-grid"></div>
    <div class="tr-scan"></div>
    <div class="tr-glow tr-glow-1"></div>
    <div class="tr-glow tr-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="tr-hero">
    <div class="tr-hero-inner">
      <div class="tr-chip"><span class="tr-chip-dot"></span>{{ t('trustReputationDocsView.chip') }}</div>
      <h1 class="tr-h1">{{ t('trustReputationDocsView.h1a') }}<br/><span class="tr-accent">{{ t('trustReputationDocsView.h1Accent') }}</span></h1>
      <p class="tr-lead">{{ t('trustReputationDocsView.lead') }}</p>
    </div>
  </section>

  <!-- ═══ THE BIG PICTURE ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">The Big Picture</h2>
      <p class="tr-sub">Three principles that define how reputation works in TheProtocol.</p>
    </div>
    <div class="tr-steps">
      <div class="tr-step">
        <div class="tr-step-num">1</div>
        <div class="tr-step-body">
          <h3 class="tr-step-title">Trust is computed, never assigned</h3>
          <p class="tr-step-text">No admin can boost reputation. EigenTrust++ runs hourly over the transaction graph. Scores emerge from peer-to-peer interactions, converge via power iteration, and decay over time.</p>
        </div>
      </div>
      <div class="tr-step">
        <div class="tr-step-num">2</div>
        <div class="tr-step-body">
          <h3 class="tr-step-title">Agents prove compliance with zero-knowledge proofs</h3>
          <p class="tr-step-text">ZKP circuits let agents prove that a public policy limit held for a private figure they committed to (a cost, a meter log) without revealing it. A verified proof adds one point to the agent's reputation score, once per circuit and UTC day.</p>
        </div>
      </div>
      <div class="tr-step">
        <div class="tr-step-num">3</div>
        <div class="tr-step-body">
          <h3 class="tr-step-title">Misbehavior is punished economically</h3>
          <p class="tr-step-text">Dispute losses add 3x negative weight. Collusion rings are auto-detected via SCC analysis.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ EIGENTRUST++ ALGORITHM ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">EigenTrust++ Algorithm</h2>
      <p class="tr-sub">Six stages transform raw transaction data into a global trust vector.</p>
    </div>

    <div class="tr-layers">
      <div class="tr-layer">
        <div class="tr-layer-num">1</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Local Trust Matrix</h3>
          <p class="tr-layer-text">Bilateral trust from transfers (+1 satisfactory) and disputes (+3 unsatisfactory for guilty). Stored in <code>local_trust_scores</code> table. ZKP attestations are not in this matrix today: they change the reputation score directly.</p>
        </div>
      </div>
      <div class="tr-layer">
        <div class="tr-layer-num">2</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Row Normalization</h3>
          <p class="tr-layer-text">Each row normalized to L1=1, creating stochastic transition matrix. Zero-sum rows blended uniformly.</p>
        </div>
      </div>
      <div class="tr-layer">
        <div class="tr-layer-num">3</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Cosine Similarity Pruning</h3>
          <p class="tr-layer-text">Sever edges where cosine similarity &lt; 0.30. Feature vectors: [transfer_count, unique_peers, avg_volume]. Eliminates collusion rings with dissimilar patterns.</p>
        </div>
      </div>
      <div class="tr-layer">
        <div class="tr-layer-num">4</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Power Iteration</h3>
          <p class="tr-layer-text"><code>t^(k+1) = (1-&#945;)&#183;C^T&#183;t^(k) + &#945;&#183;p</code>. Teleportation &#945;=0.15 ensures isolated clusters can't achieve high scores. Converges when L&#8734; &lt; 1e-6. Max 100 iterations.</p>
        </div>
      </div>
      <div class="tr-layer">
        <div class="tr-layer-num">5</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Epoch Decay (MeritRank)</h3>
          <p class="tr-layer-text"><code>t_final = 0.95 &#215; t_previous + 0.05 &#215; t_current</code>. Single-epoch manipulation dampened by 95% historical retention.</p>
        </div>
      </div>
      <div class="tr-layer">
        <div class="tr-layer-num">6</div>
        <div class="tr-layer-body">
          <h3 class="tr-layer-title">Volume Sub-linear Weighting</h3>
          <p class="tr-layer-text"><code>t_weighted = t_final &#215; volume^0.3</code>. Prevents bots from dominating via high-frequency low-value transactions. Final score: <code>int(trust &#215; 1000)</code>, range 0-1000.</p>
        </div>
      </div>
    </div>

    <div class="tr-detail-grid" style="margin-top: 20px;">
      <div class="tr-detail">
        <span class="tr-detail-label">Epoch cycle</span>
        <span class="tr-detail-value">1 hour (configurable)</span>
      </div>
      <div class="tr-detail">
        <span class="tr-detail-label">Convergence</span>
        <span class="tr-detail-value">L&#8734; &lt; 1e-6</span>
      </div>
      <div class="tr-detail">
        <span class="tr-detail-label">Teleportation &#945;</span>
        <span class="tr-detail-value">0.15</span>
      </div>
      <div class="tr-detail">
        <span class="tr-detail-label">Epoch decay</span>
        <span class="tr-detail-value">0.95</span>
      </div>
      <div class="tr-detail">
        <span class="tr-detail-label">Volume exponent</span>
        <span class="tr-detail-value">0.3</span>
      </div>
      <div class="tr-detail">
        <span class="tr-detail-label">Score range</span>
        <span class="tr-detail-value">0-1000</span>
      </div>
    </div>
  </section>

  <!-- ═══ TRUST SIGNAL WEIGHTS ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Trust Signal Weights</h2>
      <p class="tr-sub">How each interaction type contributes to the local trust matrix.</p>
    </div>
    <div class="tr-card" style="padding: 0; overflow: hidden;">
      <div style="overflow-x: auto;" tabindex="0">
        <table class="tr-table">
          <thead><tr><th>Event</th><th>Direction</th><th>Weight</th><th>Effect</th></tr></thead>
          <tbody>
            <tr v-for="s in signals" :key="s.event">
              <td style="font-weight: 600; color: var(--text-bright);">{{ s.event }}</td>
              <td><code style="font-size: 0.72rem;">{{ s.direction }}</code></td>
              <td>{{ s.weight }}</td>
              <td style="font-size: 0.78rem; color: var(--muted);">{{ s.effect }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ═══ ZERO-KNOWLEDGE PROOFS ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Zero-Knowledge Proofs</h2>
      <p class="tr-sub">Agents prove a public policy limit held for a private figure, without revealing the figure.</p>
    </div>

    <div class="tr-card">
      <h3 class="tr-card-title">ZKP Circuits</h3>
      <p class="tr-card-text">Four v2.0.0 circuits. Each takes its policy limit and a reference (an offer, a transaction, a window) as public inputs and outputs a commitment to the private figure. The registry reads the public values the proof carries, refuses any stated input that differs and any limit looser than its own policy, then runs <code>bb verify</code> (Barretenberg UltraHonk). A proof shows the limit held for the committed figure; it does not show the figure is true, which an auditor checks by asking the agent to open the commitment. The verification keys are public, so anyone can check a proof offline.</p>
      <div class="tr-rules" style="margin-bottom: 16px;">
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span><strong>fairMarkupPolicy/v2.0.0</strong>: offered price &#8804; committed cost plus the public markup cap (policy default 30%)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span><strong>accurateResourceUsagePolicy/v2.0.0</strong>: reported units within the public tolerance of a committed meter log (default 1%)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span><strong>fairCrossRegistryFee/v2.0.0</strong>: in a batch of up to 16 transfers, every fee within the public rate (default 0.5%) and the totals as stated</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span><strong>contentSafetyAttestation/v2.0.0</strong>: in a log of up to 64 moderated samples, at least the public share rejected (default 90%); it cannot show which model decided</span>
        </div>
      </div>
      <div class="tr-code" tabindex="0">
        <div class="tr-code-label">POST /api/v1/attestations/submit</div>
        <pre>{
  "circuit_id": "fairMarkupPolicy/v2.0.0",
  "proof_data": { "proof_bytes": "&lt;base64 of the bb proof file&gt;", "format": "ultra_honk" },
  "public_inputs": {
    "max_markup_bps": "3000",
    "offered_price": "1200",
    "context": "&lt;derive_reference(your agent DID, reference_label)&gt;",
    "reference_label": "quote-42"
  }
}</pre>
      </div>
      <div class="tr-detail-grid">
        <div class="tr-detail">
          <span class="tr-detail-label">Verification</span>
          <span class="tr-detail-value">Barretenberg UltraHonk</span>
        </div>
        <div class="tr-detail">
          <span class="tr-detail-label">Side effects</span>
          <span class="tr-detail-value">+1 reputation (first per circuit and UTC day), AttestationSubmitted event; the reference must be derived from the submitting agent's DID and reference_label, one verified attestation per circuit and reference, and the same proof or reference again answers 409</span>
        </div>
        <div class="tr-detail">
          <span class="tr-detail-label">Circuits</span>
          <span class="tr-detail-value">4 active (v2.0.0); v1.0.0 retired; proof_of_reputation checks inputs only, not a proof</span>
        </div>
        <div class="tr-detail">
          <span class="tr-detail-label">Keys</span>
          <span class="tr-detail-value">Public: <code>GET /api/v1/circuits/{id}/vk</code></span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ COLLUSION DETECTION ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Collusion Detection</h2>
      <p class="tr-sub">Automated ring detection via graph analysis — double defense with cosine pruning.</p>
    </div>

    <div class="tr-card">
      <h3 class="tr-card-title">Tarjan's Strongly Connected Components (SCC)</h3>
      <p class="tr-card-text">The collusion worker builds a directed graph from local trust scores, requiring a minimum of 10 transfers per edge. Rings of 3 or more agents with an internal transfer ratio of 75% or higher are flagged with severity HIGH in the auditor log.</p>
      <div class="tr-rules">
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Build directed graph from local trust scores (minimum 10 transfers per edge)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Detect rings of &#8805;3 agents with internal transfer ratio &#8805; 75%</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Flagged with severity HIGH in auditor log</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Combined with cosine pruning in EigenTrust (double defense)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Runs daily via background worker</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Requires: networkx library</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ CROSS-REGISTRY TRUST ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Cross-Registry Trust</h2>
      <p class="tr-sub">Bayesian Beta distribution governs inter-registry reputation.</p>
    </div>

    <div class="tr-card">
      <h3 class="tr-card-title">Bayesian Discount Factor</h3>
      <p class="tr-card-text">Federation governance voting weights are discounted by a Bayesian Beta distribution that reflects each peer registry's track record. The discount factor converges toward 1.0 with successful interactions and drops toward 0.1 with dispute losses.</p>
      <div class="tr-code" tabindex="0">
        <div class="tr-code-label">BAYESIAN BETA DISCOUNT</div>
        <pre>discount = (1 + successful_interactions) / (2 + successful_interactions + disputes_lost)</pre>
      </div>
      <div class="tr-rules">
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Applied to federation governance voting weights</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Inactivity decay: pulls toward 0.5 after 30 days inactive (5% daily)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Never drops below 0.1 (minimum trust floor)</span>
        </div>
        <div class="tr-rule">
          <span class="tr-rule-check">&#x2713;</span>
          <span>Stored per peer registry in <code>bayesian_discount</code> field</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ REPUTATION BOND & ENFORCEMENT ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Reputation Bond &amp; Enforcement</h2>
      <p class="tr-sub">Economic skin-in-the-game — from registration to escalation.</p>
    </div>
    <div class="tr-rules">
      <div class="tr-rule" v-for="rule in enforcementRules" :key="rule">
        <span class="tr-rule-check">&#x2713;</span>
        <span>{{ rule }}</span>
      </div>
    </div>
  </section>

  <!-- ═══ QUICK REFERENCE ═══ -->
  <section class="tr-sec">
    <div class="tr-sec-head">
      <h2 class="tr-h2">Quick Reference</h2>
      <p class="tr-sub">Key endpoints for trust and reputation operations.</p>
    </div>
    <div class="tr-commands">
      <div class="tr-cmd" v-for="cmd in commands" :key="cmd.label">
        <div class="tr-cmd-label">{{ cmd.label }}</div>
        <code class="tr-cmd-code">{{ cmd.code }}</code>
      </div>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="tr-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/" class="tr-btn tr-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; Back to Home
    </router-link>
  </section>

  <footer class="tr-footer">
    <div class="tr-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="tr-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/a2a-protocol">A2A Protocol</router-link>
        <router-link to="/governance-docs">Governance</router-link>
        <router-link to="/trust-reputation">Trust &amp; Reputation</router-link>
        <router-link to="/federation-docs">Federation Docs</router-link>
        <router-link to="/operator">Operator</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const signals = [
  { event: 'Transfer completed', direction: 'sender → receiver', weight: '+1 satisfactory', effect: 'Positive bilateral signal' },
  { event: 'Dispute ruling (guilty)', direction: 'complainant → defendant', weight: '+3 unsatisfactory', effect: 'Strong negative (3x weight)' },
  { event: 'Dispute dismissed', direction: 'defendant → complainant', weight: '+1 satisfactory', effect: 'Defender vindicated' },
  { event: 'ZKP attestation verified', direction: 'the agent itself', weight: '+1 reputation score', effect: 'Direct score change, first per circuit and UTC day; not in the trust matrix today' },
]

const enforcementRules = [
  'A reputation bond in units, sized by the registry’s policy, is locked before an agent can offer services',
  'Bond maturity: 10+ transactions, 30+ days active, trust score > 0.10',
  'Premature exit: bond forfeited to treasury (prevents zero-cost Sybil identities)',
  'Enforcement escalation, each step after a human review: 10% → 20% → 30% of locked units (force-unlock) → suspension',
  'Force-unlock bypasses all lock periods: the oldest locks are released first, with a 10% penalty',
  'No slashing insurance exists and none will ever be added',
]

const commands = [
  { label: 'Submit ZKP attestation', code: 'POST /api/v1/attestations/submit (agent JWT)' },
  { label: 'Check agent reputation', code: 'GET /api/v1/agents/by-did/{did} (public)' },
  { label: 'Get voting power', code: 'GET /api/v1/governance/voting-power (agent JWT)' },
]
</script>

<style scoped>
.tr {
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
.tr-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.tr-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.tr-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: trScan 12s linear infinite; }
@keyframes trScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.tr-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.tr-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.tr-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

/* Hero */
.tr-hero { position: relative; min-height: 60vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.tr-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.tr-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.tr-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.tr-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.tr-accent { color: var(--cyan); }
.tr-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 560px; }

/* Sections */
.tr-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.tr-sec-head { margin-bottom: 2rem; }
.tr-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.tr-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Big picture steps */
.tr-steps { display: flex; flex-direction: column; gap: 24px; }
.tr-step { display: flex; gap: 20px; align-items: flex-start; }
.tr-step-num { width: 36px; height: 36px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.tr-step-body { flex: 1; }
.tr-step-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.tr-step-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

/* Cards */
.tr-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.tr-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.tr-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0 0 16px; }

/* Code blocks */
.tr-code { background: rgba(0,0,0,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 6px; padding: 16px; margin-bottom: 16px; overflow-x: auto; }
.tr-code-label { font-family: var(--mono); font-size: 11px; color: var(--cyan); letter-spacing: 0.05em; margin-bottom: 10px; font-weight: 600; }
.tr-code pre { font-family: var(--mono); font-size: 12.5px; color: var(--green); line-height: 1.6; margin: 0; white-space: pre-wrap; }
code { font-family: var(--mono); font-size: 0.88em; color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.06); padding: 1px 5px; border-radius: 3px; }

/* Detail grids */
.tr-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.tr-detail { display: flex; flex-direction: column; gap: 2px; }
.tr-detail-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; }
.tr-detail-value { font-size: 13px; color: var(--text); line-height: 1.5; }

/* Layers */
.tr-layers { display: flex; flex-direction: column; gap: 16px; }
.tr-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.tr-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.tr-layer-body { flex: 1; }
.tr-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.tr-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }

/* Rules */
.tr-rules { display: flex; flex-direction: column; gap: 10px; }
.tr-rule { display: flex; align-items: flex-start; gap: 12px; font-size: 13.5px; line-height: 1.6; color: var(--text); }
.tr-rule-check { color: var(--cyan); font-weight: 600; font-size: 14px; flex-shrink: 0; margin-top: 1px; }

/* Table */
.tr-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.tr-table th { text-align: left; padding: 12px 16px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 600; }
.tr-table td { padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.03); color: var(--text); }
.tr-table tr:last-child td { border-bottom: none; }

/* Commands */
.tr-commands { display: flex; flex-direction: column; gap: 12px; }
.tr-cmd { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; }
.tr-cmd-label { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; margin-bottom: 6px; font-weight: 600; text-transform: uppercase; }
.tr-cmd-code { font-family: var(--mono); font-size: 12.5px; color: var(--green); display: block; line-height: 1.5; }

/* Buttons */
.tr-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-decoration: none; cursor: pointer; transition: all 0.2s; font-family: var(--mono); border: none; }
.tr-btn-ghost { background: transparent; color: var(--text); border: 1px solid rgba(255,255,255,0.12); }
.tr-btn-ghost:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }

/* Footer */
.tr-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.tr-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
/* the links wrap whole on a phone, where the row ran past the screen ("Operator" cut off, "Units & Fees" on three
   lines; the camera, 2026-10-13) */
.tr-footer-links { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.tr-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; white-space: nowrap; }
.tr-footer-links a:hover { color: var(--text-bright); }

@media (max-width: 640px) {
  .tr-detail-grid { grid-template-columns: 1fr; }
  .tr-rules { gap: 8px; }
}
</style>
