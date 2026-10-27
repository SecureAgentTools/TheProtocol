import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * Quick onboarding (2026-10-09): the step-up dialog says what its caller asks a person to confirm.
 *
 * StepUpConfirm was written for a member's vote and said "Confirm your vote" (and "Votes on this registry are confirmed
 * by a person", "Nothing was cast") over every challenge. An agent's credential reset asks for the same second factor,
 * through the same challenge, so the dialog takes an optional title, lead and the two endings. Without them it is the
 * vote's dialog, unchanged.
 */
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/services/api/liability', () => ({ liabilityApi: { pendingChallenges: vi.fn().mockResolvedValue({ challenges: [] }) } }))

import StepUpConfirm from './StepUpConfirm.vue'

function challenge(expiresInMs: number) {
  return {
    reason: 'second factor required', challengeId: 'lch_test', challengeHash: 'h',
    facts: { action: 'Reset agent credentials', agent_did: 'did:theprotocol:a' },
    expiresAt: new Date(Date.now() + expiresInMs).toISOString(), ttlSeconds: 120, methods: ['device', 'totp'], how: null,
  }
}

function mountIt(props: Record<string, unknown>) {
  return mount(StepUpConfirm, { props: { show: true, challenge: null, ...props } as any, global: { stubs: { teleport: true, Icon: true } } })
}

describe('StepUpConfirm names the action it confirms', () => {
  it('a title and a lead from the caller replace the vote\'s words', () => {
    const w = mountIt({ challenge: challenge(60_000), title: 'Confirm this reset', lead: 'A credential reset is confirmed by a person.' })
    expect(w.find('[data-testid="stepup-confirm"]').attributes('aria-label')).toBe('Confirm this reset')
    expect(w.text()).toContain('Confirm this reset')
    expect(w.text()).toContain('A credential reset is confirmed by a person.')
    expect(w.text()).not.toMatch(/vote/i)
    w.unmount()
  })

  it('an expired challenge says the caller\'s ending', () => {
    const w = mountIt({ challenge: challenge(-1_000), title: 'Confirm this reset', expiredText: 'This confirmation expired. Reset again to get a new one.' })
    expect(w.find('[data-testid="stepup-expired"]').text()).toBe('This confirmation expired. Reset again to get a new one.')
    w.unmount()
  })

  it('control: without them it is still the vote\'s dialog', () => {
    const w = mountIt({ challenge: challenge(60_000) })
    expect(w.find('[data-testid="stepup-confirm"]').attributes('aria-label')).toBe('Confirm your vote')
    expect(w.text()).toContain('Confirm your vote')
    expect(w.text()).toContain('Votes on this registry are confirmed by a person')
    w.unmount()
  })
})

/**
 * Quick onboarding (2026-10-09): the dialog is a modal in keys too. It had role="dialog" and aria-modal="true" and no
 * focus handling at all: the reset dialog stepped aside for it, focus went back to the page behind it, Tab walked the
 * page under the overlay and Esc did nothing. Now focus enters it (the code field when there is one), Tab stays inside
 * (useFocusTrap) and Esc cancels like the close button.
 */
describe('StepUpConfirm holds the keyboard while it asks', () => {
  it('focus enters the code field, and Esc cancels like the close button', async () => {
    const w = mount(StepUpConfirm, {
      attachTo: document.body,
      props: { show: true, challenge: challenge(60_000), title: 'Confirm this reset' } as any,
      global: { stubs: { teleport: true, Icon: true } },
    })
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(document.activeElement).toBe(w.find('[data-testid="stepup-code"]').element)
    await w.find('.tp-overlay').trigger('keydown', { key: 'Escape' })
    expect(w.emitted('update:show')).toEqual([[false]])
    w.unmount()
  })

  it('without a code field, focus lands on Cancel; the close control is an icon with a name, not a text glyph', async () => {
    const ch = { ...challenge(60_000), methods: ['device'] }
    const w = mount(StepUpConfirm, {
      attachTo: document.body,
      props: { show: true, challenge: ch } as any,
      global: { stubs: { teleport: true } },
    })
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(document.activeElement).toBe(w.find('[data-testid="stepup-cancel"]').element)
    const close = w.find('[data-testid="stepup-close"]')
    expect(close.attributes('aria-label')).toBe('Cancel')
    expect(close.text()).not.toContain('✕')
    expect(close.find('svg').exists()).toBe(true)
    w.unmount()
  })
})
