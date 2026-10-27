/**
 * §COCKPITDESK (2026-10-15) SECURITY — a link to an address someone ELSE wrote goes through safeExternalUrl.
 *
 * An agent's card (any developer writes one), a peer registry's card, a venue's address, a frame runner's answer: each
 * was bound straight to :href, and a `javascript:` or `data:` value ran in this console's origin for whoever pressed the
 * link (agentvault2-5b found the organization and profile websites the same night). This gate reads every component's
 * template: an :href whose expression reads a field (a member access, or a parameter named like an address) must go
 * through safeExternalUrl, unless it is one of the internal links listed here, each with its reason.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')
/** Bindings that build an internal or fixed address, or are guarded another way. */
const INTERNAL: Array<[RegExp, string]> = [
  [/^(href|exportHref|fullAgentHref|target|recordHref\(.*\))$/, 'computed by the component from a route or the console origin'],
  [/^frameConsole\(f\)$/, 'https://<frame>.<runner domain> from the runner config'],
  [/^toast\.cta_url!?$/, 'shown only under isSafeCtaUrl(toast.cta_url)'],
  [/^agent\.dashboardUrl$/, "CommunityView's own constants"],
  [/^entry\.learnMoreUrl$/, "the help catalog's own constants"],
  [/^c\.public_url && c\.status === 'up' \? c\.public_url : undefined$/, "this registry's status config (StatusPage)"],
]

function vueFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : vueFiles(p)
    return e.name.endsWith('.vue') ? [p] : []
  })
}

describe('links to addresses someone else wrote', () => {
  it('go through safeExternalUrl', () => {
    const bad: string[] = []
    for (const f of vueFiles(SRC)) {
      const s = fs.readFileSync(f, 'utf8')
      const tpl = s.slice(0, s.indexOf('<script') >= 0 ? s.indexOf('<script') : s.length)
      for (const m of tpl.matchAll(/:href="([^"]+)"/g)) {
        const expr = m[1].trim()
        if (expr.includes('safeExternalUrl(')) continue
        // a literal or template that starts with a site path, a hash route or an API path is internal
        if (/^['`](\/|#)/.test(expr) || /^`\$\{[^}]*\}\/api\/v1\//.test(expr) === false && /^`\/api\/v1\//.test(expr)) continue
        if (INTERNAL.some(([re]) => re.test(expr))) continue
        // what reads data someone else may write: a member access or an address-named value
        if (/[.\w](url|Url|URL|href|Href|link|Link)\b|\.\w+_url\b|\bu\b|\burl\b|website|homepage|github|repo/i.test(expr)) {
          bad.push(`${path.relative(SRC, f)}: :href="${expr}"`)
        }
      }
    }
    expect(bad).toEqual([])
  })
})
