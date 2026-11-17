// V0664 C3 (order gwo_4110e12c11a69a93de878829): My proxies, the owner's proxies that report their status (C2's
// GET /api/v1/developers/me/proxy-status) and each agent's recent ledger (GET /api/v1/teg/transactions/history/{did}, the
// owner's read). A report carries names and counts only, never a record or a config value.
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn() } }))
import { apiClient } from '@/services/api/client'
import { agentLedger, myProxies } from '@/services/api/proxyStatus'
import { attention, attentionGroups, formatAmount, freshness, ledgerKind, normalizeLedger, normalizeProxies, secondsSince, didTail, needsFirst } from './mine'

const get = apiClient.get as unknown as ReturnType<typeof vi.fn>

const ITEM = {
  agent_did: 'did:theprotocol:eu:lyceum', reported_at: '2026-11-14T19:00:00Z', age_s: 95,
  report: {
    name: 'lyceum-credentials', sdk_version: '0.8.0', uptime_s: 7260,
    mappings: { credential: { pending: 2, done: 140, dead: 0, paused: false, breaker: null },
                revoked: { pending: 0, done: 3, dead: 1, paused: true, breaker: 'cooling' } },
    sources: { sis: { finished: false, last_read_at: '2026-11-14T18:59:30Z' } },
  },
}

describe('a report, read', () => {
  it('names the proxy, its agent, its age and every mapping and source, with totals', () => {
    const [p] = normalizeProxies({ items: [ITEM] })
    expect(p!.did).toBe('did:theprotocol:eu:lyceum')
    expect(p!.name).toBe('lyceum-credentials')
    expect(p!.ageS).toBe(95)
    expect(p!.mappings.map((m) => m.name)).toEqual(['credential', 'revoked'])
    expect(p!.mappings[1]).toEqual({ name: 'revoked', pending: 0, done: 3, dead: 1, paused: true, breaker: 'cooling' })
    expect(p!.sources).toEqual([{ name: 'sis', finished: false, lastReadAt: '2026-11-14T18:59:30Z' }])
    expect(p!.totals).toEqual({ pending: 2, done: 143, dead: 1 })
  })

  it('keeps nothing it cannot read: a row with no agent is dropped, a count that is not a number reads 0', () => {
    const out = normalizeProxies({ items: [{ ...ITEM, agent_did: '' }, { ...ITEM, report: { ...ITEM.report, mappings: { m: { pending: 'x', done: 1 } } } }] })
    expect(out).toHaveLength(1)
    expect(out[0]!.mappings[0]).toEqual({ name: 'm', pending: 0, done: 1, dead: 0, paused: false, breaker: null })
    expect(normalizeProxies(null)).toEqual([])
    expect(normalizeProxies({ items: 'nope' })).toEqual([])
  })

  it('says how fresh a report is: fresh within 10 minutes, quiet within an hour, then silent', () => {
    expect(freshness(0)).toBe('fresh')
    expect(freshness(599)).toBe('fresh')
    expect(freshness(600)).toBe('quiet')
    expect(freshness(3599)).toBe('quiet')
    expect(freshness(3600)).toBe('silent')
  })

  it('says what needs the owner: dead records, a paused mapping, a breaker, a silent proxy', () => {
    const [p] = normalizeProxies({ items: [ITEM] })
    expect(attention(p!)).toEqual([
      { kind: 'dead', mapping: 'revoked', count: 1 },
      { kind: 'paused', mapping: 'revoked' },
      { kind: 'breaker', mapping: 'revoked', state: 'cooling' },
    ])
    const [q] = normalizeProxies({ items: [{ ...ITEM, age_s: 7200, report: { ...ITEM.report, mappings: { credential: ITEM.report.mappings.credential } } }] })
    expect(attention(q!)).toEqual([{ kind: 'silent' }])
  })
})

describe('the agent\'s recent ledger', () => {
  it('rows of what moved: the event, the amount, the time, newest first', () => {
    const rows = normalizeLedger({ transactions: [
      { id: 'a', event_type: 'TokensTransferred', amount: '5', timestamp: '2026-11-14T18:00:00Z' },
      { id: 'b', event_type: 'TokensTransferred', amount: '1.5', timestamp: '2026-11-14T19:00:00Z' },
      { event_type: 'no id' },
    ] })
    expect(rows.map((r) => r.id)).toEqual(['b', 'a'])
    expect(rows[0]).toEqual({ id: 'b', type: 'TokensTransferred', amount: '1.5', at: '2026-11-14T19:00:00Z' })
    expect(normalizeLedger({ transactions: [], error: 'Event Store unreachable' })).toEqual([])
  })
})

describe('the two reads', () => {
  it('My proxies reads the developer\'s list route, not one read per agent', async () => {
    get.mockResolvedValueOnce({ data: { items: [ITEM] } })
    const out = await myProxies()
    expect(get).toHaveBeenLastCalledWith('/developers/me/proxy-status', { expectedStatuses: [404] })
    expect(out[0]!.name).toBe('lyceum-credentials')
  })

  it('an agent\'s ledger reads the owner\'s history route, a few rows', async () => {
    get.mockResolvedValueOnce({ data: { transactions: [] } })
    await agentLedger('did:theprotocol:eu:lyceum')
    expect(get).toHaveBeenLastCalledWith('/teg/transactions/history/did%3Atheprotocol%3Aeu%3Alyceum', { params: { limit: 10 }, expectedStatuses: [403, 404] })
  })
})

// pass 1, D10-D15: what the page says, said for a person
describe('said for a person', () => {
  it('an amount without its trailing zeros, grouped as the language groups it, never rounded', () => {
    expect(formatAmount('1.5000000000', 'en')).toBe('1.5')
    expect(formatAmount('0.0075000000', 'en')).toBe('0.0075')
    expect(formatAmount('250', 'en')).toBe('250')
    expect(formatAmount('12500.10', 'en')).toBe('12,500.1')
    expect(formatAmount('12500.10', 'de')).toBe('12.500,1')
    expect(formatAmount('-3.00', 'en')).toBe('-3')
    expect(formatAmount('123456789012345678.000000000000000001', 'en')).toBe('123,456,789,012,345,678.000000000000000001')
    expect(formatAmount('', 'en')).toBe('')
    expect(formatAmount('n/a', 'en')).toBe('n/a')
  })

  it('a ledger event as a kind of move; an event it does not know keeps its name', () => {
    expect(ledgerKind('TokensTransferred')).toBe('transfer')
    expect(ledgerKind('CrossRegistryTransferCompleted')).toBe('transfer')
    expect(ledgerKind('TransactionFeeCollected')).toBe('fee')
    expect(ledgerKind('TokensIssued')).toBe('issued')
    expect(ledgerKind('SomethingNew')).toBe('other')
  })

  it('seconds since a time, and nothing for a time it cannot read', () => {
    const now = Date.parse('2026-11-14T19:00:00Z')
    expect(secondsSince('2026-11-14T18:59:30Z', now)).toBe(30)
    expect(secondsSince('2026-11-14T19:00:05Z', now)).toBe(0)
    expect(secondsSince('not a time', now)).toBeNull()
    expect(secondsSince('', now)).toBeNull()
  })

  it('what needs the owner, one line per mapping with every fact about it, then the proxy itself', () => {
    const [p] = normalizeProxies({ items: [{ ...ITEM, age_s: 7200 }] })
    expect(attentionGroups(p!)).toEqual([
      { mapping: 'revoked', facts: [{ kind: 'dead', mapping: 'revoked', count: 1 }, { kind: 'paused', mapping: 'revoked' }, { kind: 'breaker', mapping: 'revoked', state: 'cooling' }] },
      { mapping: null, facts: [{ kind: 'silent' }] },
    ])
  })

  it('a DID\'s tail short enough for a card: its network\'s first name, the start and the end of its id (passes 2 and 3)', () => {
    expect(didTail('did:theprotocol:eu.theprotocol.cloud:6b1c0a4e-2e7a-4f0b-9c55-0a8b3c1d2e3f')).toBe('eu:6b1c0a4e…2e3f')
    expect(didTail('did:theprotocol:asia.theprotocol.cloud:0fc15206-ca13-4257-884f-656866dd1bb1')).toBe('asia:0fc15206…1bb1')
    expect(didTail('did:theprotocol:eu:lyceum')).toBe('eu:lyceum')
    expect(didTail('did:theprotocol:6b1c0a4e-2e7a-4f0b-9c55-0a8b3c1d2e3f')).toBe('6b1c0a4e…2e3f')
    expect(didTail('not-a-did')).toBe('not-a-did')
  })
})

describe('many proxies (pass 4)', () => {
  it('the ones that need their owner first: silent, then records given up, then paused or a breaker; the rest as they came', () => {
    const mk = (name: string, age: number, m: Record<string, unknown> = {}) => ({ agent_did: `did:theprotocol:eu:${name}`, age_s: age,
      report: { name, mappings: { m: { pending: 0, done: 1, dead: 0, paused: false, breaker: null, ...m } } } })
    const rows = normalizeProxies({ items: [mk('ok1', 10), mk('paused', 10, { paused: true }), mk('ok2', 10), mk('dead', 10, { dead: 2 }),
                                            mk('silent', 7200), mk('breaker', 10, { breaker: 'open' })] })
    expect(needsFirst(rows).map((p) => p.name)).toEqual(['silent', 'dead', 'paused', 'breaker', 'ok1', 'ok2'])
  })
})
