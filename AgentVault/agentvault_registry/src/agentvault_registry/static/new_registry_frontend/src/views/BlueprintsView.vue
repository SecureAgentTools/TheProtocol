<template>
<div class="bp-root" @pointermove="onRailPointer" @pointerleave="railTip = null">
  <div class="bp-wrap">

    <!-- Breadcrumb + theme quick-apply -->
    <nav class="bp-crumb">
      <router-link to="/" class="bp-crumb-home">TheProtocol</router-link>
      <span class="bp-crumb-sep">/</span>
      <span>{{ t('blueprintsView.crumb', 'Industry Blueprints') }}</span>
      <div class="bp-themebar" role="group" :aria-label="t('blueprintsView.theme.label', 'Theme')">
        <span class="bp-themebar-k">{{ t('blueprintsView.theme.k', 'THEME') }}</span>
        <button type="button" class="bp-themebar-chip" :class="{ 'is-on': ui.brandTheme === 'neural' }" @click="ui.setBrandTheme('neural')">NEURAL</button>
        <button type="button" class="bp-themebar-chip bp-themebar-chip--sov" :class="{ 'is-on': ui.brandTheme === 'sovereign' }" @click="ui.setBrandTheme('sovereign')">SOVEREIGN</button>
        <button
          type="button" class="bp-themebar-chip"
          :class="{ 'is-on': ui.brandTheme === 'custom', 'is-locked': !ui.customThemeHex }"
          :title="ui.customThemeHex ? t('blueprintsView.theme.customTitle', 'Apply your saved Theme Studio palette') : t('blueprintsView.theme.customHint', 'Custom is your own palette. Sign in and define it in Settings, Theme Studio; it will be ready here.')"
          @click="ui.customThemeHex && ui.setBrandTheme('custom')"
        >
          <span v-if="ui.customThemeHex" class="bp-themebar-dot" :style="{ background: ui.customThemeHex }"></span>CUSTOM
        </button>
      </div>
    </nav>

    <!-- Hero -->
    <header class="bp-hero">
      <div class="bp-hero-mark"><ProtocolMark :size="56" alive /></div>
      <span class="bp-hero-chip">{{ t('blueprintsView.heroChip', 'INDUSTRY BLUEPRINTS') }}</span>
      <h1 class="bp-h1">
        {{ t('blueprintsView.heroTitle1', `${countWordCap} systems that could run on this network today.`) }}<br />
        <span class="bp-h1-accent">{{ t('blueprintsView.heroTitle2', 'The rails under them already do.') }}</span>
      </h1>
      <p class="bp-lead">
        {{ t('blueprintsView.heroSub', 'Named, worked designs for the industries where autonomous agents are blocked on liability, audit, revocable authority and sovereignty. Each one is drawn on primitives you can call right now, and each one is attacked on this page so you can watch the refusal.') }}
      </p>

      <div class="bp-hero-loom">
        <FlowLoom :nodes="HERO_NODES" :edges="HERO_EDGES" :script="HERO_SCRIPT"
                  :aria-title="t('blueprintsView.heroLoomTitle', 'What a request looks like on this network')" />
      </div>

      <!-- Live pills: one fetch, honest fallback. Never a fabricated zero. -->
      <div class="bp-pills">
        <div class="bp-pill">
          <span class="bp-pill-v">{{ pillRegistries }}</span>
          <span class="bp-pill-k">{{ t('blueprintsView.pill.registries', 'registries federated') }}</span>
        </div>
        <div class="bp-pill">
          <span class="bp-pill-v">{{ pillAgents }}</span>
          <span class="bp-pill-k">{{ t('blueprintsView.pill.agents', 'agents on the network') }}</span>
        </div>
        <div class="bp-pill">
          <span class="bp-pill-v">{{ pillActive }}</span>
          <span class="bp-pill-k">{{ t('blueprintsView.pill.active', 'active in the last 24h') }}</span>
        </div>
        <a class="bp-pill bp-pill--link" href="https://auditor.theprotocol.cloud" target="_blank" rel="noopener">
          <span class="bp-pill-v">&Delta; = 0</span>
          <span class="bp-pill-k">{{ t('blueprintsView.pill.delta', 'verified continuously by an independent auditor') }}</span>
        </a>
      </div>
    </header>

    <!-- How to read this page -->
    <aside class="bp-howto">
      <strong>{{ t('blueprintsView.howto.head', 'How to read this page.') }}</strong>
      {{ t('blueprintsView.howto.body', 'The systems are illustrative. The rails are real, and every rail carries a status badge:') }}
      <span class="bp-badge-demo" data-s="LIVE">LIVE</span>
      {{ t('blueprintsView.howto.live', 'running in production now') }} ·
      <span class="bp-badge-demo" data-s="LIVE (gated)">LIVE (gated)</span>
      {{ t('blueprintsView.howto.gated', 'built, switched on per deployment') }} ·
      <span class="bp-badge-demo" data-s="SHADOW">SHADOW</span>
      {{ t('blueprintsView.howto.shadow', 'built, and this deployment runs it observe-only: decisions logged, not enforced') }} ·
      <span class="bp-badge-demo" data-s="DESIGNED">DESIGNED</span>
      {{ t('blueprintsView.howto.designed', 'specified, not built yet') }}.
      {{ t('blueprintsView.howto.ratio', 'Each chamber’s ratio counts the steps whose rail is built; only DESIGNED counts against it. The badge says how this deployment runs each one.') }}
      {{ t('blueprintsView.howto.tail', 'Numbers about the fictional systems are narrative. Numbers about the protocol are backed by the tables, or absent.') }}
      {{ t('blueprintsView.howto.scodes', 'The S-codes are the nineteen named refusals of the safety catalogue: hover any S-chip for the mechanism, or read them all in the Safety Index below.') }}
      {{ t('blueprintsView.howto.arch', 'The machinery under every chamber is drawn component by component in') }}
      <router-link to="/docs/35" class="bp-howto-link">{{ t('blueprintsView.howto.archLink', 'The Architecture') }}</router-link>.
    </aside>

    <!-- Industry finder: recognition at navigation level -->
    <div class="bp-finder">
      <label class="bp-finder-k" for="bp-finder-sel">{{ t('blueprintsView.finder.label', 'FIND YOUR CASE') }}</label>
      <select id="bp-finder-sel" class="bp-finder-sel" v-model="finderPick" @change="onFinder">
        <option value="" disabled>{{ t('blueprintsView.finder.placeholder', 'I work in...') }}</option>
        <optgroup v-for="bp in BLUEPRINTS" :key="bp.id" :label="`${bp.systemName} · ${bp.industry}`">
          <option v-for="c in bp.cases" :key="c.role" :value="bp.id">{{ c.role }}</option>
        </optgroup>
      </select>
    </div>

    <!-- Index rail -->
    <section class="bp-index">
      <template v-for="tier in [1, 2, 3]" :key="tier">
        <div v-if="byTier(tier).length" class="bp-index-tier">{{ tierLabel(tier) }}</div>
        <button
          v-for="bp in byTier(tier)" :key="bp.id"
          type="button" class="bp-index-row" @click="scrollTo(bp.id)"
        >
          <span class="bp-index-rank">{{ String(bp.rank).padStart(2, '0') }}</span>
          <span class="bp-index-name">{{ bp.systemName }}</span>
          <span class="bp-index-ind">{{ bp.industry }}</span>
          <span class="bp-index-promise">{{ bp.promise }}</span>
          <span class="bp-index-ratio">{{ bp.liveRatio[0] }}/{{ bp.liveRatio[1] }}</span>
        </button>
      </template>
      <div class="bp-index-tier">{{ t('blueprintsView.tierVault', 'FROM THE VAULT · DRAFTED') }}</div>
      <button
        v-for="bp in vaultBlueprints" :key="bp.id"
        type="button" class="bp-index-row" @click="scrollTo(bp.id)"
      >
        <span class="bp-index-rank">{{ String(bp.rank).padStart(2, '0') }}</span>
        <span class="bp-index-name">{{ bp.systemName }}</span>
        <span class="bp-index-ind">{{ bp.industry }}</span>
        <span class="bp-index-promise">{{ bp.promise }}</span>
        <span class="bp-index-ratio">{{ bp.liveRatio[0] }}/{{ bp.liveRatio[1] }}</span>
      </button>
      <template v-if="frontierBlueprints.length">
        <div class="bp-index-tier bp-index-tier--frontier">{{ t('blueprintsView.tierFrontier', 'THE FRONTIER · FUTURE CASES') }}</div>
        <button
          v-for="bp in frontierBlueprints" :key="bp.id"
          type="button" class="bp-index-row" @click="scrollTo(bp.id)"
        >
          <span class="bp-index-rank">{{ String(bp.rank).padStart(2, '0') }}</span>
          <span class="bp-index-name">{{ bp.systemName }}</span>
          <span class="bp-index-ind">{{ bp.industry }}</span>
          <span class="bp-index-promise">{{ bp.promise }}</span>
          <span class="bp-index-ratio">{{ bp.liveRatio[0] }}/{{ bp.liveRatio[1] }}</span>
        </button>
      </template>
    </section>

    <!-- The Atlas grid (§18): every industry, one card, one click deep -->
    <section class="bp-atlas">
      <span class="bp-sec-label">{{ t('blueprintsView.atlas.label', 'The Atlas') }}</span>
      <h2 class="bp-h2">{{ t('blueprintsView.atlas.titleFrontier', `${countWordCap} chambers, one click each`) }}</h2>
      <p class="bp-lead bp-lead--tight">{{ t('blueprintsView.atlas.sub', 'Each industry now has its own page: the full anatomy, the attack replays, and, industry by industry, a deep reference architecture with an adoption path. The Atlas is the map; the chambers are the territory.') }}</p>
      <div class="bp-atlas-grid">
        <router-link v-for="bp in atlasCards" :key="bp.id" :to="`/blueprints/${bp.id}`" class="bp-atlas-card">
          <div class="bp-atlas-top">
            <span class="bp-atlas-rank">{{ String(bp.rank).padStart(2, '0') }}</span>
            <div class="bp-atlas-names">
              <span class="bp-atlas-ind">{{ bp.industry }}</span>
              <span class="bp-atlas-name">{{ bp.systemName }}</span>
            </div>
            <span v-if="bp.vault" class="bp-atlas-chip">{{ t('blueprintsView.atlas.vault', 'VAULT') }}</span>
            <span v-else-if="bp.frontier" class="bp-atlas-chip bp-atlas-chip--frontier">{{ t('blueprintsView.frontier.chip', 'FRONTIER') }}</span>
            <span v-else-if="bp.tier === 3" class="bp-atlas-chip bp-atlas-chip--dim">{{ t('blueprintsView.atlas.sketch', 'SKETCH') }}</span>
            <span v-if="hasDeep(bp.id)" class="bp-atlas-chip bp-atlas-chip--deep">{{ t('blueprintsView.atlas.deep', 'DEEP') }}</span>
          </div>
          <p class="bp-atlas-promise">{{ bp.promise }}</p>
          <div class="bp-atlas-cases">
            <span v-for="c in bp.cases.slice(0, 2)" :key="c.role" class="bp-atlas-case">{{ c.role }}</span>
          </div>
          <div class="bp-atlas-foot">
            <span class="bp-atlas-rails">
              <span v-for="r in bp.rails.slice(0, 5)" :key="r" class="bp-atlas-rail" :data-railtip="r">{{ r }}</span>
            </span>
            <span class="bp-atlas-ratio">{{ bp.liveRatio[0] }}/{{ bp.liveRatio[1] }} {{ t('blueprintsView.atlas.built', 'built') }}</span>
            <span class="bp-atlas-open">{{ t('blueprintsView.atlas.open', 'OPEN') }} →</span>
          </div>
        </router-link>
      </div>
    </section>

    <!-- Safety Index -->
    <section class="bp-safety">
      <span class="bp-sec-label">{{ t('blueprintsView.safety.label', 'The Safety Index') }}</span>
      <h2 class="bp-h2">{{ t('blueprintsView.safety.title', `One safety system under all ${countWord}`) }}</h2>
      <p class="bp-lead bp-lead--tight">{{ t('blueprintsView.safety.sub', 'Nineteen named refusals, shipped. Each blueprint leans on the same rails rather than bolting on its own, and the unlit cells are the honest part.') }}</p>
      <SafetyIndex :blueprints="BLUEPRINTS" />
    </section>

    <!-- The management system behind the rails -->
    <section class="bp-mgmt">
      <span class="bp-sec-label">{{ t('blueprintsView.mgmt.label', 'Behind the rails') }}</span>
      <h2 class="bp-h2">{{ t('blueprintsView.mgmt.title', 'The management system these refusals live in') }}</h2>
      <p class="bp-lead bp-lead--tight">
        {{ t('blueprintsView.mgmt.body', 'The refusals above sit inside a fourteen-layer management system: risk registers, incident procedures with a P1 clock, data protection, change management and audit cadences, all published in full. Stated exactly as the compliance page states it: self-assessed against ISO/IEC 42001, not yet independently audited, with one acknowledged hardening gap tracked in the open.') }}
      </p>
      <div class="bp-mgmt-links">
        <router-link to="/compliance" class="bp-mgmt-link">{{ t('blueprintsView.mgmt.overview', 'Compliance overview') }}</router-link>
        <router-link to="/compliance/doc/jurisdiction-profiles" class="bp-mgmt-link">{{ t('blueprintsView.mgmt.juri', 'Jurisdiction Profiles') }}</router-link>
        <router-link to="/compliance/doc/risk-assessment-framework" class="bp-mgmt-link">{{ t('blueprintsView.mgmt.risk', 'The public risk register') }}</router-link>
      </div>
    </section>

    <!-- Proof band: the rails are live right now -->
    <section class="bp-proof svc-scope">
      <span class="bp-sec-label">{{ t('blueprintsView.proof.label', 'Not a mockup') }}</span>
      <h2 class="bp-h2">{{ t('blueprintsView.proof.title', 'These rails are live right now') }}</h2>
      <p class="bp-lead bp-lead--tight">
        {{ t('blueprintsView.proof.sub', 'Everything above is a blueprint. This is not: real agents on the production network, paid per call through the same settlement rail the blueprints draw on. First calls are on us.') }}
      </p>
      <div class="bp-proof-grid">
        <ServiceCard
          v-for="svc in proofServices"
          :key="svc.id"
          :svc="svc"
          :open="activeProof === svc.id"
          :loading="loading === svc.id"
          :response="results[svc.id]"
          @toggle="toggleProof(svc.id)"
          @run="call(svc)"
        />
      </div>
      <div v-if="relayDeclined" class="bp-proof-note">
        {{ t('blueprintsView.proof.declined', 'This node could not reach the resident agent just now. The service agents live beside the flagship registry; the same call runs there:') }}
        <a href="https://api.theprotocol.cloud/ui#/services" target="_blank" rel="noopener">api.theprotocol.cloud</a>
      </div>
      <div class="bp-proof-foot">
        <span class="bp-proof-meter">{{ t('blueprintsView.proof.meter', 'Free requests left in this browser:') }} {{ requestsLeft }}</span>
        <router-link to="/services" class="bp-proof-more">{{ t('blueprintsView.proof.more', 'All live services') }}</router-link>
      </div>
    </section>

    <!-- The Vault -->
    <section class="bp-vault">
      <span class="bp-sec-label">{{ t('blueprintsView.vault.label', 'Not drafted yet') }}</span>
      <h2 class="bp-h2">{{ t('blueprintsView.vault.title', 'The Vault') }}</h2>
      <p class="bp-lead bp-lead--tight">{{ t('blueprintsView.vault.sub', 'Sectors we can see and have not drawn. The first nine entries on this list graduated to full blueprints on 2026-08-09, and three more joined the Frontier on 2026-09-25; these are next. If one of them is yours, the Guild is where work gets posted, bid on, and paid out of escrow.') }}</p>
      <div class="bp-vault-grid">
        <span v-for="v in VAULT" :key="v" class="bp-vault-item">{{ v }}</span>
      </div>
      <router-link to="/guild" class="bp-vault-cta">{{ t('blueprintsView.vault.cta', 'Post it on the Guild board') }}</router-link>
    </section>

    <!-- CTA -->
    <section class="bp-cta">
      <h2 class="bp-h2">{{ t('blueprintsView.cta.title', 'Three ways in') }}</h2>
      <p class="bp-lead bp-lead--tight">{{ t('blueprintsView.cta.sub', 'Use the network, build on it, or run a sovereign piece of it. All three are open, and the third one is free.') }}</p>
      <div class="bp-cta-acts">
        <router-link to="/register" class="bp-btn bp-btn--primary">{{ t('blueprintsView.cta.create', 'Create an account') }}</router-link>
        <router-link to="/docs" class="bp-btn">{{ t('blueprintsView.cta.docs', 'Read the docs') }}</router-link>
        <router-link to="/operator-docs" class="bp-btn">{{ t('blueprintsView.cta.operate', 'Run your own registry') }}</router-link>
      </div>
    </section>

    <footer class="bp-footer">
      A2A v1.0 · Federated Agent Network · <a href="https://theprotocol.cloud" class="bp-footer-link">theprotocol.cloud</a>
    </footer>
  </div>

  <!-- Rail tooltip singleton: follows the cursor over any [data-railtip] -->
  <div v-if="railTip" ref="railTipEl" class="bp-railtip" role="tooltip">
    <span class="bp-railtip-head">{{ railTip.id }} · {{ railTip.name }}</span>
    <span class="bp-railtip-body">{{ railTip.refusal }}</span>
  </div>
</div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { useShowcaseServices } from '@/composables/useShowcaseServices'
import { RAIL_BY_ID } from '@/data/blueprints/rails'
import type { Rail } from '@/data/blueprints/types'
import ProtocolMark from '@/components/ProtocolMark.vue'
import ServiceCard from '@/components/services/ServiceCard.vue'
import FlowLoom from '@/components/blueprints/FlowLoom.vue'
import { hasDeep } from '@/data/blueprints/arch'
import SafetyIndex from '@/components/blueprints/SafetyIndex.vue'
import { BLUEPRINTS, VAULT } from '@/data/blueprints'
import { HERO_EDGES, HERO_NODES, HERO_SCRIPT } from '@/data/blueprints/hero'

const { t } = useI18n()
const ui = useUIStore()

// ------------------------------------------------------------ rail tooltip
// One delegated handler for every [data-railtip] on the page: chips, matrix
// headers, matrix cells, legend rows. Follows the cursor so a first-time
// visitor cannot miss it (the below-the-diagram status line did not survive
// contact with first-time visitors).
const railTip = ref<Rail | null>(null)
const railTipEl = ref<HTMLElement | null>(null)
function onRailPointer(ev: PointerEvent) {
  if (ev.pointerType !== 'mouse') return
  const host = (ev.target as Element | null)?.closest?.('[data-railtip]')
  const id = host?.getAttribute('data-railtip') || null
  railTip.value = id ? RAIL_BY_ID[id] ?? null : null
  if (!railTip.value) return
  const x = ev.clientX, y = ev.clientY
  nextTick(() => {
    const el = railTipEl.value
    if (!el) return
    const w = el.offsetWidth, h = el.offsetHeight
    const left = Math.min(x + 16, window.innerWidth - w - 12)
    const top = y + 20 + h > window.innerHeight ? y - h - 14 : y + 20
    el.style.left = `${Math.max(8, left)}px`
    el.style.top = `${Math.max(8, top)}px`
  })
}

// ------------------------------------------------------------ industry finder
const finderPick = ref('')
function onFinder() {
  if (finderPick.value) scrollTo(finderPick.value)
  finderPick.value = ''
}

// ------------------------------------------------------------ catalogue
const vaultBlueprints = computed(() => BLUEPRINTS.filter((b) => b.vault))
const frontierBlueprints = computed(() => BLUEPRINTS.filter((b) => b.frontier))
// The page counts its chambers from the data, in words: a literal number in a heading went stale
// the day a chamber was added (the hero said twenty-one above twenty-seven chambers).
const NUM_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
  'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
function numberWord(n: number): string {
  if (n < 20) return NUM_WORDS[n]
  if (n < 100) { const u = n % 10; return u ? `${TENS[Math.floor(n / 10)]}-${NUM_WORDS[u]}` : TENS[Math.floor(n / 10)] }
  return String(n)
}
const countWord = numberWord(BLUEPRINTS.length)
const countWordCap = countWord.charAt(0).toUpperCase() + countWord.slice(1)
const atlasCards = computed(() => [...BLUEPRINTS].sort((a, b) => a.rank - b.rank))
function byTier(tier: number) { return BLUEPRINTS.filter((b) => b.tier === tier && !b.vault && !b.frontier) }
function tierLabel(tier: number): string {
  if (tier === 1) return t('blueprintsView.tier1', 'TIER I · FULLY WORKED')
  if (tier === 2) return t('blueprintsView.tier2', 'TIER II · FULL ANATOMY')
  return t('blueprintsView.tier3', 'TIER III · SKETCHES')
}
// §18 Atlas split: every industry reference opens its chamber.
function scrollTo(id: string) {
  router.push(`/blueprints/${id}`)
}

// ------------------------------------------------------------ live pills
// One fetch. On any failure the pills read an em dash, never a fabricated
// zero and never a baked constant (strategy §10.5).
const pillRegistries = ref('—')
const pillAgents = ref('—')
const pillActive = ref('—')
let pillAbort: AbortController | null = null

// Deep link: /blueprints?bp=<id> scrolls to that blueprint on arrival. Used
// by the "see it refuse" links on /compliance and shareable on its own.
const route = useRoute()
const router = useRouter()

onMounted(async () => {
  const bp = typeof route.query.bp === 'string' ? route.query.bp : null
  if (bp && BLUEPRINTS.some((b) => b.id === bp)) {
    // §18 compat: the ?bp= deep links (compliance "see it refuse") now land
    // in the chamber itself. The old scroll-and-re-assert dance is gone
    // because the chamber IS the target.
    router.replace(`/blueprints/${bp}`)
    return
  }
  pillAbort = new AbortController()
  const kill = window.setTimeout(() => pillAbort?.abort(), 6000)
  try {
    const res = await fetch('/api/v1/federation/network-stats', { signal: pillAbort.signal })
    if (res.ok) {
      const d = await res.json()
      if (typeof d.activeRegistries === 'number') pillRegistries.value = String(d.activeRegistries)
      if (typeof d.networkAgents === 'number') pillAgents.value = d.networkAgents.toLocaleString(appLocale())
      if (typeof d.activeAgents24h === 'number') pillActive.value = String(d.activeAgents24h)
    }
  } catch { /* pills stay at the honest dash */ }
  finally { window.clearTimeout(kill) }
})
onBeforeUnmount(() => pillAbort?.abort())

// ------------------------------------------------------------ proof band
// Third consumer of the existing showcase composable: same catalog, same
// request contract, same live-price overlay as /services and /monetize.
const { services, results, loading, requestsLeft, call } = useShowcaseServices()
const proofServices = computed(() => services.slice(0, 3))
const activeProof = ref<string | null>(null)
function toggleProof(id: string) { activeProof.value = activeProof.value === id ? null : id }
// Honest degradation: resident service agents live beside the flagship
// registry. If THIS node's relay declines a call, say so instead of letting
// "live right now" stand over an error card (strategy §10).
const relayDeclined = computed(() =>
  Object.values(results).some((r: any) => {
    const msg = String(r?.error ?? r?.detail ?? '')
    return msg.includes('unavailable') || msg.includes('resolution')
  }),
)
</script>

<style scoped>
.bp-root {
  --flow: var(--nc-primary, #00d2d2);
  --flow-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --bp-ink: #e8edf3;
  --bp-ink-soft: #c6cfda;
  --bp-dim: #94a0ae;
  --bp-faint: #788593;  /* §FESUITE: 5.1:1 (#6b7785 was 4.2:1) */
  --bp-mono: 'IBM Plex Mono', 'Fira Code', monospace;
  min-height: 100vh;
  color: var(--bp-ink-soft);
  background:
    radial-gradient(1300px 640px at 50% -10%, rgba(var(--flow-rgb), 0.07), transparent 62%),
    radial-gradient(900px 500px at 90% 40%, rgba(var(--flow-rgb), 0.03), transparent 60%),
    #070b12;
}
.bp-wrap { max-width: 1060px; margin: 0 auto; padding: 2.5rem 1.5rem 3.5rem; }

.bp-crumb { display: flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; color: var(--bp-faint); margin-bottom: 2rem; }
.bp-themebar { margin-left: auto; display: flex; align-items: center; gap: 0.4rem; }
.bp-themebar-k { font-family: var(--bp-mono); font-size: 0.56rem; font-weight: 700; letter-spacing: 0.12em; color: var(--bp-faint); }
.bp-themebar-chip { display: inline-flex; align-items: center; gap: 0.32rem; font-family: var(--bp-mono); font-size: 0.58rem; font-weight: 800; letter-spacing: 0.08em; color: var(--bp-dim); background: transparent; border: 1px solid rgba(var(--flow-rgb), 0.22); border-radius: 20px; padding: 0.26rem 0.6rem; cursor: pointer; transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease; }
.bp-themebar-chip:hover:not(:disabled) { color: var(--bp-ink); border-color: rgba(var(--flow-rgb), 0.45); }
.bp-themebar-chip.is-on { color: var(--flow); background: rgba(var(--flow-rgb), 0.09); border-color: rgba(var(--flow-rgb), 0.55); }
.bp-themebar-chip--sov:hover:not(:disabled), .bp-themebar-chip--sov.is-on { color: #ef4444; border-color: rgba(239, 68, 68, 0.55); background: rgba(239, 68, 68, 0.07); }
.bp-themebar-chip.is-locked { opacity: 0.4; cursor: not-allowed; }
.bp-themebar-chip.is-locked:hover { color: var(--bp-dim); border-color: rgba(var(--flow-rgb), 0.22); }
.bp-themebar-dot { width: 9px; height: 9px; border-radius: 50%; border: 1px solid rgba(255, 255, 255, 0.35); }

.bp-finder { display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.4rem; }
.bp-finder-k { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; letter-spacing: 0.14em; color: rgba(var(--flow-rgb), 0.8); }
.bp-finder-sel { flex: 1; max-width: 430px; font-family: var(--bp-mono); font-size: 0.72rem; color: var(--bp-ink-soft); background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(var(--flow-rgb), 0.22); border-radius: 8px; padding: 0.5rem 0.7rem; cursor: pointer; }
.bp-finder-sel:focus { outline: none; border-color: rgba(var(--flow-rgb), 0.5); box-shadow: 0 0 0 3px rgba(var(--flow-rgb), 0.12); }
.bp-finder-sel option, .bp-finder-sel optgroup { background: #0a0f17; color: var(--bp-ink-soft); }

.bp-railtip { position: fixed; z-index: 4000; max-width: 340px; pointer-events: none; background: rgba(8, 12, 20, 0.97); border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 10px; padding: 0.6rem 0.75rem; box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.9); }
.bp-railtip-head { display: block; font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 800; color: var(--flow); margin-bottom: 0.3rem; }
.bp-railtip-body { display: block; font-size: 0.7rem; color: var(--bp-ink-soft); line-height: 1.55; }
.bp-crumb-home { color: var(--bp-dim); text-decoration: none; }
.bp-crumb-home:hover { color: var(--flow); }
.bp-crumb-sep { opacity: 0.4; }

/* Hero */
.bp-hero { text-align: center; margin-bottom: 2.4rem; }
.bp-hero-mark { display: flex; justify-content: center; margin-bottom: 0.9rem; }
.bp-hero-chip { display: inline-block; font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; letter-spacing: 0.16em; color: var(--flow); background: rgba(var(--flow-rgb), 0.08); border: 1px solid rgba(var(--flow-rgb), 0.25); border-radius: 20px; padding: 0.3rem 0.8rem; margin-bottom: 1.1rem; }
.bp-h1 { margin: 0 0 0.8rem; font-size: 2.15rem; font-weight: 800; line-height: 1.22; color: var(--bp-ink); letter-spacing: -0.01em; }
.bp-h1-accent { color: var(--flow); text-shadow: 0 0 26px rgba(var(--flow-rgb), 0.35); }
.bp-lead { margin: 0 auto; max-width: 700px; font-size: 0.9rem; color: var(--bp-dim); line-height: 1.7; }
.bp-lead--tight { margin: 0 0 1.2rem; max-width: 720px; }

.bp-hero-loom {
  margin: 1.8rem auto 1.2rem;
  padding: 1.1rem 1.2rem 0.9rem;
  border: 1px solid rgba(var(--flow-rgb), 0.16);
  border-radius: 14px;
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 60%), rgba(var(--flow-rgb), 0.028);
  text-align: left;
}

.bp-pills { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.7rem; }
.bp-pill { border: 1px solid rgba(var(--flow-rgb), 0.16); border-radius: 11px; background: rgba(var(--flow-rgb), 0.03); padding: 0.75rem 0.8rem; text-align: center; text-decoration: none; }
.bp-pill-v { display: block; font-family: var(--bp-mono); font-size: 1.35rem; font-weight: 800; color: var(--bp-ink); font-variant-numeric: tabular-nums; }
.bp-pill-k { display: block; margin-top: 0.25rem; font-family: var(--bp-mono); font-size: 0.56rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.09em; color: var(--bp-faint); line-height: 1.5; }
.bp-pill--link .bp-pill-v { color: #10b981; }
.bp-pill--link:hover { border-color: rgba(16, 185, 129, 0.5); }

/* How-to-read */
.bp-howto { border: 1px solid rgba(var(--flow-rgb), 0.14); border-left: 3px solid rgba(var(--flow-rgb), 0.5); border-radius: 10px; background: rgba(var(--flow-rgb), 0.028); padding: 0.85rem 1.05rem; font-size: 0.74rem; color: var(--bp-dim); line-height: 1.9; margin-bottom: 2.6rem; }
.bp-howto strong { color: var(--bp-ink); }
.bp-badge-demo { font-family: var(--bp-mono); font-size: 0.56rem; font-weight: 700; border-radius: 5px; padding: 0.16rem 0.4rem; margin: 0 0.15rem; white-space: nowrap; }
.bp-badge-demo[data-s="LIVE"] { color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); }
.bp-badge-demo[data-s="LIVE (gated)"] { color: var(--flow); border: 1px solid rgba(var(--flow-rgb), 0.4); }
.bp-badge-demo[data-s="SHADOW"] { color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); }
.bp-badge-demo[data-s="DESIGNED"] { color: #8b98a7; border: 1px dashed rgba(139, 152, 167, 0.5); }

/* Index */
.bp-index { margin-bottom: 1rem; }
.bp-index-tier { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; letter-spacing: 0.14em; color: rgba(var(--flow-rgb), 0.75); margin: 1.3rem 0 0.45rem; }
.bp-index-row {
  display: grid; grid-template-columns: 2.4rem 9.5rem 1fr auto; gap: 0.7rem; align-items: baseline;
  width: 100%; text-align: left; background: transparent; border: 0; border-top: 1px solid rgba(var(--flow-rgb), 0.08);
  padding: 0.55rem 0.3rem; cursor: pointer; transition: background 0.2s ease;
}
.bp-index-row:hover { background: rgba(var(--flow-rgb), 0.04); }
.bp-index-rank { font-family: var(--bp-mono); font-size: 0.78rem; font-weight: 800; color: rgba(var(--flow-rgb), 0.55); font-variant-numeric: tabular-nums; }
.bp-index-name { font-family: var(--bp-mono); font-size: 0.8rem; font-weight: 800; letter-spacing: 0.05em; color: var(--bp-ink); }
.bp-index-ind { display: none; }
.bp-index-promise { font-size: 0.73rem; color: var(--bp-faint); line-height: 1.45; }
.bp-index-ratio { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; color: #10b981; }

/* Section furniture */
.bp-sec-label { display: block; font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: rgba(var(--flow-rgb), 0.8); margin-bottom: 0.5rem; }
.bp-h2 { margin: 0 0 0.55rem; font-size: 1.45rem; font-weight: 800; color: var(--bp-ink); }

/* The Atlas grid (§18) */
.bp-atlas { padding-top: 3rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); margin-bottom: 3rem; }
.bp-atlas-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.9rem; }
.bp-atlas-card {
  display: flex; flex-direction: column; gap: 0.55rem; text-decoration: none;
  border: 1px solid rgba(var(--flow-rgb), 0.16); border-radius: 14px;
  background: rgba(var(--flow-rgb), 0.025); padding: 1rem 1.1rem;
  transition: border-color 0.25s ease, background 0.25s ease, box-shadow 0.25s ease;
}
.bp-atlas-card:hover { border-color: rgba(var(--flow-rgb), 0.5); background: rgba(var(--flow-rgb), 0.05); box-shadow: 0 12px 32px -18px rgba(var(--flow-rgb), 0.5); }
.bp-atlas-top { display: flex; align-items: flex-start; gap: 0.7rem; }
.bp-atlas-rank { font-family: var(--bp-mono); font-size: 1.15rem; font-weight: 800; color: rgba(var(--flow-rgb), 0.55); line-height: 1.2; font-variant-numeric: tabular-nums; }
.bp-atlas-names { flex: 1; min-width: 0; }
.bp-atlas-ind { display: block; font-family: var(--bp-mono); font-size: 0.58rem; font-weight: 700; letter-spacing: 0.1em; color: var(--bp-faint); text-transform: uppercase; }
.bp-atlas-name { display: block; font-family: var(--bp-mono); font-size: 0.95rem; font-weight: 800; letter-spacing: 0.04em; color: var(--bp-ink); }
.bp-atlas-chip { font-family: var(--bp-mono); font-size: 0.54rem; font-weight: 800; letter-spacing: 0.1em; color: var(--flow); border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 5px; padding: 0.16rem 0.4rem; flex-shrink: 0; }
.bp-atlas-chip--dim { color: var(--bp-faint); border-color: rgba(107, 119, 133, 0.4); }
.bp-atlas-chip--deep { color: #10b981; border-color: rgba(16, 185, 129, 0.45); }
.bp-atlas-chip--frontier { color: #c4b5fd; border: 1px dashed rgba(196, 181, 253, 0.55); }
.bp-index-tier--frontier { color: #c4b5fd; }
.bp-howto-link { color: var(--flow); text-decoration: underline; text-underline-offset: 2px; }
.bp-atlas-promise { margin: 0; font-size: 0.76rem; color: var(--bp-dim); line-height: 1.55; }
.bp-atlas-cases { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.bp-atlas-case { font-size: 0.62rem; color: var(--bp-ink-soft); border: 1px solid rgba(var(--flow-rgb), 0.18); border-radius: 20px; padding: 0.18rem 0.55rem; }
.bp-atlas-foot { display: flex; align-items: center; gap: 0.6rem; margin-top: auto; }
.bp-atlas-rails { display: flex; gap: 0.25rem; flex-wrap: wrap; flex: 1; }
.bp-atlas-rail { font-family: var(--bp-mono); font-size: 0.56rem; font-weight: 700; color: rgba(var(--flow-rgb), 0.75); border: 1px solid rgba(var(--flow-rgb), 0.25); border-radius: 4px; padding: 0.1rem 0.3rem; cursor: help; }
.bp-atlas-ratio { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; color: #10b981; flex-shrink: 0; }
.bp-atlas-open { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 800; letter-spacing: 0.1em; color: var(--flow); flex-shrink: 0; }

.bp-safety { margin-bottom: 3rem; padding-top: 3rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); }

.bp-mgmt { margin-bottom: 3rem; padding: 1.6rem 1.7rem; border: 1px solid rgba(var(--flow-rgb), 0.16); border-left: 3px solid rgba(var(--flow-rgb), 0.5); border-radius: 13px; background: rgba(var(--flow-rgb), 0.025); }
.bp-mgmt-links { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }
.bp-mgmt-link { font-family: var(--bp-mono); font-size: 0.68rem; font-weight: 700; color: rgba(var(--flow-rgb), 0.95); border: 1px solid rgba(var(--flow-rgb), 0.3); border-radius: 20px; padding: 0.32rem 0.75rem; text-decoration: none; }
.bp-mgmt-link:hover { background: rgba(var(--flow-rgb), 0.08); }

.bp-proof { margin-bottom: 3rem; padding-top: 3rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); }
.bp-proof-grid { display: flex; flex-direction: column; gap: 0.65rem; }
.bp-proof-note { margin-top: 0.8rem; border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 9px; background: rgba(245, 158, 11, 0.04); padding: 0.6rem 0.9rem; font-size: 0.72rem; color: var(--bp-dim); line-height: 1.6; }
.bp-proof-note a { color: var(--flow); text-decoration: none; font-weight: 600; }
.bp-proof-note a:hover { text-decoration: underline; }
.bp-proof-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 0.8rem; }
.bp-proof-meter { font-family: var(--bp-mono); font-size: 0.62rem; color: var(--bp-faint); }
.bp-proof-more { font-size: 0.74rem; font-weight: 600; color: var(--flow); text-decoration: none; }
.bp-proof-more:hover { text-decoration: underline; }

.bp-vault { margin-bottom: 3rem; padding-top: 3rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); }
.bp-vault-grid { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.bp-vault-item { font-family: var(--bp-mono); font-size: 0.68rem; color: var(--bp-dim); border: 1px dashed rgba(var(--flow-rgb), 0.25); border-radius: 20px; padding: 0.35rem 0.8rem; }
.bp-vault-cta { display: inline-block; font-size: 0.78rem; font-weight: 700; color: var(--flow); text-decoration: none; }
.bp-vault-cta:hover { text-decoration: underline; }

.bp-cta { text-align: center; border: 1px solid rgba(var(--flow-rgb), 0.16); border-radius: 14px; background: linear-gradient(168deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 60%), rgba(var(--flow-rgb), 0.03); padding: 2rem 1.5rem; margin-bottom: 2rem; }
.bp-cta .bp-lead--tight { margin-left: auto; margin-right: auto; }
.bp-cta-acts { display: flex; gap: 0.6rem; justify-content: center; flex-wrap: wrap; }
.bp-btn { display: inline-block; font-size: 0.78rem; font-weight: 700; color: var(--flow); background: rgba(var(--flow-rgb), 0.1); border: 1px solid rgba(var(--flow-rgb), 0.35); border-radius: 9px; padding: 0.6rem 1.15rem; text-decoration: none; transition: filter 0.2s ease, transform 0.1s ease; }
.bp-btn:hover { filter: brightness(1.2); }
.bp-btn:active { transform: translateY(1px); }
.bp-btn--primary { color: #041014; background: var(--flow); border-color: var(--flow); }

.bp-footer { text-align: center; font-size: 0.62rem; color: var(--bp-faint); padding-top: 1rem; }
.bp-footer-link { color: var(--bp-dim); text-decoration: none; }
.bp-footer-link:hover { color: var(--flow); }

@media (max-width: 820px) {
  .bp-h1 { font-size: 1.5rem; }
  .bp-crumb { flex-wrap: wrap; }
  .bp-themebar { margin-left: 0; width: 100%; margin-top: 0.5rem; }
  .bp-finder { flex-direction: column; align-items: stretch; gap: 0.4rem; }
  .bp-finder-sel { max-width: none; }
  .bp-pills { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bp-index-row { grid-template-columns: 2rem 1fr auto; }
  .bp-index-promise { display: none; }
  .bp-atlas-grid { grid-template-columns: 1fr; }
  .bp-cta-acts { flex-direction: column; }
}
</style>
