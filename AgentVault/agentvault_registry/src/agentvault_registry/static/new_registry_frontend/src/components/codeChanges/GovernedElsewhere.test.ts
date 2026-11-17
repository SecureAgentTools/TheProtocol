// V0666: the banner says the sentence and links to the governing registry's console (only a safe URL); it offers no Submit.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import GovernedElsewhere from './GovernedElsewhere.vue'

const view = (link: string | null) => ({ readOnly: true, sentence: 'Code changes are governed on eu; open them there.', link })

describe('GovernedElsewhere', () => {
  it('shows the sentence and the link, and nothing to submit', () => {
    const w = mount(GovernedElsewhere, { props: { view: view('https://eu.theprotocol.cloud/') } })
    expect(w.get('[data-testid="cc-governed-sentence"]').text()).toBe('Code changes are governed on eu; open them there.')
    const a = w.get('[data-testid="cc-governed-link"]')
    expect(a.attributes('href')).toBe('https://eu.theprotocol.cloud/')
    expect(a.attributes('rel')).toContain('noopener')
    expect(w.findAll('button, form, input')).toHaveLength(0)
  })
  it('shows no link when the registry named none', () => {
    expect(mount(GovernedElsewhere, { props: { view: view(null) } }).find('[data-testid="cc-governed-link"]').exists()).toBe(false)
  })
  it('never links a javascript: address', () => {
    expect(mount(GovernedElsewhere, { props: { view: view('javascript:alert(1)') } }).find('[data-testid="cc-governed-link"]').exists()).toBe(false)
  })
})
