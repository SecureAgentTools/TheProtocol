/**
 * §OURSTATE-1 — the ONE card brain (pure, unit-tested like guildActions).
 *
 * A chat message of kind 'card' carries a versioned envelope
 * `{v:1, type, data, refs}` validated SERVER-side against a closed vocabulary
 * (services/chat_service.py). This module is the client half of the same law:
 * it maps an envelope onto a typed view descriptor the ONE renderer
 * (OurStateCard.vue) consumes. Unknown types render as an honest
 * "unsupported card" row — never markup, never silence.
 *
 * DEFANGING (§6 of the strategy): inside a REQUEST-state thread every card
 * renders with its doors suppressed — a stranger's invoice must not be
 * tappable before you accepted the stranger. The flag comes from the caller
 * (`ctx.defang`); this brain zeroes the action, so a renderer cannot forget.
 *
 * No i18n in here (pure module, node-testable): the renderer translates; this
 * file returns semantic fields only.
 */

export interface ChatCard {
  v: number
  type: string
  data: Record<string, any>
  refs?: Record<string, any> | null
}

export interface CardCtx {
  /** True while the viewer's side of the thread is a pending request. */
  defang?: boolean
}

export type CardView =
  | { type: 'pay.request'; amount: string; currency: string; memo: string; defanged: boolean }
  | {
      type: 'pay.receipt'; amount: string; currency: string; method: string
      txId: string | null
      // §OURSTATE-6 — what ARRIVED, in the recipient's unit. A cross-frame
      // send debits one currency and credits another (measured: 102 BVT out,
      // 85.709085 AVT in), and a receipt that shows only the debit is telling
      // half the story to the half that cares most.
      receivedAmount: string | null; receivedCurrency: string | null
      converted: boolean
      defanged: boolean
    }
  | { type: 'service.call'; ask: string; status: string; targetDid: string | null }
  | {
      type: 'service.result'; ok: boolean; stage: string; summary: string
      paidAmount: string | null; paidCurrency: string | null
      settlementStatus: string | null; tokenId: string | null; settlementTxId: string | null
      resultText: string; truncated: boolean; error: string
      /** §OURSTATE-6 — the SUBSTANCE the agent returned, behind a tap. The card
       *  shows the one-line summary; this is what the summary is a summary OF.
       *  Plumbing (jsonrpc / task ids / artifact wrappers) is stripped, because
       *  a disclosure that reveals an envelope teaches nothing. */
      payload: Record<string, any> | null
    }
  // §CARDREAL — an agent card that is actually an agent card. This carried a
  // name and a DID and nothing else, so `/card <did>` produced a label where a
  // reader expected the thing they had just found in /find: what it costs, where
  // it answers, what it does. Every field below already exists on the agent's
  // own card_data; none of it is new data, it was simply dropped here.
  | { type: 'agent.card'; did: string; name: string; defanged: boolean
      description: string | null; price: string | null; currency: string | null
      paymentRequired: boolean | null; priceSource: string | null
      endpointHost: string | null; skills: string[]; registry: string | null }
  | {
      type: 'contract.offer' | 'guild.order'; ref: string; title: string
      amount: string | null; currency: string | null; status: string
      counterpartyDid: string | null; defanged: boolean
    }
  // §OURSTATE-5e — a POINTER. The view carries no bytes and no URL: the
  // download is an authenticated fetch by id, so a card can never be a link
  // to somewhere else.
  | {
      type: 'media'; attachmentId: string; name: string; mime: string
      bytes: number; human: string; defanged: boolean
    }
  // §OURSTATE-5f — a declarative form. `fields` is data, never markup, and
  // `action` names a door this app already has. Nothing here can fire.
  | {
      type: 'applet'; title: string
      fields: Array<{ kind: 'text' | 'number' | 'choice' | 'confirm'; key: string
                      label: string; choices: string[] }>
      action: { kind: string; label: string; amount: string | null
                currency: string | null; did: string | null }
      defanged: boolean
    }
  // §OURCHAT-ORG — a POINTER at a share listing on this registry's venue. The
  // symbol is the address; `lastPrice` is decoration the ticket re-reads before
  // anyone can act, and there is deliberately no side and no quantity, because
  // a card carrying those would be an order slip somebody else composed.
  | {
      type: 'exchange.listing'; symbol: string; displayName: string
      lastPrice: string | null; currency: string | null; venue: string
      defanged: boolean
    }
  // §SHOWCASESTOCKS — a signed attestation that a holding exists. RAIL-ONLY:
  // the registry mints and posts it, a client cannot author one, and that is
  // exactly what makes it worth reading. `digest` + `signature` are carried so
  // the reader can verify offline against the registry's published attestation
  // pubkey — the same shape §AGENTDISC's receipts drawer already verifies.
  | {
      type: 'share.certificate'; certificateId: string; symbol: string
      displayName: string; qty: number; currency: string
      avgCost: string | null; totalShares: number | null; venue: string
      asOf: string; digest: string; signature: string | null
      signatureAlg: string | null; pubkeyId: string | null
      unsignedReason: string | null
    }
  | { type: 'org.work.receipt'; kind: string; amount: string; currency: string
      memo?: string; counterparty?: string; ref?: string }
  // §DEALTHREADS (O-D) — the negotiation family. proposal/counter are
  // CLIENT-POSTABLE structured text (amounts are DECORATION the engage rail
  // re-reads; a counter names what it supersedes so the thread keeps the whole
  // history). The other four are RAIL-ONLY transitions of a real contract;
  // their doors act on the EXISTING contract rails with the actor's own token.
  | {
      type: 'engagement.proposal' | 'engagement.counter'
      title: string; total: string | null; currency: string | null
      note: string | null; milestones: Array<{ title: string; amount: string | null }>
      supersedes: string | null; defanged: boolean
    }
  | {
      type: 'engagement.offer'; contractId: string; title: string
      total: string; currency: string; providerDid: string
      providerHome: string | null; offerExpiresAt: string | null; defanged: boolean
    }
  | {
      type: 'engagement.accepted'; contractId: string; total: string
      currency: string; escrowRef: string | null
    }
  | { type: 'engagement.milestone'; contractId: string; seq: number; title: string }
  | {
      type: 'engagement.settled'; contractId: string; seq: number
      amount: string; currency: string; completed: boolean; providerHome: string | null
    }
  | { type: 'unknown'; rawType: string }

/** The applet's doors: the server's closed list (services/chat_applet.py ACTIONS), re-applied here. D6-553: open_trade
 *  (the AGORA order ticket for a symbol, which the Pocket thread opens) was accepted by the server and dropped here, so
 *  such an applet rendered without its button. cards.test.ts reads the server's list and holds the two equal. */
export const APPLET_ACTIONS: ReadonlySet<string> = new Set(['open_pay', 'open_buy', 'open_work', 'open_reply', 'open_trade'])

const KNOWN = new Set(['pay.request', 'pay.receipt', 'service.call', 'service.result',
                       'agent.card', 'contract.offer', 'guild.order',
                       'media', 'applet', 'exchange.listing', 'share.certificate', 'org.work.receipt',
                       'engagement.proposal', 'engagement.counter', 'engagement.offer',
                       'engagement.accepted', 'engagement.milestone', 'engagement.settled'])

/** Trim a decimal string for DISPLAY. The venue stores prices at eighteen
 *  places, so a listing card rendered `1.500000000000000000 BVT` — technically
 *  the number, practically unreadable, and unlike every other money card in
 *  the app. This strips INSIGNIFICANT trailing zeros only: it never rounds,
 *  never touches digits before the point, and returns the input unchanged if
 *  it is not a plain decimal. `1.500000` -> `1.5`, `20.00` -> `20`, `100` ->
 *  `100`, `0.000001` -> `0.000001`. */
export function trimDecimal(v: string): string {
  if (!/^-?\d+(\.\d+)?$/.test(v)) return v
  if (!v.includes('.')) return v
  const out = v.replace(/0+$/, '').replace(/\.$/, '')
  return out === '' || out === '-' ? v : out
}

/** A ledger amount, as a person should read it.
 *
 *  §CHATCOHERE (2026-09-01) — the confirm sheet rendered `You hold 0E-18 BVT.`
 *  Balances come back from the TEG in SCIENTIFIC NOTATION (`1E+3`, `0E-18`) — a
 *  documented shape of this API — and `trimDecimal` deliberately passes anything
 *  that is not a plain decimal straight through, so the exponent reached the
 *  screen. Found by reading a screenshot; twenty green assertions had passed
 *  over it, because every one of them only asked whether a NUMBER was present.
 *
 *  ⚠ The exponent branch goes through `Number`, which is lossy beyond ~15
 *  significant digits. That is safe HERE and nowhere else: the ledger only emits
 *  the exponent form for values that are exactly representable (a zero, or a
 *  round power of ten). A full-precision amount arrives as a plain decimal
 *  string and takes the first branch, untouched. */
export function displayAmount(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return ''
  const s = String(v).trim()
  if (/^-?\d+(\.\d+)?$/.test(s)) return trimDecimal(s)
  if (/^-?\d+(\.\d+)?[eE][+-]?\d+$/.test(s)) {
    const n = Number(s)
    if (!Number.isFinite(n) || Math.abs(n) >= 1e21) return s
    const plain = n.toFixed(18)
    return /^-?\d+(\.\d+)?$/.test(plain) ? trimDecimal(plain) : s
  }
  return s   // anything unexpected is shown VERBATIM rather than reshaped
}

/** Extract the human answer from an A2A artifact envelope (the showcase agents
 *  answer with `artifacts[].data.summary` — the §BUYSERVICE panel's rule). */
export function resultText(result: any): string {
  try {
    if (result && result.truncated && typeof result.preview === 'string') return result.preview
    // The buy rail returns the agent's JSON-RPC envelope verbatim: artifacts
    // usually sit at result.result.artifacts, sometimes hoisted one level up.
    const arts = result?.artifacts || result?.result?.artifacts || []
    for (const a of arts) {
      const s = a?.data?.summary
      if (typeof s === 'string' && s.trim()) return s
    }
    // Some runtimes answer with message parts instead of artifacts.
    const parts = result?.message?.parts || result?.parts
      || result?.result?.message?.parts || result?.result?.parts || []
    for (const p of parts) {
      const t = p?.text
      if (typeof t === 'string' && t.trim()) return t
    }
  } catch { /* fall through */ }
  return ''
}

/** The agent's own answer object, unwrapped from the A2A envelope.
 *
 *  `resultText` gives the one line a card shows. This gives what that line
 *  summarises — for Auditor Ash, the scope note, the terms note and the
 *  numbers. It deliberately returns the artifact's `data.data` when present
 *  (the showcase envelope nests the service's own object one level under the
 *  artifact's metadata), and never the JSON-RPC wrapper. */
export function resultPayload(result: any): Record<string, any> | null {
  try {
    if (result && result.truncated) return null      // we do not have it all
    const arts = result?.artifacts || result?.result?.artifacts || []
    for (const a of arts) {
      const d = a?.data
      if (d && typeof d === 'object') {
        const inner = (d as any).data
        const chosen = inner && typeof inner === 'object' && !Array.isArray(inner) ? inner : d
        return Object.keys(chosen).length ? chosen : null
      }
    }
  } catch { /* fall through */ }
  return null
}

export function cardView(card: ChatCard | null | undefined, ctx: CardCtx = {}): CardView {
  const t = card?.type
  if (!card || card.v !== 1 || typeof t !== 'string' || !KNOWN.has(t)) {
    return { type: 'unknown', rawType: String(t ?? 'card').slice(0, 40) }
  }
  const d = card.data || {}
  const refs = card.refs || {}
  const defanged = !!ctx.defang
  switch (t) {
    case 'pay.request':
      return {
        type: 'pay.request',
        amount: String(d.amount ?? ''), currency: String(d.currency ?? ''),
        memo: typeof d.memo === 'string' ? d.memo : '',
        defanged,
      }
    case 'pay.receipt': {
      const rAmt = d.received_amount != null ? String(d.received_amount) : null
      const rCcy = d.received_currency ? String(d.received_currency) : null
      return {
        type: 'pay.receipt',
        amount: String(d.amount ?? ''), currency: String(d.currency ?? ''),
        method: typeof d.method === 'string' ? d.method : '',
        txId: (refs.tx_id ?? d.tx_id ?? null) as string | null,
        // Both halves or neither: an arrival amount without its unit is the
        // §FOREIGNACT defect, so it is dropped rather than half-rendered.
        receivedAmount: rAmt && rCcy ? rAmt : null,
        receivedCurrency: rAmt && rCcy ? rCcy : null,
        converted: !!(rAmt && rCcy && rCcy.toUpperCase() !== String(d.currency ?? '').toUpperCase()),
        defanged,
      }
    }
    case 'service.call':
      return {
        type: 'service.call',
        ask: String(d.ask ?? ''), status: String(d.status ?? ''),
        targetDid: (refs.target_did ?? null) as string | null,
      }
    case 'service.result':
      return {
        type: 'service.result',
        ok: !!d.ok, stage: String(d.stage ?? ''),
        summary: String(d.summary ?? ''),
        paidAmount: d.paid_amount != null ? String(d.paid_amount) : null,
        paidCurrency: d.paid_currency != null ? String(d.paid_currency) : null,
        settlementStatus: d.settlement_status != null ? String(d.settlement_status) : null,
        tokenId: (refs.token_id ?? null) as string | null,
        settlementTxId: (refs.settlement_tx_id ?? null) as string | null,
        resultText: resultText(d.result),
        truncated: !!d.result_truncated,
        error: String(d.error ?? ''),
        payload: d.result_truncated ? null : resultPayload(d.result),
      }
    case 'agent.card':
      return {
        type: 'agent.card',
        did: String(d.did ?? ''), name: String(d.name ?? ''),
        defanged,
        description: d.description != null ? String(d.description) : null,
        price: d.price != null ? trimDecimal(String(d.price)) : null,
        currency: d.currency != null ? String(d.currency) : null,
        paymentRequired: typeof d.payment_required === 'boolean' ? d.payment_required : null,
        priceSource: d.price_source != null ? String(d.price_source) : null,
        endpointHost: d.endpoint_host != null ? String(d.endpoint_host) : null,
        skills: Array.isArray(d.skills) ? d.skills.map((x: any) => String(x)).slice(0, 6) : [],
        registry: d.registry != null ? String(d.registry) : null,
      }
    // §OURSTATE-2 WORK cards: POINTERS into the contracts / guild rails. The
    // card states what the engagement IS; the doors act on the real rail with
    // the actor's own token (guildActions decides which doors are offered).
    case 'contract.offer':
    case 'guild.order':
      return {
        type: t,
        ref: String(d.ref ?? ''), title: String(d.title ?? ''),
        amount: d.amount != null ? String(d.amount) : null,
        currency: d.currency != null ? String(d.currency) : null,
        status: String(d.status ?? ''),
        counterpartyDid: (refs.counterparty_did ?? d.counterparty_did ?? null) as string | null,
        defanged,
      }
    // §OURCHAT-ORG — the venue pointer. Everything here is a label except the
    // symbol; the door carries the symbol and nothing else.
    case 'exchange.listing':
      return {
        type: 'exchange.listing',
        symbol: String(d.symbol ?? '').toUpperCase(),
        displayName: String(d.display_name ?? ''),
        lastPrice: d.last_price != null ? trimDecimal(String(d.last_price)) : null,
        currency: d.currency != null ? String(d.currency) : null,
        venue: String(refs.venue ?? d.venue ?? ''),
        defanged,
      }
    case 'org.work.receipt': {
      // §CHATDESK C5 — rail-authored record of org money that already moved.
      return {
        type: 'org.work.receipt',
        kind: String(d.kind ?? ''), amount: String(d.amount ?? ''), currency: String(d.currency ?? ''),
        memo: typeof d.memo === 'string' ? d.memo : undefined,
        counterparty: typeof d.counterparty === 'string' ? d.counterparty : undefined,
        ref: typeof refs.ref === 'string' ? refs.ref : undefined,
      }
    }
    // §DEALTHREADS — negotiation halves. A stated total renders only WITH its
    // currency (§FOREIGNACT: drop the pair rather than half-render it).
    case 'engagement.proposal':
    case 'engagement.counter': {
      const hasTotal = d.total != null && d.currency
      return {
        type: t,
        title: String(d.title ?? ''),
        total: hasTotal ? trimDecimal(String(d.total)) : null,
        currency: hasTotal ? String(d.currency) : null,
        note: typeof d.note === 'string' ? d.note : null,
        milestones: Array.isArray(d.milestones)
          ? d.milestones.filter((m: any) => m && m.title).slice(0, 20).map((m: any) => ({
              title: String(m.title).slice(0, 200),
              amount: m.amount != null ? trimDecimal(String(m.amount)) : null,
            }))
          : [],
        supersedes: typeof refs.supersedes === 'string' ? refs.supersedes : null,
        defanged,
      }
    }
    case 'engagement.offer':
      return {
        type: 'engagement.offer',
        contractId: String(d.contract_id ?? ''),
        title: String(d.title ?? ''),
        total: trimDecimal(String(d.total ?? '')), currency: String(d.currency ?? ''),
        providerDid: String(d.provider_did ?? ''),
        providerHome: d.provider_home != null ? String(d.provider_home) : null,
        // silence is answered by the TTL, never by read receipts (law)
        offerExpiresAt: d.offer_expires_at != null ? String(d.offer_expires_at) : null,
        defanged,
      }
    case 'engagement.accepted':
      return {
        type: 'engagement.accepted',
        contractId: String(d.contract_id ?? ''),
        total: trimDecimal(String(d.total ?? '')), currency: String(d.currency ?? ''),
        escrowRef: d.escrow_ref != null ? String(d.escrow_ref) : null,
      }
    case 'engagement.milestone':
      return {
        type: 'engagement.milestone',
        contractId: String(d.contract_id ?? ''),
        seq: Number(d.seq ?? 0), title: String(d.title ?? ''),
      }
    case 'engagement.settled':
      return {
        type: 'engagement.settled',
        contractId: String(d.contract_id ?? ''),
        seq: Number(d.seq ?? 0),
        amount: trimDecimal(String(d.amount ?? '')), currency: String(d.currency ?? ''),
        completed: !!d.completed,
        providerHome: d.provider_home != null ? String(d.provider_home) : null,
      }
    case 'share.certificate':
      return {
        type: 'share.certificate',
        certificateId: String(d.certificate_id ?? ''),
        symbol: String(d.symbol ?? '').toUpperCase(),
        displayName: String(d.display_name ?? ''),
        qty: Number(d.qty ?? 0),
        currency: String(d.currency ?? ''),
        avgCost: d.avg_cost != null ? trimDecimal(String(d.avg_cost)) : null,
        totalShares: d.total_shares != null ? Number(d.total_shares) : null,
        venue: String(d.venue_registry ?? ''),
        asOf: String(d.as_of ?? ''),
        digest: String(d.digest ?? ''),
        // An UNSIGNED certificate must render as unsigned, never quietly as a
        // signed one — the value of the artifact is the signature.
        signature: d.signature != null ? String(d.signature) : null,
        signatureAlg: d.signature_alg != null ? String(d.signature_alg) : null,
        pubkeyId: d.signature_pubkey_id != null ? String(d.signature_pubkey_id) : null,
        unsignedReason: d.unsigned_reason != null ? String(d.unsigned_reason) : null,
      }
    case 'media': {
      const bytes = Number(d.bytes ?? 0)
      return {
        type: 'media',
        attachmentId: String(d.attachment_id ?? ''),
        name: String(d.name ?? 'file'),
        mime: String(d.mime ?? ''),
        bytes,
        human: humanBytes(bytes),
        defanged,
      }
    }

    case 'applet': {
      // The renderer re-applies the closed vocabulary rather than trusting the
      // server's copy of it: two gates that must agree, and an unknown kind
      // renders NOTHING instead of falling back to something permissive.
      const KINDS = new Set(['text', 'number', 'choice', 'confirm'])
      const raw = Array.isArray(d.fields) ? d.fields : []
      const fields = raw
        .filter((f: any) => f && KINDS.has(String(f.kind)) && f.key && f.label)
        .slice(0, 8)
        .map((f: any) => ({
          kind: String(f.kind) as any,
          key: String(f.key),
          label: String(f.label).slice(0, 80),
          choices: Array.isArray(f.choices)
            ? f.choices.filter((c: any) => typeof c === 'string').slice(0, 12) : [],
        }))
      const a = d.action || {}
      const kind = APPLET_ACTIONS.has(String(a.kind)) ? String(a.kind) : ''
      return {
        type: 'applet',
        title: String(d.title ?? '').slice(0, 120),
        fields,
        action: {
          kind,
          label: String(a.label ?? '').slice(0, 80),
          // An amount without a currency is not an amount here — the whole
          // pair is dropped rather than rendering half of it.
          amount: (a.amount != null && a.currency) ? String(a.amount) : null,
          currency: (a.amount != null && a.currency) ? String(a.currency) : null,
          did: a.did ? String(a.did) : null,
        },
        defanged,
      }
    }
  }
  return { type: 'unknown', rawType: t }
}

/** Bytes a person can read. Pure — the card view carries the string so the
 *  template never does arithmetic. */
export function humanBytes(n: number): string {
  const b = Number(n) || 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(b < 10240 ? 1 : 0)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

/** Build a valid client-postable pay.request envelope (the composer's door). */
export function buildPayRequest(amount: string, currency: string, memo?: string): ChatCard {
  const data: Record<string, any> = { amount, currency }
  if (memo && memo.trim()) data.memo = memo.trim().slice(0, 240)
  return { v: 1, type: 'pay.request', data }
}

/** Build a WORK pointer card (§OURSTATE-2). It points at an engagement that
 *  ALREADY exists on the contracts / guild rails — posting one is pointing,
 *  never creating: no rail is touched here and no authority is conveyed. */
/** §OURSTATE-6 — the receipt a completed send posts into the thread.
 *  Built from what the send door actually observed, including the arrival
 *  amount, so the thread carries the payment rather than only remembering it. */
export function buildPayReceipt(r: {
  ref?: string; method?: string; amount?: string; currency?: string
  receivedAmount?: string | null; receivedCurrency?: string | null
}): ChatCard {
  const data: Record<string, any> = {
    amount: String(r.amount ?? ''), currency: String(r.currency ?? ''),
    method: String(r.method ?? 'local'),
  }
  if (r.receivedAmount != null && r.receivedCurrency) {
    data.received_amount = String(r.receivedAmount)
    data.received_currency = String(r.receivedCurrency)
  }
  const card: ChatCard = { v: 1, type: 'pay.receipt', data }
  if (r.ref) card.refs = { tx_id: r.ref }
  return card
}

export function buildWorkCard(
  kind: 'contract.offer' | 'guild.order',
  ref: string,
  title: string,
  opts: { amount?: string | null; currency?: string | null; status?: string; counterpartyDid?: string | null } = {},
): ChatCard {
  const data: Record<string, any> = { ref: String(ref).slice(0, 128), title: String(title).slice(0, 200) }
  if (opts.amount != null && opts.currency) { data.amount = String(opts.amount); data.currency = opts.currency }
  if (opts.status) data.status = String(opts.status).slice(0, 40)
  const card: ChatCard = { v: 1, type: kind, data }
  if (opts.counterpartyDid) card.refs = { counterparty_did: opts.counterpartyDid }
  return card
}

/** Build an agent.card envelope (sharing an agent into a thread). */
export function buildAgentCard(did: string, name?: string): ChatCard {
  const data: Record<string, any> = { did }
  if (name) data.name = name.slice(0, 120)
  return { v: 1, type: 'agent.card', data }
}

/** §DEALTHREADS — build a proposal (or, with `supersedes`, a counter).
 *  Structured NEGOTIATION text: nothing here is trusted by any rail; a stated
 *  total travels with its currency or not at all. */
export function buildEngagementProposal(p: {
  title: string; total?: string | null; currency?: string | null
  note?: string | null; milestones?: Array<{ title: string; amount?: string | null }>
  supersedes?: string | null
}): ChatCard {
  const data: Record<string, any> = { title: String(p.title).slice(0, 200) }
  if (p.total != null && String(p.total).trim() !== '' && p.currency) {
    data.total = String(p.total)
    data.currency = String(p.currency)
  }
  if (p.note && p.note.trim()) data.note = p.note.trim().slice(0, 2000)
  if (p.milestones && p.milestones.length) {
    data.milestones = p.milestones.slice(0, 20).map(m => {
      const out: Record<string, any> = { title: String(m.title).slice(0, 200) }
      if (m.amount != null && String(m.amount).trim() !== '') out.amount = String(m.amount)
      return out
    })
  }
  const card: ChatCard = {
    v: 1,
    type: p.supersedes ? 'engagement.counter' : 'engagement.proposal',
    data,
  }
  if (p.supersedes) card.refs = { supersedes: String(p.supersedes) }
  return card
}
