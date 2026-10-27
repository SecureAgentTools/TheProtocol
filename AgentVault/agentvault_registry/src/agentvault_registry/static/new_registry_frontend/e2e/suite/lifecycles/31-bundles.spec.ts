/**
 * A bundle through the page (§FESUITE; the MCP tester's bundle_full_crud as a person meets it): snapshot an agent into a
 * private bundle, read its manifest, download the signed archive, delete it through the shared confirm dialog. Every
 * state is read back from the API. (The console offers no way to edit a bundle's name, description or visibility; the
 * API has PATCH /bundles/{id}. Named in the findings, not driven.)
 */
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import fs from 'node:fs'
import path from 'node:path'
import { OUT_DIR, PREFIX, uniqueName } from '../support/env'
import { confirmDialog, openRoute, toast } from '../support/ui'
import { listOf, readBack, steady } from '../support/social'

test('bundle_snapshot_manifest_download_delete', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(4 * 60_000)
  const dev = await registerDeveloper(api, 'bundledev')
  const agent = await createAgentApi(api, dev, 'bundle')
  await seedSession(context, dev.token)
  const name = uniqueName('bundle')
  const mine = async () => listOf((await readBack(api, '/api/v1/bundles', dev.token)).body, 'bundles')
  const card = () => page.locator('.bdl-card').filter({ hasText: name })

  await steps.run('empty-shelf', 'ui:developer', async () => {
    expect(await openRoute(page, '/bundles')).toBe('/bundles')
    await expect(page.locator('[role="tab"][data-tab="mine"]')).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByText(/no bundles yet/i)).toBeVisible()
    await steady(page)
    await a11y(page, 'bundles-empty')
    return 'My Bundles is empty and says so'
  })

  await steps.run('snapshot-an-agent', 'ui:developer', async () => {
    await page.locator('[data-tour="bdl-new"]').click()
    const dialog = page.locator('[role="dialog"][aria-labelledby="bdl-new-title"]')
    await expect(dialog).toBeVisible()
    const row = dialog.locator(`.bdl-agent-row[data-did="${agent.did}"]`)
    await expect(row, 'the agent made over the API is offered').toBeVisible({ timeout: 20_000 })
    await steady(page)
    await a11y(page, 'bundle-new')
    await dialog.locator('#bdl-new-name').fill(name)
    await dialog.locator('#bdl-new-description').fill(`${PREFIX} snapshot`)
    await expect(dialog.locator('#bdl-new-visibility')).toHaveValue('private')
    await row.click()
    await expect(row).toHaveAttribute('aria-pressed', 'true')
    await dialog.getByRole('button', { name: /create bundle/i }).click()
    await toast(page, 'success', /bundle created/i)
    await expect(dialog).toHaveCount(0)
    await expect(card()).toHaveCount(1)
    const b = (await mine()).find((x) => x.name === name)
    expect(b, 'the API lists the bundle').toBeTruthy()
    expect(b.visibility).toBe('private')
    expect(b.kind).toBe('snapshot')
    return `bundle ${String(b.id).slice(0, 8)}… private snapshot`
  })

  await steps.run('read-the-manifest', 'ui:developer', async () => {
    await card().getByRole('button', { name: /view/i }).click()
    const drawer = page.locator('[role="dialog"][aria-labelledby="bdl-drawer-title"]')
    await expect(drawer).toBeVisible()
    await expect(drawer.locator('#bdl-drawer-title')).toHaveText(name)
    await expect(drawer, 'the manifest names the agent it carries').toContainText(agent.did)
    await steady(page)
    await a11y(page, 'bundle-manifest')
    await drawer.getByRole('button', { name: /close/i }).click()
    await expect(drawer).toHaveCount(0)
    return 'manifest names the agent'
  })

  await steps.run('download-the-archive', 'ui:developer', async () => {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 30_000 }),
      card().getByRole('button', { name: /download/i }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/\.tpb$/)
    // the browser is remote (the suite's network namespace): save a copy here, measure it, remove it
    const file = path.join(OUT_DIR, `download-${Date.now()}.tpb`)
    await download.saveAs(file)
    const size = fs.statSync(file).size
    fs.rmSync(file, { force: true })
    expect(size, 'the archive has content').toBeGreaterThan(100)
    return `${download.suggestedFilename()} (${size} bytes)`
  })

  await steps.run('delete-it', 'ui:developer', async () => {
    await card().locator('[data-action="delete"]').click()
    await confirmDialog(page)
    await toast(page, 'success', /bundle deleted/i)
    await expect(card()).toHaveCount(0)
    const left = (await mine()).filter((x) => x.name === name && x.is_active !== false && x.deleted_at == null)
    expect(left, 'the API no longer lists it as live').toEqual([])
    return 'deleted, read back'
  })
})
