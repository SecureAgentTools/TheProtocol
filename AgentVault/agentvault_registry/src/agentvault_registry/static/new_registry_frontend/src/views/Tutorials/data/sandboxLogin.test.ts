import { describe, expect, it } from 'vitest'
import { allTracks } from './trackDefinitions'
import { SANDBOX_ADMIN_LOGIN, SANDBOX_PASSWORD_PLACEHOLDER, SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * D6-736 (2026-10-16): no track ships a sandbox password. Fifteen tracks signed in with passwords rotated away on
 * 2026-08-08 (dead literals, refused with 401, still shipped in every console bundle); the sandbox seeds its accounts
 * from its own environment. A password a track sends is either a value it captured from an earlier answer (`$name`)
 * or the one placeholder.
 */
function passwords(body: unknown, out: string[] = []): string[] {
  if (body && typeof body === 'object') {
    for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
      if (k === 'password' && typeof v === 'string') out.push(v)
      else passwords(v, out)
    }
  }
  return out
}

describe('the tracks carry no sandbox password', () => {
  const sent = allTracks.flatMap((t) => t.steps.flatMap((s) => passwords(s.apiCall.body).map((p) => [`${t.id}/${s.id}`, p])))

  it('every password a track sends is a captured value or the placeholder', () => {
    expect(sent.length).toBeGreaterThanOrEqual(20)   // a scan over nothing passes loudest
    expect(sent.filter(([, p]) => !p.startsWith('$') && p !== SANDBOX_PASSWORD_PLACEHOLDER)).toEqual([])
  })

  it('the sign-ins name the two sandbox accounts, through the one module', () => {
    const signIns = allTracks.flatMap((t) => t.steps.filter((s) => s.apiCall.path === '/auth/login').map((s) => s.apiCall.body))
    expect(signIns.length).toBeGreaterThanOrEqual(19)
    for (const body of signIns) expect([SANDBOX_TUTORIAL_LOGIN, SANDBOX_ADMIN_LOGIN]).toContainEqual(body)
  })
})
