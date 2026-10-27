/**
 * §BAFIN (2026-10-01) — the lock periods a staking position can take where staking rewards are switched off.
 *
 * With STAKING_REWARDS_ENABLED=false (core/staking_gate.py) every APY-tier read answers no tiers, while a lock still
 * buys governance weight (veToken). The pickers fall back to these periods, which mirror
 * DynamicAPYConfig.lock_presets in services/dynamic_apy_engine.py, and carry no rate: apy and lockPremium are 0 and
 * every surface hides them where registry-config says staking_rewards_enabled is false.
 */
export const LOCK_PRESETS_DAYS: readonly number[] = [0, 30, 90, 180, 365]

export interface LockOnlyTier {
  lockPeriod: number
  apy: number
  lockPremium: number
  minAmount: string
  label: string
  description: string
}

export function lockOnlyTiers(): LockOnlyTier[] {
  return LOCK_PRESETS_DAYS.map((d) => ({
    lockPeriod: d,
    apy: 0,
    lockPremium: 0,
    minAmount: '0',
    label: d === 0 ? 'Flexible' : `${d} days`,
    description: '',
  }))
}
