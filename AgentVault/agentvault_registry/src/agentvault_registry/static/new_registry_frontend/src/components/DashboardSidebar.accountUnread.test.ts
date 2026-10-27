import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * §LEDGERGATE (V0601): a session whose account could not be read is not a guest. With /developers/me unanswered the
 * sidebar said VIEWING AS GUEST and offered Sign in to a person signed in all along (journal 51's figures, Sandbox
 * Beta). The sidebar is too large to mount here, so this reads its template: the guest block needs no session at all,
 * and a session without its account says the read failed, with Try again. RED on fe/batch-v0600.
 */
const src = readFileSync(path.resolve(__dirname, 'DashboardSidebar.vue'), 'utf-8')
const guest = src.match(/<div v-else-if="([^"]+)" class="p-4 sidebar-border-b sidebar-anon-cta">/)

describe('the sidebar calls only a visitor without a session a guest', () => {
  it('the guest block needs no session', () => {
    expect(guest, 'the guest block').not.toBeNull()
    expect(guest![1]).toContain('!currentUser')
    expect(guest![1]).toContain('!authStore.isAuthenticated')
  })

  it('a session without its account says the read failed, and offers it again', () => {
    const unread = src.match(/<div v-else-if="([^"]+)"[^>]*data-testid="sidebar-account-unread">\s*<ReadFailedNotice([^>]*)\/>/)
    expect(unread, 'the account-unread block').not.toBeNull()
    expect(unread![1]).toMatch(/!currentUser && authStore\.isAuthenticated/)
    expect(unread![2]).toContain(':retry="retryAccount"')
    expect(src).toMatch(/function retryAccount\(\) \{ return authStore\.refreshProfile\(\) \}/)
    expect(src.indexOf('data-testid="sidebar-account-unread"')).toBeLessThan(src.indexOf('sidebar-anon-cta"'))
  })
})
