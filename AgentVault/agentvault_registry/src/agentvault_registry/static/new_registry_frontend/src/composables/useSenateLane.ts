/**
 * composables/useSenateLane.ts — §POCKETBRIDGE #PK16.
 *
 * The senate lane's ONE brain, extracted from BridgeTerminal so the Pocket
 * senate sheet (#PK17) does not become a second copy of governance logic (the
 * §FANOUTFIX class: two sites asking the same question drift, and the drift
 * lands exactly where nobody looks). The desktop terminal consumes this first
 * — no behavior change there, proven by its existing battery — and Pocket is
 * the second consumer.
 *
 * Semantics carried verbatim from the terminal (§BRIDGE R15.2):
 *   · reading proposals is PUBLIC; whether YOU voted needs an agent, and an
 *     unreadable vote list is "unknown", never "none";
 *   · voting is agent-only (PART 5 flow 7) — the CALLER guards that, because
 *     only the caller knows how its surface acquires an agent.
 * Each consumer gets its own instance: one logic, separate state.
 */
import { ref, computed } from 'vue'
import { governanceApi, type MemberVoteOutcome } from '@/services/api/governance'

export function useSenateLane() {
  const proposals = ref<any[]>([])
  const myVoted = ref<Set<string>>(new Set())
  const loaded = ref(false)
  const busy = ref(false)

  const openProposals = computed(() => (proposals.value || []).filter((p: any) => {
    const st = String(p?.status || '').toLowerCase()
    return st === 'active' || st === 'voting'
  }))

  async function load(hasAgent: boolean): Promise<{ ok: boolean; error?: any }> {
    busy.value = true
    try {
      const r: any = await governanceApi.getProposals({ limit: 20 } as any)
      const list = Array.isArray(r) ? r : (r?.proposals ?? r?.items ?? [])
      proposals.value = Array.isArray(list) ? list : []
      if (hasAgent) {
        try {
          const mv: any = await governanceApi.getMyVotes({ limit: 100 })
          const votes = Array.isArray(mv) ? mv : (mv?.votes ?? [])
          myVoted.value = new Set((votes || []).map((v: any) =>
            String(v?.proposalId ?? v?.proposal_id ?? v?.proposal?.id ?? '')).filter(Boolean))
        } catch { myVoted.value = new Set() }   // unknown, not "none"
      }
      loaded.value = true
      return { ok: true }
    } catch (error) {
      return { ok: false, error }
    } finally { busy.value = false }
  }

  async function vote(p: any, choice: 'for' | 'against'): Promise<{ ok: boolean; error?: any }> {
    busy.value = true
    try {
      await governanceApi.vote({ proposalId: String(p.id), choice })
      myVoted.value = new Set([...myVoted.value, String(p.id)])
      return { ok: true }
    } catch (error) {
      return { ok: false, error }
    } finally { busy.value = false }
  }

  /** §MEMBERSHIP (2026-10-02) — the vote where the registry runs member mode. The outcome is returned as is (a cast,
   *  a step-up to confirm, or a member refusal); a cast or an "already voted" marks the proposal voted. Errors other
   *  than the member answers still throw, so each surface reports them its own way. */
  async function voteMember(p: any, choice: 'for' | 'against',
                            extra: { totpCode?: string; challengeId?: string } = {}): Promise<MemberVoteOutcome> {
    busy.value = true
    try {
      const out = await governanceApi.castMemberVote({ proposalId: String(p.id), choice, ...extra })
      if (out.kind === 'cast' || out.kind === 'already_voted') markVoted(String(p.id))
      return out
    } finally { busy.value = false }
  }

  function markVoted(id: string) {
    myVoted.value = new Set([...myVoted.value, String(id)])
  }

  return { proposals, myVoted, loaded, busy, openProposals, load, vote, voteMember, markVoted }
}
