/**
 * services/credImport.test.ts — §POCKETCREDS. Node-env vitest
 * (run with `npx vitest run --environment node`).
 */
import { describe, it, expect } from 'vitest'
import {
  normalizeEntries, classifyEntries, mergeCredDocs,
  isValidDid, isValidClientSecret,
} from './credImport'

const SEC = 'tp_secret_0123456789abcdef0123456789abcdef'
const ok = (n: number) => ({
  did: `did:theprotocol:00000000-0000-0000-0000-00000000000${n}`,
  client_id: `agent-${n}`, client_secret: SEC, name: `A${n}`,
})

describe('normalizeEntries: the three accepted shapes', () => {
  it('array passes through', () => {
    expect(normalizeEntries([ok(1), ok(2)])).toHaveLength(2)
  })
  it('single entry object wraps to [entry]', () => {
    const r = normalizeEntries(ok(1))
    expect(r).toHaveLength(1)
    expect(r![0].did).toBe(ok(1).did)
  })
  it('DID-keyed map spreads the key into did', () => {
    const r = normalizeEntries({ [ok(1).did]: { client_id: 'x', client_secret: SEC } })
    expect(r).toHaveLength(1)
    expect(r![0].did).toBe(ok(1).did)
    expect(r![0].client_id).toBe('x')
  })
  it('garbage is null, not an empty success', () => {
    expect(normalizeEntries('nope')).toBeNull()
    expect(normalizeEntries(42)).toBeNull()
    expect(normalizeEntries(null)).toBeNull()
  })
})

describe('classifyEntries', () => {
  it('splits new vs overwrite via the caller predicate', () => {
    const r = classifyEntries([ok(1), ok(2)], (d) => d === ok(2).did)
    expect(r.map(e => e.kind)).toEqual(['new', 'overwrite'])
  })
  it('names every defect instead of dropping the row', () => {
    const r = classifyEntries([{ did: 'not-a-did', client_id: '', client_secret: 'short' }], () => false)
    expect(r).toHaveLength(1)
    expect(r[0].kind).toBe('invalid')
    expect(r[0].error).toMatch(/DID invalid/)
    expect(r[0].error).toMatch(/client_id/)
    expect(r[0].error).toMatch(/client_secret/)
  })
  it('rejects a non-https registry_url rather than silently homing the agent here', () => {
    const bad = { ...ok(1), registry_url: 'http://evil.example' }
    const r = classifyEntries([bad], () => false)
    expect(r[0].kind).toBe('invalid')
    expect(r[0].error).toMatch(/https/)
  })
  it('accepts an https registry_url', () => {
    const r = classifyEntries([{ ...ok(1), registry_url: 'https://frame-c.theprotocol.cloud' }], () => false)
    expect(r[0].kind).toBe('new')
    expect(r[0].registry_url).toBe('https://frame-c.theprotocol.cloud')
  })
})

describe('mergeCredDocs', () => {
  it('one malformed doc never sinks the batch, and is named in the report', () => {
    const { entries, report } = mergeCredDocs([
      { name: 'good.json', text: JSON.stringify([ok(1)]) },
      { name: 'bad.json', text: '{nope' },
    ])
    expect(entries).toHaveLength(1)
    expect(report.find(r => r.name === 'bad.json')!.error).toMatch(/invalid JSON/)
  })
  it('duplicate DIDs dedupe last-doc-wins with the count reported', () => {
    const v2 = { ...ok(1), name: 'newer' }
    const { entries, dupes } = mergeCredDocs([
      { name: 'a.json', text: JSON.stringify([ok(1)]) },
      { name: 'b.json', text: JSON.stringify([v2]) },
    ])
    expect(dupes).toBe(1)
    expect(entries).toHaveLength(1)
    expect(entries[0].name).toBe('newer')
  })
  it('keyless entries survive to be flagged, not vanished', () => {
    const { entries } = mergeCredDocs([
      { name: 'a.json', text: JSON.stringify([{ client_id: 'x', client_secret: SEC }]) },
    ])
    expect(entries).toHaveLength(1)
    const classified = classifyEntries(entries, () => false)
    expect(classified[0].kind).toBe('invalid')
  })
})

describe('validators', () => {
  it('did shape', () => {
    expect(isValidDid('did:theprotocol:abc')).toBe(true)
    expect(isValidDid('did:cos:453d')).toBe(true)
    expect(isValidDid('theprotocol:abc')).toBe(false)
  })
  it('secret floor is 16 chars', () => {
    expect(isValidClientSecret('0123456789abcdef')).toBe(true)
    expect(isValidClientSecret('0123456789abcde')).toBe(false)
  })
})
