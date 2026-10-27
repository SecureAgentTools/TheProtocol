import { describe, expect, it } from 'vitest'
import { isRetiredList, railRole, railTileCounts, railTileOf, splitRailRows } from './railRows'

// Straits Assay on ASIA, as /contracts/v2/mine answered on 2026-09-24: one contract homed here (it is the client) and two
// replicas of EU's contracts (it is the provider). The page showed only the two replicas.
const ASSAY = 'did:theprotocol:asia.theprotocol.cloud:011dbd40-1039-4ef9-a457-404d87f2e130'
const SCRIVENER = 'did:theprotocol:eu.theprotocol.cloud:950eadac-6787-4302-a3b9-4d66d944015b'
const MINE = [
  { id: 'ctr_b96f2d7de25ce3d8fcbf8916', status: 'completed', client_did: ASSAY, provider_did: SCRIVENER },
  { id: 'ctr_58f55ded04fbd42df5ad4882', status: 'completed', replica: true, client_did: SCRIVENER, provider_did: ASSAY },
  { id: 'ctr_046d2b3a11c710882c88c1ad', status: 'completed', replica: true, client_did: SCRIVENER, provider_did: ASSAY },
]

describe('the Contracts page reads the rail (§TWOAGENT V0442)', () => {
  it('lists a contract that lives here as well as the replicas', () => {
    const s = splitRailRows(MINE)
    expect(s.home.map((c) => c.id)).toEqual(['ctr_b96f2d7de25ce3d8fcbf8916'])
    expect(s.replicas.map((c) => c.id)).toEqual(['ctr_58f55ded04fbd42df5ad4882', 'ctr_046d2b3a11c710882c88c1ad'])
  })

  it('ignores what is not a contract row', () => {
    expect(splitRailRows(null)).toEqual({ home: [], replicas: [] })
    expect(splitRailRows([null, 3, {}, { replica: false }]).home).toEqual([])
  })

  it('counts the tiles from the rail, every row it holds', () => {
    expect(railTileCounts(MINE)).toEqual({ proposed: 0, accepted: 0, inReview: 0, completed: 3 })
    expect(railTileCounts([{ status: 'offered' }, { status: 'agreed' }, { status: 'in_progress' }, { status: 'disputed' }]))
      .toEqual({ proposed: 1, accepted: 1, inReview: 1, completed: 0 })
  })

  it('tiles only the four states the page shows', () => {
    expect(['draft', 'disputed', 'cancelled', 'expired', '', null].map(railTileOf)).toEqual([null, null, null, null, null, null])
  })

  it('names the acting agent\'s side, whatever the case of the DID', () => {
    expect(railRole(MINE[0], ASSAY)).toBe('client')
    expect(railRole(MINE[1], ASSAY.toUpperCase())).toBe('provider')
    expect(railRole(MINE[1], 'did:theprotocol:elsewhere')).toBeNull()
    expect(railRole(MINE[1], null)).toBeNull()
  })

  it('tells a retired legacy list from any other failure', () => {
    expect(isRetiredList({ response: { status: 404 } })).toBe(true)
    expect(isRetiredList({ response: { status: 500 } })).toBe(false)
    expect(isRetiredList(new Error('Network Error'))).toBe(false)
    expect(isRetiredList(null)).toBe(false)
  })
})
