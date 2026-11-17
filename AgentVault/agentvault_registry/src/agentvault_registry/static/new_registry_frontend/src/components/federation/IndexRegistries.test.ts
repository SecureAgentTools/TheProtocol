/**
 * V0663, the Directory read path, step 3 (order gwo_0936844934f713153ede256c): the Federation Peers page lists the
 * registries the federated index knows, each card verified by this registry.
 *   - a verified registry shows its name, trust domain, place and unit from its own signed card, a "verified by this
 *     registry" mark and what it is to this registry (this registry, peer, known, candidate);
 *   - a candidate is only a candidate: an admin with the federation flag is pointed to the invitation rail, nobody else;
 *   - a row that did not verify shows the index's name, marked, with the reason;
 *   - where the index and the card name different addresses, both are shown;
 *   - an index that could not be read says so with its reason and a retry, never an empty list; an older index and a
 *     cut answer are named; a registry with no index shows nothing.
 * Red on 1fe82c44c: the component does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))

import IndexRegistries from './IndexRegistries.vue'

const URL = '/public/directory/registries'
const reg = (name: string, relation: string, extra: Record<string, any> = {}) => ({
  name, trust_domain: `${name}.theprotocol.cloud`, tier: 'sovereign-mainframe', public_url: `https://${name}.example.org`,
  location: 'Brussels', currency: 'ECU', card_etag: 'e1', verified: true, reason: 'ok', relation, address_agrees: true,
  index: { name, public_url: `https://${name}.example.org`, trust_domain: null, reachable: true, verified: true,
           card_epoch: 'e1', last_sync_at: 1 }, ...extra })
const bad = (name: string, reason: string) => ({
  name: null, trust_domain: null, tier: null, public_url: null, location: null, currency: null, card_etag: null,
  verified: false, reason, relation: 'unverified', address_agrees: null,
  index: { name, public_url: `https://${name}.example.org`, trust_domain: null, reachable: true, verified: false,
           card_epoch: null, last_sync_at: null } })

function answer(status: number, data: any) {
  h.get.mockImplementation(async (url: string) => {
    if (url !== URL) throw new Error(`unexpected read ${url}`)
    return { status, data }
  })
}

async function view(props: Record<string, any> = {}) {
  const w = mount(IndexRegistries, { props, global: { stubs: { RouterLink: { template: '<a data-testid="ixr-invite"><slot /></a>' } } } })
  await flushPromises()
  return w
}

const OK = { configured: true, index_serves_cards: true, truncated: false, counts: { index: 3, read: 3, verified: 2, unverified: 1 },
  registries: [reg('eu', 'peer'), reg('lisbon', 'candidate'), bad('ghost', 'signature invalid')] }

describe('the registries the index knows, on the Federation Peers page', () => {
  beforeEach(() => { h.get.mockReset() })   // braces: a returned function would run as a cleanup hook

  it('lists each verified registry from its own card, with the mark and what it is to this registry', async () => {
    answer(200, OK)
    const w = await view()
    const eu = w.find('[data-testid="ixr-row-eu"]')
    expect(eu.exists()).toBe(true)
    expect(eu.text()).toContain('eu.theprotocol.cloud')
    expect(eu.text()).toContain('Brussels')
    expect(eu.find('[data-testid="ixr-verified"]').exists()).toBe(true)
    expect(eu.find('[data-testid="ixr-relation"]').attributes('data-relation')).toBe('peer')
    expect(w.find('[data-testid="ixr-summary"]').text()).toMatch(/2\D+3/)
  })

  it('a row that did not verify shows the index name, marked, with the reason', async () => {
    answer(200, OK)
    const w = await view()
    const g = w.find('[data-testid="ixr-row-unverified-ghost"]')
    expect(g.exists()).toBe(true)
    expect(g.text()).toContain('ghost')
    expect(g.text()).toContain('signature invalid')
    expect(g.find('[data-testid="ixr-verified"]').exists()).toBe(false)
  })

  it('points an admin with the federation flag to the invitation rail for a candidate, and nobody else', async () => {
    answer(200, OK)
    const admin = await view({ canInvite: true })
    expect(admin.find('[data-testid="ixr-row-lisbon"] [data-testid="ixr-invite"]').exists()).toBe(true)
    expect(admin.find('[data-testid="ixr-row-eu"] [data-testid="ixr-invite"]').exists()).toBe(false)
    const member = await view({ canInvite: false })
    expect(member.find('[data-testid="ixr-invite"]').exists()).toBe(false)
  })

  it('names both addresses where the index and the card disagree', async () => {
    answer(200, { ...OK, registries: [reg('eu', 'peer', { address_agrees: false,
      index: { ...reg('eu', 'peer').index, public_url: 'https://elsewhere.example.org' } })] })
    const w = await view()
    const note = w.find('[data-testid="ixr-row-eu"] [data-testid="ixr-address"]')
    expect(note.text()).toContain('https://elsewhere.example.org')
    expect(note.text()).toContain('https://eu.example.org')
  })

  it('an index that could not be read says so, with its reason and a retry, never an empty list', async () => {
    answer(502, { configured: true, error: 'the federated index is unreachable' })
    const w = await view()
    expect(w.find('[data-testid="ixr-error"]').text()).toContain('the federated index is unreachable')
    expect(w.find('[data-testid="ixr-empty"]').exists()).toBe(false)
    answer(200, OK)
    await w.find('[data-testid="ixr-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ixr-row-eu"]').exists()).toBe(true)
  })

  it('names an older index and a cut answer', async () => {
    answer(200, { ...OK, index_serves_cards: false, truncated: true, counts: { index: 900, read: 300, verified: 0, unverified: 300 } })
    const w = await view()
    expect(w.find('[data-testid="ixr-older-index"]').exists()).toBe(true)
    expect(w.find('[data-testid="ixr-truncated"]').text()).toContain('900')
  })

  it('a registry with no index shows nothing', async () => {
    answer(200, { configured: false, registries: [] })
    const w = await view()
    expect(w.find('[data-testid="ixr"]').exists()).toBe(false)
  })

  it('an index that knows no registry says that, which is not an error', async () => {
    answer(200, { configured: true, index_serves_cards: true, truncated: false, counts: { index: 0, read: 0, verified: 0, unverified: 0 }, registries: [] })
    const w = await view()
    expect(w.find('[data-testid="ixr-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="ixr-error"]').exists()).toBe(false)
  })
})

describe('the Federation Peers page mounts it', () => {
  it('with the invitation pointer only for the federation flag', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '../../views/FederationDiscovery.vue'), 'utf8')
    expect(src).toMatch(/<IndexRegistries[^>]*:can-invite="canFederation"/)
    expect(src).toContain("import IndexRegistries from '@/components/federation/IndexRegistries.vue'")
  })
})
