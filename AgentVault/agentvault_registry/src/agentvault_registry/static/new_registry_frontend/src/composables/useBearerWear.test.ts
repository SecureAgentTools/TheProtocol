// V0666 wearing an earned item on a chosen bearer: the developer's own routes for ME, the agent routes for an agent; a press on what is worn takes it off; the registry's
// sentence answers a refusal where it was asked; a title is only ever the developer's; the page refreshes from the registry after every press.
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ equip: vi.fn(), wear: vi.fn(), onAgent: vi.fn() }))
vi.mock('@/services/api/contributorTrack', () => ({ equipTitle: (...a: any[]) => h.equip(...a), wearEarned: (...a: any[]) => h.wear(...a), wearEarnedOnAgent: (...a: any[]) => h.onAgent(...a) }))

import { useBearerWear } from './useBearerWear'
import { ME } from '@/services/flareBearers'

const item = (kind: 'corner' | 'encirclement' | 'title', key: string) => ({ kind, key, tier: 1, side: false, condition: 'x', unlocked: true }) as any
const me = { key: ME, kind: 'developer', did: null, name: 'Ada' } as const
const agent = { key: 'did:a', kind: 'agent', did: 'did:a', name: 'A' } as const

describe('wearing on a bearer', () => {
  let refresh: ReturnType<typeof vi.fn>
  const mk = () => useBearerWear({ failedWords: 'nope', refresh: refresh as any })
  beforeEach(() => {
    refresh = vi.fn().mockResolvedValue(undefined)
    h.equip.mockReset().mockResolvedValue({ title: 'patchwright' })
    h.wear.mockReset().mockResolvedValue({})
    h.onAgent.mockReset().mockResolvedValue({})
  })

  it("wears a ring or a badge through the developer's routes for the developer", async () => {
    const w = mk()
    await w.wear(item('encirclement', 'ember'), me, false)
    await w.wear(item('corner', 'initiate'), me, false)
    expect(h.wear).toHaveBeenNthCalledWith(1, 'encirclement', 'ember')
    expect(h.wear).toHaveBeenNthCalledWith(2, 'corner', 'initiate')
    expect(h.onAgent).not.toHaveBeenCalled()
    expect(refresh).toHaveBeenCalledTimes(2)
  })

  it('wears it through the agent routes for an agent, and a press on what is worn takes it off', async () => {
    const w = mk()
    await w.wear(item('encirclement', 'ember'), agent, false)
    await w.wear(item('corner', 'initiate'), agent, true)
    expect(h.onAgent).toHaveBeenNthCalledWith(1, 'did:a', 'encirclement', 'ember')
    expect(h.onAgent).toHaveBeenNthCalledWith(2, 'did:a', 'corner', null)
    expect(h.wear).not.toHaveBeenCalled()
  })

  it('wears a title for the developer only and tells the sidebar', async () => {
    const w = mk()
    const seen: any[] = []
    window.addEventListener('ct:title', (e: any) => seen.push(e.detail), { once: true })
    await w.wear(item('title', 'patchwright'), me, false)
    expect(h.equip).toHaveBeenCalledWith('patchwright')
    expect(seen).toEqual(['patchwright'])
    await w.wear(item('title', 'patchwright'), me, true)
    expect(h.equip).toHaveBeenLastCalledWith(null)
  })

  it('takes the chosen title off so the COMMANDER title is worn again, and tells the sidebar', async () => {
    const w = mk()
    const seen: any[] = []
    window.addEventListener('ct:title', (e: any) => seen.push(e.detail), { once: true })
    h.equip.mockResolvedValue({ title: null })
    await w.takeOffTitle()
    expect(h.equip).toHaveBeenCalledWith(null)
    expect(seen).toEqual([null])
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('never asks for a title on an agent', async () => {
    const w = mk()
    await w.wear(item('title', 'patchwright'), agent, false)
    expect(h.equip).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
  })

  it("shows the registry's sentence where the press was made, then refreshes so the page tells the truth", async () => {
    h.onAgent.mockRejectedValue({ response: { data: { detail: 'This agent wears a bought ring. Take it off first, then give it the unlocked one.' } } })
    const w = mk()
    await w.wear(item('encirclement', 'ember'), agent, false)
    expect(w.errors['encirclement:ember']).toMatch(/bought ring/)
    expect(w.busyKey.value).toBe('')
    expect(refresh).toHaveBeenCalledTimes(1)
    await w.wear(item('encirclement', 'ember'), agent, false)                         // a new press clears the old sentence first
    expect(w.errors['encirclement:ember']).toMatch(/bought ring/)
  })

  it('names itself busy while the registry answers', async () => {
    let done: () => void = () => {}
    h.wear.mockReturnValue(new Promise<void>((r) => { done = r }))
    const w = mk()
    const p = w.wear(item('corner', 'initiate'), me, false)
    expect(w.busyKey.value).toBe('corner:initiate')
    done(); await p
    expect(w.busyKey.value).toBe('')
  })
})
