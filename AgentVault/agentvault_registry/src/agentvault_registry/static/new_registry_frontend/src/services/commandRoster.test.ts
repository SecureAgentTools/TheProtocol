import { describe, it, expect } from 'vitest'
import { parseVault, parseCredsTsv } from './commandRoster'

/**
 * §BRIDGE R16.4 — the importer must read the file the credentials actually
 * live in, because connecting a registry is what makes its agents visible.
 */
const REAL = `# ME cloud-op admin accounts (supplied by Commander 2026-06-10)
# format: op<TAB>url<TAB>email<TAB>password

op-telaviv\thttps://op-telaviv.op.theprotocol.cloud\tadmin@cloud-op-op-telaviv.dev\tpw-one
op-riyadh\thttps://op-riyadh.op.theprotocol.cloud\tadmin@cloud-op-op-riyadh.dev\tpw-two`

describe('parseCredsTsv', () => {
  it('reads the real file shape, comments and blank lines included', () => {
    const v = parseCredsTsv(REAL)
    expect(Object.keys(v.registries).sort()).toEqual(['op-riyadh', 'op-telaviv'])
    expect(v.registries['op-telaviv'].developer).toEqual({
      email: 'admin@cloud-op-op-telaviv.dev', password: 'pw-one',
    })
  })

  it('finds the email by its @, so a missing URL column cannot swap the fields', () => {
    const v = parseCredsTsv('op-doha\tadmin@x.dev\tsecret')
    expect(v.registries['op-doha'].developer).toEqual({ email: 'admin@x.dev', password: 'secret' })
  })

  it('skips rows it cannot read rather than inventing a credential', () => {
    const v = parseCredsTsv('op-a\thttps://x\tno-at-sign\tpw\nop-b\thttps://y\tadmin@y.dev\n# c\n')
    expect(Object.keys(v.registries)).toEqual([])
  })

  it('never throws on junk', () => {
    for (const j of ['', '   ', '#only a comment', 'one'])
      expect(() => parseCredsTsv(j)).not.toThrow()
  })
})

describe('parseVault still prefers JSON', () => {
  it('reads a vault unchanged', () => {
    const v = parseVault('{"version":1,"registries":{"op-x":{"developer":{"email":"a@b.c","password":"p"}}}}')
    expect(v.registries['op-x'].developer!.email).toBe('a@b.c')
  })
  it('falls through to TSV instead of erroring on a credentials file', () => {
    expect(Object.keys(parseVault(REAL).registries).length).toBe(2)
  })
  it('still errors when the text carries no credentials at all', () => {
    expect(() => parseVault('hello world')).toThrow()
  })
})
