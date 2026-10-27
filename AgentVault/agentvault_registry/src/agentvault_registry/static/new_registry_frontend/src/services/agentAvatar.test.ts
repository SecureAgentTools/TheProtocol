import { describe, expect, it } from 'vitest'
import { agentAvatarUser, agentAvatarUrl } from './agentAvatar'

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
    expect(agentAvatarUrl({ rawCardData: { iconUrl: 'https://a/i.png' } })).toBe('https://a/i.png')
    expect(agentAvatarUrl({ card_data: { icon_url: 'https://b/i.png' } })).toBe('https://b/i.png')
    expect(agentAvatarUrl({ icon_url: 'https://c/i.png' })).toBe('https://c/i.png')
    expect(agentAvatarUrl({ rawCardData: {} })).toBe(null)
    expect(agentAvatarUrl(null)).toBe(null)
    expect(agentAvatarUser(null)).toBe(null)
  })
})
