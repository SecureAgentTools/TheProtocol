/**
 * §FESUITE (V0576): the staking store keeps whether the person's positions were read. stakingApi.getMyStakingStats
 * answers (it does not throw) when /staking/balance answered and /staking/my-positions did not: the total is the
 * ledger's, the list is [] and positionsReadable is false. The store dropped that flag, so the Staking view and the
 * Senate floor drew "No positions" beside a staked total; they now read stakingStore.positionsReadable.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { stakingApi } from '@/services'
import { useStakingStore } from './staking'

const answer = (positionsReadable: boolean, stakingPositions: any[] = []) =>
  ({ totalStaked: '250', availableRewards: '0', stakingPositions, positionsReadable }) as any

describe('the staking store keeps whether the positions were read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('a total that answered over positions that did not: positionsReadable false, the total kept', async () => {
    vi.spyOn(stakingApi, 'getMyStakingStats').mockResolvedValue(answer(false))
    const store = useStakingStore()
    await store.fetchMyStakingStats()
    expect(store.positionsReadable).toBe(false)
    expect(store.totalStaked).toBe('250')
    expect(store.positions).toEqual([])
  })

  it('a read that answered both halves: positionsReadable true again', async () => {
    const spy = vi.spyOn(stakingApi, 'getMyStakingStats').mockResolvedValue(answer(false))
    const store = useStakingStore()
    await store.fetchMyStakingStats()
    spy.mockResolvedValue(answer(true, [{ id: 'p1', amount: '250', startDate: '2026-10-01', lockPeriod: 30, apy: 0 }]))
    await store.fetchMyStakingStats()
    expect(store.positionsReadable).toBe(true)
    expect(store.positions).toHaveLength(1)
  })
})
