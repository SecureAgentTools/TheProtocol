import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-05): the Multi-Frame Console's agent list on a peer read "You own no agents on <peer> through this
 * account" when every read of it failed, because peerListAgents answered [] for "no shape answered" and for "a shape
 * answered with none" alike. A failed read rejects now; an answered empty list is still none.
 */
const dg = vi.hoisted(() => vi.fn())
vi.mock('./peerDirect', () => ({ directGet: dg, apiBase: (b: string) => b }))

import { peerListAgents } from './peer'

const refused = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('peerListAgents says a failed read as one', () => {
  // braces: a function returned from a hook is its teardown, and mockReset() returns the spy itself
  beforeEach(() => { dg.mockReset() })

  it('rejects when no shape answered at all', async () => {
    dg.mockRejectedValue(Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' }))
    await expect(peerListAgents('eu', 'tok', 'https://eu.example')).rejects.toThrow('Network Error')
    expect(dg).toHaveBeenCalledTimes(3)
  })

  it('a shape that answered with an empty list is none', async () => {
    dg.mockRejectedValueOnce(refused(403)).mockResolvedValueOnce([]).mockResolvedValueOnce({ agents: [] })
    await expect(peerListAgents('eu', 'tok', 'https://eu.example')).resolves.toEqual([])
  })

  it('the first shape that answers with agents is the list', async () => {
    dg.mockRejectedValueOnce(refused(403)).mockResolvedValueOnce({ agents: [{ did: 'did:x', name: 'A', client_id: 'c' }] })
    const r = await peerListAgents('eu', 'tok', 'https://eu.example')
    expect(r).toEqual([{ name: 'A', client_id: 'c', did: 'did:x', humanReadableId: undefined }])
    expect(dg).toHaveBeenCalledTimes(2)
  })
})
