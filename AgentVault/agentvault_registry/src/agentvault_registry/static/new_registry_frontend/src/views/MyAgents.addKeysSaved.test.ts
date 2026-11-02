import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): after a secret is saved and still sits unencrypted
 * in this browser, the add-keys dialog stays open on its saved step (where the secret sits, the one press that locks
 * it, Done). My Agents closed it on its "saved" event (and unmounted it with agentForAddCreds), so the step never
 * showed here. The view is too large to mount here (MyAgents.fleetUnread.test.ts), so this reads its script and
 * template; the real-browser drive of the dialog covers the rest. RED on 17f71c143.
 */
const src = readFileSync(path.resolve(__dirname, 'MyAgents.vue'), 'utf-8')

describe("My Agents and the add-keys dialog's saved step", () => {
  it('a save refreshes the cards and leaves the dialog open', () => {
    const body = src.match(/function handleAddCredsSaved\(\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    expect(body, 'the handler is there').toContain('credsRefreshTick.value += 1')
    expect(body).not.toMatch(/showAddCredentials\.value = false/)
    expect(body).not.toMatch(/agentForAddCreds\.value = null/)
  })

  it("the dialog's own close closes it", () => {
    expect(src).toMatch(/<AddCredentialsModal[\s\S]*?@close="showAddCredentials = false; agentForAddCreds = null"[\s\S]*?@saved="handleAddCredsSaved"/)
  })
})
