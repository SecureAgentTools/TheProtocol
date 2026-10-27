/**
 * The Forex desk's routing and its cross-currency quote (§FESUITE; the MCP tester's fx quote rows, as a sender meets
 * them). The desk shows the frame's live pairs as the API states them; a recipient that is one of the sender's own
 * agents is a local transfer and asks for no quote; a recipient on the peer frame (another currency) is a cross-frame
 * swap and the desk shows the pool's quote for it, matching the quote the API gives the same agent. Nothing is sent:
 * this lifecycle is a quote, and the balance is read back unchanged.
 */
import { request as pwRequest } from '@playwright/test'
import { test, expect, Api } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { partyWith, peerNativeDid, seedVault, stillFrame, waitActing } from '../support/commerce'
import { PEER_API_URL, PEER_URL } from '../support/env'
import { openRoute } from '../support/ui'

test('forex_route_and_quote', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  if (!PEER_URL) {
    steps.notMeasured('fx-quote', 'ui:agent', 'no peer frame configured (FESUITE_PEER_URL): a cross-currency recipient needs one')
    return
  }
  const sender = await partyWith(api, 'fxsender', 2)
  const [A, B] = sender.agents
  const peerCtx = await pwRequest.newContext({ baseURL: PEER_API_URL })
  const peer = new Api(peerCtx)
  let foreign = ''
  let before = 0

  try {
    await steps.run('the-pairs-the-api-states', 'ui:agent', async () => {
      const r = await api.json('GET', '/api/v1/teg/fx/rates')
      expect(r.body?.available, 'this frame has an FX corridor').toBe(true)
      const pairs: any[] = r.body?.pairs || []
      expect(pairs.length).toBeGreaterThan(0)
      foreign = String(await peerNativeDid(peer, new URL(PEER_URL).hostname) || '')
      expect(foreign, 'an agent native to the peer frame').not.toBe('')
      await expect.poll(() => agentBalance(api, A.token), { timeout: 45_000, message: 'the sender holds its grant' }).toBeGreaterThan(1)
      before = await agentBalance(api, A.token)
      return `${pairs.map((p) => `${p.a}/${p.b}`).join(', ')}; a peer agent to quote against`
    })

    await seedSession(context, sender.dev.token)
    await seedVault(context, sender, A.did)

    await steps.run('the-desk-shows-them', 'ui:agent', async () => {
      await openRoute(page, '/contracts')
      await waitActing(page, A.did)
      await openRoute(page, '/forex')
      const rates = (await api.json('GET', '/api/v1/teg/fx/rates')).body
      const panel = page.locator('[data-tour="fx-rate"]')
      for (const p of rates.pairs) await expect(panel, `the ${p.a}/${p.b} pair`).toContainText(new RegExp(`${p.b}[\\s\\S]*=[\\s\\S]*${p.a}`))
      await expect(page.getByRole('combobox', { name: /pay from agent/i })).toHaveValue(A.did)
      return `${rates.pairs.length} pair(s) on the desk, paying from the acting agent`
    })

    await steps.run('an-own-agent-is-local', 'ui:agent', async () => {
      const quotes: string[] = []
      const onReq = (r: { url(): string }) => { if (/\/teg\/fx\/quote/.test(r.url())) quotes.push(r.url()) }
      page.on('request', onReq)
      await page.locator('#fd-amount').fill('1')
      // the desk offers the sender's other agents as one-press recipients
      const chips = page.locator('.fd-chip')
      await expect(chips.first(), 'the other own agent is offered').toBeVisible()
      await chips.first().click()
      await expect(page.locator('#fd-recipient')).toHaveValue(B.did)
      await expect(page.locator('.fd-route--local'), 'an own agent is a local transfer').toBeVisible()
      await page.waitForTimeout(800) // the quote is debounced (400 ms): give it room to (wrongly) fire
      page.off('request', onReq)
      expect(quotes, 'no quote is asked for a transfer between own agents').toEqual([])
      return 'local transfer, no quote asked'
    })

    await steps.run('a-peer-agent-is-quoted', 'ui:agent', async () => {
      await page.locator('#fd-recipient').fill(foreign)
      const quote = page.locator('.fd-quote:not(.fd-quote--loading)')
      await expect(quote, 'the desk quotes the swap').toBeVisible({ timeout: 30_000 })
      await expect(page.locator('.fd-route--fx'), 'the route is a cross-frame swap').toBeVisible()
      const api_q = (await api.json('POST', '/api/v1/teg/fx/quote', { token: A.token, body: { receiver_did: foreign, amount: '1' } })).body || {}
      expect(api_q.same_currency, 'the API agrees it is cross-currency').toBe(false)
      await expect(quote, 'the destination currency the API names').toContainText(String(api_q.dest_currency))
      await stillFrame(page)
      await a11y(page, 'forex-quote')
      return `1 ${api_q.source_currency} quoted to ${api_q.dest_currency} at ${api_q.rate}`
    })

    await steps.run('nothing-was-sent', 'ui:agent', async () => {
      await expect(page.locator('.fd-send__btn'), 'the send stays a deliberate press').toBeEnabled()
      expect(await agentBalance(api, A.token), 'a quote moves nothing').toBeCloseTo(before, 6)
      return 'balance unchanged'
    })
  } finally {
    await peerCtx.dispose()
  }
})
