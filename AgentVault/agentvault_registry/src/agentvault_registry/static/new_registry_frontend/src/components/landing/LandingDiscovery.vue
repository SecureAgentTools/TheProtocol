<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §LANDINGDISC (2026-09-06, his word: "replace the 'sandbox networks' on discovery with an embedded
// version of the agent discovery /explore and a button or something to the whole version"), refined on
// his second look: "it should contain the current cards of the discovery and also the avatar place. how
// the discovery display on card with encirclements and everything. clickable modal opens."
//
// So this MOUNTS Discovery in `embedded` mode instead of rendering a preview card of its own. The tiles
// are the real ones — avatar, flare encirclement, provenance badge, bond chip — and clicking one opens
// the same AgentDetailModal the page opens, because it IS the page. My first pass rendered a compact
// tile of my own design and he was right that it was the wrong call: a second implementation of a card
// is a second thing to drift.
//
// The view is loaded ASYNC so the landing chunk does not carry Discovery's tree for visitors who never
// scroll this far, and the section hides itself when the network has nothing to sample.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, onMounted, defineAsyncComponent } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
const Discovery = defineAsyncComponent(() => import('@/views/Discovery.vue'))

const total = ref(0)
const ready = ref(false)

onMounted(async () => {
  try {
    // one cheap same-origin HEAD-ish read purely to decide whether to mount at all — and deliberately not
    // through apiClient, so a page with no session never touches the auth interceptor.
    const r = await fetch('/api/v1/agent-cards/discover?limit=1', { headers: { Accept: 'application/json' } })
    if (!r.ok) return
    const d = await r.json()
    total.value = Number(d?.total) || 0
    ready.value = Array.isArray(d?.items) && d.items.length > 0
  } catch { /* the section stays hidden — never a dead promise */ }
})
</script>

<template>
  <section v-if="ready" class="lp-disc lp-section" data-testid="lp-disc">
    <div class="lp-container">
      <p class="lp-strips-kicker">{{ t('landingPage.discovery.kicker', 'Agent discovery') }}</p>
      <h2 class="lp-disc-title">{{ t('landingPage.discovery.title', 'Who is on this network right now') }}</h2>
      <p class="lp-disc-lead">
        {{ t('landingPage.discovery.lead', 'Every agent below is discoverable from this registry and backed by a reputation bond its home enforces. The same list, its cross-currency neighbours and everything the federated index can see are one page away — no account needed to look.') }}
      </p>

      <!-- the real discovery grid: same cards, same flares, same modal -->
      <div class="lp-disc-embed">
        <Discovery embedded :preview-limit="6" />
      </div>

      <div class="lp-disc-actions">
        <a class="lp-cta" href="#/explore" data-testid="lp-disc-cta">
          {{ tp('landingPage.discovery.cta', 'Explore all {n} agents', { n: total.toLocaleString() }) }}
        </a>
        <span class="lp-disc-note">{{ t('landingPage.discovery.note', 'Public view — browsing needs no account; engaging an agent does.') }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ⚠ LandingPage.vue's styles are SCOPED, so `.lp-container`, `.lp-strips-kicker` and `.lp-cta` do NOT
   reach this child — measured on the first drive: the CTA had no background and 0 padding, the kicker
   rendered as 16px body text, and the container was 1376px wide against the page's real 1200. Borrowing
   a class NAME from a scoped stylesheet borrows nothing. These are this component's own copies, with the
   same values as the page's, and they are the reason the section sits on the page's grid rather than
   beside it. */
.lp-container { max-width: 1200px; margin: 0 auto; }
.lp-strips-kicker {
  margin: 0 0 .1rem; font-family: 'IBM Plex Mono', monospace; font-size: .6rem; letter-spacing: .18em;
  text-transform: uppercase; color: rgba(var(--nc-primary-rgb), .7);
}
.lp-cta {
  display: inline-flex; align-items: center; gap: 0.6rem; padding: 0.85rem 2rem;
  background: var(--nc-primary); color: #060810; font-size: 0.85rem; font-weight: 600;
  letter-spacing: 0.08em; border: none; cursor: pointer; transition: all 0.2s; text-decoration: none;
}
.lp-cta:hover { background: #00baba; box-shadow: 0 0 32px rgba(var(--nc-primary-rgb), 0.3); transform: translateY(-1px); }

.lp-disc { padding: 3rem 0; border-top: 1px solid var(--lp-hairline, rgba(255,255,255,.08)); }
.lp-disc-title { font-size: clamp(1.4rem, 2.6vw, 2.1rem); margin: .25rem 0 .5rem; }
.lp-disc-lead { max-width: 70ch; opacity: .85; margin-bottom: 1.5rem; }
/* The embed is Discovery's own markup, so it brings its own card styles. What belongs here is only how
   the block sits on the landing page: no page padding of its own, and the view's page shell neutralised. */
.lp-disc-embed { margin-top: .25rem; }
.lp-disc-embed :deep(.nc-page) { padding: 0; background: none; min-height: 0; }
.lp-disc-embed :deep(.disc-embedded .flex.gap-6) { gap: 0; }

.lp-disc-actions { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-top: 1.5rem; }
.lp-disc-note { font-size: .72rem; opacity: .55; }
</style>
