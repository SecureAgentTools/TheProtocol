// V0658 (d), polish 14 of the disputes discovery: the Guild board's "Reject -> dispute" asks the poster why and sends
// it. The registry already took a reason (VerifyIn.feedback, at most 2000 characters) and files it as the
// complainant's first statement in the dispute (routers/guild.py, verify); the board never asked for one.

export const REJECT_REASON_MAX = 2000

export function rejectReasonReady(text: string): boolean {
  const t = (text || '').trim()
  return t.length > 0 && t.length <= REJECT_REASON_MAX
}

/** The verify call's feedback: the trimmed reason with a rejection, nothing with an acceptance. */
export function verifyFeedback(accept: boolean, reason: string): string | undefined {
  return accept ? undefined : (reason || '').trim()
}
