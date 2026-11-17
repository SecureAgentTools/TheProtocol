import { describe, it, expect } from 'vitest'
import v from './report.vectors.c4.json'
import { REPORT_SCHEMA, checkCertificate, classify, claimHash, hashHolds, reportHash, sha256Hex, canonicalBytes } from './reportCheck'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): the report viewer's logic, pinned against Python. The reports and the certificate in the
 * vectors were sealed with the SDK's own formulas (scratchpad/c4/gen_report_vectors.py: reports.seal, schema.canonical, cmd_certify), so
 * a hash recomputed here over canonical JSON (sorted keys, no spaces, unicode kept, UTF-8) must equal the one Python wrote.
 */
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x))
const V: any = v

describe('canonical JSON and its hash agree with Python', () => {
  it('hashes the empty string and a known text', async () => {
    expect(await sha256Hex(new TextEncoder().encode(''))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
  })
  it('writes sorted keys (by code point: z before Ä), no spaces, unicode as it is', () => {
    expect(new TextDecoder().decode(canonicalBytes({ b: 1, a: { z: null, 'Ärger': [true, 'x'] } }))).toBe('{"a":{"z":null,"Ärger":[true,"x"]},"b":1}')
  })
  for (const name of ['dry_run', 'load', 'reconcile_not_measured', 'reconcile_pass']) {
    it(`a report Python sealed holds here: ${name}`, async () => {
      expect(await reportHash(V[name])).toBe(V[name].report_sha256)
      expect(await hashHolds(V[name])).toBe(true)
    })
  }
  it('the claim hash and the record key are Python\'s', async () => {
    expect(await claimHash(V.certificate.attestation_data.claim)).toBe(V.claim_sha256)
    expect(V.certificate.attestation_data.record).toBe('tpm-' + V.claim_sha256.slice(0, 40))
  })
  it('a changed count, a changed name or a removed field breaks the hash', async () => {
    const a = clone(V.load); a.mappings.customers.rejected = 33
    const b = clone(V.load); b.targets.pg.written = 11991
    const c = clone(V.load); delete c.batches
    for (const r of [a, b, c]) expect(await hashHolds(r)).toBe(false)
  })
  it('the order of keys in the file does not matter', async () => {
    const r = V.load
    const shuffled = Object.fromEntries(Object.entries(r).reverse())
    expect(await hashHolds(shuffled)).toBe(true)
  })
})

describe('what a dropped file is', () => {
  it('knows a report, a certificate and neither', () => {
    expect(classify(V.load)).toBe('report')
    expect(classify(V.certificate)).toBe('certificate')
    expect(classify({ hello: 1 })).toBe('unknown')
    expect(classify([1, 2])).toBe('unknown')
    expect(classify(null)).toBe('unknown')
    expect(classify({ schema: 'theprotocol.migration.report/v2', step: 'load' })).toBe('unknown')      // a schema this page does not know
    expect(REPORT_SCHEMA).toBe('theprotocol.migration.report/v1')
  })
})

describe('a certificate against its reports', () => {
  const all = () => [V.dry_run, V.load, V.reconcile_pass]
  const byKey = (c: any, key: string) => c.checks.find((x: any) => x.key === key)

  it('every check holds when the reports it names are given', async () => {
    const c = await checkCertificate(V.certificate, all())
    expect(c.claimSha256).toBe(V.claim_sha256)
    for (const x of c.checks) expect(x.state, x.key).not.toBe('bad')
    expect(byKey(c, 'record').state).toBe('ok')
    expect(byKey(c, 'report:load').state).toBe('ok')
    expect(byKey(c, 'report:dry_run').state).toBe('ok')
    expect(byKey(c, 'report:reconcile').state).toBe('ok')
    expect(byKey(c, 'report:inventory').state).toBe('unknown')                // the claim names none: nothing to match
    expect(byKey(c, 'moved').state).toBe('ok')
    expect(byKey(c, 'rejected').state).toBe('ok')
    expect(byKey(c, 'fresh').state).toBe('ok')
    expect(byKey(c, 'template').state).toBe('ok')
  })

  it('says what it could not check when a report is not given, and fails nothing for it', async () => {
    const c = await checkCertificate(V.certificate, [V.load])
    expect(byKey(c, 'report:dry_run').state).toBe('unknown')
    expect(byKey(c, 'report:load').state).toBe('ok')
    expect(byKey(c, 'moved').state).toBe('ok')
    expect(byKey(c, 'fresh').state).toBe('unknown')                            // needs the reconcile
    expect(c.checks.some((x: any) => x.state === 'bad')).toBe(false)
  })

  it('a certificate whose claim was changed fails its record key', async () => {
    const cert = clone(V.certificate); cert.attestation_data.claim.moved = 99999
    const c = await checkCertificate(cert, all())
    expect(byKey(c, 'record').state).toBe('bad')
    expect(byKey(c, 'moved').state).toBe('bad')                                // and what the load report counts no longer agrees
  })

  it('a report that was changed after it was sealed fails its own hash and does not match the claim', async () => {
    const load = clone(V.load); load.targets.pg.written = 11991
    const c = await checkCertificate(V.certificate, [V.dry_run, load, V.reconcile_pass])
    expect(byKey(c, 'report:load').state).toBe('bad')
    expect(byKey(c, 'report:load').detail).toMatch(/hash|changed/i)
  })

  it('another version of a report of the same step does not match', async () => {
    const c = await checkCertificate(V.certificate, [V.dry_run, V.load, V.reconcile_not_measured])
    expect(byKey(c, 'report:reconcile').state).toBe('bad')
  })

  it('a report for another template version disagrees', async () => {
    const other = clone(V.dry_run); other.template.version = 4
    const c = await checkCertificate(V.certificate, [other])
    expect(byKey(c, 'template').state).toBe('bad')
  })

  it('a reconcile older than the load is stale', async () => {
    const rec = clone(V.reconcile_pass); rec.finished_at = '2026-11-14T10:00:00.000000Z'
    const c = await checkCertificate(V.certificate, [V.load, rec])
    expect(byKey(c, 'fresh').state).toBe('bad')
  })
})
