import { describe, it, expect, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { readAccessToken } from './accessToken'
import { config } from '@/config'

/** §FESUITE: one reader of the access token, and no call site reading a storage tier of its own. */
describe('readAccessToken', () => {
  beforeEach(() => { window.sessionStorage.clear(); window.localStorage.clear() })

  it('reads the session tier first, then the older local tier, and says null when neither holds a token', () => {
    expect(readAccessToken()).toBeNull()
    window.localStorage.setItem(config.auth.tokenKey, 'local')
    expect(readAccessToken()).toBe('local')
    window.sessionStorage.setItem(config.auth.tokenKey, 'session')
    expect(readAccessToken()).toBe('session')
  })
})

describe('no call site reads the access token from storage itself', () => {
  // The shapes that sent no token or "Bearer null": the token key by name, the config key, or a 'token' key nothing
  // writes. Comment lines are skipped (two files document the old bug in prose).
  const READS = /getItem\(\s*(?:['"](?:sovereign_auth_token|token)['"]|config\.auth\.tokenKey)\s*\)/
  const ALLOWED = new Set([path.join('services', 'accessToken.ts')])

  function sources(dir: string, out: string[] = []): string[] {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) sources(p, out)
      else if (/\.(ts|vue)$/.test(e.name) && !/\.(test|spec)\.ts$/.test(e.name)) out.push(p)
    }
    return out
  }

  it('finds none outside services/accessToken.ts', () => {
    const root = path.resolve(__dirname, '..')
    const files = sources(root)
    expect(files.length, 'the scan sees the source tree').toBeGreaterThan(300)
    const hits: string[] = []
    for (const f of files) {
      const rel = path.relative(root, f)
      if (ALLOWED.has(rel)) continue
      fs.readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
        const s = line.trim()
        if (s.startsWith('//') || s.startsWith('*') || s.startsWith('/*')) return
        if (READS.test(line)) hits.push(`${rel}:${i + 1}`)
      })
    }
    expect(hits).toEqual([])
  })

  it('the pattern catches each shape it names (its own control)', () => {
    for (const shape of ["localStorage.getItem('sovereign_auth_token')", 'sessionStorage.getItem("token")',
      'window.localStorage.getItem(config.auth.tokenKey)']) expect(READS.test(shape), shape).toBe(true)
    expect(READS.test("localStorage.getItem('beta_banner_dismissed')")).toBe(false)
  })
})
