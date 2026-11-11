/**
 * V0658 (t), session-code 2026-11-08: an organization's room wears its organization's hosted logo in the chat list, on
 * the desktop (/ourchat, the list beside the thread) and on a phone (/pocket/ourchat), as the thread's header has since
 * V0657 (b). The maintainer's check (the sessions' room seq 2156-2157): the logo showed at the top of the thread, next to
 * the room's name, and the room's entry in the list still showed the generic room avatar.
 *
 * Setup over the API (what a person does in the organization's settings and the list): an owner with four
 * organizations: A with a logo, its room open; B without a logo, its room open (the control: today's avatar); C with a
 * logo, its room on and not opened yet (the Rooms section); D with a logo and no room (the organizations without one).
 * Then the page: each entry's avatar is the logo this registry hosts (loaded, from this origin, never another host),
 * B keeps the room avatar, and the thread's header shows the same logo as the list. Read back from the API: the list's
 * row and the rooms section carry the hosted logo's address.
 */
import type { Page } from '@playwright/test'
import { test, expect } from '../support/fixtures'
import type { Api } from '../support/fixtures'
import { ledger, registerDeveloper, seedSession, type Developer } from '../support/accounts'
import { uniqueName } from '../support/env'
import { openRoute, settle } from '../support/ui'
import { sideScroll } from '../support/pages'
import { listOf, readBack, steady } from '../support/social'

// a 24 px PNG (a cyan disc on a dark ground), the kind of file a person uploads as the logo
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAATklEQVR42mPgFlKgCmIYUgYpXX6Hhkg2CNMIgsYxkGoKLrMYyDAFq1kM5JmCaRYNDCLVFDSzRg0aEIMGXzqiZhahZqalZjFCzYJtWBT+AD+vL1869xCzAAAAAElFTkSuQmCC', 'base64')

interface Org { id: string; name: string; logo: string | null; conv: string | null }
interface Rooms { owner: Developer; a: Org; b: Org; c: Org; d: Org }

async function makeOrg(api: Api, owner: Developer, kind: string, opts: { logo: boolean; room: 'open' | 'on' | 'off' }): Promise<Org> {
  const name = uniqueName(kind)
  const o = await api.json('POST', '/api/v1/organizations', { token: owner.token, body: { name, description: 'the org room logo lifecycle' } })
  if (o.status >= 300 || !o.body?.id) throw new Error(`organization create answered ${o.status}`)
  const id = String(o.body.id)
  ledger('organization', { id, name, owner: owner.email })
  let logo: string | null = null
  if (opts.logo) {
    const r = await api.ctx.fetch(`/api/v1/organizations/${id}/logo`, {
      method: 'PUT', headers: { authorization: `Bearer ${owner.token}` }, failOnStatusCode: false,
      multipart: { file: { name: 'logo.png', mimeType: 'image/png', buffer: PNG } },
    })
    const body = await r.json().catch(() => null)
    if (r.status() !== 200 || !body?.logo) throw new Error(`logo upload answered ${r.status()}`)
    logo = String(body.logo)
  }
  let conv: string | null = null
  if (opts.room === 'on') {
    const s = await api.json('PUT', `/api/v1/chat/org-rooms/${id}/settings`, { token: owner.token, body: { chat_enabled: true } })
    if (s.status !== 200 || s.body?.chat_enabled !== true) throw new Error(`room settings answered ${s.status}`)
  } else if (opts.room === 'open') {
    const r = await api.json('POST', `/api/v1/chat/org-rooms/${id}/open`, { token: owner.token })
    if (r.status >= 300 || !r.body?.conversation_id) throw new Error(`room open answered ${r.status}`)
    conv = String(r.body.conversation_id)
  }
  return { id, name, logo, conv }
}

async function ownerWithRooms(api: Api, kind: string): Promise<Rooms> {
  const owner = await registerDeveloper(api, kind)
  return {
    owner,
    a: await makeOrg(api, owner, 'logoorg', { logo: true, room: 'open' }),
    b: await makeOrg(api, owner, 'plainorg', { logo: false, room: 'open' }),
    c: await makeOrg(api, owner, 'doororg', { logo: true, room: 'on' }),
    d: await makeOrg(api, owner, 'offorg', { logo: true, room: 'off' }),
  }
}

/** The logo inside an entry: its address as written, where the browser loaded it from, and whether it decoded. */
async function logoIn(page: Page, entry: string): Promise<{ src: string; origin: string; here: string; loaded: boolean }> {
  const img = page.locator(`${entry} [data-testid="os-room-avatar"] img`)
  await expect(img, `${entry}: the organization's logo`).toBeVisible()
  // the logo loads lazily, as a person scrolls to it: bring it into view first
  await img.scrollIntoViewIfNeeded()
  await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0),
    { message: `${entry}: the logo loaded` }).toBe(true)
  return img.evaluate((el: HTMLImageElement) => ({
    src: el.getAttribute('src') || '', origin: new URL(el.currentSrc || el.src).origin, here: location.origin,
    loaded: el.naturalWidth > 0,
  }))
}

/** Every entry of the list wears what it should: A, C and D their logos, B today's room avatar. */
async function listWearsTheLogos(page: Page, r: Rooms): Promise<string> {
  const entries: Array<[string, Org]> = [
    [`[data-testid="os-row-${r.a.conv}"]`, r.a],
    [`[data-testid="os-room-${r.c.id}"]`, r.c],
    [`[data-testid="os-room-off-${r.d.id}"]`, r.d],
  ]
  for (const [sel, org] of entries) {
    const got = await logoIn(page, sel)
    expect(got.src, `${sel}: the address this registry hosts`).toBe(org.logo)
    expect(got.origin, `${sel}: loaded from this console's own origin, never another host`).toBe(got.here)
  }
  const plain = page.locator(`[data-testid="os-row-${r.b.conv}"] [data-testid="os-room-avatar"]`)
  await expect(plain, 'B: an entry').toBeVisible()
  await expect(plain).toHaveAttribute('data-logo', 'none')
  expect(await plain.locator('img').count(), 'B hosts no logo: no image').toBe(0)
  await expect(plain.locator('svg'), 'B keeps today\'s room avatar').toBeVisible()
  return 'A, C and D wear their hosted logos; B keeps the room avatar'
}

/** The API's own answer: the list's row and the rooms section name the hosted logo. */
async function readBackTheLogos(api: Api, r: Rooms): Promise<void> {
  const rows = listOf((await readBack(api, '/api/v1/chat/conversations', r.owner.token)).body, 'conversations')
  const rowA = rows.find((c: any) => c.id === r.a.conv)
  const rowB = rows.find((c: any) => c.id === r.b.conv)
  expect(rowA?.org?.logo, 'the list row of A names its hosted logo').toBe(r.a.logo)
  expect(rowB?.org?.id, 'the list row of B names its organization').toBe(r.b.id)
  expect(rowB?.org?.logo, 'and no logo, for B hosts none').toBeNull()
  const rm = (await readBack(api, '/api/v1/chat/org-rooms', r.owner.token)).body || {}
  expect((rm.rooms || []).find((x: any) => x.org_id === r.c.id)?.org?.logo, 'the Rooms section: C').toBe(r.c.logo)
  expect((rm.enableable || []).find((x: any) => x.org_id === r.d.id)?.org?.logo, 'without a room: D').toBe(r.d.logo)
}

async function deleteOrgs(api: Api, r: Rooms): Promise<string> {
  const gone: string[] = []
  for (const o of [r.a, r.b, r.c, r.d]) {
    const d = await api.json('DELETE', `/api/v1/organizations/${o.id}`, { token: r.owner.token })
    expect(d.status, `delete ${o.name}`).toBeLessThan(300)
    gone.push(o.name)
  }
  return `${gone.length} organizations deleted`
}

test('ourchat_org_room_logo_in_the_list', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(4 * 60_000)
  const r = await ownerWithRooms(api, 'roomlogo')
  await seedSession(context, r.owner.token)

  await steps.run('the-list-shows-each-rooms-logo', 'ui:developer', async () => {
    expect(await openRoute(page, '/ourchat')).toBe('/ourchat')
    await expect(page.locator('[data-testid="ocs-list"]'), 'the desktop shell: the list beside the thread').toBeVisible()
    const said = await listWearsTheLogos(page, r)
    await readBackTheLogos(api, r)
    await steady(page)
    await a11y(page, 'ourchat-list-org-logo')
    return said
  })

  await steps.run('the-thread-header-shows-the-same-logo', 'ui:developer', async () => {
    await page.locator(`[data-testid="os-row-${r.a.conv}"]`).click()
    await page.waitForFunction((id) => location.hash.startsWith(`#/ourchat/${id}`), r.a.conv, { timeout: 20_000 })
    const head = page.locator('[data-testid="ost-room-org"] img')
    await expect(head, 'the thread\'s header shows the organization\'s logo').toBeVisible()
    await expect(head).toHaveAttribute('src', String(r.a.logo))
    await expect(page.locator(`[data-testid="os-row-${r.a.conv}"] [data-testid="os-room-avatar"] img`),
      'the list beside the open thread still wears it').toHaveAttribute('src', String(r.a.logo))
    await settle(page)
    return 'the header and the list name the same hosted logo'
  })

  await steps.run('delete-the-organizations', 'ui:developer', async () => deleteOrgs(api, r))
})

test('ourchat_org_room_logo_in_the_list_on_the_phone @phone-only', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(4 * 60_000)
  const r = await ownerWithRooms(api, 'roomlogoph')
  await seedSession(context, r.owner.token)

  await steps.run('the-pocket-list-shows-each-rooms-logo', 'ui:developer', async () => {
    expect(await openRoute(page, '/pocket/ourchat')).toBe('/pocket/ourchat')
    const said = await listWearsTheLogos(page, r)
    await readBackTheLogos(api, r)
    expect(await sideScroll(page), 'the list does not scroll sideways').toBeLessThanOrEqual(1)
    await steady(page)
    await a11y(page, 'pocket-ourchat-list-org-logo')
    return `${said} (${page.viewportSize()?.width} px)`
  })

  await steps.run('the-phone-thread-header-shows-the-same-logo', 'ui:developer', async () => {
    await page.locator(`[data-testid="os-row-${r.a.conv}"]`).tap()
    await page.waitForFunction((id) => location.hash.startsWith(`#/pocket/ourchat/${id}`), r.a.conv, { timeout: 20_000 })
    const head = page.locator('[data-testid="ost-room-org"] img')
    await expect(head, 'the thread\'s header shows the organization\'s logo').toBeVisible()
    await expect(head).toHaveAttribute('src', String(r.a.logo))
    await settle(page)
    return 'the header names the list\'s hosted logo'
  })

  await steps.run('delete-the-organizations', 'ui:developer', async () => deleteOrgs(api, r))
})
