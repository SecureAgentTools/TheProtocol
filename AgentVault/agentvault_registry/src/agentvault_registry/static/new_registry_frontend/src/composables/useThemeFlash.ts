import { ref, onBeforeUnmount, type Ref } from 'vue'
import { useUIStore, type BrandTheme } from '@/stores/ui'

export type GlitchPhase = 'idle' | 'blip' | 'rapid' | 'lock' | 'decay'

export interface ThemeFlashController {
  intensity: Ref<number>
  /** §GLITCH2 — which act of the timeline is playing; the overlay picks its distortions by it. */
  phase: Ref<GlitchPhase>
  isGlitching: Ref<boolean>
  start: () => void
  cancel: () => void
}

export interface ThemeFlashOptions {
  oncePerTab?: boolean
  sessionKey?: string
}

interface Step {
  at: number
  theme: BrandTheme
  intensity: number
  phase: GlitchPhase
}

const DEFAULT_SESSION_KEY = 'tp.landing.glitchPlayed'

// Accelerating ping-pong intervals (ms) during the rapid phase.
const RAPID_INTERVALS: number[] = [170, 150, 130, 110, 95, 80, 68, 58, 50, 44, 40, 38, 36, 36, 36, 36]

// Build a declarative timeline at module-load time (cheap, one pass).
function buildSteps(): Step[] {
  const steps: Step[] = []

  // Phase 2 — anomaly blips (three short sovereign flashes)
  const blips: Array<[number, number, number]> = [
    [1200, 80, 0.15],
    [1900, 110, 0.25],
    [2500, 140, 0.40],
  ]
  for (const [at, dur, intensity] of blips) {
    steps.push({ at, theme: 'sovereign', intensity, phase: 'blip' })
    steps.push({ at: at + dur, theme: 'neural', intensity: intensity * 0.5, phase: 'blip' })
  }

  // Phase 3 — accelerating oscillation
  let t = 2800
  for (let i = 0; i < RAPID_INTERVALS.length; i++) {
    const theme: BrandTheme = i % 2 === 0 ? 'sovereign' : 'neural'
    const intensity = 0.40 + (i / RAPID_INTERVALS.length) * 0.60
    steps.push({ at: t, theme, intensity, phase: 'rapid' })
    t += RAPID_INTERVALS[i]
  }

  // Phase 4 — lock sovereign, peak intensity hold, then decay
  const lockAt = t
  steps.push({ at: lockAt, theme: 'sovereign', intensity: 1.0, phase: 'lock' })
  steps.push({ at: lockAt + 150, theme: 'sovereign', intensity: 1.0, phase: 'lock' })
  steps.push({ at: lockAt + 350, theme: 'sovereign', intensity: 0.55, phase: 'decay' })
  steps.push({ at: lockAt + 600, theme: 'sovereign', intensity: 0.20, phase: 'decay' })
  steps.push({ at: lockAt + 850, theme: 'sovereign', intensity: 0.0, phase: 'decay' })

  return steps.sort((a, b) => a.at - b.at)
}

const STEPS = buildSteps()
const TOTAL_DURATION_MS = STEPS.length > 0 ? STEPS[STEPS.length - 1].at + 100 : 6000

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function readSessionFlag(key: string): boolean {
  try {
    return sessionStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function writeSessionFlag(key: string) {
  try {
    sessionStorage.setItem(key, '1')
  } catch { /* non-fatal */ }
}

export function useThemeFlash(opts: ThemeFlashOptions = {}): ThemeFlashController {
  const { oncePerTab = true, sessionKey = DEFAULT_SESSION_KEY } = opts
  const ui = useUIStore()

  const intensity = ref(0)
  const phase = ref<GlitchPhase>('idle')
  const isGlitching = ref(false)

  let rafHandle: number | null = null
  let startedAt = 0
  let nextStepIdx = 0

  function cancel() {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle)
      rafHandle = null
    }
    isGlitching.value = false
    phase.value = 'idle'
  }

  function tick(now: number) {
    const elapsed = now - startedAt

    while (nextStepIdx < STEPS.length && STEPS[nextStepIdx].at <= elapsed) {
      const step = STEPS[nextStepIdx]
      ui.setBrandThemeEphemeral(step.theme)
      intensity.value = step.intensity
      phase.value = step.phase
      nextStepIdx++
    }

    if (elapsed >= TOTAL_DURATION_MS || nextStepIdx >= STEPS.length) {
      // Finalize: ensure sovereign is active, intensity at 0, flag session.
      ui.setBrandThemeEphemeral('sovereign')
      intensity.value = 0
      phase.value = 'idle'
      isGlitching.value = false
      writeSessionFlag(sessionKey)
      rafHandle = null
      return
    }

    rafHandle = requestAnimationFrame(tick)
  }

  function start() {
    // Already fired in this tab — just ensure sovereign is applied and bail.
    if (oncePerTab && readSessionFlag(sessionKey)) {
      ui.setBrandThemeEphemeral('sovereign')
      return
    }

    // Accessibility short-circuit — no flashing.
    if (prefersReducedMotion()) {
      ui.setBrandThemeEphemeral('sovereign')
      writeSessionFlag(sessionKey)
      return
    }

    cancel()
    nextStepIdx = 0
    intensity.value = 0
    phase.value = 'blip'
    isGlitching.value = true
    ui.setBrandThemeEphemeral('neural')
    startedAt = performance.now()
    rafHandle = requestAnimationFrame(tick)
  }

  onBeforeUnmount(() => {
    cancel()
  })

  return { intensity, phase, isGlitching, start, cancel }
}
