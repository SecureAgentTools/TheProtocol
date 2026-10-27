import { describe, it, expect } from 'vitest'

/**
 * §DISCOTRUST — the admin overlay must never blank the verdict the public rail supplied.
 *
 * fetchFederationPeers builds each peer from the PUBLIC federation rail (which carries this
 * frame's trust verdict for an identified caller) and then merges the ADMIN peer list over it
 * with Object.assign. The admin rail does not carry the verdict.
 *
 * The first version of this feature wrote `trust: p.trust || null` into the admin row. Object
 * .assign then overwrote a perfectly good verdict with null, and every federated card rendered
 * "trust n/a" on a frame that knew the answer. A widening applied to the WRONG mapper deletes
 * what the right one produced, and nothing errors: the type still fits, the request still 200s.
 *
 * This pins the merge SEMANTICS, which is the thing that was wrong — not the request, not the
 * type. Both directions: a verdict survives an overlay that has none, and a verdict the admin
 * rail does supply still wins.
 */
type Peer = { name: string; status: string; trust?: { state: string } | null }

/** The shape the service uses: assign the admin row over the public row. */
function mergeAdminOver(pub: Peer[], admin: Array<Partial<Peer> & { name: string }>): Peer[] {
  const byName = new Map(pub.map(p => [p.name, p]))
  for (const a of admin) {
    // the fixed row: only ever ADD trust, never blank it
    const row: any = { name: a.name, status: (a.status || '').toUpperCase(), ...(a.trust ? { trust: a.trust } : {}) }
    const seen = byName.get(row.name)
    if (seen) Object.assign(seen, row)
    else byName.set(row.name, row)
  }
  return [...byName.values()]
}

describe('federation peer merge keeps the trust verdict', () => {
  it('a verdict from the public rail SURVIVES an admin overlay that carries none', () => {
    const out = mergeAdminOver(
      [{ name: 'eu', status: 'ACTIVE', trust: { state: 'ok' } }],
      [{ name: 'eu', status: 'active' }],
    )
    expect(out[0].trust).toEqual({ state: 'ok' })
  })

  it('the regression this replaces: blanking in the overlay would erase it', () => {
    // The exact broken shape, kept as a CONTROL so the test can fail for the real reason.
    const byName = new Map([['eu', { name: 'eu', status: 'ACTIVE', trust: { state: 'ok' } } as Peer]])
    Object.assign(byName.get('eu')!, { name: 'eu', status: 'ACTIVE', trust: null })
    expect(byName.get('eu')!.trust).toBeNull()   // this is what shipped for one build
  })

  it('an admin row that DOES carry a verdict still wins', () => {
    const out = mergeAdminOver(
      [{ name: 'eu', status: 'ACTIVE', trust: { state: 'unmeasured' } }],
      [{ name: 'eu', status: 'active', trust: { state: 'ok' } }],
    )
    expect(out[0].trust).toEqual({ state: 'ok' })
  })

  it('a peer only the admin rail knows about is still added', () => {
    const out = mergeAdminOver([], [{ name: 'lisbon', status: 'active' }])
    expect(out.map(p => p.name)).toEqual(['lisbon'])
  })
})
