/**
 * V0663 (order gwo_e3187dbb237a06e8261c1dfc): where the console draws an outside image from (a peer registry's logo, a
 * developer's avatar, a flare logo). Never the address a record names: every reader's browser dialled it, and whoever
 * runs that host learned who looked. The registry this console talks to serves an address one of its records names,
 * fetched once through its outbound guard (GET /public/images?src=; a card icon has its own route, cardIconSrc).
 *   - an absolute http(s) address, or a data:image one: the registry's route;
 *   - a path on this origin (the registry's own routes and static files): as it is;
 *   - anything else (scheme-relative, javascript:, another data: type): null, which draws the initial.
 */
import { config } from '@/config'

export function registryImageSrc(address: unknown): string | null {
  if (typeof address !== 'string') return null
  const a = address.trim()
  if (!a) return null
  if (a.startsWith('/')) return a.startsWith('//') ? null : a
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  if (origin && a.startsWith(`${origin}/`)) return a
  if (!/^(https?:\/\/|data:image\/)/i.test(a)) return null
  return `${config.api.baseURL}/public/images?src=${encodeURIComponent(a)}`
}
