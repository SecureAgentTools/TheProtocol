/**
 * V0663 (order gwo_e3187dbb237a06e8261c1dfc): the console draws the remaining outside images (peer registries' logos,
 * developer avatars, flare logos) only from the registry: GET /public/images?src=<address>, which serves an address one
 * of its records names, fetched once through its outbound guard. services/registryImage.registryImageSrc is the one way
 * there; UserAvatar (every avatar), FlareBadge (every flare logo) and services/peerAssets.resolvePeerAsset (every peer
 * registry logo) draw through it.
 * Red on a750d146d: the helper does not exist and the three draw the record's address.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { registryImageSrc } from './registryImage'
import { resolvePeerAsset } from './peerAssets'
import UserAvatar from '@/components/common/UserAvatar.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'

const route = (a: string) => `/api/v1/public/images?src=${encodeURIComponent(a)}`

describe('registryImageSrc', () => {
  it('sends an outside address to the registry', () => {
    expect(registryImageSrc('https://pics.example.org/ann.png')).toBe(route('https://pics.example.org/ann.png'))
    expect(registryImageSrc(' http://pics.example.org/a.png ')).toBe(route('http://pics.example.org/a.png'))
    expect(registryImageSrc('data:image/png;base64,iVBORw0KGgo=')).toBe(route('data:image/png;base64,iVBORw0KGgo='))
  })

  it("keeps a path on this origin, the registry's own routes included", () => {
    expect(registryImageSrc('/static/registry-cards/eu/icon.png')).toBe('/static/registry-cards/eu/icon.png')
    expect(registryImageSrc('/api/v1/agent-cards/did%3Ax/icon?v=1')).toBe('/api/v1/agent-cards/did%3Ax/icon?v=1')
    expect(registryImageSrc(`${window.location.origin}/static/a.png`)).toBe(`${window.location.origin}/static/a.png`)
  })

  it('draws nothing for an address it will not send anywhere', () => {
    for (const a of [null, undefined, 5, '', '   ', '//evil.example.org/x.png', 'javascript:alert(1)', 'ftp://x.example.org/a.png',
      'data:text/html,<script>alert(1)</script>']) {
      expect(registryImageSrc(a as any), String(a)).toBe(null)
    }
  })
})

describe('the three places that draw them', () => {
  it('UserAvatar draws an outside avatar from the registry, and a route of its own as it is', () => {
    const outside = mount(UserAvatar, { props: { user: { name: 'Ann' }, avatarUrl: 'https://pics.example.org/ann.png', displayName: 'Ann' } })
    expect(outside.find('img').attributes('src')).toBe(route('https://pics.example.org/ann.png'))
    const own = mount(UserAvatar, { props: { user: { name: 'A' }, avatarUrl: '/api/v1/agent-cards/did%3Ax/icon?v=1', displayName: 'A' } })
    expect(own.find('img').attributes('src')).toBe('/api/v1/agent-cards/did%3Ax/icon?v=1')
  })

  it("UserAvatar draws the owner's own unsaved address as typed only when told to (the profile preview)", () => {
    const w = mount(UserAvatar, { props: { user: { name: 'Ann' }, avatarUrl: 'https://pics.example.org/new.png', displayName: 'Ann', direct: true } })
    expect(w.find('img').attributes('src')).toBe('https://pics.example.org/new.png')
  })

  it('FlareBadge draws a flare logo from the registry', () => {
    const w = mount(FlareBadge, { props: { tier: 'architect', logoUrl: 'https://brand.example.org/flare.svg', size: 'lg', displayName: 'Acme' } })
    const img = w.findAll('img').find((i) => (i.attributes('src') || '').includes('flare.svg'))
    expect(img, w.html().slice(0, 400)).toBeTruthy()
    expect(img!.attributes('src')).toBe(route('https://brand.example.org/flare.svg'))
  })

  it("resolvePeerAsset sends a peer's logo to the registry, on the peer's own origin", () => {
    expect(resolvePeerAsset('/static/registry-cards/asia/icon.png', 'https://asia.example.org'))
      .toBe(route('https://asia.example.org/static/registry-cards/asia/icon.png'))
    expect(resolvePeerAsset('https://asia.example.org/i.png', 'https://asia.example.org')).toBe(route('https://asia.example.org/i.png'))
    expect(resolvePeerAsset('/static/registry-cards/own/icon.png', null)).toBe('/static/registry-cards/own/icon.png')
    expect(resolvePeerAsset(null, 'https://asia.example.org')).toBe(undefined)
  })
})
