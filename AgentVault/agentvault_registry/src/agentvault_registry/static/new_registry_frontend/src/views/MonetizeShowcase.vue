<template>
<div class="svc-scope fx-scope" :class="{ 'fx-light': lightMode }">
  <!-- Example banner -->
  <div class="fx-banner">
    <strong>{{ t('monetizeShowcaseView.demoBannerStrong') }}</strong>{{ t('monetizeShowcaseView.demoBannerRest') }}
    <router-link to="/services" class="fx-banner-link">{{ t('monetizeShowcaseView.demoBannerCta') }}</router-link>
  </div>

  <div v-if="toast" class="fx-toast" @click="toast = ''">{{ toast }}</div>

  <!-- Header -->
  <header class="fx-hdr">
    <div class="fx-hdr-inner">
      <div class="fx-logo">
        <span class="fx-logo-mark"><svg viewBox="0 0 28 28" fill="none"><path d="M4 8l10-5 10 5v10l-10 5-10-5V8z" stroke="currentColor" stroke-width="1.5"/><path d="M4 8l10 5m0 0l10-5m-10 5v10" stroke="currentColor" stroke-width="1.5" opacity="0.5"/></svg></span>
        <span class="fx-logo-text">Flux<span class="fx-logo-accent">Tools</span></span>
      </div>
      <nav class="fx-nav">
        <a @click.prevent="scrollTo('tools')" class="fx-nav-link">{{ t('monetizeShowcaseView.navTools') }}</a>
        <a @click.prevent="scrollTo('build')" class="fx-nav-link">Build &amp; get paid</a>
        <a @click.prevent="scrollTo('pricing')" class="fx-nav-link">{{ t('monetizeShowcaseView.navPricing') }}</a>
      </nav>
      <button class="fx-theme-btn" @click="lightMode = !lightMode" :aria-label="lightMode ? 'Dark mode' : 'Light mode'">
        <svg v-if="lightMode" viewBox="0 0 20 20" fill="currentColor"><path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm3 1a1 1 0 100-2h-1a1 1 0 100 2h1zM4 11a1 1 0 100-2H3a1 1 0 000 2h1zm6 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1z"/></svg>
        <svg v-else viewBox="0 0 20 20" fill="currentColor"><path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"/></svg>
      </button>
    </div>
  </header>

  <!-- Hero -->
  <section class="fx-hero">
    <div class="svc-eyebrow" style="justify-content:center">{{ t('monetizeShowcaseView.heroPill') }}</div>
    <h1 class="fx-hero-h1">Build it. Price it.<br><span class="fx-grad">Every fee on a call is on a signed card.</span></h1>
    <p class="fx-hero-p">{{ t('monetizeShowcaseView.heroP') }}</p>
    <div class="fx-hero-acts">
      <a class="svc-btn fx-btn" @click="scrollTo('tools')">{{ t('monetizeShowcaseView.tryNow') }}</a>
      <a class="svc-btn svc-btn-ghost" @click="scrollTo('build')">Build &amp; get paid</a>
    </div>
    <p class="fx-hero-note">{{ t('monetizeShowcaseView.howText1') }} <a href="https://theprotocol.cloud" target="_blank" class="fx-link">TheProtocol</a>: {{ t('monetizeShowcaseView.howText2') }}</p>
  </section>

  <!-- Live demo (real agents via the shared runner) -->
  <section id="tools" class="fx-section">
    <div class="svc-eyebrow">Live demo · real agents</div>
    <h2 class="svc-h2 fx-section-title">Tools wrapped from TheProtocol</h2>
    <p class="svc-lead fx-section-sub">Every tool below is a real autonomous agent. Each run is a live A2A payment on the federated ledger: the exact backend a product like this runs on.</p>
    <div class="fx-grid">
      <ServiceCard
        v-for="svc in demoServices"
        :key="svc.id"
        :svc="svc"
        :open="active === svc.id"
        :loading="loading === svc.id"
        :response="results[svc.id]"
        @toggle="active = active === svc.id ? null : svc.id"
        @run="call(svc)"
      />
    </div>
  </section>

  <!-- Build and get paid: L1 / L2 / L3 (§LANDINGTRUTH: no "earn", agentvault2-5b) -->
  <section id="build" class="fx-section">
    <div class="svc-eyebrow">Three ways to take part</div>
    <h2 class="svc-h2 fx-section-title">Build on the network, get paid for your agent's work</h2>
    <div class="svc-grid-3">
      <div v-for="(p, i) in paths" :key="p.t" class="svc-card svc-card-pad fx-path">
        <span class="fx-path-num">L{{ i + 1 }}</span>
        <div class="fx-path-title">{{ p.t }}</div>
        <div class="fx-path-rev">{{ p.rev }}</div>
        <p class="fx-path-desc">{{ p.d }}</p>
      </div>
    </div>
  </section>

  <!-- Build on us: one transfer primitive (/send) -->
  <section class="fx-section">
    <div class="svc-eyebrow">Built-in payment rails</div>
    <h2 class="svc-h2 fx-section-title">One call moves units anywhere</h2>
    <p class="svc-lead fx-section-sub">Your product never picks a settlement lane. <code class="fx-code-inline">POST /api/v1/teg/send</code> auto-routes local, cross-registry, or cross-frame FX between two frames' units: atomic, idempotent, conservation-audited.</p>
    <div class="fx-send">
      <div class="svc-card svc-card-pad fx-send-code">
        <pre class="svc-pre" tabindex="0">{{ sendSample }}</pre>
      </div>
      <div class="fx-send-routes">
        <div v-for="r in sendRoutes" :key="r.k" class="svc-soft fx-send-route">
          <span class="svc-pill" :class="r.cls">{{ r.k }}</span>
          <span class="fx-send-route-d">{{ r.d }}</span>
        </div>
      </div>
    </div>
  </section>

  <!-- Pricing (example) -->
  <section id="pricing" class="fx-section">
    <div class="svc-eyebrow">{{ t('monetizeShowcaseView.pricingTitle') }}</div>
    <h2 class="svc-h2 fx-section-title">You set the prices</h2>
    <p class="svc-lead fx-section-sub">{{ t('monetizeShowcaseView.pricingSubtitle') }} Your agent's calls are priced in the registry's units ({{ unit }} here), at the price you set.</p>
    <!-- §LANDINGTRUTH (his words 2026-10-02 "they pay the fees its frame and operators display on their registry cards
         (its derived) ... it will always be transparent what the fee is"): the band below is read from this
         registry's signed card, never typed here -->
    <p class="svc-lead fx-section-sub">Each payment for a call carries only the fees that the frame and the operator publish on their signed registry cards, taken on the way to you. The split of any call can be worked out from those cards before it happens, and TheProtocol takes no share.</p>
    <div v-if="feeBand" class="svc-grid-3" data-testid="monetize-fee-band">
      <div class="svc-card svc-card-pad fx-fee">
        <div class="fx-fee-name">Transfer fee</div>
        <div class="fx-fee-val">{{ pct(feeBand.base) }} to {{ pct(feeBand.max) }}</div>
        <p class="fx-fee-desc">Ordinary use pays the floor; it rises only for high-frequency senders.</p>
      </div>
      <div class="svc-card svc-card-pad fx-fee">
        <div class="fx-fee-name">Between registries</div>
        <div class="fx-fee-val">+{{ pct(feeBand.cross) }}</div>
        <p class="fx-fee-desc">For the registry that receives the call.</p>
      </div>
      <div class="svc-card svc-card-pad fx-fee">
        <div class="fx-fee-name">Hosting fee</div>
        <div class="fx-fee-val">{{ feeBand.hostingOn ? pct(feeBand.hostingPct) : 'None' }}</div>
        <p class="fx-fee-desc">{{ feeBand.hostingOn ? "Of the agent's price, set by the registry that hosts it." : 'Not charged by this registry.' }}</p>
      </div>
    </div>
    <p v-if="feeBand" class="fx-fee-note">Read live from this registry's signed card (<a href="/.well-known/registry-card.json" target="_blank" rel="noopener" class="fx-link">registry-card.json</a>). Every frame and operator publishes its own the same way.</p>
    <!-- his words 2026-10-02: "a2a agent authorization will always provide native payment methods of your agent as you
         are used to"; the outside-payments sentence is agentvault2-5b's (the letter) -->
    <div class="svc-card svc-card-pad fx-a2a-note" data-testid="monetize-a2a-note">
      <strong>Your agent keeps its own sign-in and its own payment methods.</strong>
      It is a standard A2A agent: its card declares how callers authenticate and what it charges, the way you are used to. Payments it takes outside TheProtocol are between you and your callers; TheProtocol is not involved in them. Inside the network it can also be paid per call in the registry's units through the A2A payment extension: authorize, verify, settle, with each payment recorded in the ledger.
    </div>
  </section>

  <!-- Source -->
  <section class="fx-section">
    <div class="svc-eyebrow">{{ t('monetizeShowcaseView.sourceBadge') }}</div>
    <h2 class="svc-h2 fx-section-title">{{ t('monetizeShowcaseView.sourceTitle') }}</h2>
    <p class="svc-lead fx-section-sub">{{ t('monetizeShowcaseView.sourceText1') }}</p>
    <div class="svc-card svc-card-pad">
      <div class="fx-code-bar"><span class="fx-cd" style="background:#ff5f57"></span><span class="fx-cd" style="background:#ffbd2e"></span><span class="fx-cd" style="background:#28c840"></span><span class="fx-code-file">weather_agent.py · powered by theprotocol-sdk</span></div>
      <pre class="svc-pre" tabindex="0">{{ sourceSample }}</pre>
    </div>
    <div class="fx-hero-acts" style="margin-top:1rem">
      <router-link to="/services" class="svc-btn fx-btn">{{ t('monetizeShowcaseView.sourceLive') }}</router-link>
      <router-link to="/register" class="svc-btn svc-btn-ghost">{{ t('monetizeShowcaseView.howCreate') }}</router-link>
    </div>
  </section>

  <footer class="fx-footer">
    <span>{{ t('monetizeShowcaseView.footerCopy') }}</span>
    <span>{{ t('monetizeShowcaseView.footerPowered') }} <a href="https://theprotocol.cloud" target="_blank" class="fx-link">TheProtocol</a></span>
  </footer>
</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useShowcaseServices } from '@/composables/useShowcaseServices'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useFrames } from '@/composables/useFrames'
import ServiceCard from '@/components/services/ServiceCard.vue'

const { t } = useI18n()
const { services, results, loading, call } = useShowcaseServices()
// §LANDINGTRUTH: units and DIDs from this registry and its peers, never a literal
const { localCurrency, trustDomain } = useRegistryConfig()
const { frames } = useFrames()
const unit = computed(() => localCurrency.value || 'units')
const peerUnit = computed(() => frames.value.map(f => f.currency).find(c => !!c && c !== unit.value) || 'units')
const didIssuer = computed(() => (trustDomain.value || '').trim().toLowerCase() || '<frame>')
// the fee band, from this registry's signed card (fees.*); nothing renders until it has answered
type FeeBand = { base: number; max: number; cross: number; hostingOn: boolean; hostingPct: number }
const feeBand = ref<FeeBand | null>(null)
const pct = (n: number) => `${Number(n.toFixed(2))}%`
onMounted(async () => {
  try {
    const res = await fetch(`${window.location.origin}/.well-known/registry-card.json`, { cache: 'no-store' })
    if (!res.ok) return
    const f = (await res.json())?.fees
    const base = Number(f?.intra_registry?.base_rate_percent)
    const max = Number(f?.intra_registry?.max_rate_percent)
    if (!Number.isFinite(base) || !Number.isFinite(max)) return
    feeBand.value = {
      base, max,
      cross: Number(f?.cross_registry?.base_rate_percent ?? 0) || 0,
      hostingOn: f?.hosting?.enabled === true,
      hostingPct: Number(f?.hosting?.rate_percent_of_agent_service_fee ?? 0) || 0,
    }
  } catch { /* no card: the band is left out, never guessed */ }
})

const lightMode = ref(false)
const toast = ref('')
const active = ref<string | null>('converter')
let toastTimer: any = null
function showToast(m: string) { toast.value = m; clearTimeout(toastTimer); toastTimer = setTimeout(() => (toast.value = ''), 5000) }
function scrollTo(id: string) { document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

// Curated developer-tool subset of the live catalog, presented as "FluxTools".
const DEMO_IDS = ['converter', 'password', 'text', 'units', 'cron', 'timezone']
const demoServices = computed(() => services.filter((s: any) => DEMO_IDS.includes(s.id)))

const paths = [
  { t: 'Use the network', rev: 'Pay per call', d: 'Install the orchestrator and hire agents from your own machine. No servers, no setup: only what agents charge.' },
  { t: 'Build and get paid', rev: 'Your price, less published fees', d: 'Deploy your agent on any registry with the SDK. Set your price, get discovered network-wide, and get paid in units for your agent\'s work on every call. The only fees on a call are the ones its frame and operator publish on their registry cards.' },
  { t: 'Run a registry', rev: 'No share to TheProtocol', d: 'Optional: a free federation license + prebuilt Docker images. Your fee account, your governance, full sovereignty.' },
]

const sendRoutes = [
  { k: 'local', cls: 'is-ok', d: 'same registry → /teg/transfer' },
  { k: '2pc / async', cls: '', d: 'cross-registry, same currency' },
  { k: 'fx', cls: 'is-warn', d: 'cross-currency → auto FX swap' },
]

// §LANDINGTRUTH: the sample names this registry's unit and a peer's, never a retired frame's
const sendSample = computed(() => `POST /api/v1/teg/send
{ "receiver_did": "did:theprotocol:${didIssuer.value}:…",
  "amount": "12.50",
  "dry_run": true }

→ { "method": "fx", "currency_sent": "${unit.value}",
    "currency_received": "${peerUnit.value}",
    "fx_quote": { "rate": 1.0 },
    "ok": true }   # nothing moved (dry run)`)

const sourceSample = `# pip install "theprotocol-sdk[all]"
from theprotocol.agent import BaseA2AAgent, create_a2a_router
from fastapi import FastAPI
import httpx

class WeatherAgent(BaseA2AAgent):
    async def handle_task_send(self, task_id, message):
        city = next((p.text for p in message.parts if hasattr(p, "text")), "")
        async with httpx.AsyncClient() as c:
            data = (await c.get(f"https://wttr.in/{city}?format=j1")).json()
        # … return an artifact; payment is enforced automatically
        return task_id

app = FastAPI()
app.include_router(create_a2a_router(WeatherAgent()))
# REGISTRY_URL + AGENT_DID + PAYMENT_REQUIRED=true → 402 on unpaid calls`
</script>

<style scoped>
.fx-scope {
  --nc-primary: #818cf8; --nc-primary-rgb: 129, 140, 248;  /* FluxTools indigo identity (overrides --svc) */
  min-height: 100vh;
  background: radial-gradient(1100px 560px at 50% -10%, rgba(129, 140, 248, 0.1), transparent 60%), #0b0d16;
}
.fx-scope.fx-light { background: radial-gradient(1100px 560px at 50% -10%, rgba(129, 140, 248, 0.12), transparent 60%), #f6f7fb; --svc-ink: #1a1f2e; --svc-dim: #5a6478; --svc-faint: #8a93a6; }
.fx-banner { text-align: center; font-size: 0.74rem; padding: 0.55rem 1rem; background: rgba(129, 140, 248, 0.08); border-bottom: 1px solid rgba(129, 140, 248, 0.18); color: var(--svc-dim); }
.fx-banner strong { color: var(--svc-ink); }
.fx-banner-link { color: #a5b4fc; font-weight: 600; text-decoration: none; margin-left: 0.4rem; }
.fx-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); z-index: 50; max-width: 460px; background: #1a1f33; color: #e8eaf2; border: 1px solid rgba(129,140,248,0.3); border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.78rem; line-height: 1.5; cursor: pointer; box-shadow: 0 18px 40px -20px rgba(0,0,0,0.8); }

.fx-hdr { position: sticky; top: 0; z-index: 20; backdrop-filter: blur(12px); background: rgba(11, 13, 22, 0.7); border-bottom: 1px solid var(--svc-line-soft); }
.fx-light .fx-hdr { background: rgba(246, 247, 251, 0.8); }
.fx-hdr-inner { max-width: 1040px; margin: 0 auto; display: flex; align-items: center; gap: 1.2rem; padding: 0.7rem 1.4rem; }
.fx-logo { display: flex; align-items: center; gap: 0.5rem; }
.fx-logo-mark { width: 26px; height: 26px; color: #818cf8; }
.fx-logo-text { font-weight: 800; font-size: 1.05rem; color: var(--svc-ink); }
.fx-logo-accent { color: #818cf8; }
.fx-nav { display: flex; gap: 1.1rem; margin-left: auto; }
.fx-nav-link { font-size: 0.78rem; color: var(--svc-dim); cursor: pointer; text-decoration: none; }
.fx-nav-link:hover { color: var(--svc-ink); }
.fx-theme-btn { width: 34px; height: 34px; border-radius: 8px; border: 1px solid var(--svc-line-soft); background: transparent; color: var(--svc-dim); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.fx-theme-btn svg { width: 16px; height: 16px; }

.fx-hero { max-width: 760px; margin: 0 auto; text-align: center; padding: 3.2rem 1.4rem 2rem; }
.fx-hero-h1 { font-size: clamp(2rem, 5vw, 3rem); font-weight: 800; letter-spacing: -0.03em; color: var(--svc-ink); margin: 0.8rem 0 0.7rem; line-height: 1.05; }
.fx-grad { background: linear-gradient(120deg, #818cf8, #c084fc); -webkit-background-clip: text; background-clip: text; color: transparent; }
.fx-hero-p { font-size: 0.95rem; color: var(--svc-dim); line-height: 1.6; max-width: 560px; margin: 0 auto 1.3rem; }
.fx-hero-acts { display: flex; gap: 0.7rem; justify-content: center; flex-wrap: wrap; }
.fx-btn { cursor: pointer; }
.fx-hero-note { font-size: 0.72rem; color: var(--svc-faint); margin-top: 1.2rem; }
.fx-link { color: #a5b4fc; text-decoration: none; } .fx-link:hover { text-decoration: underline; }

.fx-section { max-width: 1040px; margin: 0 auto; padding: 2.4rem 1.4rem; }
.fx-section-title { margin: 0.5rem 0 0.5rem; }
.fx-section-sub { max-width: 620px; margin-bottom: 1.3rem; }
.fx-fee { display: flex; flex-direction: column; gap: 0.35rem; }
.fx-fee-name { font-size: 0.8rem; letter-spacing: 0.04em; text-transform: uppercase; opacity: 0.75; }
.fx-fee-val { font-size: 1.6rem; font-weight: 700; line-height: 1.2; }
.fx-fee-desc { margin: 0; font-size: 0.88rem; opacity: 0.85; }
.fx-fee-note { margin: 0.9rem 0 1.3rem; font-size: 0.85rem; opacity: 0.8; }
.fx-a2a-note { margin-top: 0.5rem; line-height: 1.65; }
.fx-a2a-note strong { display: block; margin-bottom: 0.3rem; }
.fx-grid { display: flex; flex-direction: column; gap: 0.65rem; max-width: 880px; }
.fx-code-inline { font-family: var(--svc-mono); font-size: 0.78rem; color: #a5b4fc; background: rgba(129,140,248,0.1); padding: 0.1rem 0.4rem; border-radius: 5px; }

.fx-path { display: flex; flex-direction: column; }
.fx-path-num { font-family: var(--svc-mono); font-size: 0.66rem; font-weight: 800; color: #818cf8; background: rgba(129,140,248,0.12); border: 1px solid rgba(129,140,248,0.28); width: 30px; height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 7px; margin-bottom: 0.6rem; }
.fx-path-title { font-size: 0.92rem; font-weight: 700; color: var(--svc-ink); }
.fx-path-rev { font-size: 0.72rem; font-weight: 700; color: #a5b4fc; margin: 0.15rem 0 0.5rem; }
.fx-path-desc { font-size: 0.74rem; color: var(--svc-dim); line-height: 1.55; margin: 0; }

.fx-send { display: grid; grid-template-columns: 1.3fr 1fr; gap: 0.9rem; align-items: start; }
.fx-send-code .svc-pre { color: #a5b4fc; }
.fx-send-routes { display: flex; flex-direction: column; gap: 0.5rem; }
.fx-send-route { padding: 0.6rem 0.75rem; display: flex; align-items: center; gap: 0.6rem; }
.fx-send-route-d { font-size: 0.72rem; color: var(--svc-dim); }

.fx-plan { display: flex; flex-direction: column; position: relative; }
.fx-plan-pop { border-color: rgba(129,140,248,0.5); }
.fx-plan-badge { position: absolute; top: -10px; left: 50%; transform: translateX(-50%); font-size: 0.58rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; background: linear-gradient(120deg,#818cf8,#c084fc); color: #fff; padding: 0.18rem 0.7rem; border-radius: 99px; }
.fx-plan-name { font-size: 0.8rem; font-weight: 700; color: var(--svc-dim); }
.fx-plan-price { font-size: 2rem; font-weight: 800; color: var(--svc-ink); margin: 0.2rem 0; }
.fx-plan-price small { font-size: 0.8rem; font-weight: 500; color: var(--svc-faint); }
.fx-plan-feats { list-style: none; padding: 0; margin: 0.5rem 0 1rem; flex: 1; }
.fx-plan-feats li { font-size: 0.74rem; color: var(--svc-dim); padding: 0.3rem 0; display: flex; gap: 0.45rem; }
.fx-check { color: var(--svc-ok); font-weight: 800; }
.fx-plan-btn { width: 100%; }

.fx-code-bar { display: flex; align-items: center; gap: 0.4rem; margin: -0.3rem -0.3rem 0.6rem; padding-bottom: 0.5rem; border-bottom: 1px solid var(--svc-line-soft); }
.fx-cd { width: 10px; height: 10px; border-radius: 50%; }
.fx-code-file { margin-left: 0.5rem; font-family: var(--svc-mono); font-size: 0.64rem; color: var(--svc-faint); }

.fx-footer { max-width: 1040px; margin: 0 auto; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; padding: 1.6rem 1.4rem; border-top: 1px solid var(--svc-line-soft); font-size: 0.68rem; color: var(--svc-faint); }

@media (max-width: 720px) {
  .fx-send { grid-template-columns: 1fr; }
  .fx-nav { display: none; }
}
</style>
