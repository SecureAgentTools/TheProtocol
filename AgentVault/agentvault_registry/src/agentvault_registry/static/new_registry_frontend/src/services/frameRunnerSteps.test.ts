import { describe, expect, it } from 'vitest'
import { STANDUP_STEPS, elapsedSeconds, foldProgress, formatElapsed, frameRecordSettled, publishesStandupSteps, specKey } from './frameRunnerSteps'
import type { ProgressEvent, RunnerFrame, RunnerJob } from './api/frameRunner'

const ev = (step: string | undefined, event: string, extra: Partial<ProgressEvent> = {}): ProgressEvent =>
  ({ ts: '2026-09-13T08:00:00Z', step, event, ...extra })
const state = (f: ReturnType<typeof foldProgress>, step: string) => f.rows.find(r => r.step === step)?.state

describe('foldProgress', () => {
  it('shows a standup in flight: finished steps done, the open one running, the rest pending', () => {
    const f = foldProgress([ev('validate', 'start'), ev('validate', 'end', { verdict: 'ok' }), ev('preflight', 'start')], 'running')
    expect(f.rows.map(r => r.step)).toEqual([...STANDUP_STEPS])
    expect([state(f, 'validate'), state(f, 'preflight'), state(f, 'mtls')]).toEqual(['done', 'running', 'pending'])
    expect(f.current).toBe('preflight')
    expect(f.failure).toBeNull()
  })

  it('closes a step that ended only by the next start (the pre-boot steps write no end of their own)', () => {
    const f = foldProgress([ev('compose-up', 'start'), ev('compose', 'start')], 'running')
    expect([state(f, 'compose-up'), state(f, 'compose')]).toEqual(['done', 'running'])
  })

  it('names the refused step with the driver\'s sentence, and the steps after it never ran', () => {
    const f = foldProgress([
      ev('compose', 'start'), ev('compose', 'end'), ev('emission', 'start'),
      ev('emission', 'fail', { verdict: 'refused', sentence: 'emission gate: EventStore not healthy' }),
    ], 'failed')
    expect(state(f, 'emission')).toBe('failed')
    expect(f.failure).toEqual({ step: 'emission', sentence: 'emission gate: EventStore not healthy' })
    expect([state(f, 'vhosts'), state(f, 'mtls')]).toEqual(['unreached', 'unreached'])
    expect(f.current).toBeNull()
  })

  it('places a refusal from before any step on its own row', () => {
    const f = foldProgress([ev(undefined, 'fail', { sentence: 'load gate refused' })], 'failed')
    expect(f.rows[f.rows.length - 1]).toMatchObject({ step: 'run', state: 'failed', sentence: 'load gate refused' })
    expect(f.failure?.step).toBe('run')
  })

  it('keeps a resume\'s skips with their reasons, including the issuance that never runs twice', () => {
    const f = foldProgress([
      ev('compose', 'skip', { sentence: 'before --resume-from vhosts' }),
      ev('emission', 'skip', { sentence: 'completed in an earlier pass, and it issues units: a resume never runs it twice' }),
      ev('vhosts', 'start'),
    ], 'running')
    expect(f.rows.find(r => r.step === 'emission')).toMatchObject({ state: 'skipped', sentence: expect.stringContaining('issues units') })
    expect(state(f, 'compose')).toBe('skipped')
    expect(state(f, 'vhosts')).toBe('running')
  })

  it('reports live with the addresses the driver published', () => {
    const urls = { console: 'https://juice.theprotocol.cloud' }
    const f = foldProgress([ev('mtls', 'start'), ev('mtls', 'end'), ev('live', 'live', { verdict: 'ok', urls })], 'succeeded')
    expect(f.live?.urls).toEqual(urls)
    expect(state(f, 'mtls')).toBe('done')
    expect(f.rows.some(r => r.state === 'running' || r.state === 'pending')).toBe(false)
  })

  it('marks the step a cancel interrupted, since a killed driver writes nothing', () => {
    const f = foldProgress([ev('spire', 'start')], 'cancelled')
    expect(f.rows.find(r => r.step === 'spire')).toMatchObject({ state: 'failed', sentence: 'the job ended cancelled during this step' })
    expect(f.failure?.step).toBe('spire')
  })

  it('counts lines it cannot place instead of throwing', () => {
    const f = foldProgress([{ event: 'unreadable', raw: '{"ts' } as ProgressEvent, ev(undefined, 'start')], 'running')
    expect(f.unreadable).toBe(2)
    expect(f.rows.every(r => r.state === 'pending')).toBe(true)
  })
})

describe('specKey', () => {
  it('is the same for the same spec in any key order, and moves with any value', () => {
    expect(specKey({ name: 'juice', mint: 1 })).toBe(specKey({ mint: 1, name: 'juice' }))
    expect(specKey({ name: 'juice', mint: 1 })).not.toBe(specKey({ name: 'juice', mint: 2 }))
    expect(specKey({ lat: 39.47 })).not.toBe(specKey({ lat: 39.470001 }))
  })
})

describe('elapsed', () => {
  it('measures to the end, or to now while running, and says nothing about an unreadable start', () => {
    expect(elapsedSeconds('2026-09-13T08:00:00Z', '2026-09-13T08:15:05Z', 0)).toBe(905)
    expect(elapsedSeconds('2026-09-13T08:00:00Z', null, Date.parse('2026-09-13T08:00:42Z'))).toBe(42)
    expect(elapsedSeconds('not a time', null, 0)).toBeNull()
    expect([formatElapsed(42), formatElapsed(905), formatElapsed(3720), formatElapsed(null)]).toEqual(['42s', '15m 05s', '1h 02m', ''])
  })
})

describe('frameRecordSettled', () => {
  const job = (op: RunnerJob['op'], state: RunnerJob['state'], id = 'job1'): RunnerJob =>
    ({ id, op, name: 'orchard', state, created: '2026-09-15T01:00:00Z' })
  const frame = (state: string, built_by_job = 'job0'): RunnerFrame => ({ name: 'orchard', state, built_by_job })
  const other: RunnerFrame = { name: 'lantern', state: 'live', built_by_job: 'job9' }

  it('holds a succeeded teardown open while the runner still lists the frame (orchard read live after its teardown ended)', () => {
    expect(frameRecordSettled(job('teardown', 'succeeded'), [frame('live'), other])).toBe(false)
    expect(frameRecordSettled(job('teardown', 'succeeded'), [other])).toBe(true)
  })

  it('settles a teardown that failed or was cancelled at once: the runner leaves that record as it was', () => {
    expect(frameRecordSettled(job('teardown', 'failed'), [frame('live')])).toBe(true)
    expect(frameRecordSettled(job('teardown', 'cancelled'), [frame('live')])).toBe(true)
  })

  it('settles a standup only on the record its own job wrote, in the state the job ended with', () => {
    expect(frameRecordSettled(job('standup', 'succeeded'), [other])).toBe(false)
    expect(frameRecordSettled(job('standup', 'succeeded'), [frame('live', 'job0')])).toBe(false)
    expect(frameRecordSettled(job('standup', 'succeeded'), [frame('live', 'job1')])).toBe(true)
    expect(frameRecordSettled(job('standup', 'failed'), [frame('standup failed', 'job1')])).toBe(true)
    expect(frameRecordSettled(job('standup', 'lost'), [frame('live', 'job1')])).toBe(false)
  })

  it('settles a resume when the frame reads the outcome, or when there is no record to update', () => {
    expect(frameRecordSettled(job('resume', 'succeeded'), [frame('standup failed')])).toBe(false)
    expect(frameRecordSettled(job('resume', 'succeeded'), [frame('live')])).toBe(true)
    expect(frameRecordSettled(job('resume', 'failed'), [frame('resume failed')])).toBe(true)
    expect(frameRecordSettled(job('resume', 'succeeded'), [other])).toBe(true)
  })

  it('never calls a job that is still running settled', () => {
    expect(frameRecordSettled(job('teardown', 'running'), [other])).toBe(false)
    expect(frameRecordSettled(job('standup', 'cancelling'), [frame('live', 'job1')])).toBe(false)
  })
})


describe('publishesStandupSteps', () => {
  // The Commander saw "operator_provision · beacon · failed 9s" with all seventeen standup steps reading "not
  // run", for a job that had extracted a bundle, updated SVID SANs, written the env and markers, chowned the ACL
  // and then failed at compose up. Operator jobs run with progress off, so their event list is empty and every
  // step folds to `unreached`. The page was not merely unhelpful; it was stating something false.
  it('is false for every op that publishes no step events', () => {
    for (const op of ['teardown', 'operator_provision', 'operator_status', 'operator_teardown']) {
      expect(publishesStandupSteps(op)).toBe(false)
    }
  })

  it('is true for the ops that do', () => {
    expect(publishesStandupSteps('standup')).toBe(true)
    expect(publishesStandupSteps('resume')).toBe(true)
  })

  it('treats an absent or empty op as publishing nothing, never as a standup', () => {
    // A new op defaults to showing no steps rather than to seventeen false ones.
    expect(publishesStandupSteps(null)).toBe(false)
    expect(publishesStandupSteps(undefined)).toBe(false)
    expect(publishesStandupSteps('')).toBe(false)
    expect(publishesStandupSteps('   ')).toBe(false)
  })

  it('folding an operator job would otherwise call every step "not run"', () => {
    // The measurement behind the rule: this is exactly what the page rendered.
    const f = foldProgress([], 'failed')
    expect(f.rows.length).toBe(STANDUP_STEPS.length)
    expect(f.rows.every(r => r.state === 'unreached' || r.state === 'pending')).toBe(true)
  })
})

describe('foldProgress: the sandbox engine (§TESTBED)', () => {
  const ORDER = ['plan', 'frame_a', 'frame_b', 'ready']

  it('a note is the running step’s latest word, and an end keeps the step’s closing sentence', () => {
    const f = foldProgress([
      { step: 'plan', event: 'start' },
      { step: 'plan', event: 'end', sentence: '1 sandbox(es) of larch' },
      { step: 'frame_a', event: 'start' },
      { step: 'frame_a', event: 'note', sentence: "the standup is at 'compose-up'" },
      { step: 'frame_a', event: 'note', sentence: "the standup is at 'spire'" },
    ], 'running', ORDER)
    const row = (s: string) => f.rows.find(r => r.step === s)!
    expect(row('plan')).toMatchObject({ state: 'done', sentence: '1 sandbox(es) of larch' })
    expect(row('frame_a')).toMatchObject({ state: 'running', sentence: "the standup is at 'spire'" })
    expect(f.current).toBe('frame_a')
    expect(f.unreadable).toBe(0)
  })

  it('a note never reopens a finished step, and skips fold as skipped', () => {
    const f = foldProgress([
      { step: 'plan', event: 'start' },
      { step: 'plan', event: 'end' },
      { step: 'plan', event: 'note', sentence: 'late' },
      { step: 'frame_b', event: 'skip', sentence: 'one frame asked for' },
      { step: 'ready', event: 'live', sentence: 'ready' },
    ], 'succeeded', ORDER)
    const row = (s: string) => f.rows.find(r => r.step === s)!
    expect(row('plan').state).toBe('done')
    expect(row('plan').sentence).toBeUndefined()
    expect(row('frame_b')).toMatchObject({ state: 'skipped', sentence: 'one frame asked for' })
    expect(row('frame_a').state).toBe('unreached')
  })

  it('a failure names its step and sentence', () => {
    const f = foldProgress([
      { step: 'frame_a', event: 'start' },
      { step: 'frame_a', event: 'fail', sentence: 'frame-up for larchsbx exited 1' },
    ], 'failed', ORDER)
    expect(f.failure).toEqual({ step: 'frame_a', sentence: 'frame-up for larchsbx exited 1' })
  })
})
