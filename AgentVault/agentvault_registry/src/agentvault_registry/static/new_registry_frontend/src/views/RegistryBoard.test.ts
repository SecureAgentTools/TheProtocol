import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the registry board page: it opens only where this registry runs membership or a
 * commons, reads the Directory through this registry's own address, says when it cannot, and shows each registry's
 * members and commons with no price, no rate and none of the retired words.
 */
const h = vi.hoisted(() => ({ board: vi.fn(), cfg: null as any }))
vi.mock('@/services/api/directory', () => ({ directoryService: { board: h.board } }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => h.cfg }))

import RegistryBoard from './RegistryBoard.vue'

// (the lead itself says the page has no price, so "price" is not on this list)
const FORBIDDEN = /\b(yield|apy|dividends?|shares?|returns?|investments?|rewards?|interest)\b/i
function config(c: Record<string, unknown>, directoryUrl = '/api/v1/public/directory') {
  return { config: ref(c), loaded: ref(true), directoryUrl: ref(directoryUrl) }
}
const M = (over: Record<string, unknown> = {}) => ({ state: 'ok', mode: 'member', members: 3, joined30d: 2, left30d: 1, presenceMode: 'conditional',
  minBondAgeDays: 0, tenureFullDays: 365, asOf: null, readAt: 1759400000, checkedAt: 1759400000, error: null, ...over })
const row = (name: string, membership: any, commons: any = null) => ({ name, tier: 'frame', location: 'Sandbox', currency: 'SBXA',
  publicUrl: `https://${name}.example`, verified: true, reachable: true, membership, commons })

beforeEach(() => {
  h.board.mockReset()
  h.cfg = config({ governance_weight_mode: 'member' })
})

describe('the registry board', () => {
  it('where this registry runs neither membership nor a commons, nothing of the board shows and the index is not asked', async () => {
    h.cfg = config({ governance_weight_mode: 'lock' })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.attributes('data-state')).toBe('off')
    expect(w.text()).toBe('')                                   // not even a note naming the unreleased feature
    expect(h.board).not.toHaveBeenCalled()
  })

  it('control: before the registry configuration arrives, nothing of the board shows and nobody is sent away', async () => {
    h.cfg = { config: ref({}), loaded: ref(false), directoryUrl: ref('/api/v1/public/directory') }
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.text()).not.toMatch(/member|commons|registr/i)
    expect(h.board).not.toHaveBeenCalled()
  })

  it('opens where only the commons runs, too', async () => {
    h.cfg = config({ commons_enabled: true })
    h.board.mockResolvedValue({ registries: [], registriesTotal: 0, lastCycleAt: null })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.attributes('data-state')).toBe('ready')
    expect(w.find('[data-testid="board-empty"]').exists()).toBe(true)
  })

  it('says so when this registry has no federated index, or when the index cannot be read', async () => {
    h.cfg = config({ governance_weight_mode: 'member' }, '')
    const a = mount(RegistryBoard); await flushPromises()
    expect(a.attributes('data-state')).toBe('no-index')
    expect(h.board).not.toHaveBeenCalled()
    h.cfg = config({ governance_weight_mode: 'member' })
    h.board.mockRejectedValue(new Error('directory http 502'))
    const b = mount(RegistryBoard); await flushPromises()
    expect(b.attributes('data-state')).toBe('failed')
    expect(h.board).toHaveBeenCalledWith('/api/v1/public/directory')
  })

  it('every card gives the place a line of its own, under the name, the tag and the Visit link', async () => {
    h.board.mockResolvedValue({ registriesTotal: 2, lastCycleAt: 1759400000, registries: [
      { ...row('eu', M()), location: 'Brussels, Belgium', currency: 'ECU' },
      { ...row('a-registry-with-a-much-longer-name', M()), location: 'Ho Chi Minh City, Vietnam', currency: 'ACU' },
    ] })
    const w = mount(RegistryBoard); await flushPromises()
    const cards = w.findAll('[data-testid="board-row"]')
    expect(cards.length).toBe(2)
    for (const c of cards) {
      const top = c.find('.rb-card__top')
      expect(top.find('.rb-name').exists() && top.find('.rb-link').exists()).toBe(true)
      expect(top.text()).not.toMatch(/ECU|ACU|Belgium|Vietnam/)
      expect(top.element.nextElementSibling?.getAttribute('data-testid')).toBe('board-where')
    }
    expect(cards.map((c) => c.find('[data-testid="board-where"]').text()).sort()).toEqual(['Brussels, Belgium · ECU', 'Ho Chi Minh City, Vietnam · ACU'])
  })

  it('shows each registry\'s members and commons, each figure in its own state, with no price and no retired word', async () => {
    h.board.mockResolvedValue({ registriesTotal: 4, lastCycleAt: 1759400000, registries: [
      row('sbx-beta', M({ members: 1, joined30d: 0, left30d: 2 }), { state: 'switched_off', currency: null, seasons: [], readAt: 1, checkedAt: 1, error: null }),
      row('sbx-alpha', M(), { state: 'ok', currency: 'SBXA', readAt: 1759400000, checkedAt: 1759400000, error: null,
        seasons: [{ id: 4, title: 'Autumn', status: 'open', budget: '500', paidTotal: '0', submissions: 3, ballots: 2,
          opensAt: null, endsAt: null, closedAt: null, paidAt: null, cancelledAt: null }] }),
      row('eu', M({ state: 'absent', members: null }), { state: 'absent', currency: null, seasons: [], readAt: null, checkedAt: 1, error: null }),
      row('fresh', null, null),
    ] })
    const w = mount(RegistryBoard); await flushPromises()
    const names = w.findAll('[data-testid="board-row"]').map((r) => r.attributes('data-name'))
    expect(names).toEqual(['sbx-alpha', 'sbx-beta', 'eu', 'fresh'])          // most members first; then not published; then not checked
    const alpha = w.find('[data-name="sbx-alpha"]')
    expect(alpha.find('[data-testid="board-members"]').text()).toContain('3')
    expect(alpha.find('[data-testid="board-net"]').text()).toBe('+1')
    expect(alpha.find('[data-testid="board-commons"]').text()).toContain('#4 Autumn')
    expect(alpha.find('[data-testid="board-commons"]').text()).toContain('Budget 500 SBXA')
    expect(w.find('[data-name="sbx-beta"] [data-testid="board-net"]').text()).toBe('−2')
    expect(w.find('[data-name="sbx-beta"] [data-testid="board-commons"]').attributes('data-kind')).toBe('off')
    expect(w.find('[data-name="eu"] [data-testid="board-members"]').text()).toContain('Not published')
    expect(w.find('[data-name="fresh"] [data-testid="board-members"]').text()).toContain('Not checked yet')
    expect(w.find('[data-name="fresh"] [data-testid="board-members"]').text()).not.toMatch(/\b0\b/)
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('a registry whose latest read failed keeps its last figures and says when they were read', async () => {
    h.board.mockResolvedValue({ registriesTotal: 1, lastCycleAt: null, registries: [row('sbx-alpha', M({ state: 'unreadable', error: 'timeout' }))] })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.find('[data-testid="board-members"]').attributes('data-kind')).toBe('stale')
    expect(w.find('[data-testid="board-members-stale"]').text()).toContain('last read failed')
  })

  it('an index older than the figures: the registries are listed, the figures "not read by this index", and the page says why', async () => {
    h.board.mockResolvedValue({ registriesTotal: 1, lastCycleAt: null, figures: 'unsupported', dropped: ['membership', 'commons'],
      registries: [row('sbx-alpha', null, null)] })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.attributes('data-state')).toBe('ready')
    expect(w.find('[data-testid="board-unsupported"]').exists()).toBe(true)
    expect(w.find('[data-testid="board-members"]').text()).toContain('Not read by this index')
    expect(w.find('[data-testid="board-members"]').text()).not.toContain('Not checked yet')
  })

  it('control: a current index with an unchecked registry says "not checked yet" and carries no note', async () => {
    h.board.mockResolvedValue({ registriesTotal: 1, lastCycleAt: null, figures: 'supported', dropped: [], registries: [row('fresh', null, null)] })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.find('[data-testid="board-unsupported"]').exists()).toBe(false)
    expect(w.find('[data-testid="board-members"]').text()).toContain('Not checked yet')
  })

  it('counts the cancelled seasons the index left out, and never says "no season yet" when there were some', async () => {
    const SEASON = { id: 4, title: 'Autumn', status: 'open', budget: '100', paidTotal: '0', submissions: 0, ballots: 0,
      opensAt: null, endsAt: null, closedAt: null, paidAt: null, cancelledAt: null }
    h.board.mockResolvedValue({ registriesTotal: 3, lastCycleAt: null, registries: [
      row('running', M(), { state: 'ok', currency: 'SBXA', seasons: [SEASON], cancelledRecent: 2, readAt: 1, checkedAt: 1, error: null }),
      row('only-cancelled', M(), { state: 'ok', currency: 'SBXA', seasons: [], cancelledRecent: 5, readAt: 1, checkedAt: 1, error: null }),
      row('none', M(), { state: 'ok', currency: 'SBXA', seasons: [], cancelledRecent: 0, readAt: 1, checkedAt: 1, error: null }),
    ] })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.find('[data-name="running"] [data-testid="board-commons-cancelled"]').text()).toContain('2')
    const only = w.find('[data-name="only-cancelled"] [data-testid="board-commons"]')
    expect(only.text()).toContain('No season apart from cancelled ones.')
    expect(only.text()).not.toContain('No season yet')
    expect(only.find('[data-testid="board-commons-cancelled"]').text()).toContain('5')
    const none = w.find('[data-name="none"] [data-testid="board-commons"]')
    expect(none.text()).toContain('No season yet.')
    expect(none.find('[data-testid="board-commons-cancelled"]').exists()).toBe(false)
  })

  it('reorders by the chosen key', async () => {
    h.board.mockResolvedValue({ registriesTotal: 2, lastCycleAt: null, registries: [
      row('big', M({ members: 9, joined30d: 0, left30d: 3 })), row('growing', M({ members: 2, joined30d: 4, left30d: 0 })),
    ] })
    const w = mount(RegistryBoard); await flushPromises()
    expect(w.findAll('[data-testid="board-row"]').map((r) => r.attributes('data-name'))).toEqual(['big', 'growing'])
    await w.find('[data-testid="board-sort"]').setValue('flow')
    expect(w.findAll('[data-testid="board-row"]').map((r) => r.attributes('data-name'))).toEqual(['growing', 'big'])
  })
})
