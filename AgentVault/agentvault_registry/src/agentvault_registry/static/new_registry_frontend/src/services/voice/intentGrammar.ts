/**
 * services/voice/intentGrammar.ts — §POCKETBRIDGE3 WS-B1 (the deterministic brain).
 *
 * Utterance → typed intent. PURE: no fetching, no component state, no speech
 * API — the caller hands in the roster and the venue symbols it already holds,
 * and gets back an intent plus honest metadata (what was understood, what was
 * NOT matched, what to say back). Fully unit-tested; the D2 default brain of
 * the assistant panel and the mic both run through here.
 *
 * THE IRON RULE (WS-B3): nothing in this module executes anything. An intent
 * is at most a DOOR — a prefilled route onto an existing confirm-gated
 * surface. Voice is a faster finger, not a new authority (S8).
 *
 * Vocabulary is aligned with the MCP tool names where one exists (WS-B5), so
 * the grammar, connector Claude and the audit trail all speak one language.
 */

export interface RosterAgent {
  did: string
  name: string
}

export interface VenueSymbol {
  symbol: string
  name?: string
}

export interface GrammarContext {
  /** Agents the caller already holds (Home roster). Empty is fine — matching then reports honestly. */
  roster?: RosterAgent[]
  /** Venue tickers the caller already holds (Trade listings). */
  symbols?: VenueSymbol[]
  /** D6-835 (agentvault2-d6, 2026-10-25): the units this network speaks (the frame's own, then its peers'), any case.
   *  The grammar knew only the retired triangle's three (BVT, AVT, JDAY), so on EU "send 5 ecu to theo" was not
   *  understood and "send 5 avt to theo" prefilled a unit the frame does not have. A word outside the list is not a
   *  unit. Absent: the three, which this module's own tests speak. */
  units?: string[]
}

export type NavTarget =
  | 'home' | 'agents' | 'activity' | 'earn' | 'trade' | 'approvals' | 'more' | 'senate'

export type VoiceIntent =
  | { kind: 'navigate'; target: NavTarget }
  | { kind: 'balance'; agent?: RosterAgent; agentQuery?: string; mcpTool: 'getMyBalance' }
  | { kind: 'queue'; mcpTool: 'getMyUnreadNotifications' }
  | {
      kind: 'send'
      amount?: number
      currency?: string
      to?: RosterAgent
      toQuery?: string
      mcpTool: 'smartSend'
    }
  | { kind: 'stake'; amount?: number; agent?: RosterAgent; agentQuery?: string; mcpTool: 'lockUnits' }
  | { kind: 'find'; query: string; mcpTool: 'discoverAgents' }
  // §VOICEHIRE (H3.4): market discovery, an offer draft, the firms lane.
  // All three FILL doors — the terminal state of every voice-hire flow is a
  // filled, UNSUBMITTED surface on screen. Money never moves from speech.
  | { kind: 'market-find'; query: string; maxPrice?: number; currency?: string; mcpTool: 'discoverAgents' }
  | { kind: 'offer'; toQuery: string; to?: RosterAgent; amount?: number; currency?: string; title?: string }
  | { kind: 'hire-firm'; name: string }
  | { kind: 'order'; ref: string; mcpTool: 'guildGetOrder' }
  | { kind: 'freeze' }
  | {
      kind: 'trade'
      side?: 'buy' | 'sell'
      qty?: number
      symbol?: string
      symbolQuery?: string
      limit?: number
      mcpTool: 'placeExchangeOrder'
    }
  | { kind: 'guild-bid'; amount?: number; ref?: string; mcpTool: 'guildBid' }
  | { kind: 'guild-post'; title?: string; bounty?: number; mcpTool: 'guildPostOrder' }
  // §OURSTATE-2: the chat surface joins the grammar. Both FILL a thread's
  // composer — voice writes a draft, a human presses send (fill, never fire).
  | { kind: 'message'; toQuery?: string; to?: RosterAgent; body?: string }
  | { kind: 'reply'; body?: string }
  | { kind: 'help' }
  | { kind: 'unknown'; heard: string }

export interface ParseResult {
  intent: VoiceIntent
  /** One-line human echo of what was understood — ALWAYS rendered as a chip (S5). */
  understood: string
  /** Anything asked for but not resolvable from context (a name that matched no agent, a ticker not on the venue). */
  unresolved?: string
}

/* ── normalization ──────────────────────────────────────────────────────── */

function norm(s: string): string {
  return (
    s
      .toLowerCase()
      // protect decimal separators INSIDE numbers ("12,5" / "2.5") before
      // stripping punctuation — a comma-decimal becomes a dot-decimal here
      .replace(/(\d)[.,](\d)/g, '$1$2')
      .replace(/[.,!?;:]+/g, ' ')
      .replace(//g, '.')
      .replace(/\s+/g, ' ')
      .trim()
  )
}

const WORD_NUMBERS: Record<string, number> = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
  eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13,
  fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18,
  nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60,
  seventy: 70, eighty: 80, ninety: 90, hundred: 100, thousand: 1000,
}

/** "5", "5.5", "12,5", "five", "5k", "2 hundred" → number (or null). */
export function parseAmount(raw: string | undefined | null): number | null {
  if (!raw) return null
  const t = norm(String(raw))
  const m = t.match(/^(\d+(?:[.,]\d+)?)\s*(k|thousand|hundred)?$/)
  if (m) {
    const base = parseFloat(m[1].replace(',', '.'))
    if (!isFinite(base)) return null
    const mult = m[2] === 'k' || m[2] === 'thousand' ? 1000 : m[2] === 'hundred' ? 100 : 1
    return base * mult
  }
  // word numbers, optionally "two hundred" / "five thousand"
  const parts = t.split(' ')
  if (parts.length === 1 && parts[0] in WORD_NUMBERS) return WORD_NUMBERS[parts[0]]
  if (parts.length === 2 && parts[0] in WORD_NUMBERS && (parts[1] === 'hundred' || parts[1] === 'thousand')) {
    return WORD_NUMBERS[parts[0]] * (parts[1] === 'hundred' ? 100 : 1000)
  }
  return null
}

const LEGACY_UNITS = ['bvt', 'avt', 'jday']

/** The unit words one parse accepts: the caller's (letters and digits, 2-8, lower-cased) or the legacy three. */
function unitWords(ctx: GrammarContext): string[] {
  const given = (ctx.units || []).map(x => String(x || '').trim().toLowerCase()).filter(x => /^[a-z][a-z0-9]{1,7}$/.test(x))
  return given.length ? Array.from(new Set(given)) : LEGACY_UNITS
}

/** D6-835: an example names the frame's own unit; with none known it names none (the unit is optional in each). */
export function exampleIn(cmd: string, unit?: string | null): string {
  const u = (unit || '').trim()
  return u ? cmd.replace(/\{unit\}/g, u) : cmd.replace(/ \{unit\}/g, '')
}
const AMOUNT_TOKEN = String.raw`(\d+(?:[.,]\d+)?\s*k?|[a-z]+(?:\s+(?:hundred|thousand))?)`

/* ── fuzzy matching ─────────────────────────────────────────────────────── */

function lev(a: string, b: string): number {
  if (a === b) return 0
  const m = a.length
  const n = b.length
  if (!m) return n
  if (!n) return m
  let prev = Array.from({ length: n + 1 }, (_, j) => j)
  for (let i = 1; i <= m; i++) {
    const cur = [i]
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    }
    prev = cur
  }
  return prev[n]
}

/**
 * Match a spoken name against the roster: exact > word-prefix > substring >
 * levenshtein ≤ 2 on any name word. Returns the single best hit, or null.
 */
export function matchAgent(query: string, roster: RosterAgent[] | undefined): RosterAgent | null {
  const q = norm(query)
  if (!q || !roster?.length) return null
  let best: RosterAgent | null = null
  let bestScore = -1
  for (const a of roster) {
    const name = norm(a.name || '')
    if (!name) continue
    let score = -1
    if (name === q) score = 100
    else if (name.split(' ').some((w) => w === q)) score = 90
    else if (name.startsWith(q)) score = 80
    else if (name.includes(q)) score = 70
    else {
      const d = Math.min(...name.split(' ').map((w) => lev(w, q)), lev(name, q))
      if (d <= 2 && q.length >= 4) score = 60 - d * 10
    }
    if (score > bestScore) {
      bestScore = score
      best = a
    }
  }
  return bestScore >= 0 ? best : null
}

/** Match a spoken ticker against venue symbols: exact symbol > name fuzzy. */
export function matchSymbol(query: string, symbols: VenueSymbol[] | undefined): string | null {
  const q = norm(query).replace(/\$/g, '')
  if (!q || !symbols?.length) return null
  for (const s of symbols) if (norm(s.symbol) === q) return s.symbol
  for (const s of symbols) if (s.name && norm(s.name).includes(q)) return s.symbol
  for (const s of symbols) if (lev(norm(s.symbol), q) <= 1 && q.length >= 3) return s.symbol
  return null
}

/* ── the grammar ────────────────────────────────────────────────────────── */

// §AGORAWORDS: 'agora' and 'listings' are recognized ALONGSIDE the old
// 'market'/'markets'/'exchange' words, never instead of them: an older build's
// spoken-command list still says "market", so both must keep working.
const NAV_WORDS: Record<string, NavTarget> = {
  home: 'home', agents: 'agents', accounts: 'agents', activity: 'activity',
  earn: 'earn', payments: 'earn', guild: 'earn', work: 'earn', trade: 'trade', market: 'trade',
  markets: 'trade', exchange: 'trade', agora: 'trade', listings: 'trade',
  approvals: 'approvals', more: 'more',
  settings: 'more', senate: 'senate', votes: 'senate', voting: 'senate',
}

export function parseUtterance(utterance: string, ctx: GrammarContext = {}): ParseResult {
  const u = norm(utterance)
  if (!u) return { intent: { kind: 'unknown', heard: '' }, understood: 'Heard nothing.' }
  const units = unitWords(ctx)
  const UNIT = units.join('|')

  // help
  if (/^(help|what can (you|i) (do|say)|commands?( list)?)$/.test(u)) {
    return { intent: { kind: 'help' }, understood: 'Showing what I can do.' }
  }

  // freeze — checked early; a security surface must never fall through to search
  if (/(emergency freeze|freeze (everything|all( agents)?)|^freeze$|^panic$)/.test(u)) {
    return {
      intent: { kind: 'freeze' },
      understood: 'Opening the EMERGENCY freeze confirmation. Nothing is frozen until you confirm.',
    }
  }

  // queue / needs-you
  if (/(what needs? me|needs? (my|your) attention|read (my |the )?queue|anything (need|for) (me|you))/.test(u)) {
    return {
      intent: { kind: 'queue', mcpTool: 'getMyUnreadNotifications' },
      understood: 'Reading your NEEDS YOU queue.',
    }
  }

  // send: "send 5 bvt to theo", "transfer 2.5 to trader tilly", "pay theo 5 bvt"
  {
    let amountRaw: string | undefined, ccyRaw: string | undefined, nameRaw: string | undefined
    const m1 = u.match(new RegExp(String.raw`^(?:send|pay|transfer)\s+${AMOUNT_TOKEN}\s*(${UNIT}|tokens?)?\s+to\s+(.+)$`))
    if (m1) {
      amountRaw = m1[1]; ccyRaw = m1[2]; nameRaw = m1[3]
    } else {
      const m2 = u.match(new RegExp(String.raw`^pay\s+(.+?)\s+${AMOUNT_TOKEN}\s*(${UNIT})?$`))
      if (m2) { nameRaw = m2[1]; amountRaw = m2[2]; ccyRaw = m2[3] }
    }
    if (nameRaw !== undefined) {
      const amount = parseAmount(amountRaw) ?? undefined
      const currency = ccyRaw && units.includes(ccyRaw) ? ccyRaw.toUpperCase() : undefined
      const agent = matchAgent(nameRaw, ctx.roster)
      if (amount !== undefined || agent) {
        return {
          intent: { kind: 'send', amount, currency, to: agent ?? undefined, toQuery: nameRaw, mcpTool: 'smartSend' },
          understood: `Prefill a send${amount !== undefined ? ` of ${amount}${currency ? ' ' + currency : ''}` : ''} to ${agent ? agent.name : `"${nameRaw}"`}. You confirm on the send screen.`,
          unresolved: agent ? undefined : `No agent in your roster matched "${nameRaw}".`,
        }
      }
    }
  }

  // lock: "lock 10 with tilly", "lock five bvt on trader theo", "lock 10 units". "stake" is recognized ALONGSIDE
  // "lock" (an older spoken habit), never instead of it, and nothing on screen says it any more.
  {
    const m = u.match(
      new RegExp(String.raw`^(?:lock|stake)\s+${AMOUNT_TOKEN}\s*(?:${UNIT}|units?|tokens?)?(?:\s+(?:with|from|on|for)\s+(.+))?$`),
    )
    if (m) {
      const amount = parseAmount(m[1]) ?? undefined
      const nameRaw = m[2]
      const agent = nameRaw ? matchAgent(nameRaw, ctx.roster) : null
      return {
        intent: { kind: 'stake', amount, agent: agent ?? undefined, agentQuery: nameRaw, mcpTool: 'lockUnits' },
        understood: `Prefill a lock${amount !== undefined ? ` of ${amount}` : ''}${agent ? ` with ${agent.name}` : nameRaw ? ` with "${nameRaw}"` : ''}. You confirm on the lock sheet.`,
        unresolved: nameRaw && !agent ? `No agent in your roster matched "${nameRaw}".` : undefined,
      }
    }
  }

  // trade: "buy 5 bld0", "sell 2 qcc at 120", "buy five shares of firm72",
  // "buy five points of firm72" (§AGORAWORDS: 'points' recognized ALONGSIDE
  // 'shares', never instead of it)
  {
    const m = u.match(
      new RegExp(String.raw`^(buy|sell)\s+${AMOUNT_TOKEN}\s+(?:(?:shares?|points?)\s+(?:of\s+)?)?\$?([a-z0-9]+)(?:\s+at\s+${AMOUNT_TOKEN})?$`),
    )
    if (m) {
      const side = m[1] as 'buy' | 'sell'
      const qty = parseAmount(m[2]) ?? undefined
      const symRaw = m[3]
      const limit = m[4] ? (parseAmount(m[4]) ?? undefined) : undefined
      const symbol = matchSymbol(symRaw, ctx.symbols)
      return {
        intent: { kind: 'trade', side, qty, symbol: symbol ?? undefined, symbolQuery: symRaw, limit, mcpTool: 'placeExchangeOrder' },
        understood: `Prefill a ${side}${qty !== undefined ? ` of ${qty}` : ''} ${symbol ? '$' + symbol : `"${symRaw}"`}${limit !== undefined ? ` at ${limit}` : ' at market'}. You confirm on the order ticket.`,
        unresolved: symbol ? undefined : `No listing on this market matched "${symRaw}".`,
      }
    }
    // §AGORAWORDS: "agora" / "listings" recognized ALONGSIDE "trade" as the
    // spoken word that opens this same door.
    const m2 = u.match(/^(?:open\s+)?(?:trade|agora|listings)(?:\s+(?:for|on)\s+\$?([a-z0-9]+))?$/)
    if (m2) {
      const symbol = m2[1] ? matchSymbol(m2[1], ctx.symbols) : null
      if (m2[1]) {
        return {
          intent: { kind: 'trade', symbol: symbol ?? undefined, symbolQuery: m2[1], mcpTool: 'placeExchangeOrder' },
          understood: `Opening trade${symbol ? ' for $' + symbol : ''}.`,
          unresolved: symbol ? undefined : `No listing matched "${m2[1]}" — opening the Trade tab.`,
        }
      }
      return { intent: { kind: 'navigate', target: 'trade' }, understood: 'Opening Trade.' }
    }
  }

  // §OURSTATE-2 message: "message tilly about the invoice", "tell theo the
  // draft is ready", "dm sybil". Opens the thread with the body DRAFTED — it
  // is never sent by speaking (the iron rule, same as every money intent).
  {
    const m = u.match(/^(?:message|dm|write|tell)\s+(.+?)(?:\s+(?:about|that|saying)\s+(.+))?$/)
    if (m && !/^(me|myself)$/.test(m[1])) {
      const nameRaw = m[1]
      const agent = matchAgent(nameRaw, ctx.roster)
      return {
        intent: { kind: 'message', toQuery: nameRaw, to: agent ?? undefined, body: m[2] },
        understood: agent
          ? `Opening your thread with ${agent.name}${m[2] ? ' and drafting your message' : ''}. Nothing sends until you press send.`
          : `Looking for "${nameRaw}" to open a thread. Nothing sends until you press send.`,
        unresolved: agent ? undefined : `No agent in your roster matched "${nameRaw}".`,
      }
    }
  }

  // §OURSTATE-2 reply: "reply the invoice is paid", "answer yes" — drafts into
  // the thread you are already looking at.
  {
    const m = u.match(/^(?:reply|answer|respond)(?:\s+(?:with|saying)?\s*(.+))?$/)
    if (m) {
      return {
        intent: { kind: 'reply', body: m[1] },
        understood: m[1]
          ? 'Drafting that reply in this thread. Press send when it reads right.'
          : 'Opening the composer in this thread.',
      }
    }
  }

  // guild bid: "bid 100 on the translation job", "bid fifty"
  {
    const m = u.match(new RegExp(String.raw`^bid\s+${AMOUNT_TOKEN}(?:\s+(?:on|for)\s+(.+))?$`))
    if (m) {
      const amount = parseAmount(m[1]) ?? undefined
      return {
        intent: { kind: 'guild-bid', amount, ref: m[2], mcpTool: 'guildBid' },
        understood: `Prefill a bid${amount !== undefined ? ` of ${amount}` : ''}${m[2] ? ` on "${m[2]}"` : ' — pick the order on the board'}. You confirm on the order sheet.`,
      }
    }
  }

  // guild post: "post a job ...", "post work translate my docs for 200"
  {
    const m = u.match(new RegExp(String.raw`^post\s+(?:a\s+)?(?:job|order|work)(?:\s+(.+?))?(?:\s+for\s+${AMOUNT_TOKEN})?$`))
    if (m) {
      const bounty = m[2] ? (parseAmount(m[2]) ?? undefined) : undefined
      return {
        intent: { kind: 'guild-post', title: m[1], bounty, mcpTool: 'guildPostOrder' },
        understood: `Prefill a guild posting${m[1] ? ` "${m[1]}"` : ''}${bounty !== undefined ? ` with bounty ${bounty}` : ''}. You confirm before it goes up.`,
      }
    }
  }

  // balance: "balance", "balance of theo", "how much does tilly have", "my balance"
  {
    const m =
      u.match(/^(?:say |read |show |what.?s )?(?:my |the )?balance(?:\s+(?:of|for)\s+(.+))?$/) ||
      u.match(/^how much (?:bvt |money )?(?:do i have|does\s+(.+?)\s+have|is in .+)$/)
    if (m) {
      const nameRaw = m[1]
      const agent = nameRaw ? matchAgent(nameRaw, ctx.roster) : null
      return {
        intent: { kind: 'balance', agent: agent ?? undefined, agentQuery: nameRaw, mcpTool: 'getMyBalance' },
        understood: agent ? `Reading ${agent.name}'s balance.` : nameRaw ? `Looking for the balance of "${nameRaw}".` : 'Reading your balances.',
        unresolved: nameRaw && !agent ? `No agent in your roster matched "${nameRaw}".` : undefined,
      }
    }
  }

  // guild order by ref: "open order 42", "show the order about the logo"
  {
    const m = u.match(/^(?:open|show)\s+(?:the\s+)?order\s+(?:about\s+|number\s+|#)?(.+)$/)
    if (m) {
      return {
        intent: { kind: 'order', ref: m[1], mcpTool: 'guildGetOrder' },
        understood: `Opening the guild order "${m[1]}".`,
      }
    }
  }

  // §VOICEHIRE offer: "offer sybil 5 avt for logo design" — opens the thread
  // with the PROPOSAL COMPOSER prefilled (the S composer; a proposal is a
  // statement card, and the post button is a human's finger).
  {
    const m = u.match(new RegExp(String.raw`^offer\s+(.+?)\s+${AMOUNT_TOKEN}\s*(${UNIT})?(?:\s+(?:for|to)\s+(.+))?$`))
    if (m) {
      const nameRaw = m[1]
      const amount = parseAmount(m[2]) ?? undefined
      const currency = m[3] && units.includes(m[3]) ? m[3].toUpperCase() : undefined
      const agent = matchAgent(nameRaw, ctx.roster)
      return {
        intent: { kind: 'offer', toQuery: nameRaw, to: agent ?? undefined, amount, currency, title: m[4] },
        understood: `Drafting an offer${amount !== undefined ? ` of ${amount}${currency ? ' ' + currency : ''}` : ''} to ${agent ? agent.name : `"${nameRaw}"`}${m[4] ? ` for "${m[4]}"` : ''}. Nothing posts until you press it.`,
        unresolved: agent ? undefined : `No agent in your roster matched "${nameRaw}" — I'll search by that name.`,
      }
    }
  }

  // §VOICEHIRE firms: "hire the firm meridian" — the Discovery firms lane,
  // scrolled to the match. Checked BEFORE market-find so "hire the firm x"
  // never reads as an agent search.
  {
    const m = u.match(/^(?:hire|engage)\s+(?:the\s+)?firm\s+(.+)$/)
    if (m) {
      return {
        intent: { kind: 'hire-firm', name: m[1] },
        understood: `Opening the firms lane at "${m[1]}". Engaging still runs through the firm's intake door.`,
      }
    }
  }

  // §VOICEHIRE market find: "find me a translation agent under 2 avt",
  // "hire a research agent". The article + trailing "agent" is what separates
  // a MARKET search from the roster find below. The price cap is parsed and
  // spoken back, and the lane opens pre-filtered to PAID agents when a cap was
  // asked — the lane has no numeric price filter, and the echo says so
  // honestly instead of pretending one applied.
  {
    const m = u.match(new RegExp(String.raw`^(?:find|get|hire)(?:\s+me)?\s+(?:a|an|some)\s+(.+?)\s+agents?(?:\s+(?:under|below|at most|max)\s+${AMOUNT_TOKEN}\s*(${UNIT})?)?$`))
    if (m) {
      const query = m[1]
      const maxPrice = m[2] ? (parseAmount(m[2]) ?? undefined) : undefined
      const currency = m[3] && units.includes(m[3]) ? m[3].toUpperCase() : undefined
      return {
        intent: { kind: 'market-find', query, maxPrice, currency, mcpTool: 'discoverAgents' },
        understood: maxPrice !== undefined
          ? `Searching the network for "${query}" agents, paid lane open. Prices are on the cards — your cap of ${maxPrice}${currency ? ' ' + currency : ''} is yours to apply, the lane has no price filter.`
          : `Searching the network for "${query}" agents.`,
      }
    }
  }

  // find agent: "find agent theo", "search tilly", "look up caspian"
  {
    const m = u.match(/^(?:find|search(?:\s+for)?|look\s+up)\s+(?:agent\s+)?(.+)$/)
    if (m) {
      return {
        intent: { kind: 'find', query: m[1], mcpTool: 'discoverAgents' },
        understood: `Searching agents for "${m[1]}".`,
      }
    }
  }

  // navigation: "go to trade", "open approvals", bare "agents"
  {
    const m = u.match(/^(?:go\s+to|open|show(?:\s+me)?|switch\s+to)\s+(?:the\s+)?([a-z]+)$/) || u.match(/^([a-z]+)$/)
    if (m && m[1] in NAV_WORDS) {
      const target = NAV_WORDS[m[1]]
      return { intent: { kind: 'navigate', target }, understood: `Opening ${target === 'earn' ? 'Payments' : target}.` }
    }
  }

  return {
    intent: { kind: 'unknown', heard: utterance },
    understood: `Didn't catch that ("${utterance}").`,
  }
}

/** The capability list — rendered by help and by the unknown fallback (S5). */
/* §POCKETI18N — the capability list, split so it can be localised HONESTLY.
 *
 * `cmd` is the LITERAL English utterance this parser recognises: it is not
 * translated anywhere, because the grammar in this file only matches English
 * and a translated example would be an instruction that does not work. Only
 * `gloss` (what the command does) is localised, at the render site — this
 * module stays pure so its node-env unit tests keep running with no i18n.
 * CAPABILITIES below is the flattened English form, kept for compatibility. */
export interface CapabilityEntry { cmd: string; key: string; gloss: string }
export const CAPABILITY_ENTRIES: CapabilityEntry[] = [
  { cmd: '"go to trade" / "open approvals"', key: 'navigate', gloss: 'navigate' },
  { cmd: '"balance" or "balance of Theo"', key: 'balances', gloss: 'spoken balances' },
  { cmd: '"what needs me"', key: 'needsYou', gloss: 'read the NEEDS YOU queue' },
  { cmd: '"send 5 {unit} to Theo"', key: 'send', gloss: 'prefill the send screen' },
  { cmd: '"lock 10 with Tilly"', key: 'stake', gloss: 'prefill the lock sheet' },
  { cmd: '"buy 5 BLD0" / "sell 2 QCC at 120"', key: 'order', gloss: 'prefill an order ticket' },
  { cmd: '"bid 100 on ..." / "post a job ... for 200"', key: 'guild', gloss: 'prefill guild sheets' },
  { cmd: '"find agent ..."', key: 'find', gloss: 'search your agents' },
  { cmd: '"open order ..."', key: 'order2', gloss: 'open a guild order' },
  { cmd: '"emergency freeze"', key: 'freeze', gloss: 'open the freeze confirmation' },
  // §VOICEHIRE (H3.4)
  { cmd: '"find me a translation agent under 2 {unit}"', key: 'marketFind', gloss: 'search the network, paid lane' },
  { cmd: '"offer Sybil 5 {unit} for logo design"', key: 'offer', gloss: 'draft a proposal in the thread' },
  { cmd: '"hire the firm Meridian"', key: 'hireFirm', gloss: 'open the firms lane' },
]

export const CAPABILITIES: string[] = [
  '"go to trade" / "open approvals" — navigate',
  '"balance" or "balance of Theo" — spoken balances',
  '"what needs me" — read the NEEDS YOU queue',
  '"send 5 to Theo" — prefill the send screen',
  '"lock 10 with Tilly" — prefill the lock sheet',
  '"buy 5 BLD0" / "sell 2 QCC at 120" — prefill an order ticket',
  '"bid 100 on ..." / "post a job ... for 200" — prefill guild sheets',
  '"find agent ..." — search your agents',
  '"open order ..." — open a guild order',
  '"emergency freeze" — open the freeze confirmation',
  '"find me a translation agent under 2" — search the network, paid lane',
  '"offer Sybil 5 for logo design" — draft a proposal in the thread',
  '"hire the firm Meridian" — open the firms lane',
]

/** True for intents whose door leads to a money-moving confirm surface (S8). */
export function intentTouchesMoney(i: VoiceIntent): boolean {
  return i.kind === 'send' || i.kind === 'stake' || i.kind === 'trade' || i.kind === 'guild-bid' || i.kind === 'guild-post' || i.kind === 'freeze'
}
