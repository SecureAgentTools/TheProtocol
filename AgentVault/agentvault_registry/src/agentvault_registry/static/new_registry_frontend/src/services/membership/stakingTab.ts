/**
 * §MEMBERSHIP (V0564; agentvault2-81's finding, agentvault2-33's fix): the Senate floor's Staking tab on a registry that
 * opens no new locks, or that votes by membership.
 *
 * Production runs member mode with STAKING_ENABLED=false from V0564 (his word 2026-10-03 "the rest can go production
 * cluster"). The tab was ungated and the page's DEFAULT, so every visit read "Lock units to gain voting weight." where a
 * lock gives no weight and no new lock opens. Hiding the tab outright would hide the only console door to UNSTAKE the
 * positions people still hold (core/staking_gate.py keeps unstake working so nobody's units are stuck), so the rule is:
 * the tab exists where new positions open, or where the person still holds positions to release; nowhere else.
 *
 * Fail-closed, like the rates (§BAFIN B.5.5): an absent or unread config opens no new position.
 */
import type { RegistryConfig } from '@/composables/useRegistryConfig'
import { governanceMode } from './membership'

/** New positions open only where the registry says staking_enabled is true. */
export function stakingOpen(cfg: RegistryConfig | null | undefined): boolean {
  return cfg?.staking_enabled === true
}

/** The tab exists where positions can be opened, or where the person still holds positions to unstake. */
export function stakingTabShown(cfg: RegistryConfig | null | undefined, heldPositions: number): boolean {
  return stakingOpen(cfg) || heldPositions > 0
}

/** What the tab may say a lock is for: never voting weight where the registry votes by membership. */
export function lockSentence(cfg: RegistryConfig | null | undefined): 'gives_weight' | 'no_weight_member' {
  return governanceMode(cfg) === 'member' ? 'no_weight_member' : 'gives_weight'
}
