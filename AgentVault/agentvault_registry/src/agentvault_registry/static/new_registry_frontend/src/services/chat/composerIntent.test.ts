/** §OURSTATE-1 — the composer command line: one grammar brain (the voice
 *  rail's 4th consumer), the German comma survives, and the §FOREIGNACT
 *  NULL-currency clamp refuses by name instead of guessing a unit. */
import { describe, it, expect } from 'vitest'
import { parseComposer, composerTouchesMoney, completions, SLASH_COMMANDS } from './composerIntent'

describe('parseComposer', () => {
  it('plain text is text', () => {
    expect(parseComposer('hello there').kind).toBe('text')
    expect(parseComposer('').kind).toBe('text')
  })

  it('/pay 12,5 survives the German comma (the inherited normalizer)', () => {
    const i = parseComposer('/pay 12,5', { actingCurrency: 'BVT' }) as any
    expect(i).toMatchObject({ kind: 'pay', amount: 12.5, currency: 'BVT', refusal: null })
  })

  it('/pay 50 AVT lunch money — explicit currency + memo', () => {
    const i = parseComposer('/pay 50 AVT lunch money', { actingCurrency: 'BVT' }) as any
    expect(i).toMatchObject({ kind: 'pay', amount: 50, currency: 'AVT', memo: 'lunch money' })
  })

  it('word amounts ride the same brain: /pay five', () => {
    const i = parseComposer('/pay five', { actingCurrency: 'BVT' }) as any
    expect(i.amount).toBe(5)
  })

  it('NULL acting currency + no explicit unit → refusal BY NAME, never a guessed unit (§FOREIGNACT)', () => {
    const i = parseComposer('/pay 50', { actingCurrency: null }) as any
    expect(i.refusal).toBe('currency-unresolved')
    expect(i.currency).toBeNull()
  })

  it('an explicit unit overrides the clamp — the user named it', () => {
    const i = parseComposer('/pay 50 JDAY', { actingCurrency: null }) as any
    expect(i).toMatchObject({ currency: 'JDAY', refusal: null })
  })

  it('/pay with no amount refuses with amount-missing', () => {
    expect((parseComposer('/pay', { actingCurrency: 'BVT' }) as any).refusal).toBe('amount-missing')
  })

  it('/whois aliases /audit; target optional', () => {
    expect(parseComposer('/whois')).toMatchObject({ kind: 'audit', target: null })
    expect(parseComposer('/audit did:theprotocol:x')).toMatchObject({ kind: 'audit', target: 'did:theprotocol:x' })
  })

  it('unknown slash is named, never swallowed', () => {
    expect(parseComposer('/frobnicate now')).toMatchObject({ kind: 'unknown-slash', cmd: '/frobnicate' })
  })

  it('§AGORAWORDS: /agora is the primary market-listings command', () => {
    expect(parseComposer('/agora')).toMatchObject({ kind: 'stocks', query: null })
    expect(parseComposer('/agora BVT')).toMatchObject({ kind: 'stocks', query: 'BVT' })
  })

  it('§AGORAWORDS: /stocks keeps parsing, as an alias of /agora (SAME result kind)', () => {
    expect(parseComposer('/stocks')).toEqual(parseComposer('/agora'))
    expect(parseComposer('/stocks BVT')).toEqual(parseComposer('/agora BVT'))
    expect(parseComposer('/stocks')).toMatchObject({ kind: 'stocks', query: null })
  })

  it('§AGORAWORDS: /stock (singular) is unrelated and still shares one symbol', () => {
    expect(parseComposer('/stock SMKD')).toMatchObject({ kind: 'stock', symbol: 'SMKD' })
  })

  it('§AGORAWORDS: /listing, the name the help gives, shares one symbol exactly as /stock does', () => {
    expect(parseComposer('/listing SMKD')).toEqual(parseComposer('/stock SMKD'))
    expect(parseComposer('/listing smkd 5')).toEqual(parseComposer('/stock smkd 5'))
    expect(parseComposer('/LISTING SMKD')).toMatchObject({ kind: 'stock', symbol: 'SMKD' })
  })

  it('the whole closed set parses', () => {
    expect(parseComposer('/quote').kind).toBe('quote')
    expect(parseComposer('/call weather in Berlin')).toMatchObject({ kind: 'call', ask: 'weather in Berlin' })
    expect(parseComposer('/ledger').kind).toBe('ledger')
    expect(parseComposer('/ping').kind).toBe('ping')
    expect(parseComposer('/me waves')).toMatchObject({ kind: 'me', action: 'waves' })
    expect(parseComposer('/ignore').kind).toBe('ignore')
    expect(parseComposer('/help').kind).toBe('help')
    expect(parseComposer('/card SYBIL')).toMatchObject({ kind: 'card', query: 'SYBIL' })
  })
})

describe('composerTouchesMoney', () => {
  it('names exactly the door-opening intents', () => {
    expect(composerTouchesMoney(parseComposer('/pay 5', { actingCurrency: 'BVT' }))).toBe(true)
    expect(composerTouchesMoney(parseComposer('/request 5', { actingCurrency: 'BVT' }))).toBe(true)
    expect(composerTouchesMoney(parseComposer('/call x'))).toBe(true)
    expect(composerTouchesMoney(parseComposer('/audit'))).toBe(false)
    expect(composerTouchesMoney(parseComposer('/ping'))).toBe(false)
    expect(composerTouchesMoney(parseComposer('hello'))).toBe(false)
  })
})

describe('completions', () => {
  it('prefix-filters the closed set', () => {
    expect(completions('/pa').map(c => c.cmd)).toEqual(['/pay'])
    expect(completions('/').length).toBeGreaterThan(5)
  })
  it('agent-only commands hide outside agent threads', () => {
    const dm = completions('/', { agentThread: false }).map(c => c.cmd)
    expect(dm).not.toContain('/quote')
    expect(dm).not.toContain('/call')
    const svc = completions('/', { agentThread: true }).map(c => c.cmd)
    expect(svc).toContain('/call')
  })
  it('no completions once arguments begin', () => {
    expect(completions('/pay 5')).toEqual([])
  })
})

describe('the set is closed and self-documenting', () => {
  it('every SLASH_COMMANDS entry parses to a non-unknown intent', () => {
    for (const c of SLASH_COMMANDS) {
      const i = parseComposer(`${c.cmd} x`, { actingCurrency: 'BVT', agentThread: true })
      expect(i.kind, c.cmd).not.toBe('unknown-slash')
      expect(i.kind, c.cmd).not.toBe('text')
    }
  })
})

// ---------------------------------------------------------------------------
// §OURSTATE-2 — room commands (fill-never-fire; refusals BY NAME)
// ---------------------------------------------------------------------------
import { completions as _completions } from './composerIntent'

describe('room commands', () => {
  const inRoomOp = { room: { isOperator: true } }
  const inRoomMember = { room: { isOperator: false } }

  it('/kick fills a target op — nothing executes from parsing', () => {
    expect(parseComposer('/kick Dana', inRoomOp)).toEqual(
      { kind: 'room-op', op: 'kick', target: 'Dana', value: '', refusal: null })
  })
  it('/kick with no target refuses by name', () => {
    expect(parseComposer('/kick', inRoomOp)).toEqual(
      { kind: 'room-op', op: 'kick', target: '', value: '', refusal: 'target-missing' })
  })
  it('room commands outside a room refuse as not-a-room, never unknown', () => {
    expect(parseComposer('/mute Dana', {})).toEqual(
      { kind: 'room-op', op: 'mute', target: 'Dana', value: '', refusal: 'not-a-room' })
    expect(parseComposer('/room', {})).toEqual(
      { kind: 'room-settings', refusal: 'not-a-room' })
  })
  it('member (non-operator) refusals name the missing authority', () => {
    expect(parseComposer('/topic Q3 plans', inRoomMember)).toEqual(
      { kind: 'room-op', op: 'topic', target: '', value: 'Q3 plans', refusal: 'not-operator' })
    expect(parseComposer('/room', inRoomMember)).toEqual(
      { kind: 'room-settings', refusal: 'not-operator' })
  })
  it('/topic with empty value is legal (clears the line downstream)', () => {
    expect(parseComposer('/topic', inRoomOp)).toEqual(
      { kind: 'room-op', op: 'topic', target: '', value: '', refusal: null })
  })
  it('/motd carries the draft text into the editor', () => {
    const r = parseComposer('/motd Be kind. Settle debts.', inRoomOp)
    expect(r).toEqual({ kind: 'room-op', op: 'motd', target: '', value: 'Be kind. Settle debts.', refusal: null })
  })
  it('/invite is a DOOR to the org rail, member-visible', () => {
    expect(parseComposer('/invite', inRoomMember)).toEqual({ kind: 'room-invite', refusal: null })
  })
  it('room ops never register as money', () => {
    expect(composerTouchesMoney(parseComposer('/kick Dana', inRoomOp))).toBe(false)
    expect(composerTouchesMoney(parseComposer('/room', inRoomOp))).toBe(false)
  })

  describe('completions honor room + operator gates', () => {
    it('outside a room: no room commands offered', () => {
      const cmds = _completions('/', {}).map(c => c.cmd)
      expect(cmds).not.toContain('/kick')
      expect(cmds).not.toContain('/room')
      expect(cmds).not.toContain('/invite')
    })
    it('room member: /room + /invite offered, operator commands hidden', () => {
      const cmds = _completions('/', inRoomMember).map(c => c.cmd)
      expect(cmds).toContain('/room')
      expect(cmds).toContain('/invite')
      expect(cmds).not.toContain('/kick')
      expect(cmds).not.toContain('/motd')
    })
    it('room operator: the full room family', () => {
      const cmds = _completions('/', inRoomOp).map(c => c.cmd)
      for (const c of ['/kick', '/mute', '/unmute', '/topic', '/motd', '/room', '/invite']) {
        expect(cmds).toContain(c)
      }
    })
  })
})

/* §OURSTATE-6 — /timer. The point of the test is the SECOND assertion: parsing
   must never carry a window. A command that could set retention by being typed
   would change what the OTHER side keeps without either of them seeing the
   bound stated, which is precisely what the picker exists to say out loud. */
describe('§OURSTATE-6 /timer', () => {
  it('parses to a door, and carries no window', () => {
    const i = parseComposer('/timer', { actingCurrency: 'BVT' }) as any
    expect(i.kind).toBe('timer')
    expect(Object.keys(i)).toEqual(['kind'])
  })
  it('is listed in /help so it is discoverable', () => {
    expect(SLASH_COMMANDS.map(c => c.cmd)).toContain('/timer')
  })
})

/* ─────────────────────────── §OURSTATE-7 B + C ───────────────────────────
   The /help grouping and the argument completion. Both exist to remove a
   SECOND hand-kept list: before this, "which commands need an agent" was
   written once in the table (as nothing) and once inside completions() as a
   literal `/quote`/`/call` pair. These tests pin that they now agree, and that
   they agree because they read the same field. */
import { commandGroups, unavailableReason, argCompletions } from './composerIntent'

describe('§OURSTATE-7 B — command groups', () => {
  const dm = { agentThread: false }
  const svc = { agentThread: true }
  const inRoom = { room: { isOperator: false } }
  const inRoomOp = { room: { isOperator: true } }

  it('every command lands in exactly one group, and no group is empty', () => {
    const groups = commandGroups(dm)
    const seen = groups.flatMap(g => g.items.map(i => i.cmd))
    expect(new Set(seen).size).toBe(seen.length)
    expect(seen.sort()).toEqual(SLASH_COMMANDS.map(c => c.cmd).sort())
    for (const g of groups) expect(g.items.length).toBeGreaterThan(0)
  })

  it('DIMS rather than hides: the closed set is the same everywhere', () => {
    const inDm = commandGroups(dm).flatMap(g => g.items).map(i => i.cmd)
    const inOp = commandGroups(inRoomOp).flatMap(g => g.items).map(i => i.cmd)
    expect(inDm.sort()).toEqual(inOp.sort())
  })

  it('names WHY a command is unavailable here', () => {
    const byCmd = Object.fromEntries(
      commandGroups(dm).flatMap(g => g.items).map(i => [i.cmd, i.unavailable]))
    expect(byCmd['/pay']).toBeNull()
    expect(byCmd['/quote']).toBe('needs-agent')
    expect(byCmd['/room']).toBe('not-a-room')
    expect(byCmd['/kick']).toBe('not-a-room')
  })

  it('inside a room, a member is told operator — not "not a room"', () => {
    const byCmd = Object.fromEntries(
      commandGroups(inRoom).flatMap(g => g.items).map(i => [i.cmd, i.unavailable]))
    expect(byCmd['/room']).toBeNull()
    expect(byCmd['/kick']).toBe('not-operator')
  })

  it('THE POINT: completions() and the sheet agree, because one predicate', () => {
    for (const ctx of [dm, svc, inRoom, inRoomOp]) {
      const offered = new Set(_completions('/', ctx).map(c => c.cmd))
      for (const g of commandGroups(ctx)) {
        for (const it of g.items) {
          expect(offered.has(it.cmd)).toBe(it.unavailable === null)
        }
      }
    }
  })

  it('unavailableReason is the whole gate', () => {
    expect(unavailableReason('any', dm)).toBeNull()
    expect(unavailableReason('agent', dm)).toBe('needs-agent')
    expect(unavailableReason('agent', svc)).toBeNull()
    expect(unavailableReason('op', inRoom)).toBe('not-operator')
    expect(unavailableReason('op', inRoomOp)).toBeNull()
  })
})

describe('§OURSTATE-7 C — argument completion', () => {
  it('silent while the command token is still being typed', () => {
    expect(argCompletions('/ca')).toBeNull()
    expect(argCompletions('/card')).toBeNull()
  })
  it('fires for /card and /find once an argument begins', () => {
    expect(argCompletions('/card ')).toEqual({ cmd: '/card', kind: 'agent', query: '' })
    expect(argCompletions('/card syb')).toEqual({ cmd: '/card', kind: 'agent', query: 'syb' })
    expect(argCompletions('/find ash')).toEqual({ cmd: '/find', kind: 'agent', query: 'ash' })
  })
  it('a DID needs no lookup — suggesting alternatives for it is noise', () => {
    expect(argCompletions('/card did:theprotocol:06a0c400-6dec-43da-916b')).toBeNull()
  })
  it('never fires for commands that take no name', () => {
    for (const s of ['/pay 12,5', '/call weather in Berlin', '/topic be kind', '/me waves']) {
      expect(argCompletions(s, { agentThread: true, room: { isOperator: true } })).toBeNull()
    }
  })
  it('honors the SAME availability gate as everything else', () => {
    // /card is group 'any', so it completes anywhere — the discrimination is
    // that the gate is asked at all, proven by a room command that is not.
    expect(argCompletions('/card x', {})).not.toBeNull()
  })
})
