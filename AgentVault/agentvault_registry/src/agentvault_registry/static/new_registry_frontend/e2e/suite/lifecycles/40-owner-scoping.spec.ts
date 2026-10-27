/**
 * Owner scoping through the console (§FESUITE; the MCP tester's owner_scoping, as a second person meets it). Developer
 * A owns an agent, an organization, a webhook, a support ticket with its thread and an API key. Developer B, signed in
 * on their own browser, reads B's own lists and opens every door the console has to A's things by address: the agent
 * page and its CI/CD page by DID, the Pocket organization link, the support thread link. Every door must refuse
 * honestly: none of A's private data on screen, no 500, no blank page, words that say it is not B's. Then A's objects
 * are read back from the API: nothing changed. (An agent's DID and public card are public by design; its owner's
 * surfaces are not.)
 */
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { currentRoute, openRoute, settle } from '../support/ui'
import { listAgents, listHooks, listKeys, listOrgs, listTickets, mainText, makeOwned, snapshot } from '../support/hygiene'

test('owner_scoping_second_developer', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(6 * 60_000)
  const a = await registerDeveloper(api, 'ownera')
  const b = await registerDeveloper(api, 'ownerb')
  const agent = await createAgentApi(api, a, 'scoping')
  const owned = await makeOwned(api, a)
  const threadSubject = `${owned.ticketSubject}-thread`
  const threadText = 'owner-scoping fixture thread: A wrote this'
  const thread = await api.json('POST', '/api/v1/chat/support/open', { token: a.token, body: { subject: threadSubject, message: threadText } })
  const convId = String(thread.body?.conversation_id || '')
  const before = await snapshot(api, a)
  await seedSession(context, b.token)

  // A's private names: none may reach B's screen. (The agent's DID is public; its owner's surfaces are not.)
  const privateMarks = [owned.orgName, owned.hookUrl.slice(8, 40), owned.ticketSubject, owned.keyName, threadText]
  const showsNoneOfA = async (where: string) => {
    // the whole document: the console mounts two elements with id="app" (index.html's root and App.vue's), a finding
    const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    const leaked = privateMarks.filter((m) => text.includes(m))
    expect(leaked, `${where} shows none of A's private names`).toEqual([])
  }

  await steps.run('b-lists-hold-none-of-a', 'ui:developer', async () => {
    for (const route of ['/organization', '/webhooks', '/support', '/api-keys', '/my-agents']) {
      expect(await openRoute(page, route), `${route} opens for B`).toBe(route)
      await showsNoneOfA(route)
    }
    await expect(page.locator(`[data-did="${agent.did}"]`), 'A\'s agent is not on B\'s fleet').toHaveCount(0)
    const [o, h, t, k, g] = await Promise.all([listOrgs(api, b), listHooks(api, b), listTickets(api, b), listKeys(api, b), listAgents(api, b)])
    expect(o.some((x) => String(x.id) === owned.orgId), 'B\'s organizations').toBe(false)
    expect(h.some((x) => String(x.id) === owned.hookId), 'B\'s webhooks').toBe(false)
    expect(t.some((x) => String(x.id) === owned.ticketId), 'B\'s tickets').toBe(false)
    expect(k.some((x) => String(x.id) === owned.keyId), 'B\'s keys').toBe(false)
    expect(g.some((x) => x.did === agent.did), 'B\'s agents').toBe(false)
    return 'five lists, on the page and in the API, hold none of A\'s objects'
  })

  await steps.run('a-agent-page-is-public-only', 'ui:developer', async () => {
    const landed = await openRoute(page, `/agent/${encodeURIComponent(agent.did)}`)
    expect(landed.startsWith('/agent/'), `the agent page opens (landed ${landed})`).toBe(true)
    await settle(page)
    const text = await mainText(page)
    expect(text.length, 'the page is not blank').toBeGreaterThan(40)
    await showsNoneOfA('A\'s agent page')
    // the owner's surfaces stay closed: editing, credentials, authority
    await expect(page.getByRole('button', { name: /^(edit|save changes|reset keys|reset credentials|decommission)/i })).toHaveCount(0)
    await expect(page.getByRole('tab', { name: /^(access|lineage)$/i })).toHaveCount(0)
    await expect(page.locator('[data-testid="agd-not-yours"]'), 'the page says whose agent this is').toBeVisible()
    await a11y(page, 'scoping-agent-page')
    return text.slice(0, 120)
  })

  await steps.run('a-org-link-refused', 'ui:developer', async () => {
    await openRoute(page, `/pocket/orgs?org=${encodeURIComponent(owned.orgId)}`)
    await settle(page)
    await showsNoneOfA('the Pocket organization link')
    const said = page.locator('[data-testid="po-notyours"]')
    await expect(said, 'the page says the link names an organization B is not in').toBeVisible()
    await a11y(page, 'scoping-pocket-org-link')
    return (await said.innerText()).replace(/\s+/g, ' ').slice(0, 140)
  })

  await steps.check('a-support-thread-refused', 'ui:developer', async () => {
    expect(convId, 'A\'s support ticket opened a thread').not.toBe('')
    capture.allow(new RegExp(`GET /api/v1/chat/conversations/${convId}(/.*)?$`), [403, 404], 'B asks for A\'s thread; the API refuses')
    await openRoute(page, `/pocket/ourchat/${encodeURIComponent(convId)}`)
    await settle(page)
    const text = await mainText(page)
    await showsNoneOfA('A\'s support thread link')
    expect(text.length, 'the page is not blank').toBeGreaterThan(20)
    expect(text, 'the page says the thread is not B\'s').toMatch(/not (found|yours|a participant|available)|no access|cannot|isn.t yours|not part of/i)
    await a11y(page, 'scoping-support-thread-link')
    return `landed ${await currentRoute(page)}: ${text.slice(0, 120)}`
  })

  await steps.run('nothing-of-a-changed', 'ui:developer', async () => {
    const after = await snapshot(api, a)
    expect(after, 'A\'s organizations, webhooks, tickets, keys and agents read back unchanged').toBe(before)
    return 'A\'s objects read back unchanged'
  })

  steps.assertChecks()
})

/**
 * The CI/CD door on its own (§FESUITE): it is a different surface's (the CI/CD view's) refusal, kept apart so the
 * scoping lifecycle above measures its own doors. B opens A's agent's CI/CD page by DID: the page must say it is not
 * B's, never show "0 pipelines" for an agent B cannot see.
 */
test('owner_scoping_cicd_door', async ({ page, context, steps, api, a11y }) => {
  const a = await registerDeveloper(api, 'cicdowner')
  const b = await registerDeveloper(api, 'cicdother')
  const agent = await createAgentApi(api, a, 'scoping-cicd')
  await seedSession(context, b.token)
  await steps.run('a-agent-cicd-refused', 'ui:developer', async () => {
    const landed = await openRoute(page, `/agent/${encodeURIComponent(agent.did)}/ci-cd`)
    await settle(page)
    const text = await mainText(page)
    expect(text.length, 'the page is not blank').toBeGreaterThan(20)
    // A refusal is said in words; "0 pipelines" for an agent you cannot see is an error dressed as an empty state.
    expect(text, 'the page says the agent is not B\'s').toMatch(/not (your|yours|owned)|another developer|no access|not allowed|permission|forbidden|cannot (see|manage)/i)
    await a11y(page, 'scoping-agent-cicd')
    return `landed ${landed}: ${text.slice(0, 120)}`
  })

})
