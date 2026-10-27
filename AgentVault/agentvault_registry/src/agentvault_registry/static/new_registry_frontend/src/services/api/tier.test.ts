import { describe, it, expect } from 'vitest'
import { isAgentEndpoint } from './tier'

// §TRUSTCHAIN P4.6 (2026-09-12) — the dashboard's cockpit panes read
// /developers/me/agents?limit=500&sort=live&top_level_only=true and a transient 401 was
// measured during the login transition (§MARKSURFACES). The tier classifier is the first
// suspect for any 401 on a developer path (§COCKPITBOOK: a substring rule made
// /developers/me/exchange/portfolio an AGENT call). Pin the tiers that must never move.
describe('isAgentEndpoint', () => {
  it('the developer agent list is a DEVELOPER call, with and without its query', () => {
    expect(isAgentEndpoint('/developers/me/agents', 'get')).toBe(false)
    expect(isAgentEndpoint('/developers/me/agents?limit=500&sort=live&top_level_only=true', 'get')).toBe(false)
    expect(isAgentEndpoint('/developers/me/agents/balances', 'post')).toBe(false)
  })
  it('agent-tier rails stay agent-tier', () => {
    expect(isAgentEndpoint('/agents/spawn', 'post')).toBe(true)
    // §FESUITE V0595: cross-registry delegation, every method, acts as the agent
    expect(isAgentEndpoint('/agents/delegate-cross-registry', 'get')).toBe(true)
    expect(isAgentEndpoint('/agents/delegate-cross-registry', 'post')).toBe(true)
    expect(isAgentEndpoint('/agents/delegate-cross-registry/abc123', 'delete')).toBe(true)
    expect(isAgentEndpoint('/agents/act-token', 'post')).toBe(true)
    expect(isAgentEndpoint('/a2a-payment/authorize', 'post')).toBe(true)
  })
  it('developer-tier admin rails stay developer-tier', () => {
    expect(isAgentEndpoint('/admin/funding/pending', 'get')).toBe(false)
    expect(isAgentEndpoint('/teg/treasury/fund-agent', 'post')).toBe(false)
  })
})

// §AGORAWORDS Phase 5 (2026-09-22): every caller uses /agora/… since V0421; /exchange/… stays live until a later release.
// Both names must classify identically, and the developer-tier guard must hold for the new holdings book.
describe('the AGORA market under both names', () => {
  const both = (p: string) => [`/agora/${p}`, `/exchange/${p}`]
  it('orders, portfolio, passport, the launch purchase and share votes are AGENT-tier under either name', () => {
    for (const u of both('orders')) expect(isAgentEndpoint(u, 'post')).toBe(true)
    for (const u of both('orders/mine')) expect(isAgentEndpoint(u, 'get')).toBe(true)
    for (const u of both('portfolio')) expect(isAgentEndpoint(u, 'get')).toBe(true)
    for (const u of both('passport/orders')) expect(isAgentEndpoint(u, 'post')).toBe(true)
    for (const u of both('listings/ALFW/launch/buy')) expect(isAgentEndpoint(u, 'post')).toBe(true)
    for (const u of both('listings/ALFW/ipo/buy')) expect(isAgentEndpoint(u, 'post')).toBe(true)
    for (const u of both('proposals/7/vote')) expect(isAgentEndpoint(u, 'post')).toBe(true)
  })
  it('public reads and the developer-tier desk stay off the agent token under either name', () => {
    for (const u of both('listings')) expect(isAgentEndpoint(u, 'get')).toBe(false)
    for (const u of both('listings')) expect(isAgentEndpoint(u, 'post')).toBe(false)          // create a listing: developer
    for (const u of both('listings/ALFW/distributions')) expect(isAgentEndpoint(u, 'post')).toBe(false)
    for (const u of both('organizations/o1/treasury/ALFW/buy')) expect(isAgentEndpoint(u, 'post')).toBe(false)
    for (const u of both('admin/overview')) expect(isAgentEndpoint(u, 'get')).toBe(false)
    expect(isAgentEndpoint('/developers/me/holdings-book', 'get')).toBe(false)
    expect(isAgentEndpoint('/developers/me/share-book', 'get')).toBe(false)
  })
  it('only a LEADING /agora/ is the market: a federation relay path is not', () => {
    expect(isAgentEndpoint('/federation/agora-orders', 'post')).toBe(false)
  })
})

