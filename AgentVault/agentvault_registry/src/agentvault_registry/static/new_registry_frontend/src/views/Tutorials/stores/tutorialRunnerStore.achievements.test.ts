import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * D6-737 (2026-10-16): finishing a track records its achievement, `tutorial_<track id>`, for every track the hub lists.
 * A hand-kept map named the first twelve, so AGORA Trading, Organizations, CI/CD and Regulatory Approval recorded
 * nothing, and "all tutorials complete" meant the first twelve. The step call and the record are both mocked at the HTTP
 * layer: nothing reaches a sandbox or a registry.
 */
const http = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { post: http.post, get: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:mine' } }) }))

import { achievementTypeFor, useTutorialRunnerStore } from './tutorialRunnerStore'
import { allTracks } from '../data/trackDefinitions'
import type { TutorialTrack } from '../types/tutorial.types'

const NEWER = ['agora-trading', 'organizations', 'agent-cicd', 'jurisdiction']
const records = () => http.post.mock.calls.filter(([url]) => url === '/achievements/record').map(([, body]) => body)

/** the track with only its first step, which the mocked sandbox answers with 200, so one Execute completes it */
function oneStep(id: string): TutorialTrack {
  const t = allTracks.find((x) => x.id === id)!
  const step = { ...t.steps[0], apiCall: { ...t.steps[0].apiCall, path: '/agents/x', targetBase: undefined },
    validation: { successStatusCodes: [200] }, captures: [], requiresStepId: undefined }
  return { ...t, steps: [step] } as TutorialTrack
}

async function finish(id: string) {
  const store = useTutorialRunnerStore()
  store.loadTrack(oneStep(id))
  const r = await store.executeCurrentStep()
  expect(r.status).toBe('success')
  await flushPromises()
}

describe('every track records its achievement', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    http.post.mockReset().mockImplementation(async (url: string) =>
      url === '/admin/tutorial/execute'
        ? { data: { status_code: 200, response: {}, response_time: 1 } }
        : { data: { status: 'recorded' } })
  })

  it('the four newer tracks record tutorial_<id> like the first twelve', async () => {
    for (const id of NEWER) await finish(id)
    expect(records().map((b) => b.achievement_type)).toEqual(
      ['tutorial_agora_trading', 'tutorial_organizations', 'tutorial_agent_cicd', 'tutorial_jurisdiction'])
    expect(records().every((b) => b.agent_did === 'did:theprotocol:mine')).toBe(true)
  })

  it('the first twelve keep the names they always recorded, and no two tracks share one', () => {
    expect(achievementTypeFor('agent-lifecycle')).toBe('tutorial_agent_lifecycle')
    expect(achievementTypeFor('cross-registry-commerce')).toBe('tutorial_cross_registry_commerce')
    expect(achievementTypeFor('full-agent-economy')).toBe('tutorial_full_agent_economy')
    const types = allTracks.map((t) => achievementTypeFor(t.id))
    expect(allTracks.length).toBeGreaterThanOrEqual(16)
    expect(new Set(types).size).toBe(types.length)
  })

  it('"all tutorials complete" waits for every track the hub lists, the newer four included', async () => {
    const done = (ids: string[]) => Object.fromEntries(ids.map((id) => [id, { trackId: id, completedStepIds: [],
      capturedValues: {}, lastStepIndex: 0, savedAt: '', completedAt: '2026-10-16T00:00:00Z' }]))
    const firstTwelve = allTracks.map((t) => t.id).filter((id) => !NEWER.includes(id))
    localStorage.setItem('theprotocol_tutorial_progress', JSON.stringify(done(firstTwelve.slice(1))))
    await finish(firstTwelve[0])
    expect(records().map((b) => b.achievement_type)).not.toContain('all_tutorials_complete')
    localStorage.setItem('theprotocol_tutorial_progress',
      JSON.stringify(done(allTracks.map((t) => t.id).filter((id) => id !== 'jurisdiction'))))
    await finish('jurisdiction')
    expect(records().map((b) => b.achievement_type)).toContain('all_tutorials_complete')
  })
})
