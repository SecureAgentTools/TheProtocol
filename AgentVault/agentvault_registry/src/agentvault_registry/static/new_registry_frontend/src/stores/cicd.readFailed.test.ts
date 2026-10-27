/**
 * §FESUITE (V0577): the CI/CD store's list reads swallowed every failure into a console line. The member CI/CD page then
 * said "none" (with counts of 0) over reads that never answered; and the store, one for every agent, kept the previous
 * agent's pipelines, versions and deployments (and the previous deployment's logs) on screen under the next one's name
 * when the next read failed. A failed per-agent read now clears its list and sets readFailed; an answer clears the flag.
 * The templates, the same for every agent, keep what they last read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({
  listPipelines: vi.fn(), listVersions: vi.fn(), listDeployments: vi.fn(), getDeploymentLogs: vi.fn(), listTemplates: vi.fn(),
}))
vi.mock('@/services/api/cicdService', () => ({ cicdService: h }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }) }))

import { useCICDStore } from './cicd'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')

describe("the CI/CD store's list reads", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h)) f.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it("a failed read clears the previous agent's list and says it failed; an answer clears the flag", async () => {
    const store = useCICDStore()
    h.listPipelines.mockResolvedValueOnce([{ id: 'p-of-agent-a', pipeline_name: 'A pipeline' }])
    await store.fetchPipelines('did:theprotocol:a')
    expect(store.pipelines.map((p: any) => p.id)).toEqual(['p-of-agent-a'])

    h.listPipelines.mockRejectedValueOnce(noAnswer())
    await store.fetchPipelines('did:theprotocol:b')
    expect(store.pipelines, "agent A's pipelines stayed under agent B").toEqual([])
    expect(store.readFailed.pipelines).toBe(true)

    h.listPipelines.mockResolvedValueOnce([])
    await store.fetchPipelines('did:theprotocol:b')
    expect(store.readFailed.pipelines).toBe(false)
  })

  it('versions, deployments and logs the same way', async () => {
    const store = useCICDStore()
    h.listVersions.mockResolvedValueOnce([{ id: 'v1' }]); await store.fetchVersions('a')
    h.listDeployments.mockResolvedValueOnce([{ id: 'd1', status: 'success' }]); await store.fetchDeployments('a')
    h.getDeploymentLogs.mockResolvedValueOnce('deployment one says hello'); await store.fetchDeploymentLogs('a', 'd1')

    h.listVersions.mockRejectedValueOnce(noAnswer()); await store.fetchVersions('b')
    h.listDeployments.mockRejectedValueOnce(noAnswer()); await store.fetchDeployments('b')
    h.getDeploymentLogs.mockRejectedValueOnce(noAnswer()); await store.fetchDeploymentLogs('b', 'd2')
    expect([store.versions, store.deployments, store.deploymentLogs]).toEqual([[], [], ''])
    expect(store.readFailed).toMatchObject({ versions: true, deployments: true, logs: true })
  })

  it('the templates keep what they last read, and say a refresh failed', async () => {
    const store = useCICDStore()
    h.listTemplates.mockResolvedValueOnce([{ id: 't1', name: 'Python service' }]); await store.fetchTemplates()
    h.listTemplates.mockRejectedValueOnce(noAnswer()); await store.fetchTemplates()
    expect(store.templates.map((t: any) => t.id)).toEqual(['t1'])
    expect(store.readFailed.templates).toBe(true)
  })
})
