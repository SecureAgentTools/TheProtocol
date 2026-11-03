<template>
  <!-- §ROOMVIEW DESKTOP — OurChat was Pocket-only, so a 1440px screen got the
       phone: one pane, no conversation list, and a thread stretched to the full
       width. This shell gives desktop the two-pane shape a chat app wants while
       REUSING both existing views unchanged — there is no second OurChat to keep
       in sync. (Two divergent implementations of the same chat is exactly the
       drift that left /balance working in the showcase and dead here.)

       Below `--ocs-wide` it renders exactly what it rendered before: the list at
       /pocket/ourchat, the thread at /pocket/ourchat/:id, one at a time. Paths
       and route names are unchanged, so every deep link and battery still lands. -->
  <div ref="rootEl" class="ocs" :class="{ 'ocs-two': wide, 'ocs-bounded': bounded }" :style="paneStyle"
       data-testid="ocs-root" :data-list="railOn ? 'folded' : 'open'">
    <!-- V0653 (al): the list folded beside an open thread leaves a narrow rail: the way back and the unread count. The
         list stays mounted behind it (v-show), so its count and its live updates go on. -->
    <nav v-if="railOn" class="ocs-rail" data-testid="ocs-rail" :aria-label="t('ourstate.list.railAria', 'Conversations')">
      <button type="button" class="ocs-rail-open" data-testid="ocs-rail-open"
              :aria-label="t('ourstate.list.unfold', 'Show the conversation list')"
              :title="t('ourstate.list.unfold', 'Show the conversation list')" @click="toggleList">
        <Icon name="mdi:chevron-right" /></button>
      <span v-if="unread" class="ocs-rail-unread" data-testid="ocs-rail-unread"
            :title="tp('ourstate.list.railUnread', '{n} unread', { n: unread })">{{ unread > 99 ? '99+' : unread }}<span
            class="sr-only">{{ ' ' + t('ourstate.list.railUnreadWord', 'unread') }}</span></span>
    </nav>
    <section v-if="wide || !threadOpen" v-show="!railOn" class="ocs-list" data-testid="ocs-list">
      <PocketOurState />
    </section>

    <section v-if="threadOpen" class="ocs-thread" data-testid="ocs-thread">
      <router-view />
    </section>

    <section v-else-if="wide" class="ocs-empty" data-testid="ocs-empty">
      <!-- ⚠ This was a forum-outline glyph that components/Icon.vue's LOCAL map
           does not carry, so the empty state rendered a SILENT BLANK. Found by
           Icon.names.test.ts on a FULL unit run; the scoped chat-only run I did
           when shipping this yesterday never loaded that spec. The bad name is
           deliberately not written out here — the scanner reads literals and
           would flag its own postmortem. -->
      <Icon name="mdi:chat" />
      <p class="ocs-empty-t">{{ t('ourstate.desktop.pick', 'Pick a conversation') }}</p>
      <p class="ocs-empty-s">{{ t('ourstate.desktop.pickSub', 'Threads, rooms and the support desk all open here.') }}</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, provide, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import PocketOurState from '@/views/pocket/PocketOurState.vue'
import { useAuthStore } from '@/stores/auth'
import { OURCHAT_LIST_FOLD, listAsRail, listFolded, saveListFolded } from '@/services/chat/listFold'

const { t, tp } = useI18n()
const route = useRoute()

/** A thread is open when the child route carries an id. */
const threadOpen = computed(() => !!route.params.id)

/* Width is read from the ELEMENT, not from a media query in JS, so the two
   never disagree about where the breakpoint is. matchMedia is the one source. */
const WIDE = '(min-width: 900px)'
const wide = ref(false)
let mq: MediaQueryList | null = null
const sync = () => { wide.value = !!mq?.matches; measure() }

/* V0653 (al), the sessions' room (seq 686): the list folds beside an open thread, the choice kept per
   person on this device; the list's header, this rail and the thread's arrow are three controls over one state. */
let auth: any = null
try { auth = useAuthStore() } catch { auth = null }   // a mount without the app's store keeps the choice per device
const viewer = computed(() => {
  const u: any = auth?.user || {}
  return String(u.developer_id ?? u.id ?? '')
})
const folded = ref(listFolded(viewer.value))
watch(viewer, (v) => { folded.value = listFolded(v) })
const canFold = computed(() => wide.value && threadOpen.value)
const railOn = computed(() => listAsRail(wide.value, folded.value, threadOpen.value))
const unread = ref<number | null>(null)
function toggleList() {
  folded.value = !folded.value
  saveListFolded(viewer.value, folded.value)
}
provide(OURCHAT_LIST_FOLD, { twoPane: wide, folded, canFold, toggle: toggleList, setUnread: (n) => { unread.value = n } })

/* §DESKCHROME (2026-08-28): in wide mode the SHELL is the height container, so
   the panes scroll internally and the composer never sinks below the fold. The
   offset is the shell's own MEASURED top — never an assumed chrome height
   (`--nc-header-h` is defined nowhere; PART 1 gotcha). Below the breakpoint the
   shell stays in document flow exactly as before (Pocket unchanged).
   V0651 (y): except for an OPEN THREAD. In document flow the thread grew to its whole history and the page scrolled,
   so the approvals panel pinned above the history (V0650 (l)) scrolled away with it: on the maintainer's phone it sat
   about 2,800 px above the latest message (measured at 393 px), while the card in the thread said "decided in the
   panel pinned above". A thread on a phone is bounded like the desktop's pane now: the viewport less the shell's
   measured top and the bottom space the page keeps for its own bar (Pocket's tab bar sits over its main scroller's
   padding), so the history scrolls inside the thread and the panel and the composer stay in view. The list keeps
   the document flow. */
const rootEl = ref<HTMLElement | null>(null)
const topPx = ref(0)
const bottomPx = ref(0)
/** The padding-bottom of the nearest scrolling ancestor: the room a page keeps under its content for a bar that
 *  overlays it (Pocket's .pk-main reserves its tab bar this way). Read, never an assumed bar height. */
function scrollerPaddingBottom(el: HTMLElement): number {
  for (let e = el.parentElement; e; e = e.parentElement) {
    const cs = window.getComputedStyle(e)
    if (/(auto|scroll)/.test(cs.overflowY)) return Math.max(0, Math.round(parseFloat(cs.paddingBottom) || 0))
  }
  return 0
}
const measure = () => {
  try {
    if (rootEl.value) {
      topPx.value = Math.max(0, Math.round(rootEl.value.getBoundingClientRect().top + (window.scrollY || 0)))
      bottomPx.value = scrollerPaddingBottom(rootEl.value)
    }
  } catch { /* noop */ }
}
const bounded = computed(() => !wide.value && threadOpen.value)
const paneStyle = computed(() => {
  // V0652 (ad): the two panes leave the page's bottom space too (Pocket wide keeps its tab bar there; the console's
  // dashboard keeps none), or the composer sat under Pocket's tab bar on a wide screen (measured at 1920 on V0651)
  if (wide.value) return { height: `calc(100vh - ${topPx.value + bottomPx.value}px)` }
  if (bounded.value) return { '--ocs-offset': `${topPx.value + bottomPx.value}px` }
  return undefined
})
watch(threadOpen, () => { void nextTick().then(measure) })

onMounted(() => {
  try {
    mq = window.matchMedia(WIDE)
    sync()
    mq.addEventListener ? mq.addEventListener('change', sync) : mq.addListener(sync)
    window.addEventListener('resize', measure, { passive: true })
    requestAnimationFrame(measure)
  } catch { wide.value = false }
})
onBeforeUnmount(() => {
  try { mq?.removeEventListener ? mq.removeEventListener('change', sync) : mq?.removeListener(sync) } catch { /* noop */ }
  try { window.removeEventListener('resize', measure) } catch { /* noop */ }
})
</script>

<style scoped>
.ocs { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.ocs-list, .ocs-thread { display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; }

/* Two panes only when there is room for two. §DESKCHROME: the shell carries a
   measured viewport height in wide mode (see paneStyle), so each pane scrolls
   INTERNALLY — the list in its own column, the thread via its .ost-scroll with
   the composer pinned at the pane's bottom. */
.ocs-two { flex-direction: row; overflow: hidden; }
.ocs-two > .ocs-list {
  flex: 0 0 340px; max-width: 340px;
  border-right: 1px solid var(--border-color, rgba(128, 128, 128, .2));
  overflow-y: auto;
}
.ocs-two > .ocs-thread { flex: 1 1 auto; overflow: hidden; }
.ocs-two > .ocs-thread > :deep(.ost) { flex: 1; min-height: 0; }

/* V0653 (al): the folded list's rail (LIST_RAIL_PX): the way back to the list and its unread count, one hairline */
.ocs-two > .ocs-rail {
  flex: 0 0 56px; width: 56px; display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 10px 0;
  border-right: 1px solid var(--border-color, rgba(128, 128, 128, .2));
}
.ocs-rail-open {
  width: 44px; height: 44px; display: grid; place-items: center; cursor: pointer; color: inherit; background: none;
  border: 1px solid var(--nc-border, #2a2f3e); border-radius: 10px;
}
.ocs-rail-open :deep(svg) { width: 20px; height: 20px; }
.ocs-rail-unread {
  min-width: 22px; padding: 1px 6px; border-radius: 999px; text-align: center;
  background: var(--nc-primary, #00d4ff); color: #04121a;
  font: 600 .72rem/1.5 'IBM Plex Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums;
}

.ocs-bounded { height: calc(100vh - var(--ocs-offset, 0px)); height: calc(100dvh - var(--ocs-offset, 0px)); overflow: hidden; }
.ocs-bounded > .ocs-thread { overflow: hidden; }
.ocs-bounded > .ocs-thread > :deep(.ost) { flex: 1; min-height: 0; }

.ocs-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; opacity: .55; text-align: center; padding: 24px;
}
.ocs-empty :deep(svg) { width: 34px; height: 34px; opacity: .7; }
.ocs-empty-t { font-size: .95rem; font-weight: 600; margin: 4px 0 0; }
.ocs-empty-s { font-size: .8rem; margin: 0; max-width: 34ch; }
</style>
