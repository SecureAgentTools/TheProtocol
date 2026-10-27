/**
 * §HIRECOHERE (2026-08-28) — ONE answer to "how can I hire this agent", for every surface.
 *
 * The doors used to be decided per-surface from whatever each one happened to know about the
 * card, and they disagreed. Worse, they were rendered INSIDE the proven-work section — the
 * modal wraps it in `v-show="admTrackRecordHas"` and Discovery's drawer only opens from a
 * band with `v-if="jobs > 0"` — so on frame-c the hire CTAs were invisible for 14,236 of
 * 14,260 agents. Receipts belong with the track record; DOORS do not depend on having been
 * hired before.
 *
 * The server decides (`GET /contracts/v2/engage-preview/{did}`) and this is the only place
 * the app asks. A door that cannot be opened carries a `reason` a person can read.
 */
import { ref, watch, type Ref } from 'vue'
import { contractsV2Api, type EngagePreview } from '@/services/api/contractsV2'

export function useEngageDoors(did: Ref<string | null | undefined>, enabled?: Ref<boolean>) {
  const doors = ref<EngagePreview['doors'] | null>(null)
  const draft = ref<any>(null)
  const homeRegistry = ref<string | null>(null)
  const loading = ref(false)

  async function load() {
    const d = did.value
    if (!d || (enabled && !enabled.value)) { doors.value = null; draft.value = null; return }
    loading.value = true
    try {
      const p = await contractsV2Api.engagePreview(d)
      doors.value = p?.doors || null
      draft.value = p?.draft || null
      homeRegistry.value = p?.home_registry ?? null
    } catch {
      // A preview that cannot be read must not invent an open door. Absent means the surface
      // offers only what needs no card support (Guild), never a button that would 404 later.
      doors.value = null; draft.value = null; homeRegistry.value = null
    } finally {
      loading.value = false
    }
  }

  // A route/prop change to a DIFFERENT agent must re-ask — the §ORGJOIN lesson (a param
  // change does not re-run onMounted, and a stale answer here names the wrong registry).
  watch(did, load, { immediate: true })
  if (enabled) watch(enabled, load)

  return { doors, draft, homeRegistry, loading, reload: load }
}
