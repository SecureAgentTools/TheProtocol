/**
 * The guided tours (§FESUITE; §TOURTRUTH's lesson: drive the tour engine, never re-implement it). A developer with an
 * acting agent opens the Tutorials hub, starts the first tour from its card, then every tour a member may take is walked
 * through the store the overlay itself uses: each step is entered the way the engine enters it, and a step whose anchor
 * the page never showed (and which is not marked optional) is a dangling promise. Tours that lead into the WebGL views
 * the suite never drives, and the admin-locked operator series, are named as not measured.
 */
import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedActiveAgent, seedSession, seedVault } from '../support/accounts'
import { openRoute, pinia, settle } from '../support/ui'
import { EXPECTED_REFUSALS, NOT_DRIVEN } from '../support/pages'

interface TourFacts { id: string; routes: string[]; admin: boolean; registryFlag: string }

/** The hub's own reading of a switch it has not been told (TutorialHub.vue FLAG_DEFAULT_ON): closed unless said on,
 *  except staking, which is on unless said off. */
const FLAG_DEFAULT_ON: Record<string, boolean> = { fiat_onramp_enabled: false, staking_enabled: true, cockpit_desk_enabled: false }

function tourFiles(): TourFacts[] {
  const dir = path.resolve(process.cwd(), 'src/views/Tutorials/guided/tours')
  return fs.readdirSync(dir).filter((f) => f.endsWith('.tour.ts')).map((f) => {
    const src = fs.readFileSync(path.join(dir, f), 'utf8')
    const id = /\bid:\s*'([^']+)'/.exec(src)?.[1] || f
    const routes = [...src.matchAll(/\broute:\s*'([^']+)'/g)].map((m) => m[1])
    const admin = /\brequireAdmin:\s*true/.test(src) || /\brequireFlag:\s*'/.test(src)
    const registryFlag = /\brequiresRegistryFlag:\s*'([^']+)'/.exec(src)?.[1] || ''
    return { id, routes, admin, registryFlag }
  })
}

const webgl = (route: string) => Object.keys(NOT_DRIVEN).some((r) => route === r || route.startsWith(r + '?') || route.startsWith(r + '/'))

test('guided_tours_walk_clean', async ({ page, context, steps, api, capture }) => {
  test.setTimeout(10 * 60_000)
  const dev = await registerDeveloper(api, 'tourdev')
  const a = await createAgentApi(api, dev, 'tour-a')
  await seedSession(context, dev.token)
  await seedVault(context, api, dev, [a])
  await seedActiveAgent(context, a.did)
  // a tour visits pages that read optional resources; the page-clean row judges each of them on its own run
  capture.allowConsole(/\[guidedTour\]/, 'the tour engine reports a step it could not anchor; the step rows judge it')

  const all = tourFiles()
  const cfg: Record<string, unknown> = (await api.json('GET', '/api/v1/public/registry-config')).body || {}
  const offered = (t: TourFacts) => !t.registryFlag || (cfg[t.registryFlag] === undefined ? FLAG_DEFAULT_ON[t.registryFlag] === true : cfg[t.registryFlag] === true)
  for (const t of all.filter((t) => !offered(t))) {
    steps.notMeasured(`tour-${t.id}`, 'ui:developer', `not offered on this registry: ${t.registryFlag} is off (the hub shows no card for it)`)
  }
  const runnable = all.filter((t) => !t.admin && !t.routes.some(webgl) && offered(t))
  // the tours visit pages whose deliberate refusals the route sweeps already name (the solvency card's 404 on /agora where
  // the card is off); the same allowance here, scoped to the pages these tours open
  for (const e of EXPECTED_REFUSALS.filter((x) => runnable.some((t) => t.routes.some((r) => x.route.test(r))))) {
    capture.allow(e.call, e.status, e.reason)
  }
  for (const t of all.filter((t) => t.admin)) steps.notMeasured(`tour-${t.id}`, 'ui:developer', 'an operator-series tour: locked for a member (the hub shows it locked)')
  for (const t of all.filter((t) => !t.admin && t.routes.some(webgl))) {
    steps.notMeasured(`tour-${t.id}`, 'ui:developer', `leads into a WebGL view the suite never drives headless (${t.routes.filter(webgl).join(', ')})`)
  }

  await steps.run('the-hub-starts-a-tour', 'ui:developer', async () => {
    await openRoute(page, '/tutorials')
    const cards = page.locator('.th-tour-card:not([disabled])')
    expect(await cards.count(), 'the hub offers tours').toBeGreaterThan(5)
    await cards.first().click()
    await expect.poll(() => pinia(page, 'guidedTour', (s: any) => !!s.isActive), { message: 'the card starts its tour' }).toBe(true)
    await pinia(page, 'guidedTour', (s: any) => s.end())
    return `${await cards.count()} tour card(s); the first one starts`
  })

  for (const t of runnable) {
    const ok = await steps.check(`tour-${t.id}`, 'ui:developer', async () => {
      await openRoute(page, '/tutorials')
      await pinia(page, 'guidedTour', (s: any, id: string) => s.start(id), t.id)
      const dangling: string[] = []
      const late: string[] = []
      let walked = 0
      for (let i = 0; i < 80; i++) {
        // wait until the engine has entered the step (it navigates, then hunts for the anchor)
        await expect.poll(() => pinia(page, 'guidedTour', (s: any) => !s.isPreparing), { timeout: 20_000 }).toBe(true)
        const st = await pinia(page, 'guidedTour', (s: any) => ({
          active: !!s.isActive, index: s.stepIndex as number, id: s.currentStep?.id || '', optional: !!s.currentStep?.optional,
          anchor: s.currentStep?.anchor || '', missing: !!s.anchorMissing, needsAgent: !!s.needsAgent,
          cta: (s.currentStep?.cta?.do as string) || '',
        }))
        if (!st.active) break
        walked += 1
        if (st.needsAgent) dangling.push(`${st.id}: needs an agent although one acts`)
        else if (st.missing && !st.optional) {
          // The engine blocks only briefly (1.2-2.5 s), shows the step's text, and keeps looking for the step's whole
          // budget, snapping the spotlight on when the element arrives; a person reads meanwhile. Late is named,
          // never-anchored is dangling.
          const t0 = Date.now()
          const arrived = await expect.poll(() => pinia(page, 'guidedTour', (s: any, idx: number) => s.stepIndex === idx && !s.anchorMissing, st.index),
            { timeout: 10_000 }).toBe(true).then(() => true, () => false)
          if (arrived) late.push(`${st.id} (+${Date.now() - t0} ms)`)
          else dangling.push(`${st.id} (anchor ${st.anchor})`)
        }
        // forward the way the coach card's own button goes (GuidedTour.vue onCta): a call to action presses the anchored
        // control (opens the form, switches the tab) before the next stop, which lives behind it
        if (st.cta === 'click-anchor') await pinia(page, 'guidedTour', (s: any) => s.clickAnchorThenNext())
        else if (st.cta === 'open-runner') break  // the step leaves the tour for a track runner: the walk ends here
        else await pinia(page, 'guidedTour', (s: any) => s.next())
      }
      await pinia(page, 'guidedTour', (s: any) => s.isActive && s.end())
      await settle(page)
      expect(dangling, `tour ${t.id}: steps the page never anchored`).toEqual([])
      return `${walked} step(s), every anchor found${late.length ? `; late: ${late.join(', ')}` : ''}`
    })
    if (!ok) continue
  }
  steps.assertChecks()
})
