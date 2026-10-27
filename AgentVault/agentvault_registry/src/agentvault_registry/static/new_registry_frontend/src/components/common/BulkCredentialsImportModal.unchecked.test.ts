/**
 * §FESUITE (V0577): "could not verify is not invalid" (CLAUDE.md PART 1) in the bulk credentials import. With "Verify
 * each credential" on, a credential whose check got no answer (its registry down, a server error, the browser refusing
 * the request) was a ✗ "fail" and counted under "failed verification", beside credentials the registry really refused.
 * It is now "not checked": not saved (the person asked for a check before saving), named as such in its row, the result
 * and the toast, and never counted as a failed verification. A 401 is still a rejection.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({
  authenticate: vi.fn(),
  ui: { showSuccess: vi.fn(), showWarning: vi.fn(), showError: vi.fn(), showInfo: vi.fn() },
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { authenticate: h.authenticate } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ fetchAvailableAgents: vi.fn(async () => true) }) }))

import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import BulkCredentialsImportModal from './BulkCredentialsImportModal.vue'

const answered = (s: number) => new AxiosError(`Request failed with status code ${s}`, s >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST',
  undefined, undefined, { status: s, statusText: '', data: {}, headers: {}, config: {} } as any)
const entry = (n: string) => ({ did: `did:theprotocol:${n}`, client_id: `cid-${n}`, client_secret: `secret-${n}-0123456789abcdef`, name: n })

/** the registry's answer to each credential's check, by name */
const CHECKS: Record<string, () => Promise<unknown>> = {
  good: async () => ({ access_token: 'agent.jwt' }),
  wrong: async () => { throw answered(401) },
  silent: async () => { throw new AxiosError('Network Error', 'ERR_NETWORK') },
  broken: async () => { throw answered(502) },
}

beforeEach(() => {
  localStorage.clear()
  Object.values(h.ui).forEach(f => f.mockReset())
  h.authenticate.mockReset()
  h.authenticate.mockImplementation((did: string) => CHECKS[did.split(':').pop()!]())
})

async function importWithChecks(names: string[]) {
  const stored = vi.spyOn(agentCredentialsStore, 'storeCredentials')
  const w = mount(BulkCredentialsImportModal, { props: { show: true }, global: { stubs: { teleport: true } } })
  await flushPromises()
  await w.find('textarea').setValue(JSON.stringify(names.map(entry)))
  await w.find('input[type="checkbox"]').setValue(true)
  await w.findAll('button').find(b => b.text().startsWith('Preview'))!.trigger('click')
  await w.findAll('button').find(b => b.text().startsWith('Apply'))!.trigger('click')
  await flushPromises()
  const storedDids = stored.mock.calls.map(c => (c[0] as any).did)
  stored.mockRestore()
  return { w, storedDids }
}

describe('the bulk import when a credential check gets no answer', () => {
  it('names it not checked, never a failed verification, and does not save it; a 401 is still a rejection', async () => {
    const { w, storedDids } = await importWithChecks(['good', 'wrong', 'silent', 'broken'])
    const result = w.find('.bk-result').text()
    expect(result).toContain('Imported 1 of 4')
    expect(result).toContain('1 failed verification')
    expect(result).toContain('2 could not be checked')
    expect(storedDids).toEqual(['did:theprotocol:good'])

    const rows = w.findAll('.bk-row').map(r => ({ did: r.find('.bk-row-did').text(), tag: r.find('.bk-row-tag').text() }))
    expect(rows).toEqual([
      { did: 'did:theprotocol:good', tag: 'ok' },
      { did: 'did:theprotocol:wrong', tag: 'fail' },
      { did: 'did:theprotocol:silent', tag: 'unchecked' },
      { did: 'did:theprotocol:broken', tag: 'unchecked' },
    ])
    const toast = h.ui.showWarning.mock.calls.find(c => c[0] === 'Partial Import')
    expect(toast?.[1]).toBe('1 of 4 entries failed. 2 could not be checked (their registry did not answer) and were not saved.')
  })

  it('when every check went unanswered, nothing reads as rejected', async () => {
    const { w, storedDids } = await importWithChecks(['silent', 'broken'])
    const result = w.find('.bk-result').text()
    expect(result).not.toContain('failed verification')
    expect(result).toContain('Imported 0 of 2')
    expect(w.find('.bk-progress-failed').exists()).toBe(false)
    expect(w.find('[data-testid="bulk-progress-unchecked"]').text()).toContain('2 not checked')
    expect(storedDids).toEqual([])
  })
})
