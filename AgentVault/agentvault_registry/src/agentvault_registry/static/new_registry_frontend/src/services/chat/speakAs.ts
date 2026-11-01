/**
 * V0652 (aj) (order gwo_9fa441b938ff31f95662243f): who a message goes out as.
 *
 * The maintainer's report (the sessions' room, seq 313): "I accidentally wrote with tester session account. It got
 * accidentally picked in the mobile app I don't know why." The composer spoke as the console's ACTING agent, and the
 * console picks one by itself at sign-in (the saved one, else the richest, else the only one it can act as; stores/
 * auth.ts), so a room got a message from an agent nobody chose for it. Now, outside an agent's service thread:
 *   - a message goes out as YOU unless an agent was chosen for THIS thread;
 *   - the choice is an explicit step in the composer, remembered per thread (this browser);
 *   - an acting agent chosen on another screen never carries into a thread; and a thread's chosen agent counts only
 *     while it is the acting agent (the token a message is sent with is the acting agent's), else you again.
 * In an agent's service thread the rail fixes the speaker: the caller is the payer, the acting agent.
 */

const KEY_PREFIX = 'ourchat.speakAs.'

type KV = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function store(s?: KV | null): KV | null {
  if (s) return s
  try { return typeof localStorage !== 'undefined' ? localStorage : null } catch { return null }
}

/** The agent chosen to speak as in this thread, or null (you). */
export function rememberedSpeaker(conversationId: string, s?: KV | null): string | null {
  const kv = store(s)
  if (!kv || !conversationId) return null
  try {
    const v = kv.getItem(KEY_PREFIX + conversationId)
    return v && v.startsWith('did:') ? v : null
  } catch { return null }
}

/** Remember the choice for this thread: an agent's DID, or null for you (the default, so nothing is stored). */
export function rememberSpeaker(conversationId: string, did: string | null, s?: KV | null): void {
  const kv = store(s)
  if (!kv || !conversationId) return
  try {
    if (did && did.startsWith('did:')) kv.setItem(KEY_PREFIX + conversationId, did)
    else kv.removeItem(KEY_PREFIX + conversationId)
  } catch { /* a full or blocked storage keeps the default: you */ }
}

/** The DID the next message is signed as, or null for you. */
export function resolveSpeaker(opts: { isAgentThread: boolean; activeDid: string | null; remembered: string | null }):
  string | null {
  if (opts.isAgentThread) return opts.activeDid || null
  if (opts.remembered && opts.remembered === opts.activeDid) return opts.remembered
  return null
}
