/**
 * D6-782 (2026-10-17): the API tester's 2FA request templates carry no account's password.
 *
 * The setup and backup-codes templates sent the sandbox admin's password as it was before its rotation (2026-08-08):
 * dead since, but a credential-shaped literal in every console bundle. A 2FA change asks for the password of the
 * account signed in, so the templates now carry a placeholder the tester fills in (the health check's tokens work the
 * same way). The assertions compare without printing what a template holds: a failure names the template, not a value.
 */
import { describe, expect, it } from 'vitest'
import { ApiTestEngine } from './ApiTesterLogic'

const PLACEHOLDER = 'YOUR_CURRENT_PASSWORD'

describe('the API tester request templates', () => {
  it('ask for the current password in the 2FA templates, and carry none', () => {
    const engine = new ApiTestEngine()
    for (const path of ['/auth/2fa/setup', '/auth/2fa/backup-codes']) {
      const body = engine.findDefaultBody(path)
      expect(!!body, `${path} has a template`).toBe(true)
      expect(body.password === PLACEHOLDER, `${path}: its password is the placeholder`).toBe(true)
      // what the request editor shows (and resets to)
      expect(engine.getDefaultBody(path).includes(`"password": "${PLACEHOLDER}"`), `${path}: the editor shows it`).toBe(true)
    }
  })
})
