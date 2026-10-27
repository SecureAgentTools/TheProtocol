import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// §SETTLEUNIT (V0638, agentvault2-5b's find): every amount on a settlement card names its own frame's unit. Two read
// "AVT" (the slashed and the minted amount) while the requested amount and the shortfall read the viewer's unit; no
// card had ever rendered (cross_registry_settlements empty on every frame), so no run saw it.
const src = readFileSync(resolve(__dirname, 'Settlements.vue'), 'utf8')
const template = src.slice(src.indexOf('<template>'), src.indexOf('<script'))

describe('the settlement card names each amount in its own frame unit', () => {
  it('no amount carries a literal unit', () => {
    expect(template).not.toMatch(/_amount \}\}\s*AVT/)
    expect(template).not.toMatch(/shortfall \}\}\s*AVT/)
  })

  it("the slash side reads the defendant frame's unit, the compensation the origin's", () => {
    for (const field of ['requested_amount', 'slashed_amount', 'shortfall']) {
      expect(template).toMatch(new RegExp(`s\\.${field} \\}\\}\\s*\\{\\{ defendantUnit\\(s\\) \\}\\}`))
    }
    expect(template).toMatch(/s\.minted_amount \}\}\s*\{\{ originUnit\(s\) \}\}/)
  })
})
