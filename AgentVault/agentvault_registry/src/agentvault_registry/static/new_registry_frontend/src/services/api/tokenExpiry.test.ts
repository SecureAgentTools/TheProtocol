import { describe, it, expect } from 'vitest'
import { isJwtExpired, jwtExpiresAt } from './tokenExpiry'
import { batchedPost } from './batchedPost'

function jwt(payload: Record<string, unknown>): string {
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.sig`
}

describe('§BATCH8 item 9 — the pre-flight expiry read', () => {
  it('reads exp and calls a past token expired, a future one not', () => {
    const now = 1_800_000_000_000
    expect(isJwtExpired(jwt({ exp: now / 1000 - 60 }), now)).toBe(true)
    expect(isJwtExpired(jwt({ exp: now / 1000 + 600 }), now)).toBe(false)
    expect(jwtExpiresAt(jwt({ exp: 1700000000 }))).toBe(1700000000 * 1000)
  })
  it('never calls an unreadable or exp-less token expired (the server decides those)', () => {
    expect(isJwtExpired('not-a-jwt')).toBe(false)
    expect(isJwtExpired(null)).toBe(false)
    expect(isJwtExpired(jwt({ sub: 'x' }))).toBe(false)
  })
  it('applies the skew inside the window', () => {
    const now = 1_800_000_000_000
    expect(isJwtExpired(jwt({ exp: now / 1000 + 2 }), now, 5000)).toBe(true)
    expect(isJwtExpired(jwt({ exp: now / 1000 + 2 }), now, 0)).toBe(false)
  })
})

describe('§BATCH8 item 9 — bounded batches that stop on the first 401', () => {
  const dids = Array.from({ length: 4130 }, (_, i) => `did:x:${i}`)
  it('a dead session costs at most `concurrency` refusals, never 83', async () => {
    let calls = 0
    const post = async () => { calls++; throw { response: { status: 401 } } }
    const r = await batchedPost(dids, post, { chunkSize: 50, concurrency: 4 })
    expect(r.stoppedOn401).toBe(true)
    expect(r.requests).toBeLessThanOrEqual(4)
    expect(calls).toBe(r.requests)
    expect(r.results).toEqual([])
  })
  it('a live session walks every chunk with the window and keeps every result', async () => {
    let inFlight = 0, peak = 0
    const post = async (chunk: string[]) => {
      inFlight++; peak = Math.max(peak, inFlight)
      await new Promise(r => setTimeout(r, 1))
      inFlight--
      return chunk.length
    }
    const r = await batchedPost(dids, post, { chunkSize: 50, concurrency: 4 })
    expect(r.requests).toBe(83)
    expect(r.results.reduce((a, b) => a + b, 0)).toBe(4130)
    expect(peak).toBeLessThanOrEqual(4)
    expect(r.stoppedOn401).toBe(false)
  })
  it('a non-401 failure still propagates (the control: the helper hides nothing else)', async () => {
    const post = async () => { throw { response: { status: 500 } } }
    await expect(batchedPost(dids.slice(0, 10), post)).rejects.toMatchObject({ response: { status: 500 } })
  })
})
