import { describe, it, expect } from 'vitest'
import {
  resolveGfx, shouldOfferLite, offerText, MIN_CORES, MIN_MEMORY_GB,
  SLOW_FRAME_MS, MIN_SAMPLES, type GfxCaps,
} from './graphics'

const able: GfxCaps = { webgl: true, cores: 8, memoryGb: 8 }

describe('resolveGfx — a manual choice is never overridden', () => {
  it('FULL beats the HEURISTICS — a 2-core machine still gets its starmap', () => {
    const r = resolveGfx('full', { webgl: true, cores: 1, memoryGb: 0.5 })
    expect(r.mode).toBe('full')
    expect(r.automatic).toBe(false)
  })
  it('but FULL does NOT beat impossibility: no WebGL is a black rectangle', () => {
    const r = resolveGfx('full', { webgl: false, cores: 16, memoryGb: 32 })
    expect(r.mode).toBe('lite')
    expect(r.automatic).toBe(true)
    // and it must not read as the setting having been silently lost
    expect(r.reason).toMatch(/You chose the full bridge/)
    expect(r.reason).toMatch(/WebGL/)
  })
  it('LITE stays lite on a workstation', () => {
    const r = resolveGfx('lite', able)
    expect(r.mode).toBe('lite')
    expect(r.automatic).toBe(false)
  })
  it('every resolution explains itself', () => {
    for (const pref of ['auto', 'full', 'lite'] as const)
      for (const caps of [able, { webgl: false }, { webgl: true, cores: 1 }])
        expect(resolveGfx(pref, caps as GfxCaps).reason.length).toBeGreaterThan(10)
  })
})

describe('resolveGfx — auto downgrades on FACTS only', () => {
  it('no WebGL context is a fact', () => {
    const r = resolveGfx('auto', { webgl: false, cores: 16, memoryGb: 32 })
    expect(r.mode).toBe('lite')
    expect(r.automatic).toBe(true)
    expect(r.reason).toMatch(/WebGL/)
  })
  it('a 2-core device is a fact', () => {
    const r = resolveGfx('auto', { webgl: true, cores: MIN_CORES, memoryGb: 8 })
    expect(r.mode).toBe('lite')
    expect(r.reason).toMatch(/2 CPU cores/)
  })
  it('one core reads as singular, because a machine is not a sentence you skim', () => {
    expect(resolveGfx('auto', { webgl: true, cores: 1 }).reason).toMatch(/1 CPU core;/)
  })
  it('a low-memory device is a fact', () => {
    const r = resolveGfx('auto', { webgl: true, cores: 8, memoryGb: MIN_MEMORY_GB })
    expect(r.mode).toBe('lite')
    expect(r.reason).toMatch(/GB of memory/)
  })
  it('a capable machine is left alone', () => {
    expect(resolveGfx('auto', able).mode).toBe('full')
  })
  it('MISSING capability data is not evidence of a weak machine', () => {
    // navigator.deviceMemory is absent in Firefox and Safari. Treating "unknown"
    // as "small" would downgrade most of the web on no evidence at all.
    expect(resolveGfx('auto', { webgl: true }).mode).toBe('full')
    expect(resolveGfx('auto', { webgl: true, cores: null, memoryGb: null }).mode).toBe('full')
    expect(resolveGfx('auto', { webgl: true, cores: 0, memoryGb: 0 }).mode).toBe('full')
  })
  it('one core over the floor is still full', () => {
    expect(resolveGfx('auto', { webgl: true, cores: MIN_CORES + 1, memoryGb: 8 }).mode).toBe('full')
  })
})

describe('shouldOfferLite — offer, never switch', () => {
  const base = { mode: 'full' as const, renderMsP50: SLOW_FRAME_MS + 10, samples: MIN_SAMPLES, dismissed: false }
  it('offers when the stage is measurably slow, over a real sample', () => {
    expect(shouldOfferLite(base)).toBe(true)
  })
  it('one slow frame is a garbage collection, not a verdict', () => {
    expect(shouldOfferLite({ ...base, samples: MIN_SAMPLES - 1 })).toBe(false)
  })
  it('a fast stage is left alone', () => {
    expect(shouldOfferLite({ ...base, renderMsP50: SLOW_FRAME_MS })).toBe(false)
    expect(shouldOfferLite({ ...base, renderMsP50: 6 })).toBe(false)
  })
  it('never nags someone who already said no', () => {
    expect(shouldOfferLite({ ...base, dismissed: true })).toBe(false)
  })
  it('never offers lite to someone already in lite', () => {
    expect(shouldOfferLite({ ...base, mode: 'lite' })).toBe(false)
  })
  it('no measurement means no offer — silence is not slowness', () => {
    expect(shouldOfferLite({ ...base, renderMsP50: null })).toBe(false)
    expect(shouldOfferLite({ ...base, renderMsP50: NaN })).toBe(false)
    expect(shouldOfferLite({ ...base, renderMsP50: Infinity })).toBe(false)
  })
  it('the offer states the measurement it is based on', () => {
    expect(offerText(41.6)).toMatch(/42 ms a frame/)
  })
})
