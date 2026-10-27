import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-04) — /tutorials said "the sandbox tier … is switched off on this registry" when its health check
 * FAILED (the census on V0571, fes-20261004T161229Z-d0d7: a FALSE "off", gone once the reads answered): the check answered
 * false for every failure. The hub already reads only an EXPLICIT false as off and null as unanswered; the check now
 * keeps that meaning. Mocked at the HTTP layer.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: http.get } }))

import { tutorialApiService } from './tutorialApiService'
import { useTutorialRunnerStore } from '../stores/tutorialRunnerStore'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the sandbox check tells "could not check" from "off"', () => {
  beforeEach(() => { http.get.mockReset(); setActivePinia(createPinia()) })

  it('a failed check is unknown (null), never "off"', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(tutorialApiService.checkSandboxHealth()).resolves.toBeNull()
    http.get.mockRejectedValueOnce(new Error('timeout of 5000ms exceeded'))
    await expect(tutorialApiService.checkSandboxHealth()).resolves.toBeNull()
  })

  it('"off" is an answer: healthy false, or no sandbox tier served here (404)', async () => {
    http.get.mockResolvedValueOnce({ data: { healthy: false } })
    await expect(tutorialApiService.checkSandboxHealth()).resolves.toBe(false)
    http.get.mockRejectedValueOnce(answered(404))
    await expect(tutorialApiService.checkSandboxHealth()).resolves.toBe(false)
    http.get.mockResolvedValueOnce({ data: { healthy: true } })
    await expect(tutorialApiService.checkSandboxHealth()).resolves.toBe(true)
  })

  it('the store marks a check that could not be read, and clears it when one answers', async () => {
    const store = useTutorialRunnerStore()
    http.get.mockRejectedValueOnce(answered(503))
    await store.checkSandbox()
    expect(store.sandboxHealthy).toBeNull()
    expect(store.sandboxCheckFailed).toBe(true)
    http.get.mockResolvedValueOnce({ data: { healthy: false } })
    await store.checkSandbox()
    expect(store.sandboxHealthy).toBe(false)
    expect(store.sandboxCheckFailed).toBe(false)
  })
})
