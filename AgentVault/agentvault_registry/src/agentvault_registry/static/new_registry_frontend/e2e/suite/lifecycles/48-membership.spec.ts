/**
 * Membership on the Senate floor and in Pocket's senate sheet (§MEMBERSHIP phase C's browser pass, at 1440 and 393 px).
 * Where the frame runs governance in member mode (GOVERNANCE_WEIGHT_MODE=member, read from /public/registry-config):
 * a fresh developer reads as not a member with the server's next step; the agent posts its own reputation bond and,
 * once the bond counts (immediately where the frame asks no bond age), the developer reads as a member with weight
 * 1.00 on the panel, the stat card and the vote dialog. The fresh agent holds no `governor` role (gov.vote under IRONKEY
 * enforce), so the floor says it may not vote yet and the owner allows it with two presses: the role is added and every
 * other grant stays as it was (the additive rail, or the whole-set PUT on an image without it). Nothing is voted. The
 * words these pages own carry no reward, yield, APY, share, return or investment, and no page scrolls sideways. A frame
 * in lock mode is NOT MEASURED, loudly.
 */
import type { Page } from '@playwright/test'
import { test, expect } from '../support/fixtures'
import { agentToken, createAgentApi, registerDeveloper, seedActiveAgent, seedSession, seedVault } from '../support/accounts'
import { openRoute } from '../support/ui'

const RETIRED = /\b(rewards?|yield|apy|shares?|returns?|investments?)\b/i

async function memberMode(api: { json: (m: string, p: string, o?: any) => Promise<{ status: number; body: any }> }) {
  const r = await api.json('GET', '/api/v1/public/registry-config')
  return r.status === 200 && r.body?.governance_weight_mode === 'member'
}

/** The first proposal card with a vote: its For figure against the ledger's votes_for (points in member mode, power in
 *  lock mode), converted the way the floor must speak it. Undefined when no card carries an id (an older console) or
 *  none has a vote yet: the caller says NOT MEASURED. */
async function cardVsLedger(page: Page, api: { json: (m: string, p: string, o?: any) => Promise<{ status: number; body: any }> },
                            per: number): Promise<{ id: string; ledger: number; want: string; shown: string } | undefined> {
  const cards = page.locator('[data-tour="sen-proposal"][data-id]')
  const n = Math.min(await cards.count(), 12)
  for (let i = 0; i < n; i++) {
    const id = String(await cards.nth(i).getAttribute('data-id'))
    const p = (await api.json('GET', `/api/v1/governance/proposals/${encodeURIComponent(id)}`)).body || {}
    const ledger = Number(p.votes_for)
    if (!(ledger > 0)) continue
    const want = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(ledger / per)
    const shown = (await cards.nth(i).locator('[data-testid="sen-votes-for"]').innerText()).replace(/\s+/g, ' ').trim()
    return { id, ledger, want, shown }
  }
  return undefined
}

/** The first failed card whose proposal stored why it failed (tally_quorum_met, agentvault2-33's 0185) against the reason
 *  the card shows. Undefined when no failed card on the floor carries the stored answer yet. */
async function failedCardVsTally(page: Page, api: { json: (m: string, p: string, o?: any) => Promise<{ status: number; body: any }> }) {
  const cards = page.locator('[data-tour="sen-proposal"][data-id]')
  const n = Math.min(await cards.count(), 20)
  const out: { id: string; want: string; shown: string | null }[] = []
  for (let i = 0; i < n; i++) {
    const id = String(await cards.nth(i).getAttribute('data-id'))
    const p = (await api.json('GET', `/api/v1/governance/proposals/${encodeURIComponent(id)}`)).body || {}
    if (String(p.status || '').toLowerCase() !== 'failed' || typeof p.tally_quorum_met !== 'boolean') continue
    const want = p.tally_quorum_met ? 'majority_against' : 'quorum_not_met'
    const shown = await cards.nth(i).locator('[data-testid="sen-fail-reason"]').evaluateAll((els) => (els.length ? els[0].getAttribute('data-reason') : null))
    out.push({ id, want, shown })
  }
  return out
}

/** The first decided card whose proposal stored the numbers it was decided on (tally_weight_mode, tally_quorum_required;
 *  agentvault2-33's 0185) against its quorum line: the stored figure, in the unit the tally stored. */
async function decidedCardVsTally(page: Page, api: { json: (m: string, p: string, o?: any) => Promise<{ status: number; body: any }> }) {
  const cards = page.locator('[data-tour="sen-proposal"][data-id]')
  const n = Math.min(await cards.count(), 20)
  const per = Number((await api.json('GET', '/api/v1/membership/stats')).body?.points_per_weight) || 100
  const out: { id: string; mode: string; stored: number; want: string; shown: string | null }[] = []
  for (let i = 0; i < n; i++) {
    const id = String(await cards.nth(i).getAttribute('data-id'))
    const p = (await api.json('GET', `/api/v1/governance/proposals/${encodeURIComponent(id)}`)).body || {}
    const mode = p.tally_weight_mode, q = Number(p.tally_quorum_required)
    if ((mode !== 'member' && mode !== 'lock') || !Number.isFinite(q) || p.tally_quorum_required == null) continue
    const want = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(mode === 'member' ? q / per : q)
    const shown = await cards.nth(i).locator('[data-testid="sen-quorum"]').evaluateAll((els) => (els.length ? (els[0] as HTMLElement).innerText.replace(/\s+/g, ' ').trim() : null))
    out.push({ id, mode, stored: q, want, shown })
  }
  return out
}

/** Does the console under test render the board's cancelled-season count at all (626a189e, V0552)? Its compiled board
 *  chunk names the line's test id if and only if it does: asked of the code that is running, never inferred from a
 *  version or from whose build is served. */
async function boardKnowsCancelled(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const urls = performance.getEntriesByType('resource').map((e) => e.name).filter((n) => /\/RegistryBoard-[^/]*\.js(\?|$)/.test(n))
    for (const u of urls) {
      try { if ((await (await fetch(u)).text()).includes('board-commons-cancelled')) return true } catch { /* unreadable: not known */ }
    }
    return false
  })
}

/** The Senate floor's "Total Voters" card reads a whole count (the server's total_voters is an int: "247", never
 *  "247.00"). Undefined on a console whose card carries no test id yet (before V0552). */
async function totalVotersIsACount(page: Page): Promise<{ text: string; ok: boolean } | undefined> {
  const t = await page.locator('[data-testid="sen-total-voters"]').evaluateAll((els) => (els.length ? (els[0] as HTMLElement).innerText.trim() : null))
  if (t === null) return undefined
  return { text: t, ok: /^\d{1,3}(,\d{3})*$/.test(t) }
}

/** The page never scrolls sideways (a 393 px phone shows what a 393 px phone shows). */
async function noSidewaysScroll(page: Page, where: string) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(over, `${where}: the page is ${over}px wider than the screen`).toBeLessThanOrEqual(1)
}

/** The retired words, in the text these pages own (the panel, the stat card, the dialog), never the app's chrome. */
async function ownWordsClean(page: Page, selectors: string[], where: string) {
  for (const sel of selectors) {
    // one read that never waits: some of these (the vote-permission notice) leave the page, and a waiting read after
    // count() would time out on an element that left on purpose (agentvault2-45's sweep, 2026-10-02)
    const raw = await page.locator(sel).evaluateAll((els) => (els.length ? (els[0] as HTMLElement).innerText : null))
    if (raw === null) continue
    const text = raw.replace(/\s+/g, ' ')
    const hit = text.match(RETIRED)
    expect(hit?.[0] ?? null, `${where}: "${hit?.[0]}" in ${sel}: ${text.slice(0, 160)}`).toBeNull()
  }
}

test('membership_panel_and_member_weight', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(4 * 60_000)
  if (!(await memberMode(api))) {
    // production's shape: governance by locked units, so nothing of membership may show or be asked for
    const ldev = await registerDeveloper(api, 'memlock')
    const la = await createAgentApi(api, ldev, 'mem-l')
    await seedSession(context, ldev.token)
    await seedVault(context, api, ldev, [la])
    await seedActiveAgent(context, la.did)
    await steps.run('lock-mode-shows-nothing-of-membership', 'ui:developer', async () => {
      const asked: string[] = []
      page.on('request', (r) => { if (/\/api\/v1\/(membership|commons)(\/|$)/.test(new URL(r.url()).pathname)) asked.push(`${r.method()} ${new URL(r.url()).pathname}`) })
      await openRoute(page, '/senate?tab=governance')
      await expect(page.locator('[data-testid="sen-power-value"]'), 'the floor rendered its stat cards').toBeVisible({ timeout: 20_000 })
      expect(await page.locator('[data-testid="membership-panel"]').count(), 'no membership panel').toBe(0)
      expect(await page.locator('[data-testid="vote-permission"]').count(), 'no vote-permission notice').toBe(0)
      expect(await page.locator('[data-testid="sen-tab-commons"]').count(), 'no commons tab').toBe(0)
      expect(asked, 'no membership or commons read').toEqual([])
      const c = await cardVsLedger(page, api, 1)
      if (c) expect(c.shown, `#${c.id}: lock mode keeps the ledger's figure`).toContain(c.want)
      const tv = await totalVotersIsACount(page)
      if (tv) expect(tv.ok, `"Total Voters" reads a whole count, not "${tv.text}"`).toBe(true)
      return 'lock mode: no membership panel, no vote-permission notice, no commons tab, no membership or commons read'
        + (c ? `; card #${c.id} keeps the ledger's ${c.want}` : '') + (tv ? `; Total Voters "${tv.text}"` : '')
    })
    // production's shape for every proposal decided after migration 0185: the stored record, in power units
    await steps.run('lock-mode-a-decided-card-shows-the-quorum-it-was-decided-on', 'ui:developer', async () => {
      const all = await decidedCardVsTally(page, api)
      if (!all.length) return 'NOT MEASURED: no decided proposal here stored its numbers yet (migration 0185 ships with the ballots image)'
      for (const d of all) {
        expect(d.mode, `#${d.id}: decided in lock mode here`).toBe('lock')
        expect(d.shown, `#${d.id}: decided on ${d.stored} power, shown as ${d.want}`).toContain(` / ${d.want} `)
      }
      return all.map((d) => `#${d.id}: ${d.stored} power -> "${d.shown}"`).join('; ')
    })
    await steps.run('lock-mode-a-failed-card-says-why-as-its-tally-stored-it', 'ui:developer', async () => {
      const all = await failedCardVsTally(page, api)
      if (!all.length) return 'NOT MEASURED: no failed proposal here stored why it failed yet (migration 0185 ships with the ballots image)'
      for (const f of all) expect(f.shown, `#${f.id}: the tally stored ${f.want}`).toBe(f.want)
      return all.map((f) => `#${f.id}: ${f.shown}`).join('; ')
    })
    return
  }
  const dev = await registerDeveloper(api, 'memdev')
  const a = await createAgentApi(api, dev, 'mem-a')
  const ta = await agentToken(api, a)
  await seedSession(context, dev.token)
  await seedVault(context, api, dev, [a])
  await seedActiveAgent(context, a.did)
  const panel = page.locator('[data-testid="membership-panel"]')

  await steps.run('a-fresh-developer-reads-as-not-a-member', 'ui:developer', async () => {
    await openRoute(page, '/senate?tab=governance')
    await expect(panel, 'the panel reads the server').toHaveAttribute('data-state', 'ready', { timeout: 20_000 })
    await expect(page.locator('[data-testid="membership-status"]')).toHaveAttribute('data-member', '0')
    const next = page.locator('[data-testid="membership-next"]')
    await expect(next, 'the one next step, from the server\'s code').toHaveAttribute('data-step', 'post_bond')
    await noSidewaysScroll(page, 'senate, not a member')
    await ownWordsClean(page, ['[data-testid="membership-panel"]', '.sn-stat-card'], 'senate, not a member')
    await a11y(page, 'senate-membership')
    return `not a member; next step ${await next.getAttribute('data-step')}`
  })

  await steps.run('the-owner-allows-a-newborn-agent-to-vote', 'ui:developer', async () => {
    const authz = async () => api.json('GET', `/api/v1/agents/${encodeURIComponent(a.did)}/authz`, { token: dev.token })
    const before = await authz()
    if (before.status !== 200) return `NOT MEASURED: the agent's authority could not be read (${before.status})`
    const notice = page.locator('[data-testid="vote-permission"]')
    if (before.body?.mode !== 'enforce' || (before.body?.effective_permissions || []).includes('gov.vote')) {
      await expect(notice, 'an agent that may vote is told nothing').toHaveCount(0)
      return `NOT MEASURED: this agent may already vote (agent permissions ${before.body?.mode}); the floor says nothing`
    }
    // an image without the additive role rail answers its POST 404 or 405, and the console falls back to the whole-set
    // PUT; a refusal by the rail itself still fails this step through its outcome below
    const RAIL = /POST \/api\/v1\/agents\/[^/]+\/authz\/roles$/
    capture.allow(RAIL, [404, 405], 'no additive role rail on this image: the console falls back to the whole-set PUT')
    await expect(notice, 'a newborn agent is told it may not vote yet').toHaveAttribute('data-state', /^(grantable|time_boxed)$/, { timeout: 20_000 })
    // read without waiting: the notice LEAVES when the press succeeds, and getAttribute would wait 20 s for it
    const stateNow = () => notice.evaluateAll((els) => (els.length ? els[0].getAttribute('data-state') : null))
    const first = String(await stateNow())
    await ownWordsClean(page, ['[data-testid="vote-permission"]'], 'the vote permission notice')
    // which write the press made, as observed on the wire (a console without the rail never asks it)
    const writes: string[] = []
    page.on('response', (r) => {
      const m = r.request().method(), path = new URL(r.url()).pathname
      if (m !== 'GET' && /\/api\/v1\/agents\/[^/]+\/authz(\/roles)?$/.test(path)) writes.push(`${m} ${path.endsWith('/roles') ? 'roles' : 'authz'} ${r.status()}`)
    })
    await page.locator('[data-testid="vote-permission-allow"]').click()
    const pressedAt = Date.now()
    await page.locator('[data-testid="vote-permission-confirm"]').click()
    const errorLine = page.locator('[data-testid="vote-permission-error"]')
    const outcome = async () => {
      const st = await stateNow()
      if (st === null) return 'allowed'
      const err = await errorLine.evaluateAll((els) => (els.length ? (els[0] as HTMLElement).innerText.trim() : ''))
      return err ? `failed: ${err}` : String(st)
    }
    // every way the press can end ends the wait: allowed, sent to My Agents (panel_only), or a failure with its reason
    // the step judges the outcome, not the speed: a busy sandbox took over 20 s once (four calls on a rail-less image)
    await expect.poll(outcome, { timeout: 45_000, message: 'the press settles' }).toMatch(/^(allowed|panel_only|failed: )/)
    const pressSeconds = ((Date.now() - pressedAt) / 1000).toFixed(1)
    expect(await outcome(), 'the press allowed the agent').toBe('allowed')
    const after = await authz()
    expect(after.body?.effective_permissions || [], 'the agent may vote now').toContain('gov.vote')
    const limits = (b: any) => Object.fromEntries((b?.role_grants || []).map((g: any) => [g.role, g.expires_at ?? null]))
    const was = limits(before.body), now = limits(after.body)
    for (const [role, exp] of Object.entries(was)) expect(now[role], `${role} kept its grant and its time limit`).toBe(exp)
    expect(Object.keys(now).sort(), 'one role added, nothing else').toEqual([...Object.keys(was), 'governor'].sort())
    const path = writes.some((w) => /^POST roles 2/.test(w)) ? 'the additive rail'
      : writes.some((w) => /^PUT authz 2/.test(w)) ? `the whole-set PUT${writes.some((w) => /^POST roles 40[45]/.test(w)) ? ' after the rail answered it is not here' : ''}`
      : `a write not observed (${writes.join(', ') || 'none seen'})`
    return `${first} -> allowed through ${path} in ${pressSeconds} s: governor added, ${Object.keys(was).join(', ')} unchanged; nothing voted`
  })

  let ageDays = 0
  await steps.run('the-agent-posts-its-own-bond', 'ui:agent', async () => {
    await expect.poll(async () => Number((await api.json('GET', '/api/v1/teg/balance', { token: ta })).body?.balance || 0),
      { timeout: 45_000, message: 'the genesis grant reached the agent' }).toBeGreaterThan(0)
    const r = await api.json('POST', '/api/v1/agents/reputation-bond/deposit', { token: ta, body: {} })
    expect(r.status, `the bond: ${JSON.stringify(r.body).slice(0, 200)}`).toBeLessThan(300)
    ageDays = Number((await api.json('GET', '/api/v1/membership/stats')).body?.min_bond_age_days ?? 30)
    return `bond ${r.body?.status} (${r.body?.amount} ${r.body?.currency}); the frame counts a bond after ${ageDays} days`
  })

  if (ageDays > 0) {
    steps.notMeasured('a-member-reads-weight-1', 'ui:developer', `this frame counts a bond only after ${ageDays} days`)
    return
  }

  await steps.run('the-developer-reads-as-a-member-with-weight-1', 'ui:developer', async () => {
    // The floor is still open at this very URL from the first step, and a goto to the URL a page already shows only
    // touches the hash: nothing re-reads /membership/me and the panel keeps its first answer. A fresh document reads it.
    await page.goto('about:blank')
    await openRoute(page, '/senate?tab=governance')
    await expect(panel).toHaveAttribute('data-state', 'ready', { timeout: 20_000 })
    await expect(page.locator('[data-testid="membership-status"]'), 'the bond made a member').toHaveAttribute('data-member', '1')
    await expect(page.locator('[data-testid="membership-weight"]')).toContainText(/1[.,]00/)
    await expect(page.locator('[data-testid="sen-power-value"]'), 'the stat card names the weight').toContainText(/1[.,]00/)
    await noSidewaysScroll(page, 'senate, a member')
    await ownWordsClean(page, ['[data-testid="membership-panel"]', '.sn-stat-card'], 'senate, a member')
    const tv = await totalVotersIsACount(page)
    if (tv) expect(tv.ok, `"Total Voters" reads a whole count, not "${tv.text}"`).toBe(true)
    return 'member, weight 1.00 on the panel and the stat card' + (tv ? `; Total Voters "${tv.text}"` : '')
  })

  await steps.run('proposal-cards-name-member-weights-not-points', 'ui:developer', async () => {
    const per = Number((await api.json('GET', '/api/v1/membership/stats')).body?.points_per_weight) || 100
    const c = await cardVsLedger(page, api, per)
    if (!c) return 'NOT MEASURED: no proposal card carries an id yet (an older console) or none has a vote'
    expect(c.shown, `#${c.id}: ${c.ledger} points on the ledger read as the weight ${c.want}`).toContain(c.want)
    return `#${c.id}: ${c.ledger} points on the ledger read "${c.shown}" on the card (weight ${c.want})`
  })

  await steps.run('a-decided-card-shows-the-quorum-it-was-decided-on', 'ui:developer', async () => {
    const all = await decidedCardVsTally(page, api)
    if (!all.length) return 'NOT MEASURED: no decided proposal here stored its numbers yet (migration 0185 ships with the ballots image)'
    for (const d of all) expect(d.shown, `#${d.id}: decided on ${d.stored} (${d.mode}), shown as ${d.want}`).toContain(` / ${d.want} `)
    return all.map((d) => `#${d.id}: ${d.stored} ${d.mode === 'member' ? 'points' : 'power'} -> "${d.shown}"`).join('; ')
  })

  await steps.run('a-failed-card-says-why-as-its-tally-stored-it', 'ui:developer', async () => {
    const all = await failedCardVsTally(page, api)
    if (!all.length) return 'NOT MEASURED: no failed proposal here stored why it failed yet (migration 0185 ships with the ballots image)'
    for (const f of all) expect(f.shown, `#${f.id}: the tally stored ${f.want}`).toBe(f.want)
    return all.map((f) => `#${f.id}: ${f.shown}`).join('; ')
  })

  await steps.run('the-vote-dialog-names-the-member-weight', 'ui:agent', async () => {
    const vote = page.locator('[data-tour="sen-vote"]').first()
    if (!(await vote.count())) return 'NOT MEASURED: no proposal open for voting on this frame'
    await vote.click()
    const weight = page.locator('[data-testid="vote-modal-weight"]')
    await expect(weight, 'the dialog shows the member weight, not a lock power').toContainText(/1[.,]00/)
    await ownWordsClean(page, ['.tp-modal'], 'the vote dialog')
    await noSidewaysScroll(page, 'the vote dialog')
    await page.keyboard.press('Escape')
    const cancel = page.locator('.tp-modal').getByRole('button', { name: /^cancel$/i })
    if (await cancel.count()) await cancel.first().click()
    return 'the dialog names weight 1.00; nothing voted'
  })

  // §MEMBERSHIP fixes (V0551): a developer whose deletion is pending is no member, is told so, and gets the way back
  await steps.run('a-member-whose-deletion-is-pending-is-told-to-cancel-it', 'ui:developer', async () => {
    const me = async () => (await api.json('GET', '/api/v1/membership/me', { token: dev.token })).body || {}
    const before = await me()
    if (!before.is_member) return 'NOT MEASURED: the developer is no member here, so there is no membership to pause'
    const req = await api.json('POST', '/api/v1/account/request-deletion', { token: dev.token,
      body: { password: dev.password, confirmation: 'DELETE MY ACCOUNT', reason: 'fesuite: the membership cooling-off step' } })
    expect(req.status, `the deletion request: ${JSON.stringify(req.body).slice(0, 160)}`).toBeLessThan(300)
    const during = await me()
    if (during.is_member) {
      await api.json('POST', '/api/v1/account/cancel-deletion', { token: dev.token })
      return 'NOT MEASURED: this registry still counts a member whose deletion is pending (the rule ships with V0551); the deletion was cancelled again'
    }
    expect(during.next_step, 'the server names the step').toBe('cancel_deletion')
    await page.goto('about:blank')
    await openRoute(page, '/senate?tab=governance')
    await expect(panel).toHaveAttribute('data-state', 'ready', { timeout: 20_000 })
    await expect(page.locator('[data-testid="membership-status"]'), 'no member while the deletion is pending').toHaveAttribute('data-member', '0')
    await expect(page.locator('[data-testid="membership-next"]')).toHaveAttribute('data-step', 'cancel_deletion')
    await ownWordsClean(page, ['[data-testid="membership-panel"]'], 'the cancel-deletion step')
    await page.locator('[data-testid="membership-cancel-deletion"]').click()
    await page.waitForFunction(() => location.hash.startsWith('#/settings') && location.hash.includes('tab=security'), null, { timeout: 15_000 })
    // the deletion banner on every page has its own "Cancel deletion" button, which only leads here: the button that
    // cancels is Settings' "Cancel deletion → keep my account"
    const undo = page.getByRole('button', { name: /keep my account/i })
    await expect(undo, 'the link leads to the button that cancels').toBeVisible({ timeout: 15_000 })
    await undo.click()
    await expect.poll(async () => (await me()).is_member, { timeout: 20_000, message: 'cancelling makes a member again' }).toBe(true)
    const after = await me()
    expect(after.member_since, 'from the original start date').toBe(before.member_since)
    await page.goto('about:blank')
    await openRoute(page, '/senate?tab=governance')
    await expect(page.locator('[data-testid="membership-status"]'), 'the floor reads a member again').toHaveAttribute('data-member', '1', { timeout: 20_000 })
    return `pending deletion: no member, step cancel_deletion; the link opened Settings > Security; cancelled there: a member again since ${String(after.member_since).slice(0, 19)}`
  })
})

test('commons_pages_read_the_season', async ({ page, context, steps, api }) => {
  test.setTimeout(3 * 60_000)
  const cfg = (await api.json('GET', '/api/v1/public/registry-config')).body || {}
  const dev = await registerDeveloper(api, 'memcommons')
  const a = await createAgentApi(api, dev, 'mem-c')
  await seedSession(context, dev.token)
  await seedVault(context, api, dev, [a])
  await seedActiveAgent(context, a.did)
  if (cfg.commons_enabled !== true) {
    // production's shape: no commons tab, a commons link shows Governance, and nothing asks the commons routes
    await steps.run('the-commons-is-closed-where-its-switch-is-off', 'ui:developer', async () => {
      const asked: string[] = []
      page.on('request', (r) => { if (/\/api\/v1\/commons(\/|$)/.test(new URL(r.url()).pathname)) asked.push(`${r.method()} ${new URL(r.url()).pathname}`) })
      await openRoute(page, '/senate?tab=commons')
      await expect(page.locator('[data-testid="sen-power-value"]'), 'the floor shows Governance').toBeVisible({ timeout: 20_000 })
      expect(await page.locator('[data-testid="commons-panel"]').count(), 'no commons panel').toBe(0)
      expect(await page.locator('[data-testid="sen-tab-commons"]').count(), 'no commons tab').toBe(0)
      expect(asked, 'no commons read').toEqual([])
      return 'commons off: ?tab=commons shows Governance, no commons tab, no commons read'
    })
    return
  }
  // read-only on purpose: the seasons belong to the sandbox's own season tests (agentvault2-09's tester, 33's gate)
  await steps.run('the-commons-tab-shows-the-season-the-server-holds', 'ui:developer', async () => {
    await openRoute(page, '/senate?tab=commons')
    const cp = page.locator('[data-testid="commons-panel"]')
    await expect(cp, 'the commons settles').toHaveAttribute('data-state', /^(ready|empty|failed|disabled)$/, { timeout: 20_000 })
    const st = String(await cp.getAttribute('data-state'))
    expect(st, 'the commons answered and is on').toMatch(/^(ready|empty)$/)
    if (st === 'empty') return 'commons on, no season yet: the tab says so'
    const card = page.locator('[data-testid="commons-season"]')
    const sid = String(await card.getAttribute('data-season'))
    const s = (await api.json('GET', `/api/v1/commons/seasons/${sid}`, { token: dev.token })).body || {}
    const shown = Number((await page.locator('[data-testid="commons-budget"]').innerText()).replace(/[^\d.]/g, ''))
    expect(shown, `season ${sid}: the budget the server holds`).toBe(Number(s.budget))
    const phase = String(await card.getAttribute('data-phase'))
    if (phase === 'open') {
      await expect(page.locator('[data-testid="commons-not-member"]'), 'a fresh developer is told the ballot is for members').toBeVisible()
      // the form refuses a plain-http link before anything is sent, and nothing is submitted here
      await page.locator('[data-testid="commons-submit-open"]').click()
      const form = page.locator('[data-testid="commons-submit"]')
      await expect(form).toBeVisible()
      await page.locator('[data-testid="commons-submit-title"]').fill('fesuite: a form check, never sent')
      await page.locator('[data-testid="commons-ev-ref-0"]').fill('a reference')
      await page.locator('[data-testid="commons-ev-url-0"]').fill('http://example.org/evidence')
      await expect(page.locator('[data-testid="commons-submit-problem"]'), 'https only').toContainText('https://')
      await expect(page.locator('[data-testid="commons-submit-send"]'), 'nothing can be sent').toBeDisabled()
      await page.locator('[data-testid="commons-ev-url-0"]').fill('https://example.org/evidence')
      await expect(page.locator('[data-testid="commons-submit-send"]'), 'a well-formed form could be sent').toBeEnabled()
      await form.getByRole('button', { name: /^cancel$/i }).first().click()
      await expect(form).toHaveCount(0)
    }
    await ownWordsClean(page, ['[data-testid="commons-panel"]'], 'the commons tab')
    await noSidewaysScroll(page, 'the commons tab')
    return `season ${sid} (${phase}), budget ${shown} as the server holds it${phase === 'open' ? '; not a member: told so; the form refused http and sent nothing' : ''}`
  })
})

/** The federated index's own answer, asked at the address this registry publishes (the page asks the same one). */
async function indexBoard(api: { json: (m: string, p: string, o?: any) => Promise<{ status: number; body: any }> }) {
  const cfg = (await api.json('GET', '/api/v1/public/registry-config')).body || {}
  const dir = String(cfg.directory_url || '').replace(/\/+$/, '')
  if (!dir) return null
  const ask = (cancelled: boolean) => api.json('POST', `${dir}/graphql`, { body: { query:
    `{ status { lastCycleAt } registries { name membership { state mode members } commons { state${cancelled ? ' cancelledRecent' : ''} } } }` } })
  let r = await ask(true)
  // an index older than the cancelled count (board1) refuses the whole query for it: ask again without it
  if (r.status === 200 && (r.body?.errors || []).some((e: any) => /cancelledRecent/.test(String(e?.message)))) r = await ask(false)
  if (r.status !== 200 || r.body?.errors?.length) throw new Error(`the index answered ${r.status}: ${JSON.stringify(r.body?.errors || r.body).slice(0, 200)}`)
  return r.body.data as { status: { lastCycleAt: number | null }; registries: { name: string; membership: any; commons: any }[] }
}

test('registry_board_shows_what_the_index_read', async ({ page, context, steps, api }) => {
  test.setTimeout(3 * 60_000)
  const cfg = (await api.json('GET', '/api/v1/public/registry-config')).body || {}
  const dev = await registerDeveloper(api, 'memboard')
  await seedSession(context, dev.token)
  if (cfg.governance_weight_mode !== 'member' && cfg.commons_enabled !== true) {
    // production's shape: the board names an unreleased feature, so it must not open, not even by URL. A console with
    // the board sends the typed URL where the console starts (the router's requiresRegistryAny); one without it shows
    // its not-found page. The step reports where the URL landed and never guesses which console it met.
    await steps.run('the-board-is-closed-where-its-switches-are-off', 'ui:developer', async () => {
      const asked: string[] = []
      page.on('request', (r) => { if (/\/directory\/graphql$/.test(new URL(r.url()).pathname)) asked.push(r.url()) })
      await openRoute(page, '/registries')
      await page.waitForFunction(() => !location.hash.startsWith('#/registries'), null, { timeout: 10_000 }).catch(() => {})
      const hash = await page.evaluate(() => location.hash)
      expect(await page.locator('[data-testid="registry-board"]').count(), `nothing of the board (the URL is at ${hash})`).toBe(0)
      expect(asked, 'the index is not asked').toEqual([])
      if (hash.startsWith('#/registries')) return `NOT MEASURED: the URL stayed at ${hash} with no board shown (a console without the board shows its not-found page there)`
      return `both switches off: /registries landed on ${hash}, nothing of the board shown, the index not asked`
    })
    return
  }

  await steps.run('the-board-lists-every-registry-with-the-figures-the-index-read', 'ui:developer', async () => {
    let idx = await indexBoard(api)
    if (!idx) return 'NOT MEASURED: this registry names no federated index'
    await openRoute(page, '/registries')
    const board = page.locator('[data-testid="registry-board"]')
    if (!(await board.count())) return 'NOT MEASURED: this console has no registry board (it ships with V0551)'
    await expect(board, 'the board settles').toHaveAttribute('data-state', /^(ready|failed|no-index|off)$/, { timeout: 30_000 })
    // a cycle of the index that ended while the page read it would make two honest answers differ: read again
    const again = await indexBoard(api)
    if (again && again.status.lastCycleAt !== idx.status.lastCycleAt) {
      idx = again
      await page.goto('about:blank')
      await openRoute(page, '/registries')
      await expect(board).toHaveAttribute('data-state', /^(ready|failed|no-index|off)$/, { timeout: 30_000 })
    }
    expect(await board.getAttribute('data-state'), 'the board read the index').toBe('ready')
    const names = await page.locator('[data-testid="board-row"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-name')))
    const knowsCancelled = await boardKnowsCancelled(page)
    let cancelledUnshown = 0
    expect([...names].sort(), 'every registry the index reads is listed, and no other').toEqual(idx.registries.map((r) => r.name).sort())
    let ok = 0
    for (const r of idx.registries) {
      const row = page.locator(`[data-testid="board-row"][data-name="${r.name.replace(/"/g, '\\"')}"]`)
      const members = row.locator('[data-testid="board-members"]')
      const m = r.membership
      const want = !m ? 'unchecked' : m.state === 'absent' ? 'absent' : m.state === 'ok' ? 'ok' : null
      if (want) expect(await members.getAttribute('data-kind'), `${r.name}: the members figure as the index read it`).toBe(want)
      if (m?.state === 'ok') {
        ok += 1
        await expect(members.locator('.rb-big'), `${r.name}: the member count`).toHaveText(new Intl.NumberFormat('en').format(m.members))
        await expect(members, `${r.name}: what decides its votes`).toContainText(m.mode === 'member' ? /one per member/i : /locked units/i)
      }
      const c = r.commons
      const cwant = !c ? 'unchecked' : c.state === 'absent' ? 'absent' : null
      if (cwant) expect(await row.locator('[data-testid="board-commons"]').getAttribute('data-kind'), `${r.name}: the commons as the index read it`).toBe(cwant)
      // the cancelled seasons the index left out are counted on the page, never silently gone
      const cancelledLine = row.locator('[data-testid="board-commons-cancelled"]')
      if (c?.state === 'ok' && Number(c.cancelledRecent) > 0) {
        if (knowsCancelled) await expect(cancelledLine, `${r.name}: the cancelled seasons counted`).toContainText(new Intl.NumberFormat('en').format(Number(c.cancelledRecent)))
        else cancelledUnshown += 1
      } else if (c?.state === 'ok') {
        expect(await cancelledLine.count(), `${r.name}: no cancelled line where none were cancelled`).toBe(0)
      }
    }
    await ownWordsClean(page, ['[data-testid="registry-board"]'], 'the registry board')
    await noSidewaysScroll(page, 'the registry board')
    return `${names.length} registries as the index read them; ${ok} with membership figures`
      + (cancelledUnshown ? `; NOT MEASURED for ${cancelledUnshown}: this console does not show the cancelled-season count (it ships with V0552)` : '')
  })
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 393, height: 852 } })

  test('membership_sheet_on_the_phone @phone-only', async ({ page, context, steps, api }) => {
    test.setTimeout(3 * 60_000)
    if (!(await memberMode(api))) {
      steps.notMeasured('membership-sheet', 'ui:developer', 'this frame runs governance in lock mode (governance_weight_mode is not member)')
      return
    }
    const dev = await registerDeveloper(api, 'memphone')
    const a = await createAgentApi(api, dev, 'mem-p')
    await seedSession(context, dev.token)
    await seedVault(context, api, dev, [a])
    await seedActiveAgent(context, a.did)

    await steps.run('the-senate-sheet-shows-the-membership', 'ui:developer', async () => {
      await openRoute(page, '/pocket/home?sheet=senate')
      const panel = page.locator('[data-testid="membership-panel"]')
      await expect(panel, 'the compact panel in the sheet').toHaveAttribute('data-state', 'ready', { timeout: 20_000 })
      await expect(page.locator('[data-testid="membership-status"]')).toHaveAttribute('data-member', '0')
      await noSidewaysScroll(page, 'pocket senate sheet')
      await ownWordsClean(page, ['[data-testid="membership-panel"]'], 'pocket senate sheet')
      const box = await panel.boundingBox()
      expect(box && box.width <= 393, `the panel fits a 393 px screen (${box?.width}px)`).toBe(true)
      const notice = page.locator('[data-testid="vote-permission"]')
      if (await notice.count()) {
        const nb = await notice.boundingBox()
        expect(nb && nb.width <= 393, `the vote permission notice fits a 393 px screen (${nb?.width}px)`).toBe(true)
        await ownWordsClean(page, ['[data-testid="vote-permission"]'], 'pocket vote permission notice')
      }
      return `compact panel, ${Math.round(box?.width || 0)}px wide${(await notice.count()) ? '; the vote permission notice fits' : ''}`
    })

    await steps.run('the-registry-board-fits-a-phone', 'ui:developer', async () => {
      await openRoute(page, '/registries')
      const board = page.locator('[data-testid="registry-board"]')
      if (!(await board.count())) return 'NOT MEASURED: this console has no registry board (it ships with V0551)'
      await expect(board).toHaveAttribute('data-state', /^(ready|failed|no-index|off)$/, { timeout: 30_000 })
      await noSidewaysScroll(page, 'the registry board on a phone')
      await ownWordsClean(page, ['[data-testid="registry-board"]'], 'the registry board on a phone')
      const rows = await page.locator('[data-testid="board-row"]').count()
      return `board ${await board.getAttribute('data-state')}, ${rows} registries, no sideways scroll`
    })
  })
})
