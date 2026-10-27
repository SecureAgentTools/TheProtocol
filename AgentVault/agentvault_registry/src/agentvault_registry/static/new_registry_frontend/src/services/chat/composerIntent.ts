/**
 * §OURSTATE-1 — the composer command line (strategy §4b), the intent grammar's
 * 4th consumer (voice → assistant → bridge → THIS). One brain, not a second
 * parser: amounts go through the SAME `parseAmount` that already survived the
 * German comma ("12,5"), and money intents inherit the same iron rule —
 * **fill, never fire**. Nothing returned from this module moves anything; it
 * describes the door the composer should OPEN, pre-filled.
 *
 * The set is CLOSED and discoverable (`/help`): an unknown `/x` returns
 * 'unknown-slash' so the composer shows an inline hint and offers send-as-text
 * — it never silently swallows a message. Slash tokens stay English (the
 * §POCKETI18N quoted-command rule); glosses localize in the component.
 *
 * §FOREIGNACT clamp, inherited verbatim: `/pay 50` with no currency resolves
 * through the ACTING currency; when that is NULL (foreign card unresolved) the
 * intent carries `refusal: 'currency-unresolved'` and the composer refuses
 * WITH THE NAMED REASON — empty unit, never the wrong unit.
 */
import { parseAmount } from '@/services/voice/intentGrammar'

export interface ComposerCtx {
  /** The acting principal's currency (useActingContext.actingCurrency). NULL =
   *  foreign card unresolved — money commands refuse rather than guess. */
  actingCurrency?: string | null
  /** True when the thread's counterparty is a service agent (enables /quote, /call). */
  agentThread?: boolean
  /** §OURSTATE-2: set when THIS thread is an org room. Room commands are
   *  offered only here, operator commands only to operators — and outside a
   *  room they refuse BY NAME instead of pretending to be unknown. */
  room?: { isOperator: boolean } | null
  /** §SHOWCASEBAL: set when the acting principal holds a wallet this surface can
   *  read — i.e. /balance can actually answer. Declared rather than assumed so a
   *  surface that has not implemented it neither lists nor suggests it, instead
   *  of shipping a command that silently does nothing. */
  wallet?: boolean
}

export type ComposerIntent =
  | { kind: 'text' }
  | { kind: 'pay'; amount: number | null; currency: string | null; memo: string; refusal: 'currency-unresolved' | 'amount-missing' | null }
  | { kind: 'request'; amount: number | null; currency: string | null; memo: string; refusal: 'currency-unresolved' | 'amount-missing' | null }
  | { kind: 'quote' }
  | { kind: 'call'; ask: string }
  | { kind: 'card'; query: string }
  | { kind: 'audit'; target: string | null }
  | { kind: 'ledger' }
  | { kind: 'work' }
  /* §OURCHAT-ORG — share a listing that already trades here. The ticker is an
     ADDRESS; the card carries no side and no size, and the ticket prices it. */
  | { kind: 'stock'; symbol: string }
  | { kind: 'stocks'; query: string | null }
  | { kind: 'ping' }
  | { kind: 'me'; action: string }
  | { kind: 'ignore' }
  | { kind: 'help' }
  // §OURSTATE-6 — opens the retention picker. Parsing NEVER sets a window:
  // a timer changes what the other side keeps too, so it takes a deliberate
  // choice on a surface that states the bound, exactly like the money cards.
  | { kind: 'timer' }
  // §OURSTATE-6 — three more doors onto rails that already exist. Each one
  // OPENS a surface; none of them acts. `/find` carries its query so the
  // sheet lands searched rather than empty.
  | { kind: 'find'; query: string }
  | { kind: 'here' }
  | { kind: 'dispute' }
  // §OURSTATE-2 room commands — every one FILLS a confirm surface (destructive
  // ops additionally hold-to-execute there); parsing never executes anything.
  | { kind: 'room-op'; op: 'kick' | 'mute' | 'unmute' | 'topic' | 'motd'; target: string; value: string;
      refusal: 'not-a-room' | 'not-operator' | 'target-missing' | null }
  | { kind: 'room-settings'; refusal: 'not-a-room' | 'not-operator' | null }
  | { kind: 'room-invite'; refusal: 'not-a-room' | null }
  | { kind: 'balance' }
  // §DEALTHREADS — opens the proposal composer (structured terms card). FILLS,
  // never posts: the sheet is where the human commits the card.
  | { kind: 'propose'; title: string }
  | { kind: 'unknown-slash'; cmd: string }

/**
 * §OURSTATE-7 B — WHERE A COMMAND WORKS IS METADATA, DECLARED ONCE.
 *
 * `group` replaces the old `room`/`op` booleans AND the hardcoded
 * `c.cmd !== '/quote' && c.cmd !== '/call'` that used to sit inside
 * `completions()`. That pair was a second hand-kept list of "agent commands"
 * living apart from the table it described — the kind of split that drifts
 * silently the moment someone adds a third one. Now availability, the /help
 * grouping and the completion filter all read the same field:
 *
 *   any     every thread, every time
 *   agent   needs a service agent on the other side — and these SPEND
 *   wallet  needs a readable wallet on the acting principal
 *   room    org rooms only
 *   op      org rooms, and only for an owner/admin
 *
 * The groups are also the colours the /help sheet paints, so the colour is a
 * summary of something written down rather than decoration.
 */
export type CommandGroup = 'any' | 'agent' | 'wallet' | 'room' | 'op'

/** The closed set, in /help display order. Tokens stay English. */
export const SLASH_COMMANDS: Array<{ cmd: string; usage: string; glossKey: string; glossFallback: string;
  group: CommandGroup }> = [
  { cmd: '/pay', usage: '/pay <amount> [ccy] [memo]', group: 'any', glossKey: 'ourstate.help.pay', glossFallback: 'open Send pre-filled for this counterparty' },
  { cmd: '/request', usage: '/request <amount> [ccy] [memo]', group: 'any', glossKey: 'ourstate.help.request', glossFallback: 'post a payment request card' },
  { cmd: '/quote', usage: '/quote', group: 'agent', glossKey: 'ourstate.help.quote', glossFallback: 'price this agent’s service in your currency' },
  { cmd: '/call', usage: '/call [agent] <ask>', group: 'agent', glossKey: 'ourstate.help.call', glossFallback: 'stage a service call (confirm before anything moves)' },
  { cmd: '/card', usage: '/card <agent>', group: 'any', glossKey: 'ourstate.help.card', glossFallback: 'share an agent card into the thread' },
  { cmd: '/audit', usage: '/audit [target]', group: 'any', glossKey: 'ourstate.help.audit', glossFallback: 'local background check — public data only, posts nothing' },
  { cmd: '/ledger', usage: '/ledger', group: 'any', glossKey: 'ourstate.help.ledger', glossFallback: 'where you and this counterparty stand (local, bounded)' },
  { cmd: '/work', usage: '/work', group: 'any', glossKey: 'ourstate.help.work', glossFallback: 'share a contract or guild order you are a party to' },
  { cmd: '/stock', usage: '/stock <ticker>', group: 'any', glossKey: 'ourstate.help.stock', glossFallback: 'share a listing from this registry’s market' },
  // §SHOWCASESTOCKS — the plural. `/stock` addresses ONE symbol; this lists what
  // trades, with live prices from the venue's own stats, across the whole
  // federation rather than only this registry. `/stocks` keeps parsing (see
  // ALIASES below): it is now an alias for the primary `/agora` command.
  { cmd: '/agora', usage: '/agora [filter]', group: 'any', glossKey: 'ourstate.help.stocks', glossFallback: 'what trades right now, with live prices, across the federation' },
  { cmd: '/ping', usage: '/ping', group: 'any', glossKey: 'ourstate.help.ping', glossFallback: 'one knock — rate-limited, never overrides mute' },
  { cmd: '/me', usage: '/me <action>', group: 'any', glossKey: 'ourstate.help.me', glossFallback: 'an italic action row, pure flavor' },
  { cmd: '/ignore', usage: '/ignore', group: 'any', glossKey: 'ourstate.help.ignore', glossFallback: 'block this counterparty (silent)' },
  { cmd: '/timer', usage: '/timer', group: 'any', glossKey: 'ourstate.help.timer', glossFallback: 'set how long messages here are kept' },
  { cmd: '/find', usage: '/find [query]', group: 'any', glossKey: 'ourstate.help.find', glossFallback: 'search agents and people across the federation' },
  { cmd: '/here', usage: '/here', group: 'any', glossKey: 'ourstate.help.here', glossFallback: 'who is in this conversation, and where they are homed' },
  { cmd: '/dispute', usage: '/dispute', group: 'any', glossKey: 'ourstate.help.dispute', glossFallback: 'open the disputes lane for this counterparty' },
  { cmd: '/propose', usage: '/propose [title]', group: 'any', glossKey: 'ourstate.help.propose', glossFallback: 'draft engagement terms as a card (conversation, not money)' },
  { cmd: '/balance', usage: '/balance', group: 'wallet', glossKey: 'ourstate.help.balance', glossFallback: 'what you hold, what you have spent, and what a single payment may cost' },
  { cmd: '/help', usage: '/help', group: 'any', glossKey: 'ourstate.help.help', glossFallback: 'this list' },
  // §OURSTATE-2 — the room family.
  { cmd: '/kick', usage: '/kick <member>', group: 'op', glossKey: 'ourstate.help.kick', glossFallback: 'remove from this ROOM (org membership untouched) — hold to execute' },
  { cmd: '/mute', usage: '/mute <member>', group: 'op', glossKey: 'ourstate.help.mute', glossFallback: 'they read, they cannot post' },
  { cmd: '/unmute', usage: '/unmute <member>', group: 'op', glossKey: 'ourstate.help.unmute', glossFallback: 'restore posting' },
  { cmd: '/topic', usage: '/topic <text>', group: 'op', glossKey: 'ourstate.help.topic', glossFallback: 'set the room topic line' },
  { cmd: '/motd', usage: '/motd <text>', group: 'op', glossKey: 'ourstate.help.motd', glossFallback: 'edit the room genesis (history kept)' },
  { cmd: '/room', usage: '/room', group: 'room', glossKey: 'ourstate.help.room', glossFallback: 'room settings (mode, members)' },
  { cmd: '/invite', usage: '/invite', group: 'room', glossKey: 'ourstate.help.invite', glossFallback: 'invite to the ORGANIZATION — opens the org rail' },
]

// §AGORAWORDS (2026-10-25, his "yes all approved."): /listing is the name the help gives for sharing one listing; /stock keeps
// parsing (messages and habits already carry it), as /stocks does for /agora
const ALIASES: Record<string, string> = { '/whois': '/audit', '/bal': '/balance', '/stocks': '/agora', '/listing': '/stock' }

const CCY_RE = /^[A-Za-z]{2,6}$/

function parseMoneyArgs(rest: string, ctx: ComposerCtx):
  { amount: number | null; currency: string | null; memo: string; refusal: 'currency-unresolved' | 'amount-missing' | null } {
  const parts = rest.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return { amount: null, currency: null, memo: '', refusal: 'amount-missing' }
  // Amount may be "12,5" / "five" / "2 hundred" — try 1 then 2 leading tokens
  // through the SAME normalizer the voice rail uses.
  let amount: number | null = null
  let consumed = 0
  for (const n of [2, 1]) {
    if (parts.length >= n) {
      const a = parseAmount(parts.slice(0, n).join(' '))
      if (a !== null) { amount = a; consumed = n; break }
    }
  }
  if (amount === null) return { amount: null, currency: null, memo: rest.trim(), refusal: 'amount-missing' }
  let currency: string | null = null
  if (parts[consumed] && CCY_RE.test(parts[consumed])) {
    currency = parts[consumed].toUpperCase()
    consumed += 1
  } else if (ctx.actingCurrency) {
    currency = ctx.actingCurrency
  }
  const memo = parts.slice(consumed).join(' ')
  // The §FOREIGNACT clamp: no explicit unit + NULL acting currency = refuse,
  // by name. Never fall back to the viewer's currency — that fallback IS the bug.
  const refusal = currency === null ? 'currency-unresolved' as const : null
  return { amount, currency, memo, refusal }
}

export function parseComposer(input: string, ctx: ComposerCtx = {}): ComposerIntent {
  const raw = (input || '').trim()
  if (!raw.startsWith('/')) return { kind: 'text' }
  const sp = raw.indexOf(' ')
  let cmd = (sp === -1 ? raw : raw.slice(0, sp)).toLowerCase()
  const rest = sp === -1 ? '' : raw.slice(sp + 1)
  cmd = ALIASES[cmd] || cmd

  switch (cmd) {
    case '/pay': return { kind: 'pay', ...parseMoneyArgs(rest, ctx) }
    case '/request': return { kind: 'request', ...parseMoneyArgs(rest, ctx) }
    case '/quote': return { kind: 'quote' }
    case '/balance': return { kind: 'balance' }
    case '/call': return { kind: 'call', ask: rest.trim() }
    case '/card': return { kind: 'card', query: rest.trim() }
    case '/audit': return { kind: 'audit', target: rest.trim() || null }
    case '/agora': return { kind: 'stocks', query: rest.trim() || null }
    case '/ledger': return { kind: 'ledger' }
    case '/work': return { kind: 'work' }
    case '/stock': return { kind: 'stock', symbol: rest.trim().toUpperCase() }
    case '/ping': return { kind: 'ping' }
    case '/me': return { kind: 'me', action: rest.trim() }
    case '/ignore': return { kind: 'ignore' }
    case '/timer': return { kind: 'timer' }
    case '/find': return { kind: 'find', query: rest.trim() }
    case '/propose': return { kind: 'propose', title: rest.trim() }
    case '/here': return { kind: 'here' }
    case '/dispute': return { kind: 'dispute' }
    case '/help': return { kind: 'help' }
    case '/kick': case '/mute': case '/unmute':
      return roomTargetOp(cmd.slice(1) as 'kick' | 'mute' | 'unmute', rest, ctx)
    case '/topic': case '/motd':
      return roomValueOp(cmd.slice(1) as 'topic' | 'motd', rest, ctx)
    case '/room':
      return { kind: 'room-settings',
               refusal: !ctx.room ? 'not-a-room' : (ctx.room.isOperator ? null : 'not-operator') }
    case '/invite':
      return { kind: 'room-invite', refusal: ctx.room ? null : 'not-a-room' }
    default: return { kind: 'unknown-slash', cmd }
  }
}

function roomRefusal(ctx: ComposerCtx): 'not-a-room' | 'not-operator' | null {
  if (!ctx.room) return 'not-a-room'
  if (!ctx.room.isOperator) return 'not-operator'
  return null
}

function roomTargetOp(op: 'kick' | 'mute' | 'unmute', rest: string, ctx: ComposerCtx): ComposerIntent {
  const base = roomRefusal(ctx)
  const target = rest.trim()
  return { kind: 'room-op', op, target, value: '',
           refusal: base ?? (target ? null : 'target-missing') }
}

function roomValueOp(op: 'topic' | 'motd', rest: string, ctx: ComposerCtx): ComposerIntent {
  // An empty value is legal: /topic clears the line, /motd opens the editor
  // pre-filled with the current genesis — both are the confirm surface's job.
  return { kind: 'room-op', op, target: '', value: rest.trim(), refusal: roomRefusal(ctx) }
}

/** Mirrors intentTouchesMoney for the composer set — these intents open a door
 *  that, once CONFIRMED by the human, moves value on an existing rail. */
export function composerTouchesMoney(i: ComposerIntent): boolean {
  return i.kind === 'pay' || i.kind === 'request' || i.kind === 'call'
}

/** Why a command is not usable HERE — or null when it is. The one predicate
 *  behind both the completion filter and the /help sheet's dimming, so the two
 *  can never disagree about what this thread can do. */
export type Unavailable = 'needs-agent' | 'needs-wallet' | 'not-a-room' | 'not-operator'

export function unavailableReason(group: CommandGroup, ctx: ComposerCtx = {}): Unavailable | null {
  if (group === 'agent') return ctx.agentThread ? null : 'needs-agent'
  if (group === 'wallet') return ctx.wallet ? null : 'needs-wallet'
  if (group === 'room') return ctx.room ? null : 'not-a-room'
  if (group === 'op') {
    if (!ctx.room) return 'not-a-room'
    return ctx.room.isOperator ? null : 'not-operator'
  }
  return null
}

/** Autocomplete: commands whose token starts with the typed prefix. Room
 *  commands appear only inside a room; operator commands only to operators —
 *  nobody is offered a door they cannot open. */
export function completions(input: string, ctx: ComposerCtx = {}) {
  const raw = (input || '').trim().toLowerCase()
  if (!raw.startsWith('/') || raw.includes(' ')) return []
  return SLASH_COMMANDS.filter(c =>
    c.cmd.startsWith(raw) && unavailableReason(c.group, ctx) === null)
}

/**
 * §OURSTATE-7 B — the /help sheet's content, computed rather than written.
 *
 * Returns every command in its group, each annotated with whether it works in
 * THIS thread and, when it does not, why. Unavailable commands are DIMMED, not
 * hidden: "not here" and "does not exist" are different facts, and a list that
 * silently shrinks teaches the wrong closed set.
 */
export function commandGroups(ctx: ComposerCtx = {}): Array<{
  group: CommandGroup
  items: Array<{ cmd: string; usage: string; glossKey: string; glossFallback: string;
                 unavailable: Unavailable | null }>
}> {
  const order: CommandGroup[] = ['any', 'agent', 'wallet', 'room', 'op']
  return order
    .map(group => ({
      group,
      items: SLASH_COMMANDS.filter(c => c.group === group).map(c => ({
        cmd: c.cmd, usage: c.usage, glossKey: c.glossKey, glossFallback: c.glossFallback,
        unavailable: unavailableReason(group, ctx),
      })),
    }))
    .filter(g => g.items.length > 0)
}

/**
 * §OURSTATE-7 C — ARGUMENT completion, which did not exist: `completions()`
 * returns [] the moment the input contains a space, so everything past the
 * command token was unassisted.
 *
 * This stays PURE — it says WHAT should be suggested, never fetches it. The
 * component owns the (debounced, cached) discover call, because the grammar
 * module may not import a service any more than `guildActions` may import i18n.
 *
 * A DID needs no lookup: `/card did:theprotocol:…` names its target exactly, so
 * suggesting alternatives for it would be noise.
 */
export type ArgCompletion = { cmd: '/card' | '/find'; kind: 'agent'; query: string } | null

export function argCompletions(input: string, ctx: ComposerCtx = {}): ArgCompletion {
  // ⚠ Leading whitespace only. A TRAILING space is the signal that the command
  // token is finished and a name is coming, so `.trim()` here would erase the
  // exact keystroke that should open the list — `/card ` must suggest.
  const raw = (input || '').replace(/^\s+/, '')
  if (!raw.startsWith('/')) return null
  const sp = raw.indexOf(' ')
  if (sp === -1) return null                     // still typing the command itself
  const cmd = (ALIASES[raw.slice(0, sp).toLowerCase()] || raw.slice(0, sp).toLowerCase())
  if (cmd !== '/card' && cmd !== '/find') return null
  if (unavailableReason(
        SLASH_COMMANDS.find(c => c.cmd === cmd)?.group ?? 'any', ctx) !== null) return null
  const query = raw.slice(sp + 1).trim()
  if (query.toLowerCase().startsWith('did:')) return null
  return { cmd, kind: 'agent', query }
}
