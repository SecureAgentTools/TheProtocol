import { describe, it, expect } from 'vitest'
import { categorizeTool } from '../toolCategory'

const ADMIN = 'Admin · '

describe('the category of a row in the All tools list', () => {
  it('names a console step by its lifecycle and a federation test by its group (rows that are not tools)', () => {
    expect(categorizeTool('ui:wallet_flow.open_sheet', 'none')).toBe('Console · wallet flow')
    expect(categorizeTool('federation_suite: federation_handshake/test_mtls_both_ways', '')).toBe('Federation · handshake')
  })

  it('files a tool by the rule its name meets, the admin tier adding its prefix', () => {
    expect(categorizeTool('theprotocol_getCanaryStatus', 'admin')).toBe(ADMIN + 'Canary')
    expect(categorizeTool('theprotocol_fireCanaryPath', 'admin')).toBe(ADMIN + 'Canary')
    expect(categorizeTool('theprotocol_getSupplyAuditorStatus', 'admin')).toBe(ADMIN + 'Supply Auditor')
    expect(categorizeTool('theprotocol_getCollusionRings', 'admin')).toBe(ADMIN + 'Collusion')
    expect(categorizeTool('theprotocol_bridgeTransfer', 'agent')).toBe('Bridges')
    expect(categorizeTool('theprotocol_authorizePayment', 'agent')).toBe('A2A Payment')
  })

  it('lets the row\'s own tier decide Admin: six public tools the name rule filed under it are not admin tools', () => {
    const publicTools: Array<[string, string]> = [
      ['theprotocol_approveContractCompletion', 'agent'], ['theprotocol_approveDisputeSettlement', 'developer'],
      ['theprotocol_rejectDisputeSettlement', 'developer'], ['theprotocol_grantSupportReview', 'developer'],
      ['theprotocol_revokeSupportReview', 'developer'], ['theprotocol_revokeApiKey', 'developer'],
    ]
    for (const [tool, tier] of publicTools) {
      expect(categorizeTool(tool, tier).startsWith(ADMIN), `${tool} (${tier})`).toBe(false)
      // a row that came without its tier is still guessed from the name, as before
      expect(categorizeTool(tool).startsWith(ADMIN), `${tool} (no tier)`).toBe(true)
    }
    expect(categorizeTool('theprotocol_approveContractCompletion', 'agent')).toBe('Contracts')
    expect(categorizeTool('theprotocol_suspendAgent', 'admin').startsWith(ADMIN)).toBe(true)
    expect(categorizeTool('theprotocol_suspendAgent', 'admin-bridge').startsWith(ADMIN)).toBe(true)
  })

  it('says Other for a name no rule knows, Admin · Other for an admin one', () => {
    expect(categorizeTool('theprotocol_zzzUnheardOf', 'developer')).toBe('Other')
    expect(categorizeTool('theprotocol_zzzUnheardOf', 'admin')).toBe(ADMIN + 'Other')
  })
})
