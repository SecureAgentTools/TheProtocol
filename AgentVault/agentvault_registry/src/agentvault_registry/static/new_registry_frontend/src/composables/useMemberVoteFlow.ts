/**
 * composables/useMemberVoteFlow.ts — §MEMBERSHIP (2026-10-02): the confirm-and-resend sequence of a member's binding
 * act, once, for every surface that casts one: a vote through the senate lane (Pocket's senate sheet, the Bridge
 * terminal) and a commons ballot (the Senate floor's commons tab). Both answer 428 with the same step-up body.
 *
 *   start(cast)  first call; a 428 opens the step-up (stepUp is set), anything else settles
 *   approved(id) the phone approved: the SAME act again, with the challenge id
 *   code(totp)   a one-time code: the SAME act again, with the code
 *
 * The SAME act matters: the server binds an approval to what it showed (a vote's proposal and choice, a ballot's exact
 * allocations), so the proof is always sent through the closure that made the first call.
 *
 * A step-up answer to a call that carried a proof means the proof was refused (a wrong code, a declined or expired
 * challenge): the new challenge replaces the old one and the dialog says why. Errors on the first call throw to the
 * caller (each surface reports them its own way); errors while the dialog is open are shown in it.
 */
import { ref } from 'vue'
import type { MemberVoteOutcome } from '@/services/api/governance'
import type { StepUpChallenge } from '@/services/membership/membership'
import { useI18n } from '@/composables/useI18n'

export interface StepUpAnswer { kind: 'step_up'; stepUp: StepUpChallenge; message: string }
export type SettledOutcome = Exclude<MemberVoteOutcome, { kind: 'step_up' }>
type Extra = { totpCode?: string; challengeId?: string }

/** The flow for any member act whose answers are `S` (settled) or a step-up. */
export function useStepUpFlow<S extends { kind: string }>(onSettled: (out: S) => void) {
  const { t } = useI18n()
  const stepUp = ref<StepUpChallenge | null>(null)
  const stepUpError = ref('')
  const busy = ref(false)
  let cast: ((extra: Extra) => Promise<S | StepUpAnswer>) | null = null

  function cancel() {
    stepUp.value = null
    stepUpError.value = ''
    cast = null
  }

  async function run(extra: Extra = {}) {
    if (!cast || busy.value) return
    const withProof = !!(extra.totpCode || extra.challengeId)
    busy.value = true
    try {
      const out = await cast(extra)
      if (out.kind === 'step_up') {
        const su = out as StepUpAnswer
        stepUpError.value = withProof
          ? (su.message || t('membership.stepUp.expired', 'This confirmation expired. Vote again to get a new one.'))
          : ''
        stepUp.value = su.stepUp
        return
      }
      cancel()
      onSettled(out as S)
    } catch (e: any) {
      if (!stepUp.value) { cast = null; throw e }
      stepUpError.value = e?.response?.data?.message || e?.response?.data?.detail || e?.message
        || t('membership.vote.failed', 'Your vote could not be cast.')
    } finally {
      busy.value = false
    }
  }

  async function start(fn: (extra: Extra) => Promise<S | StepUpAnswer>) {
    cancel()
    cast = fn
    await run()
  }

  return {
    stepUp, stepUpError, busy, start, cancel,
    approved: (challengeId: string) => run({ challengeId }),
    code: (totpCode: string) => run({ totpCode }),
  }
}

/** The vote's flow (Pocket's senate sheet, the Bridge terminal): unchanged for its callers. */
export function useMemberVoteFlow(onSettled: (out: SettledOutcome) => void) {
  return useStepUpFlow<SettledOutcome>(onSettled)
}
