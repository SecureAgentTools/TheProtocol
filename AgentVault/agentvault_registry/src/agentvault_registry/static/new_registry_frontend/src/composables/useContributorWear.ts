// V0665: wearing what the contributor track earned. One place for the worn state (ring, badge, title), the press that wears or takes off, and the registry's sentence for a
// refusal, shared by the Track tab and the flare manager. The registry decides (the unlock row is the gate): this only asks and shows the answer.
import { reactive, ref } from 'vue'
import { equipTitle, wearEarned, type TrackItem } from '@/services/api/contributorTrack'
import { refusalWords } from '@/services/api/codeChanges'
import { keyOf } from '@/services/contributorTrackView'
import { apiClient } from '@/services/api/client'

export function useContributorWear(failedWords: string) {
  const wornRing = ref<string | null>(null)
  const wornBadge = ref<string | null>(null)
  const wornTitle = ref<string | null>(null)
  const flareTier = ref<string | null>(null)
  const busyKey = ref('')
  const errors = reactive<Record<string, string>>({})

  const isWorn = (i: TrackItem) => (i.kind === 'title' ? wornTitle.value === i.key : i.kind === 'encirclement' ? wornRing.value === i.key : wornBadge.value === i.key)

  /** The ring and the badge being worn come from the flare status; a failed read leaves them unknown (nothing is shown as worn), never wrong. */
  async function readWorn(equippedTitle: string | null) {
    wornTitle.value = equippedTitle
    const flare = await apiClient.get('/fiat/flare/status').then((r) => r.data).catch(() => null)
    wornRing.value = flare?.flare_encirclement_variant ?? null
    wornBadge.value = flare?.flare_corner_variant ?? null
    flareTier.value = flare?.flare_tier ?? null
  }

  async function wear(i: TrackItem) {
    const k = keyOf(i)
    busyKey.value = k; errors[k] = ''
    try {
      const off = isWorn(i)
      if (i.kind === 'title') {
        wornTitle.value = (await equipTitle(off ? null : i.key)).title ?? null
        // the sidebar reads the title once at mount: tell it (a plain window event, no store between them)
        if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('ct:title', { detail: wornTitle.value }))
      }
      else {
        const r = await wearEarned(i.kind, off ? null : i.key)
        if (i.kind === 'encirclement') wornRing.value = r?.flare_encirclement_variant ?? null; else wornBadge.value = r?.flare_corner_variant ?? null
      }
    } catch (e: any) { errors[k] = refusalWords(e, failedWords) } finally { busyKey.value = '' }
  }
  return { wornRing, wornBadge, wornTitle, flareTier, busyKey, errors, isWorn, readWorn, wear }
}
