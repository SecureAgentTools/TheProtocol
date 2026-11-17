import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0662 console polish, item 4 (order gwo_0aa7b875cbf65b6347f5f775): Discovery's cards print their numbers through the
 * app's number formatter (services/cockpit/num.ts, the app's locale), and a name is cut with an ellipsis only where a
 * hover shows it whole. The view is too large to mount here (Discovery.quantum.test.ts says why), so this reads the SFC.
 * Red on f569f6a6e: prices, guild counts, stars and the AGORA price print raw; the compact amounts and the health
 * figure use toFixed (the operating system's digits, never the app's); the card names are cut with no hover.
 */
const src = fs.readFileSync(path.resolve(__dirname, 'Discovery.vue'), 'utf8')
const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))
const script = src.slice(src.indexOf('<script'), src.lastIndexOf('</script>'))

describe('Discovery\'s numbers', () => {
  it('no card number prints raw: prices, guild counts, stars, the AGORA price and the filter counts', () => {
    const raw = [...template.matchAll(/\{\{\s*([^}]*?)\s*\}\}/g)].map((m) => m[1])
      .filter((e) => /^(agent\.pricing\.base_rate|agent\.track_record\.(jobs|stars|cross_registry|disputes)|equityFor\(agent\)!\.last|opt\.count|tg\.count|localAgentCount|encircledAgents\.length|rankBreakdown\(agent\)\.total)$/.test(e))
    expect(raw, 'each of these goes through the formatter').toEqual([])
  })
  it('nothing in the view formats a number with toFixed', () => {
    expect(src.match(/\.toFixed\(/g) || []).toEqual([])
  })
  it('the compact amount (formatAVT) is the formatter\'s compact form', () => {
    const fn = script.slice(script.indexOf('function formatAVT('), script.indexOf('function formatAVT(') + 500)
    expect(fn).toMatch(/fmtCompact\(/)
  })
})

describe('Discovery\'s names', () => {
  it('every element cut with an ellipsis carries a hover with the whole text', () => {
    const tags = [...template.matchAll(/<[a-zA-Z0-9-]+\b[^>]*?(?:class="[^"]*\b(?:truncate|disc-card-open)\b[^"]*")[^>]*>/g)].map((m) => m[0])
    expect(tags.length, 'the grid, the circle strip and the list').toBeGreaterThanOrEqual(5)
    for (const tag of tags) expect(tag, tag).toMatch(/\s:?title="/)
  })
})
