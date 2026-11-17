<!--
  FlareBearerRail — who wears (V0666, order gwo_558042610799088faf1a5e4c; his feedback on the preview, room seq 4568: "i dont like how to pick/equp the agent bearers in my flare view").
  The bearers first: you, then every agent, each with what it wears at a glance (the ring, the badge, and for you the title); pick one and the page below is about that bearer.
  Searchable at a fleet's scale (the list is capped at 200 agents), one press to choose, no popover, no per-slot hunt. A read that failed says so and offers it again.
-->
<template>
  <section class="fbr" data-testid="flare-rail" :aria-label="t('flareWear.rail.label', 'Who wears it')">
    <header class="fbr-h">
      <h2>{{ t('flareWear.rail.h', 'Who wears it') }}</h2>
      <p>{{ t('flareWear.rail.sub', 'Pick you or one of your agents. What each one wears is shown on its row.') }}</p>
    </header>
    <ReadFailedNotice v-if="state === 'failed'" :retry="() => $emit('retry')" />
    <template v-else>
      <input v-if="bearers.length > 8" v-model="q" type="search" class="fbr-search" data-testid="rail-search" :placeholder="t('flareWear.rail.search', 'Find an agent')" :aria-label="t('flareWear.rail.search', 'Find an agent')" />
      <p v-if="state === 'loading'" class="fbr-note"><Icon name="mdi:loading" class="fbr-spin" /> {{ t('flareWear.rail.loading', 'Reading your agents') }}</p>
      <ul class="fbr-list" role="list">
        <li v-for="b in shown" :key="b.key">
          <button type="button" class="fbr-row" :class="{ 'fbr-on': b.key === selected }" :aria-pressed="b.key === selected" :data-testid="`bearer-${b.key}`" @click="$emit('select', b.key)">
            <span class="fbr-init" aria-hidden="true">{{ initial(b) }}</span>
            <span class="fbr-name">{{ b.kind === 'developer' ? t('flareWear.rail.you', 'You') : b.name }}<span v-if="b.kind === 'developer'" class="fbr-sub">{{ b.name }}</span></span>
            <span class="fbr-worn" :data-testid="`bearer-${b.key}-worn`">
              <span v-if="wornOf(b).ring" class="fbr-chip" :data-source="wornOf(b).ring!.source" :data-testid="`bearer-${b.key}-ring`" :title="t('flareWear.rail.ringWord', 'Ring')"><span class="fbr-k" aria-hidden="true">{{ t('flareWear.rail.ringWord', 'Ring') }}</span> {{ itemName('ring', wornOf(b).ring!) }}</span>
              <span v-if="wornOf(b).badge" class="fbr-chip" :data-source="wornOf(b).badge!.source" :data-testid="`bearer-${b.key}-badge`" :title="t('flareWear.rail.badgeWord', 'Badge')"><span class="fbr-k" aria-hidden="true">{{ t('flareWear.rail.badgeWord', 'Badge') }}</span> {{ itemName('badge', wornOf(b).badge!) }}</span>
              <span v-if="wornOf(b).title" class="fbr-chip fbr-chip-title" :data-testid="`bearer-${b.key}-title`" :title="t('flareWear.rail.titleWord', 'Title')"><span class="fbr-k" aria-hidden="true">{{ t('flareWear.rail.titleWord', 'Title') }}</span> {{ titleName(wornOf(b).title!) }}</span>
              <span v-if="!wornOf(b).ring && !wornOf(b).badge && !wornOf(b).title" class="fbr-none">{{ t('flareWear.rail.nothing', 'Wears nothing yet') }}</span>
            </span>
          </button>
        </li>
      </ul>
      <p v-if="state === 'ready' && bearers.length === 1" class="fbr-note" data-testid="rail-no-agents">
        {{ t('flareWear.rail.noAgents', 'You have no agents yet.') }} <RouterLink to="/onboarding">{{ t('flareWear.rail.createAgent', 'Create one') }}</RouterLink>
      </p>
      <p v-if="q.trim() && shown.length === 1" class="fbr-note">{{ t('flareWear.rail.noMatch', 'No agent matches that.') }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { filterBearers, type Bearer, type Worn, type WornItem } from '@/services/flareBearers'

const props = defineProps<{ bearers: Bearer[]; selected: string; worn: (b: Bearer) => Worn; state: 'loading' | 'ready' | 'failed'; boughtName: (key: string) => string }>()
defineEmits<{ (e: 'select', key: string): void; (e: 'retry'): void }>()
const { t } = useI18n()
const q = ref('')
const shown = computed(() => filterBearers(props.bearers, q.value))
const wornOf = (b: Bearer) => props.worn(b)
const initial = (b: Bearer) => (b.name || '?').replace(/^…/, '').slice(0, 1).toUpperCase()
const itemName = (kind: 'ring' | 'badge', w: WornItem) => (w.source === 'bought' ? props.boughtName(w.key) : t(`contributorTrack.${kind === 'ring' ? 'rings' : 'badges'}.${w.key}.name`, w.key))
const titleName = (key: string) => t(`contributorTrack.titles.${key}.name`, key)
</script>

<style scoped>
.fbr { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); display: grid; gap: .7rem; margin: 0 0 1.2rem; padding: 1.1rem 1.25rem; border: 1px solid rgba(var(--cyan-rgb), .2); border-radius: 12px; background: rgba(var(--cyan-rgb), .03); font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.fbr-h h2 { margin: 0; font-size: 1.05rem; font-weight: 400; letter-spacing: .01em; }
.fbr-h p, .fbr-note { margin: .25rem 0 0; font-size: .82rem; line-height: 1.55; color: #8b97a6; }
.fbr-note a { color: var(--cyan); }
.fbr-search { min-height: 36px; padding: 0 .8rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0, 0, 0, .25); color: inherit; font: inherit; font-size: .85rem; }
.fbr-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); gap: .5rem; max-height: 26rem; overflow-y: auto; }
.fbr-row { width: 100%; min-height: 56px; display: grid; grid-template-columns: 2.1rem minmax(0, 1fr); grid-template-areas: 'i n' 'i w'; column-gap: .7rem; align-items: center; text-align: left; padding: .55rem .75rem; border-radius: 10px; border: 1px solid rgba(var(--cyan-rgb), .14); background: rgba(255, 255, 255, .02); color: inherit; font: inherit; cursor: pointer; }
.fbr-row:hover, .fbr-row:focus-visible { border-color: rgba(var(--cyan-rgb), .45); }
.fbr-on { border-color: var(--cyan); background: rgba(var(--cyan-rgb), .09); }
.fbr-init { grid-area: i; width: 2.1rem; height: 2.1rem; display: grid; place-items: center; border-radius: 50%; border: 1px solid rgba(var(--cyan-rgb), .35); font-size: .8rem; color: var(--cyan); }
.fbr-name { grid-area: n; font-size: .9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fbr-sub { margin-left: .5rem; font-size: .72rem; color: #8b97a6; }
.fbr-worn { grid-area: w; display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .15rem; }
.fbr-chip { font: 500 .66rem/1 'IBM Plex Mono', monospace; letter-spacing: .04em; padding: .22rem .45rem; border-radius: 999px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.fbr-chip[data-source='bought'] { border-color: rgba(255, 255, 255, .22); color: #c4ccd6; }
.fbr-chip-title { border-style: dashed; }
.fbr-k { opacity: .6; text-transform: uppercase; font-size: .6rem; letter-spacing: .08em; margin-right: .15rem; }
.fbr-none { font-size: .72rem; color: #8b97a6; }
.fbr-spin { animation: fbr-spin 1s linear infinite; }
@keyframes fbr-spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) { .fbr-list { grid-template-columns: minmax(0, 1fr); max-height: 22rem; } }
@media (prefers-reduced-motion: reduce) { .fbr-spin { animation: none; } }
</style>
