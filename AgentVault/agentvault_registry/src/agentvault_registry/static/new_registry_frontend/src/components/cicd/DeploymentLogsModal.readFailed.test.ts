/**
 * §FESUITE (V0577): a deployment's logs modal reads its logs through the CI/CD store, which swallowed a failure: the
 * modal said "No logs available. Logs appear here once the deployment runs." over a read that never answered, or, when
 * another deployment's logs had been read before, showed THOSE under this deployment's header. It now says the read
 * failed and offers it again. The real store, the registry answered per test.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getDeploymentLogs: vi.fn() }))
vi.mock('@/services/api/cicdService', () => ({ cicdService: h }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ resolve: () => ({ name: 'agent-cicd', href: '#/agent/x/ci-cd' }), push: vi.fn() }) }))

import DeploymentLogsModal from './DeploymentLogsModal.vue'

const deployment = (id: string) => ({ id, environment: 'staging', status: 'success', started_at: '2026-10-05T10:00:00Z' })

async function open(id: string) {
  const w = mount(DeploymentLogsModal, { props: { deployment: deployment(id), agentDid: 'did:theprotocol:mine' }, global: { stubs: { teleport: true } } })
  await flushPromises()
  return w
}

describe("a deployment's logs when their read fails", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.getDeploymentLogs.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says the read failed, never "No logs available", nor the previous deployment\'s logs', async () => {
    h.getDeploymentLogs.mockResolvedValueOnce(JSON.stringify([{ message: 'deployment one says hello' }]))
    const first = await open('d1')
    expect(first.text()).toContain('deployment one says hello')
    first.unmount()

    h.getDeploymentLogs.mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await open('d2')
    expect(w.text(), "showed deployment one's logs under deployment two").not.toContain('deployment one says hello')
    expect(w.text()).not.toContain('No logs available')
    expect(w.find('[data-testid="cicd-logs-failed"]').exists()).toBe(true)
  })
})
