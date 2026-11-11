/**
 * D6-850: a new device's registration waits for an enrolled device's approval. The registry answers 428
 * step_up_required naming a challenge; the console sends the SAME registration again with that challenge until it is
 * registered, refused, or time runs out.
 */
import { describe, it, expect, vi } from 'vitest'
import { registerDeviceCredential } from './usePocketLock'

const body = { attestation_object: 'att', client_data_json: 'cdj' }
const noSleep = async () => {}

function step428(challengeId: string, reason = 'an enrolled device approves a new one',
                 methods: string[] = ['device'], facts: Record<string, unknown> = { code: 'K7Q-29M' }) {
  const e: any = new Error('428')
  e.response = { status: 428, data: { error: 'step_up_required', step_up: {
    challenge_id: challengeId, reason, challenge_hash: 'ab', facts, methods } } }
  return e
}

describe('registerDeviceCredential (D6-850)', () => {
  it('sends once and is done when the registry takes the device', async () => {
    const post = vi.fn().mockResolvedValue({ data: { ok: true } })
    expect(await registerDeviceCredential(post, body, () => {}, { sleep: noSleep })).toBe('registered')
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toEqual(body)
  })

  it('waits for the enrolled device and resends with the challenge the 428 named', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(step428('lch_a'))
      .mockRejectedValueOnce(step428('lch_a', 'waiting for an enrolled device to approve'))
      .mockResolvedValue({ data: { ok: true } })
    const waits: string[] = []
    expect(await registerDeviceCredential(post, body, (r) => waits.push(r), { sleep: noSleep })).toBe('registered')
    expect(post.mock.calls.map((c) => c[0].confirm_challenge_id)).toEqual([undefined, 'lch_a', 'lch_a'])
    expect(waits).toEqual(['an enrolled device approves a new one', 'waiting for an enrolled device to approve'])
  })

  it('follows a challenge the registry minted anew', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(step428('lch_a'))
      .mockRejectedValueOnce(step428('lch_b', 'challenge expired — expiry is a denial'))
      .mockResolvedValue({ data: { ok: true } })
    await registerDeviceCredential(post, body, () => {}, { sleep: noSleep })
    expect(post.mock.calls[2][0].confirm_challenge_id).toBe('lch_b')
  })

  it('throws any other refusal as it came', async () => {
    const refused: any = new Error('422')
    refused.response = { status: 422, data: { detail: 'Credential refused: origin_mismatch' } }
    const post = vi.fn().mockRejectedValue(refused)
    await expect(registerDeviceCredential(post, body, () => {}, { sleep: noSleep })).rejects.toBe(refused)
  })

  it('passes the code both screens show to the waiting note', async () => {
    const post = vi.fn().mockRejectedValueOnce(step428('lch_a')).mockResolvedValue({ data: { ok: true } })
    const codes: (string | null)[] = []
    await registerDeviceCredential(post, body, (_r, code) => codes.push(code), { sleep: noSleep })
    expect(codes).toEqual(['K7Q-29M'])
  })

  it('a first device on a 2FA account sends the authenticator code it was given', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(step428('lch_t', 'a first device takes a code from your authenticator app', ['totp']))
      .mockResolvedValue({ data: { ok: true } })
    const askCode = vi.fn().mockResolvedValue(' 123456 ')
    expect(await registerDeviceCredential(post, body, () => {}, { sleep: noSleep, askCode })).toBe('registered')
    expect(post.mock.calls[1][0]).toEqual({ ...body, totp_code: '123456' })
  })

  it('stops when no code is given, and after three wrong ones', async () => {
    const needsCode = () => step428('lch_t', 'that code is not current', ['totp'])
    let t = 0
    const clock = { sleep: noSleep, maxMs: 50, now: () => (t += 10) }   // an old loop times out instead of spinning
    const none = vi.fn().mockRejectedValue(needsCode())
    expect(await registerDeviceCredential(none, body, () => {}, { ...clock, askCode: async () => null }))
      .toBe('needs_code')
    t = 0
    const wrong = vi.fn().mockRejectedValue(needsCode())
    expect(await registerDeviceCredential(wrong, body, () => {}, { ...clock, askCode: async () => '000000' }))
      .toBe('needs_code')
    expect(wrong).toHaveBeenCalledTimes(4)   // the first send, then three codes
  })

  it('gives up when no enrolled device approves in time', async () => {
    let t = 0
    const post = vi.fn().mockRejectedValue(step428('lch_a'))
    const out = await registerDeviceCredential(post, body, () => {}, { maxMs: 10, now: () => (t += 6), sleep: noSleep })
    expect(out).toBe('timed_out')
  })
})
