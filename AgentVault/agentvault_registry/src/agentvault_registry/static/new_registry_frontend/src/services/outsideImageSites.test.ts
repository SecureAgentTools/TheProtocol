/**
 * V0663 (order gwo_e3187dbb237a06e8261c1dfc): a peer registry's logo is drawn only through the registry. Avatars and
 * flare logos are drawn in two components (UserAvatar, FlareBadge) that route every address themselves
 * (registryImage.test.ts); a registry logo is read in several views, so this gate reads them all: a read of a
 * registry card's icon must sit on a line that resolves it (resolvePeerAsset, resolveRegIcon or registryImageSrc), or be
 * one of the places listed here that only carry it or show this registry's own card to its admin.
 * The profile preview is the one place that draws an address as typed (UserAvatar's `direct`), and only there.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')
const LOGO_READ = /\bvisual\??\.(icon_url|iconUrl)\b|\brcVisual\.icon_url\b|\bme\??\.icon_url\b/
const ROUTED = /\b(resolvePeerAsset|resolveRegIcon|registryImageSrc)\(/

/** [file, a substring of the line, why it may read the raw value] */
const CARRIERS: Array<[string, string, string]> = [
  ['views/RegistryCardEditor.vue', 'card.visual', "this registry's own card, a path on this origin, in its admin's editor"],
  ['views/FederationDiscovery.vue', '//   3. visual.icon_url', 'a comment'],
  ['views/FederationDiscovery.vue', 'const icon = peer.visual?.icon_url', 'resolved by resolvePeerAsset two lines on'],
  ['views/AgentWorldCesium.vue', 'const u = reg?.visual?.iconUrl', 'inside resolveRegIcon, which routes its answer'],
  ['views/AgentWorldCesium.vue', '-else-if="hoveredRegistry.visual?.iconUrl"', 'a v-if; the src is resolveRegIcon(...)'],
  ['views/AgentWorldCesium.vue', '-else-if="selectedRegistry.visual?.iconUrl"', 'a v-if; the src is resolveRegIcon(...)'],
  ['components/RegistryHoverCard.vue', 'v-else-if="r.visual?.iconUrl"', 'a v-if; the src is resolvedIconUrl'],
  ['views/GalacticMap.vue', 'iconUrl: rcVisual.icon_url', 'stored for RegistryHoverCard, which resolves it (resolvePeerAsset)'],
  ['views/UniverseView.vue', 'iconUrl: rcVisual.icon_url', 'stored for RegistryHoverCard, which resolves it (resolvePeerAsset)'],
  ['views/AgentWorldCesium.vue', 'iconUrl: rcVisual.icon_url', 'stored for resolveRegIcon, which resolves it'],
]

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : sourceFiles(p)
    if (e.name.endsWith('.test.ts') || e.name.endsWith('.spec.ts')) return []
    return /\.(vue|ts)$/.test(e.name) ? [p] : []
  })
}
const rel = (f: string) => path.relative(SRC, f).split(path.sep).join('/')

describe('outside images are drawn from the registry', () => {
  const files = sourceFiles(SRC)

  it('reads the source tree', () => {
    expect(files.length).toBeGreaterThan(300)
  })

  it('every read of a registry logo is resolved through the registry', () => {
    const bad: string[] = []
    for (const f of files) {
      const r = rel(f)
      fs.readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
        if (!LOGO_READ.test(line) || ROUTED.test(line)) return
        if (CARRIERS.some(([file, sub]) => file === r && line.includes(sub))) return
        bad.push(`${r}:${i + 1}: ${line.trim().slice(0, 140)}`)
      })
    }
    expect(bad, `draw these through resolvePeerAsset or registryImageSrc:\n${bad.join('\n')}`).toEqual([])
  })

  it('the two components that draw avatars and flare logos route their addresses', () => {
    const ua = fs.readFileSync(path.join(SRC, 'components/common/UserAvatar.vue'), 'utf8')
    const fb = fs.readFileSync(path.join(SRC, 'components/common/FlareBadge.vue'), 'utf8')
    expect(ua).toMatch(/const effectiveAvatarUrl = computed\([\s\S]{0,300}registryImageSrc\(/)
    expect(fb).toMatch(/const effectiveLogoUrl = computed\([\s\S]{0,200}registryImageSrc\(/)
  })

  it("only the profile preview draws an address as typed", () => {
    const users = files.filter((f) => /<UserAvatar[^>]*\bdirect\b/.test(fs.readFileSync(f, 'utf8'))).map(rel)
    expect(users).toEqual(['views/Settings.vue'])
  })
})
