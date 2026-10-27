<!--
  DeskBoard.vue — §DASHARRANGE (2026-09-02) — THE board: a grid of pane slots, their
  arrange tools, the maximise control, the honest shell for a pane this registry cannot
  serve, and the memoised pane components. Extracted VERBATIM from `views/CockpitDesk.vue`
  so the dashboard's `DeskArea` renders the SAME board the desk renders — same testids,
  same classes, same CSS — instead of a second copy that drifts.

  What it owns: paint and hit-testing of the slots. What it does NOT own: the arrange
  state (the host passes `useDeskArrange()`'s object in), persistence (the host's), the
  agent/deployment door modals (one per host, mounted by the host), density and chrome
  preferences (the host decides; this board only wears them as data attributes).

  ⚠ EVERY `ckd-*` testid and class below is addressed by the five desk batteries
  (§COCKPITFRAME · §COCKPITTILES · §COCKPITPOLISH · §COCKPITA · the cockpit tour). They
  moved here byte-for-byte; a rename is a battery going red for a reason that is not a
  defect.
-->
<template>
  <main class="ckd-grid" :data-density="density" :data-chrome="chrome" data-testid="ckd-board">
    <!-- ⚠ The grid item is the SLOT, not the pane inside it, so `wide` on the
         pane was inert: a declared property that quietly does nothing is the
         class this project keeps finding. The span lives on the slot now. -->
    <div v-for="id in arrange.shown" :key="id" class="ckd-slot"
         :class="{ 'ckd-slot--wide': PANES[id].wide,
                   'ckd-slot--dragging': arrange.dragId === id,
                   'ckd-slot--over': arrange.dragOver === id,
                   'ckd-slot--max': arrange.maxId === id,
                   'ckd-slot--arranging': arrange.editing }"
         :style="{ gridRow: `span ${arrange.maxId === id ? 5 : arrange.rowsOf(id)}`, '--rows': arrange.rowsOf(id) }"
         :data-pane-id="id" :data-rows="arrange.rowsOf(id)"
         :draggable="arrange.editing && arrange.dragArmed === id"
         @dragstart="arrange.onDragStart(id, $event)" @dragend="arrange.endDrag"
         @dragover="arrange.onDragOver(id, $event)" @drop.prevent="arrange.onDrop(id)">

      <!-- 🔴 §COCKPITFRAME F2 — while ARRANGING, maximise joins the tools bar as one more
           `.ckd-mini`, in normal flow, where an overlap is not expressible. It stays
           absolute only when the tools bar does not exist. One control per corner per
           mode. ⚠ Both carry `data-testid="ckd-max"` and they are mutually exclusive. -->
      <button v-if="!arrange.editing" class="ckd-max" data-testid="ckd-max"
              :aria-pressed="arrange.maxId === id ? 'true' : 'false'"
              :title="arrange.maxId === id ? t('cockpit.layout.restore', 'Restore this pane') : t('cockpit.layout.maximise', 'Maximise this pane')"
              @click="arrange.toggleMax(id)">
        <Icon :icon="arrange.maxId === id ? 'mdi:arrow-collapse' : 'mdi:arrow-expand'" />
      </button>

      <div v-if="arrange.editing" class="ckd-slot-tools">
        <!-- The handle arms the drag; the arrows remain the keyboard path. -->
        <span class="ckd-mini ckd-grip" data-testid="ckd-grip"
              :title="t('cockpit.layout.drag', 'Drag to reorder')"
              @mousedown="arrange.armDrag(id)" @mouseup="arrange.endDrag"><Icon icon="mdi:drag" /></span>
        <button class="ckd-mini" data-testid="ckd-up" :title="t('cockpit.layout.up', 'Move up')" :aria-label="t('cockpit.layout.up', 'Move up')"
                @click="arrange.movePane(id, -1)"><Icon icon="mdi:arrow-up" /></button>
        <button class="ckd-mini" data-testid="ckd-down" :title="t('cockpit.layout.down', 'Move down')" :aria-label="t('cockpit.layout.down', 'Move down')"
                @click="arrange.movePane(id, 1)"><Icon icon="mdi:arrow-down" /></button>
        <button class="ckd-mini" data-testid="ckd-shorter" :disabled="arrange.rowsOf(id) <= MIN_ROWS"
                :title="t('cockpit.layout.shorter', 'Shorter')" :aria-label="t('cockpit.layout.shorter', 'Shorter')" @click="arrange.resizePane(id, -1)"><Icon icon="mdi:chevron-up" /></button>
        <span class="ckd-rows" data-testid="ckd-rows">{{ arrange.rowsOf(id) }}/{{ MAX_ROWS }}</span>
        <button class="ckd-mini" data-testid="ckd-taller" :disabled="arrange.rowsOf(id) >= MAX_ROWS"
                :title="t('cockpit.layout.taller', 'Taller')" :aria-label="t('cockpit.layout.taller', 'Taller')" @click="arrange.resizePane(id, 1)"><Icon icon="mdi:chevron-down" /></button>
        <button class="ckd-mini" data-testid="ckd-max"
                :aria-pressed="arrange.maxId === id ? 'true' : 'false'"
                :title="arrange.maxId === id ? t('cockpit.layout.restore', 'Restore this pane') : t('cockpit.layout.maximise', 'Maximise this pane')"
                @click="arrange.toggleMax(id)"><Icon :icon="arrange.maxId === id ? 'mdi:arrow-collapse' : 'mdi:arrow-expand'" /></button>
        <span class="ckd-slot-name">{{ t(PANES[id].titleKey, PANES[id].titleFallback) }}</span>
        <button class="ckd-mini ckd-mini--drop" data-testid="ckd-drop-pane"
                :title="t('cockpit.layout.remove', 'Remove from this layout')" :aria-label="t('cockpit.layout.remove', 'Remove from this layout')" @click="arrange.dropPane(id)"><Icon icon="mdi:close" /></button>
      </div>
      <!-- R2: a layout may name a pane this registry cannot serve. Say so; never drop it. -->
      <PaneShell v-if="!PANES[id].available(ctx)"
                 :title="t(PANES[id].titleKey, PANES[id].titleFallback)" :icon="PANES[id].icon"
                 :refresh-mode="PANES[id].refreshMode" unavailable
                 :unavailable-reason="PANES[id].unavailableReason" />
      <component v-else :is="componentFor(id)" />

    </div>

    <p v-if="!arrange.shown.length" class="ckd-nopanes" data-testid="ckd-no-panes">
      {{ emptyText || t('cockpit.layout.emptyLayout', 'This layout has no panes. Use Arrange to add some.') }}
    </p>
  </main>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import PaneShell from '@/components/cockpit/PaneShell.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES, MIN_ROWS, MAX_ROWS, type PaneContext } from '@/components/cockpit/paneRegistry'
import { componentFor } from '@/services/cockpit/paneHost'
import type { DeskArrange } from '@/composables/useDeskArrange'

withDefaults(defineProps<{
  arrange: DeskArrange
  ctx: PaneContext
  density?: 'cozy' | 'compact'
  chrome?: 'on' | 'off'
  emptyText?: string
}>(), { density: 'cozy', chrome: 'on', emptyText: '' })

const { t } = useI18n()
</script>

<style scoped>
/* §COCKPITTILES T1 — a fixed row unit; every tile is a multiple of one unit, and
   `align-items: stretch` is SAFE in a fixed track (an item only fills the height its own
   pane asked for). `dense` back-fills the holes a 2-row tile beside a 3-row one leaves;
   the cost is honest and small — Arrange still moves panes in the order the layout stores,
   and that order is what is saved, so what you drag is what you get back. */
.ckd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            grid-auto-rows: 11rem; gap: .7rem; align-items: stretch; grid-auto-flow: row dense; }
/* §COCKPITFRAME F4 — the slot decides the height; a `min-height` on the pane inside it is a
   second, disagreeing opinion about height and paints over the tile below (+44px, measured). */
.ckd-slot :deep(.ckd-pane) { height: 100%; max-height: none; min-height: 0; }
/* §COCKPITPOLISH P6 — an empty pane is one row and never wide. Guarded by @supports: a browser
   without `:has()` keeps today's behaviour; a layout nicety must never break the board. */
@supports selector(:has(*)) {
  .ckd-slot--wide:has([data-empty="1"]) { grid-column: span 1; }
  .ckd-slot:has([data-empty="1"]) { grid-row: span 1 !important; }
}
.ckd-slot { position: relative; display: flex; flex-direction: column; --ckd-corner-clear: 1.75rem; }
/* §COCKPITDESK (2026-10-14): the corner control below sits over the pane's head, and the head's freshness chip (a button
   on a pane that can read again) ended under it. The head keeps its right edge clear of the control (PaneShell reads
   `--ckd-corner-clear`); while arranging the control lives in the tools bar, in flow, and the head needs no room. */
.ckd-slot--arranging { --ckd-corner-clear: 0px; }
.ckd-slot--wide { grid-column: span 2; }
.ckd-slot--dragging { opacity: .45; }
.ckd-slot--max { grid-column: 1 / -1 !important; }
/* Quiet at .3, forward on hover or keyboard focus; `z-index: 40` clears the pane header
   (`position: relative; z-index: 30`) — the probe asks elementFromPoint, not the eye. */
.ckd-max { position: absolute; top: .15rem; right: .15rem; z-index: 40; opacity: .3;
  background: var(--nc-surface-2, #1c2128); border: 1px solid var(--nc-border, #30363d);
  color: var(--nc-text-dim, #8b949e); border-radius: 4px; padding: .1rem .22rem;
  cursor: pointer; font-size: .7rem; line-height: 1; transition: opacity .12s ease; }
.ckd-slot:hover .ckd-max, .ckd-slot:focus-within .ckd-max, .ckd-max:focus-visible { opacity: 1; }
.ckd-max[aria-pressed="true"] { opacity: 1; color: var(--nc-primary, #58a6ff); }
/* §COCKPITFRAME F6 — frameless: paint only. It is also the cheapest proof of F1: a pane not
   on PaneShell has no `.ckd-pane` root and visibly keeps its frame. Empty tiles keep a faint
   outline so a hole reads as a pane with nothing to say. */
.ckd-grid[data-chrome="off"] :deep(.ckd-pane) { background: transparent; border-color: transparent; }
.ckd-grid[data-chrome="off"] :deep(.ckd-pane-head) { background: transparent; border-bottom-color: transparent; }
.ckd-grid[data-chrome="off"] :deep(.ckd-pane[data-empty="1"]) { border-color: var(--nc-border-subtle, rgba(255,255,255,.07)); }
/* §COCKPITTILES T4 — compact: a smaller row unit, tighter pane padding. */
.ckd-grid[data-density="compact"] { grid-auto-rows: 8.5rem; gap: .5rem; }
.ckd-grid[data-density="compact"] :deep(.ckd-pane-body) { padding: .45rem .5rem; }
.ckd-grid[data-density="compact"] :deep(.ckd-pane-head) { padding: .3rem max(.5rem, var(--ckd-corner-clear, 0px)) .3rem .5rem; }
.ckd-slot--over { outline: 2px dashed var(--nc-primary, #58a6ff); outline-offset: 2px; border-radius: 10px; }
.ckd-grip { cursor: grab; }
.ckd-grip:active { cursor: grabbing; }
.ckd-rows { font-size: .6rem; color: var(--nc-text-dim, #8b949e); font-variant-numeric: tabular-nums; min-width: 1.7rem; text-align: center; }
@media (max-width: 900px) { .ckd-slot--wide { grid-column: span 1; } }
/* §COCKPITDESK (2026-10-14) — ON A PHONE THE CONTENT DECIDES THE HEIGHT. Lifecycle 98's photograph at a Pixel's width:
   one column of fixed row units, every empty pane keeping its two rows, the Triage board 6,600 px tall for eleven panes.
   Below 640 px a tile is as tall as what it holds, up to the height the person gave it in Arrange (--rows units), and
   scrolls inside past that; the desktop's fixed tracks are untouched. */
@media (max-width: 640px) {
  .ckd-grid { grid-template-columns: minmax(0, 1fr); grid-auto-rows: auto; }
  .ckd-slot { grid-row: auto !important; }
  .ckd-slot :deep(.ckd-pane) { height: auto; min-height: 0; max-height: calc(var(--rows, 2) * 11rem); }
  .ckd-grid[data-density="compact"] .ckd-slot :deep(.ckd-pane) { max-height: calc(var(--rows, 2) * 8.5rem); }
}
.ckd-slot > :last-child { flex: 1; }
/* §COCKPITPOLISH — the tools occupy their OWN strip above the pane: no overlap, no hit-test
   ambiguity, and room to name which pane the buttons act on. */
.ckd-slot-tools {
  display: flex; align-items: center; gap: .2rem; padding: .2rem .3rem .3rem;
}
.ckd-slot-name {
  flex: 1; font-size: .62rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--nc-text-muted, #6e7681); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-mini { cursor: pointer; border-radius: 4px; padding: .1rem; line-height: 0; border: 1px solid var(--nc-border, rgba(255,255,255,.14)); background: var(--nc-deep, #010409); color: var(--nc-text-dim, #8b949e); }
.ckd-mini :deep(svg) { width: 12px; height: 12px; }
.ckd-mini--drop:hover { color: var(--nc-danger, #f85149); border-color: rgba(248,81,73,.5); }
.ckd-nopanes { grid-column: 1 / -1; margin: 0; padding: 2rem 0; text-align: center; font-size: .78rem; color: var(--nc-text-dim, #8b949e); }
</style>
