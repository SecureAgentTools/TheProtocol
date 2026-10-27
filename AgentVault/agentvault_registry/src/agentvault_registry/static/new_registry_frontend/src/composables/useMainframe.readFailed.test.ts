/**
 * §FESUITE (2026-10-09): a read that reached none of the three sources (the frame manifest, the registry card,
 * /federation/info) was decided as "not a mainframe" for the rest of the session. A console booted while the registry
 * could not answer kept Frame Management and OP Management locked after it was back, and the router told the admin of a
 * mainframe that "cloud-ops federate with the mainframe for these actions" (sweeps/recovery on V0587). Now it is no
 * decision: the gates stay closed as the safe side, readFailed says why, and the composable reads again on its own and
 * on the next access. The module's state is per session, so each test imports it fresh.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const manifest = vi.hoisted(() => ({ load: vi.fn() }))
vi.mock('@/composables/useFrameManifest', () => ({ loadFrameManifest: manifest.load }))

const fetchMock = vi.fn()
const answer = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
const MAINFRAME_CARD = { identity: { tier: 'sovereign-mainframe' }, federation: {}, capabilities: {} }
/** every source fails (the registry restarting) until `up` is set; then the card answers a mainframe */
let up = false

async function fresh() {
  vi.resetModules()
  return (await import('./useMainframe')).useMainframe
}
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }

describe('useMainframe when no source answers', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    up = false
    manifest.load.mockReset()
    manifest.load.mockImplementation(async () => { if (!up) throw new Error('no answer'); return null })
    fetchMock.mockReset()
    fetchMock.mockImplementation((url: string) => {
      if (!up) return Promise.reject(new TypeError('Failed to fetch'))
      if (String(url).includes('registry-card')) return answer(200, MAINFRAME_CARD)
      return answer(200, { is_mainframe: true, tier: 'sovereign-mainframe' })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('is no decision while the reads fail, and becomes the answer once the registry answers (it stayed "not a mainframe")', async () => {
    const useMainframe = await fresh()
    const mf = useMainframe()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    expect(mf.isMainframe.value, 'the gate stays closed while nothing is known').toBe(false)
    expect(mf.ready.value, 'a read that reached nothing is no decision').toBe(false)
    expect(mf.readFailed.value, 'and it says the read failed, not that this is a cloud operator').toBe(true)

    up = true
    await vi.advanceTimersByTimeAsync(5_000)
    await settle()
    expect(mf.isMainframe.value, 'read again on its own once the registry answers').toBe(true)
    expect(mf.readFailed.value).toBe(false)
    expect(mf.ready.value).toBe(true)
  })

  it('the next access reads again without waiting for the retry (a guard on the next navigation)', async () => {
    const useMainframe = await fresh()
    useMainframe()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    up = true
    const mf = useMainframe()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    expect(mf.isMainframe.value).toBe(true)
  })

  it('an answer that says "operator" stays the answer (the gate is closed for a real reason)', async () => {
    up = true
    fetchMock.mockImplementation((url: string) => String(url).includes('registry-card')
      ? answer(200, { identity: { tier: 'cloud-operator' }, federation: {}, capabilities: {} })
      : answer(200, { is_mainframe: false, tier: 'cloud-operator' }))
    const useMainframe = await fresh()
    const mf = useMainframe()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    expect(mf.isMainframe.value).toBe(false)
    expect(mf.readFailed.value).toBe(false)
    expect(mf.ready.value).toBe(true)
  })
})
