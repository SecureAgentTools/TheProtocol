/**
 * §FESUITE V0595: the switch board on an operator application (his word 2026-10-11: "the env flips that are frame
 * exclusive should be still displayed for operators but greyed out and not chooseable"). A locked setting shows the
 * frame's value with its buttons disabled and the reason beside it, and never emits a change; "changed" counts against
 * the frame's own settings there. The frame request's board (no locks, no baseline) counts against the defaults, as before.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FcSwitchBoard from './FcSwitchBoard.vue'
import { FRAME_FEATURE_SWITCHES } from '@/services/api/frameRequests'

const defaults = Object.fromEntries(FRAME_FEATURE_SWITCHES.map(sw => [sw.key, sw.def]))

describe('the switch board with locked settings', () => {
  it("shows a frame-scope setting greyed with the frame's value and its reason, and never emits a change for it", async () => {
    const baseline = { ...defaults, staking: 'no' }
    const w = mount(FcSwitchBoard, {
      props: { features: { ...baseline }, baseline, locked: { staking: { value: 'no', reason: "Money policy is the frame's." } } },
      global: { stubs: { Icon: true } },
    })
    const yes = w.find('[data-testid="fc-feature-staking-yes"]')
    expect(yes.exists(), 'the economy group opens first and lists staking').toBe(true)
    expect(yes.attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="fc-feature-staking-no"]').classes()).toContain('is-on')
    expect(w.find('[data-testid="fc-feature-staking-locked"]').text()).toContain("Money policy is the frame's.")
    await yes.trigger('click')
    expect(w.emitted('change'), 'a locked setting emitted a change').toBeUndefined()
    expect(w.find('[data-testid="fc-switch-count"]').text()).toContain('Every setting as the frame runs it')
  })

  it("counts what differs from the frame's settings, and offers the way back to them", async () => {
    const baseline = { ...defaults, guild: 'yes' }
    const w = mount(FcSwitchBoard, { props: { features: { ...baseline, guild: 'no' }, baseline }, global: { stubs: { Icon: true } } })
    expect(w.find('[data-testid="fc-switch-count"]').text()).toContain("One setting differs from the frame's")
    expect(w.find('[data-testid="fc-switch-reset"]').text()).toContain("Back to the frame's settings")
    await w.find('[data-testid="fc-feature-guild-yes"]').trigger('click')
    expect(w.emitted('change')?.[0]).toEqual(['guild', 'yes'])
  })

  it('the frame request board, unlocked, counts against the defaults as before', () => {
    const w = mount(FcSwitchBoard, { props: { features: { ...defaults } }, global: { stubs: { Icon: true } } })
    expect(w.find('[data-testid="fc-switch-count"]').text()).toContain('Every setting at its default')
    expect(w.find('[data-testid="fc-switch-reset"]').text()).toContain('Reset to defaults')
    expect(w.findAll('[data-testid$="-locked"]').length).toBe(0)
  })
})
