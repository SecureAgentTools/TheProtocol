// §FEFRAME W3.1: a service singleton reads the shared HTTP client when a request is MADE, never when its module loads.
// The client module and the stores import each other; when the client module is evaluated first (the entry order since
// V0502), every `export const xApi = new XApi()` evaluated inside that cycle captured an undefined client and every call
// threw "Cannot read properties of undefined (reading 'get')" (My Agents, the federation peers). This file imports the
// client module FIRST, which is the order that broke, and asks each singleton for the client it will use.
import { describe, it, expect } from 'vitest'

describe('service singletons and the shared client', () => {
  it('every singleton built while the client module loads still uses the client', async () => {
    const { apiClient } = await import('./client')
    const singletons: Record<string, unknown> = {
      agentApi: (await import('./agents')).agentApi,
      attestationsApi: (await import('./attestations')).attestationsApi,
      developerApi: (await import('./developer')).developerApi,
      developersApi: (await import('./developers')).developerApi,
      federationApi: (await import('./federation')).federationApi,
      governanceApi: (await import('./governance')).governanceApi,
      stakingApi: (await import('./staking')).stakingApi,
      stakingRewardsApi: (await import('./stakingRewards')).stakingRewardsApi,
      tegApi: (await import('./teg')).tegApi,
    }
    expect(apiClient).toBeTruthy()
    const missing = Object.entries(singletons).filter(([, s]) => (s as { client?: unknown }).client !== apiClient).map(([n]) => n)
    expect(missing).toEqual([])
  })

  it('a client handed to the constructor is the one used', async () => {
    const { GovernanceApi } = await import('./governance')
    const own = { get: () => null } as never
    expect((new GovernanceApi(own) as unknown as { client: unknown }).client).toBe(own)
  })

  it('no service captures the client as a constructor default', async () => {
    // the shape that breaks under the cycle, refused at the source (the order-dependent half is measured above and in
    // the browser: scratchpad/feframe/w3_cycle_probe.mjs)
    const files = import.meta.glob('./*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
    const offenders = Object.entries(files)
      .filter(([p]) => !p.endsWith('.test.ts'))
      .filter(([, src]) => /constructor\s*\([^)]*=\s*apiClient\b/.test(src))
      .map(([p]) => p)
    expect(Object.keys(files).length).toBeGreaterThan(20)
    expect(offenders).toEqual([])
  })
})
