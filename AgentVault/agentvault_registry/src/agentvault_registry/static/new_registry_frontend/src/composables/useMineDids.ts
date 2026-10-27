/**
 * composables/useMineDids.ts — §MCFOLD (2026-09-02)
 *
 * WHICH agents are yours, for a ledger's MINE scope. Extracted from `PaneLedger.vue` so
 * the dashboard's ledger strip and the desk's ledger pane ask ONE question in ONE place
 * (the §FANOUTFIX law). The set comes from `/developers/me/agent-dids`, the identity-only
 * endpoint sized for a whole fleet, and is fed to the stream so the fleet log and every
 * ledger agree on the predicate.
 *
 * "None of your agents did anything" and "we do not yet know which agents are yours"
 * render identically and mean opposite things: `scopeNote` stays a sentence until the
 * set is genuinely known, and `scopeState` publishes which of the two the reader sees.
 */
import { ref } from 'vue'
import apiClient from '@/services/api/client'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { useI18n } from '@/composables/useI18n'

export type MineScopeState = 'loading' | 'known' | 'none' | 'failed'

export function useMineDids() {
  const { t } = useI18n()
  // autoStart:false — this composable answers WHOSE, it does not join the stream; the
  // ledger component that renders the rows owns the join (and the refcount).
  const stream = useLedgerStream({ autoStart: false })
  const mineDids = ref<string[]>([])
  const scopeNote = ref<string | null>(t('cockpit.ledger.loadingScope', 'Reading which agents are yours…'))
  const scopeState = ref<MineScopeState>('loading')

  async function load(): Promise<void> {
    try {
      const res = await apiClient.get('/developers/me/agent-dids')
      const dids = Array.isArray(res.data?.dids) ? res.data.dids.map((d: any) => String(d)) : []
      mineDids.value = dids
      if (dids.length) stream.setMineDids(dids)
      scopeNote.value = dids.length
        ? null
        : t('cockpit.ledger.noAgents', 'You own no agents on this registry, so nothing can match.')
      scopeState.value = dids.length ? 'known' : 'none'
    } catch {
      scopeState.value = 'failed'
      scopeNote.value = t('cockpit.ledger.scopeFailed',
        'Could not read which agents are yours — this list may be incomplete.')
    }
  }
  return { mineDids, scopeNote, scopeState, load }
}
