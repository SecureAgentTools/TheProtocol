/**
 * §MCPTEST30 V0556 (agentvault2-45's point): the forge status read says the arena is dark ({enabled: false}, 200) where a
 * registry before V0556 refused it (403). getForgeStatus turns both into null, the "arena dark here" state GodelForge and
 * the organization dashboard already render, and passes a lit arena's status through unchanged.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { get } = vi.hoisted(() => ({ get: vi.fn() }))   // vi.mock is hoisted above the module's own lines
vi.mock('axios', () => ({ default: { create: () => ({ get }) } }))

import { getForgeStatus } from '../forge'

describe('getForgeStatus', () => {
  // a block body: a function RETURNED from beforeEach is run as the test's teardown (mockReset returns the mock)
  beforeEach(() => { get.mockReset() })

  it('reads enabled: false as the arena dark here (V0556 and later)', async () => {
    get.mockResolvedValue({ data: { enabled: false, detail: 'GÖDEL FORGE is not enabled on this registry (FORGE_ENABLED)', flags: {}, counts: {}, lineages: [] } })
    expect(await getForgeStatus()).toBeNull()
    expect(get).toHaveBeenCalledWith('/forge/status')
  })

  it('reads a refusal as the arena dark here (registries before V0556)', async () => {
    get.mockRejectedValue(Object.assign(new Error('Request failed with status code 403'), { response: { status: 403 } }))
    expect(await getForgeStatus()).toBeNull()
  })

  it('passes a lit arena through unchanged', async () => {
    const lit = { enabled: true, flags: { evals_agent_trigger: false, royalty: true, verifier_quorum_m: 2, royalty_default_bps: 500, royalty_max_bps: 2000, royalty_max_depth: 3 }, counts: { verifiers: 2 }, lineages: [] }
    get.mockResolvedValue({ data: lit })
    expect(await getForgeStatus()).toEqual(lit)
  })

  it('reads an empty answer as dark rather than a lit arena', async () => {
    get.mockResolvedValue({ data: undefined })
    expect(await getForgeStatus()).toBeNull()
  })

  it('reads a missing forge route as dark too', async () => {
    get.mockRejectedValue(Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } }))
    expect(await getForgeStatus()).toBeNull()
  })

  // §FESUITE (V0575): GodelForge drew "The arena is dark on this registry" over a status read that got no answer
  it('passes a read that got no answer, or a server error, to the caller: it is not the arena dark', async () => {
    const noAnswer = Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })
    get.mockRejectedValueOnce(noAnswer)
    await expect(getForgeStatus()).rejects.toBe(noAnswer)
    const badGateway = Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
    get.mockRejectedValueOnce(badGateway)
    await expect(getForgeStatus()).rejects.toBe(badGateway)
  })
})
