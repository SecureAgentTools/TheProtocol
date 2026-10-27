/**
 * §BOOTSEQ (2026-08-21) — the bridge gets an actual boot sequence.
 *
 * WHY. Before this, MissionControl started its work from FOUR independent
 * onMounted hooks and SIXTEEN fire-and-forget async calls, with stages coupled
 * by guessed delays — the worst being
 *     restoreReach().then(() => setTimeout(loadForeignFleets, 4000))
 * where 4000 is a hope about how long session restore takes. The fleet path
 * alone then carried FOUR overlapping re-entrancy guards (foreignBusy,
 * foreignAgain, foreignKeySig, fanTimer), which is what you build when the real
 * problem is a missing sequence.
 *
 * Every load bug we chased was one shape wearing different clothes: the fan-out
 * ran against a PARTIAL connected set and whatever landed first was what you
 * got — 2 registries, then 5, then 9, depending on luck.
 *
 * This module owns ordering, single-flight, and re-running a step whose INPUT
 * SET changed underneath it. It is pure: no Vue, no timers of its own, and the
 * clock is injected, so a test drives a whole boot in milliseconds instead of
 * sleeping through one.
 */

export type StepState = 'pending' | 'running' | 'ok' | 'failed' | 'skipped'

export interface BootStep {
  id: string
  label: string
  /** ids that must SETTLE before this runs. */
  needs?: string[]
  /** Does the view wait for it? Non-required steps stream in behind the screen. */
  required?: boolean
  /**
   * A signature of the INPUT this step consumes (e.g. the connected registry
   * set). If it differs after the run, the step re-runs ONCE more against the
   * new value. This is the whole fix for "ran against a partial set".
   */
  inputSig?: () => string
  /** Returns an optional human detail for the log ("9 registries · 841 agents"). */
  run: () => Promise<string | void>
}

export interface BootRecord {
  id: string
  label: string
  state: StepState
  required: boolean
  detail?: string
  error?: string
  startedAt?: number
  endedAt?: number
  /** How many times this step re-ran because its input moved. */
  runs: number
}

export interface BootOptions {
  now?: () => number
  /** Cap on re-runs per step, so a signature that never settles cannot loop. */
  maxRuns?: number
  onChange?: (records: BootRecord[]) => void
}

const SETTLED: ReadonlySet<StepState> = new Set(['ok', 'failed', 'skipped'])
export function isSettled(s: StepState): boolean { return SETTLED.has(s) }

export class BootSequencer {
  private steps: Map<string, BootStep> = new Map()
  private rec: Map<string, BootRecord> = new Map()
  private now: () => number
  private maxRuns: number
  private onChange?: (r: BootRecord[]) => void
  private inflight: Map<string, Promise<void>> = new Map()

  constructor(steps: BootStep[], opts: BootOptions = {}) {
    this.now = opts.now || (() => Date.now())
    this.maxRuns = opts.maxRuns ?? 3
    this.onChange = opts.onChange
    for (const s of steps) {
      this.steps.set(s.id, s)
      this.rec.set(s.id, {
        id: s.id, label: s.label, state: 'pending',
        required: s.required !== false, runs: 0,
      })
    }
    // A `needs` pointing at nothing is a wiring bug that would silently block
    // the step forever; fail loudly at construction instead.
    for (const s of steps) {
      for (const nid of s.needs || []) {
        if (!this.steps.has(nid)) throw new Error(`boot step "${s.id}" needs unknown step "${nid}"`)
      }
    }
  }

  records(): BootRecord[] { return [...this.rec.values()].map(r => ({ ...r })) }

  /** Required steps that have settled (ok/failed/skipped) — the view may paint. */
  ready(): boolean {
    for (const r of this.rec.values()) if (r.required && !isSettled(r.state)) return false
    return true
  }

  /** Everything settled, streaming steps included. */
  done(): boolean {
    for (const r of this.rec.values()) if (!isSettled(r.state)) return false
    return true
  }

  progress(): { settled: number; total: number } {
    let settled = 0
    for (const r of this.rec.values()) if (isSettled(r.state)) settled++
    return { settled, total: this.rec.size }
  }

  private emit(): void { this.onChange?.(this.records()) }

  private async runStep(step: BootStep): Promise<void> {
    const r = this.rec.get(step.id)!

    // Dependencies first. A dependency that FAILED means this step cannot run
    // honestly, so it is SKIPPED with a reason rather than run against nothing.
    for (const nid of step.needs || []) {
      await this.ensure(nid)
      const dep = this.rec.get(nid)!
      if (dep.state === 'failed' || dep.state === 'skipped') {
        r.state = 'skipped'
        r.error = `needs "${dep.label}", which ${dep.state}`
        r.endedAt = this.now()
        this.emit()
        return
      }
    }

    for (let attempt = 0; attempt < this.maxRuns; attempt++) {
      const sigBefore = step.inputSig ? step.inputSig() : null
      r.state = 'running'
      r.startedAt = r.startedAt ?? this.now()
      r.runs++
      this.emit()
      try {
        const detail = await step.run()
        r.detail = typeof detail === 'string' ? detail : r.detail
        r.state = 'ok'
        r.error = undefined
      } catch (e: any) {
        r.state = 'failed'
        r.error = String(e?.message || e || 'failed').slice(0, 200)
      }
      r.endedAt = this.now()
      this.emit()

      if (r.state !== 'ok') return
      // Did the input move while we were working? Then what we just produced is
      // already stale — run once more against what is true NOW. This is the
      // "ran against a partial registry set" bug, closed structurally.
      const sigAfter = step.inputSig ? step.inputSig() : null
      if (sigBefore === null || sigAfter === sigBefore) return
    }
  }

  /** Run a step at most once concurrently; later callers await the same promise. */
  private ensure(id: string): Promise<void> {
    const existing = this.inflight.get(id)
    if (existing) return existing
    const step = this.steps.get(id)
    if (!step) return Promise.resolve()
    const r = this.rec.get(id)!
    if (isSettled(r.state)) return Promise.resolve()
    const p = this.runStep(step).finally(() => { this.inflight.delete(id) })
    this.inflight.set(id, p)
    return p
  }

  /**
   * Start everything. Independent steps run concurrently; dependent ones wait
   * on exactly what they declared, never on a timer.
   */
  async run(): Promise<BootRecord[]> {
    this.emit()
    await Promise.all([...this.steps.keys()].map(id => this.ensure(id)))
    this.emit()
    return this.records()
  }

  /** Re-run one step by hand (the log's Retry button). */
  async retry(id: string): Promise<void> {
    const r = this.rec.get(id)
    if (!r) return
    r.state = 'pending'; r.error = undefined; r.endedAt = undefined
    this.emit()
    await this.ensure(id)
  }
}

/** One-line summary for the boot log header. */
export function bootSummary(records: BootRecord[]): string {
  const ok = records.filter(r => r.state === 'ok').length
  const failed = records.filter(r => r.state === 'failed').length
  const skipped = records.filter(r => r.state === 'skipped').length
  const parts = [`${ok}/${records.length} ready`]
  if (failed) parts.push(`${failed} failed`)
  if (skipped) parts.push(`${skipped} skipped`)
  return parts.join(' · ')
}

/*
 * "SHOWN THIS PAGE LOAD" — module scope, deliberately.
 *
 * The boot screen must not re-run when he leaves the tab and comes back to a
 * bridge he is already using, and it MUST run on a real reload. Three ways to
 * spell that, two of them wrong:
 *   - a ref inside <script setup> is per-INSTANCE, so a route change re-creates
 *     it and the screen comes back (the defect he reported first);
 *   - `sessionStorage` survives a reload and dies with the TAB, so the screen
 *     shows once ever (the defect he reported second, from my "fix");
 *   - module state dies with the DOCUMENT, which is what "this page load" means.
 */
let bootShown = false
export function bootAlreadyShown(): boolean { return bootShown }
export function markBootShown(): void { bootShown = true }
/** Tests only — a module flag with no reset cannot be tested twice. */
export function resetBootShownForTests(): void { bootShown = false }
