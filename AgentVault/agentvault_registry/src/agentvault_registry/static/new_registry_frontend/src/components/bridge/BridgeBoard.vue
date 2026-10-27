<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeBoard.vue — §LITEBRIDGE (2026-08-21)
 *
 * What the stage says, without a GPU.
 *
 * The starmap encodes three facts spatially — which registries exist, which of
 * them your agents live on, and where traffic is moving. None of those needs
 * WebGL; the 3D view is the beautiful way to read them, not the only one.
 *
 * And on one point this board is strictly BETTER than the stage: the stage is
 * bounded to 240 stars because geometry is not free, so on a fleet of 5,884 it
 * is showing you 4% of it. These numbers are exact. The board says so, rather
 * than letting you assume the prettier view was the more accurate one.
 *
 * COST, deliberately: no canvas, no WebGL, no requestAnimationFrame, no
 * backdrop-filter, no per-frame work of any kind. One row per registry, and a
 * `live` dot that changes at most once a second from a counter that is already
 * ticking for the pulse strip. That is the whole budget.
 */
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import { boardRows, boardSummary, quietLabel, filterByWindow, type BoardIndex, type BoardRegistry } from '@/services/bridge/board'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  registries?: BoardRegistry[]
  /** registry key -> agents you own there. EXACT. */
  mineByKey?: Record<string, number>
  index: BoardIndex
  /** Bumped by the parent's 1s tick; the index is a plain Map and cannot be reactive. */
  tick?: number
  /** Which registry the rails are currently scoped to, if any. */
  focusKey?: string | null
  /** Why this view is being shown at all — stated, never implied. */
  reason?: string
  automatic?: boolean
  /** The ACTIVE window from the doors row. On the stage it decides which STARS
   *  are drawn; with no stage it decides which REGISTRIES are listed, so the
   *  control does the same job rather than sitting there dead. */
  windowMs?: number | null
}>(), { registries: () => [], mineByKey: () => ({}), tick: 0, focusKey: null, reason: '', automatic: false, windowMs: null })

const emit = defineEmits<{ (e: 'focus', key: string | null): void }>()

const allRows = computed(() => {
  void props.tick
  return boardRows(props.registries || [], props.mineByKey || {}, props.index, Date.now())
})
const rows = computed(() => filterByWindow(allRows.value, props.windowMs ?? null, props.focusKey))
const hiddenByWindow = computed(() => allRows.value.length - rows.value.length)
const summary = computed(() => {
  void props.tick
  return boardSummary(rows.value, Date.now(), props.index?.since, hiddenByWindow.value)
})
const totalMine = computed(() => rows.value.reduce((n, r) => n + r.mine, 0))

/*
 * RESPONSIVE BY CONTAINER, NOT BY WINDOW.
 *
 * With both rails open at 1100px the centre column is 240px wide — measured,
 * not guessed. Five columns do not fit in 240px, and `table-layout: fixed`
 * dutifully squeezed REGISTRY to SEVEN pixels: every name gone, the header gone,
 * a column of empty cells. That is worse than the horizontal scrollbar it
 * replaced.
 *
 * So drop columns instead of crushing them, and measure the BOARD rather than
 * the viewport — the same window is roomy with a rail collapsed and cramped
 * with both open, and only the element knows which it is.
 */
const rootEl = ref<HTMLElement | null>(null)
const boardW = ref(9999)
let ro: ResizeObserver | null = null
onMounted(() => {
  if (!rootEl.value || typeof ResizeObserver === 'undefined') return
  ro = new ResizeObserver(es => { for (const e of es) boardW.value = Math.round(e.contentRect.width) })
  ro.observe(rootEl.value)
  boardW.value = Math.round(rootEl.value.getBoundingClientRect().width)
})
onBeforeUnmount(() => { ro?.disconnect(); ro = null })
/** EVENTS is the first to go: the live dot and LAST already say "is it moving". */
const showEvents = computed(() => boardW.value >= 360)
/** Then LAST. What must never go is WHICH registry and HOW MANY are yours. */
const showLast = computed(() => boardW.value >= 290)
const showChips = computed(() => boardW.value >= 250)

function onRow(key: string) {
  emit('focus', props.focusKey === key ? null : key)
}
</script>

<template>
  <section ref="rootEl" class="bbd" data-tour="bridge-board" data-testid="bridge-board" aria-label="Fleet board">
    <header class="bbd-hd">
      <span class="bbd-title">{{ t('bridge.board.title', 'FLEET BOARD') }}</span>
      <span class="bbd-sum" data-tour="bridge-board-summary" data-testid="board-summary">{{ summary }}</span>
    </header>

    <!-- Why you are looking at this and not the stage. A view that quietly
         swaps itself for a lesser one is a view you cannot trust. -->
    <p v-if="reason" class="bbd-why" data-tour="bridge-board-why" data-testid="board-why">
      <Icon :name="automatic ? 'mdi:information-outline' : 'mdi:check-circle-outline'" :size="11" />
      <span>{{ reason }}</span>
    </p>

    <div v-if="!rows.length" class="bbd-empty" data-testid="board-empty">
      {{ hiddenByWindow
        ? t('bridge.board.emptyWindow', 'Nothing has moved in this window. Widen it, or turn the ACTIVE filter off, to see every registry again.')
        : t('bridge.board.empty', 'No registries known yet. The topology step of the boot sequence fills this in.') }}
    </div>

    <!-- Explicit roles, deliberately: `.bbd-tbl { display: block }` is what
         makes this scroll, and changing a table's display to block STRIPS its
         implicit table/row/cell roles in every major engine. Without these it
         is announced as a pile of text, and `aria-pressed` on a <tr> means
         nothing at all — a toggle state on an element with no widget role. -->
    <!-- The scroll belongs to a WRAPPER, not the table. With `display: block` on
         the table itself the column algorithm stops running, so at 1100px the
         name column ate the width and EVENTS and LAST fell off the right edge
         behind a horizontal scrollbar nobody would think to use. The numbers
         are the point of this board; the name is the part that can truncate. -->
    <div v-else class="bbd-scroll" data-tour="bridge-board-rows">
    <table class="bbd-tbl" role="grid" :aria-rowcount="rows.length">
      <thead role="rowgroup">
        <tr role="row">
          <th class="bbd-th bbd-th--live" role="columnheader"><span class="sr-only">Live</span></th>
          <th class="bbd-th bbd-th--reg" role="columnheader">{{ t('bridge.board.registry', 'REGISTRY') }}</th>
          <th class="bbd-th bbd-th--n bbd-th--yours" role="columnheader">{{ t('bridge.board.yours', 'YOUR AGENTS') }}</th>
          <th v-if="showEvents" class="bbd-th bbd-th--n bbd-th--events" role="columnheader">{{ t('bridge.board.seen', 'EVENTS') }}</th>
          <th v-if="showLast" class="bbd-th bbd-th--n bbd-th--last" role="columnheader">{{ t('bridge.board.last', 'LAST') }}</th>
        </tr>
      </thead>
      <tbody role="rowgroup">
        <tr v-for="r in rows" :key="r.key"
            class="bbd-row"
            :class="{ 'is-focus': focusKey === r.key, 'is-home': r.local, 'is-empty': !r.mine }"
            :data-testid="`board-row-${r.key}`"
            role="row"
            tabindex="0"
            :aria-selected="focusKey === r.key"
            :aria-label="`${r.name || r.key}: ${r.mine.toLocaleString(appLocale())} of your agents, ${r.seen.toLocaleString(appLocale())} events this session`"
            :title="focusKey === r.key
              ? t('bridge.board.clearHelp', 'Show the whole fleet again')
              : t('bridge.board.focusHelp', 'Narrow the fleet log and the ledger to the agents you own here')"
            @click="onRow(r.key)"
            @keydown.enter.prevent="onRow(r.key)"
            @keydown.space.prevent="onRow(r.key)">
          <td role="gridcell" class="bbd-td bbd-td--live">
            <span class="bbd-dot" :class="{ 'is-live': r.live }" aria-hidden="true"></span>
          </td>
          <td role="gridcell" class="bbd-td bbd-td--name">
            <span class="bbd-name">{{ r.name || r.key }}</span>
            <span v-if="r.local" class="bbd-chip bbd-chip--home">{{ t('bridge.board.home', 'HOME') }}</span>
            <span v-if="r.frame && showChips" class="bbd-chip">{{ r.frame }}</span>
            <span v-if="r.currency && showChips" class="bbd-chip bbd-chip--cur">{{ r.currency }}</span>
          </td>
          <td role="gridcell" class="bbd-td bbd-td--n">
            <span :class="{ 'bbd-zero': !r.mine }">{{ r.mine.toLocaleString(appLocale()) }}</span>
          </td>
          <td v-if="showEvents" role="gridcell" class="bbd-td bbd-td--n">
            <span :class="{ 'bbd-zero': !r.seen }">{{ r.seen.toLocaleString(appLocale()) }}</span>
          </td>
          <td v-if="showLast" role="gridcell" class="bbd-td bbd-td--n bbd-quiet">{{ quietLabel(r.quietMs) }}</td>
        </tr>
      </tbody>
    </table>
    </div>

    <footer class="bbd-ft" data-tour="bridge-board-foot">
      <span v-if="focusKey" class="bbd-focusnote" data-testid="board-focus-note">
        {{ t('bridge.board.focused', 'Rails narrowed to this registry.') }}
        <button type="button" class="bbd-clear" data-testid="board-focus-clear" @click="emit('focus', null)">
          {{ t('bridge.board.clear', 'SHOW ALL') }}
        </button>
      </span>
      <span v-else class="bbd-hint">
        {{ totalMine
          ? t('bridge.board.hint', 'Click a registry to narrow the fleet log and the ledger to it.')
          : t('bridge.board.hintNone', 'Once you own agents somewhere, this counts them exactly.') }}
      </span>
    </footer>
  </section>
</template>

<style scoped>
/* No blur, no filter, no shadow that forces a repaint layer: this view exists
   because the machine could not afford those. */
.bbd {
  pointer-events: auto;
  display: flex; flex-direction: column; min-height: 0;
  max-height: 100%;
  background: rgba(8, 12, 22, 0.9);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.16));
  border-radius: 4px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  overflow: hidden;
}
.bbd-hd {
  display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap;
  padding: 0.5rem 0.7rem 0.35rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.12));
}
.bbd-title { font-size: 0.56rem; letter-spacing: 0.16em; color: var(--nc-primary, #22d3ee); font-weight: 700; }
.bbd-sum { font-size: 0.55rem; color: var(--nc-text-dim, #6b7f9e); }
.bbd-why {
  display: flex; align-items: center; gap: 0.35rem;
  margin: 0; padding: 0.35rem 0.7rem;
  font-size: 0.55rem; line-height: 1.5; color: var(--nc-text-dim, #8fa2ba);
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.1));
}
.bbd-empty { padding: 1rem 0.7rem; font-size: 0.6rem; color: var(--nc-text-dim, #6b7f9e); }
/* `flex: 1 1 auto; min-height: 0` is what actually makes this scroll: without
   the min-height a flex item refuses to shrink below its content and the whole
   board grows instead. */
.bbd-scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; }
/* FIXED layout so the three number columns always get their width and the
   registry name is what gives way. */
.bbd-tbl { width: 100%; border-collapse: collapse; table-layout: fixed; }
.bbd-th--reg { width: auto; min-width: 6rem; }
.bbd-th--yours { width: 5.6rem; }
.bbd-th--events { width: 4.6rem; }
.bbd-th--last { width: 3.2rem; }
.bbd-th {
  position: sticky; top: 0; z-index: 1;
  text-align: left; padding: 0.3rem 0.6rem;
  font-size: 0.48rem; letter-spacing: 0.12em; font-weight: 600;
  color: var(--nc-text-dim, #6b7f9e);
  background: rgba(8, 12, 22, 0.96);
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.12));
}
.bbd-th--n { text-align: right; }
.bbd-th--live { width: 14px; }
.bbd-row { cursor: pointer; border-bottom: 1px solid rgba(120, 160, 210, 0.06); }
.bbd-row:hover, .bbd-row:focus-visible { background: rgba(34, 211, 238, 0.06); outline: none; }
.bbd-row.is-focus { background: rgba(34, 211, 238, 0.1); box-shadow: inset 2px 0 0 var(--nc-primary, #22d3ee); }
.bbd-row.is-empty .bbd-name { color: var(--nc-text-dim, #6b7f9e); }
.bbd-td { padding: 0.3rem 0.6rem; font-size: 0.6rem; color: var(--nc-text, #d6e2f2); vertical-align: middle; }
.bbd-td--n { text-align: right; font-variant-numeric: tabular-nums; }
.bbd-td--live { width: 14px; padding-right: 0; }
/* One line per registry. Wrapping the chips made rows 26px -> 62px at 1100px
   wide, which is both ugly and how the board outgrew its column. The table
   already scrolls horizontally if a name is genuinely too long. */
.bbd-td--name { display: flex; align-items: center; gap: 0.3rem; flex-wrap: nowrap; white-space: nowrap; min-width: 0; overflow: hidden; }
.bbd-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.bbd-chip { flex: 0 0 auto; }
.bbd-zero { color: var(--nc-text-dim, #55677f); }
.bbd-quiet { color: var(--nc-text-dim, #6b7f9e); font-size: 0.55rem; }
.bbd-dot {
  display: inline-block; width: 5px; height: 5px; border-radius: 50%;
  background: var(--nc-text-dim, #3d4a5c);
}
.bbd-dot.is-live { background: var(--nc-primary, #22d3ee); }
.bbd-chip {
  font-size: 0.44rem; letter-spacing: 0.1em; padding: 0 0.22rem;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  border-radius: 2px; color: var(--nc-text-dim, #8fa2ba);
}
.bbd-chip--home { color: var(--nc-primary, #22d3ee); border-color: rgba(34, 211, 238, 0.4); }
.bbd-chip--cur { color: var(--nc-accent, #f5c451); border-color: rgba(245, 196, 81, 0.3); }
.bbd-ft {
  padding: 0.35rem 0.7rem; border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.12));
  font-size: 0.52rem; color: var(--nc-text-dim, #6b7f9e);
}
.bbd-clear {
  background: none; border: 1px solid var(--nc-border, rgba(120,160,210,.25));
  color: var(--nc-primary, #22d3ee); border-radius: 2px;
  font-size: 0.48rem; letter-spacing: 0.1em; padding: 0 0.3rem; margin-left: 0.35rem; cursor: pointer;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}
</style>
