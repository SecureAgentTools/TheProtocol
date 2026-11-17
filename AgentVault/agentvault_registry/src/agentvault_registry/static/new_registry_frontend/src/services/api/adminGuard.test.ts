/**
 * V0662, the admin guard (order gwo_c406296cb118596aa7c5c1c2; PLAN_2026-11-13_NO_ADMIN_CALLS_FOR_NON_ADMINS.md,
 * layer 2). CrowdSec bans a person whose console page fires refused admin calls (http-probing counts each 403 and
 * 404), so the console decides first: a call whose route needs an admin flag this session does not hold is not sent.
 * The rule is the registry's own (adminRoutes.generated.json, generated from its routes; the registry's test keeps the
 * copy equal), read in serving order: the first route that matches decides, as on the server.
 * Red on f569f6a6e: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { compileRule, adminFlagsFor, mayCall, ADMIN_RULE } from './adminGuard'

const FAKE = compileRule({ routes: [
  ['GET', '/api/v1/admin/things/summary', []],                 // a member's literal route, served first
  ['GET', '/api/v1/admin/things/{thing_id}', ['platform']],
  ['GET', '/api/v1/admin/files/{rest:path}', ['support']],
  ['POST', '/api/v1/admin/both', ['enforcement', 'platform']],
  ['POST', '/api/v1/teg/treasury/fund-agent', ['treasury']],
] })

describe('which flags a call needs', () => {
  it('the first route that matches decides: a member literal before an admin parameter', () => {
    expect(adminFlagsFor('get', '/admin/things/summary', FAKE)).toEqual([])
    expect(adminFlagsFor('get', '/admin/things/t-1', FAKE)).toEqual(['platform'])
  })
  it('a path parameter, a path converter, a query string, a method, the /api/v1 prefix', () => {
    expect(adminFlagsFor('GET', '/admin/files/a/b/c.txt?x=1', FAKE)).toEqual(['support'])
    expect(adminFlagsFor('post', '/admin/things/t-1', FAKE)).toBeNull()
    expect(adminFlagsFor('post', '/api/v1/teg/treasury/fund-agent', FAKE)).toEqual(['treasury'])
    expect(adminFlagsFor(undefined, '/admin/things/t-1', FAKE), 'no method is GET').toEqual(['platform'])
  })
  it('a call the rule does not know is not judged', () => {
    expect(adminFlagsFor('get', '/developers/me', FAKE)).toBeNull()
  })
})

describe('who may make it', () => {
  it('legacy is_admin holds every flag; otherwise every named flag must be held', () => {
    expect(mayCall({ is_admin: true }, ['enforcement', 'platform'])).toBe(true)
    expect(mayCall({ admin_platform: true }, ['platform'])).toBe(true)
    expect(mayCall({ admin_platform: true }, ['enforcement', 'platform'])).toBe(false)
    expect(mayCall({ is_admin: false }, ['platform'])).toBe(false)
    expect(mayCall(null, ['platform'])).toBe(false)
    expect(mayCall({}, [])).toBe(true)
  })
})

describe('the registry\'s rule, as shipped', () => {
  it('the suspects of the plan are admin calls; the tours\' Try it live is a member\'s', () => {
    expect(adminFlagsFor('get', '/admin/events/search', ADMIN_RULE)).toEqual(['platform'])
    expect(adminFlagsFor('get', '/admin/federation/topology-overview', ADMIN_RULE)).toEqual(['federation'])
    expect(adminFlagsFor('post', '/admin/federation/drift-scan', ADMIN_RULE)).toEqual(['federation'])
    expect(adminFlagsFor('get', '/admin/degradation-coverage', ADMIN_RULE)).toEqual(['platform'])
    expect(adminFlagsFor('post', '/admin/tutorial/execute', ADMIN_RULE)).toEqual([])
  })
})
