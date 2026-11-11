// V0658 (d), polish 15: who may add evidence to a dispute from the console, and as which party.
import { describe, expect, it } from 'vitest'
import { evidenceRoute } from './evidenceAs'

const A = 'did:theprotocol:aaaa'
const B = 'did:theprotocol:bbbb'
const open = { status: 'open', claimant_did: A, respondent_did: B }

describe('evidenceRoute', () => {
  it('acting as a party: the agent files as itself (the agent route, as before)', () => {
    expect(evidenceRoute(open, { actingDid: A, ownedDids: [], isAdmin: false })).toEqual({ route: 'agent', asDid: A })
  })

  it('an owner of one party, acting as no party: the owner route, filed as that party', () => {
    expect(evidenceRoute(open, { actingDid: '', ownedDids: [B, 'did:x'], isAdmin: false }))
      .toEqual({ route: 'owner', parties: [B] })
  })

  it('an owner of both parties chooses which one', () => {
    expect(evidenceRoute(open, { actingDid: '', ownedDids: [A, B], isAdmin: false }))
      .toEqual({ route: 'owner', parties: [A, B] })
  })

  it('a member whose party is outside the loaded agent list still gets the owner route: the server resolves it', () => {
    // a member reads only disputes one of their agents is a party to (D6-465), so the dispute is theirs
    expect(evidenceRoute(open, { actingDid: '', ownedDids: [], isAdmin: false })).toEqual({ route: 'owner', parties: [] })
  })

  it('an administrator who owns no party adds nothing (an admin reads every dispute, theirs or not)', () => {
    expect(evidenceRoute(open, { actingDid: '', ownedDids: [], isAdmin: true })).toBeNull()
    expect(evidenceRoute(open, { actingDid: '', ownedDids: [A], isAdmin: true })).toEqual({ route: 'owner', parties: [A] })
  })

  it('acting as an agent that is no party falls back to the owner route', () => {
    expect(evidenceRoute(open, { actingDid: 'did:other', ownedDids: [A], isAdmin: false }))
      .toEqual({ route: 'owner', parties: [A] })
  })

  it('a decided dispute takes no evidence', () => {
    for (const status of ['resolved', 'dismissed']) {
      expect(evidenceRoute({ ...open, status }, { actingDid: A, ownedDids: [A], isAdmin: false })).toBeNull()
    }
  })
})
