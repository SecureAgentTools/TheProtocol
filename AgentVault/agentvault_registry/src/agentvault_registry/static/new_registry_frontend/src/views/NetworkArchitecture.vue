<template>
<div class="arch">
  <!-- ══════════════════════════════════════════════════════════════════
       HERO — Sovereign Infrastructure
       ══════════════════════════════════════════════════════════════════ -->
  <section class="arch-hero">
    <div class="arch-grid-bg"></div>
    <div class="arch-hero-inner">
      <div class="arch-badge">
        <span class="arch-badge-dot"></span>
        {{ t('networkArchitectureView.badge') }}
      </div>
      <h1 class="arch-title">{{ t('networkArchitectureView.h1a') }}<br/>{{ t('networkArchitectureView.h1b') }}</h1>
      <p class="arch-subtitle">{{ t('networkArchitectureView.subtitle') }}</p>

      <!-- Live stats strip -->
      <div class="arch-stats">
        <div class="arch-stat" v-for="s in heroStats" :key="s.label">
          <span class="arch-stat-val" :style="{ color: s.color }">{{ s.value }}</span>
          <span class="arch-stat-lbl">{{ s.label }}</span>
        </div>
      </div>

      <!-- Mini topology -->
      <div class="arch-topo">
        <div class="arch-topo-node arch-topo-node--a">
          <span class="arch-topo-dot arch-topo-dot--green"></span>
          <span class="arch-topo-name">EU frame</span>
          <span class="arch-topo-loc">Brussels</span>
        </div>
        <div class="arch-topo-link">
          <div class="arch-topo-wire"></div>
          <div class="arch-topo-particle arch-topo-particle--fwd"></div>
          <div class="arch-topo-particle arch-topo-particle--rev"></div>
          <span class="arch-topo-proto">Federation</span>
        </div>
        <div class="arch-topo-node arch-topo-node--b">
          <span class="arch-topo-dot" :class="'arch-topo-dot--' + peerDot" :title="peerTitle" data-testid="arch-peer-dot"></span>
          <span class="arch-topo-name">ASIA frame</span>
          <span class="arch-topo-loc">Singapore</span>
        </div>
        <div class="arch-topo-link">
          <div class="arch-topo-wire"></div>
          <div class="arch-topo-particle arch-topo-particle--fwd"></div>
          <div class="arch-topo-particle arch-topo-particle--rev"></div>
          <span class="arch-topo-proto">Federation</span>
        </div>
        <div class="arch-topo-node arch-topo-node--op">
          <span class="arch-topo-dot arch-topo-dot--amber"></span>
          <span class="arch-topo-name">Cloud operators</span>
          <span class="arch-topo-loc">Amsterdam · Shenzhen · +2</span>
        </div>
      </div>
      <p class="arch-topo-note">Operators and developers set their own coordinates via registry settings. Locations are currently self-declared: jurisdiction binding is planned for a future release. {{ t('networkArchitectureView.fullMap', 'The whole system, component by component:') }} <router-link to="/docs/35" class="arch-topo-link-doc">{{ t('networkArchitectureView.fullMapLink', 'The Architecture') }}</router-link>.</p>
    </div>
    <div class="arch-hero-fade"></div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════════
       ARCHITECTURE DIAGRAM — Interactive 5-Layer
       ══════════════════════════════════════════════════════════════════ -->
  <section class="arch-section">
    <div class="arch-section-head">
      <h2 class="arch-h2">Network Architecture</h2>
      <p class="arch-section-sub">Click any layer to explore. Select a flow to trace data through the stack.</p>
    </div>

    <!-- Flow selector -->
    <div class="arch-flows">
      <button
        v-for="f in flows" :key="f.id"
        class="arch-flow-btn"
        :class="{ 'arch-flow-btn--active': activeFlow === f.id }"
        @click="activeFlow = activeFlow === f.id ? null : f.id"
      >
        <span class="arch-flow-icon">{{ f.icon }}</span>
        {{ f.label }}
      </button>
    </div>

    <!-- The diagram -->
    <div class="arch-diagram" :class="activeFlow ? `arch-diagram--flow-${activeFlow}` : ''">

      <!-- Layer 6: Developer Gateway -->
      <div class="arch-layer arch-layer--gateway" :class="{ 'arch-layer--open': expanded === 'gateway', 'arch-layer--lit': flowLights('gateway') }" @click="toggle('gateway')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">06</span>
          <span class="arch-layer-label">DEVELOPER GATEWAY</span>
          <span class="arch-layer-tech">How you connect: SDK, MCP, REST API, Docker</span>
          <span class="arch-layer-chevron">{{ expanded === 'gateway' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--gw">
            <span class="arch-node-dot arch-node-dot--green"></span>
            <span class="arch-node-name">SDK</span>
            <span class="arch-node-sub">pip install</span>
          </div>
          <div class="arch-node arch-node--gw">
            <span class="arch-node-dot arch-node-dot--purple"></span>
            <span class="arch-node-name">MCP</span>
            <span class="arch-node-sub">19 tools</span>
          </div>
          <div class="arch-node arch-node--gw">
            <span class="arch-node-dot arch-node-dot--cyan"></span>
            <span class="arch-node-name">REST API</span>
            <span class="arch-node-sub">200+ endpoints</span>
          </div>
          <div class="arch-node arch-node--gw">
            <span class="arch-node-dot arch-node-dot--amber"></span>
            <span class="arch-node-name">Templates</span>
            <span class="arch-node-sub">Docker download</span>
          </div>
        </div>
        <div v-if="expanded === 'gateway'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">SDK</span><span class="arch-detail-v">theprotocol-sdk (Python, ships with operator bundle)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">MCP</span><span class="arch-detail-v">Claude Code CLI + Claude Desktop</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">API Auth</span><span class="arch-detail-v">JWT, API Key, Bootstrap Token</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Templates</span><span class="arch-detail-v">Full-Capacity, PPAO, Minimal Starter</span></div>
          </div>
        </div>
      </div>

      <!-- Connector -->
      <div class="arch-conn"><div class="arch-conn-line"><div class="arch-conn-particle" style="animation-delay: 0.2s"></div></div></div>

      <!-- Layer 5: Agent Mesh -->
      <div class="arch-layer" :class="{ 'arch-layer--open': expanded === 'agents', 'arch-layer--lit': flowLights('agents') }" @click="toggle('agents')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">05</span>
          <span class="arch-layer-label">AGENT MESH</span>
          <span class="arch-layer-tech">A2A v1.0 / JSON-RPC 2.0 / Payment Authorizations</span>
          <span class="arch-layer-chevron">{{ expanded === 'agents' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--agent" v-for="a in agentNodes" :key="a.name">
            <span class="arch-node-dot" :class="a.paid ? 'arch-node-dot--amber' : 'arch-node-dot--green'"></span>
            <span class="arch-node-name">{{ a.name }}</span>
            <span v-if="a.price" class="arch-node-price">{{ a.price }}</span>
          </div>
        </div>
        <div v-if="expanded === 'agents'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">Protocol</span><span class="arch-detail-v">A2A v1.0 (Google spec)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Payment</span><span class="arch-detail-v">apt_ tokens, SDK PaymentVerifier</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Service Agents</span><span class="arch-detail-v">{{ shown(net.totalAgents) }} registered</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Pricing</span><span class="arch-detail-v">0.1 to 5.0 units per request</span></div>
          </div>
        </div>
      </div>

      <!-- Connector -->
      <div class="arch-conn"><div class="arch-conn-line"><div class="arch-conn-particle"></div></div></div>

      <!-- Layer 4: Sovereign Registries -->
      <div class="arch-layer" :class="{ 'arch-layer--open': expanded === 'registry', 'arch-layer--lit': flowLights('registry') }" @click="toggle('registry')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">04</span>
          <span class="arch-layer-label">SOVEREIGN REGISTRIES</span>
          <span class="arch-layer-tech">FastAPI / PostgreSQL / 4 workers / Redis</span>
          <span class="arch-layer-chevron">{{ expanded === 'registry' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--registry">
            <span class="arch-node-dot arch-node-dot--green"></span>
            <span class="arch-node-name">Registry A</span>
            <span class="arch-node-sub">Port 8000 · Freilassing</span>
          </div>
          <div class="arch-node-link">
            <div class="arch-node-link-wire"></div>
            <div class="arch-node-link-particle"></div>
          </div>
          <div class="arch-node arch-node--registry">
            <span class="arch-node-dot" :class="'arch-node-dot--' + peerDot" :title="peerTitle"></span>
            <span class="arch-node-name">Registry B</span>
            <span class="arch-node-sub">Port 8001 · London</span>
          </div>
        </div>
        <div v-if="expanded === 'registry'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">Containers</span><span class="arch-detail-v">2 registries + 2 PostgreSQL + Redis</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Auth</span><span class="arch-detail-v">JWT (dev + agent) / API Key / Bootstrap Token</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">MCP</span><span class="arch-detail-v">{{ shown(net.mcpTools) }} tools (Claude Code + Desktop)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Background</span><span class="arch-detail-v">13 workers (leader-elected via Redis)</span></div>
          </div>
        </div>
      </div>

      <div class="arch-conn"><div class="arch-conn-line"><div class="arch-conn-particle" style="animation-delay: 0.4s"></div></div></div>

      <!-- Layer 3: Units & Fees. §BAFIN (agentvault2-d6, 2026-10-23, agentvault2-56's finding): a public page names the
           layer as the sibling pages do (Units & Fees), not "Token Economy" -->
      <div class="arch-layer" :class="{ 'arch-layer--open': expanded === 'teg', 'arch-layer--lit': flowLights('teg') }" @click="toggle('teg')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">03</span>
          <span class="arch-layer-label">UNITS &amp; FEES</span>
          <span class="arch-layer-tech">{{ archMember ? 'TEG Layer / Frame Currency / Membership Governance' : archMode === 'lock' ? 'TEG Layer / Frame Currency / Locks / Weighted Governance' : 'TEG Layer / Frame Currency / Governance' }}</span>
          <span class="arch-layer-chevron">{{ expanded === 'teg' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--teg">
            <span class="arch-node-dot arch-node-dot--amber"></span>
            <span class="arch-node-name">TEG A</span>
            <span class="arch-node-sub">Ledger service</span>
          </div>
          <div class="arch-node-link">
            <div class="arch-node-link-wire arch-node-link-wire--amber"></div>
            <div class="arch-node-link-particle arch-node-link-particle--amber"></div>
          </div>
          <div class="arch-node arch-node--teg">
            <span class="arch-node-dot arch-node-dot--amber"></span>
            <span class="arch-node-name">TEG B</span>
            <span class="arch-node-sub">2PC Cross-TEG Coordination</span>
          </div>
        </div>
        <div v-if="expanded === 'teg'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">Locked</span><span class="arch-detail-v">{{ shown(net.tvl) }} units</span></div>
            <div v-if="archRatesOn" class="arch-detail-item"><span class="arch-detail-k">Payout rate</span><span class="arch-detail-v">{{ net.apy == null ? '—' : net.apy + '%' }} (logistic decay)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Fees</span><span class="arch-detail-v">{{ archFeeText }}</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Governance</span><span class="arch-detail-v">{{ archMode === 'unknown' ? '' : (archMember ? 'one vote per member, weighted by time as a member' : 'weighted by locked units') + ' · ' }}{{ shown(net.proposals) }} proposals</span></div>
          </div>
        </div>
      </div>

      <div class="arch-conn"><div class="arch-conn-line"><div class="arch-conn-particle" style="animation-delay: 0.8s"></div></div></div>

      <!-- Layer 2: Event Ledger -->
      <div class="arch-layer" :class="{ 'arch-layer--open': expanded === 'events', 'arch-layer--lit': flowLights('events') }" @click="toggle('events')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">02</span>
          <span class="arch-layer-label">IMMUTABLE LEDGER</span>
          <span class="arch-layer-tech">CQRS Event Store / Projection Snapshots / Supply Audit</span>
          <span class="arch-layer-chevron">{{ expanded === 'events' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--es arch-node--wide">
            <span class="arch-node-dot arch-node-dot--green"></span>
            <span class="arch-node-name">Event Store</span>
            <span class="arch-node-sub">Supply Invariant: delta = 0.0</span>
          </div>
        </div>
        <div v-if="expanded === 'events'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">Architecture</span><span class="arch-detail-v">CQRS append-only event sourcing</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Deduplication</span><span class="arch-detail-v">Idempotency keys (409 → success)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Emission Policy</span><span class="arch-detail-v">32 per-event-type rules (f037)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Throughput</span><span class="arch-detail-v">3,000–5,000 events/sec ingestion capacity (batch consumer)</span></div>
          </div>
        </div>
      </div>

      <div class="arch-conn"><div class="arch-conn-line"><div class="arch-conn-particle" style="animation-delay: 1.2s"></div></div></div>

      <!-- Layer 1: Identity Fabric -->
      <div class="arch-layer" :class="{ 'arch-layer--open': expanded === 'identity', 'arch-layer--lit': flowLights('identity') }" @click="toggle('identity')">
        <div class="arch-layer-bar">
          <span class="arch-layer-num">01</span>
          <span class="arch-layer-label">ZERO-TRUST IDENTITY</span>
          <span class="arch-layer-tech">SPIFFE / SPIRE / OPA / mTLS / DIDs</span>
          <span class="arch-layer-chevron">{{ expanded === 'identity' ? '−' : '+' }}</span>
        </div>
        <div class="arch-layer-nodes">
          <div class="arch-node arch-node--id">
            <span class="arch-node-dot arch-node-dot--purple"></span>
            <span class="arch-node-name">SPIRE Server</span>
            <span class="arch-node-sub">Workload attestation</span>
          </div>
          <div class="arch-node arch-node--id">
            <span class="arch-node-dot arch-node-dot--purple"></span>
            <span class="arch-node-name">OPA</span>
            <span class="arch-node-sub">Policy enforcement</span>
          </div>
          <div class="arch-node arch-node--id">
            <span class="arch-node-dot arch-node-dot--purple"></span>
            <span class="arch-node-name">mTLS Sidecars</span>
            <span class="arch-node-sub">Cert rotation</span>
          </div>
        </div>
        <div v-if="expanded === 'identity'" class="arch-layer-detail">
          <div class="arch-detail-grid">
            <div class="arch-detail-item"><span class="arch-detail-k">Identity</span><span class="arch-detail-v">did:theprotocol: (decentralized)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">SPIFFE IDs</span><span class="arch-detail-v">spiffe://theprotocol.cloud/ns/...</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Networks</span><span class="arch-detail-v">Main + Identity (isolated)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Enforcement</span><span class="arch-detail-v">mTLS enforced on all cross-boundary traffic (federation sync + EventStore writes)</span></div>
            <div class="arch-detail-item"><span class="arch-detail-k">Components</span><span class="arch-detail-v">SPIRE Server + Agent + 5 cert writers + 3 nginx mTLS sidecars</span></div>
          </div>
        </div>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════════
       SECURITY — Seven-Layer Defense
       ══════════════════════════════════════════════════════════════════ -->
  <section class="arch-section">
    <div class="arch-section-head">
      <h2 class="arch-h2">Seven-Layer Defense</h2>
      <p class="arch-section-sub">Defense in depth. Every layer independently enforced.</p>
    </div>
    <div class="arch-tower">
      <div class="arch-tower-layer" v-for="(s, i) in securityLayers" :key="s.name" :style="{ animationDelay: `${i * 0.08}s` }">
        <span class="arch-tower-num">{{ 7 - i }}</span>
        <div class="arch-tower-content">
          <span class="arch-tower-name">{{ s.name }}</span>
          <span class="arch-tower-desc">{{ s.desc }}</span>
        </div>
        <span class="arch-tower-tech">{{ s.tech }}</span>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════════
       DEPLOYMENT — Operator Tiers
       ══════════════════════════════════════════════════════════════════ -->
  <section class="arch-section">
    <div class="arch-section-head">
      <h2 class="arch-h2">Operator Deployment</h2>
      <p class="arch-section-sub">Pre-built Docker images. Two deployment modes. Zero revenue share to TheProtocol.</p>
    </div>
    <div class="arch-tiers">
      <div class="arch-tier" v-for="tier in tiers" :key="tier.name" :class="`arch-tier--${tier.id}`">
        <div class="arch-tier-head">
          <span class="arch-tier-icon">{{ tier.icon }}</span>
          <h3 class="arch-tier-name">{{ tier.name }}</h3>
        </div>
        <ul class="arch-tier-specs">
          <li v-for="s in tier.specs" :key="s">{{ s }}</li>
        </ul>
        <div class="arch-tier-tag">{{ tier.tag }}</div>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════════
       FOOTER — Live Pulse
       ══════════════════════════════════════════════════════════════════ -->
  <footer class="arch-footer">
    <div class="arch-footer-inner">
      <div class="arch-footer-item" v-for="f in footerStats" :key="f.label">
        <span class="arch-footer-dot" :style="{ background: f.color }"></span>
        <span class="arch-footer-val">{{ f.value }}</span>
        <span class="arch-footer-lbl">{{ f.label }}</span>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { governanceMode } from '@/services/membership/membership'

const { t } = useI18n()

// ── State ───────────────────────────────────────────────────────────────
const expanded = ref<string | null>(null)
const activeFlow = ref<string | null>(null)
// §FESUITE (V0578): the peer dot has three states. With the peers read and the network-stats read both failed it was
// drawn dim, which is how this page draws a peer that is not active; a peer this page could not read is drawn as a ring.
const peerState = ref<'unread' | 'active' | 'quiet'>('unread')
const peerDot = computed(() => (peerState.value === 'active' ? 'cyan' : peerState.value === 'quiet' ? 'dim' : 'unread'))
const peerTitle = computed(() => (peerState.value === 'unread' ? 'Not read' : undefined))

// §BAFIN (2026-10-01): no payout rate where this registry pays none (core/staking_gate.py).
const { config: archRegCfg, readOk: archReadOk } = useRegistryConfig()
// §LANDINGTRUTH (17/18): the governance row and the layer's tech line follow the governance this registry runs
// (governance_weight_mode); membership is the production model since V0564 (his word 2026-10-03)
// §LANDINGTRUTH (30): no mode until the registry has answered (an unread config reads as lock)
const archMode = computed(() => (archReadOk.value ? governanceMode(archRegCfg.value) : 'unknown'))
const archMember = computed(() => archMode.value === 'member')
// The fee figures come from this registry's signed card, as on /monetize and /pricing. /teg/fees answers
// {fee, fee_currency} and carries no fee_rate, so the intra figure read nothing, and the cross one was a literal.
const archFees = ref<{ base: number; max: number; cross: number } | null>(null)
const archPct = (n: number) => `${Number(n.toFixed(2))}%`
const archFeeText = computed(() => archFees.value
  ? `${archPct(archFees.value.base)} to ${archPct(archFees.value.max)} intra · +${archPct(archFees.value.cross)} cross`
  : '—')
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const archRatesOn = computed(() => archRegCfg.value.staking_rewards_enabled === true)

// §FESUITE (the loading sweep): every figure is null until its own read answered, and stays null when that read failed.
// The page drew "0 agents" and "0%" health while its reads were out, and on a failed read it drew invented figures as
// fact: 100% health and uptime, 3 registries, 19 MCP tools, a 0.5% fee. Unknown is drawn as the page's dash.
const net = ref<{
  totalAgents: number | null; activeRegistries: number | null; totalRegistries: number | null; networkHealth: number | null
  tvl: string | null; apy: string | null; feeRate: string | null
  mcpTools: number | null; proposals: number | null; totalStakers: number | null
}>({
  totalAgents: null, activeRegistries: null, totalRegistries: null, networkHealth: null,
  tvl: null, apy: null, feeRate: null,
  mcpTools: null, proposals: null, totalStakers: null,
})
const shown = (x: number | string | null): string => (x == null ? '—' : String(x))

// ── Data flow definitions ───────────────────────────────────────────────
const flows = [
  { id: 'onboard', label: 'Agent Onboarding', icon: '→', layers: ['gateway', 'agents', 'registry', 'teg', 'events'] },
  { id: 'payment', label: 'A2A Payment', icon: '⇄', layers: ['gateway', 'agents', 'registry', 'teg'] },
  { id: 'transfer', label: 'Cross-Registry', icon: '⬡', layers: ['registry', 'teg', 'events'] },
  { id: 'audit', label: 'Supply Audit', icon: '◎', layers: ['events'] },
]

function flowLights(layer: string): boolean {
  if (!activeFlow.value) return false
  const f = flows.find(fl => fl.id === activeFlow.value)
  return f ? f.layers.includes(layer) : false
}

function toggle(id: string) {
  expanded.value = expanded.value === id ? null : id
}

// ── Agent nodes for diagram ─────────────────────────────────────────────
const agentNodes = [
  { name: 'Gerald', paid: false, price: '' },
  { name: 'SYBIL', paid: true, price: '5.0' },
  { name: 'Weather', paid: true, price: '0.5' },
  { name: 'Currency', paid: true, price: '0.5' },
  { name: 'DNS/SSL', paid: true, price: '1.0' },
  { name: '+8 more', paid: true, price: '' },
]

// ── Security layers ─────────────────────────────────────────────────────
const securityLayers = [
  { name: 'EventStore mTLS', desc: 'Enforced mutual TLS for all external event writes via SPIRE SVIDs', tech: 'X.509' },
  { name: 'ZKP Attestation', desc: 'Zero-knowledge proofs that a public policy limit held for a committed private figure, verified over published circuits and keys', tech: 'UltraHonk' },
  { name: 'EigenTrust Reputation', desc: 'Distributed trust computation across the network', tech: 'PageRank' },
  { name: 'Supply Invariant', desc: 'Self-consistent audit: tokens_issued − tokens_destroyed + transit_net == circulating', tech: 'CQRS' },
  { name: 'Emission Policy', desc: 'Per-event-type authorization gates', tech: 'f037' },
  { name: 'OPA Policy Engine', desc: 'Policy decisions checked in shadow beside the code, on frames that run the kit', tech: 'Rego' },
  { name: 'SPIFFE mTLS', desc: 'Mutual TLS with auto-rotating SVID certificates', tech: 'X.509' },
]

// ── Deployment tiers ────────────────────────────────────────────────────
const tiers = [
  {
    id: 'federated', name: 'Federated', icon: '◆',
    specs: ['10 containers (incl. SPIFFE/SPIRE identity and two mTLS gateways)', '2.5 GB RAM minimum', 'Writes to its parent frame’s event store over mTLS', 'The TEG requires mTLS: no API key fallback', 'Issuance disabled (supply integrity)', 'Zero-trust mTLS on all cross-boundary traffic', 'Custom fee rates within bounds'],
    tag: 'Recommended for operators',
  },
  {
    id: 'standalone', name: 'Standalone', icon: '◇',
    specs: ['12 services, one a one-shot init', '3 GB RAM minimum', 'Local EventStore (air-gapped)', 'Its own unit, supply and issuance', 'No federation, private economy', 'Full parameter sovereignty'],
    tag: 'Air-gapped / private',
  },
  {
    id: 'enterprise', name: 'Production HQ', icon: '⬢',
    specs: ['Every frame and operator in its own stack', '128 GB ECC RAM', '4 workers per service, Redis coordination', 'Two production frames (EU, ASIA), a sandbox pair and their cloud operators', 'Prometheus + Grafana + Alertmanager', 'SPIFFE/SPIRE identity fabric + EventStore mTLS'],
    tag: 'TheProtocol genesis server',
  },
]

// ── Computed stats ──────────────────────────────────────────────────────
const heroStats = computed(() => [
  { value: shown(net.value.totalAgents), label: 'Agents', color: 'var(--nc-primary)' },
  { value: shown(net.value.totalRegistries), label: 'Registries', color: '#00e676' },
  { value: net.value.networkHealth == null ? '—' : `${net.value.networkHealth}%`, label: 'Health',
    color: net.value.networkHealth == null ? 'var(--nc-text-muted, #94a3b8)' : net.value.networkHealth >= 90 ? '#00e676' : '#f59e0b' },
  // §BAFIN (2026-10-23): the figure is units in locks, as the footer and the layer's detail call it; "Staked" spoke
  // of locking on registries that run none (STAKING_ENABLED=false on EU and ASIA)
  { value: shown(net.value.tvl), label: 'In locks', color: '#f59e0b' },
])

const footerStats = computed(() => [
  { value: net.value.totalAgents == null ? '—' : `${net.value.totalAgents} agents`, label: 'registered', color: 'var(--nc-primary)' },
  { value: shown(net.value.tvl), label: 'units in locks', color: '#f59e0b' },
  ...(archRatesOn.value ? [{ value: net.value.apy == null ? '—' : net.value.apy + '%', label: 'payout rate on locks', color: '#00e676' }] : []),
  { value: shown(net.value.mcpTools), label: 'MCP tools', color: '#a78bfa' },
  // a figure this page never reads is not drawn as one: the registry's supply auditor checks the delta continuously
  { value: 'Audited', label: 'supply delta, checked continuously', color: 'var(--nc-primary)' },
  { value: net.value.networkHealth == null ? '—' : `${net.value.networkHealth}%`, label: 'uptime', color: '#00e676' },
])

// ── Fetch live data ─────────────────────────────────────────────────────
onMounted(async () => {
  fetch(`${window.location.origin}/.well-known/registry-card.json`, { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then(c => {
      const f = c?.fees
      const base = Number(f?.intra_registry?.base_rate_percent)
      const max = Number(f?.intra_registry?.max_rate_percent)
      if (Number.isFinite(base) && Number.isFinite(max)) archFees.value = { base, max, cross: Number(f?.cross_registry?.base_rate_percent ?? 0) || 0 }
    })
    .catch(() => { /* no card: the fee row reads the dash, never a guessed number */ })
  const endpoints = [
    fetch('/api/v1/federation/network-stats'),
    fetch('/api/v1/staking/global-stats'),
    fetch('/api/v1/governance/stats'),
    fetch('/api/v1/teg/fees'),
    fetch('/mcp/health'),
    fetch('/api/v1/federation/registries'),
  ]

  // an answer that is not 2xx carries an error body, not the figures: it is a failed read (no "0" made of an error)
  const results = await Promise.allSettled(endpoints.map(p => p.then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))))
  const get = (i: number) => results[i]?.status === 'fulfilled' ? (results[i] as any).value : null

  const ns = get(0)
  const ss = get(1)
  const gs = get(2)
  const fees = get(3)
  const mcp = get(4)
  const peers = get(5)

  net.value.totalAgents = ns?.totalAgents ?? null
  net.value.activeRegistries = ns?.activeRegistries ?? null
  net.value.totalRegistries = ns?.totalRegistries ?? null
  net.value.networkHealth = ns?.networkHealth != null ? Math.round(ns.networkHealth) : null

  net.value.tvl = ss?.totalValueLocked != null
    ? Number(ss.totalValueLocked).toLocaleString(appLocale(), { maximumFractionDigits: 0 })
    : null
  net.value.apy = ss?.averageApy != null ? Number(ss.averageApy).toFixed(1) : null
  net.value.totalStakers = ss?.totalStakers ?? null

  net.value.proposals = gs?.totalProposals ?? null
  net.value.feeRate = fees?.fee_rate != null ? `${(fees.fee_rate * 100).toFixed(1)}%` : null
  net.value.mcpTools = mcp?.tools_available ?? null

  // Check peer status — public endpoint uses federation_status, admin uses status
  let active = false
  let known = false
  if (Array.isArray(peers)) {
    known = true
    active = peers.some((p: any) =>
      (p.status || p.federation_status || '').toUpperCase() === 'ACTIVE' ||
      (p.registry_name || '').includes('Registry-B')
    )
  } else if (Array.isArray(peers?.items)) {
    known = true
    active = peers.items.some((p: any) =>
      (p.status || p.federation_status || '').toUpperCase() === 'ACTIVE'
    )
  }
  // Fallback: if we have 2+ registries, peer is active
  if (!active && ns?.activeRegistries != null) {
    known = true
    active = ns.activeRegistries >= 2
  }
  peerState.value = active ? 'active' : known ? 'quiet' : 'unread'
})
</script>

<style scoped>
/* ══════════════════════════════════════════════════════════════════════
   TOKENS
   ══════════════════════════════════════════════════════════════════════ */
.arch {
  --bg: #060b14;
  --surface: #0a1020;
  --surface-hover: #0e1428;
  --border: rgba(var(--nc-primary-rgb),0.12);
  --cyan: var(--nc-primary);
  --amber: #f59e0b;
  --green: #00e676;
  --purple: #a78bfa;
  --text: #c8cdd5;
  --muted: #7d8aa0;  /* 5.3:1 on --bg (§FESUITE; #5a6577 was 3.2:1) */
  --glow-cyan: 0 0 15px rgba(var(--nc-primary-rgb),0.15), 0 0 40px rgba(var(--nc-primary-rgb),0.05);
  --glow-amber: 0 0 15px rgba(245,158,11,0.15), 0 0 40px rgba(245,158,11,0.05);
  --mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  overflow-x: hidden;
}

/* ══════════════════════════════════════════════════════════════════════
   HERO
   ══════════════════════════════════════════════════════════════════════ */
.arch-hero {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 24px 40px;
  overflow: hidden;
}

.arch-grid-bg {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(rgba(var(--nc-primary-rgb),0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.04) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 45%, black 20%, transparent 65%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 45%, black 20%, transparent 65%);
}
/* Atmospheric glow behind title */
.arch-hero::before {
  content: '';
  position: absolute;
  top: 25%;
  left: 50%;
  transform: translateX(-50%);
  width: 600px;
  height: 400px;
  background: radial-gradient(ellipse, rgba(var(--nc-primary-rgb),0.06) 0%, transparent 70%);
  pointer-events: none;
}

.arch-hero-fade {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 160px;
  background: linear-gradient(transparent, var(--bg));
  pointer-events: none;
}

.arch-hero-inner {
  position: relative;
  text-align: center;
  max-width: 800px;
}

.arch-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.15em;
  color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: rgba(var(--nc-primary-rgb),0.06);
  padding: 6px 16px;
  border-radius: 20px;
  margin-bottom: 32px;
}
.arch-badge-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
  animation: pulse 2s ease-in-out infinite;
}

.arch-title {
  font-size: clamp(48px, 8vw, 88px);
  font-weight: 800;
  line-height: 0.95;
  letter-spacing: -0.03em;
  color: #fff;
  margin: 0 0 24px;
  background: linear-gradient(135deg, #fff 40%, var(--cyan) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.arch-subtitle {
  font-size: 16px;
  line-height: 1.6;
  color: var(--muted);
  max-width: 560px;
  margin: 0 auto 32px;
}

/* Stats strip */
.arch-stats {
  display: flex;
  justify-content: center;
  gap: 40px;
  margin-bottom: 40px;
}
.arch-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.arch-stat-val {
  font-family: var(--mono);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.arch-stat-lbl {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--muted);
}

/* Mini topology */
.arch-topo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
}
.arch-topo-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 20px 28px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.04), var(--surface));
  min-width: 160px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.arch-topo-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  margin-bottom: 4px;
}
.arch-topo-dot--green { background: var(--green); box-shadow: 0 0 10px var(--green); animation: pulse 2s ease-in-out infinite; }
.arch-topo-dot--cyan { background: var(--cyan); box-shadow: 0 0 10px var(--cyan); animation: pulse 2s ease-in-out infinite 0.5s; }
.arch-topo-dot--amber { background: var(--amber); box-shadow: 0 0 10px var(--amber); animation: pulse 2s ease-in-out infinite 1s; }
.arch-topo-dot--dim { background: #444; }
/* §FESUITE (V0578): a peer this page could not read is neither lit nor dark */
.arch-topo-dot--unread { background: transparent; box-shadow: inset 0 0 0 1px #78909c; }
.arch-topo-note { font-size: 11px; color: #78909c; text-align: center; margin-top: 12px; font-style: italic; letter-spacing: 0.01em; }
.arch-topo-link-doc { color: var(--nc-primary, #22d3ee); font-style: normal; text-decoration: underline; text-underline-offset: 2px; }

.arch-topo-name {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
  color: #fff;
}
.arch-topo-loc {
  font-size: 10px;
  color: var(--muted);
}

.arch-topo-link {
  width: 140px;
  height: 2px;
  position: relative;
  display: flex;
  align-items: center;
}
.arch-topo-wire {
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.4), rgba(var(--nc-primary-rgb),0.12), rgba(var(--nc-primary-rgb),0.4));
  border-radius: 1px;
  box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.1);
}
.arch-topo-particle {
  position: absolute;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 12px var(--cyan), 0 0 24px rgba(var(--nc-primary-rgb),0.4);
  top: -3px;
}
.arch-topo-particle--fwd { animation: topoFlow 2.5s ease-in-out infinite; }
.arch-topo-particle--rev { animation: topoFlowRev 2.5s ease-in-out infinite 1.2s; }

@keyframes topoFlow { 0% { left: 0; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { left: calc(100% - 6px); opacity: 0; } }
@keyframes topoFlowRev { 0% { right: 0; left: auto; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { right: calc(100% - 6px); left: auto; opacity: 0; } }

.arch-topo-proto {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  font-family: var(--mono);
  color: var(--muted);
  white-space: nowrap;
  letter-spacing: 0.08em;
}

/* ══════════════════════════════════════════════════════════════════════
   SECTIONS
   ══════════════════════════════════════════════════════════════════════ */
.arch-section {
  max-width: 960px;
  margin: 0 auto;
  padding: 48px 24px;
}
.arch-section-head {
  text-align: center;
  margin-bottom: 28px;
}
.arch-h2 {
  font-size: 32px;
  font-weight: 700;
  color: #fff;
  margin: 0 0 12px;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, #fff 60%, var(--cyan));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.arch-section-sub {
  font-size: 14px;
  color: var(--muted);
  max-width: 500px;
  margin: 0 auto;
}

/* ══════════════════════════════════════════════════════════════════════
   FLOW BUTTONS
   ══════════════════════════════════════════════════════════════════════ */
.arch-flows {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.arch-flow-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--muted);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.arch-flow-btn:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }
.arch-flow-btn--active {
  border-color: var(--cyan) !important;
  color: var(--cyan) !important;
  background: rgba(var(--nc-primary-rgb),0.08);
  box-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.1);
}
.arch-flow-icon { font-size: 14px; }

/* ══════════════════════════════════════════════════════════════════════
   ARCHITECTURE DIAGRAM
   ══════════════════════════════════════════════════════════════════════ */
.arch-diagram {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Layer bar */
.arch-layer {
  border: 1px solid var(--border);
  border-left: 3px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 2px 10px 10px 2px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.02), var(--surface));
  cursor: pointer;
  transition: all 0.3s ease;
  overflow: hidden;
}
.arch-layer:hover {
  border-color: rgba(var(--nc-primary-rgb),0.3);
  border-left-color: rgba(var(--nc-primary-rgb),0.5);
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.04), var(--surface-hover));
  box-shadow: var(--glow-cyan);
}
.arch-layer--open {
  border-color: rgba(var(--nc-primary-rgb),0.4);
  border-left-color: var(--cyan);
  box-shadow: var(--glow-cyan), inset 0 0 40px rgba(var(--nc-primary-rgb),0.02);
}
.arch-layer--lit {
  border-color: rgba(var(--nc-primary-rgb),0.5) !important;
  border-left-color: var(--cyan) !important;
  box-shadow: 0 0 30px rgba(var(--nc-primary-rgb),0.12), 0 0 60px rgba(var(--nc-primary-rgb),0.04), inset 0 0 40px rgba(var(--nc-primary-rgb),0.03) !important;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.06), var(--surface)) !important;
}

.arch-layer-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
}
.arch-layer-num {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--cyan);
  opacity: 0.5;
  min-width: 20px;
}
.arch-layer-label {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #fff;
  min-width: 200px;
}
.arch-layer-tech {
  font-size: 11px;
  color: var(--muted);
  flex: 1;
}
.arch-layer-chevron {
  font-family: var(--mono);
  font-size: 16px;
  color: var(--muted);
  width: 20px;
  text-align: center;
}

/* Nodes row */
.arch-layer-nodes {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 8px 20px 16px;
}
.arch-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 12px 20px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.03), rgba(255,255,255,0.01));
  min-width: 110px;
  transition: all 0.2s;
}
.arch-node:hover { border-color: rgba(var(--nc-primary-rgb),0.25); box-shadow: 0 0 16px rgba(var(--nc-primary-rgb),0.06); }

.arch-node--wide { min-width: 260px; }
.arch-node--gw { min-width: 100px; }

/* Gateway layer — distinct as the developer entry point */
.arch-layer--gateway {
  border-color: rgba(0,230,118,0.2);
  border-left-color: rgba(0,230,118,0.4);
  background: linear-gradient(135deg, rgba(0,230,118,0.03), var(--surface));
}
.arch-layer--gateway:hover {
  border-color: rgba(0,230,118,0.35);
  border-left-color: rgba(0,230,118,0.6);
  box-shadow: 0 0 20px rgba(0,230,118,0.08);
}
.arch-layer--gateway .arch-layer-num { color: var(--green); }
.arch-layer--gateway.arch-layer--lit {
  border-color: rgba(0,230,118,0.5) !important;
  border-left-color: var(--green) !important;
  box-shadow: 0 0 30px rgba(0,230,118,0.1), inset 0 0 40px rgba(0,230,118,0.03) !important;
  background: linear-gradient(135deg, rgba(0,230,118,0.06), var(--surface)) !important;
}

.arch-node--agent { min-width: 80px; padding: 8px 12px; }

.arch-node-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  margin-bottom: 2px;
}
.arch-node-dot--green { background: var(--green); box-shadow: 0 0 8px var(--green), 0 0 20px rgba(0,230,118,0.2); animation: pulse 2.5s ease-in-out infinite; }
.arch-node-dot--cyan { background: var(--cyan); box-shadow: 0 0 8px var(--cyan), 0 0 20px rgba(var(--nc-primary-rgb),0.2); animation: pulse 2.5s ease-in-out infinite 0.3s; }
.arch-node-dot--amber { background: var(--amber); box-shadow: 0 0 8px var(--amber), 0 0 20px rgba(245,158,11,0.2); animation: pulse 2.5s ease-in-out infinite 0.6s; }
.arch-node-dot--purple { background: var(--purple); box-shadow: 0 0 8px var(--purple), 0 0 20px rgba(167,139,250,0.2); animation: pulse 2.5s ease-in-out infinite 0.9s; }
.arch-node-dot--dim { background: #555; }
.arch-node-dot--unread { background: transparent; box-shadow: inset 0 0 0 1px #78909c; }

.arch-node-name {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: #fff;
}
.arch-node-sub {
  font-size: 9px;
  color: var(--muted);
}
.arch-node-price {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--amber);
  font-weight: 600;
}

/* Node horizontal links */
.arch-node-link {
  width: 56px;
  height: 2px;
  position: relative;
  display: flex;
  align-items: center;
}
.arch-node-link-wire {
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.3), rgba(var(--nc-primary-rgb),0.1), rgba(var(--nc-primary-rgb),0.3));
  border-radius: 1px;
}
.arch-node-link-wire--amber {
  background: linear-gradient(90deg, rgba(245,158,11,0.3), rgba(245,158,11,0.1), rgba(245,158,11,0.3));
}

.arch-node-link-particle {
  position: absolute;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 10px var(--cyan), 0 0 20px rgba(var(--nc-primary-rgb),0.3);
  animation: topoFlow 2.5s ease-in-out infinite;
  top: -1.5px;
}
.arch-node-link-particle--amber {
  background: var(--amber);
  box-shadow: 0 0 10px var(--amber), 0 0 20px rgba(245,158,11,0.3);
}

/* Layer detail (expandable) */
.arch-layer-detail {
  padding: 0 20px 16px;
  animation: fadeSlide 0.3s ease;
}
.arch-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.arch-detail-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: rgba(var(--nc-primary-rgb),0.03);
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-radius: 6px;
}
.arch-detail-k {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.arch-detail-v {
  font-size: 11px;
  color: var(--text);
  text-align: right;
}

/* Connectors between layers */
.arch-conn {
  display: flex;
  justify-content: center;
  padding: 0;
  position: relative;
}
.arch-conn-line {
  width: 2px;
  height: 20px;
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.25), rgba(var(--nc-primary-rgb),0.08));
  position: relative;
  overflow: visible;
}
.arch-conn-particle {
  position: absolute;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 10px var(--cyan), 0 0 20px rgba(var(--nc-primary-rgb),0.3);
  left: -1.5px;
  animation: connFlow 1.8s ease-in-out infinite;
}
/* Second particle for density */
.arch-conn-line::after {
  content: '';
  position: absolute;
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--cyan);
  box-shadow: 0 0 8px var(--cyan);
  left: -1px;
  animation: connFlow 1.8s ease-in-out infinite 0.9s;
}

@keyframes connFlow {
  0% { top: -6px; opacity: 0; }
  15% { opacity: 1; }
  85% { opacity: 1; }
  100% { top: calc(100% + 6px); opacity: 0; }
}

/* ══════════════════════════════════════════════════════════════════════
   SECURITY TOWER
   ══════════════════════════════════════════════════════════════════════ */
.arch-tower {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 720px;
  margin: 0 auto;
}
.arch-tower-layer {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 0 8px 8px 0;
  transition: all 0.25s;
  animation: fadeSlide 0.4s ease both;
}
.arch-tower-layer:hover {
  border-left-color: var(--cyan);
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.06), var(--surface));
  box-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.06);
  transform: translateX(4px);
}
.arch-tower-num {
  font-family: var(--mono);
  font-size: 14px;
  font-weight: 700;
  color: var(--cyan);
  opacity: 0.4;
  min-width: 20px;
}
.arch-tower-content { flex: 1; }
.arch-tower-name {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.04em;
}
.arch-tower-desc {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}
.arch-tower-tech {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);  /* §FESUITE: an opacity of 0.6 over it read 1.9:1 */
  letter-spacing: 0.08em;
}

/* ══════════════════════════════════════════════════════════════════════
   DEPLOYMENT TIERS
   ══════════════════════════════════════════════════════════════════════ */
.arch-tiers {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.arch-tier {
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  transition: all 0.2s;
}
.arch-tier:hover { border-color: rgba(var(--nc-primary-rgb),0.3); }
.arch-tier--enterprise, .arch-tier--federated {
  border-color: rgba(var(--nc-primary-rgb),0.25);
}
.arch-tier--enterprise:hover, .arch-tier--federated:hover {
  border-color: rgba(var(--nc-primary-rgb),0.45);
  box-shadow: 0 0 30px rgba(var(--nc-primary-rgb),0.06);
}
.arch-tier--enterprise .arch-tier-icon { color: var(--amber) !important; }
.arch-tier--enterprise {
  border-color: rgba(245,158,11,0.3) !important;
  background: linear-gradient(135deg, rgba(245,158,11,0.04), var(--surface));
}
.arch-tier--enterprise:hover {
  border-color: rgba(245,158,11,0.5) !important;
  box-shadow: 0 0 30px rgba(245,158,11,0.08);
}

.arch-tier-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.arch-tier-icon {
  font-size: 20px;
  color: var(--cyan);
}
.arch-tier--enterprise .arch-tier-icon { color: var(--amber); }

.arch-tier-name {
  font-family: var(--mono);
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  margin: 0;
  letter-spacing: 0.04em;
}
.arch-tier-specs {
  list-style: none;
  padding: 0;
  margin: 0 0 16px;
  flex: 1;
}
.arch-tier-specs li {
  font-size: 12px;
  color: var(--text);
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  display: flex;
  align-items: center;
  gap: 8px;
}
.arch-tier-specs li::before {
  content: '›';
  color: var(--cyan);
  font-weight: 700;
}
.arch-tier--enterprise .arch-tier-specs li::before { color: var(--amber); }

.arch-tier-tag {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

/* ══════════════════════════════════════════════════════════════════════
   FOOTER
   ══════════════════════════════════════════════════════════════════════ */
.arch-footer {
  border-top: 1px solid var(--border);
  padding: 20px 24px;
  background: linear-gradient(180deg, var(--bg), var(--surface));
}
.arch-footer-dot {
  box-shadow: 0 0 6px currentColor;
  animation: pulse 3s ease-in-out infinite;
}
.arch-footer-inner {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  justify-content: center;
  gap: 32px;
  flex-wrap: wrap;
}
.arch-footer-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.arch-footer-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
}
.arch-footer-val {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  color: #fff;
}
.arch-footer-lbl {
  font-size: 11px;
  color: var(--muted);
}

/* ══════════════════════════════════════════════════════════════════════
   ANIMATIONS
   ══════════════════════════════════════════════════════════════════════ */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
@keyframes fadeSlide {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ══════════════════════════════════════════════════════════════════════
   RESPONSIVE
   ══════════════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {
  .arch-stats { gap: 20px; flex-wrap: wrap; }
  .arch-stat-val { font-size: 22px; }
  .arch-topo { flex-direction: column; gap: 0; }
  .arch-topo-link { width: 2px; height: 40px; flex-direction: column; }
  .arch-topo-wire { width: 1px; height: 100%; }
  .arch-topo-proto { top: auto; left: 20px; transform: none; }
  .arch-topo-particle--fwd { animation: topoFlowV 2.5s ease-in-out infinite; left: -2px; top: 0; }
  .arch-topo-particle--rev { animation: topoFlowVRev 2.5s ease-in-out infinite 1.2s; left: -2px; }
  .arch-layer-bar { flex-wrap: wrap; gap: 6px; }
  .arch-layer-label { min-width: auto; }
  .arch-layer-tech { display: none; }
  .arch-layer-nodes { flex-wrap: wrap; gap: 8px; }
  .arch-node-link { display: none; }
  .arch-detail-grid { grid-template-columns: 1fr; }
  .arch-tiers { grid-template-columns: 1fr; }
  .arch-footer-inner { gap: 16px; }
}

@keyframes topoFlowV { 0% { top: 0; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { top: calc(100% - 6px); opacity: 0; } }
@keyframes topoFlowVRev { 0% { bottom: 0; top: auto; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { bottom: calc(100% - 6px); top: auto; opacity: 0; } }
</style>
