/**
 * A peer registry's asset address (§FESUITE, the rule RegistryHoverCard has carried since 2026-06-14).
 *
 * A registry card stores its icon SAME-ORIGIN-relative (/static/registry-cards/...: the upload endpoint and the
 * receiving registry's sync normalisation both enforce it). Rendered as-is on another frame's console it resolves
 * against the VIEWER's origin and answers 404 there; resolved against the peer's own public address it is the peer's
 * icon. An absolute address, or a relative one with no host to resolve it against (our own registry), passes through.
 */
export function resolvePeerAsset(url: string | null | undefined, peerPublicUrl: string | null | undefined): string | undefined {
  if (!url) return undefined
  if (/^https?:\/\//i.test(url)) return url
  const host = (peerPublicUrl || '').trim()
  if (url.startsWith('/') && /^https?:\/\//i.test(host)) return host.replace(/\/+$/, '') + url
  return url
}
