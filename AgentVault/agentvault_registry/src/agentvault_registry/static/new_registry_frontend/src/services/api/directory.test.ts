import { describe, it, expect, vi, afterEach } from 'vitest'
import { directoryService } from './directory'

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => body })
  ;(globalThis as any).fetch = f
  return f
}

afterEach(() => { vi.restoreAllMocks() })

describe('§DIRFEED — the console reads the federated index', () => {
  it('asks the configured Directory, not this registry', async () => {
    const f = mockFetch(200, { data: { agents: { total: 1, edges: [{ cardId: 'c1', did: 'did:x', name: 'A' }] } } })
    const r = await directoryService.searchAgents('https://directory.example', 'a')
    expect(f.mock.calls[0][0]).toBe('https://directory.example/graphql')
    expect(r.total).toBe(1)
    expect(r.edges[0].cardId).toBe('c1')
  })

  it('THROWS on a GraphQL error that arrives inside a 200 — an unreadable index is not an empty world', async () => {
    mockFetch(200, { errors: [{ message: 'field agents not found' }], data: null })
    await expect(directoryService.searchAgents('https://d.example', '')).rejects.toThrow(/agents not found/)
  })

  it('throws on a transport failure too', async () => {
    mockFetch(502, {})
    await expect(directoryService.listings('https://d.example')).rejects.toThrow(/502/)
  })

  it('the control: an honest empty answer is an empty list, not an error', async () => {
    mockFetch(200, { data: { agents: { total: 0, edges: [] } } })
    const r = await directoryService.searchAgents('https://d.example', 'nobody')
    expect(r.total).toBe(0)
    expect(r.edges).toEqual([])
  })
})

describe('§MEMBERSHIP — the registry board asks an index only for the fields it knows', () => {
  const ok = { data: { status: { registriesTotal: 1, lastCycleAt: 1759400000 },
    registries: [{ name: 'sbx-alpha', tier: 'frame', currency: 'SBXA', membership: { state: 'ok', members: 3 }, commons: null }] } }
  function sequence(...bodies: unknown[]) {
    const f = vi.fn()
    for (const b of bodies) f.mockResolvedValueOnce({ ok: true, status: 200, json: async () => b })
    ;(globalThis as any).fetch = f
    return f
  }
  const unknown = (field: string) => ({ errors: [{ message: `Cannot query field '${field}' on type 'Registry'.` }], data: null })

  it('a current index: one question, the figures supported', async () => {
    const f = sequence(ok)
    const r = await directoryService.board('https://d.example')
    expect(f).toHaveBeenCalledTimes(1)
    expect(r.figures).toBe('supported')
    expect(r.registries[0].membership?.members).toBe(3)
  })

  it('an index older than the figures: the board asks again without exactly the fields it named, and says so', async () => {
    const f = sequence(unknown('membership'), unknown('commons'),
      { data: { status: { registriesTotal: 1, lastCycleAt: null }, registries: [{ name: 'sbx-alpha', tier: 'frame' }] } })
    const r = await directoryService.board('https://d.example')
    expect(f).toHaveBeenCalledTimes(3)
    const last = JSON.parse(f.mock.calls[2][1].body).query as string
    expect(last).not.toMatch(/membership|commons/)
    expect(last).toMatch(/\bname\b.*\bcurrency\b/s)
    expect(r).toMatchObject({ figures: 'unsupported', dropped: ['membership', 'commons'] })
    expect(r.registries[0]).toMatchObject({ name: 'sbx-alpha', membership: null, commons: null })
  })

  it('an index without the cancelled count (board1): the board asks again without exactly that sub-field, figures kept', async () => {
    const f = sequence({ errors: [{ message: "Cannot query field 'cancelledRecent' on type 'CommonsFigures'." }], data: null }, ok)
    const r = await directoryService.board('https://d.example')
    expect(f).toHaveBeenCalledTimes(2)
    expect(JSON.parse(f.mock.calls[0][1].body).query).toMatch(/\bcancelledRecent\b/)
    const second = JSON.parse(f.mock.calls[1][1].body).query as string
    expect(second).not.toMatch(/cancelledRecent/)
    expect(second).toMatch(/commons \{ state currency seasons/)                 // the rest of the block is still asked
    expect(r).toMatchObject({ figures: 'supported', dropped: ['commons.cancelledRecent'] })
  })

  it('control: an unknown sub-field that is not an optional one still fails (a renamed figure is a broken contract)', async () => {
    const f = sequence({ errors: [{ message: "Cannot query field 'members' on type 'MembershipFigures'." }], data: null })
    await expect(directoryService.board('https://d.example')).rejects.toThrow(/members/)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('control: any other error still fails, and a missing `name` is never asked around', async () => {
    sequence({ errors: [{ message: 'the federated index is unreachable' }], data: null })
    await expect(directoryService.board('https://d.example')).rejects.toThrow(/unreachable/)
    const f = sequence(unknown('name'))
    await expect(directoryService.board('https://d.example')).rejects.toThrow(/name/)
    expect(f).toHaveBeenCalledTimes(1)
  })
})
