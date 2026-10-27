/**
 * §COCKPITDESK (2026-10-14) — saved desk layouts and the dashboard's one board, over the prefs rail.
 *
 * The rail replaces the WHOLE value on every PUT (the write that once destroyed a saved 9-pane layout), so the rules here are
 * the ones that keep the screen and the server agreeing: unknown panes and unusable sizes are dropped on READ; a choice made
 * before the read lands is not undone by it; every write is sent first and adopted only if the server took it (a refused
 * write puts the list AND the selection back and says why); starters are built in and cannot be renamed or deleted; the
 * dashboard keeps three states apart (unset ⇒ the default four, an empty board ⇒ empty, set ⇒ theirs).
 *
 * The composable holds module-level state, so every test imports a fresh module.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: api }))

type Mod = typeof import('./useCockpitLayouts')
async function fresh(): Promise<Mod> {
  vi.resetModules()
  return await import('./useCockpitLayouts')
}
const stored = (value: unknown) => api.get.mockResolvedValueOnce({ data: { value } })
const lastPut = () => api.put.mock.calls[api.put.mock.calls.length - 1]

// the module graph (the pane registry) is transformed once, here, with time to spare: in a full parallel run the first
// test paid it and met the 5 s test timeout (2026-10-15, 5026 ms; 2.4 s for the whole file alone)
beforeAll(async () => { await import('./useCockpitLayouts') }, 30_000)

beforeEach(() => {
  api.get.mockReset(); api.put.mockReset()
  api.put.mockResolvedValue({ data: {} })
})

describe('reading saved layouts', () => {
  it('drops unknown panes and unusable sizes, trims long names, and applies the stored selection', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({
      activeId: 'u_mine',
      layouts: [
        { id: 'u_mine', name: 'x'.repeat(60), panes: ['decisions', 'not-a-pane', 'stop', 7], sizes: { decisions: 3, stop: 9, bogus: 2, chats: 'tall' } },
        { id: 42, panes: ['stop'] },
        { name: 'no id', panes: ['stop'] },
      ],
    })
    await L.load()
    expect(L.saved.value).toHaveLength(1)
    const mine = L.saved.value[0]
    expect(mine.panes).toEqual(['decisions', 'stop'])
    expect(mine.sizes).toEqual({ decisions: 3 })
    expect(mine.name).toHaveLength(40)
    expect(L.activeId.value).toBe('u_mine')
    expect(L.active.value.id).toBe('u_mine')
    expect(L.all.value.length, 'the starters are always there').toBeGreaterThan(1)
  })

  it('does not undo a layout the person picked while the read was in flight', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    let answer!: (v: unknown) => void
    api.get.mockReturnValueOnce(new Promise(r => { answer = r }))
    const loading = L.load()
    await L.setActive('money')
    expect(api.put, 'a selection made before the first read is not written').not.toHaveBeenCalled()
    answer({ data: { value: { activeId: 'triage', layouts: [] } } })
    await loading
    expect(L.activeId.value).toBe('money')
  })

  it('keeps the starters working when the saved layouts cannot be read, and says why', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    api.get.mockRejectedValueOnce({ response: { data: { detail: 'prefs unavailable' } } })
    await L.load()
    expect(L.error.value).toBe('prefs unavailable')
    expect(L.active.value.builtin).toBe(true)
  })

  it('falls back to the first starter when the stored selection names nothing that exists', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ activeId: 'u_gone', layouts: [] })
    await L.load()
    expect(L.active.value.id).toBe(L.all.value[0].id)
  })
})

describe('writing saved layouts', () => {
  it('saves under a name, replaces a layout of the same name, selects it, and sends the whole value', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ layouts: [{ id: 'u_old', name: 'Mine', panes: ['stop'] }] })
    await L.load()
    const id = await L.saveLayout('Mine', ['decisions', 'stop'], { decisions: 2 })
    expect(id.startsWith('u_mine_')).toBe(true)
    expect(L.saved.value.map(l => l.name)).toEqual(['Mine'])
    expect(L.saved.value[0].id).toBe(id)
    expect(L.activeId.value).toBe(id)
    const [path, body] = lastPut()
    expect(path).toBe('/developers/me/prefs/cockpit.layouts')
    expect(body.value.activeId).toBe(id)
    expect(body.value.layouts).toEqual([{ id, name: 'Mine', panes: ['decisions', 'stop'], sizes: { decisions: 2 } }])
  })

  it('keeps the newest twelve when a thirteenth is saved', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ layouts: Array.from({ length: 12 }, (_, i) => ({ id: `u_${i}`, name: `L${i}`, panes: ['stop'] })) })
    await L.load()
    await L.saveLayout('L12', ['stop'])
    expect(L.saved.value).toHaveLength(12)
    expect(L.saved.value[0].name).toBe('L1')
    expect(L.saved.value[11].name).toBe('L12')
  })

  it('puts the list and the selection back when the server refuses a save, and says so', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ activeId: 'trading', layouts: [{ id: 'u_a', name: 'A', panes: ['stop'] }] })
    await L.load()
    api.put.mockRejectedValueOnce(new Error('413 too large'))
    await expect(L.saveLayout('B', ['market'])).rejects.toThrow('413 too large')
    expect(L.saved.value.map(l => l.id)).toEqual(['u_a'])
    expect(L.activeId.value).toBe('trading')
  })

  it('renames in place, keeping the id every selection points at', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ activeId: 'u_a', layouts: [{ id: 'u_a', name: 'A', panes: ['stop'] }] })
    await L.load()
    await L.renameLayout('u_a', '  Night shift  ')
    expect(L.saved.value).toEqual([{ id: 'u_a', name: 'Night shift', panes: ['stop'], sizes: {} }])
    expect(L.activeId.value).toBe('u_a')
  })

  it('refuses a blank name, a starter and a layout that is not saved, and rolls a refused rename back', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ layouts: [{ id: 'u_a', name: 'A', panes: ['stop'] }] })
    await L.load()
    await expect(L.renameLayout('u_a', '   ')).rejects.toThrow()
    await expect(L.renameLayout('triage', 'Mine')).rejects.toThrow()
    await expect(L.renameLayout('u_none', 'Mine')).rejects.toThrow()
    expect(api.put).not.toHaveBeenCalled()
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(L.renameLayout('u_a', 'B')).rejects.toThrow('offline')
    expect(L.saved.value[0].name).toBe('A')
  })

  it('deletes only saved layouts, and moves the selection off a deleted one', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ activeId: 'u_a', layouts: [{ id: 'u_a', name: 'A', panes: ['stop'] }, { id: 'u_b', name: 'B', panes: ['stop'] }] })
    await L.load()
    await expect(L.deleteLayout('triage')).rejects.toThrow()
    await expect(L.deleteLayout('u_none')).rejects.toThrow()
    await L.deleteLayout('u_a')
    expect(L.saved.value.map(l => l.id)).toEqual(['u_b'])
    expect(L.isBuiltin(L.activeId.value), 'the selection lands on a starter').toBe(true)
    await L.setActive('u_b')
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(L.deleteLayout('u_b')).rejects.toThrow('offline')
    expect(L.saved.value.map(l => l.id)).toEqual(['u_b'])
    expect(L.activeId.value).toBe('u_b')
  })

  it('writes a selection after the first read, and a refused selection write is quiet', async () => {
    const m = await fresh()
    const L = m.useCockpitLayouts()
    stored({ layouts: [] })
    await L.load()
    await L.setActive('money')
    expect(lastPut()[1].value.activeId).toBe('money')
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(L.setActive('trading')).resolves.toBeUndefined()
    expect(L.activeId.value).toBe('trading')
  })
})

describe("the dashboard's one board", () => {
  it('shows the default four when nothing is stored, and an empty board when the person emptied it', async () => {
    let m = await fresh()
    let D = m.useDashboardLayout()
    stored(null)
    await D.load()
    expect(D.layout.value.panes).toEqual(m.DASHBOARD_DEFAULT.panes)
    expect(D.isDefault.value).toBe(true)

    m = await fresh()
    D = m.useDashboardLayout()
    stored({ panes: [], sizes: {} })
    await D.load()
    expect(D.layout.value.panes, 'an emptied board stays empty').toEqual([])
    expect(D.isDefault.value).toBe(false)
  })

  it('sends a save first and keeps what the server holds when it refuses', async () => {
    const m = await fresh()
    const D = m.useDashboardLayout()
    stored({ panes: ['market'], sizes: {} })
    await D.load()
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(D.save(['book', 'chats'], { book: 2 })).rejects.toThrow('offline')
    expect(D.layout.value.panes).toEqual(['market'])
    await D.save(['book', 'not-a-pane' as never, 'chats'], { book: 2 })
    expect(D.layout.value.panes).toEqual(['book', 'chats'])
    expect(lastPut()).toEqual(['/developers/me/prefs/cockpit.dashboard', { value: { panes: ['book', 'chats'], sizes: { book: 2 } } }])
  })

  it('stores the default when reset, rather than only showing it', async () => {
    const m = await fresh()
    const D = m.useDashboardLayout()
    stored({ panes: ['book'], sizes: { book: 4 } })
    await D.load()
    await D.reset()
    expect(lastPut()[1]).toEqual({ value: { panes: [...m.DASHBOARD_DEFAULT.panes], sizes: {} } })
    expect(D.isDefault.value).toBe(true)
  })

  // §COCKPITDESK (2026-10-15): the board can show one of the desk's layouts instead of its own arrangement.
  it('reads the desk layout the board follows, and drops one that is not a plain id', async () => {
    let m = await fresh()
    let D = m.useDashboardLayout()
    stored({ panes: ['book'], sizes: { book: 2 }, follow: 'u_night_abc' })
    await D.load()
    expect(D.follow.value).toBe('u_night_abc')
    expect(D.layout.value.panes, "the board's own arrangement is kept beside it").toEqual(['book'])

    m = await fresh()
    D = m.useDashboardLayout()
    stored({ panes: ['book'], follow: '../../etc' })
    await D.load()
    expect(D.follow.value).toBeNull()
  })

  it("sends a follow with the board's own panes and sizes, and puts it back when refused", async () => {
    const m = await fresh()
    const D = m.useDashboardLayout()
    stored({ panes: ['market', 'chats'], sizes: { chats: 3 } })
    await D.load()
    await D.setFollow('money')
    expect(lastPut()).toEqual(['/developers/me/prefs/cockpit.dashboard',
      { value: { panes: ['market', 'chats'], sizes: { chats: 3 }, follow: 'money' } }])
    expect(D.follow.value).toBe('money')
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(D.setFollow('triage')).rejects.toThrow('offline')
    expect(D.follow.value, 'the registry still holds money').toBe('money')
    const n = api.put.mock.calls.length
    await D.setFollow('money')
    expect(api.put.mock.calls.length, 'the same choice again sends nothing').toBe(n)
    await D.setFollow(null)
    expect(lastPut()[1], 'back to its own: no follow key').toEqual({ value: { panes: ['market', 'chats'], sizes: { chats: 3 } } })
  })

  it('stops following when the board saves its own arrangement, and follows again if that save is refused', async () => {
    const m = await fresh()
    const D = m.useDashboardLayout()
    stored({ panes: ['market'], sizes: {}, follow: 'trading' })
    await D.load()
    api.put.mockRejectedValueOnce(new Error('offline'))
    await expect(D.save(['book'])).rejects.toThrow('offline')
    expect(D.follow.value).toBe('trading')
    await D.save(['book'])
    expect(D.follow.value).toBeNull()
    expect(lastPut()[1]).toEqual({ value: { panes: ['book'], sizes: {} } })
  })

  it('says why when the board cannot be read, and keeps the default', async () => {
    const m = await fresh()
    const D = m.useDashboardLayout()
    api.get.mockRejectedValueOnce(new Error('Network Error'))
    await D.load()
    expect(D.error.value).toBe('Network Error')
    expect(D.layout.value.panes).toEqual(m.DASHBOARD_DEFAULT.panes)
  })
})
