/**
 * paneHost.ts — §ONBOARDQOL P7 (2026-09-02) — THE one memoised pane factory.
 *
 * Extracted verbatim from `views/CockpitDesk.vue` so a second host (the dashboard's
 * `DeskArea`) cannot grow its own copy. The memo is not an optimisation, it is the
 * feature: a factory called from a template runs on EVERY render, `<component :is>`
 * compares by identity, and a fresh `defineAsyncComponent()` per render tears every
 * pane down and rebuilds it. MEASURED on the desk (§COCKPITFRAME, 2026-09-01): one
 * CSS-only toggle took heartbeat's rows 13 → 0 and issued 15 API reads. Memoised, the
 * same toggle is 13 → 13 and 2 reads.
 *
 * Module-level on purpose: the map outlives any one host, so a pane opened on the
 * dashboard and later on the desk is the SAME component object in both places.
 */
import { defineAsyncComponent, type Component } from 'vue'
import { PANES, type PaneId } from '@/components/cockpit/paneRegistry'

const asyncPanes = new Map<PaneId, Component>()

export function componentFor(id: PaneId): Component {
  let c = asyncPanes.get(id)
  if (!c) { c = defineAsyncComponent(PANES[id].loader); asyncPanes.set(id, c) }
  return c
}
