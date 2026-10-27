/**
 * A dispute between two people's agents, through the page (§FESUITE; the MCP tester's log_enhanced_dispute and
 * attestation_full evidence step as people meet them): A's agent files against B's agent with a category and a
 * description, adds evidence; B, acting as the defendant's agent in a browser of their own, answers with evidence of its
 * own. Every state is read back from the API. (The registry keeps no category or description on the dispute row: the
 * console carries the description as the first evidence, which is what the read-back checks.)
 */
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle, toast } from '../support/ui'
import { developerId, listOf, readBack, seedVault, steady } from '../support/social'

test('dispute_filed_evidence_both_sides', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(6 * 60_000)
  const devA = await registerDeveloper(api, 'disputea')
  const devB = await registerDeveloper(api, 'disputeb')
  const a1 = await createAgentApi(api, devA, 'complainant')
  const b1 = await createAgentApi(api, devB, 'defendant')
  await seedSession(context, devA.token)
  await seedVault(context, a1, await developerId(api, devA), 'fesuite complainant')
  const description = `${PREFIX}: the service answered nothing for a paid call`
  let disputeId = 0
  const dispute = async () => (await readBack(api, `/api/v1/disputes/${disputeId}`, devA.token)).body || {}

  await steps.run('open-disputes-acting-as-the-agent', 'ui:agent', async () => {
    expect(await openRoute(page, '/disputes'), 'the agent-only page opens with the agent the console holds').toBe('/disputes')
    await expect(page.locator('[data-tour="dsp-file"]')).toBeVisible()
    await a11y(page, 'disputes')
    return 'the disputes page, acting as the complainant agent'
  })

  await steps.run('file-a-dispute', 'ui:agent', async () => {
    await page.locator('[data-tour="dsp-file"]').click()
    const dialog = page.locator('[role="dialog"][aria-labelledby="fd-title"]')
    await expect(dialog).toBeVisible()
    await dialog.locator('#fd-defendant').fill(b1.did)
    await dialog.locator('#fd-category').selectOption('service_failure')
    await dialog.locator('#fd-description').fill(description)
    await steady(page)
    await a11y(page, 'dispute-file')
    await dialog.getByRole('button', { name: /file dispute/i }).click()
    await toast(page, 'success', /dispute filed/i)
    await expect(dialog).toHaveCount(0)
    const mine = listOf((await readBack(api, `/api/v1/disputes/agent/${a1.did}`, devA.token)).body)
    const d = mine.find((x) => x.defendant_did === b1.did && x.complainant_did === a1.did)
    expect(d, 'the API lists the dispute between the two agents').toBeTruthy()
    disputeId = Number(d.id)
    const first = (d.evidence || [])[0]
    expect(String(first?.evidence_data?.content || ''), 'the description reached the record (as the first evidence)').toBe(description)
    return `dispute #${disputeId}, ${d.status}`
  })

  await steps.run('add-evidence', 'ui:agent', async () => {
    await page.locator('.drc-card').filter({ hasText: `#${disputeId}` }).getByRole('button').last().click()
    const detail = page.locator('.drc-detail-modal[role="dialog"]')
    await expect(detail).toBeVisible()
    await detail.locator('[role="tab"][data-tab="evidence"]').click()
    await detail.getByRole('button', { name: /submit evidence/i }).first().click()
    const ev = page.locator('[role="dialog"][aria-labelledby="dsp-ev-title"]')
    await expect(ev).toBeVisible()
    await steady(page)
    await a11y(page, 'dispute-evidence')
    await ev.locator('#dsp-ev-type').selectOption('link')
    await ev.locator('#dsp-ev-content').fill('https://receipts.invalid/fesuite-call')
    await ev.locator('#dsp-ev-desc').fill('the call that went unanswered')
    await ev.getByRole('button', { name: /submit/i }).last().click()
    await toast(page, 'success', /evidence submitted/i)
    await expect.poll(async () => ((await dispute()).evidence || []).length).toBe(2)
    const second = (await dispute()).evidence[1]
    expect(second.submitter_did).toBe(a1.did)
    expect(second.evidence_data?.content).toBe('https://receipts.invalid/fesuite-call')
    await page.keyboard.press('Escape')
    return 'two pieces of evidence, both from the complainant'
  })

  await steps.run('the-defendant-answers', 'ui:agent', async () => {
    const pageB = await openAs(devB.token)
    await seedVault(pageB.context(), b1, await developerId(api, devB), 'fesuite defendant')
    expect(await openRoute(pageB, '/disputes')).toBe('/disputes')
    await pageB.locator('.drc-card').filter({ hasText: `#${disputeId}` }).getByRole('button').last().click()
    const detail = pageB.locator('.drc-detail-modal[role="dialog"]')
    await expect(detail).toBeVisible()
    await detail.locator('[role="tab"][data-tab="evidence"]').click()
    await detail.getByRole('button', { name: /submit evidence/i }).first().click()
    const ev = pageB.locator('[role="dialog"][aria-labelledby="dsp-ev-title"]')
    await ev.locator('#dsp-ev-content').fill('the service log shows an answer at the time named')
    await ev.getByRole('button', { name: /submit/i }).last().click()
    await toast(pageB, 'success', /evidence submitted/i)
    await settle(pageB)
    await expect.poll(async () => ((await dispute()).evidence || []).length).toBe(3)
    expect((await dispute()).evidence[2].submitter_did, 'the third piece is the defendant\'s').toBe(b1.did)
    return 'the defendant answered with evidence of its own'
  })

  // §SECFIX D6-465: the owners of a dispute's parties read it, and the administrators who rule on it; nobody else. Every
  // read above is a party's, so a dispute any developer could read (as every one could, until V0619) passed this file.
  await steps.run('a-developer-who-is-no-party-reads-nothing', 'ui:developer', async () => {
    const devC = await registerDeveloper(api, 'disputec')
    expect((await readBack(api, `/api/v1/disputes/${disputeId}`, devC.token)).status, 'a stranger reads the dispute').toBe(403)
    expect((await readBack(api, `/api/v1/disputes/agent/${a1.did}`, devC.token)).status,
      'a stranger lists the disputes of an agent it does not own').toBe(403)
    const theirs = listOf((await readBack(api, '/api/v1/disputes/?limit=100', devC.token)).body)
    expect(theirs.some((x) => Number(x.id) === disputeId), 'the dispute in a stranger\'s list').toBe(false)
    expect((await readBack(api, `/api/v1/disputes/${disputeId}`, devB.token)).status, 'the defendant\'s owner reads it').toBe(200)
    return 'a developer who owns neither party: 403, 403, not in its list; the defendant\'s owner reads it'
  })
})
