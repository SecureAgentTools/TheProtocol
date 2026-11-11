/**
 * V0658 (u): an organization's logo, uploaded in its settings the way a person does it (the file input), reaches the
 * registry as a multipart upload and is served back byte for byte. The maintainer's report (sessions' room seq 2174):
 * the upload answered "field required", because the console sent the file as JSON text. The owner creates the
 * organization over the API, opens its settings, picks a PNG, sees the logo, and removes it again; every step is read
 * back from the API. Only the control's data-testids are used, never its words (V0658 (r) rewrites them).
 */
import { test, expect } from '../support/fixtures'
import { ledger, registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { openRoute } from '../support/ui'

/** a real 1x1 PNG: the page hides a logo that does not decode (OrgPublicFace's @error), so a signature alone would fail
 *  the visibility check below; the registry itself checks only the signature */
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mOQz3/9HwAEowJ5toI/yAAAAABJRU5ErkJggg==', 'base64')

test('organization_logo_upload', async ({ page, context, steps, api }) => {
  test.setTimeout(4 * 60_000)
  const owner = await registerDeveloper(api, 'orglogo')
  await seedSession(context, owner.token)
  const orgName = uniqueName('org-logo')
  let orgId = ''

  const servedLogo = async () => {
    const r = await api.ctx.fetch(`/api/v1/organizations/${orgId}/logo`, { failOnStatusCode: false, maxRedirects: 0 })
    return { status: r.status(), type: r.headers()['content-type'] || '', bytes: await r.body() }
  }

  await steps.run('create-organization', 'ui:developer', async () => {
    const r = await api.json('POST', '/api/v1/organizations', { token: owner.token, body: { name: orgName, description: 'made by the console lifecycle suite' } })
    expect(r.status, 'the organization is created').toBeLessThan(300)
    orgId = String(r.body?.id || '')
    expect(orgId, 'the answer names it').not.toBe('')
    ledger('organization', { id: orgId, name: orgName, owner: owner.email })
    expect((await servedLogo()).status, 'no logo yet').toBe(404)
    return `created ${orgName} over the API`
  })

  await steps.run('open-its-settings', 'ui:developer', async () => {
    expect(await openRoute(page, `/organization?org=${orgId}`)).toBe('/organization')
    await page.locator('[data-tour="org-tab-settings"]').click()
    await expect(page.locator('[data-testid="org-public-face"]')).toBeVisible()
    await expect(page.locator('[data-testid="org-logo-input"]')).toBeAttached()
    await expect(page.locator('[data-testid="org-public-face-logo"]')).toHaveCount(0)
    return 'the settings show the logo control, no logo yet'
  })

  await steps.run('upload-the-logo', 'ui:developer', async () => {
    const put = page.waitForResponse((r) => r.url().includes(`/organizations/${orgId}/logo`) && r.request().method() === 'PUT')
    await page.locator('[data-testid="org-logo-input"]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG })
    const resp = await put
    const type = (await resp.request().headerValue('content-type')) || ''
    expect(type, 'the browser sent the file as multipart, with its boundary').toMatch(/^multipart\/form-data; boundary=/)
    expect(resp.status(), 'the registry took it (it answered "field required" while the file went as JSON text)').toBe(200)
    const body = await resp.json()
    expect(body.content_type).toBe('image/png')
    expect(body.size).toBe(PNG.length)
    await expect(page.locator('[data-testid="org-public-face-logo"]'), 'the page shows the logo it now serves').toBeVisible()
    await expect(page.locator('[data-testid="org-logo-error"]')).toHaveCount(0)
    return `PUT /logo ${resp.status()} (${type.split(';')[0]}), ${PNG.length} bytes; the logo is on the page`
  })

  await steps.run('logo-served-byte-for-byte', 'ui:public', async () => {
    const got = await servedLogo()
    expect(got.status).toBe(200)
    expect(got.type).toBe('image/png')
    expect(Buffer.compare(got.bytes, PNG), 'the same bytes the person picked').toBe(0)
    return `GET /logo 200 image/png, ${got.bytes.length} bytes, the same`
  })

  await steps.run('remove-the-logo', 'ui:developer', async () => {
    const del = page.waitForResponse((r) => r.url().includes(`/organizations/${orgId}/logo`) && r.request().method() === 'DELETE')
    await page.locator('[data-testid="org-logo-remove"]').click()
    expect((await del).status()).toBe(200)
    await expect(page.locator('[data-testid="org-public-face-logo"]')).toHaveCount(0)
    expect((await servedLogo()).status, 'no logo served any more').toBe(404)
    return 'removed on the page, read back 404'
  })

  await steps.run('delete-organization', 'ui:developer', async () => {
    // the page leaves first: a dashboard read of an organization deleted under it would be a refusal on a page in use
    await page.goto('about:blank')
    const r = await api.json('DELETE', `/api/v1/organizations/${orgId}`, { token: owner.token })
    expect(r.status, 'the organization is deleted').toBeLessThan(300)
    return 'organization deleted over the API'
  })
})
