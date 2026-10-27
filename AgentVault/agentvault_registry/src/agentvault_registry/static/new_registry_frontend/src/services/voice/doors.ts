/**
 * services/voice/doors.ts — §POCKETBRIDGE3 WS-B: intent → the ONE existing
 * door. Pure mapping; nothing here executes anything — every money surface a
 * door opens still ends at the app's own confirm (biometric/typed) screen.
 * Route paths mirror router/index.ts pocket children + the deep-link
 * vocabulary the views already watch (?to/?amount, ?sheet=stake, ?order=,
 * ?panic=1, ?q=, ?sym/?side/?qty/?px).
 */
import type { VoiceIntent } from './intentGrammar'

export interface Door {
  path: string
  query?: Record<string, string>
  /** No route change — the panel answers in place (balance readout etc.). */
  inPlace?: boolean
}

const TAB: Record<string, string> = {
  home: '/pocket/home', agents: '/pocket/agents', activity: '/pocket/activity',
  earn: '/pocket/payments', trade: '/pocket/trade', approvals: '/pocket/approvals',
  more: '/pocket/more', senate: '/pocket/home',
}

export function doorFor(i: VoiceIntent): Door | null {
  switch (i.kind) {
    case 'navigate':
      return i.target === 'senate'
        ? { path: '/pocket/home', query: { sheet: 'senate' } }
        : { path: TAB[i.target] || '/pocket/home' }
    case 'queue':
      return { path: '/pocket/home', query: { attention: '1' } }
    case 'balance':
      return { inPlace: true, path: '' }
    case 'send': {
      if (i.to?.did) {
        const query: Record<string, string> = { to: i.to.did }
        if (i.amount != null) query.amount = String(i.amount)
        return { path: '/pocket/pay', query }
      }
      // no roster match — land in agent search with the spoken name, honestly
      return { path: '/pocket/agents', query: { q: i.toQuery || '' } }
    }
    case 'stake': {
      const query: Record<string, string> = { sheet: 'stake' }
      if (i.amount != null) query.amount = String(i.amount)
      if (i.agent?.did) query.agent = i.agent.did
      return { path: '/pocket/home', query }
    }
    case 'find':
      return { path: '/pocket/agents', query: { q: i.query } }
    // §VOICEHIRE — three doors, all FILL. market-find: the Discover lane's own
    // deep-link vocabulary (?lane/?dq/?pricing, watched immediate). A price cap
    // opens the PAID lane — the honest approximation the echo already named.
    case 'market-find': {
      const query: Record<string, string> = { lane: 'discover', dq: i.query }
      if (i.maxPrice != null) query.pricing = 'paid'
      return { path: '/pocket/agents', query }
    }
    // offer: the thread door + the S proposal composer, prefilled via the
    // propose deep-link (consumed then scrubbed by the thread, like ?draft).
    case 'offer': {
      const query: Record<string, string> = { propose: '1' }
      if (i.to?.did) query.to = i.to.did
      else query.q = i.toQuery
      if (i.title) query.ptitle = i.title
      if (i.amount != null) query.ptotal = String(i.amount)
      if (i.currency) query.pccy = i.currency
      return { path: '/pocket/ourchat', query }
    }
    // hire-firm: Discovery's firms lane, scrolled to the name (lane-side watch).
    case 'hire-firm':
      return { path: '/discover', query: { firm: i.name } }
    case 'order':
      return { path: '/pocket/payments', query: { order: i.ref } }
    case 'freeze':
      return { path: '/pocket/approvals', query: { panic: '1' } }
    case 'trade': {
      if (!i.symbol) return { path: '/pocket/trade' }
      const query: Record<string, string> = { sym: i.symbol }
      if (i.side) query.side = i.side
      if (i.qty != null) query.qty = String(i.qty)
      if (i.limit != null) query.px = String(i.limit)
      return { path: '/pocket/trade', query }
    }
    case 'guild-bid':
      return { path: '/pocket/payments' }
    case 'guild-post': {
      // §POCKETBRIDGE4 WS-G — lands on the POST sheet, prefilled. The human
      // still confirms: posting escrows the bounty (a money moment).
      const query: Record<string, string> = { post: '1' }
      if (i.title) query.title = i.title
      if (i.bounty != null) query.bounty = String(i.bounty)
      return { path: '/pocket/payments', query }
    }
    // §OURSTATE-2 — the chat doors. Both land on a COMPOSER with a draft;
    // neither can send (the thread's send button is a human's finger).
    case 'message': {
      const query: Record<string, string> = {}
      if (i.to?.did) query.to = i.to.did
      else if (i.toQuery) query.q = i.toQuery
      if (i.body) query.draft = i.body
      return { path: '/pocket/ourchat', query }
    }
    case 'reply': {
      // No path change: 'reply' means THIS thread. The caller (the assistant
      // dock) applies the draft to the composer it is already looking at; a
      // door that navigated would lose the thread the human meant.
      return i.body ? { path: '', query: { draft: i.body } } : null
    }
    case 'help':
    case 'unknown':
      return null
  }
}
