<!--
  §BONDFILL (2026-09-11) — HOW FAR A REPUTATION BOND IS FROM MATURITY, as a thing that fills up.
  §BONDFILL-3 (same night, his word) — AND WHAT HAPPENS WHEN IT GETS THERE, as a thing that burns.

  THE BOND IS THE COLLATERAL a counterparty is asked to rely on. `250 ECU` says a provider has
  something to lose; maturity says how long it has had it at stake and what it still has to do.

  THREE INDEPENDENT GATES, THREE SEGMENTS. One `percent` over three unrelated conditions cannot say
  what is holding the bond back: an agent at 28 % because it is three days old looks identical to
  one at 28 % because nobody independent will vouch for it, and those are opposite facts about
  whether to hire it. Each gate fills on its own and the furthest behind is named in words.

  THE FIRE IS A COSTLY SIGNAL, WHICH IS THE ONLY KIND WORTH DRAWING. At maturity the owner may
  unlock a declared share of the bond and keep trading on the rest. An agent that has had that
  right and kept the WHOLE bond at stake burns; one that took the share back glows as embers; one
  that released everything is ash. The fire is credible precisely because it costs something to
  keep — anything free to display would be decoration. Which state to draw is decided once, in the
  backend (`reputation_bond.fire_state`), so this card, a mirror and a backend reader agree.

  ABSENT IS NOT ZERO. No bond renders nothing. A bonded agent whose origin published no snapshot
  renders a SENTENCE naming that origin, never an empty bar. And the trust gate has its own third
  state: `waived` (too few agents ranked, a measured fact, said so) is not `unknown` (never
  measured), and only the first can pass.

  PERFORMANCE: every animation is `transform` or `opacity` on small pseudo-free elements, so it
  runs on the compositor; nothing animates a filter, a shadow or a background position. A page can
  hold dozens of these. `prefers-reduced-motion` stops all of it and keeps the static glow.
-->
<template>
  <div
    v-if="visible"
    class="bmf"
    :class="[stateClass, { 'bmf--detailed': detailed }]"
    data-testid="disc-bond-maturity"
    :data-bond-maturity="dataState"
    :data-bond-fire="fire || 'none'"
    :data-bond-maturity-source="p ? p.source || 'registry' : 'none'"
    :title="fullTitle"
  >
    <!-- Bonded, but this frame was told nothing about maturity (and it has not matured). -->
    <template v-if="!fire && !p">
      <div class="bmf-head">
        <span class="bmf-label">{{ t('discoveryView.bond.maturityUnknown', 'Maturity not published') }}</span>
      </div>
      <p class="bmf-note">{{ unpublishedNote }}</p>
    </template>

    <!-- Matured or released: one fused bar that burns, glows, or has gone to ash. -->
    <template v-else-if="fire">
      <div class="bmf-head">
        <span class="bmf-label">{{ fireLabel }}</span>
        <span class="bmf-pct" data-testid="disc-bond-maturity-pct">{{ fireRight }}</span>
      </div>
      <div class="bmf-fire" role="img" :aria-label="fullTitle">
        <span class="bmf-core"></span>
        <template v-if="fire === 'burning'">
          <i v-for="f in flames" :key="'f' + f.i" class="bmf-flame"
             :style="{ left: f.left, animationDuration: f.dur, animationDelay: f.delay, '--bmf-h': f.h }"></i>
        </template>
        <template v-else-if="fire === 'embers'">
          <i v-for="f in sparks" :key="'s' + f.i" class="bmf-spark"
             :style="{ left: f.left, animationDuration: f.dur, animationDelay: f.delay }"></i>
        </template>
      </div>
      <p class="bmf-note" data-testid="disc-bond-maturity-note">{{ fireNote }}</p>
    </template>

    <!-- Maturing: three segments, each filling on its own. -->
    <template v-else-if="p">
      <div class="bmf-head">
        <span class="bmf-label">{{ t('discoveryView.bond.maturingLabel', 'Bond maturing') }}</span>
        <span class="bmf-pct" data-testid="disc-bond-maturity-pct">{{ p.percent }}%</span>
      </div>
      <div class="bmf-track" role="img" :aria-label="fullTitle">
        <span
          v-for="g in gates"
          :key="g.key"
          class="bmf-seg"
          :class="{ 'bmf-seg--met': g.met }"
          :data-gate="g.key"
          :data-gate-met="g.met ? '1' : '0'"
          :title="g.title"
        ><i class="bmf-fill" :style="{ width: g.pct + '%' }"></i></span>
      </div>
      <p class="bmf-note" data-testid="disc-bond-maturity-note">{{ note }}</p>
    </template>

    <!-- The owner's page: every gate named, with its numbers. -->
    <ul v-if="detailed && p" class="bmf-gates" data-testid="disc-bond-maturity-gates">
      <li v-for="g in gates" :key="'d' + g.key" :class="{ 'bmf-gate--met': g.met }" :data-gate="g.key">
        <span class="bmf-gate-mark">{{ g.met ? '✓' : '·' }}</span>
        <span class="bmf-gate-text">{{ g.title }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { fmt, toNum } from '@/services/cockpit/num'
import type { BondInfo } from '@/services/api/reputationBond'

const props = defineProps<{
  bond?: BondInfo | null
  /** The registry that signs this agent's card — named when the claim is not ours. */
  origin?: string | null
  /** The owner's page: list every gate with its numbers under the bar. */
  detailed?: boolean
}>()

const { t, tp, formatDate } = useI18n()

const bond = computed(() => props.bond || null)
const p = computed(() => bond.value?.progress || null)
/** Decided by the backend. A matured/released status with no `fire` (an older origin) still
 *  draws, from the status alone, rather than falling back to an empty bar. */
const fire = computed<string | null>(() => {
  const b = bond.value
  if (!b) return null
  if (b.fire) return b.fire
  if (b.status === 'matured') return b.partial_released_at ? 'embers' : 'burning'
  if (b.status === 'released') return 'extinguished'
  return null
})
const visible = computed(() => !!bond.value && (bond.value.is_bonded || fire.value === 'extinguished'))
const stateClass = computed(() => {
  if (fire.value) return 'bmf--' + fire.value
  return p.value ? 'bmf--maturing' : 'bmf--unpublished'
})
const dataState = computed(() => fire.value || (p.value ? String(p.value.percent) : 'unpublished'))

/** A name that is only the category noun is no answer: until V0344 every frame published the
 *  literal "registry" there, and a peer on an older build still does. The origin THIS frame
 *  resolved comes first; our own registry's name would be a false attribution, so it never does. */
const GENERIC_NAMES = new Set(['registry', 'unknown', 'local', 'agentvault registry', ''])
function named(v?: string | null): string | null {
  const s = (v || '').trim()
  return s && !GENERIC_NAMES.has(s.toLowerCase()) ? s : null
}
const originName = computed(() =>
  named(props.origin) || named(bond.value?.registry)
  || t('discoveryView.bond.homeRegistry', 'its home registry'))
const ccy = computed(() => bond.value?.currency || '')

const unpublishedNote = computed(() =>
  tp('discoveryView.bond.maturityUnknownNote',
    '{registry} states the bond but not its progress toward maturity.',
    { registry: originName.value }))

// ── the three gates ────────────────────────────────────────────────────────────────────────────
type Gate = { key: string; met: boolean; pct: number; title: string }

/** `required <= 0` means the registry does not gate on it at all: satisfied, not a division by zero. */
function frac(have: number, need: number): number {
  if (!(need > 0)) return 1
  return Math.max(0, Math.min(1, have / need))
}

const trustTitle = computed(() => {
  const q = p.value
  if (!q) return ''
  if (q.trust_percentile_state === 'unknown') {
    return t('discoveryView.bond.gateTrustUnknown', 'Trust: not published in the current form')
  }
  const raters = { have: fmt(toNum(q.rated_peers) ?? 0, 0), need: fmt(toNum(q.rated_peers_required) ?? 0, 0) }
  if (q.trust_percentile_state === 'waived') {
    return tp('discoveryView.bond.gateTrustWaived',
      'Trust: rated by {have} of {need} independent peers · standing waived until {pop} agents are ranked',
      { ...raters, pop: fmt(toNum(q.trust_population_required) ?? 0, 0) })
  }
  return tp('discoveryView.bond.gateTrust',
    'Trust: rated by {have} of {need} independent peers · above {pct}% of ranked agents (needs {req}%)',
    { ...raters, pct: fmt(toNum(q.trust_percentile) ?? 0, 0), req: fmt(toNum(q.trust_percentile_required) ?? 0, 0) })
})

const gates = computed<Gate[]>(() => {
  const q = p.value
  if (!q) return []
  const tx = toNum(q.transactions) ?? 0, txReq = toNum(q.transactions_required) ?? 0
  const age = toNum(q.age_days) ?? 0, ageReq = toNum(q.age_days_required) ?? 0
  // The trust segment is only as full as its weaker half, exactly as the backend computes it.
  const peers = frac(toNum(q.rated_peers) ?? 0, toNum(q.rated_peers_required) ?? 0)
  const standing = q.trust_percentile_state === 'measured'
    ? frac(toNum(q.trust_percentile) ?? 0, toNum(q.trust_percentile_required) ?? 0)
    : (q.trust_percentile_state === 'waived' ? 1 : 0)
  return [
    { key: 'transactions', met: !!q.met?.transactions, pct: Math.round(frac(tx, txReq) * 100),
      title: tp('discoveryView.bond.gateTransactions', 'Settlements: {have} of {need}',
        { have: fmt(tx, 0), need: fmt(txReq, 0) }) },
    { key: 'age', met: !!q.met?.age, pct: Math.round(frac(age, ageReq) * 100),
      title: tp('discoveryView.bond.gateAge', 'Days bonded: {have} of {need}',
        { have: fmt(age, 0), need: fmt(ageReq, 0) }) },
    { key: 'trust', met: !!q.met?.trust, pct: q.met?.trust ? 100 : Math.round(Math.min(peers, standing) * 100),
      title: trustTitle.value },
  ]
})

const firstUnmet = computed(() => gates.value.find(g => !g.met)?.key || '')

/** The sentence under a maturing bar names the long pole in its own units. */
const note = computed(() => {
  const q = p.value
  if (!q) return ''
  const blocking = q.blocking && q.blocking.length ? q.blocking[0] : firstUnmet.value
  if (blocking === 'age') {
    const left = Math.max(0, (toNum(q.age_days_required) ?? 0) - (toNum(q.age_days) ?? 0))
    return tp('discoveryView.bond.leftAge', '{n} more days bonded', { n: fmt(left, 0) })
  }
  if (blocking === 'transactions') {
    const left = Math.max(0, (toNum(q.transactions_required) ?? 0) - (toNum(q.transactions) ?? 0))
    return tp('discoveryView.bond.leftTransactions', '{n} more settlements', { n: fmt(left, 0) })
  }
  if (blocking === 'trust') {
    if (q.trust_percentile_state === 'unknown') return t('discoveryView.bond.leftTrustUnknown', 'trust not measured yet')
    const lacking = Math.max(0, (toNum(q.rated_peers_required) ?? 0) - (toNum(q.rated_peers) ?? 0))
    if (lacking > 0) return tp('discoveryView.bond.leftRaters', '{n} more independent raters', { n: fmt(lacking, 0) })
    return tp('discoveryView.bond.leftStanding', 'trust below the {req}% of ranked agents it needs',
      { req: fmt(toNum(q.trust_percentile_required) ?? 0, 0) })
  }
  return ''
})

// ── the fire ───────────────────────────────────────────────────────────────────────────────────
/** Days since a stamp, computed HERE from the stamp: a count that moves with the clock is never
 *  stored on a card (the same rule that keeps `age_days` off the exported snapshot). */
function daysSince(iso?: string | null): number | null {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 86_400_000)) : null
}

const fireLabel = computed(() => {
  if (fire.value === 'burning') return t('discoveryView.bond.burningLabel', 'Bond matured · burning')
  if (fire.value === 'embers') return t('discoveryView.bond.embersLabel', 'Bond matured · capital unlocked')
  return t('discoveryView.bond.releasedLabel', 'Bond released')
})

const fireRight = computed(() => {
  const b = bond.value
  if (!b) return ''
  if (fire.value === 'burning') {
    const d = daysSince(b.matured_at)
    return d == null ? '' : tp('discoveryView.bond.keptDays', 'kept {n}d', { n: fmt(d, 0) })
  }
  if (fire.value === 'embers') {
    return tp('discoveryView.bond.atStake', '{amt} {ccy} held as a bond', { amt: b.amount || '', ccy: ccy.value })
  }
  return b.released_at ? formatDate(b.released_at, 'short') : ''
})

const fireNote = computed(() => {
  const b = bond.value
  if (!b) return ''
  if (fire.value === 'burning') {
    // The unlock block is the home frame's; a mirror does not carry it, and says the general thing.
    if (b.unlock && b.unlock.amount && b.unlock.percent > 0) {
      return tp('discoveryView.bond.burningNote',
        'Could take {amt} {ccy} back and has kept it all in the bond.',
        { amt: b.unlock.amount, ccy: ccy.value })
    }
    return t('discoveryView.bond.burningNoteMirror', 'All three conditions met, and the whole bond is still held.')
  }
  if (fire.value === 'embers') {
    return tp('discoveryView.bond.embersNote',
      '{unlocked} {ccy} unlocked at maturity; {held} {ccy} still held in the bond.',
      { unlocked: b.partial_released_amount || '', held: b.amount || '', ccy: ccy.value })
  }
  return t('discoveryView.bond.releasedNote', 'The bond was returned. This agent no longer holds a bond.')
})

/** Flames and sparks with DETERMINISTIC placement and timing: random values would re-roll on every
 *  render and make the fire jump whenever anything else on the card changed. */
const flames = computed(() => Array.from({ length: 7 }, (_, i) => ({
  i,
  left: `${8 + i * 14}%`,
  dur: `${760 + ((i * 137) % 5) * 90}ms`,
  delay: `${-((i * 211) % 7) * 110}ms`,
  h: String(0.75 + ((i * 53) % 5) * 0.1),
})))
const sparks = computed(() => Array.from({ length: 4 }, (_, i) => ({
  i,
  left: `${15 + i * 22}%`,
  dur: `${2400 + ((i * 97) % 4) * 350}ms`,
  delay: `${-((i * 173) % 5) * 520}ms`,
})))

const fullTitle = computed(() => {
  if (fire.value) return fireNote.value
  if (!p.value) return unpublishedNote.value
  const parts = gates.value.map(g => g.title)
  // A claim this frame did not compute is labelled as the origin's, with when it was true.
  if (p.value.source === 'card') {
    parts.push(tp('discoveryView.bond.statedBy', 'Stated by {registry}{asOf}', {
      registry: originName.value,
      asOf: p.value.as_of ? ` (${formatDate(p.value.as_of, 'short')})` : '',
    }))
  }
  return parts.join(' · ')
})
</script>

<style scoped>
.bmf { margin-bottom: 0.5rem; contain: layout paint; }
.bmf-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem;
  font-size: 0.68rem; line-height: 1.2; margin-bottom: 0.25rem; }
.bmf-label { color: #cbd5e1; font-weight: 600; letter-spacing: 0.02em; }
.bmf-pct { color: #94a3b8; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.bmf-note { font-size: 0.65rem; line-height: 1.3; margin: 0.25rem 0 0; color: #94a3b8; }

/* ── maturing: three segments ────────────────────────────────────────────────────────────── */
.bmf-track { display: flex; gap: 3px; }
.bmf-seg { flex: 1 1 0; min-width: 0; height: 5px; border-radius: 3px;
  background: rgba(148, 163, 184, 0.18); overflow: hidden; }
.bmf-fill { display: block; height: 100%; border-radius: 3px; background: rgb(251, 191, 36);
  transition: width 0.4s ease; }
.bmf-seg--met .bmf-fill { background: rgb(52, 211, 153); }

.bmf--unpublished .bmf-label { color: #94a3b8; font-weight: 500; font-style: italic; }

/* ── matured / released: one fused bar ───────────────────────────────────────────────────── */
/* Room above the bar for the flames, so they never overlap the label line. */
.bmf-fire { position: relative; height: 6px; margin-top: 14px; }
.bmf-core { position: absolute; inset: 0; border-radius: 3px; overflow: hidden; }

/* BURNING — a hot gradient, a static glow (painted once), a heat shimmer that only translates. */
.bmf--burning .bmf-label { color: #fdba74; }
.bmf--burning .bmf-pct { color: #fb923c; }
.bmf--burning .bmf-core {
  background: linear-gradient(90deg, #7f1d1d 0%, #dc2626 22%, #f97316 52%, #facc15 82%, #fef08a 100%);
  box-shadow: 0 0 8px rgba(249, 115, 22, 0.55), 0 0 18px rgba(220, 38, 38, 0.3);
}
.bmf--burning .bmf-core::after {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent 0%, rgba(255, 247, 237, 0.45) 50%, transparent 100%);
  transform: translateX(-100%);
  animation: bmf-sweep 2.6s linear infinite;
}
.bmf-flame {
  position: absolute; bottom: 3px; width: 9px; height: 15px; margin-left: -4.5px;
  border-radius: 50% 50% 38% 38% / 62% 62% 38% 38%;
  background: radial-gradient(ellipse at 50% 85%, #fffbeb 0%, #fde047 22%, #fb923c 52%, rgba(220, 38, 38, 0) 78%);
  transform-origin: 50% 100%;
  transform: scaleY(var(--bmf-h, 1));
  animation-name: bmf-flicker; animation-timing-function: ease-in-out;
  animation-iteration-count: infinite; animation-direction: alternate;
  opacity: 0.9; pointer-events: none;
}
@keyframes bmf-flicker {
  0%   { transform: translateY(0)     scale(1, var(--bmf-h, 1));                 opacity: 0.8; }
  45%  { transform: translateY(-2px)  scale(0.82, calc(var(--bmf-h, 1) * 1.3)); opacity: 1; }
  100% { transform: translateY(-1px)  scale(1.12, calc(var(--bmf-h, 1) * 0.86)); opacity: 0.65; }
}
@keyframes bmf-sweep { to { transform: translateX(100%); } }

/* EMBERS — cooler, dimmer, no flame: a few sparks drift up and fade. Still bonded, less at stake. */
.bmf--embers .bmf-label { color: #fdba74; opacity: 0.85; }
.bmf--embers .bmf-pct { color: #c2410c; }
.bmf--embers .bmf-core {
  background: linear-gradient(90deg, #431407 0%, #7c2d12 35%, #9a3412 65%, #c2410c 100%);
  box-shadow: 0 0 6px rgba(234, 88, 12, 0.3);
}
.bmf--embers .bmf-core::after {
  content: ''; position: absolute; inset: 0; background: rgba(251, 146, 60, 0.35);
  opacity: 0; animation: bmf-glow 3.2s ease-in-out infinite;
}
.bmf-spark {
  position: absolute; bottom: 4px; width: 2px; height: 2px; margin-left: -1px; border-radius: 50%;
  background: #fdba74; opacity: 0; pointer-events: none;
  animation-name: bmf-rise; animation-timing-function: ease-out; animation-iteration-count: infinite;
}
@keyframes bmf-rise {
  0%   { transform: translate(0, 0);     opacity: 0; }
  15%  { opacity: 0.9; }
  100% { transform: translate(2px, -13px); opacity: 0; }
}
@keyframes bmf-glow { 50% { opacity: 1; } }

/* EXTINGUISHED — ash: grey, grained, perfectly still. The exit, and it looks like one. */
.bmf--extinguished .bmf-label { color: #a1a1aa; }
.bmf--extinguished .bmf-pct { color: #71717a; }
.bmf--extinguished .bmf-core {
  background: repeating-linear-gradient(90deg, #3f3f46 0 7px, #52525b 7px 9px);
  opacity: 0.75;
}
.bmf--extinguished .bmf-fire { margin-top: 4px; }

/* ── the owner's page: every gate by name ────────────────────────────────────────────────── */
.bmf-gates { list-style: none; margin: 0.4rem 0 0; padding: 0; display: grid; gap: 0.15rem; }
.bmf-gates li { display: flex; gap: 0.4rem; font-size: 0.7rem; color: #94a3b8; line-height: 1.35; }
.bmf-gate-mark { width: 0.8rem; flex: 0 0 0.8rem; text-align: center; color: #64748b; }
.bmf-gate--met .bmf-gate-mark { color: #34d399; }
.bmf-gate--met .bmf-gate-text { color: #cbd5e1; }
.bmf--detailed .bmf-head { font-size: 0.74rem; }

@media (prefers-reduced-motion: reduce) {
  .bmf-flame, .bmf-spark, .bmf-core::after { animation: none !important; }
  .bmf-spark { display: none; }
  .bmf-fill { transition: none; }
}
</style>
