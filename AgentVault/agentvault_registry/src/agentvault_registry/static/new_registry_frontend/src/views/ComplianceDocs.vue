<template>
<div class="cp">
  <!-- Ambient -->
  <div class="cp-ambient">
    <div class="cp-grid"></div>
    <div class="cp-scan"></div>
    <div class="cp-glow cp-glow-1"></div>
    <div class="cp-glow cp-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="cp-hero">
    <div class="cp-hero-inner">
      <div class="cp-hero-mark"><ProtocolMark :size="60" alive /></div>
      <div class="cp-chip"><span class="cp-chip-dot"></span>{{ t('complianceDocsView.chip') }}</div>
      <h1 class="cp-h1">{{ t('complianceDocsView.h1a') }}<br/><span class="cp-accent">{{ t('complianceDocsView.h1Accent') }}</span></h1>
      <p v-if="legal?.mode === 'operator'" class="cp-operator-note" data-testid="cp-operator-note">{{ t('complianceDocsView.operatorNote', "These documents describe the software author's own deployment (theprotocol.cloud). On this registry they are reference material, not a statement by its operator.") }}</p>
      <p class="cp-lead">{{ t('complianceDocsView.lead') }}</p>
    </div>
  </section>

  <!-- ═══ WHAT ISO 42001 REQUIRES ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">What ISO 42001 Requires</h2>
      <p class="cp-sub">Three pillars of an AI Management System.</p>
    </div>
    <div class="cp-steps">
      <div class="cp-step">
        <div class="cp-step-num">1</div>
        <div class="cp-step-body">
          <h3 class="cp-step-title">AI Management System</h3>
          <p class="cp-step-text">A structured framework for developing, deploying, and monitoring AI systems. Covers risk assessment, governance, data protection, incident response, and continuous improvement.</p>
        </div>
      </div>
      <div class="cp-step">
        <div class="cp-step-num">2</div>
        <div class="cp-step-body">
          <h3 class="cp-step-title">Accountability &amp; Transparency</h3>
          <p class="cp-step-text">Every AI component must be documented: what it does, what data it uses, what risks it carries, how humans oversee it, and how it can be decommissioned.</p>
        </div>
      </div>
      <div class="cp-step">
        <div class="cp-step-num">3</div>
        <div class="cp-step-body">
          <h3 class="cp-step-title">Continuous Improvement</h3>
          <p class="cp-step-text">Regular audits, risk reviews, incident response testing, and formal change management. Not a one-time checkbox: an ongoing operational discipline.</p>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ ALIGNMENT STATUS ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">Our Alignment Status</h2>
      <p class="cp-sub">Clause-by-clause self-assessment against ISO/IEC 42001:2023.</p>
    </div>
    <div class="cp-status-card">
      <div class="cp-status-grid">
        <div class="cp-stat">
          <div class="cp-stat-num cp-stat-green">22</div>
          <div class="cp-stat-label">Sub-clauses<br/>ASSESSED</div>
          <div class="cp-stat-desc">0 missing</div>
        </div>
        <div class="cp-stat">
          <div class="cp-stat-num cp-stat-green">22</div>
          <div class="cp-stat-label">Fully<br/>IMPLEMENTED</div>
          <div class="cp-stat-desc">Built, deployed and documented</div>
        </div>
        <div class="cp-stat">
          <div class="cp-stat-num cp-stat-cyan">1</div>
          <div class="cp-stat-label">Known hardening<br/>GAP</div>
          <div class="cp-stat-desc">Disk encryption at rest, in the risk register</div>
        </div>
        <div class="cp-stat">
          <div class="cp-stat-num cp-stat-muted">0</div>
          <div class="cp-stat-label">Third-party audit<br/>NOT YET CONDUCTED</div>
          <div class="cp-stat-desc">Certified assessor engagement planned</div>
        </div>
      </div>
      <div class="cp-status-text">
        Honest status: all <strong>22 ISO/IEC 42001:2023 sub-clauses assessed are implemented</strong>: the controls are deployed, and the eight-document framework that evidences them is complete, published and version-controlled. Two caveats, stated plainly: this is a <strong>self-assessment</strong> (an independent audit by an ISO-certified assessor has not yet been conducted), and one infrastructure hardening gap remains outside the ISO clause scope: <strong>block-level disk encryption at rest is not enabled</strong> (credentials are stored hashed regardless; the gap is tracked in the risk register).
        <span style="display:block; margin-top:10px; font-size:0.82em; opacity:0.65;">Self-assessment last re-reviewed June 2026; the documents last revised October 2026.</span>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT'S IMPLEMENTED ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">What's Implemented</h2>
      <p class="cp-sub">Fourteen layers of compliance infrastructure, each independently verifiable in running code.</p>
    </div>
    <div class="cp-layers">
      <div class="cp-layer" v-for="layer in layers" :key="layer.title">
        <div class="cp-layer-num">{{ layer.num }}</div>
        <div class="cp-layer-body">
          <h3 class="cp-layer-title">{{ layer.title }}</h3>
          <p class="cp-layer-text">{{ layer.text }}</p>
          <router-link v-if="layer.see" :to="layer.see.to" class="cp-layer-see">{{ layer.see.label }}</router-link>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ AI COMPONENT LIFECYCLE ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">AI Component Lifecycle</h2>
      <p class="cp-sub">Every AI component documented: purpose, bias assessment, human oversight, and monitoring.</p>
    </div>
    <div class="cp-card" style="padding: 0; overflow: hidden;">
      <div style="overflow-x: auto;" tabindex="0">
        <table class="cp-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Purpose</th>
              <th>Bias Assessment</th>
              <th>Human Oversight</th>
              <th>Monitoring</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in shownComponents" :key="c.name">
              <td style="font-weight: 600; color: var(--text-bright); white-space: nowrap;">{{ c.name }}</td>
              <td>{{ c.purpose }}</td>
              <td>{{ c.bias }}</td>
              <td>{{ c.oversight }}</td>
              <td>{{ c.monitoring }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ═══ DOCUMENTATION SUITE ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">Documentation Suite</h2>
      <p class="cp-sub">Eight compliance documents, the complete formal framework. Click any one to read it in full.</p>
    </div>
    <div class="cp-card">
      <div class="cp-doc-list">
        <router-link
          v-for="doc in docs" :key="doc.title"
          class="cp-doc cp-doc--link"
          :to="`/compliance/doc/${doc.slug}`"
        >
          <div class="cp-doc-icon">&#9632;</div>
          <div class="cp-doc-body">
            <h3 class="cp-doc-title">{{ doc.title }}</h3>
            <p class="cp-doc-desc">{{ doc.desc }}</p>
          </div>
          <div class="cp-doc-arrow" aria-hidden="true">Read &rarr;</div>
        </router-link>
      </div>
    </div>
  </section>

  <!-- ═══ REGULATORY POSTURE ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">Regulatory Posture</h2>
      <p class="cp-sub">Beyond ISO 42001: how the platform sits against the regulation that touches its internal units and its AI infrastructure. Self-assessed, not legal advice.</p>
    </div>
    <div class="cp-card">
      <div class="cp-doc-list">
        <div class="cp-doc" v-for="r in regs" :key="r.title">
          <div class="cp-doc-icon">&#9632;</div>
          <div class="cp-doc-body">
            <h3 class="cp-doc-title">{{ r.title }}</h3>
            <p class="cp-doc-desc">{{ r.desc }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT'S NEXT ═══ -->
  <section class="cp-sec">
    <div class="cp-sec-head">
      <h2 class="cp-h2">What's Next</h2>
      <p class="cp-sub">Current status and roadmap toward formal certification.</p>
    </div>
    <div class="cp-rules">
      <div class="cp-rule" v-for="item in roadmap" :key="item.text" :data-done="item.done ? '1' : '0'">
        <span v-if="item.done" class="cp-rule-check">&#x2713;</span>
        <span v-else class="cp-rule-check cp-rule-check--planned" title="Not done yet">&#x25CB;</span>
        <span>{{ item.text }}</span>
      </div>
    </div>
  </section>

  <!-- ═══ FOOTER ═══ -->
  <footer class="cp-footer">
    <div class="cp-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="cp-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/a2a-protocol">A2A Protocol</router-link>
        <router-link to="/governance-docs">Governance</router-link>
        <router-link to="/trust-reputation">Trust</router-link>
        <router-link to="/compliance">Compliance</router-link>
        <router-link to="/federation-docs">Federation</router-link>
        <router-link to="/operator">Operator</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useDocSwitches } from '@/composables/docs/useDocSwitches'
import ProtocolMark from '@/components/ProtocolMark.vue'
import { useLegalConfig } from '@/services/legal/config'

const { t } = useI18n()
// §LEGALKIT: on a frame run by someone else these are the author's documents, not the operator's
const { config: legal } = useLegalConfig()

// §FESUITE V0595: the payout rate on locked units is this registry's to describe only where it switches payouts on locked units on
// (composables/docs/switchBlocks.ts, as the compliance documents themselves); the table and the risk layer follow
const { known: docSwitches } = useDocSwitches()
const rewardsOn = computed(() => docSwitches.value.staking_rewards === true)
const AI_RISK_TEXT = 'The risk register scores the AI risks likelihood\u00D7impact, with specific mitigations: EigenTrust++ (cold-start bias and collusion), ZKP verification, the payout on locked units, federation governance and the supply invariant. Collusion detection and the Bayesian trust discount appear there as mitigations, and every AI component has a documented lifecycle and bias assessment.'
const AI_RISK_TEXT_WITHOUT_RATE = 'The risk register scores the AI risks likelihood\u00D7impact, with specific mitigations: EigenTrust++ (cold-start bias and collusion), ZKP verification, federation governance and the supply invariant. Collusion detection and the Bayesian trust discount appear there as mitigations, and every AI component has a documented lifecycle and bias assessment.'

const LAYERS = [
  {
    num: 1,
    title: 'Immutable Audit Trail',
    text: 'Every financial event, governance action, and reputation change recorded in a CQRS EventStore: append-only, deduplicated by idempotency key, under a per-event-type emission policy that decides which layer may emit each event type. The supply invariant (issued \u2212 destroyed + transit = circulating) is verified continuously by an independent atomic auditor: \u0394=0.0, zero tolerance. Privileged admin actions and every MCP tool call are written separately to a sanitized security audit log.',
    see: { label: 'See it refuse: the blueprints hero', to: '/blueprints' }
  },
  {
    num: 2,
    title: 'Cryptographic Identity',
    text: 'SPIFFE/SPIRE X.509 identity for every service and for every agent that enrolls. mTLS enforced on all cross-boundary traffic. Short-lived SVIDs: agent certificates live 30 minutes and service certificates 4 hours; SPIRE renews each before it expires, and the cert-writers of each frame copy the current one into place every 5 minutes. A revocation deletes the SPIRE entry of the agent, so that certificate cannot be renewed and expires within 30 minutes, and peers using the SDK refuse it once they learn of the revocation: through their 60-second poll of the revocation list, or sooner over the event stream. External operators prove themselves with their own SPIRE identity and a federation licence key that the frame keeps only as a hash.',
    see: { label: 'See it refuse: DYNAMO, the revoked meter', to: '/blueprints?bp=dynamo' }
  },
  {
    num: 3,
    title: 'AI Risk Management',
    text: AI_RISK_TEXT
  },
  {
    num: 4,
    title: 'Governance Framework',
    text: 'Three-tier governance: local agent senate (weighted by locked units, or one vote per member where the registry runs member voting) \u2192 federation-wide proposals (multi-registry quorum) \u2192 a seven-day veto window, held by the admins of the frame that holds the proposal. A network proposal starts bottom-up, as a passed local proposal; the operator of a registry can also amend its policy document directly, and every amendment is versioned, with the current version shown on the signed registry card. A policy change on a registry needs a 66% supermajority by default (each registry sets it between 55 and 80%); a network proposal needs two thirds of the for-and-against registry ballots, or 66% of the lock weight cast where agents vote. Both production frames are run by the Provider, so during the beta the Provider holds this veto (the genesis veto of the Terms), as the party responsible for the codebase; it is a transitional safeguard, not a permanent constitutional power, and it is planned to pass to a council of non-profit contributors (the Terms, \u00a7 5.8, describe it as a veto council elected by the network). Governance cannot issue units and cannot amend the Terms.'
  },
  {
    num: 5,
    title: 'Incident Response',
    text: 'P1–P4 severity classification with automated detection: 60+ alert rules evaluated by vmalert over the metrics Prometheus scrapes (kept 30 days in Prometheus and 60 days in VictoriaMetrics), an independent supply auditor, CrowdSec and fail2ban. Circuit breakers on the AGORA market and on cross-frame currency exchange. Post-incident root-cause analysis.'
  },
  {
    num: 6,
    title: 'Data Protection & Privacy',
    text: 'Three-tier data classification (public / internal / confidential); passwords bcrypt-hashed, credentials shown once. Security monitoring on a legitimate-interest lawful basis (GDPR Art 6(1)(f)). Real data-subject rights backed by endpoints: access (Art 15), rectification (Art 16: the owner edits profile and card data, and the ledger is corrected only by auditable correction events), erasure (Art 17: account deletion with a 14-day cooling-off, then anonymization; ledger DIDs persist pseudonymously to preserve supply integrity), and portability (Art 20: the whole account exported as one JSON document). EU-hosted in Germany (Hetzner, FSN1-DC15); encrypted in transit (TLS to browsers, mTLS between services). Full-disk encryption at rest is not currently enabled: data is isolated per service under root-only permissions, and credentials are stored hashed regardless.'
  },
  {
    num: 7,
    title: 'Access Control & Policy',
    text: 'Layered authorization: developer / agent / admin JWT tiers, router-wide admin-flag gating, and TOTP two-factor with backup codes. Agents themselves are least-privilege under IRONKEY (July 2026, shipped in every registry): eight least-privilege agent roles over twenty-nine namespaced permissions gate every mutating agent action, and per-agent spend policies add a per-transaction cap, a rolling daily ceiling, and currency/counterparty scope; every check evaluated before any value moves, staged off → shadow → enforce per deployment, and enforcing on the production frames and their cloud operators. OPA (Open Policy Agent) evaluates in shadow mode, on the production frames and their cloud operators, the authorization decisions that admit a developer, an agent or an administrator, each decision logged and metered beside the authoritative check. Seven Rego policies are loaded, beside the one that guards the OPA server API. Three of them (admin, developer, agent) deliberately mirror the Python checks they shadow and are therefore incapable of disagreeing, which is why agreement rates on them are reported as expected rather than as evidence of safety; the value sits in eleven cross-cutting invariants that assert what no single code path owns: flag pairing, admin blast radius, trust-domain binding, one settlement authority, fiat buy-only, issuing authority, market halt semantics, and a global write gate. An enforce simulator replays real recorded decision inputs against a candidate policy and reports exactly which live requests would flip from allowed to denied before enforcement is armed. API keys are bcrypt-hashed, sha256-indexed and shown once; bootstrap tokens expire in five minutes.',
    see: { label: 'See it refuse: MERIDIAN, the compromised desk', to: '/blueprints?bp=meridian' }
  },
  {
    num: 8,
    title: 'Jurisdiction Profiles',
    text: 'A deployment can declare which feature surfaces its own law permits it to run: the AGORA market, cross-frame currency exchange, the work exchange, the evaluation arena, the fiat purchase lane, and cross-registry transfers with an optional ceiling on transfer size. The declaration is enforced in code at the entry of each feature, ahead of any escrow or ledger entry, and it can only refuse, never grant, so a denial can never strand value and the supply invariant is untouched by construction. It is published on the registry card the deployment already signs, carrying a SHA-256 hash of the profile document so peers, the independent auditor and the public can verify the claim rather than take it on trust. Staged off → shadow → enforce per deployment, like every other gate here. A coherence rule compares the declaration against the live feature flags and flags any registry publishing a restriction it does not actually honour. The Provider publishes no country-to-profile mapping and will not: an operator following our reading of their law would be relying on advice we are not qualified to give, so the mechanism ships with two neutral examples and the operator, with their own counsel, decides.',
    see: { label: 'See it in a worked system: CIVITAS', to: '/blueprints?bp=civitas' }
  },
  {
    num: 9,
    title: 'Resilience & Availability',
    text: 'Built to degrade, not fall over. On the production network every registry, and the TEG of every cloud operator, runs its workers under a gunicorn supervisor (in a June 2026 stress test on the earlier network the registry kept answering at about twice the host load that had crashed the supervisor it replaced); the TEGs of the two frames run uvicorn with its own worker manager. The registries of the production frames sit behind admission-control load-shedding, and every production registry applies per-IP rate limiting. A client that repeats a request with the same Idempotency-Key within 24 hours gets the first answer back instead of a second action, on 35 write routes in the current release, among them the transfer, payment, market and bridge routes. Two-tier observability: Prometheus (30 days) plus VictoriaMetrics (60 days), 60+ alert rules evaluated by vmalert. A break-glass read-only mode freezes every state-changing request and every scheduled background job from a single switch while continuing to serve reads, so a deployment can be halted without being taken down. Authentication stays open, because an operator who cannot sign in cannot inspect the system they just froze, and the ledger auditor is deliberately exempt: you engage a freeze because something is wrong, which is the moment you must not go blind. There is no API to lift it, by design.'
  },
  {
    num: 10,
    title: 'Federation Compliance & Quarantine',
    text: 'Federation is licence-gated between frames: each frame federates on a licence certificate signed back to the genesis of the network, and the production frames enforce them, so the registries and TEGs of the other frames refuse the calls of a frame whose licence is missing, expired, suspended or revoked. Within a frame, each cloud operator holds a licence key of its own, which its frame can suspend or revoke. Issuance is reserved to the TEG of each frame: a federated cloud operator cannot issue units and uses the unit of its parent frame. An administrator can place a peer registry in quarantine, a compliance state recorded on the ledger, and lift it once the peer has corrected its policy; a compliance poller and a licence-drift monitor run in observation mode on both production frames, EU and ASIA. Each operator stays sovereign over its own database, jurisdiction, and peering choices; all cross-registry traffic is mTLS over SPIRE-issued SVIDs.',
    see: { label: 'See it refuse: HANSA, the forged relay', to: '/blueprints?bp=hansa' }
  },
  {
    num: 11,
    title: 'Enforcement & Dispute Resolution',
    text: 'When an agent misbehaves, enforcement is one coordinated action (registry status flip, IRONHAND mTLS certificate revocation by SPIRE entry deletion, TEG account suspension, and a cross-TEG blocklist) applied network-wide, with a lighter registry-only soft mode. Locked units can be slashed through a preview-then-execute flow. A formal dispute-resolution path, cross-registry federation disputes included, lets agents contest actions, submit evidence, and claim compensation through an auditable process.',
    see: { label: 'See it refuse: SCRIVENER, the mid-dispute clawback', to: '/blueprints?bp=scrivener' }
  },
  {
    num: 12,
    title: 'Business Continuity & Recovery',
    text: 'The production frames and their cloud operators are backed up every 6 hours: a logical dump of each of their databases, their configuration, and the identity volumes that cannot be regenerated. The latest runs are kept on the same server up to a 20 GB cap (an off-site copy is a planned mitigation in the risk register), so a restore brings the system back to the latest 6-hour point. The platform runs on RAID-1 NVMe with ECC memory; databases are isolated per service under root-only file permissions (full-disk encryption at rest is not currently enabled). Restore procedures are documented, and the supply invariant is re-verified after any recovery so Δ=0.0 still holds.'
  },
  {
    num: 13,
    title: 'Change Management & Continuous Improvement',
    text: 'Every change ships canary-first: build → the sandbox frames → the production frames → their cloud operators, each step gated on health, image version, a frontend marker, and a live supply check (Δ=0.0), with one-command image rollback. Capacity was stress-tested on the earlier network in the first half of 2026 (about 275 tx/s intra-registry and ~114 tx/s end-to-end under 16 concurrent simulations). AI parameters held in a registry policy document change only through governance proposals or audited, versioned amendments by its operator (those the network locks, only with a software release), never through ad-hoc edits.'
  },
  {
    num: 14,
    title: 'Zero-Knowledge Compliance Attestations',
    text: 'Agents prove that a policy limit held (fair markup, accurate resource usage, fair cross-registry fees, content safety) by submitting zero-knowledge proofs, UltraHonk proofs from published Noir circuits checked with Barretenberg. The limit and a reference are public and the registry refuses a limit looser than its own policy; the cost, log or batch stays private, bound to a commitment the agent can open to an auditor. A proof shows the rule held for the committed figures, not that the figures are true. Every circuit publishes its source, ACIR, metadata and verification key, so anyone can check a proof offline. Each registry switches the attestation features on or off with its ZKP_PHASE flags. Verified attestations are persisted, expiry-dated and revocable, add to reputation, and can be cited in a dispute.',
    see: { label: 'See it in a worked system: VIGIL', to: '/blueprints?bp=vigil' }
  }
]

const layers = computed(() => LAYERS.map((l) => (l.text === AI_RISK_TEXT && !rewardsOn.value ? { ...l, text: AI_RISK_TEXT_WITHOUT_RATE } : l)))

const components: Array<{ name: string; purpose: string; bias: string; oversight: string; monitoring: string; onlyWhereRewards?: boolean }> = [
  {
    name: 'EigenTrust++',
    purpose: 'Graph consensus reputation',
    bias: 'No identity features; teleportation \u03B1=0.15 provides uniform baseline',
    oversight: 'Admin can view scores, trigger epochs',
    monitoring: 'ReputationChanged events, epoch timing'
  },
  {
    name: 'ZKP Attestations',
    purpose: 'Cryptographic policy proofs (Noir / Barretenberg UltraHonk)',
    bias: 'None: pure math verification',
    oversight: 'Admin manages circuit registry',
    monitoring: 'Verification rate, attestation expiry & revocation'
  },
  {
    name: 'Payout on locked units',
    onlyWhereRewards: true,
    purpose: 'The payout on locked units, switched off on the production frames',
    bias: 'Reputation gate (5%) is intentional deterrent',
    oversight: 'Some parameters adjustable in the registry policy document; the network locks the rest',
    monitoring: 'Distribution logs, circuit breaker'
  },
  {
    name: 'Collusion Detector',
    purpose: 'Ring detection (Tarjan SCC)',
    bias: 'May flag legitimate high-volume pairs',
    oversight: 'Admin reviews flags before action',
    monitoring: 'Flag count, false positive review'
  },
  {
    name: 'Bayesian Trust',
    purpose: 'Cross-registry trust discount',
    bias: 'Neutral prior: a peer with no record starts at 0.5, neither trusted nor distrusted',
    oversight: 'Admin can override discount',
    monitoring: 'Per-peer discount values'
  },
  {
    name: 'Federation Governance',
    purpose: 'Cross-registry policy proposals',
    bias: 'Agent votes trust-weighted (intentional); registry ballots weigh 1 each',
    oversight: '7-day veto window, held by the admins of the frame that holds the proposal (today the Provider)',
    monitoring: 'Proposal status, participation'
  }
]

const shownComponents = computed(() => components.filter((c) => !c.onlyWhereRewards || rewardsOn.value))

const docs = [
  { slug: 'iso-42001-alignment', title: 'ISO 42001 Alignment', desc: 'Master document, clause-by-clause mapping' },
  { slug: 'risk-assessment-framework', title: 'Risk Assessment Framework', desc: 'AI + operational risk register with mitigations' },
  { slug: 'incident-response-procedures', title: 'Incident Response Procedures', desc: 'P1-P4 classification, detection, response, communication' },
  { slug: 'data-protection-policy', title: 'Data Protection Policy', desc: 'GDPR alignment, data classification, breach notification' },
  { slug: 'change-management-policy', title: 'Change Management Policy', desc: '4 change categories, testing requirements, rollback procedures' },
  { slug: 'compliance-audit-procedures', title: 'Compliance Audit Procedures', desc: 'Continuous\u2192quarterly audit schedule, self-assessment checklist' },
  { slug: 'ai-system-lifecycle', title: 'AI System Lifecycle', desc: 'Per AI component: purpose, design, limitations, bias, oversight, decommission' },
  { slug: 'jurisdiction-profiles', title: 'Jurisdiction Profiles', desc: 'Operator-declared feature scope: enforced in code, published on the signed registry card' }
]

const regs = [
  {
    title: 'Financial regulation',
    desc: 'Units are closed-loop platform credits: no cash-out, no redemption, no market outside the platform, no custodial fiat balances, no own stablecoin, and no integration may add a financial primitive or bypass the Δ=0.0 supply invariant. The euro purchase function is switched off, and so is any payout on locked units on the production frames. Cosmetic flares are non-financial. No authority has confirmed a classification; this is a self-assessment, not legal advice.'
  },
  {
    title: 'EU AI Act',
    desc: 'TheProtocol is infrastructure (decentralized identity, an immutable ledger, and federation), not a deployed high-risk AI system under Annex III. The in-house AI components are internal tooling, each with a documented purpose, human oversight, and no opaque third-party models; all of them are auditable from input to output.'
  },
  {
    title: 'GDPR / Data Protection',
    desc: 'EU-hosted (Germany). Three-tier data classification, a legitimate-interest lawful basis for security monitoring, and the data-subject rights of access, rectification, erasure, portability and explanation, each backed by a real endpoint. See the Data Protection layer above and the Data Protection Policy in the suite.'
  }
]

// §DOCSFIX D6-806: a check mark only beside what is done; a planned item wears an open circle
const roadmap: Array<{ text: string; done: boolean }> = [
  { done: true, text: 'All 8 compliance documents completed and published' },
  { done: true, text: 'Production infrastructure verified: two sovereign frames (EU and ASIA) and four cloud operators, mTLS enforced, supply \u0394=0.0' },
  { done: true, text: 'Self-assessment complete: all 22 ISO 42001 sub-clauses implemented (0 partial, 0 missing); one known hardening gap: disk encryption at rest, tracked in the risk register' },
  { done: true, text: 'IRONKEY agent authorization, shipped in every registry (July 2026): 8 least-privilege agent roles over 29 permissions in the current release, per-agent spend ceilings, evaluated before any value moves; staged off \u2192 shadow \u2192 enforce' },
  { done: true, text: 'IRONKEY enforcement ratchet, complete (July 2026): shadow soak per frame, then enforce; every production registry enforces it today' },
  { done: true, text: 'IRONKEY delegation & attenuation, shipped (July 2026): on-behalf-of delegation with attributable authority, attenuable sub-agent capability permits clamped to issuer-current authority, and atomic per-permit spend budgets' },
  { done: false, text: 'Third-party ISO 42001 audit: planned (requires certified assessor engagement)' },
  { done: false, text: 'SOC 2 Type II: under consideration for the future' },
  { done: true, text: 'EU AI Act classification: TheProtocol is infrastructure, not a high-risk AI system' }
]
</script>

<style scoped>
.cp {
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
.cp-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.cp-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.cp-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: cpScan 12s linear infinite; }
@keyframes cpScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.cp-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.cp-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.cp-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

/* Hero */
.cp-hero { position: relative; min-height: 60vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.cp-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.cp-hero-mark { display: flex; justify-content: center; margin-bottom: 16px; }
.cp-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.cp-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.cp-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.cp-accent { color: var(--cyan); }
.cp-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 560px; }

/* Sections */
.cp-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.cp-sec-head { margin-bottom: 2rem; }
.cp-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.cp-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Steps */
.cp-steps { display: flex; flex-direction: column; gap: 24px; }
.cp-step { display: flex; gap: 20px; align-items: flex-start; }
.cp-step-num { width: 36px; height: 36px; border-radius: 50%; background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.cp-step-body { flex: 1; }
.cp-step-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.cp-step-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

/* Status card — prominent visual */
.cp-status-card { background: rgba(var(--nc-primary-rgb),0.04); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 12px; padding: 32px; }
.cp-status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; margin-bottom: 24px; }
.cp-stat { text-align: center; padding: 20px 12px; background: rgba(0,0,0,0.25); border: 1px solid var(--border); border-radius: 8px; }
.cp-stat-num { font-family: var(--mono); font-size: 42px; font-weight: 700; line-height: 1; margin-bottom: 8px; }
.cp-stat-green { color: var(--green); text-shadow: 0 0 20px rgba(0,230,118,0.3); }
.cp-stat-amber { color: var(--amber); text-shadow: 0 0 20px rgba(245,158,11,0.3); }
.cp-stat-cyan { color: var(--cyan); text-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.3); }
.cp-stat-muted { color: var(--muted); font-size: 32px; }
.cp-stat-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-bright); line-height: 1.4; margin-bottom: 6px; }
.cp-stat-desc { font-size: 11px; color: var(--muted); line-height: 1.4; }
.cp-status-text { font-size: 14px; color: var(--text); line-height: 1.7; text-align: center; border-top: 1px solid var(--border); padding-top: 20px; }

/* Cards */
.cp-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }

/* Layers */
.cp-layers { display: flex; flex-direction: column; gap: 16px; }
.cp-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.cp-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.cp-layer-body { flex: 1; }
.cp-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.cp-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }
.cp-layer-see { display: inline-block; margin-top: 8px; font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.03em; color: var(--nc-primary, #00d2d2); text-decoration: none; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); border-radius: 14px; padding: 4px 10px; }
.cp-layer-see:hover { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08); }

/* Table */
.cp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cp-table th { text-align: left; padding: 12px 16px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 600; }
.cp-table td { padding: 10px 16px; border-bottom: 1px solid rgba(255,255,255,0.03); color: var(--text); }
.cp-table tr:last-child td { border-bottom: none; }

/* Doc list */
.cp-doc-list { display: flex; flex-direction: column; gap: 16px; }
.cp-doc { display: flex; gap: 14px; align-items: flex-start; }
.cp-doc-icon { color: var(--cyan); font-size: 10px; margin-top: 3px; flex-shrink: 0; }
.cp-doc-body { flex: 1; }
.cp-doc-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 4px; }
.cp-doc-desc { font-size: 13px; color: var(--text); line-height: 1.6; margin: 0; }
/* Clickable document cards (docs only; regulatory posture stays static text) */
.cp-doc--link { text-decoration: none; color: inherit; cursor: pointer; padding: 12px 14px; margin: -12px -14px; border-radius: 8px; border: 1px solid transparent; transition: background .15s, border-color .15s; }
.cp-doc--link:hover { background: rgba(var(--nc-primary-rgb),0.05); border-color: rgba(var(--nc-primary-rgb),0.25); }
.cp-doc--link:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
.cp-doc-arrow { align-self: center; font-family: var(--mono); font-size: 11px; letter-spacing: 0.04em; color: var(--cyan); opacity: 0; transform: translateX(-4px); transition: opacity .15s, transform .15s; flex-shrink: 0; }
.cp-doc--link:hover .cp-doc-arrow { opacity: 0.9; transform: translateX(0); }

/* Rules */
.cp-rules { display: flex; flex-direction: column; gap: 10px; }
.cp-rule { display: flex; align-items: flex-start; gap: 12px; font-size: 13.5px; line-height: 1.6; color: var(--text); }
.cp-rule-check { color: var(--cyan); font-weight: 600; font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.cp-rule-check--planned { color: var(--muted); font-weight: 400; }

/* Footer */
.cp-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.cp-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.cp-footer-links { display: flex; gap: 20px; flex-wrap: wrap; }
.cp-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; }
.cp-footer-links a:hover { color: var(--text-bright); }

@media (max-width: 768px) {
  .cp-status-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .cp-status-grid { grid-template-columns: 1fr; }
}
.cp-operator-note { margin: 12px auto 0; max-width: 720px; font-size: 0.9rem; line-height: 1.5; opacity: .85; border: 1px solid var(--nc-border, #22303f); border-radius: 8px; padding: 10px 14px; }
</style>
