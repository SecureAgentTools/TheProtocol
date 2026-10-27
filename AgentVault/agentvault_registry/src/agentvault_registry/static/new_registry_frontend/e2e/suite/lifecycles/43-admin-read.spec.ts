/**
 * The frame admin, reading (§FESUITE): a throwaway developer with an agent, a key and a ticket is set up over the API;
 * the admin finds them by search on Developers, opens their drawer (and the same drawer by its deep link), finds the
 * agent on Agents, sees the ticket on the support desk, and looks at the MCP tester and the audit log. Every number on
 * screen is read back from the admin API. The admin is SHARED (the MCP tester signs in as it): the suite logs in over
 * the API, never signs out, never changes it, and never presses an action: typing in a search box, opening a drawer,
 * switching its tabs and closing it are the only things it does.
 */
import fs from 'node:fs'
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { adminCredentials, uniqueName } from '../support/env'
import { navigationSince, openRoute, pageNow, pinia, recordNavigation, recordToasts, routerArrives, settle, toastsSince } from '../support/ui'
import { mainText } from '../support/hygiene'

const listOf = (b: any): any[] => (Array.isArray(b) ? b : b?.items || b?.developers || b?.agents || b?.tickets || [])

test('admin_reads_a_developer', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(6 * 60_000)
  const admin = adminCredentials()
  if (!admin) {
    steps.notMeasured('admin-read', 'ui:admin', 'no admin credentials were given to this run (FESUITE_ADMIN_EMAIL)')
    test.skip(true, 'no admin credentials')
  }
  const dev = await registerDeveloper(api, 'adminread')
  const agent = await createAgentApi(api, dev, 'admin-read')
  const keyName = uniqueName('adkey')
  await api.json('POST', '/api/v1/auth/api-keys', { token: dev.token, body: { key_name: keyName } })
  const subject = uniqueName('adticket')
  await api.json('POST', '/api/v1/support/tickets', { token: dev.token, body: { subject, message: 'for the admin read lifecycle' } })
  const me = (await api.json('GET', '/api/v1/developers/me', { token: dev.token })).body || {}
  const devId = String(me.id ?? me.developer_id ?? '')
  expect(devId, 'the throwaway developer has an id').not.toBe('')

  const token = await api.login(admin!.email, admin!.password)
  await seedSession(context, token)
  const detail = (await api.json('GET', `/api/v1/admin/developers/${devId}`, { token })).body || {}

  // The console knows it is an admin once the restored session's profile has loaded (the auth store's user).
  const adminKnown = () => pinia<boolean>(page, 'auth', (st: any) => !!st.user && !!st.isAdmin)

  await steps.check('admin-route-right-after-load', 'ui:admin', async () => {
    // A person opens the console and goes straight to an admin page. The walk is a URL change made while the console's
    // first navigation still waits on the session restore (2.5-2.9 s on sbx-alpha), which vue-router alone drops and
    // overwrites (found 2026-10-02 with the route recorder; the console replays it since V0540, router/missedFirstNavigation.ts).
    await recordToasts(page)
    await recordNavigation(page)
    const tLoad = await pageNow(page)
    await openRoute(page, '/mission-control')
    const known = await adminKnown()
    const t0 = await pageNow(page)
    await openRoute(page, '/admin/developers')
    // the outcome is where the ROUTER lands, waited for: a walk carried out after a slow session restore arrives late, and
    // the address bar can show the walk's hash before the router takes it (a URL read could pass a walk that was dropped)
    const route = await routerArrives(page, '/admin/developers')
    // the refusal's own toast names the guard (role, admin area, mainframe); the route alone cannot say which
    const said = route === '/admin/developers' ? [] : await toastsSince(page, t0)
    // what moved it: every route change since the load, kept across reloads (the whole log goes to the output folder)
    const moved = await navigationSince(page, tLoad)
    if (route !== '/admin/developers' && moved.length) fs.writeFileSync(test.info().outputPath('navigation-after-load.txt'), moved.join('\n') + '\n')
    expect(route, `an in-app walk to an admin page right after a load (the store knew the admin: ${known}`
      + `${said.length ? `; the console said: ${said.join(' | ')}` : '; no toast'}`
      + `${moved.length ? `; the route moved: ${moved.filter((x) => !/ auth: /.test(x)).slice(-8).join(' | ')}` : ''})`).toBe('/admin/developers')
    // a pass says HOW it arrived: a walk made while the first navigation still waited arrives only through the replay
    const at = (re: RegExp) => { const x = moved.find((m) => re.test(m)); return x ? Number(x.match(/^\+(\d+)ms/)?.[1]) : NaN }
    const walkAt = at(/ hashchange: .*-> #\/admin\/developers/), firstDone = at(/ navigated: \/ -> /)
    const how = Number.isNaN(walkAt) || Number.isNaN(firstDone) ? 'how it arrived was not recorded'
      : walkAt < firstDone ? `the walk (+${walkAt} ms) came while the first navigation waited (done +${firstDone} ms): carried out after it`
      : `the walk (+${walkAt} ms) came after the first navigation (done +${firstDone} ms): an ordinary navigation`
    return `landed on ${route}; ${how}`
  })

  await steps.run('admin-home', 'ui:admin', async () => {
    const landed = await openRoute(page, '/mission-control')
    expect(landed).toBe('/mission-control')
    const t0 = Date.now()
    await expect.poll(adminKnown, { message: 'the console comes to know the admin', timeout: 30_000 }).toBe(true)
    const knownAfter = Date.now() - t0
    await expect.poll(async () => (await mainText(page)).length, { message: 'the dashboard is not blank', timeout: 30_000 }).toBeGreaterThan(80)
    await a11y(page, 'admin-read-home')
    return `mission control renders for the admin (the store knew the admin ${knownAfter} ms after the route settled)`
  })

  /** Open an admin route; when the console lands elsewhere, say what it showed and what it believed. */
  const openAdmin = async (route: string) => {
    const toasts = new Set<string>()
    const seen = setInterval(() => {
      void page.locator('[data-testid="toast"]').allInnerTexts().then((xs) => xs.forEach((x) => toasts.add(x.replace(/\s+/g, ' ').slice(0, 100)))).catch(() => {})
    }, 150)
    const landed = await openRoute(page, route).finally(() => clearInterval(seen))
    if (landed !== route) {
      const st = await pinia<string>(page, 'auth', (a: any) => `${a.userRole ?? 'null'}/${a.isAdmin ? 'admin' : 'not-admin'}/${a.user ? 'user' : 'no-user'}`)
      throw new Error(`${route} landed on ${landed}; store ${st}; toasts: ${[...toasts].join(' || ') || 'none'}`)
    }
    return landed
  }

  await steps.run('find-the-developer-by-search', 'ui:admin', async () => {
    await openAdmin('/admin/developers')
    await page.locator('.ad-search').fill(dev.email)
    const row = page.locator('tr.ad-row').filter({ hasText: dev.name })
    await expect(row, 'the search finds the developer').toHaveCount(1)
    const r = await api.json('GET', `/api/v1/admin/developers?search=${encodeURIComponent(dev.email)}`, { token })
    expect(listOf(r.body).length, 'the API finds the same one').toBe(1)
    await a11y(page, 'admin-read-developers')
    return 'one row on the page, one in the API'
  })

  await steps.run('developer-drawer', 'ui:admin', async () => {
    await page.locator('tr.ad-row').filter({ hasText: dev.name }).locator('td').first().click()
    const drawer = page.locator('aside.ad-drawer')
    await expect(drawer.locator('.ad-drawer-title')).toHaveText(dev.name)
    await settle(page)
    const agentsN = (detail.agents || []).length
    const keysN = (detail.api_keys || []).length
    expect(agentsN, 'the API holds the agent').toBe(1)
    expect(keysN, 'the API holds the key').toBe(1)
    await expect(drawer.locator('.ad-drawer-tab').filter({ hasText: /agents/i }).locator('.ad-count')).toHaveText(String(agentsN))
    await expect(drawer.locator('.ad-drawer-tab').filter({ hasText: /api keys|keys/i }).locator('.ad-count')).toHaveText(String(keysN))
    await drawer.locator('.ad-drawer-tab').filter({ hasText: /agents/i }).click()
    await expect(drawer.getByText(agent.did.slice(-10)).first(), 'the agents tab names the agent by the part of its DID that differs').toBeVisible()
    await a11y(page, 'admin-read-drawer')
    await drawer.locator('.ad-drawer-close').click()
    await expect(drawer).toHaveCount(0)
    return `the drawer's counts (${agentsN} agent, ${keysN} key) match the API`
  })

  await steps.run('developer-by-deep-link', 'ui:admin', async () => {
    await openRoute(page, `/admin/developers?id=${encodeURIComponent(devId)}`)
    await expect(page.locator('aside.ad-drawer .ad-drawer-title')).toHaveText(dev.name)
    await page.locator('aside.ad-drawer .ad-drawer-close').click()
    return 'the deep link opens the same drawer'
  })

  await steps.run('agent-on-admin-agents', 'ui:admin', async () => {
    await openAdmin('/admin/agents')
    await page.locator('.aa-search').fill(agent.did)
    await expect(page.locator('tr.aa-row').filter({ hasText: agent.did.slice(-12) }), 'the search finds the agent').toHaveCount(1)
    const r = await api.json('GET', `/api/v1/admin/agents?search=${encodeURIComponent(agent.did)}`, { token })
    expect(listOf(r.body).some((x: any) => x.did === agent.did), 'the API finds it').toBe(true)
    await a11y(page, 'admin-read-agents')
    return 'found on the page and in the API'
  })

  await steps.run('ticket-on-the-desk', 'ui:admin', async () => {
    expect(await openRoute(page, '/support')).toBe('/support')
    const r = await api.json('GET', '/api/v1/admin/support/tickets?limit=51', { token })
    expect(listOf(r.body).some((x: any) => x.subject === subject), 'the admin API lists the ticket').toBe(true)
    await expect(page.getByText(subject).first(), 'the desk shows the newest ticket').toBeVisible()
    await a11y(page, 'admin-read-desk')
    return 'the desk and the admin API both hold it'
  })

  await steps.run('mcp-tester-and-audit-log-render', 'ui:admin', async () => {
    for (const route of ['/admin/mcp-tester', '/admin/audit-logs']) {
      await openAdmin(route)
      await expect.poll(async () => (await mainText(page)).length, { message: `${route} is not blank`, timeout: 30_000 }).toBeGreaterThan(80)
      await a11y(page, `admin-read-${route.split('/').pop()}`)
    }
    return 'both render (read only, nothing pressed)'
  })
  steps.assertChecks()
})
