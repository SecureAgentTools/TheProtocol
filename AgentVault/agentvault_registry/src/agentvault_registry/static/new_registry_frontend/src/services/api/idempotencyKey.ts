/**
 * §FESUITE (2026-10-05): one Idempotency-Key per logical write, minted ONCE at the call site, so every send of that one
 * operation carries the same key and an endpoint that honours it answers a repeat from its claim instead of moving the
 * value twice. A key minted per attempt (inside a retry or an interceptor) is new on each send and dedupes nothing.
 * randomUUID needs a secure context and getRandomValues does not, so a console on plain http still gets a v4 UUID.
 */
type KeySource = { randomUUID?: () => string; getRandomValues?: (b: Uint8Array<ArrayBuffer>) => unknown } | undefined

export function newIdempotencyKey(c: KeySource = (globalThis as { crypto?: Crypto }).crypto): string {
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  if (typeof c?.getRandomValues === 'function') {
    const b = new Uint8Array(16)
    c.getRandomValues(b)
    b[6] = (b[6] & 0x0f) | 0x40
    b[8] = (b[8] & 0x3f) | 0x80
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
  }
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}
