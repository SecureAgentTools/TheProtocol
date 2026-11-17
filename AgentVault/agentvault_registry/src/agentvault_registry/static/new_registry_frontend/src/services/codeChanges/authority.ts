// V0666 (order gwo_e086b25f868da7ec9fce9fd2): governed code names ONE governing registry. On a registry that is not the governing one the Code changes view shows the registry's own
// sentence with the link and no way to submit; on the governing one nothing changes. While the answer is unknown (not read yet, or the read failed) the page behaves as it always did:
// the registry decides again at every write, so showing the form never grants anything.
import { ref, type Ref } from 'vue'
import { getAuthority, type CodeAuthority } from '@/services/api/codeChanges'

export interface AuthorityView { readOnly: boolean; sentence: string; link: string | null }

/** The pure rule: read-only only when the registry says it does not govern (self === false) and says what to tell the reader. */
export function authorityView(a: CodeAuthority | null | undefined): AuthorityView {
  if (!a || a.self !== false) return { readOnly: false, sentence: '', link: null }
  return { readOnly: true, sentence: a.sentence || `Code changes are governed on ${a.name || 'EU'}; open them there.`, link: a.console || null }
}

const shared: Ref<CodeAuthority | null> = ref(null)
let inflight: Promise<void> | null = null

/** One read per page load, shared by the three views. A failed read leaves the answer unknown. */
export function useCodeAuthority() {
  if (!shared.value && !inflight) {
    inflight = (async () => {
      try { shared.value = await getAuthority() } catch { shared.value = null }
      finally { inflight = null }
    })()
  }
  return { authority: shared, load: async () => { if (inflight) await inflight } }
}

export function resetCodeAuthorityForTests(): void { shared.value = null; inflight = null }
