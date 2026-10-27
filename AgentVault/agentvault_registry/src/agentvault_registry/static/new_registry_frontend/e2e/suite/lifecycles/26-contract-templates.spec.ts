/**
 * Contract templates through the Contracts page (§FESUITE; the MCP tester's template rows). Publishing a template is a
 * grant-only authority (contract.template.publish), never a birth role and never delegatable: a fresh agent opens the
 * Templates tab, finds what the frame offers, tries to author one and is refused in words that name the authority.
 * Nothing is created (read back). One refusal says one thing: the form's sentence, not a second generic alarm.
 */
import { test, expect } from '../support/fixtures'
import { seedSession } from '../support/accounts'
import { partyWith, seedVault, stillFrame, waitActing } from '../support/commerce'
import { uniqueName } from '../support/env'
import { openRoute } from '../support/ui'

test('contract_templates_are_a_granted_authority', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(4 * 60_000)
  const author = await partyWith(api, 'tplauthor', 1)
  const [A] = author.agents
  const slug = uniqueName('tpl').toLowerCase().replace(/[^a-z0-9-]/g, '-').slice(0, 60)
  const mine = async () => {
    const r = await api.json('GET', '/api/v1/contracts/templates?mine=true&limit=50', { token: A.token })
    return (r.body?.items || []) as any[]
  }

  await seedSession(context, author.dev.token)
  await seedVault(context, author, A.did)

  await steps.run('the-templates-tab', 'ui:agent', async () => {
    await openRoute(page, '/contracts')
    await waitActing(page, A.did)
    await page.locator('[data-tour="contracts-tab-templates"]').click()
    const listed = (await api.json('GET', '/api/v1/contracts/templates?limit=5', { token: A.token })).body?.items || []
    if (!listed.length) await expect(page.locator('[data-tour="tpl-new-empty"]'), 'an empty catalogue offers authoring').toBeVisible({ timeout: 30_000 })
    await stillFrame(page)
    await a11y(page, 'contract-templates')
    return `${listed.length} template(s) on this frame`
  })

  await steps.run('authoring-is-refused-in-words', 'ui:agent', async () => {
    capture.allow(/POST \/api\/v1\/contracts\/templates$/, 403, 'a fresh agent holds no contract.template.publish (grant-only, never a birth role)')
    const door = page.locator('[data-tour="tpl-new-empty"], [data-tour="tpl-new"]').first()
    await door.click()
    await page.getByRole('textbox', { name: /slug/i }).fill(slug)
    await page.getByRole('textbox', { name: /^title/i }).fill(`Template ${slug}`)
    await page.locator('[data-tour="tpl-create-submit"]').click()
    const hint = page.locator('[data-tour="tpl-create-hint"]')
    await expect(hint, 'the form says why').toBeVisible({ timeout: 30_000 })
    await expect(hint).toContainText(/contract\.template\.publish|permission/i)
    expect(await mine(), 'nothing was created').toEqual([])
    return (await hint.innerText()).slice(0, 120)
  })

  await steps.check('one-refusal-one-message', 'ui:agent', async () => {
    // The form already named the refusal; the global API handler's generic "Access Denied" toast is a second,
    // vaguer message for the same event.
    await expect(page.locator('[data-testid="toast"][data-kind="error"]').filter({ hasText: /access denied/i }),
      'no second, generic alarm for a refusal the form explains').toHaveCount(0)
    return 'one message'
  })
  steps.assertChecks()
})
