import { describe, it, expect } from 'vitest'
import router from './index'

// The page addresses in the compliant words (his "yes all approved." 2026-10-25 to "route and address renames such as
// /staking"): the lock desk, Units & Fees and Pocket's Payments tab answer at /locks, /units-and-fees and
// /pocket/payments. The route NAMES stay, and every old address, in links and notifications already sent, redirects
// with its query and hash (a redirect function: a bare string drops both).

function follow(path: string) {
  const from = router.resolve(path)
  const rec = from.matched[from.matched.length - 1]
  expect(rec?.redirect, `${path} redirects`).toBeTruthy()
  const target = typeof rec.redirect === 'function' ? (rec.redirect as (to: unknown) => unknown)(from) : rec.redirect
  return router.resolve(target as Parameters<typeof router.resolve>[0])
}

describe('page addresses', () => {
  it('the three pages answer at their new addresses, under their old route names', () => {
    expect(router.resolve('/locks').name).toBe('staking')
    expect(router.resolve('/units-and-fees').name).toBe('token-economy')
    expect(router.resolve('/pocket/payments').name).toBe('pocket-earn')
  })

  it('each old address redirects there and keeps its query and hash', () => {
    expect(follow('/staking?tab=positions#top')).toMatchObject({ path: '/locks', query: { tab: 'positions' }, hash: '#top' })
    expect(follow('/token-economy?from=landing')).toMatchObject({ path: '/units-and-fees', query: { from: 'landing' } })
    expect(follow('/pocket/earn?order=42')).toMatchObject({ path: '/pocket/payments', query: { order: '42' } })
  })

  it('no route answers at an old address any more except as a redirect', () => {
    for (const old of ['/staking', '/token-economy', '/pocket/earn']) {
      const matched = router.resolve(old).matched
      const rec = matched[matched.length - 1]
      expect(rec?.components?.default, old).toBeUndefined()
    }
  })
})
