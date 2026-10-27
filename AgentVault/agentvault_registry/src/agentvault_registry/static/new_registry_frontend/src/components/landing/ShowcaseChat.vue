<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §SHOWCASEFED — OurChat, on the landing page, for a stranger with no account.
//
// This is not a demo of OurChat. It IS OurChat: a real conversation row on this
// registry, driven by the SAME two brains the Pocket surface uses —
// `parseComposer` (the 24 slash commands, their groups and their refusals) and
// `cardView` (the closed card vocabulary). Nothing here re-implements either,
// because a second copy of a money-adjacent vocabulary is how two surfaces
// start disagreeing about what a card means.
//
// The visitor acts as this frame's one scoped showcase identity:
//   it may pay ONLY the showcase agents      (counterparty allowlist)
//   it may spend only small amounts          (per-tx / per-day / rate caps)
//   it may not lock, delegate, or trade
// So the interesting half of the demonstration is the REFUSALS, and they are
// shown rather than hidden: a payment to an address the visitor picks is
// refused by name, on screen, by the same gate that protects everyone else.
//
// The ledger beside it is the real public event stream, narrowed to this
// identity with the Bridge's fixture-pinned `involvesDids`. When a transfer
// goes through, the card and the ledger row are the same event seen twice —
// which is the point: the receipt is checkable against the ledger without
// leaving the page.
//
// ⚠ THE IDENTITY IS SHARED, and that is stated on screen. Threads opened here
// are visible to anyone else holding a showcase session, so the surface says
// so and nothing private should be typed into it.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import BridgeLedger from '@/components/bridge/BridgeLedger.vue'
// The venue stores 18 decimal places, so a raw pass-through renders
// "2.500000000000000000 BVT". `trimDecimal` strips only INSIGNIFICANT trailing
// zeros — a normalisation, never a rounding — and it already exists, so this
// uses it rather than growing a second opinion about numbers.
import { trimDecimal } from '@/services/chat/cards'
// §SHOWCASESTOCKS — one brain for price truth, shared with Pocket so the two
// surfaces cannot form different opinions about what a share costs.
import { normalizeListing, effectivePrice, priceLine, fxConvert, mergeTickers, tradability, type StockRow } from '@/services/chat/stocks'
import { parseComposer, commandGroups, completions, type ComposerCtx } from '@/services/chat/composerIntent'
import { cardView, type ChatCard } from '@/services/chat/cards'
import { cardPricing } from '@/services/cardPricing'
import { resolveCallTarget } from '@/services/chat/callTarget'
// §REPATLANE-7: /teg/send answers its reference as transfer_id; the one reader every send door asks.
import { sendReference } from '@/services/money/sendOutcome'

const { t, tp } = useI18n()

type Msg = {
  id: string; seq: number; kind: string; body?: string; card?: ChatCard
  sender: string; mine: boolean; at: string; expanded?: boolean
}

const session = ref<any>(null)
const sessionError = ref<string | null>(null)
const convId = ref<string | null>(null)
const partner = ref<{ did: string; name: string } | null>(null)
// 🔴 A DEFAULT IS NOT A CHOICE. openThread() with no argument opens services[0]
// so the reader has someone to talk to immediately — but that made a bare
// `/card` (his first-ever message) answer with WeatherAgent's card, an agent he
// had never named. The flag separates "this is who you picked" from "this is
// who was here when you arrived", and only the first may stand in for a missing
// argument.
const partnerChosen = ref(false)
const messages = ref<Msg[]>([])
const draft = ref('')
const busy = ref(false)
const notice = ref<string | null>(null)
const refusal = ref<string | null>(null)
const helpOpen = ref(false)
// §SHOWCASEVISITOR — the onboarding is narrated in the thread, so its steps are
// component state, not a spinner. They persist above the conversation because
// "an agent was created, scoped and funded for you" stays true all session.
const onboardSteps = ref<Array<{ key: string; label: string; detail: string; ok: boolean }>>([])
const onboarding = ref(false)
// The /help sheet keeps its buttons on screen; hovering one explains it in a
// strip below rather than in a native `title`, which is slow, unstyled and
// unreachable on touch. Focus drives it too, so a keyboard reaches the same text.
const hoverCmd = ref<any>(null)
const infoOpen = ref(false)
// Commands like /audit, /ledger, /here and /find are LOCAL reads: they answer
// from public data and post nothing into the thread. They render here so the
// difference between "I looked something up" and "I said something" stays
// visible — the same split Pocket keeps.
// The federation's live cross-currency spot, fetched once per session. A
// missing rate must produce NO converted figure rather than a guess, which is
// why this is allowed to stay null.
const fxRates = ref<any>(null)
// What this session can actually spend, so /stocks can say "above your cap" or
// "costs more than your balance" where a reader is choosing, instead of letting
// them find out by clicking.
const balance = ref<number | null>(null)
const tradeCtx = computed(() => ({
  maxPerTx: Number(session.value?.limits?.max_per_tx) || undefined,
  balance: balance.value ?? undefined,
}))
async function loadBalance() {
  try {
    const r = await api('/teg/balance')
    const b = Number(r.body?.balance ?? r.body?.available ?? NaN)
    if (isFinite(b)) balance.value = b
  } catch { /* unknown balance -> no affordability claim, which is the honest default */ }
}
async function loadFx() {
  if (fxRates.value) return
  try {
    const r = await fetch('/api/v1/teg/fx/rates')
    if (r.ok) fxRates.value = await r.json()
  } catch { /* no rates → no conversions, and the native price still shows */ }
}
/** Every listing this registry can SEE — local venue ∪ the federated catalog.
 *  `/agora/listings` is local-only, which is why the first cut had "no
 *  foreign stocks listed": it never asked the network. */
async function allListings(): Promise<StockRow[]> {
  const r = await api('/agora/network-listings')
  const rows = (r.body?.listings || []) as any[]
  const net = rows.map(normalizeListing)
  // The network catalog carries no `stats`, so local rows are re-read from the
  // local venue where the live book actually lives.
  const l = await api('/agora/listings')
  const locals = new Map(((l.body?.listings || []) as any[]).map(x => [String(x.symbol).toUpperCase(), normalizeListing(x)]))
  const merged = net.map(x => locals.get(x.symbol) ?? x)
  // 🔴 And the FOREIGN half: the network catalog carries no `stats`, so without
  // this every off-venue listing is priced at its founding float — SYBIL at 5.0
  // while it trades at 105.1, which is exactly why a passport buy came back
  // "price outside ±25% band around 105.1". federation-tickers is where foreign
  // `last` actually lives.
  const tk = await api('/agora/federation-tickers')
  return mergeTickers(merged, tk.body)
}

// Per-card buy quantity. Keyed by message id so two listing cards in the same
// thread keep their own.
const buyQty = ref<Record<string, number>>({})
// `/stock SMKD 5` seeds the card that command posts, so the size you typed is
// the size on the button.
const symQty = ref<Record<string, number>>({})
// What the buy is waiting on, said out loud: a certificate that takes a few
// seconds is fine, a silent gap is not.
const certWait = ref<string | null>(null)
const localNotes = ref<Array<{ id: string; title: string; lines: string[]; foot: string;
                             afterSeq: number; ord: number;
                             stats?: Array<{ k: string; v: string }> }>>([])
let noteOrd = 0
function qtyFor(m: any): number {
  const sym = String((m?.card as any)?.data?.symbol || '').toUpperCase()
  return buyQty.value[m.id] ?? symQty.value[sym] ?? 1
}

/** What this click is about to spend, so the size is a decision and not a surprise.
 *
 *  ⚠ Deliberately APPROXIMATE (≈). The card's price was live when the card was posted,
 *  but buyShare() re-reads the venue before anything moves — the vocabulary is explicit
 *  that a price pasted into a conversation is stale the moment it is sent. So this shows
 *  the size × the price on the card and marks it as such; the receipt afterwards states
 *  what was actually paid. Showing a hard total here would be the more confident lie. */
function buyLabel(m: any): string {
  const n = qtyFor(m)
  const d = (m?.card as any)?.data || {}
  const px = Number(d.last_price)
  if (!px || !d.currency) return tp('showcaseChat.buyN', 'Buy {n}', { n: String(n) })
  const total = trimDecimal(String(px * n))
  return tp('showcaseChat.buyNfor', 'Buy {n} · ≈{total} {ccy}',
            { n: String(n), total, ccy: String(d.currency) })
}

async function pushNote(title: string, lines: string[], foot: string,
                        stats?: Array<{ k: string; v: string }>) {
  // ANCHORED TO `seq`, NOT TO A CLOCK. A local read produces no server message,
  // so it has no seq of its own; it is pinned to the highest seq that existed
  // when it ran. Using Date.now() here would order the thread by the BROWSER's
  // clock against the SERVER's timestamps — right until the two disagree.
  const afterSeq = messages.value.reduce((a: number, m: any) => Math.max(a, Number(m.seq) || 0), 0)
  localNotes.value.push({ id: `n-${Date.now()}-${localNotes.value.length}`, title, lines, foot,
                          afterSeq, ord: ++noteOrd, stats })
  if (localNotes.value.length > 4) localNotes.value.shift()
  // Scroll to it: a read that lands off-screen reads as nothing happening.
  await nextTick()
  threadEl.value?.scrollTo({ top: threadEl.value.scrollHeight })
}
/** 🔴 ONE ORDERED STREAM — his report: he typed `/stocks` FIRST, then
 *  `/stock WASH`, then bought, and the /stocks answer rendered BELOW the listing
 *  card and the certificate. The oldest thing on screen looked like the newest.
 *
 *  Cause: local reads lived in a SECOND `v-for` after the message loop, so they
 *  were always last no matter when they happened. Two sibling loops cannot
 *  interleave; there has to be one list. */
const stream = computed(() => {
  const msgs = [...messages.value].sort((a: any, b: any) => (Number(a.seq) || 0) - (Number(b.seq) || 0))
  const notes = [...localNotes.value].sort((a, b) => (a.afterSeq - b.afterSeq) || (a.ord - b.ord))
  const out: Array<{ key: string; m?: any; nt?: any }> = []
  let i = 0
  const drain = (upto: number) => {
    while (i < notes.length && notes[i].afterSeq <= upto) { const n = notes[i++]; out.push({ key: n.id, nt: n }) }
  }
  for (const m of msgs) {
    const sq = Number(m.seq) || 0
    drain(sq - 1)                 // notes that belong before this message
    out.push({ key: m.id, m })
    drain(sq)                     // notes produced while THIS was the newest message
  }
  drain(Number.MAX_SAFE_INTEGER)  // anything after the last message
  return out
})

const services = ref<Array<{ id: string; name: string; price: string; currency: string
                             native: string }>>([])
const threadEl = ref<HTMLElement | null>(null)
let poll: number | null = null

const currency = computed(() => session.value?.currency || null)
const ctx = computed<ComposerCtx>(() => ({
  actingCurrency: currency.value,
  agentThread: !!partner.value,
  room: null,
  // This surface holds a real funded visitor agent, so /balance can answer.
  // Pocket leaves it unset and the command dims there rather than going dead.
  wallet: !!session.value?.access_token,
}))
const groups = computed(() => commandGroups(ctx.value))
const suggestions = computed(() => (draft.value.startsWith('/') ? completions(draft.value, ctx.value).slice(0, 6) : []))
// The ledger filter, and the reason per-visitor agents exist. This feeds the
// BridgeLedger's MINE scope (`mineDids`) — the same brain behind the Bridge's MINE button.
// Pointed at a SHARED identity it matched every visitor's events, so the filter
// was correct and still read as unfiltered. Pointed at an agent that belongs to
// exactly one visitor, "these are the events your actions caused" is true.
// ⚠ `[]` before there is an agent, NOT null: null means "no filter" and opened
// this ledger on the whole network's firehose, which then emptied the moment an
// agent existed. An empty list is the honest state — a filter is wanted, there
// is nothing to filter on yet.
const ledgerDids = computed(() => (session.value?.agent_did ? [session.value.agent_did] : []))

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && infoOpen.value) infoOpen.value = false
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

async function api(path: string, opts: RequestInit = {}) {
  const h: Record<string, string> = { 'Content-Type': 'application/json', ...(opts.headers as any || {}) }
  if (session.value?.access_token) h.Authorization = `Bearer ${session.value.access_token}`
  const r = await fetch(`/api/v1${path}`, { ...opts, headers: h })
  const body = await r.json().catch(() => ({}))
  return { ok: r.ok, status: r.status, body }
}

/** Taken on the first interaction, never on page load: nobody who scrolls past
 *  should cause a token to be minted or a thread to be created. */
/** Onboarding ONLY — the sub-agent, not a conversation.
 *  Split out because wiring the composer's focus straight to start() created a
 *  THREAD and sent a "Hello" nobody typed, just for clicking into the box. His
 *  instruction was that a click there begins the onboarding; the thread belongs
 *  to the first thing the visitor actually says. It also keeps the older
 *  property true: a free command creates no conversation state. */
async function ensureAgent(): Promise<boolean> {
  if (session.value) return true
  if (onboarding.value) return false          // a second click must not mint a second agent
  onboarding.value = true
  try {
    onboardSteps.value = [{
      key: 'pending',
      label: t('showcaseChat.obPending', 'Creating an agent for you'),
      detail: t('showcaseChat.obPendingD', 'Spawning a real identity on this registry, bounding what it may do, and funding it from the showcase agent.'),
      ok: true,
    }]
    const s = await fetch('/api/v1/public/showcase/onboard', { method: 'POST' })
    const sb = await s.json().catch(() => ({}))
    // The steps are rendered whether it worked or not: a refusal that is shown
    // at the step it happened on is worth more than a banner that says "error".
    if (Array.isArray(sb?.steps) && sb.steps.length) onboardSteps.value = sb.steps
    else onboardSteps.value = []
    if (!s.ok) {
      // A frame with no identity of its own is not broken — its service calls
      // still work by relaying. Say which, rather than showing a dead box.
      sessionError.value = sb.error || t('showcaseChat.noSession', 'This registry does not issue showcase agents.')
      return false
    }
    session.value = sb
    return true
  } finally {
    onboarding.value = false
  }
}

/** §SHOWCASEBAL — spending oversight, built on the balance this file ALREADY
 *  keeps for affordability hints rather than a second copy of it. Two numbers
 *  that must agree about money and are fetched separately do not stay agreeing.
 *  `spent` is DERIVED — opening float minus what the ledger says is left — so it
 *  cannot drift from the money either. */
const openingFloat = computed(() => {
  const n = Number(session.value?.float)
  return Number.isFinite(n) && n > 0 ? n : null
})
const spent = computed(() => {
  if (balance.value === null || openingFloat.value === null) return null
  const d = openingFloat.value - balance.value
  return d > 0 ? d : 0
})
function money(n: number): string {
  return n >= 100 ? n.toFixed(2) : n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
}

/** Agent + thread. Everything that actually says something goes through here. */
async function start(): Promise<boolean> {
  if (convId.value) return true
  if (!(await ensureAgent())) return false
  return await openThread()
}

async function openThread(which?: { id: string; name: string }): Promise<boolean> {
  // A named agent opens (or reuses) ITS thread — the same agent_service rail
  // first contact already uses, so /call @Someone needs no new endpoint.
  const svc = which || services.value[0]
  if (!svc) { sessionError.value = t('showcaseChat.noSvc', 'No showcase services are listed here.'); return false }
  const r = await api('/chat/conversations', {
    method: 'POST',
    body: JSON.stringify({
      kind: 'agent_service',
      target: { ptype: 'agent', agent_did: svc.id },
      first_message: { kind: 'text', body: t('showcaseChat.hello', 'Hello — what can you do?'), client_ref: `scs-${Date.now()}` },
    }),
  })
  if (!r.ok) { sessionError.value = JSON.stringify(r.body?.error ?? r.body).slice(0, 200); return false }
  convId.value = r.body.conversation_id
  partner.value = { did: svc.id, name: svc.name }
  // `which` is present only when the reader named an agent (/call @Name).
  if (which) partnerChosen.value = true
  await refresh()
  void loadBalance()
  if (poll === null) poll = window.setInterval(refresh, 4000)
  return true
}

/** A real purchase of shares — on THIS venue's book when the listing is local,
 *  or relayed to the venue that lists it when it is not. The sub-agent's own
 *  per-tx cap is the boundary, not a hidden button, and a refusal is shown by
 *  name rather than swallowed. Both roads end at issueCertificate(): a buy that
 *  moves money and leaves no artifact is the defect this closes. */
/** §CALLFORMAT — how do I phrase this call? THE AGENT SAYS SO.
 *
 *  The convention is the A2A standard field `skills[].examples`, read from the
 *  agent's own card. Nothing is hardcoded per agent here and nothing is guessed:
 *  an agent that publishes examples is explained automatically, and one that
 *  publishes none is SAID to publish none rather than given an invented format.
 *  That is what makes this work for future agents without touching this file. */
async function agentHowTo(did: string): Promise<{ desc: string; examples: string[] } | null> {
  try {
    const r = await api(`/agents/by-did/${encodeURIComponent(did)}`)
    if (!r.ok) return null
    const sk = ((r.body?.card_data?.skills || []) as any[])[0] || {}
    const ex = (sk.examples || []).map((x: any) => String(x)).filter(Boolean).slice(0, 4)
    return { desc: String(sk.description || r.body?.card_data?.description || '').slice(0, 200), examples: ex }
  } catch { return null }
}

/** Post the agent's own instructions into the thread, as a local read. */
async function tellHowTo(did: string, name: string) {
  const how = await agentHowTo(did)
  const lines: string[] = []
  if (how?.desc) lines.push(how.desc)
  if (how?.examples?.length) {
    lines.push(t('showcaseChat.howTry', 'Try:'))
    how.examples.forEach(e => lines.push(`/call ${name} ${e}`))
  } else {
    // Never invent a format for an agent that has not published one.
    lines.push(t('showcaseChat.howNone', 'This agent has not published example inputs, so there is no format to quote. Describe what you want in plain words.'))
  }
  pushNote(`${t('showcaseChat.howTitle', 'How to call')} ${name}`, lines,
           t('showcaseChat.howFoot', 'Taken from this agent\'s own card (A2A skills.examples) — not from anything hardcoded here.'))
}

/** §S13 — /call has an ask but nobody to ask, and nobody was chosen.
 *
 *  ⚠ The example here is BUILT FROM THE LIVE AGENT LIST, never written out.
 *  The old refusal said *"try /call weather in Berlin"* — a form this parser
 *  rejects, because with no DID and no chosen partner there is no thread to
 *  post to. A hint that teaches a form the code does not accept is the same
 *  class as a `t()` call with no bundle entry: it reads as help and is not.
 *
 *  ⚠ And `tellHowTo` has always printed `/call <Name> <ask>` from the agent's
 *  own A2A `skills.examples` — so the app was ALREADY teaching the name form
 *  while the parser folded the name into the question. That is the "confuses
 *  everything and doesn't produce a good answer" half of his report: the agent
 *  really was being asked *"WeatherAgent what is the weather in Berlin"*. */
function callNeedsAgent(suggestion?: string, ambiguous?: string[]) {
  const lines = services.value.slice(0, 6).map(sv => `${sv.name} — ${sv.price} ${sv.currency}`)
  const foot: string[] = []
  if (ambiguous && ambiguous.length > 1) {
    // Several match. Naming them all is the honest answer; picking one by list
    // order is how a word gets eaten out of somebody's question.
    foot.push(`${t('showcaseChat.callSeveral', 'Several agents match that word')}: ${ambiguous.join(', ')}.`)
  } else if (suggestion) {
    foot.push(`${t('showcaseChat.callTry', 'Try')}: ${suggestion}`)
  }
  foot.push(t('showcaseChat.callWhoFoot',
    'Name the agent, or paste its DID. /find searches the wider federation.'))
  pushNote(t('showcaseChat.callWho2', '/call needs an agent'), lines, foot.join('  '))
}

/** §CERTEVERYBUY — his rule, made structural: "every buy must provide share
 *  cert". EVERY path that moves money for shares ends here, and this is the only
 *  place a certificate is asked for.
 *
 *  WHY IT POLLS. The position is written by the order rail and read by the
 *  certificate rail, so even a local fill can lose the race; a FOREIGN buy is
 *  relayed and fills at the venue seconds later, so the first ask is expected to
 *  come back "not yet". Giving up after one retry is how a real purchase ended
 *  up with no artifact — the defect he found.
 *
 *  WHO SIGNS. `venue` is set only for a foreign holding, and it makes the rail
 *  fetch the certificate FROM that venue: a registry may sign only for the cap
 *  table it keeps. Failure is stated, never swallowed. */
async function issueCertificate(sym: string, venue: string | null): Promise<boolean> {
  const deadline = Date.now() + (venue ? 75000 : 20000)
  let last = ''
  while (Date.now() < deadline) {
    const c = await api(`/chat/conversations/${convId.value}/certificate`, {
      method: 'POST',
      body: JSON.stringify({ symbol: sym, ...(venue ? { venue_registry: venue } : {}),
                             client_ref: `scs-cert-${sym}-${Date.now()}` }),
    })
    if (c.ok) { await refresh(); return true }
    last = fmtErr(c.body)
    // 501 = the venue that holds the shares cannot issue a certificate at all
    // (older build). Waiting 75s for that is waiting for nothing; say it once.
    if (c.status === 501) break
    certWait.value = venue
      ? `${t('showcaseChat.certWaitV', 'Waiting for')} ${venue} ${t('showcaseChat.certWaitV2', 'to record the points, then the certificate is issued there…')}`
      : t('showcaseChat.certWait', 'Issuing the holding certificate…')
    await new Promise(r => setTimeout(r, 2500))
    await refresh()
  }
  certWait.value = null
  notice.value = `${notice.value || ''} ${t('showcaseChat.certFail', 'The certificate could not be issued:')} ${last}`.trim()
  return false
}

async function buyShare(card: any, qty = 1) {
  const sym = String(card?.data?.symbol || '').toUpperCase()
  const n = Math.max(1, Math.floor(Number(qty) || 1))
  if (!sym || busy.value) return
  busy.value = true; refusal.value = null; notice.value = null
  try {
    await loadFx()
    // 🔴 RE-READ THE VENUE. The card's price is decoration — the closed
    // vocabulary says so in as many words, because "a price pasted into a
    // conversation is stale the moment it is sent and must never be what
    // somebody trades against". So the number we act on comes from the book
    // now, not from the card.
    const rows = await allListings()
    const row = rows.find(l => l.symbol === sym)
    if (!row) { refusal.value = `${t('showcaseChat.noSym', 'No listing called')} “${sym}”.`; return }
    // Say WHY rather than failing on click: halted, delisted, still in IPO, or
    // simply no book yet are all facts the venue publishes.
    await loadBalance()
    const tr = tradability(row, tradeCtx.value)
    if (!tr.ok) {
      refusal.value = `${sym} ${t('showcaseChat.cannotTrade', 'cannot be bought right now —')} ${tr.reason}.`
      return
    }
    const eff = effectivePrice(row)
    if (!eff.value) { refusal.value = t('showcaseChat.noPrice', 'That listing has no price to trade against yet.'); return }

    let filled = false
    if (!row.isLocal) {
      // A FOREIGN venue: the Passport rail relays the order over federation
      // mTLS and funds the venue's gateway with auto-FX. This is the same road
      // the simulation's execution-clerks take, not a new one.
      const r = await api('/agora/passport/orders', {
        method: 'POST',
        body: JSON.stringify({ venue_registry: row.origin, listing: sym,
                               side: 'buy', qty: n, price: eff.value }),
      })
      if (!r.ok) { refusal.value = fmtErr(r.body); return }
      notice.value = `${t('showcaseChat.passportSent', 'Passport order relayed to')} ${row.origin}: ${eff.value} ${row.currency}. ${t('showcaseChat.passportNote2', 'It fills at the market, and the certificate is issued by the market that holds the register.')}`
      draft.value = ''
      await refresh()
      // 🔴 THIS RETURNED HERE, AND THAT WAS THE DEFECT HE REPORTED: a foreign
      // buy took the money, relayed the order, and never asked anyone for a
      // certificate — so the same symbol produced an artifact on the registry
      // that lists it and nothing at all on one that does not.
      await issueCertificate(sym, row.origin)
      return
    }

    // LOCAL venue: a real limit order on the real book, at the live ask.
    const r = await api('/agora/orders', {
      method: 'POST',
      // `order_type`, not `type` — checked against PlaceOrderRequest rather
      // than guessed, after three invented field names in one week.
      body: JSON.stringify({ listing: sym, side: 'buy', qty: n, price: eff.value,
                             order_type: 'limit', tif: 'ioc' }),
    })
    if (!r.ok) { refusal.value = fmtErr(r.body); return }
    // The response carries `fills[]`, `status`, `remaining` — there is no
    // `filled_qty` and no `avg_price`, whatever they would sound like. Read the
    // fills, which is the only place a real execution price exists.
    const fills = (r.body?.fills || []) as any[]
    filled = fills.length > 0
    const qtyFilled = fills.reduce((a, f) => a + Number(f.qty || 0), 0)
    const notional = fills.reduce((a, f) => a + Number(f.notional || 0), 0)
    const paid = filled && qtyFilled
      ? trimDecimal(String(notional))            // what this order actually cost
      : trimDecimal(String(eff.value))
    const conv = fxConvert(paid, row.currency, currency.value || row.currency, fxRates.value)
    notice.value = filled
      ? `${t('showcaseChat.boughtN', 'Bought')} ${qtyFilled} ${sym} ${t('showcaseChat.forPrice', 'for')} ${paid} ${row.currency}${conv && currency.value !== row.currency ? ` (≈ ${conv} ${currency.value})` : ''}. ${t('showcaseChat.watchLedger', 'Watch the ledger.')}`
      // IOC: match now, cancel the remainder. So an unfilled order does NOT
      // rest — saying "resting" would be false, and leaving one resting would
      // strand locked escrow on an agent this registry is about to sweep.
      // Nothing was bought and nothing is owed; say exactly that.
      : `${t('showcaseChat.noFill', 'Nobody is selling')} ${sym} ${t('showcaseChat.atPrice', 'at')} ${paid} ${row.currency} ${t('showcaseChat.rightNow', 'right now, so the order was cancelled. Nothing moved.')}`
    await refresh()

    // The artifact. Only after a real fill, and minted by the REGISTRY on its
    // own read of the cap table — a client cannot author one.
    if (filled) await issueCertificate(sym, null)
  } catch {
    refusal.value = t('showcaseChat.net', 'Could not reach this registry.')
  } finally { busy.value = false; certWait.value = null }
}

/** Throttled so the 4s message poll does not hammer the TEG, and folded into
 *  `refresh()` rather than bolted onto each spend site ON PURPOSE: enumerating
 *  the money paths means the readout goes stale the day someone adds a
 *  seventeenth one, and a spending display that is quietly stale is worse than
 *  no display. Settlement that happens server-side is caught here too. */
let lastBal = 0
async function maybeRefreshBalance(): Promise<void> {
  const now = Date.now()
  if (now - lastBal < 6000) return
  lastBal = now
  await loadBalance()
}

async function refresh() {
  if (!convId.value) return
  void maybeRefreshBalance()
  const r = await api(`/chat/conversations/${convId.value}/messages?limit=40`)
  if (!r.ok) return
  const mine = session.value?.agent_did?.toLowerCase()
  // 🔴 THE AUTO-COLLAPSE. This poll runs every 4 seconds and used to rebuild
  // every row with `expanded: false`, so a receipt you opened to read shut
  // itself within four seconds — "it collapses without my doing", and he was
  // exactly right that it was the refresh. Carry the open state across by id.
  const wasOpen = new Map(messages.value.map(m => [m.id, !!m.expanded]))
  // Reading is not scrolled away from, either: only follow the tail if the
  // reader was already at it.
  const el = threadEl.value
  const atBottom = !el || (el.scrollHeight - el.scrollTop - el.clientHeight) < 60
  messages.value = (r.body.messages || []).map((m: any) => ({
    id: m.id, seq: m.seq, kind: m.kind, body: m.body, card: m.card,
    sender: m.sender_display_name || m.sender_ptype || '—',
    mine: String(m.sender_agent_did || '').toLowerCase() === mine,
    at: m.created_at, expanded: wasOpen.get(m.id) ?? false,
  }))
  await nextTick()
  if (atBottom) threadEl.value?.scrollTo({ top: threadEl.value.scrollHeight })
}

async function send() {
  const raw = draft.value.trim()
  if (!raw || busy.value) return
  busy.value = true; refusal.value = null; notice.value = null
  try {
    // Parse FIRST. /help and an unknown command are answered locally and must
    // not be gated behind opening a session and creating a thread - my first
    // cut put start() ahead of them, so asking for help silently did nothing
    // whenever the session could not be taken. A free command should never
    // depend on a paid one.
    const intent = parseComposer(raw, ctx.value)

    // TOGGLES. Typing /help twice used to leave the sheet open forever with no
    // way to shut it, eating a third of the thread.
    if (intent.kind === 'help') { helpOpen.value = !helpOpen.value; draft.value = ''; return }

    if (intent.kind === 'unknown-slash') {
      // refused BY NAME — "unknown" is a worse answer than "that is not a command here"
      refusal.value = t('showcaseChat.unknownCmd', 'There is no such command:') + ' ' + intent.cmd
      draft.value = ''
      return
    }

    // ── PURELY LOCAL REFUSALS — answered before any network work ──────────
    // The parser already knows these are wrong. Making a stranger wait on a
    // session and a thread to be told "give an amount" is both slower and a
    // lie about where the decision was made.
    if (intent.kind === 'pay' || intent.kind === 'request') {
      if (intent.refusal === 'currency-unresolved') {
        // §FOREIGNACT: a number with no unit is a guess, never a price.
        refusal.value = t('showcaseChat.noCcy', 'That amount has no currency, so it cannot be sent.')
        return
      }
      if (intent.refusal === 'amount-missing' || intent.amount == null) {
        // D6-835: the example names the unit this visitor pays in (none while it is unknown: /pay 1 resolves through it)
        refusal.value = tp('showcaseChat.noAmt', 'Give an amount, for example {example}.', { example: currency.value ? `/pay 1 ${currency.value}` : '/pay 1' })
        return
      }
    }
    // §SHOWCASEVISITOR-2 — MOST OF THESE NOW ACTUALLY RUN.
    // This used to be a blanket refusal covering eleven commands, which made a
    // 24-command /help sheet into a menu where almost nothing worked. His
    // words: "i want a showcase and no skeleton which will tell people
    // basically nothing works within it." The sub-agent is scoped and capped,
    // so letting it read and post is safe by construction — the boundary is the
    // spend policy, not the size of the menu.
    // Only three still refuse, and each says why for ITSELF:
    if (intent.kind === 'dispute') {
      // 🔴 THIS WAS A CONSTANT, NOT A CHECK. It said "this session has none"
      // unconditionally — including right after a settled purchase, which is
      // exactly when a reader would reach for it. A refusal that cannot be true
      // or false is not a refusal, it is a lie with a helpful tone.
      if (!(await start())) return
      const tk = await api('/a2a-payment/my-tokens')
      const rows = (tk.body?.tokens || tk.body?.items || (Array.isArray(tk.body) ? tk.body : [])) as any[]
      const spent = rows.filter(r => ['SETTLED', 'CONSUMED', 'settled', 'consumed']
                                      .includes(String(r?.status || '')))
      if (!spent.length) {
        // NAME THE DISTINCTION HE HIT. He had just bought shares and was told
        // "this session has none", which reads as a lie when you are looking at
        // your own certificate. A venue trade is real, and it is not an
        // engagement with an AGENT — there is no counterparty to accuse.
        const pf = await api('/agora/portfolio')
        const held = ((pf.body?.positions || pf.body?.holdings || []) as any[]).length
        refusal.value = held
          ? t('showcaseChat.disputeTrade', 'A dispute is filed against an AGENT you engaged. You hold points here, but a market trade has no counterparty agent to accuse: the market matched you against a book. Buy a service with /call and that call is disputable.')
          : t('showcaseChat.noDispute', 'Nothing to dispute yet — this session has no settled engagement. Buy a service with /call first.')
        draft.value = ''; return
      }
      // 🔴 READ FROM THE PRODUCER, NOT FROM MEMORY. /a2a-payment/my-tokens rows
      // carry `target_agent_did` — measured, not guessed. My first cut read
      // `service_agent_did`/`payee_did` (neither exists) and fell through to the
      // thread partner, which is right ONLY by accident in this thread shape and
      // would accuse the wrong agent anywhere else. The §BRIDGE R1 class.
      const defendant = String(spent[0]?.target_agent_did || partner.value?.did || '')
      if (!defendant) {
        refusal.value = t('showcaseChat.noDefendant', 'Found a settled engagement but no counterparty on it to dispute.')
        draft.value = ''; return
      }
      const d = await api('/disputes/', { method: 'POST', body: JSON.stringify({ defendant_did: defendant }) })
      if (!d.ok) {
        // Say WHY. A dispute refused for a named reason is information; a
        // silent failure is the thing this command was already doing.
        refusal.value = `${t('showcaseChat.disputeNo', 'The dispute rail refused:')} ${fmtErr(d.body)}`
        draft.value = ''; return
      }
      pushNote(t('showcaseChat.disputeT', 'Dispute filed'),
               [`${t('showcaseChat.disputeAgainst', 'against')} ${defendant}`,
                `${t('showcaseChat.disputeId', 'case')} ${d.body?.dispute_id || d.body?.id || '—'}` +
                ` · ${d.body?.status || ''}`,
                `${spent.length} ${t('showcaseChat.disputeEng', 'settled engagement(s) in this session')}`],
               t('showcaseChat.disputeFoot', 'An operator rules on it. Nothing moves until they do.'))
      draft.value = ''; await refresh(); return
    }
    if (intent.kind === 'ignore') {
      refusal.value = t('showcaseChat.noIgnore', 'Blocking would close the only thread you have here. It works in the app, where you have others.')
      draft.value = ''; return
    }

    // everything below this line touches the network
    if (!(await start())) return

    if (intent.kind === 'call') {
      // 🔴 HIS QUESTION: "how should i type it in then?" — he wrote
      // `/call freilassing did:theprotocol:ce1031a8-...` and the whole line,
      // DID included, was sent as the QUESTION ("City 'freilassing did:...'
      // not found"). /call had no notion of a target at all: it always asked
      // this thread's counterparty, so naming an agent could only ever corrupt
      // the question. Naming the agent you just found in /find is the obvious
      // thing to type, so it now works — a DID or an @name ANYWHERE in the line
      // is the target, and what is left is the question.
      //
      // 🔴 §S13, HIS REPORT: "/call weather in berlin doesnt work. if i type
      // /call did:theprotocol:ce1031a8-... berlin it works. otherwise not."
      // Exactly right, and the cause was MINE: before §SHOWCASEBAL the thread
      // auto-opened on services[0], so a target-less /call always had somebody
      // to ask. Making /card stop standing in for a counterparty the reader
      // never chose left /call posting to `/chat/conversations//service-call`
      // with an empty id. A DID worked because a DID names the agent itself.
      //
      // Two things follow. A bare agent NAME is now a target, because "@" is
      // not a thing anyone guesses — and only on an EXACT match, so a question
      // word can never be eaten out of the ask (his "weather" is a question,
      // not an agent, and `WeatherAgent` is the agent). And when there is no
      // target and no chosen partner, the command says so and shows a form
      // that actually works, built from the agents this showcase really has.
      // ONE resolver, in `services/chat/callTarget.ts`, so the rule that decides
      // WHO gets asked — and therefore who gets PAID — is asserted by unit tests
      // rather than only through a WebGL landing page this box cannot reliably
      // drive. A second copy of this parsing here would be the first bug of one.
      const tgt = resolveCallTarget({
        ask: String(intent.ask || ''),
        services: services.value as any,
        partnerChosen: partnerChosen.value,
      })
      const askText = tgt.askText
      const atTok = tgt.unknownAt ? `@${tgt.unknownAt}` : ''
      const didTok = tgt.targetDid
      let targetDid = tgt.targetDid
      if (tgt.unknownAt) {
        refusal.value = `${t('showcaseChat.callNoAgent', 'No agent here called')} “${tgt.unknownAt}”. ` +
          `${t('showcaseChat.callWho', 'Here you can call:')} ${services.value.map(sv => sv.name).join(', ')}`
        draft.value = ''; return
      }
      if ((didTok || atTok) && !askText) {
        // Naming an agent is not a question — but a bare refusal leaves the
        // reader exactly where they were. Answer the question they were really
        // asking: what does this one expect?
        const nm = services.value.find(sv => String(sv.id).toLowerCase() === String(targetDid).toLowerCase())?.name
                   || atTok.slice(1) || targetDid
        await tellHowTo(targetDid, nm)
        draft.value = ''; return
      }
      // `/call` with nothing at all: explain the agent this thread is already on.
      if (!targetDid && !askText) {
        if (partnerChosen.value && partner.value?.did) {
          await tellHowTo(partner.value.did, partner.value.name || 'this agent'); draft.value = ''; return
        }
        callNeedsAgent(tgt.suggestion, tgt.ambiguous); draft.value = ''; return
      }
      // An ask, but nobody to ask. Same rule /card now follows: standing in for
      // a missing argument is only honest when the reader actually CHOSE the
      // counterparty. Refusing here is the whole of his bug report.
      if (tgt.needsAgent && askText) {
        callNeedsAgent(tgt.suggestion, tgt.ambiguous); draft.value = ''; return
      }
      // A different agent means a different agent_service thread. That is the
      // EXISTING first-contact rail, not a new one: open (or reuse) their thread
      // and the call runs there, against them.
      if (targetDid && targetDid.toLowerCase() !== String(partner.value?.did || '').toLowerCase()) {
        const svc = services.value.find(sv => String(sv.id).toLowerCase() === targetDid.toLowerCase())
        if (!svc) {
          refusal.value = `${t('showcaseChat.callNotHere', 'That agent is not one this showcase can call. Here you can call:')} ${services.value.map(sv => sv.name).join(', ')}`
          draft.value = ''; return
        }
        const opened = await openThread(svc)
        if (!opened) { draft.value = ''; return }
        notice.value = `${t('showcaseChat.callSwitched', 'Now talking to')} ${svc.name}.`
      }
      const r = await api(`/chat/conversations/${convId.value}/service-call`, {
        method: 'POST',
        // ServiceCallBody takes `text` (or `payload`), NOT `ask` — my first cut
        // guessed the field name and the rail answered "a service call needs
        // text or a payload", which is it telling me exactly that.
        body: JSON.stringify({ text: askText || intent.ask || raw, client_ref: `scs-call-${Date.now()}` }),
      })
      if (!r.ok) refusal.value = fmtErr(r.body)
      draft.value = ''; await refresh(); return
    }

    if (intent.kind === 'quote') {
      // 🔴 `target_agent_did`, not `agent_did`. This was `agent_did` and had
      // therefore NEVER worked: the endpoint answers 422 "Field required:
      // query -> target_agent_did". Measured both spellings against the live
      // rail — 422 vs 200 — rather than reading the handler and assuming.
      const r = await api(`/a2a-payment/quote?target_agent_did=${encodeURIComponent(partner.value!.did)}`)
      // 🔴 And the field names were invented too: QuoteResponse carries
      // `your_amount` / `your_currency` (and `price` / `price_currency` for the
      // card's own number). Reading `amount`/`currency` rendered "Quote: —"
      // forever — the §BRIDGE R1 class, where a shape is guessed rather than
      // read from the producer. Both halves were broken, so this never worked
      // even once.
      if (!r.ok) notice.value = fmtErr(r.body)
      else if (r.body.payment_required === false) {
        notice.value = t('showcaseChat.quoteFree', 'This agent is free — no payment required.')
      } else {
        const amt = r.body.recommended_amount ?? r.body.your_amount
        const native = r.body.price && r.body.price_currency !== r.body.your_currency
          ? ` (${r.body.price} ${r.body.price_currency} on its card)` : ''
        notice.value = `${t('showcaseChat.quoteIs', 'Quote:')} ${amt ?? '—'} ${r.body.your_currency ?? ''}${native}`
      }
      draft.value = ''; return
    }

    if (intent.kind === 'pay' || intent.kind === 'request') {
      if (intent.kind === 'request') {
        // an ASK is a card, and moves nothing
        await api(`/chat/conversations/${convId.value}/messages`, {
          method: 'POST',
          body: JSON.stringify({ kind: 'card', client_ref: `scs-req-${Date.now()}`,
            card: { v: 1, type: 'pay.request', data: { amount: String(intent.amount), currency: intent.currency, memo: intent.memo || '' } } }),
        })
        draft.value = ''; await refresh(); return
      }
      // /pay REALLY MOVES MONEY — to the thread's counterparty, which is an
      // allowlisted showcase agent. A payment anywhere else is refused by the
      // spend policy, and that refusal is worth seeing.
      // /teg/send, not /teg/transfer. The showcase agents live on registry-a
      // while a visitor may be on any frame, so a plain local transfer answers
      // "that agent is not on this registry" - measured. Smart send picks
      // local / 2PC / FX for itself and reports which it chose, which is also
      // the more honest thing to show a reader.
      const tr = await api('/teg/send', {
        method: 'POST',
        body: JSON.stringify({ receiver_did: partner.value!.did, amount: String(intent.amount),
                               message: intent.memo || 'showcase demo transfer' }),
      })
      if (!tr.ok) { refusal.value = fmtErr(tr.body); return }
      await api(`/chat/conversations/${convId.value}/messages`, {
        method: 'POST',
        body: JSON.stringify({ kind: 'card', client_ref: `scs-rcpt-${Date.now()}`,
          card: { v: 1, type: 'pay.receipt', data: {
            amount: String(intent.amount), currency: intent.currency || currency.value || '',
            counterparty_name: partner.value!.name,
            tx_ref: sendReference(tr.body) } } }),
      })
      // say WHICH route it took - "fx" and "local" are different journeys and
      // the reader is watching a ledger that will show the difference
      notice.value = `${t('showcaseChat.sent', 'Sent. Watch the ledger on the right.')} (${tr.body?.method || 'sent'})`
      draft.value = ''; await refresh(); return
    }

    if (intent.kind === 'balance') {
      // §SHOWCASEBAL — his report: "i have no oversight over my spending".
      // Read the wallet, then state four things a spender needs: what is left,
      // what has gone, what one payment may be, and what the day allows. Posted
      // as a note rather than a chat card: it is YOUR position, not something to
      // share into a thread with a counterparty.
      await loadBalance()
      const ccy = String(session.value?.currency || currency.value || '')
      const lim = session.value?.limits || {}
      const lines: string[] = []
      if (balance.value === null) {
        lines.push(t('showcaseChat.balUnknown', 'The ledger did not answer just now — no number rather than a guessed one.'))
      } else {
        lines.push(`${t('showcaseChat.balHave', 'you hold')} ${money(balance.value)} ${ccy}`)
        if (spent.value !== null) {
          lines.push(`${t('showcaseChat.balSpent', 'spent this session')} ${money(spent.value)} ${ccy}` +
                     (openingFloat.value !== null ? ` ${t('showcaseChat.balOf', 'of an opening')} ${money(openingFloat.value)}` : ''))
        }
      }
      if (lim.max_per_tx) lines.push(`${t('showcaseChat.balTx', 'most one payment may be')} ${lim.max_per_tx} ${ccy}`)
      if (lim.max_per_day) lines.push(`${t('showcaseChat.balDay', 'most this session may spend in a day')} ${lim.max_per_day} ${ccy}`)
      pushNote(t('showcaseChat.balTitle', 'Your position'), lines,
               t('showcaseChat.balFoot', 'Real balance on the public ledger — the same number the ledger on the right is moving.'))
      draft.value = ''; return
    }

    if (intent.kind === 'card') {
      // 🔴 THIS IGNORED ITS ARGUMENT ENTIRELY and always posted the thread's
      // counterparty, so `/card <any did>` returned WeatherAgent every time —
      // including for a DID the reader had just copied out of /find. A command
      // that takes an argument and silently substitutes something else is worse
      // than one that refuses.
      const q = String((intent as any).query || '').trim()
      let did = '', name = ''
      if (!q) {
        // 🔴 His report: the FIRST thing typed was a bare `/card`, and the
        // weather agent's card came back — an agent he had never named. The
        // thread opens on services[0] so there is always someone to talk to,
        // and this branch read that default as if it were an answer. Standing
        // in for a missing argument is only honest when the reader actually
        // chose the counterparty; otherwise the command must say what it needs
        // and point at the way to find it.
        if (!partnerChosen.value) {
          pushNote(
            t('showcaseChat.cardWho', '/card needs an agent'),
            services.value.slice(0, 6).map(sv => `${sv.name} — ${sv.price} ${sv.currency}`),
            t('showcaseChat.cardWhoFoot',
              'Try /card CurrencyAgent, or /find weather to search the federation.'))
          draft.value = ''; return
        }
        did = partner.value?.did || ''; name = partner.value?.name || ''
        if (!did) { refusal.value = t('showcaseChat.cardNeed', '/card needs a name or a DID — try /card CurrencyAgent'); draft.value = ''; return }
      } else if (q.toLowerCase().startsWith('did:')) {
        const r = await api(`/agents/by-did/${encodeURIComponent(q)}`)
        if (!r.ok) { refusal.value = `${t('showcaseChat.cardNoDid', 'No agent on this registry with that DID:')} ${q}`; draft.value = ''; return }
        did = q; name = String(r.body?.name || r.body?.card_data?.name || q)
      } else {
        const r = await api(`/agent-cards/discover?q=${encodeURIComponent(q)}&limit=6`)
        const rows = ((r.body?.results || r.body?.items || []) as any[]).filter(a => a?.did)
        const exact = rows.filter(a => String(a.name || '').toLowerCase() === q.toLowerCase())
        const pick = exact.length === 1 ? exact : rows
        if (!pick.length) { refusal.value = `${t('showcaseChat.cardNoMatch', 'No agent matches')} “${q}”.`; draft.value = ''; return }
        if (pick.length > 1) {
          // Several matches is not an error and must not silently pick one.
          pushNote(t('showcaseChat.cardPick', 'Several agents match') + ` “${q}”`,
                   pick.map(a => `${a.name} — ${a.did}`),
                   t('showcaseChat.cardPickFoot', 'Run /card with the exact name or the DID.'))
          draft.value = ''; return
        }
        did = pick[0].did; name = String(pick[0].name || pick[0].did)
      }
      // §CARDREAL — his report: "/card <did> doesnt provide a real agent card".
      // It posted a name and a DID. Everything a reader wants is already on the
      // agent's OWN card_data, one call away, and the price comes from the SAME
      // brain Discover uses (cardPricing) so the two surfaces cannot disagree
      // about what an agent costs.
      const cardData: any = { did, name }
      try {
        const full = await api(`/agents/by-did/${encodeURIComponent(did)}`)
        const cd: any = full.ok ? (full.body?.card_data || {}) : {}
        if (cd.description) cardData.description = String(cd.description).slice(0, 240)
        const pr = cardPricing(cd)
        if (pr) {
          cardData.price = pr.base_rate; cardData.currency = pr.currency
          cardData.payment_required = pr.payment_required; cardData.price_source = pr.source
        } else {
          cardData.payment_required = false
        }
        try { const h = new URL(String(cd.url || '')).hostname; if (h) cardData.endpoint_host = h } catch { /* no endpoint */ }
        const sk = (cd.skills || []).map((x: any) => x?.name).filter(Boolean).slice(0, 6)
        if (sk.length) cardData.skills = sk
        const reg = cd.federation_metadata?.source_registry || full.body?.origin_registry_name
        if (reg) cardData.registry = String(reg)
      } catch { /* a card that is only a name is still better than a refusal */ }
      await api(`/chat/conversations/${convId.value}/messages`, {
        method: 'POST',
        body: JSON.stringify({ kind: 'card', client_ref: `scs-card-${Date.now()}`,
          card: { v: 1, type: 'agent.card', data: cardData } }),
      })
      draft.value = ''; await refresh(); return
    }

    if (intent.kind === 'me') {
      // His report: "/me does nothing, prints 'you . weatheragent'". It posted
      // the literal string "/me " with nothing after it, which the renderer
      // slices to the empty string — an empty action row between two sender
      // labels. An action with no verb is not an action; say so.
      if (!String(intent.action || '').trim()) {
        refusal.value = t('showcaseChat.meNeeds', '/me needs an action — try /me waves')
        draft.value = ''; return
      }
      await api(`/chat/conversations/${convId.value}/messages`, {
        method: 'POST',
        body: JSON.stringify({ kind: 'text', body: `/me ${intent.action}`, client_ref: `scs-me-${Date.now()}` }),
      })
      draft.value = ''; await refresh(); return
    }

    if (intent.kind === 'ping') {
      const r = await api(`/chat/conversations/${convId.value}/ping`, {
        method: 'POST', body: JSON.stringify({ client_ref: `scs-ping-${Date.now()}` }),
      })
      if (!r.ok) refusal.value = fmtErr(r.body)
      draft.value = ''; await refresh(); return
    }

    // /stock — resolve the symbol against THIS registry's venue before posting,
    // so a card can never point at a listing that does not exist. Ported from
    // the Pocket thread rather than re-invented.
    if (intent.kind === 'stock') {
      // `/stock SMKD 5` — the ticker carries an optional size, so a reader can
      // say it in one line instead of tapping a stepper five times.
      const parts = String(intent.symbol || '').trim().split(/\s+/)
      const sym = (parts[0] || '').toUpperCase()
      const askQty = Math.max(1, Math.floor(Number(parts[1]) || 1))
      if (!sym) { refusal.value = t('showcaseChat.needSym', '/stock needs a ticker — try /stock SMKD, or /stock SMKD 5'); draft.value = ''; return }
      await loadFx()
      const rows = await allListings()
      const row = rows.find(l => l.symbol === sym)
      if (!row) {
        refusal.value = `${t('showcaseChat.noSym', 'No listing called')} “${sym}”. ${t('showcaseChat.trading', 'Trading here:')} ${rows.map(l => l.symbol).slice(0, 12).join(', ')}`
        draft.value = ''; return
      }
      const eff = effectivePrice(row)
      await loadBalance()
      const tstat = tradability(row, tradeCtx.value)
      const card: any = { v: 1, type: 'exchange.listing',
        data: { symbol: row.symbol, display_name: row.displayName, status: row.status } }
      // A price on a card is DECORATION — the vocabulary says so, and the buy
      // re-reads the venue before anything moves. It is here so a reader can
      // see what they are looking at, and it is the LIVE number now, not the
      // founding float price the first cut showed for everything.
      if (eff.value && row.currency) { card.data.last_price = eff.value; card.data.currency = row.currency }
      await api(`/chat/conversations/${convId.value}/messages`, {
        method: 'POST', body: JSON.stringify({ kind: 'card', card, client_ref: `scs-stock-${Date.now()}` }),
      })
      symQty.value[sym] = askQty
      notice.value = priceLine(row, currency.value, fxRates.value, tradeCtx.value)
      if (!tstat.ok) refusal.value = `${sym} ${t('showcaseChat.cannotTrade', 'cannot be bought right now —')} ${tstat.reason}.`
      draft.value = ''; await refresh(); return
    }

    // /stocks — what trades right now, across the whole federation, with live
    // prices and the viewer's currency alongside where a rate exists.
    if (intent.kind === 'stocks') {
      await loadFx()
      const q = String((intent as any).query || '').trim().toUpperCase()
      let rows = await allListings()
      if (q) rows = rows.filter(l => l.symbol.includes(q) || l.displayName.toUpperCase().includes(q))
      await loadBalance()
      rows.sort((a, b) => (a.isLocal === b.isLocal ? a.symbol.localeCompare(b.symbol) : (a.isLocal ? -1 : 1)))
      const nLocal = rows.filter(r => r.isLocal).length
      const nTradeable = rows.filter(r => tradability(r, tradeCtx.value).ok).length
      pushNote(
        t('showcaseChat.stocksT', 'Trading right now'),
        rows.length ? rows.map(r => priceLine(r, currency.value, fxRates.value, tradeCtx.value))
                    : [t('showcaseChat.stocksNone', 'Nothing matched.')],
        `${nTradeable}/${rows.length} ${t('showcaseChat.buyableNow', 'buyable from here')} · ${nLocal} ${t('showcaseChat.here', 'on this market')} · ${rows.length - nLocal} ${t('showcaseChat.elsewhere', 'elsewhere')}. ${t('showcaseChat.stocksFoot2', 'Prices are the market’s own: last traded or best ask, never the launch price. Anything marked NOT TRADEABLE says why. /listing SYM shares one into the thread; /listing SYM 5 sets the size.')}`)
      draft.value = ''; return
    }

    // /find — a PUBLIC read, rendered locally. Posts nothing.
    if (intent.kind === 'find') {
      const q = String(intent.query || '').trim()
      if (!q) { refusal.value = t('showcaseChat.needQ', '/find needs something to look for — try /find weather'); draft.value = ''; return }
      const r = await api(`/agent-cards/discover?q=${encodeURIComponent(q)}&limit=6`)
      const rows = (r.body?.results || r.body?.items || []) as any[]
      pushNote(t('showcaseChat.findT', 'Agents matching') + ` “${q}”`,
        rows.length ? rows.map(a => `${a.name || a.did} — ${a.did}`)
                    : [t('showcaseChat.findNone', 'Nothing matched. Discovery searched the whole federation.')],
        t('showcaseChat.localOnly', 'A public read. Nothing was posted to the thread.'))
      draft.value = ''; return
    }

    // /here — who is in this conversation. Local render of a real read.
    if (intent.kind === 'here') {
      const r = await api(`/chat/conversations/${convId.value}/members`)
      const ms = (r.body?.members || r.body?.participants || []) as any[]
      pushNote(t('showcaseChat.hereT', 'In this conversation'),
        ms.length ? ms.map(m => `${m.name || m.agent_did || m.developer_id} — ${m.ptype || 'participant'}`)
                  : [`${t('showcaseChat.you2', 'you')} · ${partner.value?.name || ''}`],
        t('showcaseChat.localOnly', 'A public read. Nothing was posted to the thread.'))
      draft.value = ''; return
    }

    // /audit — PUBLIC data only, rendered locally, target never notified.
    if (intent.kind === 'audit') {
      const target = (intent as any).target || partner.value?.did
      if (!target) { refusal.value = t('showcaseChat.needTarget', '/audit needs a counterparty.'); draft.value = ''; return }
      const [prof, rec] = await Promise.all([
        api(`/agents/by-did/${encodeURIComponent(target)}`),
        api(`/agents/${encodeURIComponent(target)}/track-record`),
      ])
      const p: any = prof.body || {}
      const tr: any = rec.body?.summary || rec.body || {}
      const lines: string[] = [`${p.name || partner.value?.name || target}`, target]
      if (p.origin_registry_name || p.registry_name) lines.push(`${t('showcaseChat.homedAt', 'homed at')} ${p.origin_registry_name || p.registry_name}`)
      lines.push(`${t('showcaseChat.verifiedJobs', 'verified jobs')}: ${tr.jobs_verified ?? 0}`)
      if (tr.last_verified_at) lines.push(`${t('showcaseChat.lastWork', 'last verified work')}: ${String(tr.last_verified_at).slice(0, 10)}`)
      pushNote(t('showcaseChat.auditT', 'Background check'), lines,
        t('showcaseChat.auditFoot', 'Public data only, read locally. Nothing was posted, and the agent was not told you looked.'))
      draft.value = ''; return
    }

    // /ledger — where you and this counterparty stand, from what THIS page can
    // see, and it says that bound out loud rather than implying completeness.
    if (intent.kind === 'ledger') {
      // 🔴 SECOND PASS, after he bought ACROSS THE CLUSTER and saw
      // "3 purchases · 0 shares held" and "0 transfers".
      //
      // Both numbers were read from the wrong place, and both were measured
      // before this rewrite rather than guessed again:
      //
      //  SHARES — /exchange/portfolio is LOCAL. A passport buy leaves the shares
      //  on the VENUE's register, so a cluster-wide holding is invisible there:
      //  measured, local positions [] while op-doha's passport portfolio held
      //  DOHA qty 1. The certificates are the right source — each one is a
      //  SIGNED attestation of a holding at a venue, they already span the
      //  cluster, and they need no extra call. Deduplicated per (venue, symbol)
      //  keeping the LATEST, because a certificate states a HOLDING and not a
      //  trade: buy 1 then 1 more and the second says 2, so summing every card
      //  would count the same share twice.
      //
      //  TRANSFERS — this counted pay.receipt cards, which a purchase never
      //  writes, so it read 0 while money was plainly moving. /teg/transactions
      //  is the rail that knows: {transactions,total,...} with a `type` per row
      //  (cross_teg_send, lock, exchange_order_deposit, transfer).
      if (!(await start())) return
      const [tk, tx] = await Promise.all([
        api('/a2a-payment/my-tokens'),
        api('/teg/transactions?limit=100'),
      ])
      const tokens = (tk.body?.tokens || tk.body?.items || (Array.isArray(tk.body) ? tk.body : [])) as any[]
      const settled = tokens.filter(x => String(x?.status || '').toLowerCase() === 'settled')
      const spent = settled.reduce((a, x) => a + (Number(x?.amount) || 0), 0)
      const txRows = (tx.body?.transactions || []) as any[]
      const moves = Number(tx.body?.total ?? txRows.length) || 0
      // 🔴 TWO MISTAKES HERE, BOTH FROM GUESSING, AND HE CAUGHT THEM: two real
      // cross-FX transfers counted 0.
      //   1. The field is `transaction_type`, not `type` — and my own probe had
      //      hidden that from me by printing `r.type || r.transaction_type`, so
      //      the fallback made a wrong field name look right.
      //   2. A cross-CURRENCY buy does not write `cross_teg_send`. It writes an
      //      FX swap: reason="fx_swap_lock" surfacing as `fx_fx_swap_lock`
      //      (teg_integration.py:5327). `cross_teg_send` is the SAME-currency,
      //      cross-registry case, which is why an earlier same-currency test
      //      made the wrong filter look correct.
      // Matched by family rather than by a literal, so a new member of either
      // family is counted instead of silently ignored.
      const ttype = (r: any) => String(r?.transaction_type || r?.type || '')
      const crossLegs = txRows.filter(r => {
        const tt = ttype(r)
        return tt.startsWith('fx_') || tt.includes('cross_teg') || tt.includes('cross_registry')
      }).length

      const cards = messages.value.filter(m => m.card)
      const cd = (m: any) => (m.card as any)?.data || {}
      const certs = cards.filter(m => (m.card as any)?.type === 'share.certificate')
      const results = cards.filter(m => (m.card as any)?.type === 'service.result')
      const free = results.filter(m => !cd(m).paid_amount).length
      const home = currency.value || ''

      // latest certificate per (venue, symbol) — a holding, not a trade
      const held = new Map<string, { qty: number; venue: string }>()
      for (const m of certs) {
        const d = cd(m)
        const k = `${String(d.venue_registry || '')}|${String(d.symbol || '')}`.toLowerCase()
        held.set(k, { qty: Number(d.qty) || 0, venue: String(d.venue_registry || '') })
      }
      const shares = [...held.values()].reduce((a, x) => a + x.qty, 0)
      const venues = new Set([...held.values()].map(x => x.venue).filter(Boolean)).size

      // (An earlier cut ALSO counted cross-currency service calls from the agent
      //  list. Dropped: paying an agent priced in another currency writes its own
      //  fx_ leg in the ledger above, so adding it here counted the same crossing
      //  twice. One source of truth.)

      pushNote(t('showcaseChat.ledgerT', 'This session, so far'), [],
        t('showcaseChat.ledgerFoot3', 'Holdings are counted from your signed certificates, which span every market you bought on; money movements come from the TEG ledger. Local read: nothing was posted.'),
        [
          { k: t('showcaseChat.lCalls', 'service calls'),
            v: `${settled.length}${spent ? ` · ${trimDecimal(String(spent))} ${home}` : ''}${free ? ` · ${free} ${t('showcaseChat.lFree', 'unpaid')}` : ''}` },
          { k: t('showcaseChat.lShares', 'points held'),
            v: `${shares}${venues ? ` · ${venues} ${venues === 1 ? t('showcaseChat.lVenue', 'market') : t('showcaseChat.lVenues', 'markets')}` : ''}` },
          // NOT certs.length. A certificate attests a HOLDING, so asking for one
          // twice on the same holding yields two cards and no second purchase —
          // measured while checking this very number. Distinct (venue, symbol)
          // is the thing that is actually true.
          { k: t('showcaseChat.lHoldings', 'holdings'), v: String(held.size) },
          { k: t('showcaseChat.lMoves', 'money movements'), v: String(moves) },
          { k: t('showcaseChat.lFx', 'cross-frame legs'), v: String(crossLegs) },
          { k: t('showcaseChat.lMsgs', 'messages'), v: String(messages.value.length) },
        ])
      draft.value = ''; return
    }

    // /work — honest emptiness beats a refusal: a brand-new session has no work.
    if (intent.kind === 'work') {
      const r = await api('/contracts/v2/mine')
      const items = (r.body?.items || r.body || []) as any[]
      pushNote(t('showcaseChat.workT', 'Work you are a party to'),
        (Array.isArray(items) && items.length)
          ? items.slice(0, 5).map((c: any) => `${c.title || c.ref || c.id} — ${c.status || ''}`)
          : [t('showcaseChat.workNone', 'None yet. This agent was created minutes ago — contracts and guild orders show up here once it has some.')],
        t('showcaseChat.localOnly', 'A public read. Nothing was posted to the thread.'))
      draft.value = ''; return
    }

    if (intent.kind === 'timer') {
      pushNote(t('showcaseChat.timerT', 'Retention'), [
        t('showcaseChat.timerL', 'This thread is kept until the session agent is swept, then it goes with it.'),
      ], t('showcaseChat.timerF', 'In the app you can set 1h / 1d / 1w / 30d or none per thread.'))
      draft.value = ''; return
    }

    // plain text
    await api(`/chat/conversations/${convId.value}/messages`, {
      method: 'POST',
      body: JSON.stringify({ kind: 'text', body: raw, client_ref: `scs-txt-${Date.now()}` }),
    })
    draft.value = ''; await refresh()
  } catch {
    refusal.value = t('showcaseChat.net', 'Could not reach this registry.')
  } finally {
    busy.value = false
  }
}

/** Headline + sub for a card, derived from the REAL CardView union.
 *  cards.ts is the one vocabulary; this only decides how a landing page says it. */
function cardLine(card: ChatCard): { label: string; head: string; sub: string } {
  const v: any = cardView(card, {})
  const money = (a: any, c: any) => [a, c].filter(Boolean).join(' ')
  switch (v?.type) {
    case 'pay.request':
      return { label: 'payment requested', head: money(v.amount, v.currency), sub: v.memo || '' }
    case 'pay.receipt':
      return { label: 'receipt', head: money(v.amount, v.currency),
               sub: v.converted && v.receivedAmount ? `arrived as ${money(v.receivedAmount, v.receivedCurrency)}` : (v.txId || '') }
    case 'service.call':
      return { label: 'service call', head: v.ask || '—', sub: v.status || '' }
    case 'service.result':
      return { label: v.ok ? 'answer' : 'no answer', head: v.summary || v.resultText || '—',
               sub: v.paidAmount ? `paid ${money(v.paidAmount, v.paidCurrency)}` : (v.error || '') }
    case 'agent.card':
      return { label: 'agent', head: v.name || v.did,
               sub: [v.paymentRequired === true && v.price
                       ? `${v.price} ${v.currency || ''}`.trim() + ' ' + t('showcaseChat.perReq', 'per request')
                       : (v.paymentRequired === false ? t('showcaseChat.freeCall', 'free to call') : ''),
                     v.description, v.skills?.length ? v.skills.join(', ') : '',
                     v.endpointHost, v.registry, v.did]
                    .filter(Boolean).join(' · ') }
    case 'contract.offer':
    case 'guild.order':
      return { label: v.type, head: v.title || v.ref, sub: money(v.amount, v.currency) }
    case 'share.certificate':
      // The signature is the whole point, so an UNSIGNED certificate says so in
      // the label rather than looking identical to a signed one.
      return {
        label: v.signature ? 'holding certificate · signed' : 'holding certificate · UNSIGNED',
        head: `${v.qty} ${v.symbol}${v.displayName ? ' — ' + v.displayName : ''}`,
        sub: [v.certificateId, v.venue, v.signature ? `${v.signatureAlg} ${v.pubkeyId || ''}`.trim() : (v.unsignedReason || '')]
               .filter(Boolean).join(' · '),
      }
    default:
      return { label: String(card?.type || 'card'), head: '', sub: '' }
  }
}

function fmtErr(b: any): string {
  const d = b?.error?.detail || b?.detail || b?.error
  return typeof d === 'string' ? d : JSON.stringify(d ?? b).slice(0, 220)
}

async function loadServices() {
  try {
    const r = await fetch('/api/v1/public/showcase/agents')
    const d = await r.json()
    // the DID is what a thread is addressed by; the list gives ids + names
    services.value = (d.agents || []).map((a: any) => ({
      id: a.did || a.agent_did || a.id, name: a.name,
      price: a.price_local || a.price, currency: a.currency_local || a.currency,
      // KEEP THE NATIVE CURRENCY. The list carries both (0.5 AVT priced, 0.60
      // BVT local) and this kept only the local one — so nothing downstream
      // could tell that paying a BVT balance for an AVT-priced agent CROSSED.
      // The payment token is no help: it always records the payer's currency.
      native: a.currency || '',
    })).filter((a: any) => String(a.id || '').startsWith('did:'))
  } catch { /* the panel says so on first send */ }
}

onMounted(loadServices)
onUnmounted(() => { if (poll) window.clearInterval(poll) })
</script>

<template>
  <div class="oc" data-testid="showcase-chat">
    <div class="oc-head">
      <div class="oc-title-row">
        <Icon name="mdi:chat" class="oc-title-icon" />
        <h3 class="oc-title">{{ t('showcaseChat.title2', 'OurChat, live') }}</h3>
        <button class="oc-help-btn" data-testid="showcase-help" @click="helpOpen = !helpOpen">/help</button>
        <button class="oc-info-btn" data-testid="showcase-info"
                :aria-label="t('showcaseChat.about', 'What is this?')"
                @click="infoOpen = true">i</button>
      </div>
      <p class="oc-lede">
        {{ t('showcaseChat.lede5', 'A real thread on this registry — no account. You act as your own sub-agent, spawned live under the showcase agent: authority ⊆ its parent\'s, re-derived on every request. Deterministic code end to end — no language model anywhere.') }}
      </p>
      <div v-if="session && balance !== null" class="oc-purse" data-testid="showcase-purse">
        <Icon name="mdi:wallet" class="oc-purse-icon" />
        <span class="oc-purse-have">{{ money(balance) }} {{ session.currency || '' }}</span>
        <span v-if="spent !== null && spent > 0" class="oc-purse-spent">
          &#32;·&#32;{{ t('showcaseChat.purseSpent', 'spent') }}&#32;{{ money(spent) }}
        </span>
        <span v-else-if="openingFloat !== null" class="oc-purse-spent">
          &#32;·&#32;{{ t('showcaseChat.purseNone', 'nothing spent yet') }}
        </span>
        <button type="button" class="oc-purse-cmd" data-testid="showcase-purse-cmd"
                @click="draft = '/balance'">/balance</button>
      </div>
      <div class="oc-facts" data-testid="showcase-facts">
        <span class="oc-fact oc-fact-key">
          <Icon name="mdi:account-plus" /> {{ t('showcaseChat.f1', 'sub-agent, spawned per session') }}
        </span>
        <span class="oc-fact">{{ t('showcaseChat.f2b', 'authority ⊆ parent · live') }}</span>
        <span class="oc-fact">{{ t('showcaseChat.f3b', 'pays only the 11 showcase agents') }}</span>
        <span class="oc-fact">{{ t('showcaseChat.f4b', 'capped · per tx / day / hour') }}</span>
        <span class="oc-fact">{{ t('showcaseChat.f7', 'real balance → public ledger') }}</span>
        <span class="oc-fact oc-fact-det">{{ t('showcaseChat.f6', 'deterministic — no language model') }}</span>
        <button class="oc-fact oc-fact-more" @click="infoOpen = true">
          {{ t('showcaseChat.f5', 'how it works') }}
        </button>
      </div>
      <!-- Kept as the SESSION-PRESENCE signal two existing batteries assert on,
           but short and true: the old paragraph here still called this "a shared
           demonstration identity", which stopped being true the moment each
           visitor got their own sub-agent. -->
      <p v-if="session" class="oc-shared" data-testid="showcase-session">
        {{ t('showcaseChat.actingAs', 'Acting as your own sub-agent') }}
        <code>{{ String(session.agent_did || '').split(':').pop() }}</code>
        <span v-if="session.float && session.funded"> · {{ session.float }} {{ session.currency }}</span>
      </p>
    </div>

    <div class="oc-panes">
      <!-- ── the thread ─────────────────────────────────────────────────── -->
      <div class="oc-chat">
        <div ref="threadEl" class="oc-thread" data-testid="showcase-feed">
          <!-- The onboarding, in the chat. His ruling: this is part of the
               demonstration, not plumbing to hide. -->
          <div v-if="onboardSteps.length" class="oc-ob" data-testid="showcase-onboard-steps">
            <div v-for="st in onboardSteps" :key="st.key" :class="['oc-ob-row', { 'oc-ob-bad': !st.ok }]">
              <Icon :name="st.ok ? 'mdi:check-circle-outline' : 'mdi:alert-circle-outline'" class="oc-ob-ic" />
              <div class="oc-ob-txt">
                <div class="oc-ob-label">{{ st.label }}</div>
                <div class="oc-ob-detail">{{ st.detail }}</div>
              </div>
            </div>
          </div>

          <div v-if="!session && !sessionError && !onboarding" class="oc-ob-cta" data-testid="showcase-onboard-cta">
            <button class="oc-ob-btn" @click="ensureAgent">
              <Icon name="mdi:account-plus" />
              {{ t('showcaseChat.onboardBtn', 'Onboard an agent for the showcase') }}
            </button>
            <span class="oc-ob-hint">{{ t('showcaseChat.onboardHint', 'Creates a real agent on this registry — scoped, funded from the showcase agent, and yours alone for this session. Clicking into the box below does the same thing.') }}</span>
          </div>

          <p v-if="!messages.length && !sessionError && !onboardSteps.length" class="oc-empty">
            {{ t('showcaseChat.empty2', 'Try /help, then /call what is the weather in Berlin, then /pay 1 — and watch the ledger.') }}
          </p>
          <template v-for="{ m, nt, key } in stream" :key="key">
          <div v-if="m" :class="['oc-msg', { 'oc-msg-mine': m.mine }]">
            <div class="oc-msg-who">{{ m.mine ? t('showcaseChat.you2', 'you') : m.sender }}</div>
            <!-- /me is an action, and reads as one. It used to render as plain
                 text with the slash still on it. -->
            <div v-if="m.kind === 'text' && String(m.body || '').startsWith('/me ')"
                 class="oc-me" data-testid="showcase-me">{{ String(m.body).slice(4) }}</div>
            <div v-else-if="m.kind === 'text'" class="oc-bubble">{{ m.body }}</div>
            <div v-else-if="m.card" class="oc-card" @click="m.expanded = !m.expanded">
              <div class="oc-card-head">
                <span class="oc-card-type">{{ cardLine(m.card).label }}</span>
                <Icon name="mdi:chevron-down" :class="['oc-chev', { 'oc-chev-open': !!m.expanded }]" />
              </div>
              <div v-if="cardLine(m.card).head" class="oc-card-body">{{ cardLine(m.card).head }}</div>
              <div v-if="cardLine(m.card).sub" class="oc-card-sub">{{ cardLine(m.card).sub }}</div>
              <pre v-if="m.expanded" class="oc-payload">{{ JSON.stringify(m.card, null, 2) }}</pre>
              <!-- §CHATPOLISH 2026-08-26, his report: "it will buy 1 and then ask me to
                   buy 1 more with a + … i think this is wrong". It was: an unlabelled
                   ±, and a button that said "Buy 1", so the size read as something you
                   corrected AFTER the fact rather than chose before. Now the quantity is
                   named, and the button carries what it will actually cost — one
                   deliberate purchase of the size on screen, never a repeated Buy-1. -->
              <div v-if="(m.card as any)?.type === 'exchange.listing'" class="oc-buyrow" @click.stop>
                <span class="oc-qtylabel">{{ t('showcaseChat.qty', 'Quantity') }}</span>
                <div class="oc-qtybox">
                  <button class="oc-qty" :disabled="busy || qtyFor(m) <= 1"
                          :aria-label="t('showcaseChat.less', 'fewer')"
                          @click="buyQty[m.id] = Math.max(1, qtyFor(m) - 1)">−</button>
                  <input class="oc-qtyv" type="number" min="1" inputmode="numeric"
                         data-testid="showcase-qty"
                         :aria-label="t('showcaseChat.qty', 'Quantity')"
                         :value="qtyFor(m)" :disabled="busy"
                         @input="buyQty[m.id] = Math.max(1, Math.floor(Number(($event.target as HTMLInputElement).value) || 1))" />
                  <button class="oc-qty" :disabled="busy"
                          :aria-label="t('showcaseChat.more', 'more')"
                          @click="buyQty[m.id] = qtyFor(m) + 1">+</button>
                </div>
                <button class="oc-buy" data-testid="showcase-buy" :disabled="busy"
                        @click="buyShare(m.card, qtyFor(m))">
                  {{ buyLabel(m) }}
                </button>
              </div>
            </div>
            <!-- A ping is a knock, not the word "system". The fallback used to
                 print `m.kind` verbatim, so /ping rendered as literally
                 "system" — measured in a browser, not inferred. -->
            <div v-else-if="m.kind === 'system' && m.body === 'ping'" class="oc-ping" data-testid="showcase-ping">
              <Icon name="mdi:bell-ring" /> {{ t('showcaseChat.pinged', 'knocked') }}
            </div>
            <div v-else-if="m.kind === 'system'" class="oc-bubble oc-bubble-dim">{{ m.body || m.kind }}</div>
            <div v-else class="oc-bubble oc-bubble-dim">{{ m.kind }}</div>
          </div>

          <!-- A local read (/find, /audit, /ledger, /here, /work, /stocks) renders
               WHERE IT HAPPENED, in the same stream as the messages. It used to
               live in its own loop after the thread, so running /stocks and then
               buying something put the /stocks answer under the certificate. -->
          <div v-else-if="nt" class="oc-note" data-testid="showcase-note">
            <div class="oc-note-title">{{ nt.title }}</div>
            <div v-if="nt.stats" class="oc-mini" data-testid="showcase-mini">
              <div v-for="st in nt.stats" :key="st.k" class="oc-mini-cell">
                <div class="oc-mini-v">{{ st.v }}</div>
                <div class="oc-mini-k">{{ st.k }}</div>
              </div>
            </div>
            <div v-for="(ln, i) in nt.lines" :key="i" class="oc-note-line">{{ ln }}</div>
            <div class="oc-note-foot">{{ nt.foot }}</div>
          </div>
          </template>
        </div>

        <div v-if="helpOpen" class="oc-help" data-testid="showcase-helpsheet">
          <button class="oc-help-x" :aria-label="t('cta.close', 'Close')" @click="helpOpen = false">
            <Icon name="mdi:close" />
          </button>
          <div v-for="g in groups" :key="g.group" class="oc-help-g">
            <div class="oc-help-g-title">{{ g.group }}</div>
            <div class="oc-help-cmds">
              <button v-for="c in g.items" :key="c.cmd" type="button"
                      :class="['oc-cmd', { 'oc-cmd-off': !!c.unavailable }]"
                      @mouseenter="hoverCmd = c" @focus="hoverCmd = c"
                      @mouseleave="hoverCmd = null" @blur="hoverCmd = null"
                      @click="!c.unavailable && (draft = c.cmd + ' ')"
                      :title="c.unavailable ? String(c.unavailable) : `${c.usage} — ${t(c.glossKey, c.glossFallback)}`">{{ c.cmd }}</button>
            </div>
          </div>
          <div class="oc-help-explain" data-testid="showcase-help-explain">
            <template v-if="hoverCmd">
              <code class="oc-help-usage">{{ hoverCmd.usage }}</code>
              <span class="oc-help-gloss">{{ t(hoverCmd.glossKey, hoverCmd.glossFallback) }}</span>
              <span v-if="hoverCmd.unavailable" class="oc-help-off">
                {{ t('showcaseChat.notHere', 'Not available here:') }} {{ hoverCmd.unavailable }}
              </span>
            </template>
            <span v-else class="oc-help-gloss">
              {{ t('showcaseChat.hoverHint', 'Hover a command to see what it does. Nothing fires on its own — a command fills a door and you confirm.') }}
            </span>
          </div>
        </div>

        <div v-if="refusal" class="oc-refusal" data-testid="showcase-refusal">
          <Icon name="mdi:alert-circle-outline" /><span>{{ refusal }}</span>
        </div>
        <div v-if="notice" class="oc-notice" data-testid="showcase-notice">{{ notice }}</div>
        <div v-if="certWait" class="oc-notice oc-notice-wait" data-testid="showcase-certwait">{{ certWait }}</div>
        <div v-if="sessionError" class="oc-refusal" data-testid="showcase-nosession">
          <Icon name="mdi:alert-circle-outline" /><span>{{ sessionError }}</span>
        </div>

        <div v-if="suggestions.length" class="oc-sugg">
          <span v-for="sg in suggestions" :key="sg.cmd" class="oc-sugg-i" @click="draft = sg.cmd + ' '">{{ sg.cmd }}</span>
        </div>

        <div class="oc-composer">
          <input v-model="draft" class="oc-input" data-testid="showcase-input"
                 :placeholder="t('showcaseChat.ph2', 'Try /help · /call weather in Berlin · /agora')"
                 :disabled="busy" @focus="ensureAgent" @keydown.enter.prevent="send" />
          <button class="oc-send" data-testid="showcase-send" :disabled="busy || !draft.trim()" @click="send">
            <Icon :name="busy ? 'mdi:refresh' : 'mdi:send'" :class="{ 'oc-spin': busy }" />
          </button>
        </div>
      </div>

      <!-- ── the ledger: the same events, seen from the outside ──────────── -->
      <div class="oc-ledger">
        <div class="oc-ledger-head">
          <span class="oc-ledger-title">{{ t('showcaseChat.ledger', 'The ledger, live') }}</span>
          <span class="oc-ledger-sub">{{ t('showcaseChat.ledgerSub', 'every payment above, seen from the outside') }}</span>
        </div>
        <!-- §FEFRAME W2: the app's ONE ledger stream (every frame of the manifest), opened on MINE = the visitor's
             agent; EventLedgerLive opened three raw A/B/C sockets of the retired frames of its own. -->
        <BridgeLedger :mine-dids="ledgerDids" :mine-available="true" :can-open-forensics="false" />
        <p class="oc-ledger-foot">
          {{ session
             ? t('showcaseChat.ledgerFootMine', 'Filtered to your agent alone. Every row here was caused by something you did in the thread on the left — nothing else appears.')
             : t('showcaseChat.ledgerFootIdle', 'Filtered to your agent. Onboard one and this fills with the events your own actions cause.') }}
        </p>
      </div>
    </div>

    <!-- ── what this is, condensed ───────────────────────────────────────── -->
    <div v-if="infoOpen" class="oc-modal-wrap" data-testid="showcase-info-modal"
         @click.self="infoOpen = false">
      <div class="oc-modal" role="dialog" aria-modal="true">
        <div class="oc-modal-head">
          <h3 class="oc-modal-title">{{ t('showcaseChat.infoTitle', 'What you are looking at') }}</h3>
          <button class="oc-modal-x" :aria-label="t('cta.close', 'Close')" @click="infoOpen = false">
            <Icon name="mdi:close" />
          </button>
        </div>
        <div class="oc-modal-body">
          <p>{{ t('showcaseChat.info1', 'This is a real conversation on a real registry, with no account. The thread, the typed cards, the slash commands and the payments are the same ones the product uses — reached anonymously so you can try them.') }}</p>

          <h4>{{ t('showcaseChat.infoH2', 'A sub-agent was spawned for you') }}</h4>
          <p>{{ t('showcaseChat.info2', 'When you interacted, this registry spawned a capability-scoped SUB-AGENT under its showcase agent — the same L4 birth rail any agent uses to delegate a bounded piece of itself. It is not a fresh account: its authority can never exceed its parent\'s, it is re-derived on every request, and revoking the parent revokes it instantly. You can see it happen in the ledger as AgentSpawned.') }}</p>
          <p>{{ t('showcaseChat.info2b', 'It then got its own spend policy and a small float from that same showcase agent — never from the treasury, and nothing minted. It is yours alone for this session; a scheduled sweep returns what is left and retires it.') }}</p>

          <h4>{{ t('showcaseChat.infoH3', 'What is real, and what it cannot do') }}</h4>
          <p>{{ t('showcaseChat.info3b', 'Payments move real balance and appear on the public ledger beside this chat, which is filtered to your agent alone. That agent may pay only the showcase service agents, may trade on the AGORA markets, is capped per payment, per day and per hour, and cannot delegate or pay any other address. The containment is a policy on the registry, not a secret token.') }}</p>

          <h4>{{ t('showcaseChat.infoH6', 'Buying a point leaves a signed certificate') }}</h4>
          <p>{{ t('showcaseChat.info6', 'A listing you buy here is bought on a real market, and the certificate you get back is signed by the registry that keeps that market\'s register: not by the one you are typing into. Buy something listed elsewhere in the federation and the order is relayed there, fills there, and the certificate comes back carrying THAT market\'s signature. It attests a holding at a moment, so buying more supersedes the previous one.') }}</p>

          <h4>{{ t('showcaseChat.infoH7', 'A call that fails costs nothing') }}</h4>
          <p>{{ t('showcaseChat.info7', 'Paying an agent is authorized first and settled only if it delivers. If the agent answers that it could not do the work, the authorization is released and you are not charged — the reply says so in those words. Each agent also publishes how to phrase a call: type /call followed by its name to see its own examples.') }}</p>

          <h4>{{ t('showcaseChat.infoH35', 'There is no AI in this') }}</h4>
          <p>{{ t('showcaseChat.info35', 'This is a demonstration of protocol infrastructure, not an assistant. Every reply you see is produced by deterministic code: a parser with a fixed set of commands, registry endpoints, and priced service agents that return structured results. No language model is involved at any point — not in the chat, not in the commands, not in the answers the service agents give. The same input produces the same output.') }}</p>

          <h4>{{ t('showcaseChat.infoH4', 'Nothing fires on its own') }}</h4>
          <p>{{ t('showcaseChat.info4b', 'A slash command fills a door and stops. You confirm. An amount without a currency is refused by name rather than guessed, and naming an agent without asking it anything shows you what it expects instead of buying nonsense. Type /help to see the whole closed set, and hover any command to read what it does.') }}</p>

          <h4>{{ t('showcaseChat.infoH8', 'This registry is one of sixteen') }}</h4>
          <p>{{ t('showcaseChat.info8', 'The same chat runs on every registry in this federation, and each one spawns your sub-agent locally, under its OWN showcase agent, in its OWN currency. That is why the identity you are given here belongs to this registry and not to a central account: a registry is sovereign over the agents it homes. Buying or calling across the federation works because the registries trust each other\'s signatures, not because they share a database — the price is converted at the live rate, the order is placed where the asset lives, and the receipt is signed by whoever holds that register.') }}</p>
          <p>{{ t('showcaseChat.info8b', 'What does NOT travel today is your identity. Your sub-agent is homed here; to act on another registry you would hold an agent there too. Making one verified identity reachable across every federated registry is an open design question, not a shipped feature — and this page is careful not to imply otherwise.') }}</p>

          <h4>{{ t('showcaseChat.infoH5', 'One shape, not the shape') }}</h4>
          <p>{{ t('showcaseChat.info5', 'This is an example of what these rails allow, not the only way to build on them. An operator can scope, fund and expire agents however their product needs. What is worth copying is the order: create the identity, bound it, fund it from something that already holds value, and say all three out loud.') }}</p>

          <a class="oc-modal-link" href="/ui#/docs/34" target="_blank" rel="noopener">
            <Icon name="mdi:book-open-variant" />
            {{ t('showcaseChat.infoDocs', 'Read the full OurChat documentation') }}
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.oc { border: 1px solid var(--nc-border, rgba(255,255,255,.10)); border-radius: 14px;
      background: rgba(0,0,0,.24); padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.oc-title-row { display: flex; align-items: center; gap: 9px; }
.oc-title-icon { width: 20px; height: 20px; color: var(--nc-primary, #4fd1c5); }
.oc-title { font-size: 18px; font-weight: 700; margin: 0; }
.oc-help-btn { margin-left: auto; font-family: ui-monospace, monospace; font-size: 12px; cursor: pointer;
   background: none; color: var(--nc-primary, #4fd1c5); border: 1px solid rgba(var(--nc-primary-rgb), .4);
   border-radius: 999px; padding: 3px 11px; min-height: 28px; }
.oc-lede { font-size: 13px; line-height: 1.6; color: var(--nc-text-dim, #8b98a8); margin: 6px 0 0; max-width: 72ch; }
.oc-info-btn { width: 28px; height: 28px; border-radius: 999px; cursor: pointer;
   font-family: Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 700; font-size: 14px;
   background: none; color: var(--nc-text-dim, #8b98a8);
   border: 1px solid var(--nc-border, rgba(255,255,255,.18)); }
.oc-info-btn:hover { color: var(--nc-primary, #4fd1c5); border-color: rgba(var(--nc-primary-rgb), .5); }

/* /help keeps its buttons; the strip below is where the explanation lives. */
.oc-help-explain { margin-top: 10px; padding-top: 9px; min-height: 34px;
   border-top: 1px solid var(--nc-border, rgba(255,255,255,.08));
   display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.oc-help-usage { font-family: ui-monospace, monospace; font-size: 11.5px;
   color: var(--nc-primary, #4fd1c5); }
.oc-help-gloss { font-size: 11.5px; line-height: 1.5; color: var(--nc-text-dim, #8b98a8); }
.oc-help-off { font-size: 11.5px; color: #f6ad55; }

.oc-modal-wrap { position: fixed; inset: 0; z-index: 12000; display: flex;
   align-items: center; justify-content: center; padding: 20px;
   background: rgba(0,0,0,.72); }
.oc-modal { width: min(680px, 100%); max-height: 84vh; overflow-y: auto;
   background: var(--nc-surface, #0f1620); border: 1px solid var(--nc-border, rgba(255,255,255,.14));
   border-radius: 14px; padding: 20px 22px 22px; }
.oc-modal-head { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.oc-modal-title { font-size: 17px; font-weight: 700; margin: 0; }
.oc-modal-x { margin-left: auto; width: 34px; height: 34px; border-radius: 8px; cursor: pointer;
   background: none; border: 1px solid var(--nc-border, rgba(255,255,255,.14));
   color: var(--nc-text-dim, #8b98a8); display: flex; align-items: center; justify-content: center; }
.oc-modal-body p { font-size: 13px; line-height: 1.65; color: var(--nc-text-dim, #8b98a8);
   margin: 6px 0 0; max-width: 70ch; }
.oc-modal-body h4 { font-size: 12.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
   color: var(--nc-text, #e6edf3); margin: 16px 0 0; }
.oc-modal-link { display: inline-flex; align-items: center; gap: 8px; margin-top: 18px;
   min-height: 44px; padding: 0 15px; border-radius: 10px; font-size: 13px; font-weight: 600;
   text-decoration: none; color: var(--nc-primary, #4fd1c5);
   background: rgba(var(--nc-primary-rgb), .10); border: 1px solid rgba(var(--nc-primary-rgb), .42); }
.oc-modal-link:hover { background: rgba(var(--nc-primary-rgb), .18); }

/* §SHOWCASEVISITOR — the onboarding, rendered as system rows in the thread. */
.oc-ob { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px;
   border-left: 2px solid rgba(var(--nc-primary-rgb), .45); padding: 2px 0 2px 11px; }
.oc-ob-row { display: flex; gap: 9px; align-items: flex-start; }
.oc-ob-ic { width: 15px; height: 15px; flex: 0 0 auto; margin-top: 2px; color: var(--nc-primary, #4fd1c5); }
.oc-ob-bad .oc-ob-ic { color: #f6ad55; }
.oc-ob-txt { min-width: 0; }
.oc-ob-label { font-size: 12.5px; font-weight: 600; color: var(--nc-text, #e6edf3); }
.oc-ob-detail { font-size: 11.5px; line-height: 1.55; color: var(--nc-text-dim, #8b98a8);
   word-break: break-word; }
.oc-ob-cta { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; padding: 6px 0 2px; }
.oc-ob-btn { display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
   min-height: 44px; padding: 0 16px; font-size: 13px; font-weight: 600;
   color: var(--nc-primary, #4fd1c5); background: rgba(var(--nc-primary-rgb), .10);
   border: 1px solid rgba(var(--nc-primary-rgb), .45); border-radius: 10px; }
.oc-ob-btn:hover { background: rgba(var(--nc-primary-rgb), .18); }
.oc-ob-hint { font-size: 11.5px; line-height: 1.55; color: var(--nc-text-dim, #8b98a8); max-width: 62ch; }
/* Local reads — they answer from public data and post nothing. */
.oc-note { border: 1px dashed var(--nc-border, rgba(255,255,255,.16)); border-radius: 10px;
   padding: 10px 12px; margin-bottom: 10px; background: rgba(255,255,255,.02); }
.oc-note-title { font-size: 11px; text-transform: uppercase; letter-spacing: .07em;
   color: var(--nc-primary, #4fd1c5); margin-bottom: 5px; }
.oc-note-line { font-size: 12.5px; line-height: 1.5; color: var(--nc-text, #e6edf3);
   word-break: break-word; font-variant-numeric: tabular-nums; }
.oc-note-foot { font-size: 11px; line-height: 1.5; color: var(--nc-text-dim, #8b98a8); margin-top: 6px; }
.oc-qtylabel { font-size: 11.5px; color: var(--nc-text-dim, #8b98a8); }
.oc-qtybox { display: inline-flex; align-items: center; gap: 2px; border-radius: 8px;
   border: 1px solid var(--nc-border, rgba(255,255,255,.14)); background: rgba(255,255,255,.03); }
.oc-qtyv { width: 46px; height: 30px; text-align: center; background: transparent; border: 0;
   color: var(--nc-text, #e6edf3); font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.oc-qtyv::-webkit-outer-spin-button, .oc-qtyv::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.oc-qtyv { -moz-appearance: textfield; }
.oc-buy { margin-top: 8px; min-height: 34px; padding: 0 12px; border-radius: 8px; cursor: pointer;
   font-size: 12px; font-weight: 600; color: var(--nc-primary, #4fd1c5);
   background: rgba(var(--nc-primary-rgb), .12); border: 1px solid rgba(var(--nc-primary-rgb), .45); }
.oc-buy:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), .2); }
.oc-buy:disabled { opacity: .5; cursor: not-allowed; }

/* Scannable facts instead of a paragraph of disclosure. */
.oc-purse { display: flex; align-items: center; gap: 6px; margin-top: 10px; padding: 6px 10px;
  border: 1px solid var(--nc-border, #223); border-radius: 8px; font-size: 12px;
  background: var(--nc-surface-2, rgba(255,255,255,.03)); }
.oc-purse-icon { width: 14px; height: 14px; opacity: .8; flex: none; }
.oc-purse-have { font-variant-numeric: tabular-nums; font-weight: 600; }
.oc-purse-spent { color: var(--nc-text-dim, #8b98a8); font-variant-numeric: tabular-nums; }
.oc-purse-cmd { margin-left: auto; font: inherit; font-size: 11px; cursor: pointer;
  background: none; border: 1px solid var(--nc-border, #223); border-radius: 6px;
  padding: 2px 7px; color: var(--nc-text-dim, #8b98a8); }
.oc-purse-cmd:hover { color: var(--nc-text, #dfe7ef); }
.oc-facts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }
.oc-fact { font-size: 11px; line-height: 1; padding: 5px 9px; border-radius: 999px;
   color: var(--nc-text-dim, #8b98a8); background: rgba(255,255,255,.04);
   border: 1px solid var(--nc-border, rgba(255,255,255,.10));
   display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.oc-fact svg { width: 12px; height: 12px; }
.oc-fact-key { color: var(--nc-primary, #4fd1c5);
   background: rgba(var(--nc-primary-rgb), .10); border-color: rgba(var(--nc-primary-rgb), .35); }
.oc-fact-det { color: var(--nc-text, #e6edf3); border-style: dashed; }
.oc-fact-more { cursor: pointer; font-family: inherit; text-decoration: underline;
   text-underline-offset: 2px; }
.oc-fact-more:hover { color: var(--nc-primary, #4fd1c5); border-color: rgba(var(--nc-primary-rgb), .4); }

.oc-shared { font-size: 11.5px; line-height: 1.5; color: var(--nc-text-dim, #8b98a8); margin: 6px 0 0;
   border-left: 2px solid rgba(var(--nc-primary-rgb), .4); padding-left: 9px; max-width: 72ch; }

.oc-panes { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, .9fr); gap: 16px; }
@media (max-width: 900px) { .oc-panes { grid-template-columns: minmax(0, 1fr); } }
/* The desktop module is deliberately tall (§CHATPOLISH: +36%, his ask). Stacked on a
   phone that would be two 790px columns of dead scroll, so clamp to the viewport there
   — the height is a desktop presentation choice, not a layout constant. */
@media (max-width: 900px) { .oc-thread { height: 62vh; min-height: 380px; } }

.oc-chat { display: flex; flex-direction: column; gap: 9px; min-width: 0; }
.oc-thread { height: 790px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px;
   border: 1px solid var(--nc-border, rgba(255,255,255,.08)); border-radius: 10px; padding: 12px;
   background: rgba(0,0,0,.18); }
.oc-empty { font-size: 13px; color: var(--nc-text-dim, #8b98a8); margin: 0; line-height: 1.6; }
.oc-msg { display: flex; flex-direction: column; gap: 3px; max-width: 92%; }
.oc-msg-mine { align-self: flex-end; align-items: flex-end; }
.oc-msg-who { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--nc-text-dim, #8b98a8); }
.oc-bubble { font-size: 13.5px; line-height: 1.5; border-radius: 10px; padding: 8px 11px;
   background: rgba(255,255,255,.04); border: 1px solid var(--nc-border, rgba(255,255,255,.07)); }
.oc-msg-mine .oc-bubble { background: rgba(var(--nc-primary-rgb), .12); border-color: rgba(var(--nc-primary-rgb), .3); }
.oc-bubble-dim { color: var(--nc-text-dim, #8b98a8); font-style: italic; }
.oc-card { border: 1px solid rgba(var(--nc-primary-rgb), .32); border-radius: 10px; padding: 9px 11px;
   background: rgba(var(--nc-primary-rgb), .06); cursor: pointer; }
.oc-card-head { display: flex; align-items: center; gap: 8px; }
.oc-card-type { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--nc-primary, #4fd1c5); }
.oc-chev { width: 14px; height: 14px; margin-left: auto; opacity: .6; transition: transform .16s ease; }
.oc-chev-open { transform: rotate(180deg); }
.oc-card-body { font-size: 13.5px; margin-top: 4px; font-weight: 600; }
.oc-card-sub { font-size: 12px; color: var(--nc-text-dim, #8b98a8); margin-top: 2px; }
.oc-payload { margin: 9px 0 0; font-size: 11px; line-height: 1.45; max-height: 220px; overflow: auto;
   background: rgba(0,0,0,.36); border-radius: 7px; padding: 9px; white-space: pre-wrap; word-break: break-word; }

.oc-help { position: relative; border: 1px solid var(--nc-border, rgba(255,255,255,.10)); border-radius: 10px;
   padding: 10px 34px 10px 12px; display: flex; flex-direction: column; gap: 8px; background: rgba(0,0,0,.2);
   /* Capped and scrollable: it used to grow to 24 commands tall and eat the thread. */
   max-height: 210px; overflow-y: auto; }
.oc-help-x { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; border-radius: 6px;
   cursor: pointer; background: none; color: var(--nc-text-dim, #8b98a8);
   border: 1px solid var(--nc-border, rgba(255,255,255,.14)); display: flex; align-items: center; justify-content: center; }
.oc-help-x:hover { color: var(--nc-primary, #4fd1c5); }
.oc-ping { display: inline-flex; align-items: center; gap: 6px; align-self: flex-start;
   font-size: 12px; color: var(--nc-text-dim, #8b98a8); padding: 4px 10px; border-radius: 999px;
   background: rgba(255,255,255,.04); border: 1px dashed var(--nc-border, rgba(255,255,255,.16)); }
.oc-ping svg { width: 13px; height: 13px; }
.oc-me { font-style: italic; font-size: 12.5px; line-height: 1.55; color: var(--nc-text-dim, #8b98a8);
   padding: 2px 0; }
.oc-buyrow { display: flex; align-items: center; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.oc-qty { width: 30px; height: 30px; border-radius: 7px; cursor: pointer; font-size: 15px; line-height: 1;
   color: var(--nc-text, #e6edf3); background: transparent; border: 0; }
.oc-qty:hover:not(:disabled) { background: rgba(255,255,255,.07); }
.oc-qty:disabled { opacity: .4; cursor: not-allowed; }
.oc-help-g-title { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--nc-text-dim, #8b98a8); }
.oc-help-cmds { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.oc-cmd { font-family: ui-monospace, monospace; font-size: 11.5px; border-radius: 6px; padding: 2px 7px;
   background: rgba(var(--nc-primary-rgb), .10); border: 1px solid rgba(var(--nc-primary-rgb), .26); }
.oc-cmd { cursor: pointer; position: relative; font: inherit; font-family: ui-monospace, monospace;
   color: inherit; -webkit-appearance: none; appearance: none; }
.oc-cmd::before { content: ''; position: absolute; inset: -8px -4px; }
.oc-cmd:hover:not(.oc-cmd-off), .oc-cmd:focus-visible:not(.oc-cmd-off) {
   border-color: rgba(var(--nc-primary-rgb), .55); color: var(--nc-primary, #4fd1c5); }
.oc-cmd-off { cursor: default; }
.oc-cmd-off { opacity: .42; background: rgba(255,255,255,.03); border-color: var(--nc-border, rgba(255,255,255,.10)); }

.oc-refusal { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #f6ad55;
   background: rgba(246,173,85,.08); border: 1px solid rgba(246,173,85,.26); border-radius: 8px; padding: 8px 11px; }
.oc-notice-wait { color: #90cdf4; background: rgba(144,205,244,.08); }
.oc-mini { display: grid; grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
           gap: 6px; margin: 8px 0 4px; }
.oc-mini-cell { background: rgba(255,255,255,.035); border: 1px solid rgba(255,255,255,.07);
                border-radius: 7px; padding: 7px 9px; }
.oc-mini-v { font-size: 13px; font-weight: 600; color: #e2e8f0; font-variant-numeric: tabular-nums; }
.oc-mini-k { font-size: 10.5px; color: #8fa0b4; text-transform: uppercase; letter-spacing: .04em; margin-top: 2px; }
.oc-notice { font-size: 12.5px; color: #68d391; background: rgba(104,211,145,.08);
   border: 1px solid rgba(104,211,145,.24); border-radius: 8px; padding: 8px 11px; }

.oc-sugg { display: flex; gap: 6px; flex-wrap: wrap; }
.oc-sugg-i { font-family: ui-monospace, monospace; font-size: 11.5px; cursor: pointer; border-radius: 6px;
   padding: 2px 8px; background: rgba(255,255,255,.05); border: 1px solid var(--nc-border, rgba(255,255,255,.12)); }

.oc-composer { display: flex; gap: 8px; }
.oc-input { flex: 1 1 auto; min-width: 0; background: var(--nc-surface-2, #111823); color: var(--nc-text, #e6edf3);
   border: 1px solid var(--nc-border, rgba(255,255,255,.14)); border-radius: 9px; padding: 11px; font-size: 14px; }
.oc-send { min-width: 52px; min-height: 44px; border-radius: 9px; cursor: pointer;
   background: rgba(var(--nc-primary-rgb), .16); color: var(--nc-primary, #4fd1c5);
   border: 1px solid rgba(var(--nc-primary-rgb), .4); display: inline-flex; align-items: center; justify-content: center; }
.oc-send:disabled { opacity: .5; cursor: not-allowed; }
.oc-spin { animation: oc-rot 1s linear infinite; }
@keyframes oc-rot { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .oc-spin { animation: none; } }

.oc-ledger { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.oc-ledger-head { display: flex; flex-direction: column; gap: 2px; }
.oc-ledger-title { font-size: 13px; font-weight: 600; }
.oc-ledger-sub { font-size: 11.5px; color: var(--nc-text-dim, #8b98a8); }
.oc-ledger-foot { font-size: 11px; line-height: 1.5; color: var(--nc-text-dim, #8b98a8); margin: 0; }
</style>
