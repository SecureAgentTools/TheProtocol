/**
 * V0658 (q), item 2: the owner's reads go out on the developer's own token, the acting agent's lists on its token.
 * GET /guild/owned and GET /contracts/v2/owned are developer routes (reading follows ownership); /contracts/v2/owned is
 * registered before the contract detail, and the console's copy of the server's token map says so (a `d` row, else the
 * template /contracts/v2/{cid} answers for it). BASE: the map has no such row (the detail template matches, "either").
 */
import { describe, it, expect } from 'vitest'
import { actsAsAgent, tierOf } from './authTiers'

describe("the owner's reads take the developer's token", () => {
  it('the owned lists are developer reads', () => {
    expect(actsAsAgent('/guild/owned', 'get')).toBe(false)
    expect(actsAsAgent('/contracts/v2/owned', 'get')).toBe(false)
    expect(tierOf('GET', '/contracts/v2/owned'), 'the map lists the route ahead of the detail template').toBe('developer')
    expect(tierOf('GET', '/guild/owned')).toBe('developer')
  })
  it("control: the acting agent's lists keep its token, and a contract id still reads as before", () => {
    expect(actsAsAgent('/guild/mine', 'get')).toBe(true)
    expect(actsAsAgent('/contracts/v2/mine', 'get')).toBe(true)
    expect(tierOf('GET', '/contracts/v2/ctr_0123abcd')).toBe('either')
  })
})
