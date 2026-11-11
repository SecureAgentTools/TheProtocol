/**
 * V0658 (q), item 2: the two questions a view asks of an owner read's row (services/ownerParties). Is the acting agent a
 * party of it (then it acts, as before), and if not, which of the reader's parties (`my_parties`, as the registry named
 * them) to name. BASE: the module does not exist.
 */
import { describe, it, expect } from 'vitest'
import { actingIsParty, myParties, ownerParty, partyName } from './ownerParties'

const LEAD = 'did:theprotocol:eu.test:session-lead'
const SHELDON = 'did:theprotocol:eu.test:shadowban-sheldon'
const lead = { role: 'poster', agent_did: LEAD, name: 'session-lead', via: 'agent' as const }

describe('ownerParties', () => {
  const order = { poster_did: LEAD, worker_did: 'did:x:worker', my_parties: [lead] }

  it('names his party when another of his agents is acting, and when none is', () => {
    expect(ownerParty(order, SHELDON)).toEqual(lead)
    expect(ownerParty(order, null)).toEqual(lead)
  })
  it('names nobody when the acting agent is a party: it acts, as before (case of the DID ignored)', () => {
    expect(actingIsParty(order, LEAD.toUpperCase())).toBe(true)
    expect(ownerParty(order, LEAD)).toBeNull()
    expect(ownerParty({ ...order, my_parties: [] }, LEAD)).toBeNull()
  })
  it('a contract asks the same of its client and provider', () => {
    const c = { client_did: 'did:x:c', provider_did: SHELDON, my_parties: [{ ...lead, role: 'client', agent_did: 'did:x:c' }] }
    expect(actingIsParty(c, SHELDON)).toBe(true)
    expect(ownerParty(c, 'did:x:other')?.role).toBe('client')
  })
  it('a row the registry named no parties on, or a malformed list, has none', () => {
    expect(myParties({})).toEqual([])
    expect(myParties({ my_parties: 'x' })).toEqual([])
    expect(myParties({ my_parties: [null, { role: 'poster' }, lead] })).toEqual([lead])
    expect(ownerParty(null, SHELDON)).toBeNull()
  })
  it('a party is called by its name, else by a short DID', () => {
    expect(partyName(lead)).toBe('session-lead')
    expect(partyName({ name: null, agent_did: 'did:theprotocol:eu.theprotocol.cloud:8db7b75e-6d87' })).toBe('did:theprotocol…-6d87')
  })
})
