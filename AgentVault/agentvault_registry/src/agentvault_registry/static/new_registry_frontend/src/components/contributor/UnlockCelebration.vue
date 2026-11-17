<!--
  UnlockCelebration — the contributor track's celebration (V0665, order gwo_5e0701efdef9d3989491bc37): when an item is newly earned, the person is told once, with the item
  drawn large by the art's own component. Mounted globally in App.vue for a signed-in person, beside FlareCelebrationModal (the Shadow Chancellor reveal, which stays
  as it is). One read of the track per session; the items already shown on this device are remembered (localStorage, per developer), so a celebration never repeats. It
  asks for nothing: it opens the track or closes. Escape closes it; a person who asked the system for less motion gets the art's still frame.
-->
<template>
  <Teleport to="body">
    <div v-if="open" class="uc-overlay" data-testid="unlock-celebration" @click.self="close">
      <div ref="card" class="uc-card" role="dialog" aria-modal="true" aria-labelledby="uc-h" tabindex="-1" @keydown.esc.prevent="close">
        <span class="uc-eyebrow">{{ t('contributorTrack.unlock.eyebrow', 'Contributor track') }}</span>
        <h2 id="uc-h" class="uc-h">{{ fresh.length > 1 ? tp('contributorTrack.unlock.many', '{n} new items unlocked', { n: fresh.length }) : t('contributorTrack.unlock.one', 'You unlocked something') }}</h2>
        <ul class="uc-list">
          <li v-for="i in fresh" :key="keyOf(i)" class="uc-item" :data-testid="`unlock-item-${i.key}`">
            <EarnedRing v-if="drawn(i.kind) === 'ring'" :ring-key="i.key" :size="96" :initials="initials" :still="still" />
            <EarnedBadge v-else-if="drawn(i.kind) === 'badge'" :badge-key="i.key" :size="72" :still="still" />
            <TitleEmblem v-else :title-key="i.key" size="card" :variant="titleVariant(i.key)" :still="still" />
            <span class="uc-name">{{ nameOf(i) }}</span>
            <span class="uc-cond">{{ i.condition }}</span>
          </li>
        </ul>
        <p class="uc-note">{{ t('contributorTrack.unlock.note', 'Unlocked by real work on the platform. Nothing here was bought, and you can wear it from the track.') }}</p>
        <div class="uc-actions">
          <button ref="primary" type="button" class="uc-btn primary" data-testid="unlock-open" @click="openTrack">{{ t('contributorTrack.unlock.open', 'See the track') }}</button>
          <button type="button" class="uc-btn" data-testid="unlock-close" @click="close">{{ t('contributorTrack.unlock.close', 'Close') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import EarnedBadge from '@/components/contributor/EarnedBadge.vue'
import EarnedRing from '@/components/contributor/EarnedRing.vue'
import TitleEmblem from '@/components/contributor/TitleEmblem.vue'
import { useI18n } from '@/composables/useI18n'
import { getMyTrack, type TrackItem } from '@/services/api/contributorTrack'
import { drawn, keyOf, markChecked, newUnlocks, readSeen, section, titleVariant, writeSeen } from '@/services/contributorTrackView'
import { useAuthStore } from '@/stores/auth'

const { t, tp } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const open = ref(false)
const fresh = ref<TrackItem[]>([])
const card = ref<HTMLElement | null>(null)
const primary = ref<HTMLButtonElement | null>(null)
const devId = computed(() => (auth.user as any)?.id ?? null)
const initials = computed(() => String((auth.user as any)?.name || (auth.user as any)?.email || '').split(/\s+/).map((w: string) => w[0] || '').join('').slice(0, 2).toUpperCase())
const still = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false
const nameOf = (i: TrackItem) => t(`contributorTrack.${section(i.kind)}.${i.key}.name`, i.key)

onMounted(async () => {
  if (!auth.isAuthenticated) return
  if (!markChecked(devId.value)) return                                          // one read of the track per page load (in memory: no browser-storage key)
  try {
    const mine = await getMyTrack()
    const seen = readSeen(localStorage, devId.value)
    const list = newUnlocks(mine.items, seen)
    if (!list.length) return
    fresh.value = list
    open.value = true
    await nextTick()
    primary.value?.focus()
  } catch { /* a celebration is never worth an error: the track tab answers for itself */ }
})

function remember() {
  const seen = readSeen(localStorage, devId.value)
  fresh.value.forEach((i) => seen.add(keyOf(i)))
  writeSeen(localStorage, devId.value, seen)
}
function close() { remember(); open.value = false }
function openTrack() { remember(); open.value = false; void router.push({ name: 'code-changes-track' }) }
</script>

<style scoped>
.uc-overlay { position: fixed; inset: 0; z-index: 10050; display: grid; place-items: center; padding: 1rem; background: rgba(2, 6, 10, .78); }
.uc-card { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); width: min(40rem, 100%); max-height: calc(100vh - 2rem); overflow: auto; display: grid; gap: .9rem; justify-items: center; text-align: center;
  padding: 1.6rem 1.4rem; border-radius: 14px; border: 1px solid rgba(var(--cyan-rgb), .35); background: #0a1118; color: #e8eaed; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.uc-card:focus { outline: none; }
.uc-eyebrow { font: 700 10px/1 'IBM Plex Mono', monospace; letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); }
.uc-h { margin: 0; font-size: 1.4rem; font-weight: 300; }
.uc-list { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 1.2rem 1.4rem; width: 100%; align-items: flex-start; }
.uc-list > li { flex: 0 1 12rem; min-width: 0; }
.uc-item { display: grid; gap: .4rem; justify-items: center; }
.uc-item > :first-child { margin: 1rem 0 1.2rem; }   /* a ring's halo overflows its box: room for it above the name */
.uc-name { font-size: 1.05rem; font-weight: 500; }
.uc-cond { font-size: .8rem; color: #aab4c0; line-height: 1.5; }
.uc-note { margin: 0; font-size: .8rem; color: #8b97a6; line-height: 1.55; max-width: 26rem; }
.uc-actions { display: flex; flex-wrap: wrap; gap: .6rem; justify-content: center; }
.uc-btn { min-height: 42px; padding: 0 20px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .4); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .85rem; cursor: pointer; }
.uc-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.uc-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .7); outline-offset: 2px; }
</style>
