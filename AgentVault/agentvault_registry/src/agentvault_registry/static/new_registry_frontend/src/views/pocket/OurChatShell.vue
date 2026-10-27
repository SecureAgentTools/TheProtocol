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
  <div ref="rootEl" class="ocs" :class="{ 'ocs-two': wide }" :style="paneStyle" data-testid="ocs-root">
    <section v-if="wide || !threadOpen" class="ocs-list" data-testid="ocs-list">
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
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import PocketOurState from '@/views/pocket/PocketOurState.vue'

const { t } = useI18n()
const route = useRoute()

/** A thread is open when the child route carries an id. */
const threadOpen = computed(() => !!route.params.id)

/* Width is read from the ELEMENT, not from a media query in JS, so the two
   never disagree about where the breakpoint is. matchMedia is the one source. */
const WIDE = '(min-width: 900px)'
const wide = ref(false)
let mq: MediaQueryList | null = null
const sync = () => { wide.value = !!mq?.matches; measure() }

/* §DESKCHROME (2026-08-28): in wide mode the SHELL is the height container, so
   the panes scroll internally and the composer never sinks below the fold. The
   offset is the shell's own MEASURED top — never an assumed chrome height
   (`--nc-header-h` is defined nowhere; PART 1 gotcha). Below the breakpoint the
   shell stays in document flow exactly as before (Pocket unchanged). */
const rootEl = ref<HTMLElement | null>(null)
const topPx = ref(0)
const measure = () => {
  try {
    if (rootEl.value) topPx.value = Math.max(0, Math.round(rootEl.value.getBoundingClientRect().top + (window.scrollY || 0)))
  } catch { /* noop */ }
}
const paneStyle = computed(() =>
  wide.value ? { height: `calc(100vh - ${topPx.value}px)` } : undefined)

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

.ocs-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; opacity: .55; text-align: center; padding: 24px;
}
.ocs-empty :deep(svg) { width: 34px; height: 34px; opacity: .7; }
.ocs-empty-t { font-size: .95rem; font-weight: 600; margin: 4px 0 0; }
.ocs-empty-s { font-size: .8rem; margin: 0; max-width: 34ch; }
</style>
