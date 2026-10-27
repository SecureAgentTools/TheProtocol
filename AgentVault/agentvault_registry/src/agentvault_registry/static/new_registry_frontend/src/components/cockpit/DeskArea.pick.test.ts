/**
 * §COCKPITDESK (2026-10-15) — Mission Control's board picker: a choice the registry takes shows that desk layout; a
 * choice it refuses leaves the board AND the select on what the registry holds, and says why. (Vue re-applies a select's
 * bound value on every render, so the select follows the board; a checkbox's `checked` is not re-applied that way.)
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: api }))
vi.mock('@/composables/useRegistryConfig', async (orig) => ({
  ...(await orig<Record<string, unknown>>()), useRegistryConfig: () => ({ config: { value: {} } }) }))
// real refs: a template unwraps only refs, and a plain { value: false } is truthy, so the async logs dialog started
// loading and finished after the test's environment was gone (an unhandled error that fails the build's FE unit gate)
vi.mock('@/services/cockpit/agentDoor', async () => {
  const { ref } = await import('vue')
  return { useAgentDoor: () => ({
    agentDid: ref(''), agentName: ref(''), agentOpen: ref(false), deployment: ref(null),
    deploymentDid: ref(''), deploymentOpen: ref(false), closeAgent: () => {}, closeDeployment: () => {} }) }
})

import DeskArea from './DeskArea.vue'

describe("Mission Control's board picker", () => {
  it('shows a desk layout when the registry takes the choice, and goes back when it refuses one', async () => {
    setActivePinia(createPinia())
    api.get.mockImplementation(async (url: string) => ({ data: { value: url.endsWith('cockpit.dashboard') ? { panes: ['agents'], sizes: {} } : { layouts: [] } } }))
    api.put.mockResolvedValue({ data: {} })
    const w = mount(DeskArea, { global: { stubs: { DeskBoard: true, DeskAttention: true, RouterLink: true, AgentDetailModal: true, DeploymentLogsModal: true } } })
    await flushPromises()
    const sel = w.find('select[data-testid="dsk-board"]')
    await sel.setValue('money'); await flushPromises()
    expect(w.find('[data-testid="dsk-root"]').attributes('data-follow')).toBe('money')
    expect(api.put).toHaveBeenLastCalledWith('/developers/me/prefs/cockpit.dashboard', { value: { panes: ['agents'], sizes: {}, follow: 'money' } })
    api.put.mockRejectedValueOnce(new Error('offline'))
    await sel.setValue('trading'); await flushPromises()
    expect(w.find('[data-testid="dsk-root"]').attributes('data-follow'), 'the board still shows Money').toBe('money')
    expect((sel.element as HTMLSelectElement).value, 'and so does the select').toBe('money')
    expect(w.find('[data-testid="dsk-msg"]').attributes('data-kind')).toBe('warn')
  })
})
