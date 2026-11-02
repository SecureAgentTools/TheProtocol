import { describe, it, expect, beforeEach } from 'vitest'
import { LIST_RAIL_PX, headerArrow, listAsRail, listFolded, saveListFolded } from './listFold'
import { pinMore, pinStart, pinnedFirst } from './approvalsPin'
import type { ApprovalItem } from './approvals'

/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc): the conversation list folds beside an open thread and the thread
 * header's arrow follows the panes (the maintainer, the sessions' room, seq 686); the requests pinned above the history
 * start as a card at every width and as the one-line strip on a phone. BASE (V0652): no fold, the arrow always left the
 * thread, and on a wide console pane the requests sat only in the side panel.
 */
describe('the list folds, kept per person on this device', () => {
  beforeEach(() => { try { localStorage.clear() } catch { /* no storage */ } })

  it('is open until this person folds it, and the choice survives a reload (a fresh read)', () => {
    expect(listFolded('dev:6')).toBe(false)
    saveListFolded('dev:6', true)
    expect(listFolded('dev:6')).toBe(true)
    saveListFolded('dev:6', false)
    expect(listFolded('dev:6')).toBe(false)
  })

  it("one person's choice is not another's", () => {
    saveListFolded('dev:6', true)
    expect(listFolded('dev:7')).toBe(false)
    expect(listFolded('')).toBe(false)
  })

  it('a value nobody wrote reads as open', () => {
    localStorage.setItem('ourchat.list.v1.dev:6', 'yes')
    expect(listFolded('dev:6')).toBe(false)
  })

  it("V0654: with no viewer known yet nothing is read or kept (a fold saved under 'anon' never folds the list)", () => {
    // the shell read the choice before the viewer was known: someone else's fold on this device folded the list at the
    // open and the viewer's own choice unfolded it a moment later, after the thread had scrolled to its NEW line
    const kept = () => Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .filter((k): k is string => !!k && k.startsWith('ourchat.list.v1.')).sort()
    localStorage.setItem('ourchat.list.v1.anon', 'folded')    // written before the guard
    expect(listFolded('')).toBe(false)
    saveListFolded('', true)
    saveListFolded('', false)
    expect(kept(), 'nothing written or cleared for nobody').toEqual(['ourchat.list.v1.anon'])
    expect(localStorage.getItem('ourchat.list.v1.anon')).toBe('folded')
    saveListFolded('dev:6', true)                              // control: a known viewer's choice is kept and read
    expect(listFolded('dev:6')).toBe(true)
  })

  it('the rail stands in only with two panes, the list folded and a thread open', () => {
    expect(listAsRail(true, true, true)).toBe(true)
    expect(listAsRail(true, true, false)).toBe(false)   // no thread: the list is all there is to show
    expect(listAsRail(true, false, true)).toBe(false)
    expect(listAsRail(false, true, true)).toBe(false)   // a phone: one pane at a time, as before
    expect(LIST_RAIL_PX).toBeGreaterThanOrEqual(44)      // a full tap target
  })
})

describe("the thread header's arrow", () => {
  it('with two panes it folds the list, and opens it again once folded: it never leaves the thread', () => {
    expect(headerArrow(true, false)).toBe('fold-list')
    expect(headerArrow(true, true)).toBe('open-list')
  })

  it('with one pane (a phone) it leaves the thread for the list, as before, folded or not', () => {
    expect(headerArrow(false, false)).toBe('leave')
    expect(headerArrow(false, true)).toBe('leave')
  })
})

const NOW = Date.parse('2026-11-01T21:00:00Z')
const req = (id: string, created: string, o: Partial<ApprovalItem> = {}): ApprovalItem => ({
  id, conversation_id: 'room1', status: 'pending', title: id, created_at: created,
  expires_at: '2099-01-01T00:00:00Z', ...o,
} as ApprovalItem)

describe('the pinned requests (compact)', () => {
  it('start as the card at every width and as the one-line strip on a phone-width pane', () => {
    expect(pinStart(false)).toBe('card')
    expect(pinStart(true)).toBe('strip')
  })

  it('the card shows the newest request that can still be decided (the one that just arrived)', () => {
    const shown = [req('apr_a', '2026-11-01T19:00:00Z'), req('apr_b', '2026-11-01T20:00:00Z'),
      req('apr_late', '2026-11-01T20:30:00Z', { expires_at: '2026-11-01T20:45:00Z' })]
    expect(pinnedFirst(shown, NOW)?.id).toBe('apr_b')
  })

  it('a link that opened one request shows that one', () => {
    const shown = [req('apr_a', '2026-11-01T19:00:00Z'), req('apr_b', '2026-11-01T20:00:00Z')]
    expect(pinnedFirst(shown, NOW, 'apr_a')?.id).toBe('apr_a')
    expect(pinnedFirst(shown, NOW, 'apr_gone')?.id).toBe('apr_b')
  })

  it('only expired ones: the newest stays readable; none: no card', () => {
    const shown = [req('apr_x', '2026-11-01T18:00:00Z', { status: 'expired' }),
      req('apr_y', '2026-11-01T18:30:00Z', { status: 'expired' })]
    expect(pinnedFirst(shown, NOW)?.id).toBe('apr_y')
    expect(pinnedFirst([], NOW)).toBeNull()
  })

  it('"n more" counts the others', () => {
    expect(pinMore(0)).toBe(0)
    expect(pinMore(1)).toBe(0)
    expect(pinMore(3)).toBe(2)
  })
})
