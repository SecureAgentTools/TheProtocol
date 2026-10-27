import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §REPATLANE-7 (after V0606): EVERY SEND DOOR READS ITS REFERENCE THROUGH sendReference.
 *
 * /teg/send answers a payment's reference as `transfer_id` (SmartSendResponse) and keeps the inner endpoint's answer
 * under `detail`. Three doors read `transaction_id` instead, a field that answer never carries: Pocket's send sheet (so a
 * priced first contact could never open its thread), the bridge's quick send (every send said "confirmed" instead of its
 * reference) and the landing showcase's receipt card (it stored an empty tx_ref). Each guessed on its own; the rule now
 * lives in one place (services/money/sendOutcome.ts), and this census holds every file that sends through /teg/send to
 * it. A new door fails here until it asks the same rule.
 */
const SRC = path.resolve(__dirname, '../..')

// Files that reach /teg/send without reading a payment's reference, each with its reason.
const READS_NO_REFERENCE: Record<string, string> = {
  'services/api/teg.ts': 'defines smartSend and returns the answer whole; its callers read the reference',
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (/\.(vue|ts)$/.test(e.name) && !/\.(test|spec)\.ts$/.test(e.name)) out.push(full)
  }
  return out
}

/** the code alone: comments say what a rule is, so a comment naming sendReference must not count as asking it */
function code(text: string): string {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1')
}

/** a file sends through /teg/send when it calls smartSend or posts to the path itself */
function sends(text: string): boolean {
  const c = code(text)
  return /\bsmartSend\s*\(/.test(c) || /(['"`])\/teg\/send(?:\?[^'"`]*)?\1/.test(c)
}

function asksTheRule(text: string): boolean {
  return /\bsendReference\s*\(/.test(code(text))
}

describe('every send door reads its reference through sendReference', () => {
  const files = walk(SRC).map((f) => path.relative(SRC, f).split(path.sep).join('/'))
  const senders = files.filter((f) => sends(fs.readFileSync(path.join(SRC, f), 'utf8'))).sort()

  it('finds the doors it holds (a census of nothing would pass on nothing)', () => {
    expect(senders).toEqual(expect.arrayContaining([
      'components/bridge/BridgeQuickActions.vue',
      'components/landing/ShowcaseChat.vue',
      'services/api/teg.ts',
      'views/pocket/PocketSend.vue',
    ]))
  })

  it('each door asks sendReference, or is listed with the reason it reads no reference', () => {
    const offenders = senders.filter((f) => !(f in READS_NO_REFERENCE) && !asksTheRule(fs.readFileSync(path.join(SRC, f), 'utf8')))
    expect(offenders).toEqual([])
  })

  it('every listed exception still sends (a stale exception would hide nothing and keep a door open)', () => {
    for (const f of Object.keys(READS_NO_REFERENCE)) expect(senders, f).toContain(f)
  })

  it('control: the census sees a door that guesses, and a rule named only in a comment', () => {
    const guesses = "const r = await tegApi.smartSend(body, { idempotencyKey: k })\nconst ref = r.transaction_id || ''\n"
    expect(sends(guesses)).toBe(true)
    expect(asksTheRule(guesses)).toBe(false)
    const commentOnly = "// read it with sendReference(r), see sendOutcome\nconst tr = await api('/teg/send', { method: 'POST' })\n"
    expect(sends(commentOnly)).toBe(true)
    expect(asksTheRule(commentOnly)).toBe(false)
    expect(sends("const docs = 'POST /api/v1/teg/send'\n")).toBe(false)
    expect(asksTheRule('const ref = sendReference(r)\n')).toBe(true)
  })
})
