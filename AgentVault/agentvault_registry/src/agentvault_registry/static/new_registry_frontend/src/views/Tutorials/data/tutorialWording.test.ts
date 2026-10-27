/**
 * §TUTORIALWORDING (2026-10-14): the API tutorial tracks are listed on every console, production frames included,
 * behind the sign-in. Since 2026-10-01 nothing on the production frames may promise a return on Units: no yield, no
 * APY, no "passive income", no interest on the reputation bond, and no comparison with a central bank or a bank. The
 * tracks still said all of that (the staking track and the capstone sold staking as yield; the bond "withdrawn with
 * interest"; the treasury "the central bank of the agent economy"), while the console for signed-in users is meant to
 * advertise no rewards. A track may still teach the lock and its voting power, and say plainly that a registry which
 * pays no staking rewards shows no rates.
 *
 * The scan reads what a person sees (titles, subtitles, descriptions, explanations, notes, the one-line call
 * descriptions), never ids or API paths: `/staking/apy-tiers` is a real route name.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { allTracks } from './trackDefinitions'

const FORBIDDEN: Array<[string, RegExp]> = [
  ['APY', /\bAPY\b/],
  ['annual percentage yield', /annual percentage yield/i],
  ['yield', /\byields?\b/i],
  ['passive income', /passive income/i],
  ['earning a return', /\bearn(?:s|ing)?\s+(?:yield|rewards?|interest|APY)\b/i],
  ['interest', /\b(?:with|earns?|pays?) interest\b|\binterest rates?\b/i],
  ['bank', /\bbank(?:s|ing)?\b/i],
  ['dividend', /\bdividends?\b/i],
  ['IPO', /\bIPO\b/],
  ['investment', /\binvest(?:ment|ments|or|ors)?\b/i],
]

type Hit = { where: string; word: string; text: string }

function shownTexts(): Array<[string, string]> {
  const out: Array<[string, string]> = []
  for (const track of allTracks) {
    const t = track as any
    for (const f of ['title', 'subtitle', 'description', 'completionTitle']) {
      if (typeof t[f] === 'string') out.push([`${track.id}.${f}`, t[f]])
    }
    for (const step of track.steps) {
      const s = step as any
      for (const f of ['title', 'subtitle', 'explanation', 'notes']) {
        if (typeof s[f] === 'string') out.push([`${track.id}/${step.id}.${f}`, s[f]])
      }
      if (typeof s.apiCall?.description === 'string') out.push([`${track.id}/${step.id}.apiCall.description`, s.apiCall.description])
    }
  }
  return out
}

describe('the API tutorial tracks promise no return on Units', () => {
  it('reads a real population', () => {
    // A scan over nothing passes loudest: there are sixteen tracks with well over a hundred steps.
    expect(allTracks.length).toBeGreaterThanOrEqual(16)
    expect(shownTexts().length).toBeGreaterThan(500)
  })

  it('no shown text sells yield, interest, dividends or a bank', () => {
    const hits: Hit[] = []
    for (const [where, text] of shownTexts()) {
      for (const [word, re] of FORBIDDEN) {
        if (re.test(text)) hits.push({ where, word, text: text.slice(0, 120) })
      }
    }
    expect(hits).toEqual([])
  })

  it('the word list still catches the old sentences (control)', () => {
    const old = [
      'Stake AVT tokens for yield, earn voting power through the veToken model',
      '- **APY rewards** — passive income on locked tokens',
      'when all conditions are met, the bond can be withdrawn with interest',
      'Think of the treasury as the central bank of the agent economy.',
    ]
    for (const line of old) {
      expect(FORBIDDEN.some(([, re]) => re.test(line))).toBe(true)
    }
    // ...and leaves the route name alone, which a step may still quote.
    expect(FORBIDDEN.some(([, re]) => re.test('The `/staking/apy-tiers` endpoint (the name is historical)'))).toBe(false)
  })
})

/**
 * D6-738 (2026-10-16): a frame's money is its own unit (ECU on EU, ACU on ASIA, the sandbox's own), written "units".
 * The tracks still said AVT (the former network's unit) and "tokens" for money, the hub promised "earn {ccy}
 * rewards" and the track card an "AVT reward". "Token" stays for credentials (a JWT, a bootstrap or an agent token)
 * and in names (the Token Exchange Gateway, the Token Economics track); the scan reads the shown texts with inline
 * code removed, so a field name such as `auto_slash_max_avt` may still be quoted.
 */
const CREDENTIAL = new Set(('auth authentication access bearer refresh api jwt capability payment bootstrap session csrf '
  + 'pull push device agent developer verification reset invite invitation signed spiffe oauth id one-time join').split(' '))

function unitWording(text: string): string[] {
  const hits: string[] = []
  for (const line of text.split('\n')) {
    const prose = line.replace(/`[^`]*`/g, '')
    for (const m of prose.matchAll(/\b(?:AVT|JDAY|BVT)\b/g)) hits.push(m[0])
    for (const m of prose.matchAll(/(?:\b([\w-]+)[\s-]+)?\btokens\b/gi)) {
      const before = (m[1] || '').toLowerCase().split('-').pop() || ''
      if (!CREDENTIAL.has(before)) hits.push(m[0])
    }
  }
  return hits
}

describe('the tutorial texts name the frame\'s units', () => {
  it('no shown text of a track says AVT or tokens for money', () => {
    const hits = shownTexts().flatMap(([where, text]) => unitWording(text).map((w) => `${where}: ${w}`))
    expect(hits).toEqual([])
  })

  it('the hub and the track card promise no reward and name no former unit', () => {
    const template = (rel: string) => {
      const src = fs.readFileSync(path.resolve(__dirname, rel), 'utf8')
      return src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>')).replace(/<!--[\s\S]*?-->/g, '')
    }
    for (const rel of ['../TutorialHub.vue', '../components/shared/TrackCard.vue']) {
      const t = template(rel)
      expect(t.length).toBeGreaterThan(500)
      expect(unitWording(t), rel).toEqual([])
      expect(t, rel).not.toMatch(/\bearn(?:s|ing)?\b[^.'"]{0,40}\brewards?\b|\breward<\/span>/i)
    }
    const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../../i18n/locales/en.json'), 'utf8'))
    expect(en.tutorialHubView.body).not.toMatch(/\bearn\b|\brewards?\b|\{ccy\}/i)
  })

  it('the unit rule still catches the old sentences, and leaves credentials alone (control)', () => {
    expect(unitWording('Fund Agent A (5,000 AVT)')).toEqual(['AVT'])
    expect(unitWording('Give the agent AVT tokens to operate')).toEqual(['AVT', 'AVT tokens'])
    expect(unitWording('Transfer Tokens (A → B)')).toEqual(['Transfer Tokens'])
    expect(unitWording('Bootstrap tokens expire in 5 minutes. Agent tokens and JWT tokens too.')).toEqual([])
    expect(unitWording('- **auto_slash_max_avt** reads `max_avt` (a field name)')).toEqual([])
  })
})
