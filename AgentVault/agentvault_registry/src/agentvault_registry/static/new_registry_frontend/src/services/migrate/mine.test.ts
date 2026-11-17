import { describe, it, expect } from 'vitest'
import { normalizeMine, normalizeMineList, normalizeRuns, migrationsOnly, normalizeCertificates, certificatesFor, stateOf, hasNewerDraft, shareWords, certifiedBy, claimWords } from './mine'

const tpl = {
  id: 'wt_1', slug: 'crm-to-pg', title: 'CRM to Postgres', summary: 's', visibility: 'public', pricing_model: 'purchase', price: '5.0000000000', price_currency: 'ECU', fork_share_bps: 1000,
  versions: [{ version: 1, published: true, content_hash: 'a'.repeat(64), changelog: 'first' }, { version: 2, published: false, content_hash: 'b'.repeat(64), changelog: 'wip' }],
  counts: { kit_downloads: 12, instantiations: 4, certified: 2, forks: 1 },
  buyers: { count: 3, items: [{ agent_did: 'did:theprotocol:x:1', at: '2026-11-14T10:00:00Z' }] },
}

describe('normalizeMine', () => {
  it('reads the contract shape: versions newest first, counts, buyers', () => {
    const t = normalizeMine(tpl)
    expect(t.versions.map((v) => v.version)).toEqual([2, 1])
    expect([t.uses, t.used_by, t.certified, t.forks, t.buyers]).toEqual([12, 4, 2, 1, 3])
    expect(t.buyer_rows).toEqual([{ agent_did: 'did:theprotocol:x:1', at: '2026-11-14T10:00:00Z', name: '' }])
    expect(normalizeMine({ ...tpl, buyers: { count: 1, items: [{ agent_did: 'did:x:2', at: 'a', agent_name: 'Atlas' }] } }).buyer_rows[0].name).toBe('Atlas')
  })
  it('reads the registry\'s buyers {count, list: [{agent_did, at}]} (session-code, gwo_ef4d9981)', () => {
    const t = normalizeMine({ ...tpl, buyers: { count: 2, list: [{ agent_did: 'did:a:1', at: '2026-11-14T10:00:00Z' }, { agent_did: 'did:a:2', at: '2026-11-13T10:00:00Z' }] } })
    expect(t.buyers).toBe(2)
    expect(t.buyer_rows.map((b) => b.agent_did)).toEqual(['did:a:1', 'did:a:2'])
  })
  it('takes a buyer count alone (not the owner) and a plain number', () => {
    expect(normalizeMine({ ...tpl, buyers: { count: 7 } }).buyers).toBe(7)
    expect(normalizeMine({ ...tpl, buyers: 2 }).buyers).toBe(2)
    expect(normalizeMine({ ...tpl, buyers: { count: 7 } }).buyer_rows).toEqual([])
  })
  it('reads a version published by status or by its date, and a missing flag as a draft', () => {
    expect(normalizeMine({ ...tpl, versions: [{ version: 1, status: 'published' }] }).versions[0].published).toBe(true)
    expect(normalizeMine({ ...tpl, versions: [{ version: 1, published_at: '2026-11-01' }] }).versions[0].published).toBe(true)
    expect(normalizeMine({ ...tpl, versions: [{ version: 1 }] }).versions[0].published).toBe(false)
  })
  it('drops a row without an id and accepts the three list wrappers', () => {
    expect(normalizeMineList({ items: [tpl, { title: 'no id' }] })).toHaveLength(1)
    expect(normalizeMineList([tpl])).toHaveLength(1)
    expect(normalizeMineList({ templates: [tpl] })).toHaveLength(1)
    expect(normalizeMineList(null)).toEqual([])
  })
})

describe('state and share words', () => {
  it('draft, unlisted, published, and a newer draft on a published template', () => {
    expect(stateOf(normalizeMine({ ...tpl, versions: [{ version: 1, published: false }] }))).toBe('draft')
    expect(stateOf(normalizeMine(tpl))).toBe('published')
    expect(stateOf(normalizeMine({ ...tpl, visibility: 'unlisted' }))).toBe('unlisted')
    expect(hasNewerDraft(normalizeMine(tpl))).toBe(true)
    expect(hasNewerDraft(normalizeMine({ ...tpl, versions: [{ version: 1, published: true }] }))).toBe(false)
  })
  it('says a share for the original author, never a return', () => {
    expect(shareWords(1000)).toBe('A share of 10% for the original author')
    expect(shareWords(250)).toBe('A share of 2.5% for the original author')
    expect(shareWords(0)).toBe('No share for the original author')
    for (const b of [0, 250, 1000]) expect(shareWords(b)).not.toMatch(/stake|token|apy|yield|reward/i)
  })
  it('counts text', () => {
    expect(certifiedBy(1)).toBe('certified by 1 developer')
    expect(certifiedBy(3)).toBe('certified by 3 developers')
    expect(certifiedBy(0)).toBe('certified by 0 developers')
  })
})

describe('runs and certificates', () => {
  const runs = normalizeRuns({ workflows: [
    { id: 'wf1', title: 'A', status: 'running', total_budget: '5', currency: 'ECU', created_at: 'x', template: { id: 'wt_1', version: 2, content_hash: 'b'.repeat(64), title: 'CRM to Postgres' } },
    { id: 'wf2', title: 'by hand', status: 'draft', template: null },
  ] })
  it('keeps provenance and drops the workflows made by hand', () => {
    expect(runs).toHaveLength(2)
    expect(migrationsOnly(runs).map((r) => r.id)).toEqual(['wf1'])
    expect(runs[0].template).toEqual({ id: 'wt_1', version: 2, content_hash: 'b'.repeat(64), title: 'CRM to Postgres' })
  })
  const cert = (hash: string, name = 'crm-to-pg') => ({ attestation_id: 'att1', attestation_type: 'migration.certificate', target_agent_did: 'did:x', attestation_data: { record: 'tpm-1', claim: { template: { name, version: 1, content_hash: hash }, moved: 117, rejected: 3, verdict: 'pass' } } })
  it('keeps only migration certificates with a claim', () => {
    const c = normalizeCertificates([cert('a'.repeat(64)), { attestation_type: 'other', attestation_data: {} }, { attestation_type: 'migration.certificate', attestation_data: {} }])
    expect(c).toHaveLength(1)
    expect(claimWords(c[0])).toBe('117 rows moved, 3 rejected, reconcile passed')
  })
  it('matches a certificate to a template by the content hash of a version, else by name only when no hash is known', () => {
    const certs = normalizeCertificates([cert('a'.repeat(64)), cert('c'.repeat(64)), cert('', 'other')])
    expect(certificatesFor(certs, normalizeMine(tpl))).toHaveLength(1)
    expect(certificatesFor(certs, { slug: 'crm-to-pg', versions: [] })).toHaveLength(2)
    expect(certificatesFor(certs, { slug: 'crm-to-pg', content_hash: 'z'.repeat(64) })).toHaveLength(0)
  })
})
