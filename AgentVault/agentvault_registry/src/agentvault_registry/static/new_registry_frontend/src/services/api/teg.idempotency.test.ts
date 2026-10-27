/**
 * §FESUITE (2026-10-05): every value-moving POST of the TEG service carries its own Idempotency-Key, minted once per
 * call at the call site (a key minted per attempt would be new on a re-send and dedupe nothing).
 */
import { describe, expect, it, vi } from 'vitest'
import { TegApi } from './teg'
import { newIdempotencyKey } from './idempotencyKey'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function service() {
  const posts: Array<{ url: string; key: unknown }> = []
  const client = {
    post: vi.fn(async (url: string, _body: unknown, cfg?: { headers?: Record<string, unknown> }) => {
      posts.push({ url, key: cfg?.headers?.['Idempotency-Key'] })
      return { data: {} }
    }),
  }
  return { api: new TegApi(client as any), posts }
}

describe('the TEG service sends a key with every value-moving POST', () => {
  it('each of the four, a different key per call', async () => {
    const { api, posts } = service()
    await api.transfer({ receiver_agent_id: 'did:theprotocol:r', amount: '1' })
    await api.transfer({ receiver_agent_id: 'did:theprotocol:r', amount: '1' })     // the same transfer pressed twice
    await api.systemTransfer({ amount: '1', purpose: 'fee' })
    await api.smartSend({ receiver_did: 'did:theprotocol:r', amount: '1' })
    await api.transferCrossRegistry({} as any)

    expect(posts.map(p => p.url)).toEqual(['/teg/transfer', '/teg/transfer', '/teg/system-transfer', '/teg/send',
      '/teg/cross-registry-transfer'])
    for (const p of posts) expect(p.key, p.url).toMatch(UUID_V4)
    expect(new Set(posts.map(p => p.key)).size).toBe(posts.length)   // a second press is a second operation
  })
})

describe('a send asked again after an unknown outcome', () => {
  it('carries the key its caller holds for that request', async () => {
    const { api, posts } = service()
    await api.smartSend({ receiver_did: 'did:theprotocol:r', amount: '1' }, { idempotencyKey: 'the-request-key' })
    await api.smartSend({ receiver_did: 'did:theprotocol:r', amount: '1' }, { idempotencyKey: 'the-request-key' })
    expect(posts.map(p => p.key)).toEqual(['the-request-key', 'the-request-key'])
  })
})

describe('the key', () => {
  it('is a v4 UUID with or without crypto.randomUUID (plain http has only getRandomValues)', () => {
    expect(newIdempotencyKey()).toMatch(UUID_V4)
    const real = globalThis.crypto
    const httpOnly = { getRandomValues: (b: Uint8Array<ArrayBuffer>) => real.getRandomValues(b) }
    const a = newIdempotencyKey(httpOnly)
    const b = newIdempotencyKey(httpOnly)
    expect(a).toMatch(UUID_V4)
    expect(b).not.toBe(a)
    // every bit set: only the version and variant bits the fallback writes can make this a v4 UUID
    const allOnes = { getRandomValues: (x: Uint8Array<ArrayBuffer>) => x.fill(0xff) }
    expect(newIdempotencyKey(allOnes)).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff')
  })
})
