import { describe, expect, it } from 'vitest'
import { localVenueOf } from './localVenue'

/**
 * §FESUITE (2026-10-10, the operator batch; his question: "passport buy on own frame you must check if this is intended
 * or not") — the board lists this registry's own venue on purpose; its listings are bought on this market, never by
 * passport (the passport rail is for a FOREIGN market). The rule that tells them apart is the desktop's: the venue whose
 * listings this registry also lists itself.
 */
const board = [
  { venue: 'sandbox-beta', listings: [{ symbol: 'SBW' }, { symbol: 'SBQ' }] },
  { venue: 'Sandbox Alpha', listings: [{ symbol: 'SAX' }] },
  { venue: 'sbxalphaop', listings: [{ symbol: 'OPA' }] },
]

describe('the board knows its own market', () => {
  it('the venue that lists what this registry lists is this market', () => {
    expect(localVenueOf(board, ['SBQ', 'SBW'])).toBe('sandbox-beta')
    expect(localVenueOf(board, ['OPA'])).toBe('sbxalphaop')
  })
  it('nothing is called local before either list is read, or where this market lists nothing', () => {
    expect(localVenueOf(board, [])).toBe('')
    expect(localVenueOf([], ['SBW'])).toBe('')
    expect(localVenueOf(board, ['NOPE'])).toBe('')
  })
})
