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

/** V0654 (aq): a member's wake mode in a conversation (services/chat_service.WAKE_MODES). */
export type WakeMode = 'listen' | 'on-call' | 'off'

export interface ChatApiError extends Error {
  status: number
  detail: string
  /** The answer's whole JSON body (V0650 (l)): a 428 step-up answer carries its challenge here, not in `detail`. */
  body?: any
  /** V0652 (ag): a 429's or a 503's Retry-After, in seconds, when the answer named one. */
  retryAfterS?: number
}

async function call(method: string, path: string, token: string | null, body?: any): Promise<any> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  // V0662: a FormData goes out as it is. Its Content-Type carries the multipart BOUNDARY and only the browser knows
  // it, so naming one here (or stringifying the form) sends a body the registry cannot read.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  const r = await fetch(`/api/v1/chat${path}`, {
    method, headers, body: body === undefined ? undefined : (isForm ? body : JSON.stringify(body)),
  })
  let data: any = null
  try { data = await r.json() } catch { /* empty body */ }
  if (!r.ok) {
    const detail = (data && (data.detail?.detail || data.detail || data.error?.detail)) || `HTTP ${r.status}`
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)) as ChatApiError
    err.status = r.status
    err.detail = err.message
    err.body = data
    const ra = Number(r.headers?.get?.('retry-after'))
    if (Number.isFinite(ra) && ra > 0) err.retryAfterS = ra
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
  listConversations(token: string, state: 'active' | 'requests' | 'archived' = 'active', cursor?: string, limit = 30) {
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

  /** V0663 (order 418): the messages of this thread that name the caller (the registry's mentions=me read, newest first). */
  getMentionsMe(token: string, conversationId: string, limit = 50) {
    const q = new URLSearchParams({ limit: String(limit), mentions: 'me' })
    return call('GET', `/conversations/${conversationId}/messages?${q}`, token)
  },

  /** V0663 (order 418): the newest unread messages that name the caller across their rooms, with the total (the bell). */
  unreadMentions(token: string, limit = 20) {
    return call('GET', `/mentions?limit=${limit}`, token)
  },

  postMessage(token: string, conversationId: string,
              payload: { kind: 'text' | 'card'; body?: string; card?: any; client_ref: string; reply_to?: string }) {
    return call('POST', `/conversations/${conversationId}/messages`, token, payload)
  },

  /** V0662: store a file for this thread. Uploading posts nothing: the answer carries the attachment's pointer and the
   *  `card` to send next as a `kind: 'card'` message, so a failed upload never leaves a half-message in the room
   *  (routers/chat.py upload_attachment; chat_link does the same two steps). The registry takes text, markdown, PDF
   *  and images up to 5 MB. */
  uploadAttachment(token: string, conversationId: string, file: Blob, name?: string) {
    const form = new FormData()
    // The name travels on a File of its own: `append(name, blob, filename)` renames in a browser but not in every
    // environment that builds a FormData, and the registry derives the stored extension from this name.
    form.append('file', new File([file], name || (file as File).name || 'file', { type: file.type }))
    return call('POST', `/conversations/${conversationId}/attachments`, token, form)
  },

  /** V0654 (ap): ask your personal assistant to answer in this room as the identity of `token` (you, or your agent
   *  through your own signed-in session). The prompt is never posted: the registry posts the assistant's answer
   *  (sent_with "assistant") and returns it, after tens of seconds. Asking again with the same client_ref returns
   *  the answer already posted and never asks twice. */
  assist(token: string, conversationId: string, payload: { prompt: string; client_ref: string }) {
    return call('POST', `/conversations/${conversationId}/assist`, token, payload)
  },

  /** V0652 (ag): the catch-up stream (V0650 (g)): with `wait` the call answers as soon as something new reaches one of
   *  your threads, or empty at the bound; pass the answer's next_cursor back as `cursor`. */
  sync(token: string, opts: string | { since?: string; cursor?: string; wait?: number } = {}) {
    if (typeof opts === 'string') opts = { since: opts }       // the older call shape: sync(token, sinceIso)
    const q = new URLSearchParams()
    if (opts.cursor) q.set('cursor', opts.cursor)
    else if (opts.since) q.set('since', opts.since)
    if (opts.wait) q.set('wait', String(Math.max(0, Math.min(25, opts.wait))))
    const s = q.toString()
    return call('GET', `/sync${s ? `?${s}` : ''}`, token)
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
  /** V0652 (ak): `until` (ISO) makes a mute end by itself; without it a mute holds until lifted. */
  mute(token: string, conversationId: string, muted: boolean, until?: string | null) {
    return call('POST', `/conversations/${conversationId}/mute`, token, until && muted ? { muted, until } : { muted })
  },
  burn(token: string, conversationId: string) {
    return call('POST', `/conversations/${conversationId}/burn`, token, {})
  },
  /** V0652 (ac): an organization's room's status board (any member), its every edit, and the owner's editors. */
  getBoard(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/board`, token)
  },
  putBoard(token: string, conversationId: string, text: string, baseRev: number) {
    return call('PUT', `/conversations/${conversationId}/board`, token, { text, base_rev: baseRev })
  },
  boardHistory(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/board/history`, token)
  },
  putBoardEditors(token: string, conversationId: string, editors: string[]) {
    return call('PUT', `/conversations/${conversationId}/board/editors`, token, { editors })
  },
  /** V0652 (aa): the updates a card took in place, oldest first (who, when, what changed). */
  cardHistory(token: string, conversationId: string, messageId: string) {
    return call('GET', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/card/history`, token)
  },
  /** V0662: the thread's pins (newest first), `can_pin`, `max`; PUT / DELETE .../pin pins or unpins a message. */
  listPins(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/pins`, token)
  },
  pinMessage(token: string, conversationId: string, messageId: string) {
    return call('PUT', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/pin`, token)
  },
  unpinMessage(token: string, conversationId: string, messageId: string) {
    return call('DELETE', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/pin`, token)
  },
  /** V0662: text lines of one thread holding the words (newest first; `before_seq` continues). */
  searchMessages(token: string, conversationId: string, q: string, beforeSeq?: number) {
    const qs = new URLSearchParams({ q })
    if (beforeSeq) qs.set('before_seq', String(beforeSeq))
    return call('GET', `/conversations/${conversationId}/search?${qs.toString()}`, token)
  },
  /** V0662: the session board of an organization's room (the organization's owners and admins; 403 otherwise). */
  agentStatus(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/agent-status`, token)
  },
  /** V0662: put a reaction word on a message (answers { reactions, added }); DELETE takes it off. */
  addReaction(token: string, conversationId: string, messageId: string, word: string) {
    return call('PUT', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/reactions/${encodeURIComponent(word)}`, token)
  },
  removeReaction(token: string, conversationId: string, messageId: string, word: string) {
    return call('DELETE', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/reactions/${encodeURIComponent(word)}`, token)
  },
  /** V0662: change the text of your own message inside the registry's window (answers { message, changed }). */
  editMessage(token: string, conversationId: string, messageId: string, body: string) {
    return call('PUT', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}`, token, { body })
  },
  /** V0662: take back your own message inside the window (answers { message }, the tombstone). */
  deleteMessage(token: string, conversationId: string, messageId: string) {
    return call('DELETE', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}`, token)
  },
  /** V0662: the earlier texts of a message, oldest first (when, who, the text before). */
  messageHistory(token: string, conversationId: string, messageId: string) {
    return call('GET', `/conversations/${conversationId}/messages/${encodeURIComponent(messageId)}/history`, token)
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
  /** V0662: seat a guest in an organization's room ({ agent_did } or { developer_id }); remove one by the member sheet's key. */
  seatGuest(token: string, conversationId: string, target: { agent_did?: string; developer_id?: number }) {
    return call('POST', `/conversations/${conversationId}/guests`, token, target)
  },
  removeGuest(token: string, conversationId: string, memberKey: string) {
    return call('DELETE', `/conversations/${conversationId}/guests/${encodeURIComponent(memberKey)}`, token)
  },
  roomMembers(token: string, conversationId: string) {
    return call('GET', `/conversations/${conversationId}/members`, token)
  },

  /** V0654 (aq): what of this conversation wakes a member: listen, on-call or off. `member` (its key, as the member
   *  sheet gives it) for another member's, which the room's owner sets from a signed-in console; none for your own.
   *  A change posts one line in the room, to that member alone; the same mode again changes nothing. */
  setWakeMode(token: string, conversationId: string, mode: WakeMode, member?: string) {
    return call('PUT', `/conversations/${conversationId}/wake`, token, member ? { mode, member } : { mode })
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
  /** V0651 (y): every pending request the caller may decide, across the rooms (Pocket's Approvals). */
  listWaitingApprovals(token: string, limit = 50) {
    return call('GET', `/approvals?limit=${Math.max(1, Math.min(200, limit))}`, token)
  },
  getApproval(token: string, approvalId: string, wait = 0) {
    return call('GET', `/approvals/${encodeURIComponent(approvalId)}?wait=${Math.max(0, Math.min(20, wait))}`, token)
  },
  decideApprovals(token: string, conversationId: string,
                  body: { decision: 'approve' | 'deny' | 'choose'; approval_ids: string[]; challenge_id?: string;
                          note?: string; surface?: string; option?: number }) {   // V0652 (ab): choose + option
    return call('POST', `/conversations/${conversationId}/approvals/decide`, token, body)
  },

  // ── V0659 (f): cross-frame rooms (routers/chat.py, the /rooms family) ──────────────────────────────────────────
  /** Open a room hosted on this registry, owned by the speaking principal. */
  createRoom(token: string, body: { title: string; topic?: string; join_rule: RoomJoinRule }) {
    return call('POST', '/rooms', token, body)
  },
  /** Join a room by its address (room:<id>@https://its.registry), here or on a peer registry. */
  joinRoom(token: string, address: string) { return call('POST', '/rooms/join', token, { address }) },
  /** A room as its members see it: head, your seat, its members (and, for its operators, the requests). */
  roomInfo(token: string, conversationId: string) {
    return call('GET', `/rooms/${encodeURIComponent(conversationId)}`, token)
  },
  /** One operator act (the owner, or a moderator on a lower rank), in a room hosted here. */
  /** V0663: close a room nobody has spoken in (its owner or a moderator); a room with messages is archived instead. */
  closeRoom(token: string, conversationId: string) {
    return call('POST', `/rooms/${encodeURIComponent(conversationId)}/close`, token)
  },
  roomAct(token: string, conversationId: string, body: { action: RoomAction; member?: string; value?: string }) {
    return call('POST', `/rooms/${encodeURIComponent(conversationId)}/act`, token, body)
  },

}

/** V0659 (f): a room's join rule, set by its owner. */
export type RoomJoinRule = 'invited' | 'request' | 'anyone'
/** V0659 (f): the operator acts a room's host takes. */
export type RoomAction = 'invite' | 'mute' | 'unmute' | 'remove' | 'ban' | 'accept' | 'moderator' | 'unmoderator'
  | 'rule' | 'topic' | 'title' | 'archive' | 'unarchive'
