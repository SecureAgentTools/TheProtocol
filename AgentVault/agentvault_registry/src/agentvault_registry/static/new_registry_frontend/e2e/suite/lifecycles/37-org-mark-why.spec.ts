/**
 * V0658 (r): an owner sees why his organization's mark does not show (the sessions' room seq 2136: no organization
 * logo anywhere on EU after V0657). V0657 (b) states the mark only while the organization is listed and shows only a
 * logo this registry hosts; an old logo address is never shown. The owner opens an unlisted organization that still
 * names an old logo address: the page says both reasons, and offers the old image for upload without asking its host
 * until the owner presses "Show the old image here"; the settings say it too, once; a member sees nothing new and his
 * page asks nothing an admin alone may read; the owner lists it and uploads a logo with the notice's own controls, each
 * read back from the API, and the notice goes once the mark shows.
 * The old address is on the console's own host (a file every build serves), because the suite's browser reaches the
 * sandbox consoles only; on another host it could take only the "did not load" branch.
 * The upload step needs V0658 (u) (the console sends the logo as multipart).
 */
import type { Locator, Page } from '@playwright/test'
import { test, expect } from '../support/fixtures'
import { ledger, registerDeveloper, seedSession } from '../support/accounts'
import { BASE_URL, uniqueName } from '../support/env'
import { openRoute, settle } from '../support/ui'

// a 1x1 PNG: the registry reads the type from the bytes
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64')

/**
 * The legacy sentence's box against its own lines: the first cut gave it a 320 px flex basis inside a column (a height).
 * A line is as tall as its line height, not its glyphs: at 12 px / 1.5 the box is 18 a line and a range over its text 4
 * less on any number of lines (fes-20261108T034151Z-3923: 18 against 14), so the box is held to lines x line height.
 */
async function sentenceFitsItsLines(sentence: Locator): Promise<{ box: number; lines: number; lineHeight: number }> {
  return sentence.evaluate((p) => {
    const r = document.createRange()
    r.selectNodeContents(p)
    const tops = new Set(Array.from(r.getClientRects()).filter((q) => q.width > 0).map((q) => Math.round(q.top)))
    return { box: p.getBoundingClientRect().height, lines: tops.size, lineHeight: parseFloat(getComputedStyle(p).lineHeight) }
  })
}

/**
 * A new width re-lays the page over DashboardLayout's 0.3 s transition (below 1024 the sidebar slides out and the
 * content's padding follows it), so a box read in the tick of the resize measures a column on its way
 * (fes-20261108T034529Z-8c5c: at 393 the notice about 116 px wide, its list button past its edge). Resize, give the
 * resize event and the re-render two frames to start their transitions, and wait for every transition to end.
 */
async function resizeAndSettle(page: Page, width: number, height: number): Promise<void> {
  await page.setViewportSize({ width, height })
  await page.evaluate(async () => {
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))
    await Promise.allSettled(document.getAnimations().filter((a) => a instanceof CSSTransition).map((a) => a.finished))
  })
}

test('organization_mark_why', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(5 * 60_000)
  // an old logo address, as organizations carried them before V0657 (b), on a host the suite's browser reaches
  const OLD = new URL('/static/og/enterprise-card.png', BASE_URL).toString()
  const owner = await registerDeveloper(api, 'markowner')
  const member = await registerDeveloper(api, 'markmember')
  await seedSession(context, owner.token)
  const orgName = uniqueName('org')
  let orgId = ''
  let other: Page | null = null
  const read = async () => (await api.json('GET', `/api/v1/organizations/${orgId}`, { token: owner.token })).body
  // every request the owner's page makes for the old address: none before the press
  const askedOld: string[] = []
  page.on('request', (r) => { if (r.url() === OLD) askedOld.push(r.method()) })

  await steps.run('organization-with-an-old-logo-address', 'ui:developer', async () => {
    const o = await api.json('POST', '/api/v1/organizations', {
      token: owner.token, body: { name: orgName, description: 'made by the console lifecycle suite', logo_url: OLD } })
    expect(o.status, 'the organization is created').toBeLessThan(300)
    orgId = String(o.body.id)
    ledger('organization', { id: orgId, name: orgName, owner: owner.email })
    const inv = await api.json('POST', `/api/v1/organizations/${orgId}/invite`, {
      token: owner.token, body: { email: member.email, role: 'member' } })
    expect(inv.status, 'the member is invited').toBeLessThan(300)
    // the token travels in the invitation mail; the suite reads it from the invite's own answer, never stores it
    const token = String(inv.body.token || inv.body.invitation_token || inv.body.invitation?.token || '')
    const acc = await api.json('POST', `/api/v1/organizations/invitations/${token}/accept`, { token: member.token })
    expect(acc.status, 'the member joins').toBeLessThan(300)
    const org = await read()
    expect(org.listed, 'not listed (the default)').toBe(false)
    expect(org.logo ?? null, 'no logo hosted').toBeNull()
    expect(org.logo_url).toBe(OLD)
    return 'unlisted, no hosted logo, an old logo address; a member joined'
  })

  await steps.run('the-page-says-why', 'ui:developer', async () => {
    expect(await openRoute(page, `/organization?org=${orgId}`)).toBe('/organization')
    await expect(page.locator('.identity-name')).toHaveText(orgName)
    const why = page.locator('.identity-panel [data-testid="org-mark-why"]')
    await expect(why).toBeVisible()
    await expect(why).toHaveAttribute('data-missing', 'listing logo')
    await expect(why.locator('[data-testid="org-mark-why-list"]')).toBeVisible()
    await expect(why.locator('[data-testid="org-mark-why-legacy-open"]')).toHaveAttribute('href', OLD)
    // offered, not loaded: the owner's browser has not asked the old host
    await expect(why.locator('[data-testid="org-mark-why-legacy-image"]')).toHaveCount(0)
    expect(askedOld, 'nothing asked the old address before the press').toEqual([])
    await why.locator('[data-testid="org-mark-why-legacy-show"]').click()
    const img = why.locator('[data-testid="org-mark-why-legacy-image"]')
    await expect(img).toBeVisible()
    await expect.poll(() => img.evaluate((el) => (el as HTMLImageElement).complete && (el as HTMLImageElement).naturalWidth > 0),
      { message: 'the old image decodes in the owner\'s browser' }).toBe(true)
    expect(askedOld.length, 'asked once the owner pressed').toBeGreaterThan(0)
    // the old logo's row is as tall as what it says (the first cut stood it 338 px tall around a 14 px sentence)
    const row = why.locator('[data-testid="org-mark-why-legacy"]')
    expect((await row.boundingBox())!.height, 'the old logo\'s row at 1440').toBeLessThan(120)
    const fit = await sentenceFitsItsLines(row.locator('.omw__why'))
    expect(Math.abs(fit.box - fit.lines * fit.lineHeight),
      `its sentence's box (${fit.box}) against its ${fit.lines} line(s) of ${fit.lineHeight}`).toBeLessThan(1)
    await a11y(page, 'org-mark-why-page')
    // the same notice at phone width: its rows wrap and keep their controls inside it (whether the page around it fits
    // a phone is the page's own question: reported, not asserted here)
    await resizeAndSettle(page, 393, 852)
    const box = (await why.boundingBox())!
    for (const id of ['org-mark-why-list', 'org-mark-why-legacy-open']) {
      const b = (await why.locator(`[data-testid="${id}"]`).boundingBox())!
      expect(b.x >= box.x - 1 && b.x + b.width <= box.x + box.width + 1, `${id} inside the notice at 393`).toBe(true)
    }
    const phone = await sentenceFitsItsLines(row.locator('.omw__why'))
    expect(Math.abs(phone.box - phone.lines * phone.lineHeight),
      `at 393 its sentence's box (${phone.box}) against its ${phone.lines} line(s) of ${phone.lineHeight}`).toBeLessThan(1)
    const past = Math.round(box.x + box.width - 393)
    await resizeAndSettle(page, 1440, 900)
    return `both reasons on the page; the old image offered, loaded only after the press; at 393 the notice ${past > 0 ? `runs ${past} px past the screen` : 'fits the screen'}`
  })

  await steps.run('a-member-sees-nothing-new', 'ui:developer', async () => {
    other = await openAs(member.token)
    expect(await openRoute(other, `/organization?org=${orgId}`)).toBe('/organization')
    await expect(other.locator('.identity-name')).toHaveText(orgName)
    // the role is read off the members after the page mounts: the absence below means something once it says MEMBER
    await expect(other.locator('.identity-name-row .role-badge')).toHaveText('MEMBER')
    await settle(other)
    await expect(other.locator('[data-testid="org-mark-why"]')).toHaveCount(0)
    await other.locator('[data-tour="org-tab-settings"]').click()
    // a member's settings tab is the access notice (the settings themselves are for owners and admins)
    await expect(other.locator('.empty-state').filter({ hasText: 'Access Restricted' })).toBeVisible()
    await expect(other.locator('[data-testid="org-public-face"]')).toHaveCount(0)
    await settle(other)
    await expect(other.locator('[data-testid="org-mark-why"]')).toHaveCount(0)
    return 'no notice for a member, on the page or in the settings'
  })

  await steps.run('the-settings-say-it-once', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-settings"]').click()
    await expect(page.locator('[data-testid="org-mark-why"]')).toHaveCount(1)
    await expect(page.locator('.identity-panel [data-testid="org-mark-why"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="org-mark-why-upload-below"]')).toBeVisible()
    await expect(page.locator('[data-testid="org-logo-input"]')).toHaveCount(1)
    await a11y(page, 'org-mark-why-settings')
    return 'in the settings, once, pointing at the logo panel'
  })

  await steps.run('list-it-with-its-control', 'ui:developer', async () => {
    // an unsaved edit in the policy form below stays when the notice lists the organization
    const ttl = page.locator('#pol-contract_offer_ttl_days')
    await ttl.fill('45')
    await page.locator('[data-testid="org-mark-why-list"]').click()
    await expect(page.locator('[data-testid="org-mark-why"]')).toHaveAttribute('data-missing', 'logo')
    await expect.poll(async () => (await read()).listed, { message: 'the API reads it listed' }).toBe(true)
    await expect(page.locator('[data-testid="pol-bool-public_listing"] input')).toBeChecked()
    await expect(ttl, 'the policy form kept its unsaved edit').toHaveValue('45')
    return 'listed, read back; the policy switch reads on, the form kept its edit'
  })

  await steps.run('upload-its-logo-with-its-control', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-teams"]').click()
    const why = page.locator('.identity-panel [data-testid="org-mark-why"]')
    await expect(why).toHaveAttribute('data-missing', 'logo')
    await why.locator('[data-testid="org-mark-why-upload"]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG })
    await expect(page.locator('[data-testid="org-mark-why"]'), 'the mark shows: nothing more to say').toHaveCount(0)
    await expect.poll(async () => Boolean((await read()).logo), { message: 'the API reads a hosted logo' }).toBe(true)
    return 'logo hosted, read back; the notice is gone'
  })

  await steps.run('delete-organization', 'ui:developer', async () => {
    // both pages leave first: a dashboard read of an organization deleted under it would be a refusal on a page in use
    await page.goto('about:blank')
    if (other) await other.goto('about:blank')
    const d = await api.json('DELETE', `/api/v1/organizations/${orgId}`, { token: owner.token })
    expect(d.status, 'the organization is deleted').toBeLessThan(300)
    return 'deleted'
  })
})
