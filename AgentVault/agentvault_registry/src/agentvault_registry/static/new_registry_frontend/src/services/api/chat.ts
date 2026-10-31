/**
 * §OURSTATE-1 — the OurState chat API client.
 *
 * DELIBERATELY A BARE fetch CLIENT, not `apiClient` (the §FOREIGNDEV
 * peerDirect precedent): the chat API is DUAL-AUTH and the token of the
 * SPEAKING principal is chosen per call by the caller — the axios
 * interceptor's central token stamping is exactly what §VCSIGN proved
 * overrides per-call auth, and the `/chat/` family must never be blanketed
 * agent-tier (peer caution: the exchange-follows-acting predicate lives right
 * next to where that carve-out would go). Chat is LOCAL-registry by law in
 * CORE (same-registry threads only), so the origin is simply ours.
 *
 * Every mutation takes a `clientRef` — the schema-level idempotency the
 * offline queue replays through.
 */

import type { BlockTarget } from '@/services/chat/counterparty'

export interface ChatApiError extends Error {
  status: number
  detail: string
  /** The answer's whole JSON body (V0650 (l)): a 428 step-up answer carries its challenge here, not in `detail`. */
  body?: any
}

async function call(method: string, path: string, token: string | null, body?: any): Promise<any> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const r = await fetch(`/api/v1/chat${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data: any = null
  try { data = await r.json() } catch { /* empty body */ }
  if (!r.ok) {
    const detail = (data && (data.detail?.detail || data.detail || data.error?.detail)) || `HTTP ${r.status}`
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)) as ChatApiError
    err.status = r.status
    err.detail = err.message
    err.body = data
    throw err
  }
  return data
}

export interface TargetSpec {
  ptype: 'developer' | 'agent'
  developer_id?: number
  agent_did?: string
  /** §OURSTATE-3: `@name` is an ADDRESS the SERVER resolves — the client never
   *  guesses an id from it. The router has taken this since 3a; the type had
   *  not, so every caller that wanted to reach someone by handle had to look
   *  the id up first (or, in TypeScript, simply could not compile). */
  handle?: string
  /** §OURSTATE-3b: `handle@https://their.registry` — a principal on a PEER
   *  registry. This registry becomes the HOST of the resulting thread. */
  remote_key?: string
}

export const chatApi = {
  listConversations(token: string, state: 'active' | 'requests' = 'active', cursor?: string, limit = 30) {
    const q = new URLSearchParams({ state, limit: String(limit) })
    if (cursor) q.set('cursor', cursor)
    return call('GET', `/conversations?${q}`, token)
  },

  createConversation(token: string, kind: 'dm' | 'agent_service', target: TargetSpec,
                     firstMessage?: { kind: 'text' | 'card'; body?: string; card?: any; client_ref: string },
                     /* §OURSTATE-5a — the reference of a transfer that already
                        happened, when the recipient prices first contact. */
                     introPaymentRef?: string) {
    return call('POST', '/conversations', token,
      { kind, target, ...(firstMessage ? { first_message: firstMessage } : {}),
        ...(introPaymentRef ? { intro_payment_ref: introPaymentRef } : {}) })
  },

  myContactPolicy(token: string) { return call('GET', '/contact-policy/me', token) },
  /* §OURSTATE-5b — authority, re-derived at read time from IRONKEY. Never
     cached client-side: a revoked grant must read empty on the next call. */
  conversationAuthority(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/authority`, token)
  },
  myAwayAuthority(token: string) { return call('GET', '/away/authority', token) },
  /* §OURSTATE-6 — the disappearing timer. `hours: null` clears it. */
  setRetention(token: string, conversationId: string, hours: number | null) {
    return call('PUT', `/conversations/${conversationId}/retention`, token, { hours })
  },
  setContactPolicy(token: string, body: { policy?: string; price?: string; currency?: string;
                                          purse_did?: string; stated?: string }) {
    return call('PUT', '/contact-policy/me', token, body)
  },

  /* §OURSTATE-7 D — support threads. The ticket is the authority: `supportState`
     reads it, `supportReply` writes THROUGH it (a direct postMessage into a
     support thread is refused 409 on purpose — one writer). */
  supportState(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/support`, token)
  },
  supportReply(token: string, conversationId: string, text: string) {
    return call('POST', `/conversations/${conversationId}/support-reply`, token, { text })
  },
  supportOpen(token: string, body: { subject: string; message: string; category?: string }) {
    return call('POST', '/support/open', token, body)
  },

  getMessages(token: string, conversationId: string, beforeSeq?: number, limit = 40, join = false) {
    const q = new URLSearchParams({ limit: String(limit) })
    if (beforeSeq) q.set('before_seq', String(beforeSeq))
    // §TWOAGENT G1 (V0437): an owner opening its agent's cross-registry thread is announced; true is its consent
    if (join) q.set('join', 'true')
    return call('GET', `/conversations/${conversationId}/messages?${q}`, token)
  },

  postMessage(token: string, conversationId: string,
              payload: { kind: 'text' | 'card'; body?: string; card?: any; client_ref: string; reply_to?: string }) {
    return call('POST', `/conversations/${conversationId}/messages`, token, payload)
  },

  markRead(token: string, conversationId: string, seq: number) {
    return call('POST', `/conversations/${conversationId}/read`, token, { seq })
  },

  accept(token: string, conversationId: string) {
    return call('POST', `/conversations/${conversationId}/accept`, token, {})
  },
  decline(token: string, conversationId: string) {
    return call('POST', `/conversations/${conversationId}/decline`, token, {})
  },
  leave(token: string, conversationId: string) {
    return call('POST', `/conversations/${conversationId}/leave`, token, {})
  },
  mute(token: string, conversationId: string, muted: boolean) {
    return call('POST', `/conversations/${conversationId}/mute`, token, { muted })
  },
  burn(token: string, conversationId: string) {
    return call('POST', `/conversations/${conversationId}/burn`, token, {})
  },
  ping(token: string, conversationId: string, clientRef: string) {
    return call('POST', `/conversations/${conversationId}/ping`, token, { client_ref: clientRef })
  },

  /** AGENT JWT only — the caller IS the payer (§BUYSERVICE loop in a thread). */
  serviceCall(agentJwt: string, conversationId: string,
              payload: { client_ref: string; text?: string; payload?: any; amount?: string; ttl_seconds?: number }) {
    return call('POST', `/conversations/${conversationId}/service-call`, agentJwt, payload)
  },

  // §OURSTATE-2 — org rooms. Ops are gated server-side on the LIVE org role;
  // the client only ever OFFERS what services/chat/orgRoomActions.ts says.
  orgRooms(token: string) { return call('GET', '/org-rooms', token) },
  /* §OURSTATE-6 — an org's own answer to "do we have a room, and who opens it". */
  setOrgChatSettings(token: string, orgId: string,
                     body: { chat_enabled?: boolean; chat_open_policy?: string }) {
    return call('PUT', `/org-rooms/${encodeURIComponent(orgId)}/settings`, token, body)
  },
  openOrgRoom(token: string, orgId: string) {
    return call('POST', `/org-rooms/${encodeURIComponent(orgId)}/open`, token, {})
  },
  roomAction(token: string, conversationId: string,
             payload: { action: 'kick' | 'mute' | 'unmute' | 'mode' | 'topic' | 'motd' | 'assistant_on' | 'assistant_off';
                        target?: TargetSpec; value?: string }) {
    return call('POST', `/conversations/${conversationId}/room`, token, payload)
  },
  roomMembers(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/members`, token)
  },

  // §CHATDESK C4 — support review with consent: the banner's state, the
  // filer's grant, the granter's revoke. The desk's read side is admin-only
  // and lives on the support router, not here.
  reviewState(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/support-review`, token)
  },
  reviewGrant(token: string, conversationId: string, body: { ticket_id: number; expires_hours?: number }) {
    return call('POST', `/conversations/${conversationId}/support-review`, token, body)
  },
  reviewRevoke(token: string, conversationId: string, grantId: string) {
    return call('DELETE', `/conversations/${conversationId}/support-review/${grantId}`, token)
  },

  // §OURSTATE-3 REACH — handles: an opt-in ADDRESS. The profile read is
  // PUBLIC (no token) because that is the page a contact QR opens.
  myHandle(token: string) { return call('GET', '/handles/me', token) },
  claimHandle(token: string, handle: string) { return call('POST', '/handles/claim', token, { handle }) },
  handleProfile(handle: string) { return call('GET', `/handles/${encodeURIComponent(handle.replace(/^@/, ''))}`, null) },

  // §OURSTATE-4 PULSE — the opt-in economy feed. Moments are computed from
  // the registry-attested track record; there is no presence in it by design.
  myPulse(token: string) { return call('GET', '/pulse/me', token) },
  setPulse(token: string, cfg: { enabled: boolean; show_agents?: boolean; note?: string }) {
    return call('PUT', '/pulse/me', token, cfg)
  },
  handlePulse(handle: string) {
    return call('GET', `/handles/${encodeURIComponent(handle.replace(/^@/, ''))}/pulse`, null)
  },

  /** §OURSTATE-2 Away mode: "while you were away" — staged, never accepted. */
  awayDigest(token: string, limit = 30) { return call('GET', `/away/digest?limit=${limit}`, token) },

  listBlocks(token: string) { return call('GET', '/blocks', token) },
  // §TWOAGENT G1 household/V0436: a block names a developer, an agent OR a principal on a peer registry by its address
  block(token: string, target: BlockTarget) { return call('POST', '/blocks', token, target) },
  unblock(token: string, target: BlockTarget) { return call('DELETE', '/blocks', token, target) },

  // V0650 (l) — approvals in the chat. The decision always goes with the DEVELOPER token (agents never decide), and a
  // 428 answer carries the phone challenge in err.body (parseStepUp reads it).
  listApprovals(token: string, conversationId: string, status: 'pending' | 'decided' | 'all' = 'pending', limit = 50) {
    const q = new URLSearchParams({ status, limit: String(limit) })
    return call('GET', `/conversations/${conversationId}/approvals?${q}`, token)
  },
  getApproval(token: string, approvalId: string, wait = 0) {
    return call('GET', `/approvals/${encodeURIComponent(approvalId)}?wait=${Math.max(0, Math.min(20, wait))}`, token)
  },
  decideApprovals(token: string, conversationId: string,
                  body: { decision: 'approve' | 'deny'; approval_ids: string[]; challenge_id?: string;
                          note?: string; surface?: string }) {
    return call('POST', `/conversations/${conversationId}/approvals/decide`, token, body)
  },

  sync(token: string, sinceIso?: string) {
    const q = sinceIso ? `?since=${encodeURIComponent(sinceIso)}` : ''
    return call('GET', `/sync${q}`, token)
  },
}
