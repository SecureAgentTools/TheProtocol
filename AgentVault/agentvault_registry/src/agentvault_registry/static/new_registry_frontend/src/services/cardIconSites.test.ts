/**
 * V0662, item 14 (order gwo_d721ad2f8118863d62815103): the console loads a card's icon only from the registry.
 *
 * A card's iconUrl is an address its developer wrote (or a peer relayed). Bound straight to an image, every reader's
 * browser dialled it: whoever runs that host learns who looked at the card, and when. The registry now fetches it once
 * through its outbound guard and serves it from its own origin (GET /agent-cards/{did}/icon), and
 * services/agentAvatar.cardIconSrc is the one way to that route.
 *
 * This gate reads every component and module: a read of an agent card's icon field must go through cardIconSrc (or
 * agentAvatarUrl, which uses it), unless it is one of the places listed here that only carry the value along or show
 * it as text to its owner, each with its reason. A registry card's logo (visual.icon_url) is another field and is not
 * read here.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')

/** an agent card's icon field, read from the card (card_data, rawCardData, cd) or from a row that hoists it */
const ICON_READ = /\b(card_data|rawCardData|cardData|cd)\??\.(iconUrl|icon_url)\b|(?<![\w.])(a|it|agent|row|profile|p|m|r)\??\.icon_url\b/

/** [file, a substring of the line, why it may read the raw value] */
const CARRIERS: Array<[string, string, string]> = [
  ['services/api/discovery.ts', 'card_data: { iconUrl: it.icon_url', "builds the row's card_data stub; the views draw it through cardIconSrc"],
  ['services/agentAvatar.ts', '', 'the helper itself'],
  ['services/api/organizationService.ts', '/** V0655 (ay)', 'a type comment'],
]

/** files that may call rawCardIcon: the owner's own edit field and its text, never an image */
const RAW_READERS = ['views/MyAgents.vue']

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : sourceFiles(p)
    if (e.name.endsWith('.test.ts') || e.name.endsWith('.spec.ts')) return []
    return /\.(vue|ts)$/.test(e.name) ? [p] : []
  })
}

describe("a card's icon is drawn from the registry", () => {
  const files = sourceFiles(SRC)

  it('reads the source tree (a gate over nothing passes for nothing)', () => {
    expect(files.length).toBeGreaterThan(300)
    expect(files.some((f) => f.endsWith(path.join('views', 'Discovery.vue')))).toBe(true)
  })

  it('every read of an agent card icon goes through cardIconSrc', () => {
    const bad: string[] = []
    for (const f of files) {
      const rel = path.relative(SRC, f).split(path.sep).join('/')
      fs.readFileSync(f, 'utf8').split('\n').forEach((line, i) => {
        if (!ICON_READ.test(line)) return
        if (/\b(cardIconSrc|agentAvatarUrl)\(/.test(line)) return
        if (CARRIERS.some(([file, sub]) => file === rel && line.includes(sub))) return
        bad.push(`${rel}:${i + 1}: ${line.trim().slice(0, 140)}`)
      })
    }
    expect(bad, `draw these through cardIconSrc (services/agentAvatar):\n${bad.join('\n')}`).toEqual([])
  })

  it('the raw address is read only where its owner edits it', () => {
    const bad: string[] = []
    for (const f of files) {
      const rel = path.relative(SRC, f).split(path.sep).join('/')
      if (rel === 'services/agentAvatar.ts' || RAW_READERS.includes(rel)) continue
      if (/\brawCardIcon\(/.test(fs.readFileSync(f, 'utf8'))) bad.push(rel)
    }
    expect(bad).toEqual([])
  })

  it('the gate sees a direct read (control)', () => {
    expect(ICON_READ.test(':avatar-url="agent.card_data?.iconUrl || null"')).toBe(true)
    expect(ICON_READ.test('safeIcon(a.icon_url)')).toBe(true)
    expect(ICON_READ.test('const u = vis.value.icon_url')).toBe(false)
    expect(ICON_READ.test('peer.visual?.icon_url')).toBe(false)
  })
})
