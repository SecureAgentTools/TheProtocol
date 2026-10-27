/**
 * §MCPTEST30 (V0550): what the run's target switched off, and the tool rows held to those switches' refusals.
 *
 * A registry can switch surfaces off (STAKING_ENABLED, STAKING_REWARDS_ENABLED, AGORA_DISTRIBUTIONS_ENABLED, and since
 * V0551 COMMONS_ENABLED) or move its
 * governance to member mode (GOVERNANCE_WEIGHT_MODE=member), and says so in its public registry-config. Since V0550 a
 * run reads that once and holds a switched-off tool to the refusal its switch documents, so a 403 "staking_disabled"
 * there is a pass and a 2xx a finding. The page says so beside the pass rate: without it a reader sees a stake pass
 * on a refusal and has no way to tell why. The summary carries `target_switches` (the keys the target reported),
 * `target_switches_read` and `switched_off_rows`; a run before V0550 carries none of them, and then nothing is shown.
 */

/** The value of each reported key that switches tools off (or moves them, for the governance mode). */
export const SWITCH_OFF_VALUES: Record<string, string | boolean> = {
  staking_enabled: false,
  staking_rewards_enabled: false,
  agora_distributions_enabled: false,
  governance_weight_mode: 'member',
  // §MEMBERSHIP phase B (V0551): the commons is off by default (COMMONS_ENABLED); its 11 tools then answer commons_disabled
  commons_enabled: false,
}

export interface TargetSwitchesReading {
  /** each reported switch in its off (or member) position, as `key=value`, in a fixed order */
  off: string[]
  /** the tool rows held to a switch's refusal, without the `theprotocol_` prefix */
  rows: string[]
  /** false when the run could not read the target's config: its rows were judged as on any registry */
  read: boolean
}

export function readTargetSwitches(switches: unknown, read: unknown, rows: unknown): TargetSwitchesReading | null {
  if (read === false) return { off: [], rows: [], read: false }
  if (!switches || typeof switches !== 'object' || Array.isArray(switches)) return null
  const s = switches as Record<string, unknown>
  const off = Object.keys(SWITCH_OFF_VALUES)
    .filter((k) => k in s && s[k] === SWITCH_OFF_VALUES[k])
    .map((k) => `${k}=${String(s[k])}`)
  const held = Array.isArray(rows)
    ? rows.filter((t): t is string => typeof t === 'string' && t.length > 0).map((t) => t.replace(/^theprotocol_/, ''))
    : []
  if (!off.length && !held.length) return null
  return { off, rows: held, read: true }
}
