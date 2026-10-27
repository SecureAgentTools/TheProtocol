/**
 * §LITEBRIDGE (2026-08-21) — the bridge for machines that cannot run the bridge.
 *
 * His words, carried since §BRIDGE R8: *"the LOW-GFX FALLBACK (keep the old
 * Mission Control + its tour for machines without the compute)"*. The old
 * Mission Control is gone — §BRIDGE P4 deleted 375 lines of it, including the
 * health arithmetic that printed '80.0% GOOD' beside '5 DOWN' — so restoring it
 * would restore a view that lied. What it needs is a bridge that reports the
 * SAME truths without a WebGL stage.
 *
 * Two rules this module exists to enforce:
 *
 *  1. **A machine is downgraded on FACTS, never on a guess.** No WebGL context
 *     is a fact. Two cores is a fact. "Feels slow" is not, and silently serving
 *     someone a lesser view because of a hunch is how a product stops being
 *     trustable. `auto` therefore drops to lite on hard capability only, and
 *     always says which fact did it.
 *  2. **A manual choice is never overridden.** Not by a probe, not by a slow
 *     frame, not by a later visit. If someone picks FULL on a potato, they get
 *     FULL — with an offer to switch, which they can decline once and for all.
 */

export type GfxPref = 'auto' | 'full' | 'lite'
export type GfxMode = 'full' | 'lite'

export interface GfxCaps {
  /** Can this browser actually create a WebGL context? */
  webgl: boolean
  /** navigator.hardwareConcurrency, when the browser reports it. */
  cores?: number | null
  /** navigator.deviceMemory in GB, when the browser reports it. */
  memoryGb?: number | null
}

export interface GfxResolution {
  mode: GfxMode
  /** Why, in one sentence, for a human. Never empty. */
  reason: string
  /** True when the machine, not the person, chose this. */
  automatic: boolean
}

export const GFX_KEY = 'bridge.gfx'
export const GFX_OFFER_DISMISSED_KEY = 'bridge.gfxOfferDismissed'

/**
 * Hard floors. Anything at or below these genuinely cannot carry the stage:
 * two cores must run the compositor, the app and three.js at once, and the
 * measured cost of a single WebGL context on a shared CPU is multiple cores.
 * Deliberately conservative — a wrong auto-downgrade is worse than none.
 */
export const MIN_CORES = 2
export const MIN_MEMORY_GB = 1

export function resolveGfx(pref: GfxPref, caps: GfxCaps): GfxResolution {
  if (pref === 'lite') return { mode: 'lite', reason: 'You chose the light bridge.', automatic: false }
  if (pref === 'full') {
    /*
     * A manual choice beats a HEURISTIC. It does not beat IMPOSSIBILITY.
     *
     * Two cores is a reason to think the stage will be unpleasant, and someone
     * is entitled to disagree with that and get their starmap. No WebGL context
     * is not an opinion — honouring FULL there buys a black rectangle where the
     * stage should be, which is a worse outcome than the one the preference was
     * expressed to avoid. So: everything else is overridable, this is not, and
     * the reason names both halves so it never reads as the setting being lost.
     */
    if (!caps.webgl) {
      return {
        mode: 'lite', automatic: true,
        reason: 'You chose the full bridge, but this browser cannot open a WebGL context — showing the light bridge instead.',
      }
    }
    return { mode: 'full', reason: 'You chose the full bridge.', automatic: false }
  }
  if (!caps.webgl) {
    return { mode: 'lite', reason: 'This browser cannot open a WebGL context, so the stage would render nothing.', automatic: true }
  }
  if (typeof caps.cores === 'number' && caps.cores > 0 && caps.cores <= MIN_CORES) {
    return { mode: 'lite', reason: `This device reports ${caps.cores} CPU core${caps.cores === 1 ? '' : 's'}; the stage needs more than that to stay smooth.`, automatic: true }
  }
  if (typeof caps.memoryGb === 'number' && caps.memoryGb > 0 && caps.memoryGb <= MIN_MEMORY_GB) {
    return { mode: 'lite', reason: `This device reports ${caps.memoryGb} GB of memory; the stage needs more than that.`, automatic: true }
  }
  return { mode: 'full', reason: 'This machine can run the stage.', automatic: true }
}

/**
 * Does a WebGL context actually open?
 *
 * Asking for the capability is the only honest test: a browser can advertise
 * `WebGLRenderingContext` and still refuse to create a context (blocklisted
 * driver, GPU process crashed, hardware acceleration switched off). Cheap, and
 * the throwaway canvas is released immediately.
 */
export function probeWebgl(): boolean {
  try {
    const c = document.createElement('canvas')
    const gl = (c.getContext('webgl2') || c.getContext('webgl') || c.getContext('experimental-webgl')) as
      WebGLRenderingContext | null
    if (!gl) return false
    // Some environments hand back a context that is already lost.
    const lost = typeof gl.isContextLost === 'function' ? gl.isContextLost() : false
    const ext = gl.getExtension('WEBGL_lose_context')
    if (ext) ext.loseContext()
    return !lost
  } catch { return false }
}

export function readCaps(): GfxCaps {
  const nav: any = typeof navigator === 'undefined' ? {} : navigator
  return {
    webgl: probeWebgl(),
    cores: typeof nav.hardwareConcurrency === 'number' ? nav.hardwareConcurrency : null,
    memoryGb: typeof nav.deviceMemory === 'number' ? nav.deviceMemory : null,
  }
}

export function loadGfxPref(): GfxPref {
  try {
    const v = localStorage.getItem(GFX_KEY)
    if (v === 'full' || v === 'lite' || v === 'auto') return v
  } catch { /* storage blocked */ }
  return 'auto'
}

export function saveGfxPref(p: GfxPref): void {
  try {
    if (p === 'auto') localStorage.removeItem(GFX_KEY)
    else localStorage.setItem(GFX_KEY, p)
  } catch { /* storage blocked */ }
}

/**
 * Should we OFFER the light bridge? (Never switch — offer.)
 *
 * The stage times its own draw (`bridgeStats().renderMs`), so this is a
 * measurement, not an impression. It takes a sustained sample because one slow
 * frame is a garbage collection, not a verdict — and it stays quiet for anyone
 * who has already answered the question.
 */
export interface OfferInput {
  mode: GfxMode
  /** p50 of the stage's own draw time, ms. */
  renderMsP50: number | null
  /** How many frames that p50 was taken over. */
  samples: number
  dismissed: boolean
}

/** Above this, a frame budget of 60fps (16.7ms) is already blown by the stage alone. */
export const SLOW_FRAME_MS = 24
export const MIN_SAMPLES = 20

export function shouldOfferLite(i: OfferInput): boolean {
  if (i.mode !== 'full' || i.dismissed) return false
  if (typeof i.renderMsP50 !== 'number' || !isFinite(i.renderMsP50)) return false
  if (i.samples < MIN_SAMPLES) return false
  return i.renderMsP50 > SLOW_FRAME_MS
}

export function offerText(renderMsP50: number): string {
  return `The stage is costing ${Math.round(renderMsP50)} ms a frame on this machine.`
}
