/**
 * §COCKPITDESK (2026-10-15) — the EMERGENCY freeze's confirmation states its scope without a number it does not know.
 * It printed the picker's page as "all N agent(s) you own" (at most 30, or 0 before the picker opened) while the sweep
 * pages through the whole fleet (4,130 agents on one account): an irreversible action's dialog understated its reach.
 */
import { describe, expect, it } from 'vitest'
import src from './PocketApprovals.vue?raw'

const modal = src.slice(src.indexOf(':show="globalConfirm"'), src.indexOf('@confirm="doGlobalPanic"'))

describe('the emergency freeze names its scope', () => {
  it('says every agent you own, and counts nothing from the picker', () => {
    expect(modal).toContain('every agent you own')
    expect(modal).not.toMatch(/agents\.length/)
  })
  it('the sweep it confirms pages through the whole fleet, not the picker', () => {
    const sweep = src.slice(src.indexOf('async function doGlobalPanic'), src.indexOf('async function doGlobalPanic') + 2500)
    expect(sweep).toMatch(/getMyAgents\(\{ limit: 500, offset \}\)/)
    expect(sweep).not.toMatch(/agents\.value/)
  })
})
