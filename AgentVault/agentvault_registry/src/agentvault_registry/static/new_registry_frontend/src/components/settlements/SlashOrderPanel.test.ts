/**
 * V0658 (k): the admin settlements view edits the slash order every slash on the registry drains: it reads the policy
 * section, shows the steps in order (the cascade last, off unless the order lists it), and saves the order the admin
 * set through PUT /admin/enforcement/policy/section/slash_waterfall with a reason, only once the order is one the
 * registry would take. A refusal is shown in the registry's words.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('@/services/api/enforcementAdmin', () => ({
  enforcementAdmin: { getSlashOrder: vi.fn(), updateSlashOrder: vi.fn() },
}))

import { enforcementAdmin } from '@/services/api/enforcementAdmin'
import SlashOrderPanel from './SlashOrderPanel.vue'

const factory = [{ source: 'bond', max_percent: 100 }, { source: 'stake', max_percent: 100 },
  { source: 'liquid', max_percent: 100 }]
const api = enforcementAdmin as unknown as { getSlashOrder: ReturnType<typeof vi.fn>; updateSlashOrder: ReturnType<typeof vi.fn> }

async function panel() {
  const w = mount(SlashOrderPanel, {
    global: { stubs: { ConfirmActionModal: { props: ['show'], emits: ['confirm', 'close'], template: '<div v-if="show" data-testid="confirm"><button data-testid="confirm-go" @click="$emit(\'confirm\', \'the cascade, as decided\')" /></div>' } } },
  })
  await flushPromises()
  return w
}

describe('the slash order panel', () => {
  beforeEach(() => {
    api.getSlashOrder.mockReset()
    api.updateSlashOrder.mockReset()
    api.getSlashOrder.mockResolvedValue({ section: 'slash_waterfall', value: null, default: factory, version: 0, source: 'default' })
  })

  it('reads the factory order: the three own steps, then the cascade, off', async () => {
    const w = await panel()
    const steps = w.findAll('[data-testid^="slash-order-step-"]').map((s) => s.attributes('data-testid'))
    expect(steps).toEqual(['slash-order-step-bond', 'slash-order-step-stake', 'slash-order-step-liquid', 'slash-order-step-cascade'])
    expect((w.find('[data-testid="slash-order-on-cascade"]').element as HTMLInputElement).checked).toBe(false)
    expect(w.find('[data-testid="slash-order-source"]').text()).toBe('The factory order')
    expect(w.text()).toContain('Locked units')
    expect(w.text(), 'the console says locked units, never the old word').not.toMatch(/\bstak/i)
    expect((w.find('[data-testid="slash-order-save"]').element as HTMLButtonElement).disabled, 'nothing changed').toBe(true)
  })

  it('saves the cascade switched on, with the reason the admin gave', async () => {
    api.updateSlashOrder.mockResolvedValue({ version: 4, slash_waterfall_changed: true })
    const w = await panel()
    await w.find('[data-testid="slash-order-on-cascade"]').setValue(true)
    await w.find('[data-testid="slash-order-share-cascade"]').setValue('40')
    await w.find('[data-testid="slash-order-share-cascade"]').trigger('change')
    await w.find('[data-testid="slash-order-save"]').trigger('click')
    api.getSlashOrder.mockResolvedValue({ section: 'slash_waterfall', value: [...factory, { source: 'cascade', max_percent: 40 }],
      default: factory, version: 4, source: 'policy' })
    await w.find('[data-testid="confirm-go"]').trigger('click')
    await flushPromises()
    expect(api.updateSlashOrder).toHaveBeenCalledWith([...factory, { source: 'cascade', max_percent: 40 }], 'the cascade, as decided')
    expect(w.find('[data-testid="slash-order-saved"]').text()).toContain('4')
    expect(w.find('[data-testid="slash-order-source"]').text()).toContain('version 4')
  })

  it('moves a step and never lets every own step go off', async () => {
    const w = await panel()
    await w.find('[data-testid="slash-order-up-liquid"]').trigger('click')
    expect(w.findAll('[data-testid^="slash-order-step-"]').map((s) => s.attributes('data-testid'))).toEqual(
      ['slash-order-step-bond', 'slash-order-step-liquid', 'slash-order-step-stake', 'slash-order-step-cascade'])
    for (const s of ['bond', 'stake', 'liquid']) await w.find(`[data-testid="slash-order-on-${s}"]`).setValue(false)
    expect(w.find('[data-testid="slash-order-problems"]').text()).toContain('Keep at least one')
    expect((w.find('[data-testid="slash-order-save"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows the registry\'s refusal in its words and keeps the edit', async () => {
    api.updateSlashOrder.mockRejectedValue({ response: { data: { detail: 'policy refused: slash_waterfall: the cascade step must be the last step' } } })
    const w = await panel()
    await w.find('[data-testid="slash-order-on-cascade"]').setValue(true)
    await w.find('[data-testid="slash-order-save"]').trigger('click')
    await w.find('[data-testid="confirm-go"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="slash-order-save-failed"]').text()).toContain('the cascade step must be the last step')
    expect((w.find('[data-testid="slash-order-on-cascade"]').element as HTMLInputElement).checked).toBe(true)
  })

  it('says when the order could not be read, and draws no steps', async () => {
    api.getSlashOrder.mockRejectedValue(new Error('503'))
    const w = await panel()
    expect(w.find('[data-testid="slash-order-read-failed"]').exists()).toBe(true)
    expect(w.findAll('[data-testid^="slash-order-step-"]')).toHaveLength(0)
  })
})
