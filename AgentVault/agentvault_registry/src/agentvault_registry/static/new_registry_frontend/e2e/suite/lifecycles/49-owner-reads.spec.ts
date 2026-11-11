/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c): the maintainer's three console defects (sessions' room seq 2105), as
 * the owner meets them at desktop width. One developer with two agents: the poster P posts a Guild order (over the API,
 * as his session agents do), and the console acts as the other one, S.
 *
 *   (1) the order's door on a desktop is the Guild board (/guild?order=<id>), not Pocket's order sheet: the board opens
 *       that order;
 *   (3) the agent selector draws S's own logo (its card's picture), not initials and never a vanity core;
 *   (2) reading follows ownership: with S selected the order shows, the board names P as the poster and as the agent
 *       that may act, offers S no poster action, and My work lists the order with P named.
 *
 * The steps run in that order on purpose: (1) and (3) need only the console, so a console dist served against a
 * registry from before V0658 (q) still measures them; from the owner read on, the steps need a registry with the owner
 * reads (GET /guild/owned, and the order detail naming a developer's parties), and a step that fails stops the
 * lifecycle.
 *
 * The chat card itself is not driven here (a room with the Guild's live card is the Guild's to post): its door is the
 * same orderDoor() the unit tests pin (PocketOurStateThread.orderDoor.test.ts); this lifecycle proves where it lands.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { partyWith, seedVault, waitActing } from '../support/commerce'
import { BASE_URL, uniqueName } from '../support/env'
import { openRoute } from '../support/ui'

test('owner_reads_order_door_selector_logo', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const owner = await partyWith(api, 'ownread', 2)
  const [P, S] = owner.agents
  const title = uniqueName('owned-task')
  const logo = `${new URL(BASE_URL).origin}/static/pwa-192.png`
  let oid = ''

  await steps.run('the-poster-posts', 'ui:developer', async () => {
    await expect.poll(() => agentBalance(api, P.token), { timeout: 45_000, message: 'the poster holds its grant' }).toBeGreaterThan(1)
    const r = await api.json('POST', '/api/v1/guild/orders', { token: P.token,
      body: { title, spec: 'Read only for its owner whichever agent is selected.', bounty: 1, deadline_seconds: 3600 } })
    expect(r.status, JSON.stringify(r.body)).toBe(200)
    oid = String(r.body?.order_id || '')
    expect(oid, 'the order has an id').not.toBe('')
    return `posted ${oid.slice(0, 12)}`
  })

  await steps.run('a-logo-on-the-selected-agent', 'ui:developer', async () => {
    const got = await api.json('GET', `/api/v1/agent-cards/${encodeURIComponent(S.did)}`, { token: owner.dev.token })
    expect(got.status).toBe(200)
    const put = await api.json('PUT', `/api/v1/agent-cards/${encodeURIComponent(S.did)}`, { token: owner.dev.token,
      body: { card_data: { ...(got.body?.card_data || {}), iconUrl: logo } } })
    expect(put.status, JSON.stringify(put.body)).toBe(200)
    return 'the selected agent has a logo'
  })

  await seedSession(context, owner.dev.token)
  await seedVault(context, owner, S.did)

  // ── the console alone: (1) the door, (3) the selector ──
  await steps.run('the-order-opens-on-the-guild-board', 'ui:developer', async () => {
    await openRoute(page, `/guild?order=${encodeURIComponent(oid)}`)
    await waitActing(page, S.did)
    await expect(page.locator('.gld-d-head h2'), 'the board opened the order its address named').toHaveText(title, { timeout: 30_000 })
    await expect(page.getByRole('button', { name: /cancel & refund/i }), 'acting still needs the poster agent').toHaveCount(0)
    return 'the door opens the order on the desktop board'
  })

  await steps.run('the-selector-draws-the-logo', 'ui:developer', async () => {
    const face = page.locator('.as-trigger img')
    await expect(face, "the selected agent's own logo in the selector").toHaveAttribute('src', logo, { timeout: 30_000 })
    await expect(page.locator('.as-trigger .fc-blackhole-core')).toHaveCount(0)
    return 'the selector shows the logo'
  })

  // ── (2) the owner reads: from here on the registry must carry them ──
  await steps.run('the-owner-read-names-the-poster', 'ui:developer', async () => {
    const owned = await api.json('GET', '/api/v1/guild/owned', { token: owner.dev.token })
    expect(owned.status, 'the registry answers the owner read (a registry from before V0658 (q) answers 404)').toBe(200)
    const row = (owned.body?.orders || []).find((o: any) => o.id === oid)
    expect(row?.my_parties?.[0]?.agent_did, 'the order is listed as his, by the poster agent').toBe(P.did)
    return 'the owner read names the poster'
  })

  await steps.run('the-owner-line-names-the-agent-that-acts', 'ui:developer', async () => {
    const line = page.locator('[data-testid="gld-owner-line"]')
    await expect(line, 'the owner is told whose order it is').toBeVisible({ timeout: 30_000 })
    await expect(line).toContainText('poster')
    await a11y(page, 'guild-owner-detail')
    return 'the order shows to its owner with another agent selected'
  })

  await steps.run('my-work-lists-it', 'ui:developer', async () => {
    await page.getByRole('button', { name: /^my work$/i }).click()
    await expect(page.locator(`[data-testid="gld-open-${oid}"]`), 'My work holds the order of his other agent').toBeVisible({ timeout: 30_000 })
    await expect(page.locator('[data-testid="gld-mine-parties"]').first()).toContainText('poster')
    return 'My work lists it'
  })
})
