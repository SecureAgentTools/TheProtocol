<!--
  EarnedWearPanel — the EARNED category of the Flare view (V0666, order gwo_558042610799088faf1a5e4c; his feedback, room seq 4568: "they need to be visible in another category
  so they know its separate unlocks not bought ... the not unlocked ones from code track can be blacked out in my flare too"). Rings, badges and (for you, never an agent) titles,
  labelled as earned by contributing and never for sale; what the person has not unlocked is an outline only, as on the Track tab, and only the next title and the next item of
  the pass are shown in full. Wearing is for the bearer chosen above: one earned copy is worn by one bearer at a time, and a copy another bearer wears says so and moves here on a
  press. An agent that wears a bought ring or corner is told to take it off first, before the registry has to say it. The registry's unlock row is the gate; this only asks.
-->
<template>
  <section class="ewp" data-testid="earned-wear" :data-bearer="bearer.kind">
    <header class="ewp-h">
      <h2>{{ t('flareWear.earned.h', 'Unlocked by contributing') }}</h2>
      <p>{{ t('flareWear.earned.sub', 'Never for sale and never given: these came from real work on the platform. They are separate from the flares you bought.') }}</p>
      <p class="ewp-for" data-testid="earned-for">{{ bearer.kind === 'developer' ? t('flareWear.earned.forYou', 'Choosing for you') : tp('flareWear.earned.forAgent', 'Choosing for {name}', { name: bearer.name }) }}</p>
    </header>
    <p v-if="state === 'failed'" class="ewp-note" data-testid="earned-failed"><ReadFailedNotice :retry="() => $emit('retry')" /></p>
    <template v-else-if="state === 'ready'">
      <p v-if="!unlockedCount" class="ewp-none" data-testid="earned-none">{{ t('flareWear.earned.none', 'Nothing unlocked yet.') }} <RouterLink :to="{ name: 'code-changes-track' }">{{ t('flareWear.earned.trackShort', 'See what unlocks a badge, a ring or a title.') }}</RouterLink></p>
      <section v-for="g in sections" :key="g.id" class="ewp-sec" :data-testid="`earned-${g.id}`">
        <h3>{{ g.label }}<span class="ewp-count">{{ g.done }} / {{ g.items.length }}</span></h3>
        <div v-if="g.id === 'titles' && isCommander" class="ewp-commander" data-testid="earned-commander">
          <CommanderPlate size="card" :still="still" />
          <p>{{ t('contributorTrack.view.commander', 'One of one. It belongs to the commander flare tier and to no one else: nobody unlocks it and nobody is given it.') }}</p>
          <p v-if="commanderWorn" class="ewp-cmd-worn" data-testid="earned-commander-worn">{{ t('contributorTrack.view.commanderWorn', 'Worn under your name unless you choose another title.') }}</p>
          <button v-else type="button" class="ewp-cmd-btn" :disabled="busyKey === 'title:commander'" data-testid="earned-commander-wear" @click="$emit('commander')">{{ t('flareWear.earned.wearCommander', 'Wear the COMMANDER title') }}</button>
          <p v-if="errors['title:commander']" class="ewp-cmd-err" role="alert">{{ errors['title:commander'] }}</p>
        </div>
        <p v-if="g.blockedBy" class="ewp-block" :data-testid="`earned-${g.id}-blocked`">{{ g.blockedBy }}</p>
        <ul class="ewp-grid">
          <li v-for="i in g.open" :key="keyOf(i)">
            <TrackItemCard :item="i" :still="still" :initials="initials" :blacked="isBlacked(i, nextT, nextI)" :next="nextKind(i)" :can-wear="!g.blockedBy" :worn="worn(i)" :busy="busyKey === keyOf(i)" :error="errors[keyOf(i)]" @wear="(x: TrackItem) => $emit('wear', x, worn(x))" />
            <p v-if="heldElsewhere(i)" class="ewp-held" :data-testid="`earned-held-${i.key}`">{{ tp('flareWear.earned.heldBy', 'Worn by {name}. Wearing it here moves it.', { name: heldElsewhere(i) }) }}</p>
          </li>
        </ul>
        <div v-if="g.dark.length" class="ewp-darkwrap">
          <p class="ewp-dark-count" :data-testid="`earned-${g.id}-dark-count`">{{ tp('flareWear.earned.stillDark', '{n} still locked', { n: g.dark.length }) }}</p>
          <ul class="ewp-dark" :data-testid="`earned-${g.id}-dark`">
            <li v-for="i in g.dark" :key="keyOf(i)"><TrackItemCard :item="i" :still="still" :initials="initials" :blacked="true" /></li>
          </ul>
        </div>
      </section>
      <p v-if="bearer.kind !== 'developer'" class="ewp-note" data-testid="earned-no-titles">{{ t('flareWear.earned.noTitles', 'A title says what a person did, so it stays yours: choose it with "You" selected.') }}</p>
      <RouterLink :to="{ name: 'code-changes-track' }" class="ewp-more" data-testid="earned-track-link">{{ t('contributorTrack.panel.track', 'See the whole track') }}</RouterLink>
    </template>
    <p v-else class="ewp-note"><Icon name="mdi:loading" /> {{ t('flareWear.earned.loading', 'Reading what you unlocked') }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import CommanderPlate from '@/components/contributor/CommanderPlate.vue'
import TrackItemCard from '@/components/contributor/TrackItemCard.vue'
import { useI18n } from '@/composables/useI18n'
import type { TrackItem } from '@/services/api/contributorTrack'
import { isBlacked, keyOf, nextTitle, nextTrackItem } from '@/services/contributorTrackView'
import type { Bearer, Worn } from '@/services/flareBearers'

const props = defineProps<{
  items: TrackItem[]
  state: 'loading' | 'ready' | 'failed'
  bearer: Bearer
  /** what this bearer wears now */
  wornNow: Worn
  /** the name of the OTHER bearer that wears an earned ring or badge, or '' when it is free or worn by this bearer */
  holderName: (kind: 'encirclement' | 'corner', key: string) => string
  busyKey: string
  errors: Record<string, string>
  initials: string
  still: boolean
  /** the commander flare tier: the COMMANDER plate is theirs alone (nobody unlocks it, nobody is given it) */
  isCommander: boolean
}>()
defineEmits<{ (e: 'wear', item: TrackItem, off: boolean): void; (e: 'retry'): void; (e: 'commander'): void }>()
const { t, tp } = useI18n()

const nextT = computed(() => nextTitle(props.items))
const nextI = computed(() => nextTrackItem(props.items))
const nextKind = (i: TrackItem): '' | 'title' | 'track' => (nextT.value && keyOf(i) === keyOf(nextT.value) ? 'title' : nextI.value && keyOf(i) === keyOf(nextI.value) ? 'track' : '')
// the commander wears the COMMANDER title by default: while no other title is worn (a rule of the code, nothing is stored)
const commanderWorn = computed(() => props.isCommander && !props.wornNow.title)
const unlockedCount = computed(() => props.items.filter((i) => i.unlocked).length)
const byTier = (a: TrackItem, b: TrackItem) => (a.tier ?? 999) - (b.tier ?? 999)

const worn = (i: TrackItem): boolean => (i.kind === 'title' ? props.wornNow.title === i.key : i.kind === 'encirclement' ? props.wornNow.ring?.source === 'earned' && props.wornNow.ring.key === i.key : props.wornNow.badge?.source === 'earned' && props.wornNow.badge.key === i.key)
const heldElsewhere = (i: TrackItem): string => (i.kind === 'title' || !i.unlocked || worn(i) ? '' : props.holderName(i.kind, i.key))

// an agent that wears a bought ring or corner is told to take it off first (one ring and one corner per agent)
const blockedRing = computed(() => props.bearer.kind === 'agent' && props.wornNow.ring?.source === 'bought')
const blockedBadge = computed(() => props.bearer.kind === 'agent' && props.wornNow.badge?.source === 'bought')
const sections = computed(() => {
  const mk = (id: string, label: string, kind: TrackItem['kind'], blocked: boolean, blockWords: string) => {
    const items = props.items.filter((i) => i.kind === kind).sort(byTier)
    // what is shown in full (unlocked, and the next of the pass and the next title) first; the rest is an outline only, in a compact strip after them
    const open = items.filter((i) => !isBlacked(i, nextT.value, nextI.value))
    const dark = items.filter((i) => isBlacked(i, nextT.value, nextI.value))
    return { id, label, items, open, dark, done: items.filter((i) => i.unlocked).length, blockedBy: blocked ? blockWords : '' }
  }
  const out = [
    mk('rings', t('flareWear.earned.rings', 'Rings'), 'encirclement', blockedRing.value, t('flareWear.earned.ringBlocked', 'This agent wears a bought ring. Take it off in Bought first, then give it an unlocked one.')),
    mk('badges', t('flareWear.earned.badges', 'Badges'), 'corner', blockedBadge.value, t('flareWear.earned.badgeBlocked', 'This agent wears a bought corner. Take it off in Bought first, then give it an unlocked badge.')),
  ]
  if (props.bearer.kind === 'developer') out.push(mk('titles', t('flareWear.earned.titles', 'Titles'), 'title', false, ''))
  return out
})
</script>

<style scoped>
.ewp { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); display: grid; gap: 1rem; margin: 0 0 1.4rem; padding: 1.1rem 1.25rem; border: 1px solid rgba(var(--cyan-rgb), .2); border-radius: 12px; background: rgba(var(--cyan-rgb), .03); font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ewp-h h2 { margin: 0; font-size: 1.05rem; font-weight: 400; }
.ewp-h p, .ewp-note, .ewp-none { margin: .25rem 0 0; font-size: .82rem; line-height: 1.55; color: #8b97a6; }
.ewp-for { color: var(--cyan) !important; font: 500 .72rem/1.4 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; }
.ewp-sec h3 { margin: 0 0 .6rem; font-size: .8rem; font-weight: 500; letter-spacing: .1em; text-transform: uppercase; color: #c4ccd6; display: flex; align-items: baseline; gap: .6rem; }
.ewp-count { font: 500 .7rem 'IBM Plex Mono', monospace; color: #8b97a6; letter-spacing: .04em; }
.ewp-block { margin: 0 0 .6rem; padding: .5rem .75rem; border-left: 2px solid rgba(255, 196, 0, .6); font-size: .8rem; color: #d9c27a; background: rgba(255, 196, 0, .05); }
.ewp-grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); gap: .8rem; align-items: start; }
.ewp-held { margin: .35rem .2rem 0; font-size: .74rem; color: #8b97a6; }
.ewp-darkwrap { display: grid; gap: .3rem; margin-top: .8rem; }
.ewp-dark-count { margin: 0; font: 500 .68rem 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; color: #8b97a6; }
.ewp-dark { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: .1rem .4rem; align-items: center; }
.ewp-none a, .ewp-more { color: var(--cyan); }
.ewp-more { justify-self: start; font-size: .82rem; }
.ewp-commander { display: grid; gap: .6rem; justify-items: start; margin: 0 0 .8rem; padding: 1rem 1.1rem; border: 1px solid rgba(255, 255, 255, .12); border-radius: 10px; background: #05070a; }
.ewp-commander p { margin: 0; font-size: .8rem; line-height: 1.55; color: #aab4c0; max-width: 40rem; }
.ewp-cmd-worn { color: #8fd9b6 !important; }
.ewp-cmd-btn { min-height: 36px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(255, 255, 255, .25); background: transparent; color: #e8eaed; font: inherit; font-size: .8rem; cursor: pointer; }
.ewp-cmd-btn:hover:not(:disabled), .ewp-cmd-btn:focus-visible { background: rgba(255, 255, 255, .08); }
.ewp-cmd-btn:disabled { opacity: .5; cursor: default; }
.ewp-cmd-err { color: #ff8a8a !important; }
@media (max-width: 720px) { .ewp-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
