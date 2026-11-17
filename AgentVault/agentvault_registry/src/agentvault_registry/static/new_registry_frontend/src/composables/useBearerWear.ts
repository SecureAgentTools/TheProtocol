// V0666 the Flare view reworked: wearing an earned item on the bearer the person chose. The developer's own routes serve the developer, the agent routes serve an agent;
// a press on what the bearer already wears takes it off; the registry's sentence answers a refusal where the press was made (the unlock row is its gate, a bought ring
// or corner on the agent asks to be taken off first); the page refreshes from the registry after every press, because one earned copy moves between bearers and the
// registry, not this screen, knows where it went. A title is the developer's only.
import { reactive, ref } from 'vue'
import { equipTitle, wearEarned, wearEarnedOnAgent, type TrackItem } from '@/services/api/contributorTrack'
import { refusalWords } from '@/services/api/codeChanges'
import { keyOf } from '@/services/contributorTrackView'
import type { Bearer } from '@/services/flareBearers'

export function useBearerWear(opts: { failedWords: string; refresh: () => Promise<void> }) {
  const busyKey = ref('')
  const errors = reactive<Record<string, string>>({})

  async function wear(i: TrackItem, bearer: Bearer, off: boolean): Promise<void> {
    if (i.kind === 'title' && bearer.kind !== 'developer') return          // an agent does not wear a title
    const k = keyOf(i)
    busyKey.value = k; errors[k] = ''
    try {
      if (i.kind === 'title') {
        const r = await equipTitle(off ? null : i.key)
        // the sidebar reads the title once at mount: tell it (a plain window event, no store between them)
        if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('ct:title', { detail: r?.title ?? null }))
      } else if (bearer.kind === 'developer') {
        await wearEarned(i.kind, off ? null : i.key)
      } else {
        await wearEarnedOnAgent(bearer.did as string, i.kind, off ? null : i.key)
      }
    } catch (e: any) {
      errors[k] = refusalWords(e, opts.failedWords)
    } finally {
      busyKey.value = ''
    }
    await opts.refresh()
  }
  /** The COMMANDER title is worn by default while no other title is chosen: taking the chosen title off returns to it (a rule of the code, nothing is stored). */
  async function takeOffTitle(): Promise<void> {
    busyKey.value = 'title:commander'; errors['title:commander'] = ''
    try {
      const r = await equipTitle(null)
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('ct:title', { detail: r?.title ?? null }))
    } catch (e: any) {
      errors['title:commander'] = refusalWords(e, opts.failedWords)
    } finally {
      busyKey.value = ''
    }
    await opts.refresh()
  }
  return { busyKey, errors, wear, takeOffTitle }
}
