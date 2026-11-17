/**
 * V0662 console polish, item 5 (order gwo_0aa7b875cbf65b6347f5f775): an agent's roles in the console's words. The
 * roles come from the API by their names (trader, client, staker); the console says LOCKED for what the ledger calls
 * staked (i18n/vocabulary.test.ts), so the staker role reads as the words for locking units, and keeps its API name
 * for the hover. Every other role reads as its name. Red on f569f6a6e: the module does not exist.
 */
import { describe, it, expect } from 'vitest'
import { roleLabel, roleTitle } from './roleLabel'

const t = (_k: string, fallback: string) => fallback

describe('a role in the console\'s words', () => {
  it('the staker role reads as locking units; its API name stays on the hover', () => {
    expect(roleLabel('staker', t)).toBe('locks units')
    expect(roleTitle('staker', t)).toContain('staker')
  })
  it('every other role reads as its name, and so does one the console has not met', () => {
    for (const r of ['trader', 'client', 'observer', 'governor', 'canary', 'service-provider', 'legacy-full', 'new-role']) {
      expect(roleLabel(r, t)).toBe(r)
    }
    expect(roleTitle('trader', t)).toBe('')
  })
})
