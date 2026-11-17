import { describe, expect, it } from 'vitest'
import { agentAvatarUser, agentAvatarUrl, cardIconSrc, rawCardIcon } from './agentAvatar'

describe('agentAvatar: an agent drawn as its owner dressed it', () => {
  it("reads SYBIL's ring and overlay from its card, where EU keeps them", () => {
    // the shape EU's discover row carries for SYBIL on 2026-10-23: the flare nested, no top-level tier
    const sybil = { name: 'SYBIL', did: 'did:theprotocol:eu.theprotocol.cloud:bafbca1e', flare_tier: null,
      rawCardData: { flare: { tier: 'sovereign', encirclement_variant: 'panopticon', encirclement_overlay: 'glitch' } } }
    const u = agentAvatarUser(sybil)!
    expect(u.flare_tier).toBe('sovereign')
    expect(u.flare_encirclement_variant).toBe('panopticon')
    expect(u.flare_encirclement_overlay).toBe('glitch')
  })

  it('takes the nested value first and lets the hoisted one fill in', () => {
    const u = agentAvatarUser({ name: 'A', agent_did: 'did:x', flare_tier: 'gold', flare_tagline: 'hoisted',
      card_data: { flare: { tier: 'sovereign' } } })!
    expect(u.did).toBe('did:x')
    expect(u.flare_tier).toBe('sovereign')
    expect(u.flare_tagline).toBe('hoisted')
    expect(u.bears_corner_flare).toBe(false)
  })

  it("finds the agent's own picture wherever its card or row carries it, and nothing otherwise", () => {
    expect(rawCardIcon({ rawCardData: { iconUrl: 'https://a/i.png' } })).toBe('https://a/i.png')
    expect(rawCardIcon({ card_data: { icon_url: 'https://b/i.png' } })).toBe('https://b/i.png')
    expect(rawCardIcon({ icon_url: 'https://c/i.png' })).toBe('https://c/i.png')
    expect(rawCardIcon({ rawCardData: {} })).toBe(null)
    expect(rawCardIcon(null)).toBe(null)
    expect(agentAvatarUser(null)).toBe(null)
  })
})

/* V0662, item 14 (order gwo_d721ad2f8118863d62815103): the console draws a card's icon only from the registry, which
   fetched it once through its outbound guard and serves it from its own origin (GET /agent-cards/{did}/icon). A
   reader's browser no longer dials the address a card names. */
describe('cardIconSrc: a card icon comes from the registry', () => {
  const did = 'did:theprotocol:eu.theprotocol.cloud:8db7b75e-6d87-4a1e-b530-42effe5787ab'

  it("names the registry's icon route for the card, never the card's own address", () => {
    const src = cardIconSrc(did, 'https://tracker.example.org/i.png')!
    expect(src.startsWith(`/api/v1/agent-cards/${encodeURIComponent(did)}/icon?v=`)).toBe(true)
    expect(src).not.toContain('tracker.example.org')
  })

  it('changes its address when the card names another icon, so a cached old one is not shown', () => {
    const a = cardIconSrc(did, 'https://i.example.org/v1.png')
    const b = cardIconSrc(did, 'https://i.example.org/v2.png')
    expect(a).not.toBe(b)
    expect(cardIconSrc(did, ' https://i.example.org/v1.png ')).toBe(a)
  })

  it('draws the initial when there is no icon or no DID to ask for it by', () => {
    expect(cardIconSrc(did, null)).toBe(null)
    expect(cardIconSrc(did, '   ')).toBe(null)
    expect(cardIconSrc(did, 5)).toBe(null)
    expect(cardIconSrc(null, 'https://i.example.org/a.png')).toBe(null)
    expect(cardIconSrc('not-a-did', 'https://i.example.org/a.png')).toBe(null)
  })

  it('is what agentAvatarUrl gives, for every place a row keeps its DID', () => {
    const icon = 'https://a.example.org/i.png'
    const want = cardIconSrc(did, icon)
    expect(agentAvatarUrl({ did, rawCardData: { iconUrl: icon } })).toBe(want)
    expect(agentAvatarUrl({ agent_did: did, card_data: { iconUrl: icon } })).toBe(want)
    expect(agentAvatarUrl({ card_data: { did, iconUrl: icon } })).toBe(want)
    expect(agentAvatarUrl({ did, icon_url: icon })).toBe(want)
    expect(agentAvatarUrl({ rawCardData: { iconUrl: icon } })).toBe(null)
  })
})
