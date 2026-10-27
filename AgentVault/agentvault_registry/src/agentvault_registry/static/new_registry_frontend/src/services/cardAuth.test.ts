import { describe, it, expect } from 'vitest'
import { cardAuthSchemes, needsOwnCredential } from './cardAuth'

// §CARDAUTH: a card declares its auth in one of two legal places, like its price. Sundial (journal 52's worked example)
// declares an API key in an A2A v1.0 securitySchemes map; the console read only the legacy authSchemes list.
const sundial = {
  securitySchemes: {
    sundial_key: { type: 'apiKey', in: 'header', name: 'X-Sundial-Key', description: 'Get a key at https://example/keys: 100 calls a day free.' },
  },
  security: [{ sundial_key: [] }],
}

describe('the auth a card declares, in either dialect', () => {
  it('reads an A2A v1.0 apiKey scheme with its header and its own words', () => {
    const rows = cardAuthSchemes(sundial)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ scheme: 'apiKey', name: 'sundial_key', header: 'X-Sundial-Key', query: null, declared: true })
    expect(rows[0].description).toContain('100 calls a day')
    expect(needsOwnCredential(rows)).toBe(true)
  })

  it('keeps a legacy authSchemes list as it is (the control)', () => {
    const legacy = [{ scheme: 'none', scopes: null, tokenUrl: null }]
    expect(cardAuthSchemes({ authSchemes: legacy, ...sundial })).toBe(legacy)
    expect(needsOwnCredential(legacy)).toBe(false)
  })

  it('names bearer, basic, oauth2, OpenID Connect and mutual TLS, in the order security asks for them', () => {
    const rows = cardAuthSchemes({
      securitySchemes: {
        tls: { type: 'mutualTLS' },
        b: { type: 'http', scheme: 'bearer' },
        basic: { type: 'http', scheme: 'basic' },
        o: { type: 'oauth2', flows: { clientCredentials: { tokenUrl: 'https://example/token', scopes: {} } } },
        oidc: { type: 'openIdConnect', openIdConnectUrl: 'https://example/.well-known/openid-configuration' },
        unused: { type: 'apiKey', in: 'query', name: 'k' },
      },
      security: [{ o: [] }, { b: [], tls: [] }, { oidc: [] }, { basic: [] }],
    })
    expect(rows.map((r) => r.scheme)).toEqual(['oauth2', 'bearer', 'mtls', 'openIdConnect', 'basic'])
    expect(rows[0].tokenUrl).toBe('https://example/token')
    expect(rows[3].tokenUrl).toContain('openid-configuration')
  })

  it('without a security requirement, shows every declared scheme; an empty requirement means a call may come without one', () => {
    expect(cardAuthSchemes({ securitySchemes: { q: { type: 'apiKey', in: 'query', name: 'key' } } })[0])
      .toMatchObject({ scheme: 'apiKey', query: 'key', header: null })
    const optional = cardAuthSchemes({ securitySchemes: { k: { type: 'apiKey', in: 'header', name: 'X-K' } }, security: [{}, { k: [] }] })
    expect(optional.map((r) => r.scheme)).toEqual(['apiKey', 'none'])
  })

  it('declares nothing when the card says nothing, or says it in a shape it cannot read', () => {
    expect(cardAuthSchemes(null)).toEqual([])
    expect(cardAuthSchemes({})).toEqual([])
    expect(cardAuthSchemes({ securitySchemes: ['apiKey'] })).toEqual([])
    expect(cardAuthSchemes({ securitySchemes: { k: { type: 'apiKey', in: 'header', name: 'X-K' } }, security: [{ missing: [] }] })).toEqual([])
    expect(needsOwnCredential([])).toBe(false)
  })
})
