import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §MEMBERSHIP phase C (2026-10-02) — submitting work: the form says what is missing once the person has typed, sends
 * the evidence trimmed and without blank rows, and shows the server's refusal in the person's words.
 */
const h = vi.hoisted(() => ({ submit: vi.fn(), ui: { showSuccess: vi.fn(), showWarning: vi.fn(), showError: vi.fn() } }))
vi.mock('@/services/api/commons', () => ({ commonsApi: { submit: h.submit } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))

import CommonsSubmitForm from './CommonsSubmitForm.vue'

function mountForm() {
  return mount(CommonsSubmitForm, { props: { seasonId: 4, limit: 5 }, global: { stubs: { teleport: true } } })
}

beforeEach(() => { h.submit.mockReset(); h.ui.showSuccess.mockReset() })

describe('submitting work to a season', () => {
  it('an empty form names nothing yet, and cannot be sent', () => {
    const w = mountForm()
    expect(w.find('[data-testid="commons-submit-problem"]').exists()).toBe(false)
    expect(w.find('[data-testid="commons-submit-send"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('Up to 5 submissions per developer')
  })

  it('says what is missing once something is typed', async () => {
    const w = mountForm()
    await w.find('[data-testid="commons-submit-title"]').setValue('ab')
    expect(w.find('[data-testid="commons-submit-problem"]').text()).toContain('3 to 200 characters')
    await w.find('[data-testid="commons-submit-title"]').setValue('Translated the cookie page')
    expect(w.find('[data-testid="commons-submit-problem"]').text()).toContain('at least one piece of evidence')
    await w.find('[data-testid="commons-ev-url-0"]').setValue('http://not-https.test')
    await w.find('[data-testid="commons-ev-ref-0"]').setValue('cookie page')
    expect(w.find('[data-testid="commons-submit-problem"]').text()).toContain('https://')
  })

  it('sends trimmed evidence without blank rows, and hands the new submission up', async () => {
    h.submit.mockResolvedValue({ kind: 'submitted', submission: { id: 9, seasonId: 4, kind: 'translation', title: 'Translated', status: 'submitted', submitterDid: 'did:a' } })
    const w = mountForm()
    await w.find('[data-testid="commons-submit-kind"]').setValue('translation')
    await w.find('[data-testid="commons-submit-title"]').setValue('  Translated  ')
    await w.find('[data-testid="commons-ev-ref-0"]').setValue(' abc123 ')
    await w.find('[data-testid="commons-ev-add"]').trigger('click')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(h.submit).toHaveBeenCalledWith(4, { kind: 'translation', title: 'Translated', description: '', evidence: [{ type: 'url', ref: 'abc123' }] })
    expect(w.emitted('submitted')?.[0]?.[0]).toMatchObject({ id: 9 })
    expect(h.ui.showSuccess).toHaveBeenCalled()
  })

  it('a refusal stays in the form, in the person\'s words', async () => {
    h.submit.mockResolvedValue({ kind: 'refused', status: 429, error: 'too_many_submissions', message: 'too_many_submissions: ...', submissionIds: [] })
    const w = mountForm()
    await w.find('[data-testid="commons-submit-title"]').setValue('Another one')
    await w.find('[data-testid="commons-ev-ref-0"]').setValue('ticket 12')
    await w.find('form').trigger('submit'); await flushPromises()
    expect(w.find('[data-testid="commons-submit-error"]').text()).toContain('reached the number of submissions')
    expect(w.emitted('submitted')).toBeUndefined()
  })
})
