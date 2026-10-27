/**
 * Notifications through the page (§FESUITE; the MCP tester's notifications_2fa as a person meets it): the bell of a fresh
 * account says all clear; a type's in-app channel is switched on in the preference matrix and back to its default; the
 * broadcast basics auto-save. Every state is read back from the API. Where the frame delivers in-app notifications
 * (NOTIFY_V2_MODE=on) the lifecycle goes on: a real security event (2FA turned on over the API) arrives in the desktop
 * bell, is marked read there, and the unread count the server keeps moves; elsewhere that half is NOT MEASURED with the
 * frame's mode as the reason.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { openRoute, settle } from '../support/ui'
import { nextStepAfter, totp, totpStep } from '../support/totp'
import { readBack, steady } from '../support/social'

const TYPE = 'security.2fa_changed'

test('notifications_preferences_and_bell', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'notifdev')
  await seedSession(context, dev.token)
  const effective = async () => (await readBack(api, '/api/v1/notifications/prefs/effective', dev.token)).body || {}
  const cell = async (channel: string) => {
    const e = await effective()
    const t = (e.types || []).find((x: any) => x.key === TYPE)
    return { mode: String(e.mode || ''), cell: t?.effective?.[channel] || null }
  }
  const basics = async () => (await readBack(api, '/api/v1/developers/me/notification-prefs', dev.token)).body || {}
  const bell = page.locator('.nb-btn').first()
  const dropdown = page.locator('#nb-teleported-dropdown')

  await steps.run('bell-says-all-clear', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=notifications')
    await expect(bell).toHaveAttribute('aria-label', /^0 unread/)
    await bell.click()
    await expect(dropdown).toBeVisible()
    await expect(dropdown).toContainText(/all clear/i)
    await steady(page)
    await a11y(page, 'notifications-bell')
    await bell.click()
    await expect(dropdown).toHaveCount(0)
    return 'a fresh account: 0 unread, all clear'
  })

  const row = page.locator(`.np-mrow[data-type="${TYPE}"]`)
  const inapp = row.locator('input[data-channel="inapp"]')

  await steps.run('switch-in-app-on-for-a-type', 'ui:developer', async () => {
    await expect(row).toBeVisible({ timeout: 20_000 })
    await a11y(page, 'notifications-matrix')
    const before = await cell('inapp')
    expect(before.cell?.enabled, 'in-app is off by default for this type').toBe(false)
    await inapp.locator('xpath=ancestor::label[1]').click()  // the switch's track; the input itself is 0x0
    await expect(inapp).toBeChecked()
    await expect.poll(async () => (await cell('inapp')).cell?.source, { message: 'the API keeps a row for it' }).toBe('row')
    expect((await cell('inapp')).cell?.enabled).toBe(true)
    return `in-app on for ${TYPE} (frame mode ${before.mode})`
  })

  await steps.run('back-to-default', 'ui:developer', async () => {
    await row.getByRole('button', { name: /in-app, back to default/i }).click()
    await expect(inapp).not.toBeChecked()
    await expect.poll(async () => (await cell('inapp')).cell?.source).toBe('default')
    return 'the row is gone; the default (off) applies again'
  })

  await steps.run('broadcast-basics-auto-save', 'ui:developer', async () => {
    const mute = page.getByLabel('Mute Info')
    await expect(mute).not.toBeChecked()
    await mute.check()
    await expect(page.locator('.np-basics-status')).toHaveText(/saved/)
    await expect.poll(async () => (await basics()).mute_info).toBe(true)
    await mute.uncheck()
    await expect.poll(async () => (await basics()).mute_info).toBe(false)
    return 'Mute Info saved on, then off, each read back'
  })

  const { mode } = await cell('inapp')
  if (mode !== 'on') {
    steps.notMeasured('feed-arrives-in-the-bell', 'ui:developer',
      `this frame runs NOTIFY_V2_MODE=${mode || 'unknown'}: the server writes in-app feed entries only in mode on (the store's half is a unit test)`)
    return
  }

  await steps.run('feed-arrives-in-the-bell', 'ui:developer', async () => {
    await inapp.locator('xpath=ancestor::label[1]').click()
    await expect.poll(async () => (await cell('inapp')).cell?.enabled).toBe(true)
    // the event: 2FA turned on over the API (the security lifecycle drives the page for it)
    const setup = await api.json('POST', '/api/v1/auth/2fa/setup', { token: dev.token, body: { password: dev.password } })
    expect(setup.status).toBe(200)
    const secret = String(setup.body?.secret_raw || '').replace(/\s+/g, '')
    const used = totpStep()
    expect((await api.json('POST', '/api/v1/auth/2fa/verify', { token: dev.token, body: { code: totp(secret, used) } })).status).toBe(200)
    try {
      await expect.poll(async () => {
        await bell.click()
        const n = await dropdown.locator(`.nb-feed-item[data-type="${TYPE}"]`).count()
        if (!n) await bell.click()
        return n
      }, { timeout: 30_000, message: 'the 2FA notice reaches the bell' }).toBeGreaterThan(0)
      const unreadBefore = Number((await readBack(api, '/api/v1/notifications/unread-count', dev.token)).body?.count)
      await dropdown.locator(`.nb-feed-item[data-type="${TYPE}"]`).first().getByRole('button', { name: /mark read/i }).click()
      await expect.poll(async () => Number((await readBack(api, '/api/v1/notifications/unread-count', dev.token)).body?.count))
        .toBe(unreadBefore - 1)
    } finally {
      // never leave a throwaway with 2FA on: the sweep signs in with the password alone
      await nextStepAfter(used)
      await api.json('POST', '/api/v1/auth/2fa/disable', { token: dev.token, body: { password: dev.password, code: totp(secret) } })
    }
    await settle(page)
    return 'the event arrived in the bell; marked read there; the server count moved by one'
  })
})
