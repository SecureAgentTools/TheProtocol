/**
 * V0666 D3 (order gwo_542285271416c653ca39af3f): a code distribution's change, live in its organization's room. The card is
 * the registry's (code.change.live: its state, the line, the signed checker, the reviews, the line's own ballot); what the
 * reader may do is read for the reader from the change itself (my_vote, i_decide, reader_may_review): a decider votes from
 * the card through their agent, confirmed (a vote is never changed) and then sees the vote cast; another developer of the
 * organization reviews from the card; anyone else sees the record. A refusal is the registry's sentence. The card is
 * rendered through OurStateCard (the chat's card component), as every card is. Red before D3: the card is "Unsupported".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: null as any, vote: null as any, review: null as any, auth: null as any }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')),
  getChange: (...a: any[]) => h.get(...a), reviewChange: (...a: any[]) => h.review(...a) }))
vi.mock('@/services/api/codeDistributions', () => ({ voteLineChange: (...a: any[]) => h.vote(...a) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import OurStateCard from './OurStateCard.vue'
import { cardView } from '@/services/chat/cards'

const SHA = 'a'.repeat(40)
const card = (state = 'balloting', extra: Record<string, unknown> = {}) => ({ v: 1, type: 'code.change.live', refs: { code_change_id: 'cc_1' },
  data: { change_id: 'cc_1', title: 'A seating chart', state, sensitive: false,
    line: { slug: 'lyceum', title: "Lyceum's line", release_name: 'V0666_lyceum', organization_name: 'Lyceum Labs', paused: false },
    checker: { state: 'ok', reasons: [] }, reviews: { count: 1, approvals: 1, needed: 1, blockers: 0 },
    ballot: { votes: 1, deciders: 3, ends: '2026-11-17T09:30:00Z', result: null, sentence: null, note: null }, ...extra } })
const reader = (over: Record<string, unknown> = {}) => ({ id: 'cc_1', commit: SHA, state: 'balloting', reader_may_review: false,
  line_ballot: { my_vote: null, i_decide: true, votes: 1, deciders_now: 3 }, ...over })
const opts = { global: { stubs: { Icon: true, OurStateIdentity: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } }
const mountCard = (c: any, rev = 0) => mount(OurStateCard, { props: { card: c, rev } as any, ...opts })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the change card in a room', () => {
  beforeEach(() => {
    h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    h.get = vi.fn().mockResolvedValue(reader()); h.vote = vi.fn(); h.review = vi.fn()
  })

  it('is read as a card of its own, never as an unsupported one', () => {
    const v: any = cardView(card() as any)
    expect(v.type).toBe('code.change.live')
    expect(v).toMatchObject({ changeId: 'cc_1', title: 'A seating chart', state: 'balloting',
      line: { releaseName: 'V0666_lyceum', organizationName: 'Lyceum Labs', paused: false },
      checker: { state: 'ok' }, reviews: { approvals: 1, needed: 1 }, ballot: { votes: 1, deciders: 3 } })
  })

  it('shows the record: the state for a line, the line and its organization, the checker, the reviews, the ballot, and the door to the change', async () => {
    const w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-cc-live').attributes('data-state')).toBe('balloting')
    expect(tid(w, 'osc-cc-state').text()).toBe('Deciders voting')
    expect(tid(w, 'osc-cc-line').text()).toContain('V0666_lyceum')
    expect(tid(w, 'osc-cc-line').text()).toContain('Lyceum Labs')
    expect(tid(w, 'osc-cc-checker').text()).toBe('The signed checks passed for this commit.')
    expect(tid(w, 'osc-cc-reviews').text()).toBe('1 of 1 approving reviews')
    expect(tid(w, 'osc-cc-ballot').text()).toMatch(/1 of 3 deciders voted/)
    expect(JSON.parse(tid(w, 'osc-cc-open').attributes('data-to')!)).toEqual({ name: 'code-change', params: { id: 'cc_1' } })
    expect(h.get).toHaveBeenCalledWith('cc_1')
    expect(w.find('[data-testid="osc-unknown"]').exists()).toBe(false)
  })

  it('lets a decider vote from the card, confirmed, then says the vote cast', async () => {
    h.vote = vi.fn().mockResolvedValue(reader({ line_ballot: { my_vote: 'FOR', i_decide: true } }))
    const w = mountCard(card()); await flushPromises()
    await tid(w, 'osc-cc-vote-for').trigger('click')
    expect(h.vote).not.toHaveBeenCalled()
    expect(tid(w, 'osc-cc-vote-confirm-text').text()).toMatch(/never changed/)
    await tid(w, 'osc-cc-vote-confirm').trigger('click'); await flushPromises()
    expect(h.vote).toHaveBeenCalledWith('cc_1', true)
    expect(tid(w, 'osc-cc-voted').text()).toMatch(/Your vote for this change is in/)
    expect(tid(w, 'osc-cc-vote-for').exists()).toBe(false)
  })

  it('shows the vote already cast, from the change, and no buttons', async () => {
    h.get = vi.fn().mockResolvedValue(reader({ line_ballot: { my_vote: 'AGAINST', i_decide: true } }))
    const w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-cc-voted').text()).toMatch(/Your vote against this change is in/)
    expect(tid(w, 'osc-cc-vote-for').exists()).toBe(false)
  })

  it('shows a refused vote in the registry\'s words', async () => {
    h.vote = vi.fn().mockRejectedValue({ response: { data: { code: 'not_a_decider', detail: 'only the line\'s deciders vote' } } })
    const w = mountCard(card()); await flushPromises()
    await tid(w, 'osc-cc-vote-against').trigger('click'); await tid(w, 'osc-cc-vote-confirm').trigger('click'); await flushPromises()
    expect(tid(w, 'osc-cc-refusal').text()).toBe('only the line\'s deciders vote')
    expect(tid(w, 'osc-cc-voted').exists()).toBe(false)
  })

  it('offers no vote to a reader who does not decide, and asks for an agent when none is chosen', async () => {
    h.get = vi.fn().mockResolvedValue(reader({ line_ballot: { my_vote: null, i_decide: false } }))
    let w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-cc-vote').exists()).toBe(false)
    h.get = vi.fn().mockResolvedValue(reader())
    h.auth = { isAuthenticated: true, activeAgent: null }
    w = mountCard(card()); await flushPromises()
    expect(tid(w, 'osc-cc-vote-agent').text()).toMatch(/Choose one of your agents/)
  })

  it('lets another developer of the organization review the accepted commit from the card', async () => {
    h.get = vi.fn().mockResolvedValue(reader({ state: 'accepted', reader_may_review: true, line_ballot: { my_vote: null, i_decide: false } }))
    h.review = vi.fn().mockResolvedValue(reader({ state: 'accepted', reader_may_review: true }))
    const w = mountCard(card('accepted')); await flushPromises()
    await tid(w, 'osc-cc-review-open').trigger('click')
    await tid(w, 'osc-cc-review-findings').setValue('Read the diff: the chart follows the seats.')
    await tid(w, 'osc-cc-review-approve').trigger('click'); await flushPromises()
    expect(h.review).toHaveBeenCalledWith('cc_1', { verdict: 'approve', commit: SHA, findings: 'Read the diff: the chart follows the seats.' })
    expect(tid(w, 'osc-cc-reviewed').text()).toMatch(/Your review is in/)
  })

  it('offers no review to a reader who may not review, and reads the reader again when the card moves', async () => {
    const w = mountCard(card('accepted')); await flushPromises()
    expect(tid(w, 'osc-cc-review-open').exists()).toBe(false)
    await w.setProps({ card: card('balloting'), rev: 1 } as any); await flushPromises()
    expect(h.get).toHaveBeenCalledTimes(2)
  })

  it('says a failed check, a closed ballot in its own words, and a paused line', async () => {
    const w = mountCard(card('failed', { checker: { state: 'failed', reasons: ['CI is not green'] },
      ballot: { votes: 1, deciders: 3, result: 'FAILED', sentence: '1 of 3 deciders voted, below the quorum of 50 percent' },
      line: { slug: 'lyceum', release_name: 'V0666_lyceum', organization_name: 'Lyceum Labs', paused: true } }))
    await flushPromises()
    expect(tid(w, 'osc-cc-state').text()).toBe('Did not pass')
    expect(tid(w, 'osc-cc-checker').text()).toBe('The signed checks did not pass: CI is not green')
    expect(tid(w, 'osc-cc-ballot').text()).toBe('Failed: 1 of 3 deciders voted, below the quorum of 50 percent')
    expect(tid(w, 'osc-cc-paused').exists()).toBe(true)
  })
})
