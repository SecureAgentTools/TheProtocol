/**
 * composables/useVotePermission.ts — §MEMBERSHIP phase C (2026-10-02): may the agent a member acts as vote, and if
 * not, allow it (services/membership/votePermission.ts has the rule and the reason for every limit here).
 *
 *   check()  reads the agent's authority (GET /agents/{did}/authz, the owner's developer token)
 *   allow()  adds `governor` and touches nothing else: through the additive rail where the registry has it
 *            (POST /agents/{did}/authz/roles, any agent); on an older image through the whole-set PUT, but only after
 *            reading the roles again right before writing and only where no role carries a time limit; otherwise the
 *            state becomes `panel_only` (My Agents, where the limit stays visible). A write that fails keeps the state it
 *            had (nothing was granted, or the next press reads it again) and says why in `error`; only check() fails the
 *            state itself
 */
import { ref, watch, type Ref } from 'vue'
import { agentAuthzApi } from '@/services/api/agentAuthz'
import { rolesWithGovernor, VOTE_PERMISSION, VOTE_ROLE, votePermissionState, type VotePermissionState } from '@/services/membership/votePermission'

/** `panel_only`: the registry has no additive rail and a role carries a time limit, so nothing is written here */
export type VotePermissionView = 'idle' | 'checking' | VotePermissionState | 'panel_only' | 'failed'

export function useVotePermission(did: Ref<string | null | undefined>) {
  const state = ref<VotePermissionView>('idle')
  const error = ref('')
  const busy = ref(false)
  // Replies count in the order they were ASKED: a check that read the roles before the press wrote them must not land
  // after the press and put "not allowed yet" back (a check can start mid-press when the acting agent is set again).
  // Every check takes a number; the press takes one when it settles, superseding every check asked before it.
  let seq = 0

  function reason(e: any): string {
    const d = e?.response?.data
    return (typeof d?.detail === 'string' && d.detail) || (typeof d?.message === 'string' && d.message) || e?.message || ''
  }

  async function check(): Promise<VotePermissionView> {
    const d = did.value
    const mine = ++seq
    if (!d) { state.value = 'idle'; return state.value }
    state.value = 'checking'
    error.value = ''
    try {
      const s = votePermissionState(await agentAuthzApi.get(d))
      if (mine === seq) state.value = s
    } catch (e: any) {
      if (mine === seq) {
        state.value = 'failed'
        error.value = reason(e)
      }
    }
    return state.value
  }

  async function allow(): Promise<boolean> {
    const d = did.value
    if (!d || busy.value) return false
    busy.value = true
    error.value = ''
    // the press's answer supersedes every check asked before it, and belongs to the agent it was made for
    const settle = (s: VotePermissionView): boolean => {
      seq += 1
      if (did.value !== d) return false
      state.value = s
      return s === 'ok'
    }
    try {
      // the additive rail: one role, every other grant as it is (time limits included)
      const added = await agentAuthzApi.addRole(d, VOTE_ROLE)
      if (added) {
        return settle((added.effective_permissions || []).includes(VOTE_PERMISSION) ? 'ok' : votePermissionState(await agentAuthzApi.get(d)))
      }
      // an older image: the whole-set PUT, read again right before writing, never over a time limit
      const fresh = await agentAuthzApi.get(d)
      const s = votePermissionState(fresh)
      if (s === 'ok') return settle('ok')
      if (s === 'time_boxed') { settle('panel_only'); return false }
      await agentAuthzApi.set(d, { roles: rolesWithGovernor(fresh.roles) })
      return settle(votePermissionState(await agentAuthzApi.get(d)))
    } catch (e: any) {
      error.value = reason(e) || String(e)        // never empty: an empty reason would hide the failure
      return false
    } finally {
      busy.value = false
    }
  }

  watch(did, () => { state.value = 'idle'; error.value = '' })
  return { state, error, busy, check, allow }
}
