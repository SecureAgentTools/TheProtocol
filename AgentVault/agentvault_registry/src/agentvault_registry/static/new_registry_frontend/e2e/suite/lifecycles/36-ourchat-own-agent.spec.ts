/**
 * What my own agent posts, in my thread (§FESUITE; V0659 (o), order gwo_d7ce94c88a55f629c17b4ff7). The maintainer, in
 * the sessions' room (seq 1833): "if any of my agents use any card, i should also see it ... maybe opake or some other
 * indicator/distinction so the dev knows this is from his agent and not posted by him/his dev account."
 *
 * A developer owns an agent; the agent opens a thread with him and writes a line and a progress card, and he writes a
 * line of his own. He opens the thread (the console's /ourchat on the desktop, Pocket's /pocket/ourchat on a phone): his
 * agent's card is there, drawn as his agent's (a lighter frame and the "your agent" mark beside the agent's name), and his
 * own line is drawn as it always was. The registry's word is read back as him: sender_is_my_agent on his agent's lines,
 * never on his own.
 */
import crypto from 'node:crypto'
import { test, expect } from '../support/fixtures'
import { agentToken, createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle } from '../support/ui'
import { sideScroll } from '../support/pages'
import { developerId, listOf, readBack, steady } from '../support/social'

test('ourchat_owner_sees_his_agents_card_marked @phone', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'chatown')
  const ownerId = Number(await developerId(api, dev))
  const agent = await createAgentApi(api, dev, 'chatown')
  const agentJwt = await agentToken(api, agent)
  await seedSession(context, dev.token)
  const onPhone = (page.viewportSize()?.width ?? 1440) < 900
  const ref = () => `fes-${crypto.randomBytes(6).toString('hex')}`
  const said = `${PREFIX}: the proof is running`
  const mine = `${PREFIX}: thanks, I am watching`
  const progressTitle = `${PREFIX} pair proof`
  let convId = ''
  let cardSeq = 0
  let ownSeq = 0
  let agentName = ''

  await steps.run('his-agent-writes-to-him', 'ui:agent', async () => {
    const c = await api.json('POST', '/api/v1/chat/conversations', { token: agentJwt,
      body: { kind: 'dm', target: { ptype: 'developer', developer_id: ownerId } } })
    expect(c.status, `the agent opens a thread with its owner: ${JSON.stringify(c.body).slice(0, 200)}`).toBeLessThan(300)
    convId = String(c.body?.conversation_id || '')
    expect(convId).not.toBe('')
    const line = await api.json('POST', `/api/v1/chat/conversations/${convId}/messages`, { token: agentJwt,
      body: { kind: 'text', body: said, client_ref: ref() } })
    expect(line.status, 'the agent\'s line').toBe(201)
    const card = await api.json('POST', `/api/v1/chat/conversations/${convId}/messages`, { token: agentJwt,
      body: { kind: 'card', client_ref: ref(), card: { v: 1, type: 'progress',
        data: { title: progressTitle, state: 'running', steps: [{ label: 'console', state: 'done' }, { label: 'pair', state: 'running' }] } } } })
    expect(card.status, `the agent's progress card: ${JSON.stringify(card.body).slice(0, 200)}`).toBe(201)
    cardSeq = Number(card.body?.message?.seq || 0)
    const own = await api.json('POST', `/api/v1/chat/conversations/${convId}/messages`, { token: dev.token,
      body: { kind: 'text', body: mine, client_ref: ref() } })
    expect(own.status, 'his own line').toBe(201)
    ownSeq = Number(own.body?.message?.seq || 0)
    // the registry's word, read back as him: his agent's lines are his agent's, his own line is not
    const read = listOf((await readBack(api, `/api/v1/chat/conversations/${convId}/messages`, dev.token)).body, 'messages')
    const bySeq = new Map(read.map((m: any) => [Number(m.seq), m]))
    expect(bySeq.get(cardSeq)?.sender_is_my_agent, 'his agent\'s card, as he reads it').toBe(true)
    expect(bySeq.get(ownSeq)?.sender_is_my_agent, 'his own line, as he reads it').toBe(false)
    agentName = String(bySeq.get(cardSeq)?.sender_name || '')
    return `thread ${convId.slice(0, 8)}…: the agent's line and card (seq ${cardSeq}), his line (seq ${ownSeq})`
  })

  await steps.run('he-sees-his-agents-card-marked', 'ui:developer', async () => {
    const route = onPhone ? `/pocket/ourchat/${convId}` : `/ourchat/${convId}`
    expect(await openRoute(page, route), `${route} opens`).toBe(route)
    const cardLine = page.locator(`[data-testid="ost-msg-${cardSeq}"]`)
    await expect(cardLine.locator('[data-testid="osc-progress"]'), 'his agent\'s card is in the thread').toBeVisible({ timeout: 30_000 })
    await expect(cardLine.getByText(progressTitle)).toBeVisible()
    await expect(cardLine, 'drawn as his agent\'s').toHaveClass(/(^|\s)my-agent(\s|$)/)
    // the mark heads the agent's lines, beside its name
    const mark = page.locator('[data-testid="ost-my-agent"]').first()
    await expect(mark).toBeVisible()
    await expect(mark).toHaveText(/your agent/i)
    const author = page.locator('.ost-author.my-agent').first()
    if (agentName) await expect(author, 'the agent\'s name heads its lines').toContainText(agentName)
    // his own line is drawn as it always was: his, no mark
    const ownLine = page.locator(`[data-testid="ost-msg-${ownSeq}"]`)
    await expect(ownLine.getByText(mine)).toBeVisible()
    await expect(ownLine).toHaveClass(/(^|\s)mine(\s|$)/)
    await expect(ownLine).not.toHaveClass(/(^|\s)my-agent(\s|$)/)
    await expect(page.locator(`[data-testid="ost-author-${ownSeq}"] [data-testid="ost-my-agent"]`)).toHaveCount(0)
    await settle(page)
    await steady(page)
    if (onPhone) expect(await sideScroll(page), 'the thread does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, onPhone ? 'pocket-ourchat-own-agent' : 'ourchat-own-agent')
    return `${route}: the card under "your agent"${agentName ? ` (${agentName})` : ''}, his own line unmarked`
  })
})
