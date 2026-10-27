import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ReadFailedNotice from './ReadFailedNotice.vue'

/**
 * §FESUITE (2026-10-04) — where a page's read failed it says so, never "none": the notice speaks to a screen reader, says
 * the read failed in the page's words or its own, and offers the read again only when the page gives one.
 */
describe('the read-failed notice', () => {
  it('says the read failed, as an alert, with no retry unless the page gives one', () => {
    const w = mount(ReadFailedNotice)
    const n = w.find('[data-testid="read-failed"]')
    expect(n.attributes('role')).toBe('alert')
    expect(n.text()).toContain('could not be read')
    expect(n.text()).not.toMatch(/\bno\b|\bnone\b|nothing/i)
    expect(w.find('[data-testid="read-failed-retry"]').exists()).toBe(false)
  })

  it('carries the page\'s own sentence when it names what could not be read', () => {
    const w = mount(ReadFailedNotice, { props: { text: 'The markets could not be read just now.' } })
    expect(w.text()).toContain('The markets could not be read just now.')
  })

  it('stays countable when its page gives it a name of its own', () => {
    // a caller's data-testid replaces the component's (attribute fallthrough); data-read-failed is never passed by one
    const named = mount(ReadFailedNotice, { attrs: { 'data-testid': 'ap-metrics-failed' } })
    expect(named.find('[data-testid="read-failed"]').exists()).toBe(false)
    expect(named.find('[data-testid="ap-metrics-failed"]').exists()).toBe(true)
    expect(named.find('[data-read-failed]').exists()).toBe(true)
    expect(mount(ReadFailedNotice).find('[data-testid="read-failed"][data-read-failed]').exists()).toBe(true)
  })

  it('reads again when asked, and a retry that fails is the page\'s to report', async () => {
    const retry = vi.fn().mockRejectedValue(new Error('502'))
    const w = mount(ReadFailedNotice, { props: { retry } })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    expect(retry).toHaveBeenCalledTimes(1)
  })
})
