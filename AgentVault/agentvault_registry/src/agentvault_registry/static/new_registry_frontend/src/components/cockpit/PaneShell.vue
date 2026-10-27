<script setup lang="ts">
/**
 * §COCKPIT P1 (2026-08-31) — the frame every desk pane lives in.
 *
 * Three laws it exists to hold:
 *  1. §DISCREFINE — a pane with nothing to say SAYS SO. It never auto-hides.
 *     An empty tile that vanishes is indistinguishable from a tile that failed,
 *     and both are indistinguishable from a feature that was never built.
 *  2. R2 — a pane a registry cannot serve renders as UNAVAILABLE with a reason,
 *     not as a blank, and not by being dropped from the layout the user saved.
 *  3. Freshness is part of the number. Every pane states how it refreshes
 *     (LIVE / POLL Ns / ONCE), because a figure with no stated freshness is one
 *     you cannot act on.
 *  4. §COCKPITDESK (2026-10-14) — A FAILED RE-READ IS NOT THE END OF THE LAST ANSWER. A pane that
 *     passes `readAt` (when its source last answered) keeps what it shows when a later read fails,
 *     and says so above it: the time of the figures and why the newest read failed, with Try
 *     again. Before, one failed poll (a roll's restart, one 502) swapped every pane's figures for
 *     "could not read its source" until the next poll, 60 to 180 s later, with no way to ask
 *     again. A pane that never read keeps the error state, now with Try again where it hands the
 *     shell its `reload`; the freshness chip of such a pane reads again on a press.
 *
 * ⚠ No `backdrop-filter` anywhere in this file or its children: §BRIDGE P2 and
 * §TICKERLAG both cost a day to a blur sitting over something that repaints.
 */
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import type { RefreshMode } from './paneRegistry'
import { appLocale } from '@/services/appLocale'
import { deskRefreshTick } from '@/services/cockpit/deskRefresh'

const props = defineProps<{
  title: string
  icon: string
  refreshMode: RefreshMode
  pollSeconds?: number
  loading?: boolean
  /** Non-empty ⇒ the pane renders its error state (siblings keep living). */
  error?: string
  /** True ⇒ the source answered, and the honest answer is "nothing". */
  empty?: boolean
  emptyText?: string
  /** §PANEDOORS (2026-09-02) — a door out of the empty state ("Create your first agent"),
   *  rendered by the shell so every pane's door looks and hit-tests the same. */
  emptyActionLabel?: string
  /** §COCKPITBOOK — opt OUT of the 30rem cap, for a pane whose whole point is a large
   *  readable surface (an analytics board with a chart). Deliberately per-pane and not a
   *  free-for-all: the cap exists because ONE tall pane stretched its whole row into two
   *  empty boxes (§COCKPITFIT), and a board where every pane opts out is that bug again. */
  tall?: boolean
  /** R2: the pane is not serveable on this registry. */
  unavailable?: boolean
  unavailableReason?: string
  wide?: boolean
  /**
   * §COCKPITFRAME F1 — the CONTENT owns its scroll; the body must not add a second one.
   *
   * For one pane only so far: `PaneLedger` nests `BridgeLedger`, which scrolls its own
   * list. Its own file has carried the warning since §MINELEDGER — *"giving this wrapper a
   * height of its own is how a nested scroller ends up with two scrollbars"* — written at a
   * time when nothing owned the frame at all. Now that the shell does, the shell has to be
   * told, or the reader gets two bars and neither reaches the end.
   */
  innerScroll?: boolean
  /** §COCKPITDESK — when the pane's source last answered (epoch ms); null until it has. With an `error`
   *  after it, the pane keeps what it shows and says the newest read failed (law 4). */
  readAt?: number | null
  /** §COCKPITDESK — the pane's own read, for Try again and the chip. AWAITED: the door says "Reading…" until
   *  it settles, whatever it answers (an event could not tell the shell a retry failed with the same words). */
  reload?: () => unknown
}>()
const emit = defineEmits<{ (e: 'empty-action'): void }>()

const { t, tp } = useI18n()

const canRetry = computed(() => typeof props.reload === 'function')
const everRead = computed(() => typeof props.readAt === 'number')
/** A newest read failed after one that answered: the figures stay, marked with their time. */
const stale = computed(() => !!props.error && everRead.value)
const readAtText = computed(() => everRead.value
  ? new Date(props.readAt as number).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  : '')
/** Pressed once, the door says it is reading until the pane's read settles, whatever it answers. */
const retrying = ref(false)
async function retry() {
  if (!canRetry.value || retrying.value) return
  retrying.value = true
  try { await props.reload?.() } catch { /* the pane's own read records its failure */ } finally { retrying.value = false }
}
/** The host's "Refresh": every frame that can reload reads again (one that is already reading is left alone). */
watch(deskRefreshTick, () => { void retry() })
const freshTitle = computed(() => {
  const policy = props.refreshMode === 'live' ? t('cockpit.fresh.liveHint', 'Pushed as it happens')
    : props.refreshMode === 'once' ? t('cockpit.fresh.onceHint', 'Read when the pane opened')
    : tp('cockpit.fresh.pollHint', 'Read again every {n} s', { n: props.pollSeconds ?? 60 })
  const when = everRead.value ? ' · ' + tp('cockpit.fresh.readAt', 'last answered at {time}', { time: readAtText.value }) : ''
  const press = canRetry.value && props.refreshMode !== 'live' ? ' · ' + t('cockpit.fresh.readNow', 'press to read now') : ''
  return policy + when + press
})

const freshness = computed(() => {
  if (props.refreshMode === 'live') return t('cockpit.fresh.live', 'LIVE')
  if (props.refreshMode === 'once') return t('cockpit.fresh.once', 'AT OPEN')
  return `${props.pollSeconds ?? 60}s`
})
</script>

<template>
  <!-- §COCKPITPOLISH P6 — `data-empty` is published so the enclosing GRID SLOT can stop
       spending two columns on a pane with nothing in it. The pane cannot resize its own
       slot (the slot is the grid item, not the pane — the same confusion that made `wide`
       inert until P1 moved it), so the honest mechanism is: the pane states a fact, the
       desk's stylesheet decides the layout. -->
  <section class="ckd-pane" :class="{ 'ckd-pane--wide': wide, 'ckd-pane--tall': tall }" :data-pane-title="title"
           :data-empty="(empty || unavailable) ? '1' : '0'">
    <header class="ckd-pane-head">
      <Icon :icon="icon" class="ckd-pane-icon" />
      <h3 class="ckd-pane-title">{{ title }}</h3>
      <!-- §COCKPITDESK — a polling pane that listens for `retry` reads again when its chip is pressed; the title says when
           its source last answered. A LIVE pane has nothing to ask for: it is pushed. -->
      <button v-if="canRetry && refreshMode !== 'live'" type="button"
              class="ckd-fresh is-button" :class="[`ckd-fresh--${refreshMode}`, { 'is-stale': stale }]"
              data-testid="ckd-fresh" :title="freshTitle" :aria-label="freshTitle" :aria-busy="retrying ? 'true' : undefined"
              @click="retry">{{ freshness }}</button>
      <span v-else class="ckd-fresh" :class="[`ckd-fresh--${refreshMode}`, { 'is-stale': stale }]"
            data-testid="ckd-fresh" :title="freshTitle">{{ freshness }}</span>
    </header>

    <!-- §FESUITE (2026-10-10, axe on the everything-on sandbox's /desk): the body is the pane's scroller, and a scroller
         with nothing focusable inside cannot be scrolled from the keyboard. It is a named stop of its own; a pane that
         scrolls inside (innerScroll) leaves that to the component that owns the scroll. -->
    <div class="ckd-pane-body" :class="{ 'ckd-pane-body--inner': innerScroll }"
         :tabindex="innerScroll ? undefined : 0" :role="innerScroll ? undefined : 'region'"
         :aria-label="innerScroll ? undefined : title">
      <!-- R2: cannot exist here, and says which registry fact makes that so -->
      <div v-if="unavailable" class="ckd-state ckd-state--unavailable" data-testid="ckd-unavailable">
        <Icon icon="mdi:cancel" class="ckd-state-icon" />
        <p class="ckd-state-title">{{ t('cockpit.state.unavailable', 'Not available on this registry') }}</p>
        <p class="ckd-state-sub">{{ unavailableReason || t('cockpit.state.unavailableSub', 'This deployment does not serve the data this pane reads.') }}</p>
      </div>

      <div v-else-if="loading" class="ckd-state ckd-state--loading" data-testid="ckd-loading">
        <span class="ckd-spinner" aria-hidden="true" />
        <p class="ckd-state-sub">{{ t('cockpit.state.loading', 'Reading…') }}</p>
      </div>

      <!-- An error in ONE pane must never take the desk down with it. Only a pane that never read lands here: one that
           did keeps its figures below the stale line (law 4). -->
      <div v-else-if="error && !everRead" class="ckd-state ckd-state--error" data-testid="ckd-error">
        <Icon icon="mdi:alert-circle-outline" class="ckd-state-icon" />
        <p class="ckd-state-title">{{ t('cockpit.state.error', 'This pane could not read its source') }}</p>
        <p class="ckd-state-sub">{{ error }}</p>
        <button v-if="canRetry" type="button" class="ckd-state-door" data-testid="ckd-retry" :disabled="retrying"
                @click="retry">{{ retrying ? t('cockpit.state.loading', 'Reading…') : t('common.readFailed.retry', 'Try again') }}</button>
      </div>

      <template v-else>
        <div v-if="stale" class="ckd-stale" data-testid="ckd-stale" role="status">
          <Icon icon="mdi:alert-circle-outline" class="ckd-stale-icon" />
          <span class="ckd-stale-text">{{ tp('cockpit.state.stale', 'As of {time}: the newest read failed ({reason}).', { time: readAtText, reason: error }) }}</span>
          <button v-if="canRetry" type="button" class="ckd-stale-retry" data-testid="ckd-retry" :disabled="retrying"
                  @click="retry">{{ retrying ? t('cockpit.state.loading', 'Reading…') : t('common.readFailed.retry', 'Try again') }}</button>
        </div>

        <div v-if="empty" class="ckd-state ckd-state--empty" data-testid="ckd-empty">
          <Icon icon="mdi:check-circle-outline" class="ckd-state-icon" />
          <p class="ckd-state-sub">{{ emptyText || t('cockpit.state.empty', 'Nothing here right now.') }}</p>
          <button v-if="emptyActionLabel" type="button" class="ckd-state-door" data-testid="ckd-empty-action"
                  @click="emit('empty-action')">{{ emptyActionLabel }}</button>
        </div>

        <slot v-else />
      </template>
    </div>
  </section>
</template>

<style scoped>
.ckd-pane {
  display: flex; flex-direction: column; min-height: 180px; max-height: 30rem;
  background: var(--nc-surface, #0d1117);
  border: 1px solid var(--nc-border, rgba(255,255,255,0.08));
  border-radius: 10px; overflow: hidden;
}
/* The width decision lives on the SLOT (the grid item) in CockpitDesk.vue —
   this class stays only as a hook for a pane rendered outside a desk grid. */
.ckd-pane--wide { width: 100%; }
/* A board pane: a taller ceiling, still a ceiling. */
.ckd-pane--tall { max-height: 52rem; }

.ckd-pane-head {
  display: flex; align-items: center; gap: .5rem;
  /* a desk slot's corner control sits over this edge (DeskBoard sets the clearance) */
  padding: .55rem max(.75rem, var(--ckd-corner-clear, 0px)) .55rem .75rem;
  border-bottom: 1px solid var(--nc-border-subtle, rgba(255,255,255,0.06));
  background: rgba(var(--nc-primary-rgb, 0,229,255), 0.035);
}
.ckd-pane-icon { width: 15px; height: 15px; color: var(--nc-primary, #00e5ff); flex: 0 0 auto; }
.ckd-pane-title {
  flex: 1; margin: 0; font-size: .8rem; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; color: var(--nc-text-primary, #e6edf3);
}
.ckd-fresh {
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: .6rem; letter-spacing: .08em; padding: .1rem .35rem;
  border-radius: 4px; border: 1px solid var(--nc-border, rgba(255,255,255,0.1));
  color: var(--nc-text-dim, #8b949e);
}
.ckd-fresh--live { color: var(--nc-success, #3fb950); border-color: rgba(63,185,80,.35); }
.ckd-fresh.is-button { background: transparent; cursor: pointer; line-height: inherit; }
.ckd-fresh.is-button:hover, .ckd-fresh.is-button:focus-visible { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255), .5); }
.ckd-fresh.is-button[aria-busy="true"] { opacity: .6; cursor: progress; }
.ckd-fresh.is-stale { color: var(--nc-warning, #d29922); border-color: rgba(210,153,34,.45); }

.ckd-pane-body { flex: 1; padding: .65rem .75rem; overflow: auto; min-height: 0; }
.ckd-pane-body:focus-visible { outline: 2px solid var(--brand-primary, #4dd8e6); outline-offset: -2px; }
/* §COCKPITFRAME F1 — see `innerScroll`. `min-height: 0` above is what lets a flex child
   actually shrink to its allocation instead of growing to its content, which is the other
   half of "the tile decides the height". */
.ckd-pane-body--inner { overflow: hidden; display: flex; flex-direction: column; }

/* §COCKPITDESK (2026-10-14): an empty pane is one row on the desk, and the longest sentences (Denials' "a real zero")
   ran past it: the body scrolled and the board showed half a sentence. The state fills the body and centres its content
   with auto margins, which stop at zero when there is no room (plain centring would push the first line above the top,
   out of reach); the padding, gap and icon are smaller and the sentence wider, so it fits one row. */
.ckd-state {
  display: flex; flex-direction: column; align-items: center; justify-content: flex-start;
  gap: .25rem; padding: .4rem .5rem; text-align: center; min-height: 100%;
}
.ckd-state > :first-child { margin-top: auto; }
.ckd-state > :last-child { margin-bottom: auto; }
.ckd-state-icon { width: 18px; height: 18px; flex: 0 0 auto; color: var(--nc-text-muted, #6e7681); }
.ckd-state-title { margin: 0; font-size: .78rem; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-state-sub { margin: 0; font-size: .72rem; line-height: 1.4; color: var(--nc-text-dim, #8b949e); max-width: 50ch; }
.ckd-state--error .ckd-state-icon { color: var(--nc-danger, #f85149); }
.ckd-state--unavailable .ckd-state-icon { color: var(--nc-warning, #d29922); }

.ckd-spinner {
  width: 16px; height: 16px; border-radius: 50%;
  border: 2px solid var(--nc-border, rgba(255,255,255,.12));
  border-top-color: var(--nc-primary, #00e5ff);
  animation: ckd-spin .8s linear infinite;
}
@keyframes ckd-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .ckd-spinner { animation-duration: 2.4s; } }
.ckd-state-door { margin-top: .5rem; font-size: .68rem; letter-spacing: .04em; padding: .3rem .7rem; border-radius: 6px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), .5); background: transparent; color: var(--nc-primary, #00e5ff); }
.ckd-state-door:hover { background: rgba(var(--nc-primary-rgb, 0,229,255), .08); }
.ckd-state-door:disabled, .ckd-stale-retry:disabled { opacity: .55; cursor: progress; }
/* §COCKPITDESK — the stale line sits above the figures it qualifies, in the body's own flow. */
.ckd-stale { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; margin: 0 0 .45rem; padding: .25rem .45rem;
  border: 1px solid rgba(210,153,34,.35); border-radius: 6px; background: rgba(210,153,34,.06);
  font-size: .68rem; line-height: 1.3; color: var(--nc-warning, #d29922); }
.ckd-stale-icon { width: 13px; height: 13px; flex: 0 0 auto; }
.ckd-stale-text { flex: 1 1 12rem; min-width: 0; }
.ckd-stale-retry { font-size: .66rem; padding: .12rem .45rem; border-radius: 5px; cursor: pointer; background: transparent;
  border: 1px solid rgba(210,153,34,.5); color: var(--nc-warning, #d29922); }
.ckd-stale-retry:hover { background: rgba(210,153,34,.12); }
</style>
