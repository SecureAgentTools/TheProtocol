/**
 * §FRESHFRAME (2026-09-14) — ONE read of `/api/v1/public/showcase/agents` for the landing page's
 * sovereign roster gate. The decision itself is `rosterDecision()` in services/frameHost.ts (pure,
 * unit-tested); this composable only carries the answer. Module-cached: N callers, one request. A
 * failed read stays `unknown`, which renders NOTHING: for a demonstration, showing nothing beats
 * publishing another deployment's agents as this frame's.
 */
import { ref, computed } from 'vue'
import { rosterDecision, type RosterDecision } from '@/services/frameHost'

export interface ShowcaseRail { enabled?: boolean; agents?: unknown[]; count?: number; reason?: string }

const rail = ref<ShowcaseRail | null>(null)
let inflight: Promise<void> | null = null

export function loadShowcaseRoster(): Promise<void> {
  if (rail.value) return Promise.resolve()
  if (inflight) return inflight
  inflight = fetch(`${window.location.origin}/api/v1/public/showcase/agents`, { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : null))
    .then((d: ShowcaseRail | null) => { if (d && typeof d === 'object') rail.value = d })
    .catch(() => { /* stays unknown */ })
    .finally(() => { inflight = null })
  return inflight
}

export function useShowcaseRoster() {
  if (!rail.value && !inflight) void loadShowcaseRoster()
  return {
    rail: computed(() => rail.value),
    decision: computed<RosterDecision>(() => rosterDecision(rail.value)),
    load: loadShowcaseRoster,
  }
}

/** Test seam only. */
export const __showcaseRosterInternals = { reset(): void { rail.value = null; inflight = null } }
