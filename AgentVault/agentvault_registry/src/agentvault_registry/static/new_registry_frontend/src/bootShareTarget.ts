/**
 * bootShareTarget.ts — §POCKETBRIDGE4 WS-H: Web Share Target boot shim.
 *
 * MUST be the FIRST import in main.ts. The manifest's share_target action is
 * /ui (no hash — GET params would land after a fragment), so a share arrives
 * as /ui?text=…&url=…&title=… BEFORE any hash. vue-router's
 * createWebHashHistory() normalizes a hashless URL to `#/` AT MODULE
 * EVALUATION TIME and drops the query with it — ESM hoisting runs the router
 * module before any statement in main.ts, so this shim only works as an
 * import that precedes the router's (imports evaluate in declaration order).
 *
 * Routing: a did:… anywhere in the payload opens the send door prefilled;
 * anything else lands in the Assistant as a DRAFT (never auto-submitted —
 * shared text is data, not a command). The query is scrubbed so a reload
 * doesn't replay the share.
 */
try {
  const boot = new URLSearchParams(window.location.search)
  if (boot.has('text') || boot.has('url') || boot.has('title')) {
    const payload = ['text', 'url', 'title'].map((k) => boot.get(k) || '').join(' ').trim()
    const did = (payload.match(/did:[a-z0-9]+:[A-Za-z0-9._-]+/) || [])[0]
    const target = did
      ? `#/pocket/pay?to=${encodeURIComponent(did)}`
      : '#/pocket/assistant'
    if (!did && payload) {
      try { sessionStorage.setItem('tp_assistant_draft', payload.slice(0, 2000)) } catch { /* private mode */ }
    }
    window.history.replaceState(null, '', window.location.pathname + target)
  }
} catch { /* a malformed share must never block boot */ }

export {}
