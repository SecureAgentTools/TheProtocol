import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * §LEDGERGATE (V0601): a notice is drawn above every page, panel and dialog. The app's notice stack sat at z-index 50
 * while the beta banner is 9999, so on every page that shows the banner the top of each notice, its title, lay under the
 * banner, and every overlay above 50 (most modals: 9999 to 99999) hid a notice raised from inside it. Journal 51's photo
 * drill found it: Pocket's "Ledger busy" under the banner on a phone. RED on fe/batch-v0600 (the stack reads 50).
 * The levels are read from the sources, so a later change to the banner, a modal or the tour is measured here too.
 */
const SRC = path.resolve(__dirname, '../..')
const read = (rel: string) => readFileSync(path.join(SRC, rel), 'utf-8')

function zOfRule(src: string, selector: string): number {
  const m = src.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{[^}]*?z-index:\\s*(\\d+)`))
  if (!m) throw new Error(`no z-index for ${selector}`)
  return Number(m[1])
}

function stackZ(): number {
  const sfc = read('components/common/NotificationSystem.vue')
  const tpl = sfc.slice(sfc.indexOf('<template>'))
  const root = tpl.match(/<div class="([^"]+)"/)
  if (!root) throw new Error('no root element in the template')
  const classes = root[1].split(/\s+/)
  const tw = classes.map((c) => c.match(/^z-(?:\[(\d+)\]|(\d+))$/)).find(Boolean)
  if (tw) return Number(tw[1] ?? tw[2])
  for (const c of classes) {
    try { return zOfRule(sfc, `.${c}`) } catch { /* not this class */ }
  }
  throw new Error(`the stack's classes carry no z-index: ${root[1]}`)
}

describe('a notice is drawn above every page, panel and dialog', () => {
  const z = stackZ()
  const app = read('App.vue')

  it('is above the beta banner', () => {
    expect(z).toBeGreaterThan(zOfRule(app, '.beta-banner'))
  })

  it('is above the highest modal overlay and the guided tour', () => {
    expect(z).toBeGreaterThan(zOfRule(read('views/MyAgents.vue'), '.modal-overlay'))
    expect(z).toBeGreaterThan(zOfRule(read('views/Tutorials/guided/GuidedTour.vue'), '.gt-root'))
  })

  it('stays below the skip link, which outranks it', () => {
    expect(z).toBeLessThan(zOfRule(app, '.skip-to-content'))
  })
})
