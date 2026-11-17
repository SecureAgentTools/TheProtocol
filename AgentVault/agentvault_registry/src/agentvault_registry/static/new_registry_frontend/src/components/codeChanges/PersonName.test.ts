import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PersonName from './PersonName.vue'

const DID = 'did:theprotocol:eu.theprotocol.cloud:0fc15206-ca13-4257-884f-656866dd1bb1'
const mountIt = (label: any, gone = false) => mount(PersonName, { props: { label, gone }, global: { stubs: { Icon: { props: ['name'], template: '<i :data-icon="name" />' } } } })

describe('a person of a code change', () => {
  it('shows the name, the whole DID as its title, and a Copy control for an agent', () => {
    const w = mountIt({ text: "Ada's builder", tail: '', full: DID })
    expect(w.find('[data-testid="pn-name"]').text()).toBe("Ada's builder")
    expect(w.attributes('title')).toBe(DID)
    expect(w.find('[data-testid="pn-copy"]').exists()).toBe(true)
    expect(w.find('[data-testid="pn-tail"]').exists()).toBe(false)
  })

  it('shows a tail when it is given one', () => {
    expect(mountIt({ text: 'Builder', tail: '…dd1bb1', full: DID }).find('[data-testid="pn-tail"]').text()).toBe('…dd1bb1')
  })

  it('a member has no DID: no title, no Copy control', () => {
    const w = mountIt({ text: 'Grace', tail: '', full: null })
    expect(w.attributes('title')).toBeUndefined()
    expect(w.find('[data-testid="pn-copy"]').exists()).toBe(false)
  })

  it('copies the WHOLE DID, says copied, and goes back', async () => {
    vi.useFakeTimers()
    const write = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    const w = mountIt({ text: "Ada's builder", tail: '', full: DID })
    await w.find('[data-testid="pn-copy"]').trigger('click'); await flushPromises()
    expect(write).toHaveBeenCalledWith(DID)
    expect(w.find('[data-icon]').attributes('data-icon')).toBe('mdi:check')
    expect(w.find('[data-testid="pn-copy"]').attributes('aria-label')).toBe('DID copied')
    vi.advanceTimersByTime(2000); await flushPromises()
    expect(w.find('[data-icon]').attributes('data-icon')).toBe('mdi:content-copy')
    vi.useRealTimers()
  })

  it('a blocked clipboard leaves the control as it was (the title still has the DID)', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('blocked')) }, configurable: true })
    const w = mountIt({ text: 'A', tail: '', full: DID })
    await w.find('[data-testid="pn-copy"]').trigger('click'); await flushPromises()
    expect(w.find('[data-icon]').attributes('data-icon')).toBe('mdi:content-copy')
  })
})
