<!--
  V0665 (order gwo_5e0701efdef9d3989491bc37; room seq 4063, 4070, 4081): the contributor track, #/code-changes/track, the Track tab beside the Code changes.
  The pass (forty tiers) in a row like a battle pass, each item drawn live by the art's own components, its condition in one sentence, the person's progress, locked or unlocked;
  the titles after them, side quests off the main row, and the items still waiting for a condition ("comes later", with the registry's reason). Only real governed-code
  events count: nothing is bought, nothing is granted by hand, no value moves. The registry's evaluator decides (services/contributor_track); this page words the record.
  The Commander plate is one of one: shown only to an account on the commander flare tier, and worn by default while no other title is chosen.
  What is not yet unlocked is BLACKED OUT (the Commander's feedback, room seq 4404): an outline, no art, no name, no sentence; only the NEXT title is shown in full.
  A signed-out visitor reads the track itself, every item dark, with no progress.
-->
<template>
  <div class="ct" data-testid="track-root">
    <CodeChangesTabs current="code-changes-track" />

    <header class="ct-hero">
      <span class="ct-eyebrow">{{ t('contributorTrack.view.eyebrow', 'Contributor track') }}</span>
      <h1>{{ t('contributorTrack.view.h1', 'Unlocked by building it') }}</h1>
      <p class="ct-lede">{{ t('contributorTrack.view.lede', 'Corner badges, rings and titles for the people who help build the platform. Only real governed-code work counts: a change proposed, reviewed, voted on or merged. Nothing is bought, nothing is granted by hand, and no value moves.') }}</p>
      <p v-if="signedIn && track" class="ct-total" data-testid="track-total">{{ tp('contributorTrack.view.total', '{done} of {total} unlocked', { done: total.done, total: total.total }) }}</p>
      <p v-else-if="!signedIn" class="ct-total" data-testid="track-signin">
        <RouterLink :to="{ name: 'login' }">{{ t('contributorTrack.view.signIn', 'Sign in') }}</RouterLink> {{ t('contributorTrack.view.signInTail', 'to see your own progress.') }}
      </p>
    </header>

    <div v-if="loading" class="ct-skel" data-testid="track-loading" aria-busy="true"><i></i><i></i><i></i></div>
    <div v-else-if="failed" class="ct-card ct-fail" role="alert" data-testid="track-error">
      <p>{{ t('contributorTrack.view.failed', 'The track could not be read just now.') }}</p>
      <button type="button" class="ct-btn" data-testid="track-retry" @click="load">{{ t('contributorTrack.view.retry', 'Try again') }}</button>
    </div>

    <template v-else>
      <section v-if="isCommander" class="ct-card ct-commander" data-testid="track-commander">
        <CommanderPlate size="card" :still="still" />
        <p>{{ t('contributorTrack.view.commander', 'One of one. It belongs to the commander flare tier and to no one else: nobody unlocks it and nobody is given it.') }}</p>
        <p v-if="commanderWorn" class="ct-note ct-worn" data-testid="track-commander-worn">{{ t('contributorTrack.view.commanderWorn', 'Worn under your name unless you choose another title.') }}</p>
      </section>

      <section class="ct-sec" data-testid="track-tiers">
        <h2>{{ t('contributorTrack.view.tiers', 'The pass') }}</h2>
        <div class="ct-pass-bar">
          <p class="ct-hint" aria-hidden="true">{{ tp('contributorTrack.view.scrollHint', '{n} tiers: scroll sideways for the next ones.', { n: g.tiers.length }) }}</p>
          <div class="ct-jumps">
            <button type="button" class="ct-arrow" data-testid="track-scroll-prev" :aria-label="t('contributorTrack.view.prevTiers', 'Earlier tiers')" @click="scrollRow(-1)"><Icon name="mdi:chevron-left" aria-hidden="true" /></button>
            <button v-if="signedIn && openTier !== null" type="button" class="ct-jump" data-testid="track-jump-next" @click="jumpTo(openTier)">{{ tp('contributorTrack.view.jumpNext', 'Jump to my next tier ({n})', { n: openTier }) }}</button>
            <button type="button" class="ct-arrow" data-testid="track-scroll-next" :aria-label="t('contributorTrack.view.nextTiers', 'Later tiers')" @click="scrollRow(1)"><Icon name="mdi:chevron-right" aria-hidden="true" /></button>
          </div>
        </div>
        <ol ref="rowEl" class="ct-row" tabindex="0" :aria-label="t('contributorTrack.view.rowLabel', 'The pass: scroll sideways with the arrow keys')">
          <li v-for="tier in g.tiers" :key="tier.tier" class="ct-tier" :class="{ 'ct-tier--pair': tier.items.length > 1 }" :data-state="tier.done ? 'done' : tier.partial ? 'partial' : 'open'" :data-testid="`track-tier-${tier.tier}`">
            <span class="ct-node" aria-hidden="true">{{ tier.tier }}</span>
            <span class="ct-tier-k">{{ tp('contributorTrack.view.tierN', 'Tier {n}', { n: tier.tier }) }}</span>
            <TrackItemCard v-for="i in tier.items" :key="keyOf(i)" :item="i" :still="still" :initials="initials" :blacked="isBlacked(i, next, nextItem)" :next="nextKind(i)" :can-wear="wearable(i)" :worn="isWorn(i)" :busy="busyKey === keyOf(i)" :error="errors[keyOf(i)]" @wear="wear" />
          </li>
        </ol>
      </section>

      <section v-if="g.titles.length" class="ct-sec" data-testid="track-titles">
        <h2>{{ t('contributorTrack.view.titles', 'Titles') }}</h2>
        <p class="ct-note">{{ t('contributorTrack.view.titlesNote', 'One title is worn at a time, under your name. Only the next one to unlock is shown; the others stay dark until you get there.') }}</p>
        <ul class="ct-grid">
          <li v-for="i in g.titles" :key="keyOf(i)"><TrackItemCard :item="i" :still="still" :blacked="isBlacked(i, next, nextItem)" :next="nextKind(i)" :can-wear="wearable(i)" :worn="isWorn(i)" :busy="busyKey === keyOf(i)" :error="errors[keyOf(i)]" @wear="wear" /></li>
        </ul>
      </section>

      <section v-if="g.side.length" class="ct-sec" data-testid="track-side">
        <h2>{{ t('contributorTrack.view.side', 'Side quests') }}</h2>
        <ul class="ct-grid">
          <li v-for="i in g.side" :key="keyOf(i)"><TrackItemCard :item="i" :still="still" :blacked="isBlacked(i, next, nextItem)" :next="nextKind(i)" :can-wear="wearable(i)" :worn="isWorn(i)" :busy="busyKey === keyOf(i)" :error="errors[keyOf(i)]" @wear="wear" /></li>
        </ul>
      </section>

      <details v-if="g.later.length" class="ct-card ct-later" data-testid="track-later-group">
        <summary>{{ t('contributorTrack.view.laterGroup', 'Drawn and waiting for a condition') }} <span class="ct-count">{{ g.later.length }}</span></summary>
        <p class="ct-note">{{ t('contributorTrack.view.laterNote', 'These rings and badges are drawn and waiting. Nothing unlocks them yet: a condition is set only when a real signal exists.') }}</p>
        <ul class="ct-grid">
          <li v-for="i in g.later" :key="keyOf(i)"><TrackItemCard :item="i" :still="still" :blacked="isBlacked(i, next, nextItem)" /></li>
        </ul>
      </details>

      <p v-if="seasonNote" class="ct-note" data-testid="track-seasons">{{ seasonNote }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import CodeChangesTabs from '@/components/codeChanges/CodeChangesTabs.vue'
import CommanderPlate from '@/components/contributor/CommanderPlate.vue'
import TrackItemCard from '@/components/contributor/TrackItemCard.vue'
import { useI18n } from '@/composables/useI18n'
import { getMyTrack, getPublicTrack, type TrackItem } from '@/services/api/contributorTrack'
import { useContributorWear } from '@/composables/useContributorWear'
import Icon from '@/components/Icon.vue'
import { groups, isBlacked, keyOf, nextOpenTier, nextTitle, nextTrackItem, unlockedCount, wornTitleOf } from '@/services/contributorTrackView'
import { useAuthStore } from '@/stores/auth'

const { t, tp } = useI18n()
const auth = useAuthStore()
const signedIn = computed(() => !!auth.isAuthenticated)
const initials = computed(() => String((auth.user as any)?.name || (auth.user as any)?.email || '').split(/\s+/).map((w: string) => w[0] || '').join('').slice(0, 2).toUpperCase())
// reduced motion: the art shows its still frame by itself; the page also gives a still frame to a person who asked the system for less motion
const still = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false

const loading = ref(true)
const failed = ref(false)
const items = ref<TrackItem[]>([])
const track = ref<Awaited<ReturnType<typeof getMyTrack>> | null>(null)
const { busyKey, errors, isWorn, readWorn, wear, flareTier, wornTitle } = useContributorWear(t('contributorTrack.view.wearFailed', 'That could not be changed just now.'))

// the commander tier comes from the flare status the page already reads (the stored user may predate it)
const isCommander = computed(() => flareTier.value === 'commander' || (auth.user as any)?.flare_tier === 'commander')
const g = computed(() => groups(items.value))
// the one title shown in full; the rest of what is not yet unlocked is an outline
const next = computed(() => nextTitle(items.value))
const rowEl = ref<HTMLElement | null>(null)
const openTier = computed(() => nextOpenTier(g.value.tiers))                    // the first tier not done: where "jump to my next tier" goes
// the row scrolls sideways on a wide screen and stacks on a phone: the jump follows what the page is doing, and a person who asked for less motion gets none
const reduced = typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
function scrollRow(dir: -1 | 1) {
  const el = rowEl.value
  if (!el || typeof el.scrollBy !== 'function') return
  el.scrollBy({ left: dir * Math.max(el.clientWidth * 0.8, 240), behavior: reduced ? 'auto' : 'smooth' })
}
function jumpTo(tier: number | null) {
  const row = rowEl.value
  if (!row || tier === null) return
  const el = row.querySelector<HTMLElement>(`[data-testid="track-tier-${tier}"]`)
  if (!el) return
  const stacked = typeof getComputedStyle === 'function' && getComputedStyle(row).overflowX === 'visible'   // a phone: the tiers are one under the other (the row does not scroll), so the page scrolls to it
  if (stacked) { if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'start', behavior: reduced ? 'auto' : 'smooth' }) }
  else if (typeof row.scrollTo === 'function') row.scrollTo({ left: Math.max(0, el.offsetLeft - row.offsetLeft), behavior: reduced ? 'auto' : 'smooth' })
}
const nextItem = computed(() => nextTrackItem(items.value))                // the next item of the pass: shown in full too (his feedback, room seq 4568)
const nextKind = (i: TrackItem): '' | 'title' | 'track' =>
  (next.value && keyOf(i) === keyOf(next.value) ? 'title' : nextItem.value && keyOf(i) === keyOf(nextItem.value) ? 'track' : '')
// the commander wears the COMMANDER title by default: while no other title is worn (a rule of the code, nothing is stored)
const commanderWorn = computed(() => isCommander.value && wornTitleOf(wornTitle.value, 'commander') === 'commander')
const total = computed(() => unlockedCount(items.value))
const seasonNote = computed(() => (track.value?.season_wins?.length ? tp('contributorTrack.view.seasonWins', 'Seasons you won: {q}.', { q: track.value.season_wins.join(', ') }) : ''))

const wearable = (i: TrackItem) => signedIn.value && !!i.unlocked

async function load() {
  loading.value = true; failed.value = false
  try {
    if (signedIn.value) {
      const mine = await getMyTrack()
      track.value = mine; items.value = mine.items
      await readWorn(mine.equipped_title)
    } else {
      items.value = (await getPublicTrack()).items
    }
  } catch { failed.value = true } finally { loading.value = false }
}

onMounted(load)
</script>

<style scoped>
.ct { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 78rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.4rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ct > * { min-width: 0; }
.ct-hero { display: grid; gap: .6rem; justify-items: start; }
.ct-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.ct-hero h1 { margin: 0; font-size: 1.9rem; font-weight: 300; letter-spacing: -.01em; }
.ct-lede { margin: 0; color: var(--muted); font-size: .92rem; max-width: 50rem; line-height: 1.6; }
.ct-total { margin: 0; font: 600 .78rem var(--mono); letter-spacing: .05em; color: #34d399; }
.ct-total a { color: var(--cyan); }
.ct-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.25rem; min-width: 0; }
.ct-fail { display: grid; gap: .7rem; justify-items: start; }
.ct-btn { min-height: 40px; padding: 0 18px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .85rem; cursor: pointer; }
.ct-skel { display: grid; gap: .8rem; }
.ct-skel i { display: block; height: 7rem; border-radius: 12px; background: rgba(255,255,255,.04); animation: ct-pulse 1.4s ease-in-out infinite; }
@keyframes ct-pulse { 50% { opacity: .5; } }
@media (prefers-reduced-motion: reduce) { .ct-skel i { animation: none; } }
.ct-sec { display: grid; gap: .8rem; }
.ct-sec h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.ct-hint { margin: -.3rem 0 0; font: 600 .68rem var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
@media (max-width: 720px) { .ct-hint { display: none; } }
.ct-note { margin: 0; font-size: .82rem; line-height: 1.55; color: var(--muted); max-width: 52rem; }
.ct-commander { display: grid; gap: .8rem; justify-items: start; background: #05070a; border-color: rgba(255,255,255,.12); }
.ct-commander p { margin: 0; font-size: .82rem; color: #aab4c0; max-width: 40rem; }
/* the battle-pass row: tiers side by side on a wide screen (it scrolls sideways inside its own box), stacked on a phone */
.ct-row { list-style: none; margin: 0; padding: 0 0 .5rem; display: grid; grid-auto-flow: column; grid-auto-columns: minmax(17rem, 19rem); gap: .9rem; align-items: start; overflow-x: auto; scroll-snap-type: x proximity; scrollbar-width: thin; scrollbar-color: rgba(var(--cyan-rgb), .6) rgba(255,255,255,.07); }
/* a tier of two items (tier ten) takes two columns and draws them side by side, so every column is one card tall and the scrollbar sits right under the cards */
.ct-tier--pair { grid-column: span 2; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: .9rem; }
.ct-tier--pair > .ct-node, .ct-tier--pair > .ct-tier-k { grid-column: 1; }
.ct-pass-bar { display: flex; align-items: center; justify-content: space-between; gap: .8rem; flex-wrap: wrap; }
.ct-pass-bar .ct-hint { margin: 0; }
.ct-jumps { display: flex; align-items: center; gap: .5rem; }
.ct-arrow, .ct-jump { min-height: 36px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .08); color: var(--cyan); font: inherit; font-size: .78rem; cursor: pointer; }
.ct-arrow { width: 36px; display: grid; place-items: center; }
.ct-arrow :deep(svg) { width: 1.1rem; height: 1.1rem; }
.ct-jump { padding: 0 14px; font-weight: 600; letter-spacing: .02em; }
.ct-row:focus-visible { outline: 2px solid var(--cyan); outline-offset: 3px; border-radius: 6px; }
.ct-arrow:hover, .ct-jump:hover, .ct-arrow:focus-visible, .ct-jump:focus-visible { background: rgba(var(--cyan-rgb), .16); }
.ct-tier { position: relative; display: grid; gap: .6rem; align-content: start; padding-top: 2.1rem; scroll-snap-align: start; scroll-margin-top: 1rem; min-width: 0; }
.ct-tier::before { content: ''; position: absolute; left: 1.2rem; right: -.9rem; top: .75rem; height: 2px; background: rgba(var(--cyan-rgb), .22); }
.ct-tier:last-child::before { right: 0; }
.ct-tier[data-state='done']::before { background: var(--cyan); }
.ct-node { position: absolute; left: 0; top: 0; width: 1.6rem; height: 1.6rem; border-radius: 50%; display: grid; place-items: center; font: 700 .72rem var(--mono); background: #0b1218; border: 1px solid rgba(var(--cyan-rgb), .4); color: var(--muted); }
.ct-tier[data-state='done'] .ct-node { background: var(--cyan); color: #04141a; border-color: transparent; }
.ct-tier[data-state='partial'] .ct-node { border-color: var(--cyan); color: var(--cyan); }
.ct-tier-k { position: absolute; left: 2.1rem; top: .25rem; font: 700 9px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.ct-grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); gap: .9rem; }
.ct-later summary { cursor: pointer; font-size: .95rem; min-height: 32px; display: flex; align-items: center; gap: .6rem; }
.ct-later[open] summary { margin-bottom: .8rem; }
.ct-count { font: 600 .68rem var(--mono); color: var(--muted); }
@media (max-width: 720px) {
  .ct { padding: 1rem .9rem 2.5rem; }
  .ct-row { grid-auto-flow: row; grid-auto-columns: auto; overflow-x: visible; }
  .ct-tier--pair { grid-column: auto; grid-template-columns: minmax(0, 1fr); }
  .ct-arrow { display: none; }
  .ct-tier::before { right: auto; width: 2px; height: calc(100% - 1.6rem); left: .79rem; top: 1.7rem; }
  .ct-tier:last-child::before { display: none; }
  .ct-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
