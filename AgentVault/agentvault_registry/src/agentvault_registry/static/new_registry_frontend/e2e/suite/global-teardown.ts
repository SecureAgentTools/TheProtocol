/**
 * The sweep (§FESUITE): every developer this run registered asks for its own deletion (the product's path: 202, the
 * account pending deletion, anonymised by the deletion worker after its grace period). Only accounts in this run's
 * ledger, and only ones carrying its prefix, are touched; the ledger then keeps the outcome and loses the password.
 */
import { request } from '@playwright/test'
import { API_URL, PREFIX } from './support/env'
import { isOurs, readLedger, scrubLedger } from './support/accounts'

export default async function globalTeardown(): Promise<void> {
  const devs = readLedger().filter((r) => r.kind === 'developer' && r.password && isOurs(String(r.name || '')))
  if (!devs.length) return
  const ctx = await request.newContext({ baseURL: API_URL })
  const outcomes = new Map<string, string>()
  try {
    for (const d of devs) {
      const email = String(d.email)
      const login = await ctx.post('/api/v1/auth/login', { form: { username: email, password: String(d.password) }, failOnStatusCode: false })
      const token = login.status() === 200 ? (await login.json().catch(() => null))?.access_token : null
      if (!token) {
        // A lifecycle that deleted or locked its own account leaves nothing to sweep, and says so in the ledger.
        outcomes.set(email, `login ${login.status()}`)
        continue
      }
      const del = await ctx.post('/api/v1/account/request-deletion', {
        headers: { authorization: `Bearer ${token}` },
        data: { password: String(d.password), confirmation: 'DELETE MY ACCOUNT' },
        failOnStatusCode: false,
      })
      outcomes.set(email, `request-deletion ${del.status()}`)
    }
  } finally {
    await ctx.dispose()
    scrubLedger(outcomes)
  }
  const bad = [...outcomes.values()].filter((v) => !/ 202$| 409$/.test(v)).length
  process.stdout.write(`[fesuite] sweep (${PREFIX}): ${outcomes.size} account(s), ${outcomes.size - bad} deletion requested${bad ? `, ${bad} not (see created.jsonl)` : ''}\n`)
}
