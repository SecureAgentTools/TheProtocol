/**
 * Engage in Agent Discovery, followed to its outcome, and the Firms surfaces around it (V0658 (v); the maintainer's
 * review on EU after V0657, sessions' room seq 2181: "engage button on agent discovery needs a test written probably").
 * Until this file nothing drove Engage in a browser; only unit tests touched it.
 *
 * discovery_engage_to_its_outcome: a firm whose intake agent is a provider with a priced card that serves nothing (its
 * address is under .invalid, never dialled anywhere real). The firm's Engage in the Firms strip opens the intake agent;
 * the agent's own Engage prices the call (read back from the quote), the buy authorizes it, the call fails, the
 * authorization is released, and the page says nothing was charged. Read back: the buyer's units are where they were
 * and its payment authorization for the provider reads released. The money path ends where it began (Δ untouched).
 *
 * firms_surfaces_at_desktop_width and firms_surfaces_on_a_phone: the hosted logo in the strip, the firm's own count
 * beside its agents' own work, the filter that hides the strip (remembered in the address and in this browser), the
 * bounty door, which stays in the shell it is pressed in (session-lead's decision, the sessions' room seq 2389: in the
 * desktop console's Discovery the Guild board, on a phone too) and follows the landing decision only where no shell is
 * mounted (the public Explore page: on a phone, Pocket's sheet), the firm reserved on all of them, the sidebar's Firms
 * entry, and #/firms side by side at desktop width, stacked on a phone.
 *
 * Every firm made here is taken apart at the end (no intake, not listed, deleted): the strip lists 12 firms, and a run
 * must not crowd the next one out. Where this frame's strip or open-books list already holds more firms than it shows,
 * the step that needs ours there is recorded as not measured, with the count.
 */
import crypto from 'node:crypto'
import type { Page } from '@playwright/test'
import { test, expect, type Api } from '../support/fixtures'
import { agentBalance, agentToken, createAgentApi, ledger, passReconsent, registerDeveloper, seedSession, type CreatedAgent, type Developer } from '../support/accounts'
import { bondFrom, partyWith, seedVault, stillFrame, waitActing } from '../support/commerce'
import { PREFIX, uniqueName } from '../support/env'
import { sideScroll } from '../support/pages'
import { currentRoute, firstOf, openRoute, routerArrives, settle } from '../support/ui'

const PRICE = 0.5
/** A real 1x1 PNG: the registry sniffs PNG bytes, and a browser must decode it for the logo to count as shown. */
const PNG_1PX = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64')
/** What the Firms strip reads (FirmsLane.vue asks for 12). */
const STRIP_LIMIT = 12

interface Firm { id: string; slug: string; name: string }

/** A provider agent with a PRICED card (legacy pricing, the frame's own unit) that serves nothing: its address is under
 *  .invalid, so a call to it fails before anything is delivered. */
async function pricedAgent(api: Api, dev: Developer, hint: string): Promise<CreatedAgent & { name: string }> {
  const bt = await api.json('POST', '/api/v1/onboard/bootstrap/request-token', { token: dev.token, body: { agent_type_hint: hint } })
  const bootstrap = bt.body?.bootstrap_token
  if (bt.status !== 200 || !bootstrap) throw new Error(`bootstrap token answered ${bt.status}`)
  const name = `${PREFIX}-${hint}-${crypto.randomBytes(3).toString('hex')}`
  const host = `https://${name}.invalid`
  const card = {
    protocolVersion: '1.0', agentVersion: '1.0.0', humanReadableId: name, name,
    description: 'A priced agent the console suite made to be engaged; it serves nothing, so a call to it fails.',
    url: host, preferredTransport: 'JSONRPC',
    supportedInterfaces: [{ url: host, protocolBinding: 'JSONRPC', protocolVersion: '1.0' }],
    securitySchemes: { agent_jwt: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' } },
    security: [{ agent_jwt: [] }],
    provider: { name: PREFIX }, capabilities: { streaming: false },
    pricing: { payment_required: true, base_rate: PRICE, pricing_model: 'per_request' },
  }
  const r = await api.json('POST', '/api/v1/onboard/create_agent', {
    headers: { 'Bootstrap-Token': bootstrap },
    body: { agent_did_method: 'theprotocol', agent_card: card },
  })
  if (!r.body?.agent_did || !r.body?.client_secret) throw new Error(`create_agent answered ${r.status}`)
  ledger('agent', { did: r.body.agent_did, owner: dev.email, via: 'api' })
  return { did: r.body.agent_did, clientId: r.body.client_id, clientSecret: r.body.client_secret, name }
}

/** A firm of `dev` with `agentDid` assigned and named its intake agent (so the strip lists it), optionally listed, with
 *  open books, and with a logo this registry hosts. */
async function makeFirm(api: Api, dev: Developer, agentDid: string,
  opts: { listed?: boolean; transparent?: boolean; logo?: boolean } = {}): Promise<Firm> {
  const name = uniqueName('firm')
  const o = await api.json('POST', '/api/v1/organizations', { token: dev.token, body: { name, description: 'made by the console lifecycle suite' } })
  if (o.status >= 300 || !o.body?.id) throw new Error(`organization create answered ${o.status}`)
  const firm = { id: String(o.body.id), slug: String(o.body.slug), name }
  ledger('organization', { id: firm.id, name, owner: dev.email })
  const a = await api.json('POST', `/api/v1/organizations/${firm.id}/agents/${encodeURIComponent(agentDid)}/assign`, { token: dev.token, body: {} })
  if (a.status >= 300) throw new Error(`assign answered ${a.status}: ${JSON.stringify(a.body).slice(0, 200)}`)
  const s = await api.json('PUT', `/api/v1/organizations/${firm.id}/settings`, { token: dev.token, body: {
    intake_agent_did: agentDid,
    ...(opts.listed ? { public_listing: true } : {}),
    ...(opts.transparent ? { public_transparency_opt_in: true } : {}),
  } })
  if (s.status >= 300) throw new Error(`settings answered ${s.status}: ${JSON.stringify(s.body).slice(0, 200)}`)
  if (opts.logo) {
    const l = await api.ctx.fetch(`/api/v1/organizations/${firm.id}/logo`, {
      method: 'PUT', headers: { authorization: `Bearer ${dev.token}` }, failOnStatusCode: false,
      multipart: { file: { name: 'logo.png', mimeType: 'image/png', buffer: PNG_1PX } },
    })
    if (l.status() >= 300) throw new Error(`logo upload answered ${l.status()}`)
  }
  return firm
}

/** Take a firm apart: no intake, not listed, books closed, then deleted. Best effort, after the checks; what each call
 *  answered is kept on the test as an annotation (a cleanup is not a step the lifecycle measures). */
async function retireFirm(api: Api, dev: Developer, firm: Firm | null): Promise<void> {
  if (!firm) return
  let note = ''
  try {
    const s = await api.json('PUT', `/api/v1/organizations/${firm.id}/settings`, { token: dev.token, body: {
      intake_agent_did: '', public_listing: false, public_transparency_opt_in: false } })
    const d = await api.json('DELETE', `/api/v1/organizations/${firm.id}`, { token: dev.token })
    note = `settings ${s.status}, delete ${d.status}`
  } catch (e) {
    note = `cleanup failed: ${String(e).slice(0, 160)}`
  }
  test.info().annotations.push({ type: 'cleanup', description: `firm ${firm.slug}: ${note}` })
}

/** The firms the strip shows on this frame now, and where ours is among them (-1 when not shown). */
async function stripPlace(api: Api, firm: Firm): Promise<{ at: number; total: number; row: any }> {
  const r = await api.json('GET', `/api/v1/organizations/discover/firms?limit=${STRIP_LIMIT}`)
  const firms: any[] = Array.isArray(r.body?.firms) ? r.body.firms : []
  const at = firms.findIndex((f) => String(f.org_id) === firm.id)
  return { at, total: firms.length, row: at >= 0 ? firms[at] : null }
}

async function imageLoaded(page: Page, selector: string): Promise<boolean> {
  return page.locator(selector).evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0).catch(() => false)
}

// ── Engage, to its outcome ────────────────────────────────────────────────────────────────────────────────────────
test('discovery_engage_to_its_outcome', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(8 * 60_000)
  const prov = await registerDeveloper(api, 'engprov')
  const wallet = await createAgentApi(api, prov, 'engwallet')   // the developer's first agent holds the frame's grant
  const provider = await pricedAgent(api, prov, 'engprov')
  const buyer = await partyWith(api, 'engbuyer', 1)
  const [B] = buyer.agents
  let firm: Firm | null = null
  let before = 0

  try {
    await steps.run('a-bonded-provider', 'ui:developer', async () => {
      const wTok = await agentToken(api, wallet)
      await expect.poll(() => agentBalance(api, wTok), { timeout: 45_000, message: 'the wallet holds its grant' }).toBeGreaterThan(250)
      await bondFrom(api, prov, provider.did, wallet.did)   // the provider gate: an unbonded provider is not listed here
      await expect.poll(() => agentBalance(api, B.token), { timeout: 45_000, message: 'the buyer holds its grant' }).toBeGreaterThan(PRICE)
      before = await agentBalance(api, B.token)
      return `provider ${provider.did.slice(-12)} bonded; the buyer holds ${before}`
    })
    const f = await makeFirm(api, prov, provider.did)   // the provider is the firm's intake agent
    firm = f

    await seedSession(context, buyer.dev.token)
    await seedVault(context, buyer, B.did)

    const place = await stripPlace(api, f)
    const dialog = page.getByRole('dialog', { name: provider.name })

    if (place.at < 0) {
      steps.notMeasured('the-firms-engage-opens-its-intake-agent', 'ui:agent',
        `the strip shows the first ${STRIP_LIMIT} firms by settled work and ${place.total} rank ahead of a fresh one here; the agent's own Engage is driven from its card instead`)
      await steps.run('the-agents-card-opens-it', 'ui:agent', async () => {
        await openRoute(page, '/discover')
        await waitActing(page, B.did)
        await page.locator('input.disc-search-input').fill(provider.name)
        const open = page.getByRole('button', { name: `View ${provider.name}` })
        await expect(open, 'the provider is found by its name').toBeVisible({ timeout: 45_000 })
        await open.click()
        await expect(dialog).toBeVisible()
        return 'opened from its card'
      })
    } else {
      await steps.run('the-firms-engage-opens-its-intake-agent', 'ui:agent', async () => {
        await openRoute(page, '/discover')
        await waitActing(page, B.did)
        const card = page.locator(`[data-testid="fl-firm-${f.slug}"]`)
        await expect(card, 'the firm is in the strip').toBeVisible({ timeout: 45_000 })
        const engage = card.locator(`[data-testid="fl-engage-${f.slug}"]`)
        await expect(engage, 'a firm with an intake agent has an open door').toBeEnabled()
        await engage.click()
        await expect(dialog, 'the intake agent opens in the agent modal').toBeVisible()
        await expect(dialog.locator('.adm-hero-name')).toHaveText(provider.name)
        return `strip place ${place.at + 1} of ${place.total}; the modal names ${provider.name}`
      })
    }

    await steps.run('engage-prices-the-call', 'ui:agent', async () => {
      const go = dialog.locator('[data-testid="adm-engage-go"]')
      await expect(go, 'a priced agent of this frame is engaged directly').toBeEnabled({ timeout: 30_000 })
      await go.click()
      const panel = dialog.locator('[data-testid="bsp"]')
      await expect(panel).toBeVisible()
      const shown = await firstOf(page, [panel.locator('[data-testid="bsp-price"]'), panel.locator('[data-testid="bsp-quote-error"]'),
        panel.locator('[data-testid="bsp-blocked"]')], 45_000)
      expect(shown, `the quote answered (0), not ${['', 'a quote refusal', 'no acting agent'][shown]}`).toBe(0)
      const q = await api.json('GET', `/api/v1/a2a-payment/quote?target_agent_did=${encodeURIComponent(provider.did)}`, { token: B.token })
      expect(q.status).toBe(200)
      expect(q.body?.payment_required, 'the card charges').toBe(true)
      const yours = panel.locator('[data-testid="bsp-price-yours"]')
      await expect(yours).toContainText(String(q.body.recommended_amount))
      await expect(yours).toContainText(String(q.body.your_currency))
      return `quoted ${q.body.recommended_amount} ${q.body.your_currency}, as the API reads it`
    })

    await steps.run('engage-to-its-outcome', 'ui:agent', async () => {
      const panel = dialog.locator('[data-testid="bsp"]')
      await panel.locator('[data-testid="bsp-prompt"]').fill('Say hello.')
      const buy = panel.locator('[data-testid="bsp-go"]')
      await expect(buy).toBeEnabled()
      await buy.click()
      const outcome = await firstOf(page, [panel.locator('[data-testid="bsp-error"]'), panel.locator('[data-testid="bsp-result"]')], 90_000)
      expect(outcome, 'an agent that serves nothing cannot answer').toBe(0)
      await expect(panel.locator('[data-testid="bsp-error"]'), 'the page says nothing was charged').toContainText(/not charged/i)
      await expect(panel.locator('[data-testid="bsp-settlement"]')).toContainText(/nothing charged/i)
      // read back: the authorization was released and the units are where they were
      const t = await api.json('GET', '/api/v1/a2a-payment/my-tokens?limit=20', { token: B.token })
      const mine = (Array.isArray(t.body) ? t.body : []).filter((x: any) => x?.target_agent_did === provider.did)
      expect(mine.length, 'one authorization for the provider').toBeGreaterThan(0)
      expect(String(mine[0].status).toLowerCase(), 'the authorization reads released').toBe('released')
      await expect.poll(() => agentBalance(api, B.token), { timeout: 30_000, message: 'the buyer\'s units are where they were' })
        .toBeCloseTo(before, 6)
      await stillFrame(page)
      await a11y(page, 'discover-engage-outcome')
      return `released, nothing charged; the buyer holds ${before}`
    })
  } finally {
    await retireFirm(api, prov, firm)
  }
})

// ── the Firms surfaces at desktop width ───────────────────────────────────────────────────────────────────────────
test('firms_surfaces_at_desktop_width', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(8 * 60_000)
  const owner = await registerDeveloper(api, 'firmowner')
  await createAgentApi(api, owner, 'firmwallet')
  const member = await createAgentApi(api, owner, 'firmagent')
  let firm: Firm | null = null
  try {
    const f = await makeFirm(api, owner, member.did, { listed: true, transparent: true, logo: true })
    firm = f
    await seedSession(context, owner.token)
    const place = await stripPlace(api, f)
    const strip = page.locator('[data-testid="firms-lane"]')
    const card = page.locator(`[data-testid="fl-firm-${f.slug}"]`)

    if (place.at < 0) {
      steps.notMeasured('the-strip-shows-the-hosted-logo-and-both-counts', 'ui:developer',
        `the strip shows ${STRIP_LIMIT} firms by settled work and ${place.total} rank ahead of a fresh one here`)
      steps.notMeasured('the-bounty-door-opens-the-guild-board', 'ui:developer', 'the firm is not in the strip (above)')
    } else {
      await steps.run('the-strip-shows-the-hosted-logo-and-both-counts', 'ui:developer', async () => {
        await openRoute(page, '/discover')
        await expect(card).toBeVisible({ timeout: 45_000 })
        const img = `[data-testid="fl-logo-${f.slug}"] img`
        await expect(page.locator(img)).toHaveAttribute('src', new RegExp(`/api/v1/organizations/${f.id}/logo`))
        await expect.poll(() => imageLoaded(page, img), { timeout: 15_000, message: 'the hosted logo loads' }).toBe(true)
        const own = card.locator('[data-testid="fl-proof"]').first()
        await expect(own).toContainText('As the firm')
        await expect(own).toContainText(new RegExp(`${place.row.verified_jobs}\\s*jobs delivered`))
        const members = card.locator('[data-testid="fl-members"]')
        if (place.row.member_work) {
          await expect(members).toContainText('Its agents, on their own')
          await expect(members).toContainText(new RegExp(`${place.row.member_work.jobs}\\s*jobs? settled`))
        } else {
          await expect(members, 'no member_work in the answer, no line').toHaveCount(0)
        }
        await stillFrame(page)
        await a11y(page, 'discover-firms-strip')
        return `logo loaded; as the firm ${place.row.verified_jobs}, its agents ${place.row.member_work?.jobs ?? 'not stated'}`
      })

      await steps.run('the-bounty-door-opens-the-guild-board', 'ui:developer', async () => {
        await card.locator(`[data-testid="fl-bounty-${f.slug}"]`).click()
        expect(await routerArrives(page, '/guild')).toBe('/guild')
        expect(decodeURIComponent(page.url()), 'the firm rides the door').toContain(`for_org=${f.id}`)
        const dialog = page.getByRole('dialog', { name: /post a task/i })
        await expect(dialog).toBeVisible()
        await expect(dialog.locator('[data-testid="gld-post-fororg"]'), 'the bounty is reserved for the firm').toBeVisible()
        await expect(dialog.locator('#gld-post-name')).toHaveValue(`For ${f.name}: `)
        await dialog.getByRole('button', { name: /cancel/i }).click()
        await expect(dialog).toHaveCount(0)
        return 'the Guild board, the firm reserved; nothing posted'
      })
    }

    await steps.run('the-filter-hides-the-strip-and-it-stays-hidden', 'ui:developer', async () => {
      await openRoute(page, '/discover')
      await expect(strip).toBeVisible({ timeout: 45_000 })
      await page.locator('[data-testid="disc-firms-filter"] input[type="checkbox"]').check()
      await expect(strip).toHaveCount(0)
      await expect(page.locator('[data-testid="disc-firms-hidden"]'), 'the page says what the filter withheld').toBeVisible()
      await expect.poll(() => decodeURIComponent(page.url())).toContain('firms=hide')
      await page.reload()
      await settle(page)
      await passReconsent(page)
      await expect(page.locator('[data-testid="disc-firms-hidden"]'), 'a reload keeps it').toBeVisible({ timeout: 45_000 })
      await openRoute(page, '/firms')                                // leave, then come back: a fresh Discovery
      await openRoute(page, '/discover')
      await expect(page.locator('[data-testid="disc-firms-hidden"]'), 'the next visit keeps it').toBeVisible({ timeout: 45_000 })
      await expect(strip).toHaveCount(0)
      await expect.poll(() => decodeURIComponent(page.url()), { message: 'and the address says so' }).toContain('firms=hide')
      await page.locator('[data-testid="disc-firms-show"]').click()
      await expect(strip).toBeVisible({ timeout: 45_000 })
      await expect.poll(() => decodeURIComponent(page.url())).not.toContain('firms=hide')
      expect(await page.evaluate(() => localStorage.getItem('tp_disc_firms_hidden')), 'shown again, nothing kept').toBeNull()
      return 'hidden, kept across a reload and a visit, shown again'
    })

    await steps.run('the-sidebar-reaches-firms', 'ui:developer', async () => {
      await openRoute(page, '/discover')
      const entry = page.locator('[data-tour="nav-firms"]').first()
      await expect(entry).toBeVisible()
      await entry.click()
      expect(await routerArrives(page, '/firms')).toBe('/firms')
      return 'Agents, Firms: #/firms'
    })

    await steps.run('firms-side-by-side-at-desktop-width', 'ui:developer', async () => {
      if (await currentRoute(page) !== '/firms') await openRoute(page, '/firms')
      await expect(page.locator('[data-testid="pf-layout"]')).toBeVisible({ timeout: 45_000 })
      const dir = await page.locator('.pfw-dir').boundingBox()
      const panel = await page.locator('[data-testid="pf-records"]').boundingBox()
      expect(dir && panel, 'both columns are laid out').toBeTruthy()
      expect(panel!.x, 'the records sit beside the directory').toBeGreaterThanOrEqual(dir!.x + dir!.width - 1)
      expect(Math.abs(panel!.y - dir!.y), 'on the same line').toBeLessThanOrEqual(4)
      const mine = page.locator(`[data-testid="org-directory-local"][data-slug="${f.slug}"]`)
      await expect(mine, 'a listed firm is in the directory').toBeVisible({ timeout: 30_000 })
      await expect(mine.locator('img')).toHaveAttribute('src', new RegExp(`/api/v1/organizations/${f.id}/logo`))
      const pill = page.locator(`[data-testid="pf-firm-${f.slug}"]`)
      if (await pill.count()) {
        await pill.click()
        await expect(page.locator('[data-testid="pf-feed"]')).toContainText(f.name)
        await expect(mine, 'the picked firm is marked in the directory').toHaveClass(/odir__card--on/)
      } else {
        steps.notMeasured('firms-pick-marks-the-directory', 'ui:public',
          'the open-books list shows 25 organizations by their last record and ours has none yet')
      }
      expect(await sideScroll(page)).toBeLessThanOrEqual(1)
      await stillFrame(page)
      await a11y(page, 'firms-desktop')
      return `directory at x=${Math.round(dir!.x)}, records at x=${Math.round(panel!.x)}, top ${Math.round(dir!.y)}/${Math.round(panel!.y)}`
    })
  } finally {
    await retireFirm(api, owner, firm)
  }
})

// ── the Firms surfaces on a phone ─────────────────────────────────────────────────────────────────────────────────
test('firms_surfaces_on_a_phone @phone-only', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(6 * 60_000)
  const owner = await partyWith(api, 'firmphone', 2)
  const [, agent] = owner.agents
  let firm: Firm | null = null
  try {
    const f = await makeFirm(api, owner.dev, agent.did, { listed: true, transparent: true, logo: true })
    firm = f
    await seedSession(context, owner.dev.token)
    await seedVault(context, owner, owner.agents[0].did)
    const place = await stripPlace(api, f)

    if (place.at < 0) {
      const why = `the strip shows ${STRIP_LIMIT} firms by settled work and ${place.total} rank ahead of a fresh one here`
      steps.notMeasured('the-bounty-door-stays-in-the-desktop-console', 'ui:developer', why)
      steps.notMeasured('the-bounty-door-on-explore-opens-pockets-sheet', 'ui:developer', why)
    } else {
      const card = page.locator(`[data-testid="fl-firm-${f.slug}"]`)
      await steps.run('the-bounty-door-stays-in-the-desktop-console', 'ui:developer', async () => {
        // Agent Discovery renders inside DashboardLayout: a press there stays in the desktop console, on a phone too
        await openRoute(page, '/discover')
        await expect(card).toBeVisible({ timeout: 45_000 })
        await expect.poll(() => imageLoaded(page, `[data-testid="fl-logo-${f.slug}"] img`), { timeout: 15_000 }).toBe(true)
        await card.locator(`[data-testid="fl-bounty-${f.slug}"]`).tap()
        expect(await routerArrives(page, '/guild'), 'a press in the desktop console stays there').toBe('/guild')
        expect(decodeURIComponent(page.url()), 'the firm rides the door').toContain(`for_org=${f.id}`)
        const dialog = page.getByRole('dialog', { name: /post a task/i })
        await expect(dialog).toBeVisible()
        await expect(dialog.locator('[data-testid="gld-post-fororg"]'), 'the bounty is reserved for the firm').toBeVisible()
        await expect(dialog.locator('#gld-post-name')).toHaveValue(`For ${f.name}: `)
        await dialog.getByRole('button', { name: /cancel/i }).tap()
        await expect(dialog).toHaveCount(0)
        return 'the Guild board in the desktop console, the firm reserved; nothing posted'
      })

      await steps.run('the-bounty-door-on-explore-opens-pockets-sheet', 'ui:developer', async () => {
        // the public Explore page mounts no shell: there the landing decision picks, and a phone's is Pocket
        await openRoute(page, '/explore')
        await expect(card).toBeVisible({ timeout: 45_000 })
        await card.locator(`[data-testid="fl-bounty-${f.slug}"]`).tap()
        expect(await routerArrives(page, '/pocket/payments'), 'where no shell is mounted, a phone follows the landing decision to Pocket').toBe('/pocket/payments')
        const sheet = page.locator('[data-testid="pe-post-sheet"]')
        await expect(sheet).toBeVisible({ timeout: 30_000 })
        await expect(sheet.locator('[data-testid="pe-post-fororg"]'), 'the bounty stays reserved for the firm').toBeVisible()
        await expect(sheet.locator('[data-testid="pe-post-title"]')).toHaveValue(new RegExp(`^For ${f.name}:`))
        await sheet.getByRole('button', { name: /cancel/i }).tap()
        await expect(sheet).toHaveCount(0)
        return 'Pocket\'s sheet, the firm reserved; nothing posted'
      })
    }

    await steps.run('firms-stacked-on-a-phone', 'ui:public', async () => {
      await openRoute(page, '/firms')
      await expect(page.locator('[data-testid="pf-layout"]')).toBeVisible({ timeout: 45_000 })
      const dir = await page.locator('.pfw-dir').boundingBox()
      const panel = await page.locator('[data-testid="pf-records"]').boundingBox()
      expect(dir && panel, 'both parts are laid out').toBeTruthy()
      expect(panel!.y, 'the records follow the directory').toBeGreaterThanOrEqual(dir!.y + dir!.height - 1)
      expect(await sideScroll(page), 'nothing scrolls sideways').toBeLessThanOrEqual(1)
      await stillFrame(page)
      await a11y(page, 'firms-phone')
      return `directory ${Math.round(dir!.height)} px tall, records below at y=${Math.round(panel!.y)}`
    })
  } finally {
    await retireFirm(api, owner.dev, firm)
  }
})
