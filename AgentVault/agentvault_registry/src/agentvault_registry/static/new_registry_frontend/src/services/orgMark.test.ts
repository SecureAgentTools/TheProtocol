/**
 * V0657 (b): the organization mark, as an agent's home registry states it (services/orgMark.ts).
 *  - read from the card's extension, or from the discover list's `org` field;
 *  - the logo is loaded only from this origin or, https, from under the mark's own home origin (a card can never send
 *    a viewer's browser to a third party);
 *  - a click goes to this console's page for an organization here, else to its home's page, else nowhere.
 * RED on e143dd798: the module does not exist.
 */
import { describe, it, expect } from 'vitest'
import { ORG_EXTENSION_URI, orgMarkFromParams, orgMarkLink, orgMarkOf, safeLogo } from './orgMark'

const params = {
  version: 1, id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions',
  logo: 'https://eu.example/api/v1/organizations/org-1/logo?v=abc',
  home: { name: 'EU', origin: 'https://eu.example', console: 'https://eu.example/ui' },
  page: 'https://eu.example/ui/#/firms?org=sessions',
}

describe('the organization mark', () => {
  it('is read from the card extension its home stated, and from the discover list', () => {
    const cd = { name: 'a', extensions: [{ uri: 'x:other' }, { uri: ORG_EXTENSION_URI, params }] }
    expect(orgMarkOf(cd)).toMatchObject({ id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions' })
    expect(orgMarkOf(JSON.stringify(cd))?.home?.origin).toBe('https://eu.example')
    expect(orgMarkFromParams(params)?.page).toBe(params.page)
    expect(orgMarkOf({ name: 'a', provider: { name: 'Acme Labs' } }), 'provider.name is no mark').toBeNull()
    expect(orgMarkFromParams({ id: 'org-1' }), 'a mark names its organization').toBeNull()
    expect(orgMarkOf('not json')).toBeNull()
  })

  it('loads a logo only from this origin or from under its own home', () => {
    const m = orgMarkFromParams(params)!
    expect(safeLogo(m)).toBe(params.logo)
    expect(safeLogo({ logo: '/api/v1/organizations/org-1/logo?v=1', home: null })).toBe('/api/v1/organizations/org-1/logo?v=1')
    for (const logo of ['https://tracker.example/pixel.png', 'http://eu.example/api/v1/organizations/org-1/logo',
      'javascript:alert(1)', 'https://eu.example/static/evil.png', '//tracker.example/api/v1/organizations/x/logo']) {
      expect(safeLogo({ ...m, logo }), logo).toBeNull()
    }
    expect(safeLogo({ logo: params.logo, home: { origin: null } }), 'no home origin, no remote logo').toBeNull()
  })

  it('links to this console for a local organization, to its home otherwise', () => {
    const m = orgMarkFromParams(params)!
    expect(orgMarkLink(m, true)).toEqual({ kind: 'route', to: { name: 'public-firms', query: { org: 'sessions' } } })
    expect(orgMarkLink(m, false)).toEqual({ kind: 'external', href: params.page })
    expect(orgMarkLink({ ...m, page: 'javascript:alert(1)' }, false)).toBeNull()
    expect(orgMarkLink(null, true)).toBeNull()
  })
})
