/**
 * §MCPTEST30 (V0640): the console's rule for an agent that cannot act, read as the server reads it
 * (routers/developers.owner_mint_refusal): status revoked or suspended, or an enforcement status saying so.
 */
import { describe, expect, it } from 'vitest'
import { cannotActReason, cannotActSentence } from './agentActable'

describe('cannotActReason', () => {
  it('names a revoked or a suspended agent in the server\'s words', () => {
    expect(cannotActReason({ status: 'revoked' })).toBe('revoked')
    expect(cannotActReason({ status: 'SUSPENDED' })).toBe('suspended')
    expect(cannotActReason({ status: 'active', enforcement_status: 'suspended' })).toBe('suspended')
    expect(cannotActReason({ status: 'active', enforcement_status: 'revoked' })).toBe('revoked')
  })

  it('says nothing for an active row, a saved-secret row (unknown) or no row at all', () => {
    expect(cannotActReason({ status: 'active' })).toBeNull()
    expect(cannotActReason({ status: 'unknown' })).toBeNull()
    expect(cannotActReason({})).toBeNull()
    expect(cannotActReason(null)).toBeNull()
  })

  it('words each case for a person', () => {
    expect(cannotActSentence({ name: 'Old Throwaway' }, 'revoked')).toContain('deleted')
    expect(cannotActSentence({ did: 'did:theprotocol:x' }, 'suspended')).toContain('suspended')
  })
})
