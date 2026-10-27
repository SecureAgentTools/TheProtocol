/**
 * §FRAMEPROV P3 (2026-09-13): fold the standup driver's progress events into one row per step, and key a spec for
 * the plan gate.
 *
 * The driver appends {ts, step, event: start|end|skip|fail|live, verdict, sentence} per line (Progress in
 * scripts/hetzner_demo/standup_driver.py). Pure, so the rules are unit-tested rather than read off a live standup.
 */
import type { JobState, ProgressEvent, RunnerFrame, RunnerJob } from './api/frameRunner'

/**
 * The order a standup reports in: the runner's `dns` (it creates the frame's names and waits for them before the driver
 * starts), the four steps the driver's main() runs before post_boot, then post_boot's steps. post_boot's `_STEPS` also
 * names `login`, which never reports (there is no `do("login")`), so listing it showed a finished standup's `login` as
 * never reached.
 */
export const STANDUP_STEPS: readonly string[] = [
  'dns', 'validate', 'preflight', 'render', 'compose-up',
  'compose', 'spire', 'seed', 'emission', 'vhosts', 'admin', 'jurisdiction',
  'federate', 'operators', 'canary', 'wire', 'mtls',
]

/** `unreached`: the job ended before the step began. */
export type StepState = 'pending' | 'running' | 'done' | 'skipped' | 'failed' | 'unreached'

export interface StepRow {
  step: string
  state: StepState
  sentence?: string
  started?: string
  ended?: string
}

export interface FoldedProgress {
  rows: StepRow[]
  current: string | null
  live: ProgressEvent | null
  failure: { step: string; sentence: string } | null
  /** Lines this fold could not place (the runner marks an unparsable line `unreadable`). */
  unreadable: number
}

const ENDED: readonly JobState[] = ['succeeded', 'failed', 'cancelled', 'lost']

/** Does this op publish the standup step events, or would a step list be a claim nobody made?
 *
 * ⚠ THE PAGE USED TO ASK `op !== 'teardown'`, which names ONE exception rather than the property. Operator jobs
 * are launched with progress off, so their event list is empty and all seventeen standup steps fold to
 * `unreached`, which the template renders as "not run" — a page stating something false about a job that did
 * most of its work and then failed. Ask what the op publishes; a new op that publishes nothing is then right by
 * default rather than wrong until someone notices.
 */
export function publishesStandupSteps(op: string | null | undefined): boolean {
  const name = (op ?? '').trim()
  if (!name) return false
  return name !== 'teardown' && !name.startsWith('operator_')
}

export function foldProgress(
  events: readonly ProgressEvent[],
  jobState: JobState | null = null,
  order: readonly string[] = STANDUP_STEPS,
): FoldedProgress {
  const rows = new Map<string, StepRow>()
  for (const step of order) rows.set(step, { step, state: 'pending' })
  const row = (step: string): StepRow => {
    let r = rows.get(step)
    if (!r) {
      r = { step, state: 'pending' }
      rows.set(step, r)
    }
    return r
  }
  let current: string | null = null
  let live: ProgressEvent | null = null
  let failure: FoldedProgress['failure'] = null
  let unreadable = 0

  for (const e of events) {
    const step = typeof e.step === 'string' && e.step ? e.step : null
    if (e.event === 'start' && step) {
      // Steps run one after another and a refused step writes `fail` before the process exits, so a start while
      // another step is open means that step finished (the driver's pre-boot steps close only on the next start).
      if (current && current !== step && row(current).state === 'running') {
        row(current).state = 'done'
        row(current).ended = e.ts
      }
      const r = row(step)
      r.state = 'running'
      r.started = e.ts
      r.sentence = undefined
      current = step
    } else if (e.event === 'end' && step) {
      const r = row(step)
      r.state = 'done'
      r.ended = e.ts
      // §TESTBED: the sandbox engine closes a step with what it made ("larchsbx is up: <console>"); the driver's end
      // carries a verdict only, so a standup's rows are unchanged
      if (e.sentence) r.sentence = e.sentence
      if (current === step) current = null
    } else if (e.event === 'note' && step) {
      // §TESTBED: a sentence INSIDE a running step (frame-sandbox.py: "the standup is at 'spire'"): the row's latest word
      const r = row(step)
      if (r.state === 'pending') {
        r.state = 'running'
        r.started = r.started ?? e.ts
        current = step
      }
      if (r.state === 'running') r.sentence = e.sentence
    } else if (e.event === 'skip' && step) {
      const r = row(step)
      r.state = 'skipped'
      r.sentence = e.sentence
    } else if (e.event === 'fail') {
      const r = row(step ?? 'run')
      r.state = 'failed'
      r.ended = e.ts
      r.sentence = e.sentence || e.verdict || 'failed'
      failure = { step: r.step, sentence: r.sentence }
      current = null
    } else if (e.event === 'live') {
      if (current && row(current).state === 'running') row(current).state = 'done'
      live = e
      current = null
    } else {
      unreadable += 1
    }
  }

  if (jobState && ENDED.includes(jobState)) {
    for (const r of rows.values()) {
      if (r.state === 'running') {
        r.state = 'failed'
        r.sentence = `the job ended ${jobState} during this step`
        if (!failure) failure = { step: r.step, sentence: r.sentence }
      } else if (r.state === 'pending') {
        r.state = 'unreached'
      }
    }
    current = null
  }
  return { rows: [...rows.values()], current, live, failure, unreadable }
}

/** A spec's identity for the plan gate: the same fields and values in any key order give the same key. */
export function specKey(spec: object): string {
  const src = spec as Record<string, unknown>
  return JSON.stringify(Object.keys(src).sort().map(k => [k, src[k]]))
}

/** Seconds between an ISO start and an ISO end (or now); null when the start is unreadable. */
export function elapsedSeconds(created: string | null | undefined, ended: string | null | undefined, nowMs: number): number | null {
  const start = created ? Date.parse(created) : NaN
  if (!Number.isFinite(start)) return null
  const stop = ended ? Date.parse(ended) : nowMs
  return Math.max(0, Math.round(((Number.isFinite(stop) ? stop : nowMs) - start) / 1000))
}

export function formatElapsed(seconds: number | null): string {
  if (seconds === null) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}h ${pad(m)}m` : m ? `${m}m ${pad(s)}s` : `${s}s`
}

/**
 * Whether the runner's frame record already shows how a job ended (§PROVSHOW, 2026-09-15).
 *
 * The runner saves a job's end BEFORE it writes the frame record (`_finish` in tools/frame-runner/frame_runner.py:
 * `save_job`, then `_record_frame`, which for a DNS-managed teardown removes the names and the frame's secrets before
 * it deletes `frames/<name>.json`). A status read taken the moment the job reads ended can still list a torn-down
 * frame as live, and the page read it once: orchard stayed listed live after its teardown until Refresh.
 */
export function frameRecordSettled(
  job: Pick<RunnerJob, 'id' | 'op' | 'name' | 'state'>,
  frames: readonly Pick<RunnerFrame, 'name' | 'state' | 'built_by_job'>[],
): boolean {
  if (!ENDED.includes(job.state)) return false
  const frame = frames.find(f => f.name === job.name)
  // Only a succeeded teardown removes the record; a failed or cancelled one leaves it as it was.
  if (job.op === 'teardown') return job.state !== 'succeeded' || !frame
  const outcome = job.state === 'succeeded' ? 'live' : `${job.op} ${job.state}`
  // A resume updates a record that exists and writes none otherwise.
  if (job.op === 'resume') return !frame || frame.state === outcome
  // A standup that never made its stack directory writes no record at all: the caller's bound ends that wait.
  return !!frame && frame.built_by_job === job.id && frame.state === outcome
}
