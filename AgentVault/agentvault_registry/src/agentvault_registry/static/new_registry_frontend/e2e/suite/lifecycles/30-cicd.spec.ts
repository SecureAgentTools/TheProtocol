/**
 * An agent's CI/CD through the page (§FESUITE; the MCP tester's pipeline_full_crud): build a pipeline with a stage and a
 * step, see its webhook secret once, edit it (the edit changes THAT pipeline, it used to add a second one), tag a
 * version that is not stable, activate it, delete the pipeline through the shared confirm dialog. Every state is read
 * back from the API. The deployments tab must not dial the agent's relay until asked.
 */
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX, uniqueName } from '../support/env'
import { confirmDialog, openRoute, settle, toast } from '../support/ui'
import { listOf, readBack, steady } from '../support/social'

test('cicd_pipeline_and_version', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'cicddev')
  const agent = await createAgentApi(api, dev, 'cicd')
  await seedSession(context, dev.token)
  const name = uniqueName('pipe')
  const renamed = `${name}-v2`
  const pipelines = async () => listOf((await readBack(api, `/api/v1/agents/${agent.did}/pipelines`, dev.token)).body, 'pipelines')
  const versions = async () => listOf((await readBack(api, `/api/v1/agents/${agent.did}/versions`, dev.token)).body, 'versions')
  const tab = (id: string) => page.locator(`[role="tab"][data-tab="${id}"]`)

  await steps.run('open-the-agents-ci-cd', 'ui:developer', async () => {
    expect(await openRoute(page, `/agent/${agent.did}/ci-cd`)).toBe(`/agent/${agent.did}/ci-cd`)
    await expect(tab('builder')).toHaveAttribute('aria-selected', 'true')
    await steady(page)
    await a11y(page, 'cicd-builder')
    return 'the builder tab is open'
  })

  await steps.run('build-a-pipeline-and-see-its-secret-once', 'ui:developer', async () => {
    await page.locator('#cicd-pipeline-name').fill(name)
    await page.locator('#cicd-trigger-type').selectOption('push')
    await page.locator('#cicd-webhook-url').fill(`https://${PREFIX}-ci.invalid/hook`)
    await page.getByRole('button', { name: /add first stage/i }).click()
    await page.getByRole('button', { name: /add step/i }).first().click()
    await page.getByLabel('Step 1 name').fill('Run tests')
    await page.getByLabel('Step 1 command').fill('npm test')
    await page.getByRole('button', { name: /^.?\s*save pipeline$/i }).click()
    await toast(page, 'success', /pipeline created/i)
    const panel = page.locator('[data-testid="cicd-webhook-secret"]')
    await expect(panel, 'the secret is shown in the page, once').toBeVisible()
    const secretLen = (await panel.locator('code').innerText()).trim().length
    expect(secretLen, 'a real secret, not a placeholder').toBeGreaterThan(16)
    await steady(page)
    await a11y(page, 'cicd-webhook-secret')
    await page.locator('[data-testid="cicd-secret-saved"]').click()
    await expect(panel).toHaveCount(0)
    const rows = await pipelines()
    expect(rows.map((p) => p.pipeline_name), 'the API lists the pipeline').toContain(name)
    return `pipeline created with a ${secretLen}-character secret (not recorded)`
  })

  await steps.run('edit-changes-that-pipeline', 'ui:developer', async () => {
    await tab('pipelines').click()
    const card = page.locator('[data-testid="cicd-pipeline"]').filter({ hasText: name })
    await expect(card).toHaveCount(1)
    await steady(page)
    await a11y(page, 'cicd-pipelines')
    await card.locator('[data-action="edit"]').click()
    await expect(page.locator('[data-testid="cicd-editing"]')).toContainText(name)
    await page.locator('#cicd-pipeline-name').fill(renamed)
    await page.getByRole('button', { name: /save changes/i }).click()
    await toast(page, 'success', /pipeline updated/i)
    await expect(page.locator('[data-testid="toast"]').filter({ hasText: /webhook secret replaced/i }),
      'an edit that keeps the URL keeps the secret').toHaveCount(0)
    const rows = await pipelines()
    expect(rows.length, 'still one pipeline, not a copy').toBe(1)
    expect(rows[0].pipeline_name).toBe(renamed)
    return `renamed in place to ${renamed}`
  })

  await steps.run('tag-a-version-not-stable', 'ui:developer', async () => {
    await tab('versions').click()
    await page.getByRole('button', { name: /create version/i }).click()
    const dialog = page.locator('[role="dialog"][aria-labelledby="cicd-version-title"]')
    await expect(dialog).toBeVisible()
    await steady(page)
    await a11y(page, 'cicd-create-version')
    await dialog.locator('#cicd-version-number').fill('1.0.0')
    await dialog.locator('#cicd-version-notes').fill(`${PREFIX} release`)
    await dialog.getByRole('button', { name: /create version/i }).click()
    await toast(page, 'success', /version 1\.0\.0 created/i)
    await expect(dialog).toHaveCount(0)
    const v = (await versions()).find((x) => x.version === '1.0.0')
    expect(v, 'the API lists the version').toBeTruthy()
    expect(v.is_stable, '"Mark as stable" was left unchecked').toBe(false)
    return 'version 1.0.0, not stable'
  })

  await steps.run('activate-the-version', 'ui:developer', async () => {
    const row = page.locator('[data-testid="cicd-version"][data-version="1.0.0"]')
    await row.locator('[data-action="activate"]').click()
    await toast(page, 'success', /version 1\.0\.0 activated/i)
    await expect(row).toContainText(/active/i)
    const v = (await versions()).find((x) => x.version === '1.0.0')
    expect(v?.is_active, 'the API says it is the active version').toBe(true)
    return 'active, read back'
  })

  await steps.run('delete-the-pipeline', 'ui:developer', async () => {
    await tab('pipelines').click()
    await page.locator('[data-testid="cicd-pipeline"]').filter({ hasText: renamed }).locator('[data-action="delete"]').click()
    await confirmDialog(page)
    await toast(page, 'success', /pipeline deleted/i)
    await expect(page.locator('[data-testid="cicd-pipeline"]')).toHaveCount(0)
    expect((await pipelines()).map((p) => p.pipeline_name), 'the API no longer lists it').not.toContain(renamed)
    return 'deleted through the shared dialog, read back'
  })

  await steps.run('deployments-tab-asks-before-dialling', 'ui:developer', async () => {
    const relayCalls: string[] = []
    const onReq = (r: { url(): string }) => { if (/\/relay\/status$/.test(r.url())) relayCalls.push(r.url()) }
    page.on('request', onReq)
    await tab('deployments').click()
    await expect(page.locator('[data-testid="cicd-relay-check"]')).toBeVisible()
    await settle(page)
    await steady(page)
    await a11y(page, 'cicd-deployments')
    page.off('request', onReq)
    expect(relayCalls, 'no relay call until the person asks').toEqual([])
    return 'the relay is asked for, not polled'
  })
  // The relay answer for an agent with no relay is the registry's 503 ("Cannot reach relay"): a backend shape, named in
  // the findings, so the suite does not press the button.
  steps.notMeasured('relay-status', 'ui:developer', 'the registry answers 503 for an agent with no relay (it should say "no relay" in a 200)')
})
