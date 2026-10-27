import { describe, expect, it } from 'vitest'
import { resolvePeerAsset } from './peerAssets'

describe('resolvePeerAsset', () => {
  it('resolves a peer card\'s same-origin icon against the peer, not the viewer', () => {
    expect(resolvePeerAsset('/static/registry-cards/b/icon.png', 'https://sandbox-b.example.org/'))
      .toBe('https://sandbox-b.example.org/static/registry-cards/b/icon.png')
  })
  it('leaves an absolute address alone', () => {
    expect(resolvePeerAsset('https://cdn.example.org/i.png', 'https://peer.example.org')).toBe('https://cdn.example.org/i.png')
  })
  it('leaves a relative address alone when there is no peer host (our own registry)', () => {
    expect(resolvePeerAsset('/static/x.png', '')).toBe('/static/x.png')
    expect(resolvePeerAsset('/static/x.png', null)).toBe('/static/x.png')
  })
  it('never invents a host from something that is not one', () => {
    expect(resolvePeerAsset('/static/x.png', 'not a url')).toBe('/static/x.png')
  })
  it('answers nothing for nothing', () => {
    expect(resolvePeerAsset(undefined, 'https://p.example.org')).toBeUndefined()
    expect(resolvePeerAsset('', 'https://p.example.org')).toBeUndefined()
  })
})
