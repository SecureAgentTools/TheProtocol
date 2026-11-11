/**
 * V0658 (s), the review (blocking 1): the move question is an answer, not an alarm. The registry refuses a move the
 * request did not confirm with a 409 naming the organization the agent is in (AGENT_IN_ANOTHER_ORGANIZATION), and the
 * Agents tab and the join request panel ask about it in a dialog. A 409 the request did not declare as an answer reaches
 * the API client's global error handler, whose red "Error" toast (the registry's sentence, 7 s) sits above the dialog's
 * overlay, so the question opened under an alarm, and again on every stale re-ask.
 *
 * Driven through the real apiClient: its interceptors run and an adapter answers the refusal in the registry's own
 * envelope. The caller still hears the refusal, and organizationLeft still reads the organization from it. The control
 * shows the same refusal, undeclared, raising the alarm, so a pass is not the instrument going deaf.
 * RED on 6194c8fa0: the accept the panel sends through organizationService declared nothing, and the handler ran.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, type AxiosRequestConfig } from 'axios'

let apiClient: any
let organizationService: any
let errorHandler: any
// the organization as the refusal names it (what else organizationLeft reads, what confirms the move, is orgMove.test's)
let organizationLeft: (e: unknown) => { id: string | null; name: string } | null

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient } = await import('@/services/api/client'))
  ;({ organizationService } = await import('@/services/api/organizationService'))
  ;({ errorHandler } = await import('@/utils/errorHandler'))
  ;({ organizationLeft } = await import('./orgMove'))
}, 30_000)

const FROM = { id: '0a6e2f1c-0000-4000-8000-00000000000a', name: 'Alder Freight' }
const ASSIGN = '/organizations/org-b/agents/did:theprotocol:eu:courier-1/assign'

/** the registry's answer to a move the request did not confirm (errors.http_exception_handler's envelope) */
function refusesTheMove(cfg: AxiosRequestConfig): never {
  const detail = `The agent is in the organization ${FROM.name} (id ${FROM.id}). An agent belongs to one organization, `
    + `so bringing it into this one would take it out of ${FROM.name}; nothing was changed. To move it, send `
    + `leave_organization_id ${FROM.id} with the request.`
  const data = { detail, status: 409, title: 'Conflict', type: 'conflict',
    error: { code: 'AGENT_IN_ANOTHER_ORGANIZATION', type: 'conflict', detail,
      context: { current_organization: FROM, confirm_with: 'leave_organization_id' } } }
  const response = { data, status: 409, statusText: 'Conflict', headers: {}, config: cfg }
  throw new AxiosError('Request failed with status code 409', 'ERR_BAD_REQUEST', cfg as any, {}, response as any)
}

let handled: ReturnType<typeof vi.spyOn>
let adapter: unknown
beforeEach(() => {
  window.location.hash = '#/organization'
  handled = vi.spyOn(errorHandler, 'handleError').mockImplementation(() => {})
  adapter = apiClient.defaults.adapter
  apiClient.defaults.adapter = async (cfg: AxiosRequestConfig) => refusesTheMove(cfg)
})
afterEach(() => {
  handled.mockRestore()
  apiClient.defaults.adapter = adapter
})

const failure = (p: Promise<unknown>) => p.then(() => null, (e: any) => e)

describe('a move the request did not confirm, through the real API client', () => {
  it('the accept the join request panel sends: no global alarm, and the panel still reads the organization', async () => {
    const e: any = await failure(organizationService.decideAgentRequest('org-b', 'oar_1', 'accept'))
    expect(e?.response?.status, 'the panel still hears the refusal').toBe(409)
    expect(organizationLeft(e)).toMatchObject(FROM)
    expect(handled, 'a red toast over the question').not.toHaveBeenCalled()
  })

  it('the confirmed accept (a stale confirmation is refused the same way): no global alarm', async () => {
    const e: any = await failure(organizationService.decideAgentRequest('org-b', 'oar_1', 'accept',
      { leave_organization_id: 'org-c' }))
    expect(organizationLeft(e)).toMatchObject(FROM)
    expect(handled).not.toHaveBeenCalled()
  })

  it('the assign as the Agents tab sends it, the 409 declared: no global alarm', async () => {
    const e: any = await failure(apiClient.post(ASSIGN, undefined, { expectedStatuses: [409] }))
    expect(organizationLeft(e)).toMatchObject(FROM)
    expect(handled).not.toHaveBeenCalled()
  })

  it('control: the same refusal, undeclared, raises the global alarm the question stood under', async () => {
    const e: any = await failure(apiClient.post(ASSIGN))
    expect(organizationLeft(e), 'the refusal is read the same either way').toMatchObject(FROM)
    expect(handled).toHaveBeenCalledTimes(1)
  })
})
