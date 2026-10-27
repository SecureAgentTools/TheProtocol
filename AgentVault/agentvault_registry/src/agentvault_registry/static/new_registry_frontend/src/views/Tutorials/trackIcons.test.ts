import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { TRACK_ICONS, TRACK_ICON_FALLBACK, trackIcon } from './trackIcons'

describe('tutorial track icons', () => {
  it('maps every icon key a track definition names, and falls back for an unknown one', () => {
    const dir = path.resolve(__dirname, 'data')
    const keys = new Set<string>()
    for (const f of fs.readdirSync(dir).filter(n => n.endsWith('.track.ts'))) {
      for (const m of fs.readFileSync(path.join(dir, f), 'utf8').matchAll(/^\s+icon:\s*'([^']+)'/gm)) keys.add(m[1])
    }
    expect(keys.size).toBeGreaterThan(5)
    for (const k of keys) expect(TRACK_ICONS[k], `track icon key ${k}`).toMatch(/^mdi:/)
    expect(trackIcon('no-such-key')).toBe(TRACK_ICON_FALLBACK)
    expect(trackIcon(undefined)).toBe(TRACK_ICON_FALLBACK)
  })

  it('leaves no emoji standing in for an icon in the hub, the track card or the event panel', () => {
    // colour pictographs and anything asking for emoji presentation (U+FE0F); a typographic check mark (U+2713) is text
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2B50}\u{2705}\u{FE0F}]/u
    for (const rel of ['TutorialHub.vue', 'components/shared/TrackCard.vue', 'components/shared/EventPanel.vue']) {
      const text = fs.readFileSync(path.resolve(__dirname, rel), 'utf8')
      const hits = text.split('\n').filter(l => emoji.test(l) && !l.trim().startsWith('//'))
      expect(hits, rel).toEqual([])
    }
  })
})
