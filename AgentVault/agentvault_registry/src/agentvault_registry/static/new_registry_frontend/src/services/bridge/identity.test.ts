import { describe, it, expect } from 'vitest'
import { classifyIdentity, didOrNull, firstOpenable, isDidLike, isUuidLike, isSystemAccount } from './identity'

// The exact values MEASURED on the wire / in his screenshot, 2026-08-19.
const DID = 'did:theprotocol:f7123936-1234-4abc-9def-0123456789ab'
const UUID = '342df814-cbd0-4ab2-8614-79a57e06a5c4'   // the one that 404'd
const UUID2 = '86e776c5-9fbd-421e-8c5c-6708e66d278e'
const SYS = 'teg:system:fee_collector'
const GATEWAY = 'agora-gateway-bvt'

describe('classifyIdentity', () => {
  it('a DID is openable and payable', () => {
    const id = classifyIdentity(DID)
    expect(id.kind).toBe('did')
    expect(id.did).toBe(DID)
    expect(id.canOpen).toBe(true)
    expect(id.canPay).toBe(true)
  })

  it('a bare UUID is matchable but NEVER a door and NEVER payable', () => {
    for (const u of [UUID, UUID2]) {
      const id = classifyIdentity(u)
      expect(id.kind).toBe('uuid')
      expect(id.did).toBeNull()
      expect(id.canOpen).toBe(false)
      expect(id.canPay).toBe(false)
      expect(id.key).toBe(u.toLowerCase())   // still usable for "is this mine?"
    }
  })

  it('system accounts are named, not opened, not paid', () => {
    for (const s of [SYS, GATEWAY, 'org-acme-treasury']) {
      const id = classifyIdentity(s)
      expect(id.kind).toBe('system')
      expect(id.canOpen).toBe(false)
      expect(id.canPay).toBe(false)
    }
    expect(classifyIdentity(SYS).label).toBe('fee collector')
  })

  it('labels never show a bare 36-char UUID', () => {
    expect(classifyIdentity(UUID).label).toBe('#342df814')
    expect(classifyIdentity(UUID).label.length).toBeLessThan(20)
  })

  it('empty / non-string is none', () => {
    for (const v of [null, undefined, '', '   ', 42, {}]) {
      expect(classifyIdentity(v as any).kind).toBe('none')
      expect(classifyIdentity(v as any).canOpen).toBe(false)
    }
  })
})

describe('didOrNull — the only safe by-did argument', () => {
  it('passes DIDs and rejects everything else', () => {
    expect(didOrNull(DID)).toBe(DID)
    expect(didOrNull(UUID)).toBeNull()
    expect(didOrNull(SYS)).toBeNull()
    expect(didOrNull('')).toBeNull()
  })

  it('REGRESSION: the R8 precedence bug — a UUID aggregate_id must not pass', () => {
    // `isDidLike(raw) ? raw : null || aggregate_id` returned the UUID, because the
    // ternary's false branch swallowed the ||. One function, one answer, no operators.
    const actorRaw = '9182e130-7642-4751-ab5d-74219492ac96'
    const aggregateId = UUID
    expect(didOrNull(actorRaw) ?? didOrNull(aggregateId)).toBeNull()
  })
})

describe('firstOpenable', () => {
  it('picks the first DID and skips UUIDs/system', () => {
    expect(firstOpenable(UUID, SYS, DID)).toBe(DID)
    expect(firstOpenable(UUID, SYS)).toBeNull()
    expect(firstOpenable()).toBeNull()
  })
})

describe('predicates', () => {
  it('are consistent with the classifier', () => {
    expect(isDidLike(DID)).toBe(true)
    expect(isDidLike(UUID)).toBe(false)
    expect(isUuidLike(UUID)).toBe(true)
    expect(isUuidLike(DID)).toBe(false)
    expect(isSystemAccount(SYS)).toBe(true)
    expect(isSystemAccount(DID)).toBe(false)
  })
  it('a DID that CONTAINS a uuid is a DID, not a uuid', () => {
    expect(classifyIdentity(`did:theprotocol:${UUID}`).kind).toBe('did')
  })
})

// §TRUSTCHAIN P4.6 (2026-09-12) — the developer wallet DID the backend mints from an email
// (identifiers.developer_teg_did: `@` -> `_at_`). It is a party on real transfers and not an agent.
describe('developer wallet DIDs', () => {
  const WALLET = 'did:theprotocol:ruffa_at_example.com'
  it('is payable, never an agent door, and never labelled with the email', () => {
    const id = classifyIdentity(WALLET)
    expect(id.kind).toBe('wallet')
    expect(id.canPay).toBe(true)
    expect(id.canOpen).toBe(false)
    expect(id.label).not.toContain('example.com')
  })
  it('never reaches /agents/by-did', () => {
    expect(didOrNull(WALLET)).toBeNull()
    expect(firstOpenable(WALLET, DID)).toBe(DID)
  })
  it('a real agent DID that merely contains _at_ elsewhere is still an agent', () => {
    // the wallet shape is the WHOLE identifier: `did:theprotocol:<local>_at_<domain>` with no colon
    expect(classifyIdentity('did:theprotocol:eu.theprotocol.cloud:_at_-not-a-wallet').kind).toBe('did')
  })
})
