/**
 * V0667 D4: the upstream panel on a change's page. On a merged line change: the action (a signed-in decider), then the proposal and its state, then "upstream since"; on the main-line
 * change that carries a line's change upstream: where it came from, every part, with a way back to the line's change. Nowhere else: a plain change shows nothing.
 * Red before: components/codeChanges/UpstreamPanel.vue does not exist.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UpstreamPanel from './UpstreamPanel.vue'

const stubs = { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' }, Icon: true }
const mountIt = (rec: any, props: Record<string, any> = {}) => mount(UpstreamPanel, { props: { rec, signedIn: true, readOnly: false, busy: false, error: '', ...props }, global: { stubs } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const line = (over: Record<string, any> = {}) => ({ id: 'cc_line', state: 'merged', title: 'A clearer page', code_distribution: { slug: 'lyceum', title: 'Lyceum' }, line_ballot: { i_decide: true }, upstream: null, ...over })
const PROV = {
  line: { id: 'cdst_1', slug: 'lyceum', title: 'Lyceum', base_release: 'V0666', organization_name: 'Lyceum Labs' },
  line_change: { id: 'cc_line', title: 'A clearer page', merged: { at: '2026-11-16T10:00:00+00:00' } },
  ballot: { result: { status: 'PASSED', sentence: 'passed: 3 for, 0 against' } },
  reviews: [{ verdict: 'approve' }], checker: { ok: true, record: { ci: { status: 'success' }, checker_kid: 'kid-1' } },
}

describe('the upstream panel', () => {
  it('offers the action to a signed-in decider on a merged line change, and says what it does', async () => {
    const w = mountIt(line())
    expect(tid(w, 'up-propose').exists()).toBe(true)
    expect(tid(w, 'up-explain').text()).toMatch(/main code/i)
    await tid(w, 'up-propose').trigger('click')
    expect(w.emitted('propose')).toHaveLength(1)
  })

  it('offers nothing to a reader who does not decide, and nothing where code is not governed here', () => {
    expect(tid(mountIt(line({ line_ballot: { i_decide: false } })), 'up-propose').exists()).toBe(false)
    expect(tid(mountIt(line(), { readOnly: true }), 'up-propose').exists()).toBe(false)
    expect(tid(mountIt(line(), { signedIn: false }), 'up-propose').exists()).toBe(false)
  })

  it('disables the action while the call is out and shows the registry\'s own sentence where it was refused', () => {
    const w = mountIt(line(), { busy: true, error: 'a line change goes upstream once' })
    expect(tid(w, 'up-propose').attributes('disabled')).toBeDefined()
    expect(tid(w, 'up-error').text()).toBe('a line change goes upstream once')
  })

  it('says the proposal and its state, with a link to the change on the main code', () => {
    const w = mountIt(line({ upstream: { change_id: 'cc_u', state: 'proposed', since: null } }))
    expect(tid(w, 'up-propose').exists()).toBe(false)
    expect(tid(w, 'up-status').text()).toContain('Proposed upstream as cc_u')
    expect(tid(w, 'up-link').attributes('data-to')).toContain('cc_u')
  })

  it('says "upstream since" once it landed', () => {
    const w = mountIt(line({ upstream: { change_id: 'cc_u', state: 'merged', since: '2026-11-20T10:00:00+00:00' } }))
    expect(tid(w, 'up-status').text()).toContain('Upstream since cc_u')
    expect(tid(w, 'up-status').attributes('data-kind')).toBe('landed')
  })

  it('shows a carried change where it came from, all five parts, with a way back to the line\'s change', () => {
    const w = mountIt({ id: 'cc_u', state: 'proposed', upstream_of: 'cc_line', provenance: PROV })
    expect(tid(w, 'up-provenance').exists()).toBe(true)
    for (const k of ['line', 'change', 'ballot', 'reviews', 'checker']) expect(tid(w, `up-prov-${k}`).exists()).toBe(true)
    expect(tid(w, 'up-prov-ballot').text()).toContain('passed: 3 for, 0 against')
    expect(tid(w, 'up-back').attributes('data-to')).toContain('cc_line')
    expect(tid(w, 'up-propose').exists()).toBe(false)
  })

  it('shows nothing for a change that is neither', () => {
    const w = mountIt({ id: 'cc_m', state: 'proposed' })
    expect(w.find('[data-testid="up-root"]').exists()).toBe(false)
  })
})
