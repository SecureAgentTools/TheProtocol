/** §FESUITE (2026-10-10): a refused action on the agent's Access panel says what was refused, in words, never as JSON. */
import { describe, expect, it } from 'vitest'
import { refusalText } from './accessRefusal'

const refused = (data: unknown, message = 'Request failed with status code 422') => ({ message, response: { data } })

// the registry's own 422 (errors.py, validation_exception_handler), as sandbox-b answered a refused register on 2026-10-10
const registry422 = (errors: Array<{ field: string, message: string }>) => ({
  error: { detail: errors[0].message, type: 'validation_error', code: 'VALIDATION_FAILED', field: errors[0].field,
    ...(errors.length > 1 ? { context: { errors: errors.map((x) => ({ ...x, type: 'value_error' })) } } : {}) },
  type: 'https://docs.theprotocol.cloud/errors/validation_error', title: 'Validation Error', status: 422,
  detail: errors[0].message, instance: '/api/v1/agents/did/authz',
})

describe('what a refused action says', () => {
  it("the registry's own 422 names the refused field (error.field), not only the rule", () => {
    const e = refused(registry422([{ field: 'body -> spend_policy -> rate_per_hour', message: 'Input should be greater than or equal to 1' }]))
    expect(refusalText(e, 'Save failed')).toBe('rate per hour: Input should be greater than or equal to 1')
  })

  it("the registry's own 422 with several refused fields names each (error.context.errors)", () => {
    const e = refused(registry422([
      { field: 'body -> spend_policy -> rate_per_hour', message: 'Input should be greater than or equal to 1' },
      { field: 'body -> roles -> 0', message: 'Input should be a valid string' },
    ]))
    expect(refusalText(e, 'x')).toBe('rate per hour: Input should be greater than or equal to 1; roles: Input should be a valid string')
  })

  it("the registry's refusal that names no field is its sentence", () => {
    const e = refused({ error: { detail: 'authz.delegate is required to delegate', type: 'forbidden' }, title: 'Forbidden',
      status: 403, detail: 'authz.delegate is required to delegate' }, 'Request failed with status code 403')
    expect(refusalText(e, 'x')).toBe('authz.delegate is required to delegate')
  })

  it('a refused field in FastAPI\'s own 422 (a list) names the field and the rule', () => {
    const e = refused({ detail: [{ type: 'greater_than_equal', loc: ['body', 'spend_policy', 'rate_per_hour'],
      msg: 'Input should be greater than or equal to 1', input: 0 }] })
    expect(refusalText(e, 'Save failed')).toBe('rate per hour: Input should be greater than or equal to 1')
  })

  it('two refused fields are both named', () => {
    const e = refused({ detail: [
      { loc: ['body', 'spend_policy', 'rate_per_hour'], msg: 'Input should be greater than or equal to 1' },
      { loc: ['body', 'roles', 0], msg: 'Input should be a valid string' },
    ] })
    expect(refusalText(e, 'x')).toBe('rate per hour: Input should be greater than or equal to 1; roles: Input should be a valid string')
  })

  it('a string detail is said as it is; an object one by its message', () => {
    expect(refusalText(refused({ detail: 'authz.delegate is required' }), 'x')).toBe('authz.delegate is required')
    expect(refusalText(refused({ detail: { message: 'not your agent', code: 'owner' } }), 'x')).toBe('not your agent')
  })

  it('no detail at all: the RFC 7807 title, then the error, then the fallback', () => {
    expect(refusalText(refused({ title: 'Forbidden' }), 'x')).toBe('Forbidden')
    expect(refusalText({ message: 'Network Error' }, 'x')).toBe('Network Error')
    expect(refusalText({}, 'Save failed')).toBe('Save failed')
  })

  it('never JSON', () => {
    const e = refused({ detail: [{ loc: ['body'], msg: 'Field required' }, { nonsense: true }] })
    const said = refusalText(e, 'x')
    expect(said).toBe('Field required')
    expect(said).not.toMatch(/[{}[\]]/)
  })
})
