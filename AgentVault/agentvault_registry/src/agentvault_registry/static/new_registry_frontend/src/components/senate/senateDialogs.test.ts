/**
 * §COCKPITDESK (2026-10-15) — the Senate's dialogs say they are dialogs and close on Escape. agentvault2-5b's scoped run of
 * lifecycle 99 on V0616 found "Create a proposal" opening as no dialog at all (no role, no aria-modal, no name) and deaf to
 * Escape; Stake, Unstake and Vote were built the same way. Each now carries role="dialog" aria-modal="true" named by its
 * title, and Escape closes it wherever the focus is, never while it submits.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU') }) }
})

import CreateProposalModal from './CreateProposalModal.vue'
import StakeModal from './StakeModal.vue'
import UnstakeModal from './UnstakeModal.vue'
import VoteModal from './VoteModal.vue'

const CASES: Array<[string, any, Record<string, unknown>]> = [
  ['Create a proposal', CreateProposalModal, {}],
  ['Stake', StakeModal, { tegBalance: '10', tiers: [] }],
  ['Unstake', UnstakeModal, { position: { id: 'p1', amount: '5', lockPeriod: 0, apy: 0 } }],
  ['Vote', VoteModal, { votingPower: '1', proposal: { title: 'A proposal' } }],
]
const esc = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
let w: ReturnType<typeof mount> | null = null
afterEach(() => { w?.unmount(); w = null; document.body.innerHTML = '' })

describe("the Senate's dialogs", () => {
  for (const [name, comp, props] of CASES) {
    it(`${name}: a modal dialog named by its title; Escape closes it`, () => {
      setActivePinia(createPinia())
      w = mount(comp, { props: { show: true, loading: false, ...props }, attachTo: document.body, global: { stubs: { Icon: true } } })
      const dlg = document.querySelector('[role="dialog"][aria-modal="true"]')
      expect(dlg, 'a dialog is open').not.toBeNull()
      const label = document.getElementById(dlg!.getAttribute('aria-labelledby') || '')
      expect(label?.textContent?.trim(), 'its name is its title').toBeTruthy()
      expect(document.querySelector('.tp-modal-close')?.getAttribute('aria-label'), 'the close button is named').toBe('Close')
      esc()
      const shown = w.emitted('update:show') ?? []
      expect(shown[shown.length - 1]).toEqual([false])
    })
    it(`${name}: Escape does nothing while it submits`, () => {
      setActivePinia(createPinia())
      w = mount(comp, { props: { show: true, loading: true, ...props }, attachTo: document.body, global: { stubs: { Icon: true } } })
      esc()
      expect(w.emitted('update:show')).toBeUndefined()
    })
  }
})
