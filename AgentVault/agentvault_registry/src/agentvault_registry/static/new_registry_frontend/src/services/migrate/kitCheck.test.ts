import { describe, it, expect } from 'vitest'
import vectors from './kit.vectors.c4.json'
import { checkKit, writtenOutSecrets, destinationRefusals } from './kitCheck'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): the console's kit check, which a person sees BEFORE they download or save a kit, is the registry's
 * publish gate (services/workflow_templates.check_kit, AgentVault v0664/cut) ported rule by rule. The vectors were produced by RUNNING that
 * function over the three shipped kits and over mutations that break each rule once (scratchpad/c4/gen_kit_vectors.py, in the registry image);
 * the first problem the console names must be the very sentence the registry gives.
 *
 * The one place the console deliberately differs: the registry refuses a secret field that holds a ${PARAM} placeholder (all three shipped kits
 * do), which the SDK's own check accepts (reported to session-code, room seq 3992). `secretPlaceholders: 'registry'` follows the registry (what
 * the vectors say), 'intended' (the console's default) follows the SDK; the second block tests that choice by itself.
 */
const V: any = vectors

describe('the registry\'s publish gate, case by case', () => {
  for (const c of V.cases as any[]) {
    it(c.name, () => {
      const files: Record<string, string> = {}
      for (const f of c.files) files[f] = c.text && c.text[f] !== undefined ? c.text[f] : 'x\n'
      const r = checkKit({ files, manifest: c.manifest, proxy: c.proxy }, { secretPlaceholders: 'registry' })
      if (c.expected.ok) expect(r.problems, JSON.stringify(r.problems)).toEqual([])
      else {
        expect(r.ok).toBe(false)
        expect(r.problems[0].sentence).toBe(c.expected.refused)
      }
    })
  }
})

describe('the console\'s own default for a secret placeholder', () => {
  const base = () => ({
    manifest: { schema: 'theprotocol.migration/v1', name: 'k', title: 'K', from: { kind: 'file' }, to: { kind: 'sql' }, load: { mappings: ['m'] }, rollback: 'auto',
      parameters: { TARGET_PASSWORD: { secret: true, description: 'a reference' }, TARGET_HOST: {}, PLAIN: {} } },
    proxy: { version: 1, name: 'k', sinks: { s: { type: 'sql_upsert', config: { host: '${TARGET_HOST}', password: '${TARGET_PASSWORD}' } } } },
    files: { 'migration.yaml': 'x', 'proxy.yaml': 'x', 'README.md': 'x' } as Record<string, string>,
  })
  it('accepts a placeholder for a declared secret parameter, as the SDK does', () => {
    expect(checkKit(base()).problems).toEqual([])
  })
  it('refuses a placeholder for a parameter that is NOT secret (a secret field would then carry a plain parameter), and for an undeclared one', () => {
    const k = base(); (k.proxy.sinks.s.config as any).password = '${PLAIN}'
    expect(checkKit(k).problems[0].sentence).toMatch(/credential is written out at proxy.yaml:sinks.s.config.password/)
    const u = base(); (u.proxy.sinks.s.config as any).password = '${NOPE}'
    expect(checkKit(u).problems[0].sentence).toMatch(/credential is written out/)
  })
  it('still refuses a literal, and takes env: and file: references', () => {
    const k = base(); (k.proxy.sinks.s.config as any).password = 'hunter2'
    expect(checkKit(k).ok).toBe(false)
    for (const ref of ['env:DB_PASS', 'file:/run/secrets/db']) { const r = base(); (r.proxy.sinks.s.config as any).password = ref; expect(checkKit(r).problems).toEqual([]) }
  })
  it('lists every problem, not only the first, each with the file and rule it breaks', () => {
    const k = base()
    ;(k.manifest as any).rollback = 'never'
    ;(k.proxy.sinks.s.config as any).host = 'db.example.com'
    const r = checkKit(k)
    expect(r.problems.length).toBeGreaterThanOrEqual(2)
    expect(r.problems.map((p) => p.rule)).toEqual(expect.arrayContaining(['schema', 'destination']))
    for (const p of r.problems) { expect(p.file).toMatch(/yaml|kit/); expect(p.sentence.length).toBeGreaterThan(10) }
  })
})

describe('the two pure rules', () => {
  it('finds a written-out credential by the key\'s own name, at any depth, never repeating its value', () => {
    expect(writtenOutSecrets({ a: { api_key: 'abc', note: 'x', client_secret: 'env:OK' }, b: [{ token: 'zzz' }] }, 'proxy.yaml:')).toEqual(['proxy.yaml:a.api_key', 'proxy.yaml:b[0].token'])
  })
  it('names a destination that is not a declared parameter, and a default that is not local', () => {
    const proxy = { sinks: { s: { config: { host: 'db.example.com', url: '${U}.evil', database: '${DB}', path: '${P}' } } } }
    const manifest = { parameters: { DB: { default: 'prod' }, P: { default: '/etc/x' } } }
    expect(destinationRefusals(proxy, manifest)).toEqual(['migration.yaml:parameters.P.default', 'proxy.yaml:sinks.s.config.host', 'proxy.yaml:sinks.s.config.url'])
  })
})
