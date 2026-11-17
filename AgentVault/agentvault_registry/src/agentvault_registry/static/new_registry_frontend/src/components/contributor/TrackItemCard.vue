<!--
  TrackItemCard — one item of the contributor track (V0665, order gwo_5e0701efdef9d3989491bc37): the item drawn live by the art's own components
  (EarnedRing, EarnedBadge, TitleEmblem), its name, the one sentence that earns it, and where the person stands: earned, n of m, or "comes later" with
  the registry's reason. An item not yet unlocked is BLACKED OUT (his feedback, room seq 4404): its outline only, no art, no name, no sentence, no progress, so the track
  shows what can be unlocked and not what it is; the one NEXT title is shown in full. An earned item can be worn here (a title through the title route, a ring or a badge
  through the flare selection); the registry's sentence answers a refusal where it was asked.
-->
<template>
  <article v-if="blacked" class="tic tic-blacked" :class="`tic-${kind}`" :data-testid="`track-item-${item.kind}-locked`" data-state="blacked" :data-shape="shape" role="img" :aria-label="lockedWords">
    <svg class="tic-outline" :class="`tic-outline-${shape}`" :viewBox="outline.box" aria-hidden="true" focusable="false" data-testid="track-outline">
      <path v-for="(d, n) in outline.paths" :key="n" :d="d" />
    </svg>
  </article>
  <article v-else class="tic" :class="[`tic-${kind}`, { 'tic-on': item.unlocked, 'tic-later': !!item.later && !item.unlocked, 'tic-worn': worn }]" :data-testid="`track-item-${item.kind}-${item.key}`" :data-state="state">
    <div class="tic-art" :class="{ 'tic-locked': !item.unlocked && !next }" aria-hidden="false">
      <EarnedRing v-if="kind === 'ring'" :ring-key="item.key" :size="ringSize" :initials="initials" :still="still" />
      <EarnedBadge v-else-if="kind === 'badge'" :badge-key="item.key" :size="badgeSize" :still="still" />
      <TitleEmblem v-else :title-key="item.key" size="card" :variant="titleVariant(item.key)" :still="still" />
      <span v-if="!item.unlocked && !next" class="tic-lock" :title="t('contributorTrack.view.locked', 'Locked')"><Icon name="mdi:lock" /></span>
    </div>
    <div class="tic-body">
      <p v-if="next === 'title'" class="tic-next" data-testid="track-next-title">{{ t('contributorTrack.view.nextTitle', 'Next title') }}</p>
      <p v-else-if="next === 'track'" class="tic-next" data-testid="track-next-item">{{ t('contributorTrack.view.nextItem', 'Next on the pass') }}</p>
      <h3 class="tic-name">{{ name }}<span class="tic-kind">{{ kindWord }}</span></h3>
      <p class="tic-cond" :title="item.condition">{{ item.condition }}</p>
      <p v-if="item.later && !item.unlocked" class="tic-later" data-testid="track-later"><span class="tic-later-k">{{ t('contributorTrack.view.later', 'Comes later') }}</span> {{ item.later }}</p>
      <template v-else>
        <div v-if="!item.unlocked" class="tic-bar" role="progressbar" :aria-valuenow="pct" aria-valuemin="0" aria-valuemax="100" :aria-label="tp('contributorTrack.view.progressOf', '{n} of {of}', { n: shownN, of: shownOf })"><i :style="{ width: pct + '%' }"></i></div>
        <p class="tic-state" :data-testid="`track-state-${item.key}`">
          <template v-if="item.unlocked">{{ worn ? t('contributorTrack.view.worn', 'Worn') : t('contributorTrack.view.earned', 'Unlocked') }}</template>
          <template v-else>{{ tp('contributorTrack.view.progressOf', '{n} of {of}', { n: shownN, of: shownOf }) }}</template>
        </p>
      </template>
      <button v-if="item.unlocked && canWear" type="button" class="tic-wear" :disabled="busy" :data-testid="`track-wear-${item.key}`" @click="$emit('wear', item)">
        {{ worn ? t('contributorTrack.view.takeOff', 'Take it off') : t('contributorTrack.view.wear', 'Wear it') }}
      </button>
      <p v-if="error" class="tic-err" role="alert" :data-testid="`track-err-${item.key}`">{{ error }}</p>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import EarnedBadge from '@/components/contributor/EarnedBadge.vue'
import EarnedRing from '@/components/contributor/EarnedRing.vue'
import TitleEmblem from '@/components/contributor/TitleEmblem.vue'
import { useI18n } from '@/composables/useI18n'
import type { TrackItem } from '@/services/api/contributorTrack'
import { drawn, percent, section, titleVariant } from '@/services/contributorTrackView'

const props = withDefaults(defineProps<{ item: TrackItem; worn?: boolean; canWear?: boolean; busy?: boolean; error?: string; initials?: string; still?: boolean; blacked?: boolean; next?: '' | 'title' | 'track' }>(),
  { worn: false, canWear: false, busy: false, error: '', initials: '', still: false, blacked: false, next: '' })
defineEmits<{ (e: 'wear', item: TrackItem): void }>()
const { t, tp } = useI18n()

const kind = computed(() => drawn(props.item.kind))
const ringSize = 64
const badgeSize = 44
const name = computed(() => t(`contributorTrack.${section(props.item.kind)}.${props.item.key}.name`, props.item.key))
const kindWord = computed(() => ({ ring: t('contributorTrack.view.ring', 'Ring'), badge: t('contributorTrack.view.badge', 'Badge'), title: t('contributorTrack.view.title', 'Title') } as Record<string, string>)[kind.value])
const pct = computed(() => percent(props.item))
const shownN = computed(() => props.item.progress?.n ?? 0)
const shownOf = computed(() => props.item.progress?.of ?? 1)
// the outline of what a blacked-out item will be: a ring (two circles), a badge (a shield) or a title plate (a chamfered bar); nothing of the art itself
const OUTLINES = {
  ring: { box: '0 0 64 64', paths: ['M32 3a29 29 0 1 0 0.01 0Z', 'M32 13a19 19 0 1 0 0.01 0Z'] },
  badge: { box: '0 0 44 44', paths: ['M22 3 L40 12 V26 Q40 36 22 41 Q4 36 4 26 V12 Z'] },
  plate: { box: '0 0 220 46', paths: ['M8 1 H212 L219 8 V38 L212 45 H8 L1 38 V8 Z'] },
} as const
const shape = computed<'ring' | 'badge' | 'plate'>(() => (kind.value === 'ring' ? 'ring' : kind.value === 'badge' ? 'badge' : 'plate'))
const outline = computed(() => OUTLINES[shape.value])
const lockedWords = computed(() => tp('contributorTrack.view.lockedKind', 'A locked {kind}', { kind: kindWord.value.toLowerCase() }))
const state = computed(() => (props.item.unlocked ? (props.worn ? 'worn' : 'earned') : props.item.later ? 'later' : 'locked'))
</script>

<style scoped>
.tic.tic-blacked { display: grid; place-items: center; padding: .45rem; background: transparent; border: 1px solid transparent; border-radius: 12px; min-height: 4.4rem; }
.tic.tic-blacked.tic-title { grid-column: 1 / -1; justify-items: start; }
.tic-outline { display: block; overflow: visible; }
.tic-outline path { fill: #05070a; stroke: rgba(255,255,255,.3); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.tic-outline-ring { width: 64px; height: 64px; }
.tic-outline-badge { width: 44px; height: 44px; }
.tic-outline-plate { width: min(100%, 11rem); height: auto; }
.tic-next { margin: 0; font: 700 9px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: #fcd34d; }
.tic { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  display: grid; grid-template-columns: auto minmax(0, 1fr); gap: .9rem; align-items: start; background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035);
  border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: .9rem 1rem; min-width: 0; color: #e8eaed; }
.tic-on { border-color: rgba(var(--cyan-rgb), .5); }
.tic-worn { box-shadow: 0 0 0 1px rgba(var(--cyan-rgb), .6) inset; }
.tic-later { opacity: .92; }
.tic-art { position: relative; display: grid; place-items: center; min-width: 4.4rem; min-height: 4.4rem; max-width: 9rem; }
.tic-ring .tic-art { min-width: 6rem; min-height: 6rem; }   /* a ring's halo overflows the avatar: room for it, so it never touches the card's edge or its words */
.tic-title .tic-art { min-width: 0; min-height: 0; max-width: none; grid-column: 1 / -1; justify-items: start; }
.tic-title { grid-template-columns: minmax(0, 1fr); }
.tic-locked { filter: grayscale(1) brightness(.5) contrast(.9); }
.tic-lock { position: absolute; right: -2px; bottom: -2px; width: 1.3rem; height: 1.3rem; display: grid; place-items: center; border-radius: 50%; background: #0b1218; border: 1px solid rgba(255,255,255,.25); color: #cbd5e1; filter: none; }
.tic-lock :deep(svg) { width: .8rem; height: .8rem; }
.tic-body { display: grid; gap: .35rem; min-width: 0; }
.tic-name { margin: 0; font-size: .95rem; font-weight: 500; display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; overflow-wrap: anywhere; }
.tic-kind { font: 700 9px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.tic-cond { margin: 0; font-size: .8rem; line-height: 1.5; color: #aab4c0; }
/* on a wide screen with a pointer the row stays one height: two lines, the whole sentence in the title on hover; a phone shows it all */
@media (hover: hover) and (min-width: 721px) { .tic-cond { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden; } }
.tic-later { margin: 0; font-size: .78rem; line-height: 1.5; color: #aab4c0; }
.tic-later-k { font: 700 9px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: #fcd34d; margin-right: .4rem; }
.tic-bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.08); overflow: hidden; }
.tic-bar i { display: block; height: 100%; background: var(--cyan); }
.tic-state { margin: 0; font: 600 .72rem var(--mono); letter-spacing: .04em; color: var(--muted); font-variant-numeric: tabular-nums; }
.tic-on .tic-state { color: #34d399; }
.tic-wear { justify-self: start; min-height: 36px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .4); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .78rem; cursor: pointer; }
.tic-wear:hover, .tic-wear:focus-visible { filter: brightness(1.15); }
.tic-wear:disabled { opacity: .5; cursor: progress; }
.tic-err { margin: 0; font-size: .78rem; line-height: 1.5; color: #fca5a5; overflow-wrap: anywhere; }
</style>
