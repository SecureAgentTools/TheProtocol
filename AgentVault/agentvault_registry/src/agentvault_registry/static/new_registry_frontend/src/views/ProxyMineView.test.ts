// V0664 C3 (order gwo_4110e12c11a69a93de878829): #/proxy/mine. Loading, none, failed and filled said distinctly; the ledger read on
// request, with its own three states.
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ myProxies: vi.fn(), agentLedger: vi.fn() }))
vi.mock('@/services/api/proxyStatus', () => api)
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import { normalizeProxies } from '@/services/proxy/mine'
import ProxyMineView from './ProxyMineView.vue'

const stubs = { RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const ROW = normalizeProxies({ items: [{
  agent_did: 'did:theprotocol:eu:lyceum', reported_at: '2026-11-14T19:00:00Z', age_s: 95,
  report: { name: 'lyceum-credentials', sdk_version: '0.8.0', uptime_s: 7260,
    mappings: { credential: { pending: 2, done: 140, dead: 0, paused: false, breaker: null },
                revoked: { pending: 0, done: 3, dead: 1, paused: true, breaker: 'cooling' } },
    sources: { sis: { finished: false, last_read_at: '2026-11-14T18:59:30Z' } } },
}] })


// V0664 console proof (axe scrollable-region-focusable, session-lead seq 4206): a code box that can scroll is reachable by
// keyboard and named: tabindex 0, role region, an aria-label
function codeBoxesReachable(w: any) {
  const pres = w.findAll('pre')
  expect(pres.length).toBeGreaterThan(0)
  for (const p of pres) {
    expect(p.attributes('tabindex'), p.html().slice(0, 60)).toBe('0')
    expect(p.attributes('role')).toBe('region')
    expect((p.attributes('aria-label') || '').trim().length).toBeGreaterThan(3)
  }
}

describe('My proxies', () => {
  beforeEach(() => { api.myProxies.mockReset(); api.agentLedger.mockReset() })

  it('says it is reading, then that none reports yet and how a proxy starts to', async () => {
    let done: (v: unknown) => void = () => {}
    api.myProxies.mockReturnValue(new Promise((r) => (done = r)))
    const w = mount(ProxyMineView, { global: { stubs } })
    expect(w.find('[data-testid=pm-loading]').exists()).toBe(true)
    done([])
    await flushPromises()
    expect(w.find('[data-testid=pm-none]').text()).toContain('report_every_s')
  })

  it('a registry without the reports route says so, not a generic failure', async () => {
    api.myProxies.mockRejectedValue({ response: { status: 404, data: { detail: 'Not Found' } } })
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid=pm-failed]').text()).toBe('This registry does not keep proxy reports yet.')
  })

  it('a proxy: how fresh, its counts, what needs the owner, its mappings', async () => {
    api.myProxies.mockResolvedValue(ROW)
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    const card = w.find('[data-testid=pm-proxy-lyceum-credentials]')
    expect(w.find('[data-testid=pm-fresh-lyceum-credentials]').text()).toBe('Reporting')
    expect(card.text()).toContain('143')                                  // sent, both mappings
    // pass 1 D14: one line per mapping that needs the owner, every fact about it once
    const attn = w.find('[data-testid=pm-attn-lyceum-credentials]').text()
    expect(attn.match(/revoked/g)).toHaveLength(1)
    expect(attn).toContain('1 record given up')
    expect(attn).toContain('paused')
    expect(attn).toContain('breaker cooling')
    expect(attn).not.toContain('credential')
    // pass 1 D13: a mapping's name on a line of its own, its counts and state under it
    const revoked = w.find('[data-testid=pm-map-lyceum-credentials-revoked]')
    expect(revoked.find('code').text()).toBe('revoked')
    expect(revoked.text()).toContain('breaker cooling')
    expect(revoked.find('.bad').text()).toContain('1')
    expect(card.find('table').exists()).toBe(false)
  })

  it('says what each chip means, in a legend and in the chip\'s own title, so it is never a guess (pass 3, session-lead seq 4123)', async () => {
    api.myProxies.mockResolvedValue(ROW)
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    const said = (f: string) => w.findAll(`[data-testid=pm-legend-${f}] span`).map((x) => x.text())
    expect(said('fresh')).toEqual(['Reporting', 'A report within the last 10 minutes'])
    expect(said('quiet')).toEqual(['Quiet', 'The last report 10 to 60 minutes ago'])
    expect(said('silent')).toEqual(['Silent', 'No report for over an hour'])
    expect(w.find('[data-testid=pm-fresh-lyceum-credentials]').attributes('title')).toBe('A report within the last 10 minutes')
  })

  it('says how many need their owner (pass 4)', async () => {
    api.myProxies.mockResolvedValue(ROW)
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid=pm-need]').text()).toBe('1 of 1 needs you')
  })

  it('a source\'s last read is said as a time ago, its exact time in its title (pass 1 D12)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-14T19:00:00Z'))
    api.myProxies.mockResolvedValue(ROW)
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    const src = w.find('[data-testid=pm-source-lyceum-credentials-sis]')
    expect(src.text()).toContain('last read 30 s ago')
    expect(src.find('time').attributes('datetime')).toBe('2026-11-14T18:59:30Z')
    vi.useRealTimers()
  })

  it('the agent\'s DID is short on the card, copied whole (pass 1 D15)', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    api.myProxies.mockResolvedValue(ROW)
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid=pm-proxy-lyceum-credentials] .pm-did').text()).toBe('eu:lyceum')     // pass 3: the tail a card has room for
    expect(w.find('[data-testid=pm-proxy-lyceum-credentials] .pm-did').attributes('title')).toBe('did:theprotocol:eu:lyceum')
    await w.find('[data-testid=pm-did-copy-lyceum-credentials]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('did:theprotocol:eu:lyceum')
    expect(w.find('[data-testid=pm-did-copy-lyceum-credentials]').text()).toBe('Copied')
  })

  it('the ledger is read when asked, once, and its none and failed are said', async () => {
    api.myProxies.mockResolvedValue(ROW)
    api.agentLedger.mockResolvedValueOnce([{ id: 'b', type: 'TokensTransferred', amount: '1.5000000000', at: '2026-11-14T19:00:00Z' }])
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    expect(api.agentLedger).not.toHaveBeenCalled()
    await w.find('[data-testid=pm-ledger-lyceum-credentials]').trigger('click')
    await flushPromises()
    expect(api.agentLedger).toHaveBeenCalledWith('did:theprotocol:eu:lyceum')
    // pass 1 D11: the move in words, the amount without its trailing zeros, the time as a time ago (exact in its title)
    const rows = w.find('[data-testid=pm-ledger-rows-lyceum-credentials]')
    expect(rows.text()).toContain('Transfer')
    expect(rows.text()).toContain('1.5')
    expect(rows.text()).not.toContain('1.5000')
    expect(rows.find('time').attributes('datetime')).toBe('2026-11-14T19:00:00Z')
    expect(rows.find('time').text()).toMatch(/ago$/)
    await w.find('[data-testid=pm-ledger-lyceum-credentials]').trigger('click')       // hide
    await w.find('[data-testid=pm-ledger-lyceum-credentials]').trigger('click')       // show again: no second read
    expect(api.agentLedger).toHaveBeenCalledTimes(1)
  })

  it('a ledger that cannot be read says so beside the proxy', async () => {
    api.myProxies.mockResolvedValue(ROW)
    api.agentLedger.mockRejectedValue({ response: { status: 403, data: { detail: 'not your ledger' } } })
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid=pm-ledger-lyceum-credentials]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid=pm-proxy-lyceum-credentials] [role=alert]').text()).toBe('not your ledger')
  })

  it('the service block is reachable by keyboard and named (proof seq 4206)', async () => {
    api.myProxies.mockResolvedValue([])
    const w = mount(ProxyMineView, { global: { stubs } })
    await flushPromises()
    codeBoxesReachable(w)
  })
})
