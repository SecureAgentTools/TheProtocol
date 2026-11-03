import { describe, it, expect } from 'vitest'
import {
  alreadyDecidedIds, approveAllIds, decidedElsewhere, didTail, isExpired, leftParts, liveApprovalStatus, pendingShown,
  secondsLeft, shortSha, touchesApprovals, type ApprovalItem,
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

describe('V0652 (y): a press on a request decided before it', () => {
  it('names the ids the server says were decided before (skipped already_*), or every sent id on a bare repeat', () => {
    expect(alreadyDecidedIds({ decided: [], skipped: { a: 'already_approved', b: 'expired' }, already: true }, ['a', 'b']))
      .toEqual(['a'])
    expect(alreadyDecidedIds({ already: true }, ['a', 'b'])).toEqual(['a', 'b'])
    expect(alreadyDecidedIds({ decided: [{ id: 'a' }], skipped: {} }, ['a'])).toEqual([])
    expect(alreadyDecidedIds({ decided: [{ id: 'a' }], skipped: { b: 'already_denied' } }, ['a', 'b'])).toEqual(['b'])
    expect(alreadyDecidedIds(null, ['a'])).toEqual([])
  })

  it('reads the decision, its time and whether the signed-in developer made it', () => {
    const rec = (dev: unknown) => ({ id: 'apr_1', decision: { decision: 'approved', decided_at: '2026-10-31T04:35:12Z',
                                                               decided_by: { developer_id: dev, name: 'Commander' } } })
    expect(decidedElsewhere(rec(6), 6)).toEqual(
      { id: 'apr_1', decision: 'approved', at: '2026-10-31T04:35:12Z', mine: true, name: 'Commander' })
    expect(decidedElsewhere(rec(6), '6')?.mine).toBe(true)
    expect(decidedElsewhere(rec(9), 6)?.mine).toBe(false)
    expect(decidedElsewhere(rec(6), null)?.mine).toBe(false)           // unknown signer: never claimed as "yours"
    expect(decidedElsewhere(rec(null), null)?.mine).toBe(false)
  })

  it('says nothing about a record without a decision', () => {
    expect(decidedElsewhere({ id: 'apr_1', status: 'pending' }, 6)).toBeNull()
    expect(decidedElsewhere({ decision: { decision: 'approved' } }, 6)).toBeNull()   // no time
    expect(decidedElsewhere({ decision: { decision: 'expired', decided_at: 'x' } }, 6)).toBeNull()
    expect(decidedElsewhere(null, 6)).toBeNull()
  })
})

describe('V0654 (aq), item 18: a request its asker withdrew', () => {
  const req = (id: string, extra: Record<string, unknown> = {}, ex = '2026-10-31T05:00:00Z') =>
    ({ kind: 'card', card: { v: 1, type: 'approval.request', data: { approval_id: id, expires_at: ex, ...extra } } })
  const choice = (id: string, extra: Record<string, unknown> = {}) =>
    ({ kind: 'card', card: { v: 1, type: 'choice.request', data: { approval_id: id, expires_at: '2026-10-31T05:00:00Z', ...extra } } })
  const w = { withdrawn: { at: '2026-10-31T03:58:00Z', by_agent_did: 'did:x' } }

  it('reads withdrawn from its card (updated in place), past its expiry too', () => {
    // BASE (V0653): pending and expired, the withdrawal unseen
    const live = liveApprovalStatus([req('w', w), choice('c', w), req('late', w, '2026-10-31T03:00:00Z'), req('p')], NOW)
    expect(live).toEqual({ w: 'withdrawn', c: 'withdrawn', late: 'withdrawn', p: 'pending' })
  })

  it('a request card that changed reaches the pinned panel, which reads its list again', () => {
    expect(touchesApprovals(req('w', w))).toBe(true)
    expect(touchesApprovals(choice('c', w))).toBe(true)
  })
})
