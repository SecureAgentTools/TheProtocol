/**
 * V0667 D5b (order gwo_efd89f2041bfda1eeb7e2cda): an organization's content change, live in its room. The card is the registry's (content.change.live: its kind, state, the line, our checker, the line's ballot);
 * what the reader may do is read for the reader from the change itself (ballot.can_vote, ballot.my_vote): a decider votes from the card through their agent, confirmed (a vote is never changed) and then sees
 * the vote cast; anyone else sees the record. A refusal is the registry's sentence. The card is rendered through OurStateCard, as every card is. Red before D5b: the card is "Unsupported".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: null as any, vote: null as any, auth: null as any }))
vi.mock('@/services/api/contentChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/contentChanges')),
  getContentChange: (...a: any[]) => h.get(...a), voteContentChange: (...a: any[]) => h.vote(...a) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import OurStateCard from './OurStateCard.vue'
import { cardView } from '@/services/chat/cards'

const card = (state = 'balloting', extra: Record<string, unknown> = {}) => ({ v: 1, type: 'content.change.live', refs: { content_change_id: 'ct_1' },
  data: { change_id: 'ct_1', kind: 'console_text', title: 'A tagline', state, applied: state === 'applied',
    line: { slug: 'lyceum', title: "Lyceum's line", release_name: 'V0666_lyceum', organization_name: 'Lyceum Labs', paused: false },
    checker: { state: 'ok', rules: ['schema', 'secrets'] },
    ballot: { votes: 1, deciders: 3, ends: '2026-11-17T09:30:00Z', result: null, sentence: null }, ...extra } })
const reader = (ballot: Record<string, unknown> = {}) => ({ id: 'ct_1', state: 'balloting', ballot: { can_vote: true, my_vote: null, ...ballot } })
const opts = { global: { stubs: { Icon: true, OurStateIdentity: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } }
const mountCard = (c: any, rev = 0) => mount(OurStateCard, { props: { card: c, rev } as any, ...opts })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the content change card in a room', () => {
  beforeEach(() => {
    h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    h.get = vi.fn().mockResolvedValue(reader()); h.vote = vi.fn()
  })

  it('is read as a card of its own, never as an unsupported one', () => {
    const v: any = cardView(card() as any)
    expect(v.type).toBe('content.change.live')
    expect(v).toMatchObject({ changeId: 'ct_1', kind: 'console_text', title: 'A tagline', state: 'balloting', applied: false })
    expect(v.line).toEqual({ slug: 'lyceum', title: "Lyceum's line", releaseName: 'V0666_lyceum', organizationName: 'Lyceum Labs', paused: false })
    expect(v.checker).toEqual({ state: 'ok', rules: ['schema', 'secrets'] })
  })

  it('shows the kind, the state, the line with its organization, our checker and the ballot', async () => {
    const w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-ct-live').exists()).toBe(true)
    expect(w.text()).toContain('Console text'); expect(tid(w, 'osc-ct-state').text()).toBe('In its ballot'); expect(w.text()).toContain('A tagline')
    expect(tid(w, 'osc-ct-line').text()).toContain('V0666_lyceum'); expect(tid(w, 'osc-ct-line').text()).toContain('Lyceum Labs')
    expect(tid(w, 'osc-ct-checker').text()).toBe('Our checker passed it: schema, secrets.')
    expect(tid(w, 'osc-ct-ballot').text()).toContain('1 of 3 deciders voted')
  })

  it('offers the vote to a decider, confirms it, and shows it cast', async () => {
    h.vote.mockResolvedValue(reader({ can_vote: false, my_vote: 'FOR' }))
    const w = mountCard(card()); await flushPromises()
    await tid(w, 'osc-ct-vote-for').trigger('click')
    await tid(w, 'osc-ct-vote-confirm').trigger('click'); await flushPromises()
    expect(h.vote).toHaveBeenCalledWith('ct_1', true)
    expect(tid(w, 'osc-ct-voted').exists()).toBe(true); expect(tid(w, 'osc-ct-vote').exists()).toBe(false)
  })

  it('offers nothing to a reader who does not decide, or who has voted, or on a closed ballot', async () => {
    h.get.mockResolvedValue(reader({ can_vote: false }))
    expect(tid(mountCard(card()), 'osc-ct-vote').exists()).toBe(false)
    h.get.mockResolvedValue(reader({ can_vote: false, my_vote: 'AGAINST' }))
    const w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-ct-voted').exists()).toBe(true)
    h.get.mockResolvedValue(reader())
    const closed = mountCard(card('applied', { ballot: { votes: 3, deciders: 3, ends: null, result: 'PASSED', sentence: '3 for, 0 against, of 3 deciders: passed' } })); await flushPromises()
    expect(tid(closed, 'osc-ct-vote').exists()).toBe(false); expect(tid(closed, 'osc-ct-ballot').text()).toBe('Passed: 3 for, 0 against, of 3 deciders: passed')
    expect(tid(closed, 'osc-ct-state').text()).toBe('Applied')
  })

  it('asks for an agent first, and offers no vote at all on a paused line', async () => {
    h.auth = { isAuthenticated: true, activeAgent: null }
    const w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-ct-vote-agent').exists()).toBe(true); expect(tid(w, 'osc-ct-vote-for').exists()).toBe(false)
    h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    const paused = mountCard(card('balloting', { line: { slug: 'lyceum', title: 'x', release_name: 'V0666_lyceum', organization_name: 'L', paused: true } })); await flushPromises()
    expect(tid(paused, 'osc-ct-paused').exists()).toBe(true); expect(tid(paused, 'osc-ct-vote').exists()).toBe(false)
  })

  it('shows the registry\'s sentence when it refuses the vote', async () => {
    h.vote.mockRejectedValue({ response: { data: { code: 'not_a_decider', detail: 'only the line\'s deciders vote' } } })
    const w = mountCard(card()); await flushPromises()
    await tid(w, 'osc-ct-vote-for').trigger('click'); await tid(w, 'osc-ct-vote-confirm').trigger('click'); await flushPromises()
    expect(tid(w, 'osc-ct-refusal').text()).toContain('only the line')
  })

  it('reads its own acts again when the card moves, and links to the line under Contributions', async () => {
    const w = mountCard(card(), 0); await flushPromises()
    expect(h.get).toHaveBeenCalledTimes(1)
    await w.setProps({ rev: 1 } as any); await flushPromises()
    expect(h.get).toHaveBeenCalledTimes(2)
    expect(JSON.parse(tid(w, 'osc-ct-open').attributes('data-to')!)).toEqual({ name: 'contributions', query: { line: 'lyceum' } })
  })
})
