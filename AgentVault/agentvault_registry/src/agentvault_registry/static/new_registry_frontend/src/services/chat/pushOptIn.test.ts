import { describe, it, expect } from 'vitest'
import { pushOptInRows, PUSH_NEEDS_TYPES } from './pushOptIn'

/** V0652 (z): the opt-in turns on what needs you, never a room's whole traffic. BASE (V0651): the card turned on
 *  chat.message (every message of every room) and chat.ping. */
describe("the thread's push opt-in", () => {
  it('turns on both push channels for what needs you', () => {
    const rows = pushOptInRows()
    expect(rows).toHaveLength(PUSH_NEEDS_TYPES.length * 2)
    for (const t of ['chat.mention', 'chat.direct', 'chat.request', 'chat.approval_requested', 'chat.ping']) {
      expect(rows.filter((r) => r.type_key === t).map((r) => r.channel).sort()).toEqual(['push_desktop', 'push_mobile'])
    }
    expect(rows.every((r) => r.enabled)).toBe(true)
  })
  it("never a room's traffic", () => {
    expect(pushOptInRows().some((r) => r.type_key === 'chat.message')).toBe(false)
  })
})
