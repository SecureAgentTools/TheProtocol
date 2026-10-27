<template>
  <div class="bp-root" @pointermove="onRailPointer" @pointerleave="railTip = null">
    <div class="bp-wrap">
      <!-- Breadcrumb -->
      <nav class="bpd-crumb" :aria-label="t('blueprintsView.crumb', 'Industry Blueprints')">
        <router-link to="/" class="bpd-crumb-home">TheProtocol</router-link>
        <span class="bpd-crumb-sep">/</span>
        <router-link to="/blueprints" class="bpd-crumb-home">{{ t('blueprintsView.crumb', 'Industry Blueprints') }}</router-link>
        <span class="bpd-crumb-sep">/</span>
        <span>{{ bp?.systemName || '' }}</span>
      </nav>

      <template v-if="bp">
        <!-- The full anatomy, unchanged -->
        <BlueprintSection :key="bp.id" :bp="bp" />

        <!-- Deep layers (§18.3) -->
        <template v-if="deep">
          <section class="bpd-sec">
            <span class="bpd-label">{{ t('blueprintsView.deep.archLabel', 'Reference architecture') }}</span>
            <h2 class="bpd-h2">{{ t('blueprintsView.deep.archTitle', 'How it sits in a real estate') }}</h2>
            <p v-if="deep.intro" class="bpd-lead">{{ deep.intro }}</p>
            <ArchLoom :arch="deep.arch" :aria-title="`${bp.systemName} reference architecture`" />
            <p class="bpd-machinery">
              {{ t('blueprintsView.deep.machinery', 'Every chamber stands on the same machinery: the registries, transfer gateways, ledgers and identity fabric of the live network. It is drawn component by component, from the whole network down to one transfer, in') }}
              <router-link to="/docs/35" class="bpd-machinery-link">{{ t('blueprintsView.howto.archLink', 'The Architecture') }}</router-link>.
            </p>
          </section>

          <section class="bpd-sec">
            <span class="bpd-label">{{ t('blueprintsView.deep.planLabel', 'The adoption path') }}</span>
            <h2 class="bpd-h2">{{ t('blueprintsView.deep.planTitle', 'Four phases, each ending on proof') }}</h2>
            <div class="bpd-phases">
              <article v-for="(p, i) in deep.plan" :key="p.name" class="bpd-phase">
                <div class="bpd-phase-head">
                  <span class="bpd-phase-no">{{ i }}</span>
                  <div>
                    <span class="bpd-phase-name">{{ p.name }}</span>
                    <span class="bpd-phase-headline">{{ p.headline }}</span>
                  </div>
                </div>
                <dl class="bpd-phase-rows">
                  <div><dt>{{ t('blueprintsView.deep.runs', 'Runs') }}</dt><dd>{{ p.runs }}</dd></div>
                  <div><dt>{{ t('blueprintsView.deep.agents', 'Agents') }}</dt><dd>{{ p.agents }}</dd></div>
                  <div><dt>{{ t('blueprintsView.deep.integrates', 'Integrates') }}</dt><dd>{{ p.integrates }}</dd></div>
                  <div><dt>{{ t('blueprintsView.deep.notYet', 'Not yet') }}</dt><dd>{{ p.notYet }}</dd></div>
                  <div class="bpd-proof"><dt>{{ t('blueprintsView.deep.proof', 'Proof') }}</dt><dd>{{ p.proof }}</dd></div>
                </dl>
              </article>
            </div>
          </section>

          <details v-if="deep.sequence" class="bpd-wiring" @toggle="onSequenceToggle">
            <summary>{{ deep.sequenceTitle || t('blueprintsView.deep.seq', 'The settlement path, as messages') }}</summary>
            <div class="bpd-wiring-body">
              <pre :class="`bp-mermaid bpd-mermaid-${bp.id}`">{{ deep.sequence }}</pre>
            </div>
          </details>

          <section v-if="deep.sizing?.length" class="bpd-sec">
            <span class="bpd-label">{{ t('blueprintsView.deep.sizingLabel', 'Sizing truth') }}</span>
            <h2 class="bpd-h2">{{ t('blueprintsView.deep.sizingTitle', 'What you actually run') }}</h2>
            <div class="bpd-tablewrap">
              <table class="bpd-table">
                <thead><tr><th>{{ t('blueprintsView.deep.level', 'Level') }}</th><th>{{ t('blueprintsView.deep.what', 'What it means') }}</th><th>{{ t('blueprintsView.deep.containers', 'Containers') }}</th></tr></thead>
                <tbody>
                  <tr v-for="r in deep.sizing" :key="r.level">
                    <td class="bpd-mono">{{ r.level }}</td><td>{{ r.what }}</td><td class="bpd-mono">{{ r.containers }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>

        <!-- Honest state for chambers whose deep layer is not drafted yet -->
        <section v-else-if="!deepLoading" class="bpd-drafting">
          <span class="bpd-drafting-chip">{{ t('blueprintsView.deep.draftingChip', 'IN DRAFTING') }}</span>
          <p class="bpd-drafting-text">{{ t('blueprintsView.deep.drafting', 'The deep architecture for this industry, its reference topology, adoption path and settlement sequence, is being drafted in an upcoming wave. The anatomy above is the current truth; nothing here is ever mocked up to look finished.') }}</p>
        </section>

        <!-- Prev / next -->
        <nav class="bpd-nav">
          <router-link v-if="prevBp" :to="`/blueprints/${prevBp.id}`" class="bpd-nav-link">
            <span class="bpd-nav-k">{{ t('blueprintsView.deep.prev', 'PREVIOUS') }}</span>
            <span class="bpd-nav-name">{{ String(prevBp.rank).padStart(2, '0') }} {{ prevBp.systemName }}</span>
          </router-link>
          <span v-else></span>
          <router-link to="/blueprints" class="bpd-nav-atlas">{{ t('blueprintsView.deep.atlas', 'All industries') }}</router-link>
          <router-link v-if="nextBp" :to="`/blueprints/${nextBp.id}`" class="bpd-nav-link bpd-nav-link--next">
            <span class="bpd-nav-k">{{ t('blueprintsView.deep.next', 'NEXT') }}</span>
            <span class="bpd-nav-name">{{ String(nextBp.rank).padStart(2, '0') }} {{ nextBp.systemName }}</span>
          </router-link>
          <span v-else></span>
        </nav>
      </template>
    </div>

    <!-- Rail tooltip singleton (same contract as the Atlas) -->
    <div v-if="railTip" ref="railTipEl" class="bpd-railtip" role="tooltip">
      <span class="bpd-railtip-head">{{ railTip.id }} · {{ railTip.name }}</span>
      <span class="bpd-railtip-body">{{ railTip.refusal }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// The chamber (strategy §18.2): one industry, full anatomy plus the deep
// layers. Deep data is lazy: the Atlas never pays for it, and a chamber
// without an arch module states so honestly instead of pretending.
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import BlueprintSection from '@/components/blueprints/BlueprintSection.vue'
import ArchLoom from '@/components/blueprints/ArchLoom.vue'
import { BLUEPRINTS } from '@/data/blueprints'
import { ARCH_LOADERS } from '@/data/blueprints/arch'
import { RAIL_BY_ID } from '@/data/blueprints/rails'
import type { Blueprint, BlueprintDeep, Rail } from '@/data/blueprints/types'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const byRank = [...BLUEPRINTS].sort((a, b) => a.rank - b.rank)
const bp = ref<Blueprint | null>(null)
const deep = ref<BlueprintDeep | null>(null)
const deepLoading = ref(false)

const prevBp = computed(() => {
  if (!bp.value) return null
  const i = byRank.findIndex((b) => b.id === bp.value!.id)
  return i > 0 ? byRank[i - 1] : null
})
const nextBp = computed(() => {
  if (!bp.value) return null
  const i = byRank.findIndex((b) => b.id === bp.value!.id)
  return i >= 0 && i < byRank.length - 1 ? byRank[i + 1] : null
})

// Declared before resolve(): the immediate watcher below calls resolve()
// synchronously during setup, and a later `let` would still be in its
// temporal dead zone at that moment.
let sequenceRendered = false

async function resolve(id: string) {
  const found = BLUEPRINTS.find((b) => b.id === id) || null
  if (!found) { router.replace('/blueprints'); return }
  bp.value = found
  deep.value = null
  sequenceRendered = false
  const loader = ARCH_LOADERS[id]
  if (loader) {
    deepLoading.value = true
    try {
      const mod = await loader()
      // Guard against a stale resolve landing after another navigation.
      if (bp.value?.id === id) deep.value = mod.deep
    } finally {
      deepLoading.value = false
    }
  }
  window.scrollTo({ top: 0 })
}

watch(() => route.params.id, (id) => { if (typeof id === 'string') resolve(id) }, { immediate: true })

// Sequence diagram renders only when opened, same contract as the wiring.
async function onSequenceToggle(ev: Event) {
  const el = ev.target as HTMLDetailsElement
  if (!el.open || sequenceRendered || !bp.value) return
  sequenceRendered = true
  const { renderMermaidDiagrams } = await import('@/composables/docs/useMermaidRenderer')
  await renderMermaidDiagrams({ selector: `.bpd-mermaid-${bp.value.id}`, theme: 'blueprints' })
}

// Rail tooltip singleton — same behavior as the Atlas page.
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
</script>

<script lang="ts">
export default { name: 'BlueprintDetailView' }
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

.bpd-crumb { display: flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; color: var(--bp-faint); margin-bottom: 1rem; }
.bpd-crumb-home { color: var(--bp-dim); text-decoration: none; }
.bpd-crumb-home:hover { color: var(--flow); }
.bpd-crumb-sep { opacity: 0.4; }

.bpd-sec { padding-top: 3rem; margin-bottom: 1.5rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); }
.bpd-label { display: inline-block; font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 800; letter-spacing: 0.16em; color: var(--flow); border: 1px solid rgba(var(--flow-rgb), 0.35); border-radius: 20px; padding: 0.3rem 0.85rem; margin-bottom: 0.9rem; }
.bpd-h2 { font-size: 1.5rem; font-weight: 800; color: var(--bp-ink); letter-spacing: -0.01em; margin: 0 0 0.7rem; }
.bpd-lead { font-size: 0.86rem; color: var(--bp-dim); line-height: 1.75; max-width: 62rem; margin: 0 0 1.4rem; }
.bpd-machinery { font-size: 0.8rem; color: var(--bp-dim); line-height: 1.7; max-width: 62rem; margin: 1rem 0 0; }
.bpd-machinery-link { color: var(--flow); text-decoration: underline; text-underline-offset: 2px; }

/* Adoption phases */
.bpd-phases { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
.bpd-phase { border: 1px solid rgba(var(--flow-rgb), 0.16); border-radius: 14px; background: rgba(var(--flow-rgb), 0.025); padding: 1.1rem 1.2rem; }
.bpd-phase-head { display: flex; align-items: flex-start; gap: 0.8rem; margin-bottom: 0.8rem; }
.bpd-phase-no { font-family: var(--bp-mono); font-size: 1.3rem; font-weight: 800; color: rgba(var(--flow-rgb), 0.55); line-height: 1.15; }
.bpd-phase-name { display: block; font-family: var(--bp-mono); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.12em; color: var(--flow); text-transform: uppercase; }
.bpd-phase-headline { display: block; font-size: 0.86rem; font-weight: 700; color: var(--bp-ink); margin-top: 0.15rem; }
.bpd-phase-rows { margin: 0; display: grid; gap: 0.45rem; }
.bpd-phase-rows > div { display: grid; grid-template-columns: 5.4rem 1fr; gap: 0.6rem; }
.bpd-phase-rows dt { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; letter-spacing: 0.08em; color: var(--bp-faint); text-transform: uppercase; padding-top: 0.14rem; }
.bpd-phase-rows dd { margin: 0; font-size: 0.76rem; color: var(--bp-ink-soft); line-height: 1.55; }
.bpd-proof dt { color: #10b981; }
.bpd-proof dd { color: var(--bp-ink); }

/* Sequence disclosure (mirrors the wiring pattern) */
.bpd-wiring { margin: 1.4rem 0 0; border: 1px solid rgba(var(--flow-rgb), 0.16); border-radius: 12px; background: rgba(var(--flow-rgb), 0.02); }
.bpd-wiring summary { font-family: var(--bp-mono); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; color: var(--bp-dim); padding: 0.85rem 1.1rem; cursor: pointer; }
.bpd-wiring summary:hover { color: var(--flow); }
.bpd-wiring-body { padding: 0.4rem 1.1rem 1.1rem; overflow-x: auto; }

/* Sizing table */
.bpd-tablewrap { overflow-x: auto; }
.bpd-table { width: 100%; border-collapse: collapse; }
.bpd-table th { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 800; letter-spacing: 0.1em; color: var(--bp-faint); text-align: left; text-transform: uppercase; padding: 0.5rem 0.8rem; border-bottom: 1px solid rgba(var(--flow-rgb), 0.2); }
.bpd-table td { font-size: 0.78rem; color: var(--bp-ink-soft); padding: 0.6rem 0.8rem; border-bottom: 1px solid rgba(var(--flow-rgb), 0.08); line-height: 1.55; }
.bpd-mono { font-family: var(--bp-mono); font-size: 0.72rem; color: var(--flow); white-space: nowrap; }

/* In-drafting band */
.bpd-drafting { display: flex; align-items: flex-start; gap: 0.9rem; margin-top: 2.4rem; padding: 1.1rem 1.2rem; border: 1px dashed rgba(var(--flow-rgb), 0.3); border-radius: 12px; }
.bpd-drafting-chip { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 800; letter-spacing: 0.12em; color: var(--flow); border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 5px; padding: 0.2rem 0.5rem; flex-shrink: 0; margin-top: 0.1rem; }
.bpd-drafting-text { margin: 0; font-size: 0.76rem; color: var(--bp-dim); line-height: 1.65; }

/* Prev / next */
.bpd-nav { display: grid; grid-template-columns: 1fr auto 1fr; gap: 1rem; align-items: center; margin-top: 3rem; padding-top: 1.6rem; border-top: 1px solid rgba(var(--flow-rgb), 0.12); }
.bpd-nav-link { display: inline-flex; flex-direction: column; gap: 0.2rem; text-decoration: none; }
.bpd-nav-link--next { justify-self: end; text-align: right; }
.bpd-nav-k { font-family: var(--bp-mono); font-size: 0.58rem; font-weight: 800; letter-spacing: 0.14em; color: var(--bp-faint); }
.bpd-nav-name { font-family: var(--bp-mono); font-size: 0.8rem; font-weight: 800; color: var(--bp-dim); transition: color 0.2s ease; }
.bpd-nav-link:hover .bpd-nav-name { color: var(--flow); }
.bpd-nav-atlas { font-family: var(--bp-mono); font-size: 0.66rem; font-weight: 700; letter-spacing: 0.08em; color: var(--flow); text-decoration: none; border: 1px solid rgba(var(--flow-rgb), 0.35); border-radius: 20px; padding: 0.45rem 1rem; }
.bpd-nav-atlas:hover { background: rgba(var(--flow-rgb), 0.08); }

/* Rail tooltip singleton */
.bpd-railtip { position: fixed; z-index: 4000; max-width: 340px; pointer-events: none; background: rgba(8, 12, 20, 0.97); border: 1px solid rgba(var(--flow-rgb), 0.4); border-radius: 10px; padding: 0.6rem 0.75rem; box-shadow: 0 14px 34px -14px rgba(0, 0, 0, 0.9); }
.bpd-railtip-head { display: block; font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 800; color: var(--flow); margin-bottom: 0.3rem; }
.bpd-railtip-body { display: block; font-size: 0.7rem; color: var(--bp-ink-soft); line-height: 1.55; }

@media (max-width: 860px) {
  .bpd-phases { grid-template-columns: 1fr; }
  .bpd-nav { grid-template-columns: 1fr; justify-items: start; }
  .bpd-nav-link--next { justify-self: start; text-align: left; }
}
</style>
