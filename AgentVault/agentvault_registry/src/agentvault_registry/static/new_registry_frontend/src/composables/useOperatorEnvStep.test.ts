/**
 * §FESUITE V0595: the operator application's configuration step (his word 2026-10-11: "we need env setup in the
 * application forms ... the env flips that are frame exclusive should be still displayed for operators but greyed out
 * and not chooseable"). Before, an operator application had no configuration at all. The step starts from the frame's
 * own settings, locks the frame-scope ones, and sends only what the applicant chose differently; an unread catalog is
 * said, and sends nothing (never a guess).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EnvCatalog } from '@/services/api/envCatalog'

const h = vi.hoisted(() => ({ load: vi.fn() }))
vi.mock('@/services/api/envCatalog', async (orig) => ({ ...(await orig<any>()), loadEnvCatalog: () => h.load() }))

import { useOperatorEnvStep } from './useOperatorEnvStep'

const CATALOG: EnvCatalog = {
  catalog_version: 1, role: 'frame', groups: ['economy', 'agents'],
  entries: [
    { key: 'liability_card', group: 'agents', label: 'Liability card', hint: '', options: ['off', 'shadow', 'enforce'], default: 'off',
      scope: 'operator', reason: null, pair: null, env: 'LIABILITY_MODE', current: 'enforce', current_source: 'set' },
    { key: 'guild', group: 'economy', label: 'Guild', hint: '', options: ['yes', 'no'], default: 'yes',
      scope: 'operator', reason: null, pair: null, env: 'GUILD_ENABLED', current: null, current_source: 'unknown' },
    { key: 'staking', group: 'economy', label: 'Staking', hint: '', options: ['yes', 'no'], default: 'no',
      scope: 'frame', reason: "Money policy is the frame's: its operators follow it.", pair: null, env: 'STAKING_ENABLED', current: 'no', current_source: 'set' },
  ],
}

describe("the operator application's configuration step", () => {
  beforeEach(() => { h.load.mockReset() })

  it("starts as the frame runs, locks the frame's settings, and sends only what was changed", async () => {
    h.load.mockResolvedValueOnce(CATALOG)
    const s = useOperatorEnvStep()
    await s.loadEnv()
    expect(s.opFeatures.value).toEqual({ liability_card: 'enforce', guild: 'yes', staking: 'no' })
    expect(s.envLocked.value).toEqual({ staking: { value: 'no', reason: "Money policy is the frame's: its operators follow it." } })
    expect(s.choices(), 'nothing changed: nothing sent, everything inherited').toEqual({})
    s.onEnvChange('liability_card', 'shadow')
    s.onEnvChange('staking', 'yes')   // locked: the screen cannot choose it
    expect(s.opFeatures.value.staking).toBe('no')
    expect(s.choices()).toEqual({ liability_card: 'shadow' })
    expect(s.envChangedCount.value).toBe(1)
    s.resetEnv()
    expect(s.choices()).toEqual({})
  })

  it('an unread catalog is said, and the application sends no choices', async () => {
    h.load.mockRejectedValueOnce(new Error('Request failed with status code 502'))
    const s = useOperatorEnvStep()
    await s.loadEnv()
    expect(s.envFailed.value).toBe(true)
    expect(s.envCatalog.value).toBeNull()
    expect(s.choices()).toEqual({})
  })
})
