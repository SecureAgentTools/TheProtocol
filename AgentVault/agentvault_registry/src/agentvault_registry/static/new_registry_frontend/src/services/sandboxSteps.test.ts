import { describe, expect, it } from 'vitest'
import en from '@/i18n/locales/en.json'
import de from '@/i18n/locales/de.json'
import { SANDBOX_DOWN_STEPS, SANDBOX_UP_STEPS, formatGib, sandboxStepLabel, sandboxSteps } from './sandboxSteps'

// §TESTBED (2026-09-19): the Sandbox panel's step rows. A teardown acts on the same frames as the standup (`frame_a`) with
// the opposite verb; the browser drive on larch caught the teardown reading "Stand up the sandbox".
const stepsBundle = (b: unknown) => (b as { mcpTester: { sandbox: { steps: Record<string, string> } } }).mcpTester.sandbox.steps

describe('sandbox steps', () => {
  it('every step of both jobs has a label whose key is in the English and German bundles', () => {
    for (const [op, steps] of [['sandbox_up', SANDBOX_UP_STEPS], ['sandbox_down', SANDBOX_DOWN_STEPS]] as const) {
      for (const step of steps) {
        const [key, fallback] = sandboxStepLabel(op, step)
        expect(fallback).not.toBe(step)
        expect(stepsBundle(en)[key]).toBeTruthy()
        expect(stepsBundle(de)[key]).toBeTruthy()
      }
    }
  })

  it('a teardown says remove where the standup says stand up', () => {
    expect(sandboxStepLabel('sandbox_up', 'frame_a')[1]).toBe('Stand up the sandbox')
    expect(sandboxStepLabel('sandbox_down', 'frame_a')[1]).toBe('Remove the sandbox')
    expect(sandboxSteps('sandbox_down')).toEqual(SANDBOX_DOWN_STEPS)
    expect(sandboxSteps('sandbox_up')).toEqual(SANDBOX_UP_STEPS)
  })

  it('formats the runner’s memory estimate as a person reads it', () => {
    expect(formatGib(2600)).toBe('2.5 GiB')
    expect(formatGib(undefined)).toBe('')
  })
})
