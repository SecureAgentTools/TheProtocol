import { describe, it, expect } from 'vitest'
import {
  AGENTS_LIMIT, BALANCE_CHUNK, cardFileName, chunks, classifyBalance, firstIsWallet, fundingKind, isGone, isSlice,
  isSuspended, issueRefusal, proofWasRefused, resetRefusal, serverMessage, shortDid, useItSnippet, validationPassed,
  visibleAgents,
} from './quickOnboarding'
import { agentSlug, nameMark } from './agentSlug'

/**
 * Quick onboarding (2026-10-09): the page's decisions, each on its own. Every rule here was a way a page could say
 * something untrue: a deleted agent listed as yours, a failed balance read shown as 0, a failed agents read taken for
 * "no agents" (and a hidden wallet made for a person who has agents), a skipped validation shown as valid.
 */
const refused = (status: number, data: unknown) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } })

describe('agentSlug: the card handle and the endpoint path segment', () => {
  it('keeps [a-z0-9-], drops accents, collapses the rest into single dashes', () => {
    expect(agentSlug('Research Assistant')).toBe('research-assistant')
    expect(agentSlug('  Café Bot #1? / ünïcode%  ')).toBe('cafe-bot-1-unicode')
    expect(agentSlug('a__b--c  d')).toBe('a-b-c-d')
    expect(agentSlug('ÅNGSTRÖM 2.0')).toBe('angstrom-2-0')
  })
  it('a name with nothing usable is "agent"; a long one is cut to 64 without a trailing dash', () => {
    expect(agentSlug('!!! ???')).toBe('agent')
    expect(agentSlug('')).toBe('agent')
    expect(agentSlug(undefined)).toBe('agent')
    const long = agentSlug(`${'x'.repeat(63)} y z`)
    expect(long.length).toBeLessThanOrEqual(64)
    expect(long.endsWith('-')).toBe(false)
  })
  it('Latin letters Unicode does not decompose keep a base too', () => {
    expect(agentSlug('Straße')).toBe('strasse')
    expect(agentSlug('Đà Nẵng bot')).toBe('da-nang-bot')
    expect(agentSlug('Ørsted Æble')).toBe('orsted-aeble')
    // a symbol is not a letter: it drops like punctuation and asks for no mark
    expect(agentSlug('Bot 🤖')).toBe('bot')
  })
  it('a name in a script with no Latin base gets a handle of its own, not the one shared "agent"', () => {
    const cjk = agentSlug('研究助手')
    const ja = agentSlug('翻訳ボット')
    const ru = agentSlug('Помощник')
    for (const h of [cjk, ja, ru, agentSlug('مساعد')]) expect(h).toMatch(/^agent-[0-9a-f]{6}$/)
    expect(new Set([cjk, ja, ru]).size).toBe(3)
    // the same name always gets the same handle (the hint shows what will be sent), whatever its case or spacing
    expect(agentSlug('研究助手')).toBe(cjk)
    expect(agentSlug('  ПОМОЩНИК ')).toBe(ru)
    expect(cjk).toBe(`agent-${nameMark('研究助手')}`)
    // a name partly in Latin keeps its Latin part, and the mark tells it from another such name
    expect(agentSlug('Помощник 2')).toMatch(/^2-[0-9a-f]{6}$/)
    expect(agentSlug('한국 agent')).toMatch(/^agent-[0-9a-f]{6}$/)
    // still a slug of [a-z0-9-], at most 64 characters
    const long = agentSlug('研'.repeat(90) + ' ' + 'x'.repeat(80))
    expect(long).toMatch(/^[a-z0-9-]+$/)
    expect(long.length).toBeLessThanOrEqual(64)
    expect(long).toMatch(/-[0-9a-f]{6}$/)
  })
})

describe('the agents list', () => {
  const rows = [
    { did: 'did:theprotocol:a', status: 'active', name: 'A' },
    { did: 'did:theprotocol:b', status: 'revoked', name: 'Deleted' },
    { did: 'did:theprotocol:c', status: 'suspended', name: 'C' },
    { did: 'did:theprotocol:d', status: 'deleted', name: 'Old row' },
    { did: '', status: 'active', name: 'No DID' },
    null,
    { did: 'did:theprotocol:e', name: 'No status' },
  ]
  it('drops what the owner deleted (revoked, deleted) and rows without a DID; keeps suspended, in the server order', () => {
    expect(visibleAgents(rows).map((r) => r.did)).toEqual(['did:theprotocol:a', 'did:theprotocol:c', 'did:theprotocol:e'])
    expect(visibleAgents(null)).toEqual([])
    expect(isGone('REVOKED')).toBe(true)
    expect(isGone('active')).toBe(false)
  })
  it('a suspended agent is labelled (and gets no reset); an active one is not', () => {
    expect(isSuspended('suspended')).toBe(true)
    expect(isSuspended('Suspended')).toBe(true)
    expect(isSuspended('active')).toBe(false)
    expect(isSuspended(undefined)).toBe(false)
  })
  it('a full page is a slice the page says out loud', () => {
    expect(AGENTS_LIMIT).toBe(100)
    expect(isSlice(100)).toBe(true)
    expect(isSlice(99)).toBe(false)
  })
  it('the first identity is the wallet only after a read that answered with no live agent', () => {
    expect(firstIsWallet({ ok: true, searched: false, rows: [] })).toBe(true)
    // only deleted agents: none is live
    expect(firstIsWallet({ ok: true, searched: false, rows: [{ did: 'did:x', status: 'revoked' }] })).toBe(true)
    // a failed read is not "no agents"
    expect(firstIsWallet({ ok: false, searched: false, rows: [] })).toBe(false)
    // a search that found nothing says nothing about the account
    expect(firstIsWallet({ ok: true, searched: true, rows: [] })).toBe(false)
    // control: a person with a live agent
    expect(firstIsWallet({ ok: true, searched: false, rows: [{ did: 'did:x', status: 'active' }] })).toBe(false)
    // a full page of deleted agents says nothing about the older rows beyond it
    const deleted = Array.from({ length: AGENTS_LIMIT }, (_, i) => ({ did: `did:x:${i}`, status: 'revoked' }))
    expect(firstIsWallet({ ok: true, searched: false, rows: deleted, rawCount: AGENTS_LIMIT })).toBe(false)
    expect(firstIsWallet({ ok: true, searched: false, rows: deleted })).toBe(false)
    expect(firstIsWallet({ ok: true, searched: false, rows: deleted.slice(1), rawCount: AGENTS_LIMIT - 1 })).toBe(true)
  })
  it('a DID shortened keeps its method and the head and tail of its UUID; a namespaced one says the issuer was left out', () => {
    expect(shortDid('did:theprotocol:0f0e0d0c-0b0a-4000-8000-000000000001')).toBe('did:theprotocol:0f0e0d0c…000001')
    expect(shortDid('did:theprotocol:sandbox-a.theprotocol.cloud:e3fc998c-91ab-40ff-9c5e-907808420405'))
      .toBe('did:theprotocol:…:e3fc998c…420405')
    expect(shortDid('did:theprotocol:5d1c0e2a9b7f4e11a0b2')).toBe('did:theprotocol:5d1c0e2a9b7f4e11a0b2')
    expect(shortDid('did:short')).toBe('did:short')
    expect(shortDid('')).toBe('')
  })
})

describe('classifyBalance: one entry of the balances batch', () => {
  it('a reading is a number with the frame currency', () => {
    expect(classifyBalance({ balance: '1000.000000', currency: 'ECU' }, 'XXX')).toEqual({ state: 'ok', amount: '1000.000000', currency: 'ECU' })
    expect(classifyBalance({ balance: '1E+3' }, 'ACU')).toEqual({ state: 'ok', amount: '1E+3', currency: 'ACU' })
    expect(classifyBalance({ balance: '0' }, 'ECU')).toEqual({ state: 'ok', amount: '0', currency: 'ECU' })
  })
  it('the error key is read FIRST: "0" with an error is unread, with the registry\'s own reason', () => {
    expect(classifyBalance({ balance: '0', currency: 'ECU', error: 'Agent is suspended' }, 'ECU'))
      .toEqual({ state: 'unread', why: 'error', detail: 'Agent is suspended', currency: 'ECU' })
  })
  it('no entry, or no number in it, is unread too, as a code the page puts into words (no English in here)', () => {
    expect(classifyBalance(undefined, 'ECU')).toEqual({ state: 'unread', why: 'no_entry', detail: '', currency: 'ECU' })
    expect(classifyBalance({ balance: 'n/a' }, 'ECU')).toEqual({ state: 'unread', why: 'no_number', detail: '', currency: 'ECU' })
    expect(classifyBalance({}, 'ECU')).toMatchObject({ state: 'unread', why: 'no_number' })
  })
  it('chunks of at most 50 DIDs', () => {
    const dids = Array.from({ length: 101 }, (_, i) => `did:${i}`)
    const c = chunks(dids)
    expect(BALANCE_CHUNK).toBe(50)
    expect(c.map((x) => x.length)).toEqual([50, 50, 1])
    expect(c.flat()).toEqual(dids)
    expect(chunks([])).toEqual([])
  })
})

describe('fundingKind: the starting balance in initial_funding_status', () => {
  // routers/onboarding.py: "deferred" is returned when the treasury is below its floor and the grant does not run at all
  // (:389); "partial" when the funding chain ran out and the shortfall is never paid (:422-428). mint_genesis_grant has
  // one caller (create_agent) and nothing runs it again, so neither is "pending": the page must not promise money.
  it('completed is credited; partial, deferred, failed and error are each their own fact, none of them "pending"', () => {
    expect(fundingKind('completed')).toBe('credited')
    expect(fundingKind('partial')).toBe('partial')
    expect(fundingKind('deferred')).toBe('deferred')
    expect(fundingKind('failed')).toBe('failed')
    expect(fundingKind('error')).toBe('failed')
  })
  it('no starting balance was due: nothing to say', () => {
    expect(fundingKind('not_first_agent')).toBeNull()
    expect(fundingKind('not_eligible')).toBeNull()
    expect(fundingKind(undefined)).toBeNull()
    expect(fundingKind('something new')).toBeNull()
  })
})

describe('refusals', () => {
  it('the registry sentence, from detail or the RFC 7807 body', () => {
    expect(serverMessage(refused(400, { detail: 'Invalid agent card: name' }))).toBe('Invalid agent card: name')
    expect(serverMessage(refused(400, { error: { detail: 'Wrapped' } }))).toBe('Wrapped')
    expect(serverMessage(refused(422, { detail: [{ msg: 'field required' }] }))).toBe('field required')
    expect(serverMessage(refused(502, '<html>bad gateway</html>'))).toBe('')
    expect(serverMessage(new Error('no response'))).toBe('')
  })
  it('an issue refused to an unverified developer, by the rate limit, or for another reason', () => {
    expect(issueRefusal(refused(403, { detail: 'Only verified developers can request bootstrap tokens' })).kind).toBe('unverified')
    expect(issueRefusal(refused(429, { detail: 'Rate limit exceeded' })).kind).toBe('rate_limited')
    expect(issueRefusal(refused(400, { detail: 'Invalid agent card: x' }))).toEqual({ kind: 'other', message: 'Invalid agent card: x' })
    // control: a 403 for another reason is not "unverified"
    expect(issueRefusal(refused(403, { detail: 'Developer suspended' })).kind).toBe('other')
  })
  it('a reset: the step-up 401 carries a challenge; any other 401 is the session', () => {
    const body = { error: 'step_up_required', message: 'Confirm', step_up: { reason: 'second factor required', challenge_id: 'lch_1', challenge_hash: 'h', facts: {}, expires_at: '2030-01-01T00:00:00Z', ttl_seconds: 120, methods: ['totp'] } }
    const r = resetRefusal(refused(401, body))
    expect(r.kind).toBe('step_up')
    expect(r.kind === 'step_up' && r.challenge.challengeId).toBe('lch_1')
    expect(r.kind === 'step_up' && r.challenge.methods).toEqual(['totp'])
    expect(resetRefusal(refused(401, { detail: 'Not authenticated' })).kind).toBe('session')
  })
  it('a reset: 403 is the password unless the agent is not yours; 400, 404 and 429 each say their own', () => {
    expect(resetRefusal(refused(403, { detail: 'Invalid password. Credential reset requires your current account password.' })).kind).toBe('wrong_password')
    expect(resetRefusal(refused(403, { detail: 'You do not own this agent. Only the creator can reset credentials.' })).kind).toBe('not_owner')
    expect(resetRefusal(refused(404, { detail: 'Agent not found' })).kind).toBe('not_found')
    expect(resetRefusal(refused(400, { detail: "Cannot reset credentials for agent with status 'suspended'." })))
      .toEqual({ kind: 'inactive', message: "Cannot reset credentials for agent with status 'suspended'." })
    expect(resetRefusal(refused(429, {})).kind).toBe('rate_limited')
    expect(resetRefusal(new Error('network')).kind).toBe('other')
  })
  it('a step-up answer after a proof names why the proof was refused; the first one does not', () => {
    expect(proofWasRefused('second factor required')).toBe(false)
    expect(proofWasRefused('challenge is pending')).toBe(true)
    expect(proofWasRefused('')).toBe(false)
  })
})

describe('the card', () => {
  it('only a validation that checked and said valid is positive', () => {
    expect(validationPassed({ is_valid: true, validated_card_data: {} })).toBe(true)
    expect(validationPassed({ is_valid: true, detail: null })).toBe(true)
    // a registry without the core library answers "valid" without looking
    expect(validationPassed({ is_valid: true, detail: 'Validation skipped: Core library not available.' })).toBe(false)
    expect(validationPassed({ is_valid: false, detail: 'name required' })).toBe(false)
    expect(validationPassed(null)).toBe(false)
  })
  it('a downloaded card is named by its slug, never the DID', () => {
    expect(cardFileName('research-assistant')).toBe('research-assistant.agent-card.json')
    expect(cardFileName('')).toBe('agent.agent-card.json')
    expect(cardFileName('did:theprotocol:x')).toBe('did-theprotocol-x.agent-card.json')
  })
  it('the "use it" command reads the secret from the shell and never carries it', () => {
    const s = useItSnippet('https://registry.example.test/api/v1/auth/agent/token', 'agent-0123456789abcdef')
    // the first line asks for the secret without showing it (and keeps it out of the shell's history)
    expect(s.split('\n')[0]).toMatch(/^read -rs CLIENT_SECRET\b/)
    expect(s).toContain('curl -s -X POST "https://registry.example.test/api/v1/auth/agent/token"')
    expect(s).toContain('-d "username=agent-0123456789abcdef"')
    expect(s).toContain('-d "password=$CLIENT_SECRET"')
    expect(s).not.toMatch(/tp_secret_/)
  })
})
