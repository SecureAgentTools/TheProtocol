/**
 * TOTP (RFC 6238: HMAC-SHA1, 30-second steps, 6 digits) for the suite's 2FA lifecycle (§FESUITE). The secret is the one
 * the page shows a person to type into an authenticator; the suite types the code a person's phone would show.
 */
import crypto from 'node:crypto'

function base32Decode(input: string): Buffer {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  const clean = input.replace(/[\s=-]/g, '').toUpperCase()
  let bits = 0
  let value = 0
  const out: number[] = []
  for (const ch of clean) {
    const idx = alphabet.indexOf(ch)
    if (idx < 0) throw new Error('not a base32 secret')
    value = (value << 5) | idx
    bits += 5
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff)
      bits -= 8
    }
  }
  return Buffer.from(out)
}

/** The 30-second step a moment falls in. */
export function totpStep(at = Date.now()): number {
  return Math.floor(at / 1000 / 30)
}

export function totp(secret: string, step = totpStep()): string {
  const key = base32Decode(secret)
  const msg = Buffer.alloc(8)
  msg.writeBigUInt64BE(BigInt(step))
  const h = crypto.createHmac('sha1', key).update(msg).digest()
  const off = h[h.length - 1] & 0x0f
  const code = ((h.readUInt32BE(off) & 0x7fffffff) % 1_000_000).toString()
  return code.padStart(6, '0')
}

/** Wait until the clock enters a step after `used` (a server refuses a code it has already accepted). */
export async function nextStepAfter(used: number): Promise<number> {
  while (totpStep() <= used) await new Promise((r) => setTimeout(r, 500))
  return totpStep()
}
