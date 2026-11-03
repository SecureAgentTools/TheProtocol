/**
 * V0654 (ar), order gwo_6a3d3f679899629bf1b4542d (his report in the sessions' room, seq 1083: the Pocket assistant's
 * conversation was gone when he came back): the conversation is kept for this browser session (sessionStorage), across
 * moves in the app and reloads, one conversation for Pocket's panel and the desktop dock; Clear empties it; signing out
 * removes it, like the personal key, which stays where it was. BASE (V0653): every panel starts empty.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get, post: h.post } }))
vi.mock('@/services/api/developers', () => ({
  developerApi: { getTegSummary: vi.fn().mockResolvedValue({ total_balance: 1, total_liquid_balance: 1, total_staked_balance: 0, agent_count: 1 }) },
}))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: { listings: vi.fn().mockResolvedValue({ listings: [] }) } }))

import { useAssistantBrains, CONVERSATION_KEY, BRAIN_KEY } from './useAssistantBrains'

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}
const texts = (b: ReturnType<typeof useAssistantBrains>) => b.msgs.value.map(m => `${m.role}:${m.text.slice(0, 12)}`)

describe("the assistant's conversation, kept for this browser session", () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    h.get.mockReset().mockResolvedValue({ data: {} })
    h.post.mockReset()
  })

  it('is there again when the panel is opened again (a move in the app, or a reload)', async () => {
    const first = useAssistantBrains({ autoOpenDoors: false })
    await first.handle('help')
    expect(first.msgs.value.length).toBe(2)
    const again = useAssistantBrains({ autoOpenDoors: false })       // the panel mounted anew
    expect(texts(again)).toEqual(texts(first))
    expect(again.msgs.value.map(m => m.id)).toEqual(first.msgs.value.map(m => m.id))
  })

  it('an answer that arrives after the panel was left is there when it is opened again', async () => {
    const answer = deferred<any>()
    h.post.mockImplementation(() => answer.promise)
    const left = useAssistantBrains({ autoOpenDoors: false })
    left.brain.value = 'bridge'
    const asked = left.handle('what needs me today?')
    const back = useAssistantBrains({ autoOpenDoors: false })        // he came back before the answer
    expect(texts(back)).toEqual(['user:what needs m'])
    answer.resolve({ data: { reply: 'Two approvals wait for you.' } })
    await asked
    expect(texts(back)).toEqual(['user:what needs m', 'assistant:Two approval'])
    expect(JSON.parse(sessionStorage.getItem(CONVERSATION_KEY) || '[]').length).toBe(2)
  })

  it('Pocket and the dock never write over each other', async () => {
    const pocket = useAssistantBrains({ autoOpenDoors: true })
    const dock = useAssistantBrains({ autoOpenDoors: false })
    await pocket.handle('help')
    await dock.handle('help')
    const kept = JSON.parse(sessionStorage.getItem(CONVERSATION_KEY) || '[]')
    expect(kept.length).toBe(4)
    expect(new Set(kept.map((m: any) => m.id)).size).toBe(4)
    expect(pocket.msgs.value.length).toBe(4)
  })

  it('Clear empties it, everywhere it shows, and keeps nothing; the personal key stays', async () => {
    localStorage.setItem('tp_byok', 'sk-test-not-a-real-key')
    const a = useAssistantBrains({ autoOpenDoors: false })
    const b = useAssistantBrains({ autoOpenDoors: false })
    await a.handle('help')
    a.clearConversation()
    expect(a.msgs.value).toEqual([])
    expect(b.msgs.value).toEqual([])
    expect(sessionStorage.getItem(CONVERSATION_KEY)).toBeNull()
    expect(useAssistantBrains({ autoOpenDoors: false }).msgs.value).toEqual([])
    expect(localStorage.getItem('tp_byok')).toBe('sk-test-not-a-real-key')
  })

  it('keeps the newest sixty, and reads a stored value that is not a message as nothing', async () => {
    sessionStorage.setItem(CONVERSATION_KEY, JSON.stringify([
      { id: 1, role: 'user', text: 'kept' }, { id: 2, role: 'system', text: 'not a role' }, { id: 'x', role: 'user', text: 'no id' },
      '<img src=x onerror=alert(1)>', null,
    ]))
    expect(texts(useAssistantBrains({ autoOpenDoors: false }))).toEqual(['user:kept'])
    sessionStorage.setItem(CONVERSATION_KEY, '{not json')
    expect(useAssistantBrains({ autoOpenDoors: false }).msgs.value).toEqual([])
    const b = useAssistantBrains({ autoOpenDoors: false })
    for (let i = 0; i < 31; i++) await b.handle('help')
    const kept = JSON.parse(sessionStorage.getItem(CONVERSATION_KEY) || '[]')
    expect(kept.length).toBe(60)
    expect(kept[kept.length - 1].id).toBe(62)
  })

  it('keeps the brain it was talking to, and falls back to Commands where the personal bridge is not there', async () => {
    const first = useAssistantBrains({ autoOpenDoors: false })
    expect(first.brain.value).toBe('grammar')
    first.brain.value = 'bridge'
    await Promise.resolve()
    expect(sessionStorage.getItem(BRAIN_KEY)).toBe('bridge')
    h.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/assistant/status' ? { bridge: { enabled: true } } : {} }))
    const back = useAssistantBrains({ autoOpenDoors: false })
    await back.loadStatus()
    expect(back.brain.value).toBe('bridge')
    h.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/assistant/status' ? { bridge: { enabled: false } } : {} }))
    const elsewhere = useAssistantBrains({ autoOpenDoors: false })
    await elsewhere.loadStatus()
    expect(elsewhere.brain.value).toBe('grammar')
    sessionStorage.setItem(BRAIN_KEY, 'something-else')
    expect(useAssistantBrains({ autoOpenDoors: false }).brain.value).toBe('grammar')
  })

  it('is removed when the session ends on this device, with the personal key', async () => {
    setActivePinia(createPinia())
    sessionStorage.setItem(CONVERSATION_KEY, JSON.stringify([{ id: 1, role: 'user', text: 'mine' }]))
    sessionStorage.setItem(BRAIN_KEY, 'bridge')
    sessionStorage.setItem('tp_assistant_draft', 'a shared draft')       // the control: not the conversation
    const { useAuthStore } = await import('@/stores/auth')
    await useAuthStore().endLocalSession('a unit test')
    expect(sessionStorage.getItem(CONVERSATION_KEY)).toBeNull()
    expect(sessionStorage.getItem(BRAIN_KEY)).toBeNull()
    expect(sessionStorage.getItem('tp_assistant_draft')).toBe('a shared draft')
  }, 30_000)   // the auth store's module graph is slow to import under a loaded host
})
