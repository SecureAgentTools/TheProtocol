import { describe, it, expect } from 'vitest'
import {
  manifestFrom, framesOf, ledgersOf, frameOf, entryByTrustDomain, entryByName, entryByOrigin, currencyNames, consoleLink,
  didIssuer, entryByRegistryUrl, settlementUnit,
} from './frameManifest'

// EU's view of the live cluster (2026-09-30), as core/federation_view.build_manifest assembles it
const EU = {
  manifest_version: 1,
  multi_frame: true,
  self: {
    key: 'eu', name: 'EU', display_name: 'EU', trust_domain: 'eu.theprotocol.cloud', role: 'frame', parent: null,
    public_url: 'https://eu.theprotocol.cloud', console_url: 'https://theprotocol.cloud', currency: 'ECU',
    currency_name: 'European Compute Unit', theme: 'neural', icon_url: null, ledger_ws: 'wss://eu.theprotocol.cloud/ws/events',
    tier: 'sovereign-mainframe', verified: true,
  },
  peers: [
    { key: 'asia', name: 'ASIA', display_name: 'ASIA', trust_domain: 'asia.theprotocol.cloud', role: 'frame', parent: null,
      public_url: 'https://asia.theprotocol.cloud', console_url: 'https://asia.theprotocol.cloud', currency: 'ACU',
      currency_name: 'Asian Compute Unit', theme: 'sovereign', icon_url: null,
      ledger_ws: 'wss://asia.theprotocol.cloud/ws/events', tier: 'sovereign-mainframe', verified: true },
    { key: 'amsterdam', name: 'amsterdam', display_name: 'Amsterdam', trust_domain: 'eu.theprotocol.cloud',
      role: 'operator', parent: 'eu', public_url: 'https://amsterdam.op.theprotocol.cloud',
      console_url: 'https://amsterdam.op.theprotocol.cloud', currency: 'ECU', currency_name: null, theme: 'neural',
      icon_url: null, ledger_ws: 'wss://eu.theprotocol.cloud/ws/events', tier: 'cloud-operator', verified: true },
    { key: 'hochiminh', name: 'hochiminh', display_name: 'Ho Chi Minh City', trust_domain: 'asia.theprotocol.cloud',
      role: 'operator', parent: 'asia', public_url: 'https://hochiminh.op.theprotocol.cloud',
      console_url: 'https://hochiminh.op.theprotocol.cloud', currency: 'ACU', currency_name: null, theme: 'sovereign',
      icon_url: null, ledger_ws: 'wss://asia.theprotocol.cloud/ws/events', tier: 'cloud-operator', verified: true },
  ],
}

// the same federation seen from amsterdam's console: an operator streams its parent's ledger
const AMS = {
  manifest_version: 1,
  multi_frame: true,
  self: { ...EU.peers[1] },
  peers: [{ ...EU.self }, { ...EU.peers[0] }, { ...EU.peers[2] }],
}

describe('the frame manifest (§FEFRAME W2)', () => {
  it('reads a manifest and refuses a body without one (an older registry)', () => {
    expect(manifestFrom(EU)?.self.key).toBe('eu')
    expect(manifestFrom({ registry_name: 'x', local_currency: 'AVT' })).toBeNull()
    expect(manifestFrom(null)).toBeNull()
  })

  it('lists the frames with the own frame first, and one ledger per frame', () => {
    const m = manifestFrom(EU)!
    expect(framesOf(m).map((f) => f.key)).toEqual(['eu', 'asia'])
    expect(ledgersOf(m)).toEqual([
      { frame: m.self, url: 'wss://eu.theprotocol.cloud/ws/events' },
      { frame: m.peers[0], url: 'wss://asia.theprotocol.cloud/ws/events' },
    ])
  })

  it("an operator's console streams its parent frame first", () => {
    const m = manifestFrom(AMS)!
    expect(frameOf(m, m.self)?.key).toBe('eu')
    expect(framesOf(m).map((f) => f.key)).toEqual(['eu', 'asia'])
    expect(ledgersOf(m).map((l) => l.url)).toEqual(['wss://eu.theprotocol.cloud/ws/events', 'wss://asia.theprotocol.cloud/ws/events'])
  })

  it('attributes by trust domain to the FRAME, by name and by origin to the entry', () => {
    const m = manifestFrom(EU)!
    expect(entryByTrustDomain(m, 'asia.theprotocol.cloud')?.key).toBe('asia')          // not hochiminh
    expect(entryByTrustDomain(m, 'nowhere.example')).toBeNull()
    expect(entryByName(m, 'Ho Chi Minh City')?.key).toBe('hochiminh')
    expect(entryByName(m, 'HOCHIMINH')?.key).toBe('hochiminh')
    expect(entryByOrigin(m, 'https://theprotocol.cloud/#/dashboard')?.key).toBe('eu')
    expect(entryByOrigin(m, 'https://eu.theprotocol.cloud')?.key).toBe('eu')
    expect(entryByOrigin(m, 'https://registry-a.example')).toBeNull()
  })

  it('names currencies from the server only, and links a console route', () => {
    const m = manifestFrom(EU)!
    expect(currencyNames(m)).toEqual({ ECU: 'European Compute Unit', ACU: 'Asian Compute Unit' })
    expect(consoleLink(m.peers[0], 'discovery')).toBe('https://asia.theprotocol.cloud/#/discovery')
    expect(consoleLink(m.self)).toBe('https://theprotocol.cloud/')
    expect(consoleLink({ ...m.self, console_url: null })).toBeNull()
  })
})


// §SETTLEUNIT (V0638): a cross-registry settlement names each amount in its own frame's unit (Settlements.vue)
describe("a settlement amount's unit", () => {
  const m = manifestFrom(EU)!
  const asiaDid = 'did:theprotocol:asia.theprotocol.cloud:5b6acf43-0000-4000-8000-000000000001'
  const euDid = 'did:theprotocol:eu.theprotocol.cloud:5b6acf43-0000-4000-8000-000000000002'

  it("reads a DID's issuer, and none from a legacy DID", () => {
    expect(didIssuer(asiaDid)).toBe('asia.theprotocol.cloud')
    expect(didIssuer('did:theprotocol:0123456789abcdef0123')).toBeNull()
    expect(didIssuer('')).toBeNull()
    expect(didIssuer('not-a-did:x:y:z')).toBeNull()
  })

  it('finds the entry a registry URL names, by origin or by host when a port differs', () => {
    expect(entryByRegistryUrl(m, 'https://asia.theprotocol.cloud')?.key).toBe('asia')
    expect(entryByRegistryUrl(m, 'https://asia.theprotocol.cloud:8443/api/v1')?.key).toBe('asia')
    expect(entryByRegistryUrl(m, 'http://asia-registry:8000')).toBeNull()
    expect(entryByRegistryUrl(m, '')).toBeNull()
  })

  it("names the party's frame: by its DID first, else its registry URL, else nothing", () => {
    // EU's page, the origin's row: the defendant is ASIA's agent, the compensation EU's own
    expect(settlementUnit(m, asiaDid, 'http://asia-registry:8000')).toBe('ACU')
    expect(settlementUnit(m, euDid, 'https://eu.theprotocol.cloud')).toBe('ECU')
    // a legacy DID: the URL decides
    expect(settlementUnit(m, 'did:theprotocol:0123456789abcdef0123', 'https://asia.theprotocol.cloud')).toBe('ACU')
    // neither known: no unit (never the viewer's or AVT)
    expect(settlementUnit(m, 'did:theprotocol:0123456789abcdef0123', 'http://localhost:8000')).toBeNull()
    expect(settlementUnit(null, asiaDid, 'https://asia.theprotocol.cloud')).toBeNull()
  })
})
