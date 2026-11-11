// V0658 (d), polish 14: the Guild board's "Reject -> dispute" asks the poster's reason and sends it; the registry files
// it as the complainant's first statement (routers/guild.py verify: statement=body.feedback).
import { describe, expect, it } from 'vitest'
import { REJECT_REASON_MAX, rejectReasonReady, verifyFeedback } from './rejectReason'
import board from '../../views/GuildBoard.vue?raw'

describe('rejectReason', () => {
  it('a rejection needs words, within what the registry takes', () => {
    expect(rejectReasonReady('')).toBe(false)
    expect(rejectReasonReady('   \n ')).toBe(false)
    expect(rejectReasonReady('the delivery is empty')).toBe(true)
    expect(rejectReasonReady('x'.repeat(REJECT_REASON_MAX))).toBe(true)
    expect(rejectReasonReady('x'.repeat(REJECT_REASON_MAX + 1))).toBe(false)
    expect(REJECT_REASON_MAX).toBe(2000)   // VerifyIn.feedback max_length
  })

  it('the reason goes with a rejection, trimmed, and never with an acceptance', () => {
    expect(verifyFeedback(false, '  the delivery is empty \n')).toBe('the delivery is empty')
    expect(verifyFeedback(true, 'anything')).toBeUndefined()
  })
})

describe('GuildBoard', () => {
  it('sends the reason with the verify call', () => {
    expect(board).toMatch(/guildApi\.verify\([^)]*verifyFeedback\(/)
  })

  it('asks before it sends: the reject press opens the reason, and the send waits for words', () => {
    expect(board).toContain('data-testid="gld-reject-reason"')
    expect(board).toMatch(/:disabled="[^"]*!rejectReasonReady\(rejectReason\)/)
  })
})
