/**
 * §TESTBED (2026-09-19): the steps of a sandbox job, in the order frame-sandbox.py reports them, and what each means to a
 * person. The engine appends the driver's line shape ({ts, step, event: start|end|skip|fail|note|live, sentence}), so the
 * rows are folded by frameRunnerSteps.foldProgress with this order.
 */
export const SANDBOX_UP_STEPS: readonly string[] = [
  'plan', 'frame_a', 'frame_b', 'federate', 'operator_a', 'operator_b', 'fixtures', 'ready',
]
export const SANDBOX_DOWN_STEPS: readonly string[] = ['operators', 'frame_b', 'frame_a', 'firewall']

/** i18n key suffix and English fallback per step. */
export const SANDBOX_STEP_LABELS: Record<string, [string, string]> = {
  plan: ['plan', 'Check names, lanes and memory'],
  frame_a: ['frameA', 'Stand up the sandbox'],
  frame_b: ['frameB', 'Stand up the second sandbox'],
  federate: ['federate', 'Federate the two sandboxes'],
  operator_a: ['operatorA', 'Cloud operator on the sandbox'],
  operator_b: ['operatorB', 'Cloud operator on the second sandbox'],
  fixtures: ['fixtures', 'Federation suite fixtures'],
  ready: ['ready', 'Check the tester can log in'],
}

/** A teardown names the same frames with the opposite verb (it is `frame_a` in both jobs, the sandbox it acts on). */
export const SANDBOX_DOWN_STEP_LABELS: Record<string, [string, string]> = {
  operators: ['operatorsDown', 'Remove the cloud operators'],
  frame_b: ['frameBDown', 'Remove the second sandbox'],
  frame_a: ['frameADown', 'Remove the sandbox'],
  firewall: ['firewallDown', 'Close the firewall ports'],
}

export function sandboxSteps(op: string | null | undefined): readonly string[] {
  return op === 'sandbox_down' ? SANDBOX_DOWN_STEPS : SANDBOX_UP_STEPS
}

/** [i18n key suffix, English] for a step of this job. */
export function sandboxStepLabel(op: string | null | undefined, step: string): [string, string] {
  const table = op === 'sandbox_down' ? SANDBOX_DOWN_STEP_LABELS : SANDBOX_STEP_LABELS
  return table[step] ?? [step, step]
}

/** The memory a topology adds, from the runner's estimate (MiB), as a person reads it. */
export function formatGib(mib: number | null | undefined): string {
  if (typeof mib !== 'number' || !Number.isFinite(mib)) return ''
  return `${(mib / 1024).toFixed(1)} GiB`
}
