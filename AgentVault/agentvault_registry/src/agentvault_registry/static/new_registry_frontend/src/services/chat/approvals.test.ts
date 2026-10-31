import { describe, it, expect } from 'vitest'
import {
  approveAllIds, didTail, isExpired, leftParts, liveApprovalStatus, pendingShown, secondsLeft, shortSha,
  touchesApprovals, type ApprovalItem,
} from './approvals'

/** V0650 (l): the pinned panel's pure rules. BASE (V0649): the module does not exist. */
const NOW = Date.parse('2026-10-31T04:00:00Z')
const item = (id: string, over: Partial<ApprovalItem> = {}): ApprovalItem => ({
  id, conversation_id: 'c1', status: 'pending', title: `t ${id}`,
  created_at: '2026-10-31T03:50:00Z', expires_at: '2026-10-31T05:00:00Z', ...over,
})

describe('approvals: what the panel shows and what Approve all sends', () => {
  it('lists pending requests oldest first and keeps an expired one visible but out of Approve all', () => {
    const items = [
      item('b', { created_at: '2026-10-31T03:55:00Z' }),
      item('a', { created_at: '2026-10-31T03:40:00Z' }),
      item('late', { expires_at: '2026-10-31T03:59:59Z' }),
      item('done', { status: 'approved' }),
    ]
    expect(pendingShown(items, NOW).map((i) => i.id)).toEqual(['a', 'late', 'b'])
    expect(approveAllIds(items, NOW)).toEqual(['a', 'b'])
  })

  it('an expired request is expired on this clock even while the server still said pending', () => {
    expect(isExpired(item('x', { expires_at: '2026-10-31T03:59:00Z' }), NOW)).toBe(true)
    expect(isExpired(item('y'), NOW)).toBe(false)
    expect(isExpired(item('z', { status: 'expired' }), NOW)).toBe(true)
    expect(secondsLeft(item('y'), NOW)).toBe(3600)
  })

  it('words the countdown in parts and shortens hashes and DIDs without losing the address', () => {
    expect(leftParts(3725)).toEqual({ h: 1, m: 2, s: 5 })
    expect(leftParts(-5)).toEqual({ h: 0, m: 0, s: 0 })
    expect(shortSha('a'.repeat(64))).toBe(`${'a'.repeat(12)}…`)
    expect(didTail('did:theprotocol:eu:0000000000abcdef')).toBe('…abcdef')
  })

  it('reads a request card\'s live status from the thread: a later decision wins, else expiry, else pending', () => {
    const req = (id: string, ex = '2026-10-31T05:00:00Z') => ({ kind: 'card', card: { v: 1, type: 'approval.request', data: { approval_id: id, expires_at: ex } } })
    const dec = (id: string, d: string) => ({ kind: 'card', card: { v: 1, type: 'approval.decided', data: { approval_id: id, decision: d } } })
    const live = liveApprovalStatus([req('p'), req('ok'), dec('ok', 'approved'), req('no'), dec('no', 'denied'),
      req('old', '2026-10-31T03:00:00Z'), { kind: 'text' }], NOW)
    expect(live).toEqual({ p: 'pending', ok: 'approved', no: 'denied', old: 'expired' })
    expect(touchesApprovals(dec('ok', 'approved'))).toBe(true)
    expect(touchesApprovals({ kind: 'card', card: { type: 'pay.request' } })).toBe(false)
  })
})
