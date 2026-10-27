<script setup lang="ts">
/**
 * GuidedTour — global spotlight overlay. Mounted once in DashboardLayout.
 * Reads the guidedTour store; measures the anchored `[data-tour]` element and renders a
 * dimmed backdrop with a lit "spotlight" cutout + a floating coachmark. Educational &
 * safe: it guides + explains; navigation is via Back/Next/Skip (the store handles routing).
 */
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useGuidedTourStore, findAnchor } from './tourStore'
import Icon from '@/components/Icon.vue'
import { apiClient } from '@/services/api/client'
import { getTour } from './tourRegistry'
import { useUIStore } from '@/stores/ui'
import { tourKeyAction, isEditableTarget } from './tourKeys'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { walletSentence } from '@/services/walletAgent'
import { useCurrency } from '@/composables/useCurrency'
import { withUnit } from './tourUnit'

const tour = useGuidedTourStore()
/* §WALLETAGENT (2026-09-02) — the needs-agent coachmark is where every agent-gated tour pauses,
 * so it is where the wallet agent is explained and created. The tour resumes by itself. */
const uiStore = useUIStore()
const auth = useAuthStore()
const { t } = useI18n()
// §FESUITE V0597: a tour's {unit} is the frame's own unit (tourUnit.ts)
const { localCurrency } = useCurrency()
const walletLines = computed(() => walletSentence(t))
const hasNoAgents = computed(() => ((auth as any).availableAgents?.length ?? 0) === 0)
function createWalletFromTour() { uiStore.openQuickAgentModal() }
function pickAgent() { (auth as any).showAgentSelector = true }
watch(() => uiStore.agentCreatedTick, () => {
  if (tour.needsAgent) { void tour.retryStep(); return }
  if (tour.currentStep?.cta?.do === 'create-wallet') void tour.next()
})
watch(() => tour.needsAgent, (v) => { if (v && !(auth as any).availableAgents?.length) void (auth as any).fetchAvailableAgents?.() })
const route = useRoute()
// Deep-link launcher: ?tour=agora auto-starts a tour (shareable + testable).
watch(() => route.query.tour, (t) => {
  if (typeof t === 'string' && t && !tour.isActive) tour.start(t)
}, { immediate: true })

// Contextual launcher — a dismissible pill suggesting the tour for the current area.
const dismissed = ref<string[]>((() => { try { return JSON.parse(localStorage.getItem('gt_dismissed') || '[]') } catch { return [] } })())
const suggestedId = computed(() => {
  const p = route.path
  if (p.startsWith('/agora') || p.startsWith('/stocks') || p.startsWith('/exchange')) return 'agora'
  if (p.startsWith('/organization')) return 'organizations'
  if (p.startsWith('/ci-cd') || /\/agent\/.+\/ci-cd/.test(p)) return 'cicd'
  if (p.startsWith('/mission-control') || p.startsWith('/my-agents')) return 'first-steps'
  return ''
})
const suggested = computed(() => (suggestedId.value && !dismissed.value.includes(suggestedId.value)) ? getTour(suggestedId.value) : null)
function dismissSuggested() {
  if (!suggestedId.value) return
  dismissed.value = [...dismissed.value, suggestedId.value]
  try { localStorage.setItem('gt_dismissed', JSON.stringify(dismissed.value)) } catch { /* ignore */ }
}

const rect = ref<{ top: number; left: number; width: number; height: number } | null>(null)
const PAD = 8
// Live-measured coachmark size → drives accurate flip/clamp/arrow positioning
// (replaces the old hardcoded 230/240 height guesses).
const coachEl = ref<HTMLElement | null>(null)
const coachH = ref(240)
function measureCoach() { const h = coachEl.value?.offsetHeight; if (h) coachH.value = h }

function measure() {
  const step = tour.currentStep
  if (!step || !step.anchor || tour.needsAgent || tour.anchorMissing) { rect.value = null; return }
  // §TOURFIX (2026-08-14): resolve through findAnchor, never a raw querySelector.
  // `anchor` may be a comma-separated alternatives chain ('org-tab-teams,org-hero');
  // the raw string built a selector that matched NOTHING, so the store found and
  // scrolled to the element while this overlay full-dimmed with no spotlight — the
  // "tour stops highlighting" report, on every chained step of every tour.
  const el = findAnchor(step.anchor)
  if (!el) { rect.value = null; observeAnchor(null); return }
  const r = el.getBoundingClientRect()
  rect.value = { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }
  observeAnchor(el)
}

// §POCKETBRIDGE5 — the spotlight measured ONCE per step, but anchors GROW
// after entry: the Pocket balance hero adds its flow chip and live strip
// seconds after render, so the box sat too high and stopped short of the
// card's real bottom (Commander's report, tour step 2). A ResizeObserver on
// the CURRENT anchor re-measures on any size change; scroll/resize listeners
// already cover movement.
let anchorRO: ResizeObserver | null = null
let observedEl: Element | null = null
function observeAnchor(el: Element | null) {
  if (el === observedEl) return
  anchorRO?.disconnect()
  observedEl = el
  if (!el || typeof ResizeObserver === 'undefined') return
  anchorRO = new ResizeObserver(() => { measure(); measureCoach() })
  anchorRO.observe(el)
}

// Hybrid "Try it live" — fires a safe, read-only sandbox call through the tutorial proxy
// (which ALWAYS targets the sandbox, so it never touches prod). Logged-in dev required.
const liveLoading = ref(false)
const liveResult = ref<{ ok: boolean; status: number | string; text: string } | null>(null)
async function runLive() {
  const live = tour.currentStep?.live
  if (!live) return
  liveLoading.value = true; liveResult.value = null
  try {
    const { data } = await apiClient.post('/admin/tutorial/execute', {
      method: live.method, path: live.path, body: live.body ?? null,
      auth_type: live.authType || 'none', auth_token: null,
    })
    const sc = data?.status_code
    liveResult.value = { ok: sc >= 200 && sc < 300, status: sc ?? '—', text: JSON.stringify(data?.response ?? {}, null, 2).slice(0, 600) }
  } catch (e: any) {
    liveResult.value = { ok: false, status: e?.response?.status || 'ERR', text: String(e?.message || e).slice(0, 300) }
  } finally { liveLoading.value = false }
}

// Re-measure whenever the step (re)enters, on resize, and on scroll. Also clear any live result.
watch(() => tour.tick, () => { liveResult.value = null; nextTick(() => { measure(); measureCoach(); nextTick(measureCoach) }) })
// The "Try it live" panel changes the card height → re-measure so flip/clamp/arrow stay correct.
watch(liveResult, () => nextTick(measureCoach))
function onViewportChange() { measure(); measureCoach() }
onMounted(() => {
  window.addEventListener('resize', onViewportChange, { passive: true })
  window.addEventListener('scroll', onViewportChange, { passive: true, capture: true })
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
  window.removeEventListener('keydown', onKey)
  observeAnchor(null)
})
// §TOURWALK (2026-09-03): the wallet sheet the tour opens sits OVER the hidden coach — Escape on that
// sheet used to END the walkthrough that opened it, and arrow keys in its name field stepped the tour
// behind it. One pure, unit-tested rule (tourKeys.ts): no key reaches the tour while a door is open or
// the focus is in a field.
function onKey(e: KeyboardEvent) {
  const a = tourKeyAction(e.key, { active: tour.isActive, modalOpen: uiStore.showQuickAgentModal, editable: isEditableTarget(e.target) })
  if (a === 'end') tour.end()
  else if (a === 'next') void tour.next()
  else if (a === 'back') void tour.back()
}

const accent = computed(() => tour.tour?.accent || 'var(--accent, #00e5c7)')

// Spotlight cutout via a big box-shadow (dims everything outside the rect).
const spotStyle = computed(() => {
  if (!rect.value) return { display: 'none' }
  return {
    top: `${rect.value.top}px`, left: `${rect.value.left}px`,
    width: `${rect.value.width}px`, height: `${rect.value.height}px`,
    '--gt-ring': accent.value,
  } as Record<string, string>
})

// Coachmark layout: resolves placement near the anchor, FLIPS to stay on-screen using the
// live-measured card height, clamps to the viewport, and emits an arrow that points back at
// the anchor's centre along the facing edge. Centered card when anchorless.
const COACH_W = 360
const EDGE = 12          // viewport margin
const GAP = 14           // gap between anchor and card
type Place = 'top' | 'bottom' | 'left' | 'right' | 'center'
interface Arrow { edge: Place; x?: number; y?: number }
const layout = computed<{ style: Record<string, string>; place: Place; arrow: Arrow | null }>(() => {
  const step = tour.currentStep
  const r = rect.value
  const w = Math.min(COACH_W, window.innerWidth - EDGE * 2)
  const h = coachH.value
  if (!step || !r || step.placement === 'center') {
    return { style: { top: '50%', left: '50%', transform: 'translate(-50%,-50%)', width: `${w}px`, '--gt-ring': accent.value }, place: 'center', arrow: null }
  }
  const vw = window.innerWidth, vh = window.innerHeight
  let place: Place = (step.placement === 'auto' || !step.placement)
    ? (r.top > vh / 2 ? 'top' : 'bottom')
    : step.placement
  // Flip to the opposite side when there's no room but the other side fits.
  const fitsBelow = r.top + r.height + GAP + h <= vh - EDGE
  const fitsAbove = r.top - GAP - h >= EDGE
  const fitsRight = r.left + r.width + GAP + w <= vw - EDGE
  const fitsLeft = r.left - GAP - w >= EDGE
  if (place === 'bottom' && !fitsBelow && fitsAbove) place = 'top'
  else if (place === 'top' && !fitsAbove && fitsBelow) place = 'bottom'
  else if (place === 'right' && !fitsRight && fitsLeft) place = 'left'
  else if (place === 'left' && !fitsLeft && fitsRight) place = 'right'
  let top = 0, left = 0
  if (place === 'bottom') { top = r.top + r.height + GAP; left = r.left + r.width / 2 - w / 2 }
  else if (place === 'top') { top = r.top - GAP - h; left = r.left + r.width / 2 - w / 2 }
  else if (place === 'right') { top = r.top + r.height / 2 - h / 2; left = r.left + r.width + GAP }
  else { top = r.top + r.height / 2 - h / 2; left = r.left - GAP - w }
  left = Math.max(EDGE, Math.min(left, vw - w - EDGE))
  top = Math.max(EDGE, Math.min(top, vh - h - EDGE))
  // Arrow points at the anchor centre, clamped within the card edge (hidden if it would miss).
  const acx = r.left + r.width / 2, acy = r.top + r.height / 2
  let arrow: Arrow | null = null
  if (place === 'top' || place === 'bottom') {
    if (acx > left - 24 && acx < left + w + 24) arrow = { edge: place, x: Math.max(20, Math.min(acx - left, w - 20)) }
  } else {
    if (acy > top - 24 && acy < top + h + 24) arrow = { edge: place, y: Math.max(20, Math.min(acy - top, h - 20)) }
  }
  return { style: { top: `${top}px`, left: `${left}px`, width: `${w}px`, '--gt-ring': accent.value }, place, arrow }
})
const coachStyle = computed(() => layout.value.style)
// Centered card style (needs-agent gate) — responsive width + accent ring, shared with the main card.
const centerStyle = computed(() => ({
  top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
  width: `${Math.min(COACH_W, window.innerWidth - EDGE * 2)}px`, '--gt-ring': accent.value,
}))
const arrowStyle = computed(() => {
  const a = layout.value.arrow
  if (!a) return {}
  return a.x != null ? { left: `${a.x}px` } : { top: `${a.y}px` }
})

// Minimal, safe markdown: escape, then **bold**, `code`, [text](url), paragraph breaks.
function md(s: string): string {
  const esc = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return esc
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .split(/\n\n+/).map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('')
}

function onCta() {
  const c = tour.currentStep?.cta
  if (!c) return
  if (c.do === 'click-anchor') tour.clickAnchorThenNext()
  else if (c.do === 'open-runner' && c.runnerTrackId) { tour.end(); window.location.hash = `#/tutorials/${c.runnerTrackId}` }
  else if (c.do === 'create-wallet') { if ((auth as any).activeAgent && (auth as any).agentToken) tour.next(); else uiStore.openQuickAgentModal() }
  else tour.next()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="tour.isActive && !uiStore.showQuickAgentModal" class="gt-root" role="dialog" aria-modal="true" aria-label="Guided tour">
      <!-- Full dim when centered/no-anchor; otherwise the spot's box-shadow dims. -->
      <div v-if="!rect" class="gt-fulldim" />
      <!-- Spotlight cutout + pulsing ring -->
      <div v-else class="gt-spot" :style="spotStyle" />

      <!-- Preparing (routing / waiting for element) -->
      <div v-if="tour.isPreparing" class="gt-coach gt-coach--prep" :style="coachStyle">
        <div class="gt-spin"><Icon name="mdi:loading" /></div>
        <span>Opening the next stop…</span>
      </div>

      <!-- Needs-agent gate -->
      <div v-else-if="tour.needsAgent" class="gt-coach" :style="centerStyle">
        <div class="gt-head"><span class="gt-kicker" :style="{ color: accent }"><Icon name="mdi:account-alert" /> {{ t('tour.needsAgent.kicker', 'ACT AS AN AGENT') }}</span></div>
        <h3 class="gt-title">{{ t('tour.needsAgent.title', 'This is done as one of your agents') }}</h3>
        <div class="gt-body" data-testid="gt-needs-agent" :data-has-agents="hasNoAgents ? '0' : '1'"><p v-for="(l, i) in walletLines" :key="i">{{ l }}</p></div>
        <div class="gt-actions">
          <button class="gt-skip" @click="tour.end()" aria-label="End tour">{{ t('tour.exit', 'Exit tour') }}</button>
          <div class="gt-actions-main">
            <button class="gt-btn gt-btn--ghost" @click="tour.back()">{{ t('tour.back', 'Back') }}</button>
            <template v-if="hasNoAgents">
              <button class="gt-btn gt-btn--primary" :style="{ background: accent }" data-testid="gt-create-wallet" @click="createWalletFromTour">{{ t('tour.needsAgent.create', 'Create my wallet agent') }}</button>
            </template>
            <template v-else>
              <button class="gt-btn gt-btn--ghost" data-testid="gt-pick-agent" @click="pickAgent">{{ t('tour.needsAgent.pick', 'Pick one') }}</button>
              <button class="gt-btn gt-btn--primary" :style="{ background: accent }" @click="tour.retryStep()">{{ t('tour.needsAgent.picked', 'I picked one →') }}</button>
            </template>
          </div>
        </div>
      </div>

      <!-- Main coachmark -->
      <div v-else-if="tour.currentStep" ref="coachEl" class="gt-coach" :class="`gt-coach--${layout.place}`" :style="coachStyle">
        <div v-if="layout.arrow" class="gt-arrow" :class="`gt-arrow--${layout.arrow.edge}`" :style="arrowStyle" />
        <div class="gt-head">
          <span class="gt-kicker" :style="{ color: accent }">
            <Icon :name="tour.tour?.icon || 'mdi:school'" /> {{ withUnit(tour.tour?.title, localCurrency) }}
          </span>
          <span class="gt-count" :aria-label="`Step ${tour.stepIndex + 1} of ${tour.totalSteps}`">{{ tour.stepIndex + 1 }} / {{ tour.totalSteps }}</span>
        </div>
        <h3 class="gt-title">{{ withUnit(tour.currentStep.title, localCurrency) }}</h3>
        <div class="gt-body" aria-live="polite" v-html="md(withUnit(tour.currentStep.body, localCurrency))" />
        <div v-if="tour.anchorMissing" class="gt-note">This element isn't on screen right now — the explanation still applies.</div>
        <div v-if="tour.currentStep.live" class="gt-live">
          <button class="gt-live-btn" :style="{ borderColor: accent, color: accent }" :disabled="liveLoading" @click="runLive">
            {{ liveLoading ? 'Running…' : (tour.currentStep.live.label || 'Try it live ▸') }}
          </button>
          <div v-if="liveResult" class="gt-live-res" :class="{ bad: !liveResult.ok }">
            <div class="gt-live-status">{{ liveResult.ok ? '✓' : '✗' }} {{ liveResult.status }} <i>· live from the sandbox</i></div>
            <pre class="gt-live-pre">{{ liveResult.text }}</pre>
          </div>
        </div>
        <div class="gt-progress" role="progressbar" :aria-valuenow="tour.progressPct" aria-valuemin="0" aria-valuemax="100" :aria-label="`Tour progress: ${tour.progressPct}%`"><div class="gt-progress-fill" :style="{ width: tour.progressPct + '%', background: accent }" /></div>
        <div class="gt-actions">
          <button class="gt-skip" @click="tour.end()" aria-label="End tour">Skip tour</button>
          <div class="gt-actions-main">
            <button v-if="!tour.isFirst" class="gt-btn gt-btn--ghost" @click="tour.back()">Back</button>
            <button v-if="tour.currentStep.cta" class="gt-btn gt-btn--cta" :style="{ borderColor: accent, color: accent }" @click="onCta">{{ tour.currentStep.cta.label }}</button>
            <button class="gt-btn gt-btn--primary" :style="{ background: accent }" @click="tour.next()">{{ tour.isLast ? 'Finish ✓' : 'Next →' }}</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Contextual launcher pill (off-tour, on tour-relevant routes) -->
  <Teleport to="body">
    <div v-if="!tour.isActive && suggested" class="gt-pill" :style="{ '--tc': suggested.accent }">
      <button class="gt-pill-go" @click="tour.start(suggested.id)"><Icon :name="suggested.icon" /> Take the {{ withUnit(suggested.title, localCurrency) }} tour</button>
      <button class="gt-pill-x" @click="dismissSuggested" aria-label="Dismiss">✕</button>
    </div>
  </Teleport>
</template>

<style scoped>
.gt-root { position: fixed; inset: 0; z-index: 99990; pointer-events: none; font-family: inherit; }
.gt-fulldim { position: fixed; inset: 0; background: rgba(6,10,14,0.72); pointer-events: auto; backdrop-filter: blur(1.5px); }
/* Static dim cutout — the heavy 9999px shadow no longer animates (that was the pulse jank). */
.gt-spot {
  position: fixed; border-radius: 12px; pointer-events: none;
  box-shadow: 0 0 0 9999px rgba(6,10,14,0.72);
  transition: top .26s cubic-bezier(.4,0,.2,1), left .26s cubic-bezier(.4,0,.2,1), width .26s cubic-bezier(.4,0,.2,1), height .26s cubic-bezier(.4,0,.2,1);
}
/* Only this lightweight ring pulses → smooth, GPU-friendly, no full-screen repaint. */
.gt-spot::after {
  content: ''; position: absolute; inset: -1px; border-radius: inherit; pointer-events: none;
  box-shadow: 0 0 0 1.5px var(--gt-ring), 0 0 16px 1px var(--gt-ring);
  animation: gt-pulse 2.4s ease-in-out infinite; will-change: box-shadow, opacity;
}
@keyframes gt-pulse {
  0%,100% { box-shadow: 0 0 0 1.5px var(--gt-ring), 0 0 10px 0 var(--gt-ring); opacity: .92; }
  50%     { box-shadow: 0 0 0 2px var(--gt-ring), 0 0 26px 5px var(--gt-ring); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .gt-spot { transition: none; }
  .gt-spot::after { animation: none; box-shadow: 0 0 0 2px var(--gt-ring), 0 0 16px 2px var(--gt-ring); }
  .gt-coach { transition: none; }
}
.gt-coach {
  position: fixed; pointer-events: auto; background: linear-gradient(180deg, #0e1620, #0a1118);
  border: 1px solid rgba(255,255,255,0.10); border-radius: 14px; padding: 18px 18px 16px;
  box-shadow: 0 18px 50px rgba(0,0,0,0.6); color: #e8eef3; transition: top .28s, left .28s; max-width: 92vw;
}
.gt-coach--prep { display: flex; align-items: center; gap: 10px; color: #9fb3c2; font-size: 14px; }
/* Directional pointer — a rotated square sharing the card's edge + border, so it reads as a caret aimed at the spotlight. */
.gt-arrow { position: absolute; width: 13px; height: 13px; transform: rotate(45deg); pointer-events: none; }
.gt-arrow--bottom { top: -7px; margin-left: -6.5px; background: #0e1620; border-top: 1px solid rgba(255,255,255,0.10); border-left: 1px solid rgba(255,255,255,0.10); }
.gt-arrow--top    { bottom: -7px; margin-left: -6.5px; background: #0a1118; border-bottom: 1px solid rgba(255,255,255,0.10); border-right: 1px solid rgba(255,255,255,0.10); }
.gt-arrow--right  { left: -7px; margin-top: -6.5px; background: #0c131c; border-bottom: 1px solid rgba(255,255,255,0.10); border-left: 1px solid rgba(255,255,255,0.10); }
.gt-arrow--left   { right: -7px; margin-top: -6.5px; background: #0c131c; border-top: 1px solid rgba(255,255,255,0.10); border-right: 1px solid rgba(255,255,255,0.10); }
.gt-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.gt-kicker { font-size: 11px; font-weight: 700; letter-spacing: .08em; display: inline-flex; align-items: center; gap: 6px; }
.gt-kicker :deep(svg) { width: 14px; height: 14px; }
.gt-count { font-size: 11.5px; color: #93a7b6; font-variant-numeric: tabular-nums; letter-spacing: .02em; }
.gt-title { font-size: 17.5px; font-weight: 660; margin: 0 0 7px; line-height: 1.28; letter-spacing: -.01em; color: #f3f8fb; }
.gt-body { font-size: 14px; line-height: 1.55; color: #c7d4de; }
.gt-body :deep(p) { margin: 0 0 8px; }
.gt-body :deep(p:last-child) { margin-bottom: 0; }
.gt-body :deep(code) { background: rgba(255,255,255,0.08); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.gt-body :deep(strong) { color: #eef5fa; }
.gt-body :deep(a) { color: var(--accent, #00e5c7); }
.gt-note { margin-top: 8px; font-size: 12px; color: #c79a4a; }
.gt-live { margin-top: 12px; }
.gt-live-btn { background: transparent; border: 1px solid; border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; cursor: pointer; transition: filter .15s, box-shadow .15s; }
.gt-live-btn:hover:not(:disabled) { filter: brightness(1.15); }
.gt-live-btn:disabled { opacity: .6; cursor: default; }
.gt-live-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px #0a1118, 0 0 0 4px var(--gt-ring, #00e5c7); }
.gt-live-res { margin-top: 8px; border-radius: 8px; border: 1px solid rgba(52,211,153,0.35); background: rgba(52,211,153,0.07); padding: 8px; }
.gt-live-res.bad { border-color: rgba(255,107,107,0.4); background: rgba(255,107,107,0.07); }
.gt-live-status { font-size: 11px; font-weight: 700; color: #34d399; margin-bottom: 4px; }
.gt-live-res.bad .gt-live-status { color: #ff8a8a; }
.gt-live-status i { font-weight: 400; color: #7d93a3; font-style: normal; }
.gt-live-pre { margin: 0; font-size: 10.5px; line-height: 1.35; color: #c4d2dd; max-height: 140px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
.gt-pill { position: fixed; bottom: 18px; right: 18px; z-index: 99980; display: flex; align-items: stretch; background: linear-gradient(180deg,#0e1620,#0a1118); border: 1px solid var(--tc, #00e5c7); border-radius: 999px; box-shadow: 0 8px 28px rgba(0,0,0,.5), 0 0 16px -4px var(--tc,#00e5c7); overflow: hidden; pointer-events: auto; }
.gt-pill-go { display: inline-flex; align-items: center; gap: 7px; background: transparent; border: none; color: #e8eef3; font-size: 13px; font-weight: 600; padding: 9px 14px; cursor: pointer; }
.gt-pill-go :deep(svg) { width: 15px; height: 15px; color: var(--tc, #00e5c7); }
.gt-pill-go:hover { background: rgba(255,255,255,0.05); }
.gt-pill-go:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--tc, #00e5c7); }
.gt-pill-x { background: transparent; border: none; border-left: 1px solid rgba(255,255,255,0.12); color: #5f7283; font-size: 12px; padding: 0 11px; cursor: pointer; }
.gt-pill-x:hover { color: #e8eef3; }
.gt-pill-x:focus-visible { outline: none; color: #e8eef3; box-shadow: inset 0 0 0 2px var(--tc, #00e5c7); }
.gt-progress { height: 3px; background: rgba(255,255,255,0.08); border-radius: 3px; margin: 14px 0 12px; overflow: hidden; }
.gt-progress-fill { height: 100%; border-radius: 3px; transition: width .35s ease; }
.gt-actions { display: flex; gap: 10px 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
.gt-actions-main { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: wrap; margin-left: auto; }
.gt-btn { border: none; border-radius: 8px; padding: 8px 15px; font-size: 13px; font-weight: 600; line-height: 1.1; color: #08121a; cursor: pointer; transition: filter .15s, transform .1s, box-shadow .15s; white-space: nowrap; }
.gt-btn:hover { filter: brightness(1.08); }
.gt-btn:active { transform: translateY(1px); }
.gt-btn:focus-visible { outline: none; box-shadow: 0 0 0 2px #0a1118, 0 0 0 4px var(--gt-ring, #00e5c7); }
.gt-btn--primary { min-width: 84px; }
.gt-btn--ghost { background: transparent; color: #9fb3c2; border: 1px solid rgba(255,255,255,0.14); }
.gt-btn--ghost:hover { color: #e8eef3; border-color: rgba(255,255,255,0.28); }
.gt-btn--cta { background: transparent; border: 1px solid; font-weight: 600; }
.gt-skip { background: none; border: none; color: #6b7f8f; font-size: 12px; font-weight: 500; cursor: pointer; padding: 7px 4px; border-radius: 6px; white-space: nowrap; transition: color .15s; }
.gt-skip:hover { color: #cdd9e3; text-decoration: underline; }
.gt-skip:focus-visible { outline: none; color: #e8eef3; box-shadow: 0 0 0 2px #0a1118, 0 0 0 4px var(--gt-ring, #00e5c7); }
.gt-spin :deep(svg) { width: 18px; height: 18px; animation: gt-rot 1s linear infinite; }
@keyframes gt-rot { to { transform: rotate(360deg); } }

/* Phone polish (≤430px): tighter card + tap-friendly buttons; the actions row already
   wraps the Skip link above the grouped Back/CTA/Next when all four can't share a line. */
@media (max-width: 430px) {
  .gt-coach { padding: 15px 14px 13px; border-radius: 13px; }
  .gt-title { font-size: 16.5px; }
  .gt-body { font-size: 13.5px; }
  .gt-actions { gap: 8px 10px; }
  .gt-actions-main { gap: 7px; }
  .gt-btn { padding: 9px 13px; font-size: 12.5px; }
  .gt-skip { padding: 8px 4px; }
  .gt-pill { bottom: 12px; right: 12px; max-width: calc(100vw - 24px); }
  .gt-pill-go { font-size: 12px; padding: 9px 12px; }
}
</style>
