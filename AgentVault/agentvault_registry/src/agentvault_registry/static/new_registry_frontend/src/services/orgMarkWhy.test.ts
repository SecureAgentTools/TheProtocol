/**
 * V0658 (r): why an organization's mark does not show (the maintainer found no organization logo anywhere on EU after
 * V0657, the sessions' room seq 2136). V0657 (b) states the mark on an agent's card only while the organization is
 * listed (`public_listing`, off by default), shows a logo only when this registry hosts it (organization_logos), and
 * never shows a `logo_url` from before. These pin which condition is missing for each state, which old logo address
 * can be offered for upload, and the file check made before a logo is sent.
 * RED on v0657/cut: services/orgMarkWhy.ts does not exist.
 */
import { describe, it, expect } from 'vitest'
import { orgMarkGaps, markShows, missingList, legacyLogo, logoFileProblem, LOGO_MAX_BYTES } from './orgMarkWhy'

const HOSTED = '/api/v1/organizations/org-1/logo?v=abc123def456'

describe('which condition keeps an organization\'s mark from showing', () => {
  it('not listed and no hosted logo: both are missing', () => {
    const g = orgMarkGaps({ listed: false, logo: null })
    expect(g.listing).toBe(true)
    expect(g.logo).toBe(true)
    expect(missingList(g)).toEqual(['listing', 'logo'])
    expect(markShows(g)).toBe(false)
  })

  it('not listed, with a hosted logo: only the listing is missing', () => {
    const g = orgMarkGaps({ listed: false, logo: HOSTED })
    expect(missingList(g)).toEqual(['listing'])
    expect(markShows(g)).toBe(false)
  })

  it('listed, with no hosted logo: only the logo is missing', () => {
    const g = orgMarkGaps({ listed: true, logo: null })
    expect(missingList(g)).toEqual(['logo'])
    expect(markShows(g)).toBe(false)
  })

  it('listed, with a hosted logo: nothing is missing and the mark shows', () => {
    const g = orgMarkGaps({ listed: true, logo: HOSTED })
    expect(missingList(g)).toEqual([])
    expect(markShows(g)).toBe(true)
  })

  it('reads the listing as the server does: only a true is listed (fail closed)', () => {
    for (const listed of [undefined, null, 'true' as unknown as boolean, 1 as unknown as boolean]) {
      expect(orgMarkGaps({ listed, logo: HOSTED }).listing, String(listed)).toBe(true)
    }
    expect(orgMarkGaps(null).listing).toBe(true)
    expect(orgMarkGaps(undefined).logo).toBe(true)
    expect(orgMarkGaps({ listed: true, logo: '  ' }).logo, 'a blank logo is no logo').toBe(true)
  })
})

describe('the old logo address an owner is offered for upload', () => {
  it('an https address can be shown here; an http one only opened (the console allows https images only)', () => {
    expect(legacyLogo('https://old.example/brand/logo.png')).toEqual(
      { href: 'https://old.example/brand/logo.png', host: 'old.example', showable: true })
    expect(legacyLogo(' http://old.example:8080/l.jpg ')).toEqual(
      { href: 'http://old.example:8080/l.jpg', host: 'old.example:8080', showable: false })
  })

  it('anything that is not an http(s) address is not offered', () => {
    for (const v of ['', '   ', 'logo.png', '/static/logo.png', '//old.example/l.png', 'javascript:alert(1)',
      'data:image/png;base64,AAAA', 'ftp://old.example/l.png', null, undefined, 42]) {
      expect(legacyLogo(v as any), String(v)).toBeNull()
    }
  })

  it('is offered only while no logo is hosted here', () => {
    const old = 'https://old.example/logo.png'
    expect(orgMarkGaps({ listed: false, logo: null, logo_url: old }).legacy?.href).toBe(old)
    expect(orgMarkGaps({ listed: true, logo: null, logo_url: old }).legacy?.host).toBe('old.example')
    expect(orgMarkGaps({ listed: false, logo: HOSTED, logo_url: old }).legacy, 'a hosted logo replaces it').toBeNull()
    expect(orgMarkGaps({ listed: true, logo: null, logo_url: null }).legacy).toBeNull()
  })
})

describe('the file check made before a logo is sent (the server\'s own rule)', () => {
  it('a PNG or a JPEG of at most 256 KB passes; a bigger file or another type does not', () => {
    expect(LOGO_MAX_BYTES).toBe(256 * 1024)
    expect(logoFileProblem({ size: 10, type: 'image/png' })).toBeNull()
    expect(logoFileProblem({ size: LOGO_MAX_BYTES, type: 'image/jpeg' })).toBeNull()
    expect(logoFileProblem({ size: LOGO_MAX_BYTES + 1, type: 'image/png' })).toBe('tooBig')
    expect(logoFileProblem({ size: 10, type: 'image/svg+xml' })).toBe('wrongType')
    expect(logoFileProblem({ size: 10, type: '' })).toBe('wrongType')
  })
})
