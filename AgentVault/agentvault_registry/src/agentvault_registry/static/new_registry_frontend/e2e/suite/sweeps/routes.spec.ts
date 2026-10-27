/**
 * Every page, as three people see it (§FESUITE): a visitor, a member with an agent, and the frame's admin. The pages
 * come from the console's own router, not from a list. Each page is a row: where it landed (never NotFound, never a
 * bounce to the login form for someone allowed in), what it said (no console error, no refused call), what it showed
 * (no raw translation key, no sideways scroll) and whether axe finds anything serious. A sweep never clicks: it reads.
 */
import fs from 'node:fs'
import { test, expect } from '../support/fixtures'
import type { Page } from '@playwright/test'
import type { Steps, Tier } from '../support/steps'
import type { Capture } from '../support/capture'
import { createAgentApi, registerDeveloper, seedActiveAgent, seedSession } from '../support/accounts'
import { adminCredentials } from '../support/env'
import { navigationSince, openRoute, pageNow, recordNavigation, recordToasts, routerArrives, toastsSince } from '../support/ui'
import { EXPECTED_REFUSALS, NOT_DRIVEN, actingAgent, appRoutes, rawKeys, resolvedRoute, sideScroll, type RouteInfo } from '../support/pages'

type Audience = 'visitor' | 'member' | 'admin'

function isAdminRoute(r: RouteInfo): boolean {
  const m = r.meta
  return m.requiresRole === 'admin' || !!m.requiresAdminFlag || !!m.requiresMainframe || /^\/admin\//.test(r.path)
}

function audienceOf(r: RouteInfo): Audience {
  if (isAdminRoute(r)) return 'admin'
  return r.meta.requiresAuth === true ? 'member' : 'visitor'
}

async function sweep(page: Page, steps: Steps, capture: Capture, a11y: (p: Page, l: string) => Promise<unknown[]>,
  audience: Audience, tier: Tier): Promise<void> {
  await openRoute(page, audience === 'visitor' ? '/login' : '/mission-control')
  const all = await appRoutes(page)
  const mine = all.filter((r) => audienceOf(r) === audience)
  for (const r of all.filter((x) => audienceOf(x) === audience && NOT_DRIVEN[x.path])) {
    steps.notMeasured(`page${r.path}`, tier, `not opened headless: ${NOT_DRIVEN[r.path]}`)
  }
  for (const r of mine.filter((x) => !NOT_DRIVEN[x.path])) {
    for (const e of EXPECTED_REFUSALS.filter((x) => x.route.test(r.path))) capture.allow(e.call, e.status, e.reason)
    await steps.check(`page${r.path}`, tier, async () => {
      const cp = capture.checkpoint()
      const t0 = audience === 'admin' ? await pageNow(page) : 0
      let landed = await openRoute(page, r.path)
      // an admin page not reached yet may still be on its way (a walk carried out after the first navigation): ask the
      // router, bounded, before calling it a refusal
      if (audience === 'admin' && landed.split('?')[0] !== r.path) landed = (await routerArrives(page, r.path, 10_000)) || landed
      const resolved = await resolvedRoute(page)
      const problems: string[] = []
      if (/notfound|not-found|404/i.test(resolved.name)) problems.push(`landed on NotFound (${resolved.path})`)
      if (audience !== 'visitor' && landed.startsWith('/login')) problems.push('bounced to the login form')
      // worker C: the admin may open every admin page; landing elsewhere is a refusal unless the route declares where
      // it sends a frame that lacks it (a mainframe-only page, a page behind a registry flag)
      if (audience === 'admin' && landed.split('?')[0] !== r.path) {
        const declared = !!r.meta.requiresMainframe || !!r.meta.requiresRegistryFlag || !!r.meta.registryFlagRedirect
        const said = declared ? [] : await toastsSince(page, t0)
        // what moved it (kept across reloads; the whole log goes to the output folder)
        const moved = declared ? [] : await navigationSince(page, t0)
        if (moved.length) fs.writeFileSync(test.info().outputPath(`navigation${r.path.replace(/\W+/g, '-')}.txt`), moved.join('\n') + '\n')
        if (!declared) problems.push(`the admin was refused: landed on ${landed}${said.length ? ` (the console said: ${said.join(' | ')})` : ''}`
          + `${moved.length ? `; the route moved: ${moved.filter((x) => !/ auth: /.test(x)).slice(-6).join(' | ')}` : ''}`)
      }
      const keys = await rawKeys(page)
      if (keys.length) problems.push(`raw keys: ${keys.slice(0, 5).join(', ')}`)
      const side = await sideScroll(page)
      if (side > 1) problems.push(`scrolls sideways by ${side}px`)
      const noise = capture.since(cp)
      if (noise.length) problems.push(...noise.slice(0, 6))
      const label = r.path.replace(/^\//, '').replace(/\W+/g, '-') || 'root'
      await a11y(page, `${audience}-${label}`)
      if (problems.length) throw new Error(problems.join(' | '))
      return landed === r.path ? 'landed' : `landed on ${landed} (a redirect the route declares)`
    })
  }
}

test('route_sweep_visitor', async ({ page, steps, capture, a11y }) => {
  test.setTimeout(30 * 60_000)
  await sweep(page, steps, capture, a11y, 'visitor', 'ui:public')
  steps.assertChecks()
})

test('route_sweep_member', async ({ page, context, steps, capture, a11y, api }) => {
  test.setTimeout(45 * 60_000)
  const dev = await registerDeveloper(api, 'sweepmember')
  const agent = await createAgentApi(api, dev, 'route-sweep')
  await seedSession(context, dev.token)
  await seedActiveAgent(context, agent.did)
  await steps.run('member-acts-as-its-agent', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    await expect.poll(() => actingAgent(page), { timeout: 30_000 }).toBe(agent.did)
    return 'the console acts as the member\'s own agent'
  })
  await sweep(page, steps, capture, a11y, 'member', 'ui:developer')
  steps.assertChecks()
})

test('route_sweep_admin', async ({ page, context, steps, capture, a11y, api }) => {
  test.setTimeout(45 * 60_000)
  const admin = adminCredentials()
  if (!admin) {
    steps.notMeasured('admin-pages', 'ui:admin', 'no admin credentials were given to this run (FESUITE_ADMIN_EMAIL)')
    test.skip(true, 'no admin credentials')
  }
  // The frame admin is shared (the MCP tester signs in as it): the suite logs in over the API and never signs out,
  // because a sign-out revokes the account's tokens everywhere.
  const token = await api.login(admin!.email, admin!.password)
  await seedSession(context, token)
  await recordToasts(page)
  await recordNavigation(page)
  await sweep(page, steps, capture, a11y, 'admin', 'ui:admin')
  steps.assertChecks()
})
