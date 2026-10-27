import { describe, expect, it } from 'vitest'
import { readTargetSwitches } from '../targetSwitches'

describe('readTargetSwitches (§MCPTEST30 V0550)', () => {
  it('names the switches in their off position and the rows held to them', () => {
    const r = readTargetSwitches(
      { staking_enabled: false, staking_rewards_enabled: false, agora_distributions_enabled: true,
        governance_weight_mode: 'member', governance_presence_mode: 'off' },
      true,
      ['theprotocol_lockUnits', 'theprotocol_federationVoteProposal'],
    )
    expect(r).toEqual({
      off: ['staking_enabled=false', 'staking_rewards_enabled=false', 'governance_weight_mode=member'],
      rows: ['lockUnits', 'federationVoteProposal'],
      read: true,
    })
  })

  it('shows nothing for a target with nothing switched off, or a run before V0550', () => {
    expect(readTargetSwitches({ staking_enabled: true, governance_weight_mode: 'lock' }, true, [])).toBeNull()
    expect(readTargetSwitches(undefined, undefined, undefined)).toBeNull()
    expect(readTargetSwitches(null, null, null)).toBeNull()
    expect(readTargetSwitches(['staking_enabled'], true, [])).toBeNull()
  })

  it('names the commons switch where the commons is off (V0551), in the fixed order', () => {
    const r = readTargetSwitches(
      { commons_enabled: false, staking_enabled: false, governance_weight_mode: 'member' },
      true,
      ['theprotocol_getCommonsSeasons'],
    )
    expect(r).toEqual({
      off: ['staking_enabled=false', 'governance_weight_mode=member', 'commons_enabled=false'],
      rows: ['getCommonsSeasons'],
      read: true,
    })
    // an open commons switches nothing
    expect(readTargetSwitches({ commons_enabled: true }, true, [])).toBeNull()
  })

  it('says so when the target could not be read', () => {
    expect(readTargetSwitches(undefined, false, [])).toEqual({ off: [], rows: [], read: false })
  })

  it('reads only what a switch means: a missing key is not off, nor a string "false"', () => {
    expect(readTargetSwitches({ staking_enabled: 'false' }, true, [])).toBeNull()
    expect(readTargetSwitches({}, true, ['theprotocol_lockUnits', 7, ''])).toEqual({ off: [], rows: ['lockUnits'], read: true })
  })
})
