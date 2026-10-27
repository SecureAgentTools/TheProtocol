import { describe, it, expect } from 'vitest'
import { registryBase, mcpEndpoints, mcpToolsetUrl, sdkSnippetHost, rosterDecision, tickerState, FLAGSHIP_API_ORIGIN } from './frameHost'

describe('§FRESHFRAME registryBase — the page addresses the host that serves it', () => {
  it('a fresh frame addresses itself', () => {
    expect(registryBase('https://sandbox-a.theprotocol.cloud')).toBe('https://sandbox-a.theprotocol.cloud')
    expect(registryBase('https://hansa.example.org/')).toBe('https://hansa.example.org')
    expect(registryBase('http://localhost:5173')).toBe('http://localhost:5173')
  })
  it('the apex publishes the flagship documented address (the bare /mcp 301s on the apex, measured)', () => {
    expect(registryBase('https://theprotocol.cloud')).toBe(FLAGSHIP_API_ORIGIN)
    expect(registryBase('https://www.theprotocol.cloud')).toBe(FLAGSHIP_API_ORIGIN)
    expect(registryBase('https://api.theprotocol.cloud')).toBe(FLAGSHIP_API_ORIGIN)
  })
  it('a console under the same domain is NOT the apex (eu., sandbox-a. address themselves)', () => {
    expect(registryBase('https://eu.theprotocol.cloud')).toBe('https://eu.theprotocol.cloud')
  })
})

describe('§FRESHFRAME mcpEndpoints — forms every console vhost routes', () => {
  const e = mcpEndpoints('https://sandbox-a.theprotocol.cloud')
  it('sse under /mcp/, gateway and toolsets under /mcp/rpc', () => {
    expect(e.publicSse).toBe('https://sandbox-a.theprotocol.cloud/mcp/sse')
    expect(e.adminSse).toBe('https://sandbox-a.theprotocol.cloud/mcp/admin/sse')
    expect(e.gateway).toBe('https://sandbox-a.theprotocol.cloud/mcp/rpc?mode=gateway')
    expect(e.toolsets).toBe('https://sandbox-a.theprotocol.cloud/mcp/rpc?toolsets=wallet,discovery')
  })
  it('never the bare /mcp?mode= form (a POST 301 is a POST downgraded)', () => {
    for (const u of [e.publicSse, e.adminSse, e.gateway, e.toolsets]) expect(u).not.toMatch(/\/mcp\?/)
  })
  it('the on-screen short forms drop the scheme, the mode forms drop the host too', () => {
    expect(e.publicSseShort).toBe('sandbox-a.theprotocol.cloud/mcp/sse')
    expect(e.gatewayShort).toBe('/mcp/rpc?mode=gateway')
    expect(e.toolsetsShort).toBe('/mcp/rpc?toolsets=wallet,discovery')
  })
  it('a toolset-scoped endpoint (the Pocket connect page) takes the /mcp/rpc form too', () => {
    expect(mcpToolsetUrl('https://sandbox-a.theprotocol.cloud/', 'pocket')).toBe('https://sandbox-a.theprotocol.cloud/mcp/rpc?toolsets=pocket')
  })
  it('on the flagship the four are the documented api. address', () => {
    const f = mcpEndpoints(registryBase('https://theprotocol.cloud'))
    expect(f.publicSse).toBe('https://api.theprotocol.cloud/mcp/sse')
    expect(f.adminSseShort).toBe('api.theprotocol.cloud/mcp/admin/sse')
  })
})

describe('§FRESHFRAME sdkSnippetHost — the snippets print this frame', () => {
  it('registry base, bare host, and the trust domain from the card', () => {
    const s = sdkSnippetHost('https://sandbox-a.theprotocol.cloud', 'sandbox-a.theprotocol.cloud')
    expect(s).toEqual({ registryUrl: 'https://sandbox-a.theprotocol.cloud', host: 'sandbox-a.theprotocol.cloud', trustDomain: 'sandbox-a.theprotocol.cloud' })
  })
  it('no trust domain known → the host stands in (never a flagship literal)', () => {
    const s = sdkSnippetHost('https://hansa.example.org', '')
    expect(s.trustDomain).toBe('hansa.example.org')
    expect(JSON.stringify(s)).not.toContain('agentvault.com')
    expect(JSON.stringify(s)).not.toContain('frame-b')
  })
})

describe('§FRESHFRAME rosterDecision — the server says whether the flagship roster is published here', () => {
  it('unknown until the rail answers', () => { expect(rosterDecision(null)).toBe('unknown'); expect(rosterDecision(undefined)).toBe('unknown') })
  it('sandbox-a today: disabled with a reason → absent', () => {
    expect(rosterDecision({ agents: [], count: 0, enabled: false })).toBe('absent')
  })
  it('the flagship today: eleven agents and no enabled key → here', () => {
    expect(rosterDecision({ agents: new Array(11).fill({}), count: 11 })).toBe('here')
  })
  it('enabled but nothing listed → absent (a roster with nobody on it is not a roster)', () => {
    expect(rosterDecision({ agents: [], count: 0 })).toBe('absent')
  })
})

describe('§FRESHFRAME tickerState — empty is not an outage and an outage is not empty', () => {
  it('live while any venue lists', () => { expect(tickerState(true, 1, null)).toBe('live'); expect(tickerState(false, 2, 'x')).toBe('live') })
  it('loading before the first answer', () => { expect(tickerState(false, 0, null)).toBe('loading') })
  it('empty after an answer with no venue', () => { expect(tickerState(true, 0, null)).toBe('empty') })
  it('unreachable after a failed answer', () => { expect(tickerState(true, 0, 'Network Error')).toBe('unreachable') })
})
