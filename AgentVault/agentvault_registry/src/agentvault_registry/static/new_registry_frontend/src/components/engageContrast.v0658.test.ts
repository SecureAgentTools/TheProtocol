import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0658 (v): the Engage outcome in the agent modal reads at least 4.5:1 (WCAG AA, normal text). The lifecycle
 * discovery_engage_to_its_outcome (e2e/suite/lifecycles/38-discovery-engage.spec.ts) is the first to check that screen,
 * and its a11y check (axe, color-contrast) measured three texts under 4.5:1 on sbx-alpha (fes-20261108T035249Z-9dd2),
 * each on the modal's #12212e:
 *  - the price's unit, "/req" (.adm-engage-per), #08868b = 3.73:1: the accent at 0.95, faded by `opacity: 0.6`;
 *  - the reason a door is shut (.adm-door-shut), #0a7178 = 2.84:1: the accent at 0.45;
 *  - the authorization on the receipt (.bsp-token), #6a7179 = 3.31:1: the muted text, faded by `opacity: 0.7`.
 * Each text is read the way the browser paints it: the rule's own colour, else the one it inherits from the rule named
 * as its parent, with the neural theme's values for its variables (the console's default; the theme the check ran on),
 * and every declared opacity on the way folded in, laid over #12212e. Red at ee2c8bdfd.
 */

const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

type RGB = [number, number, number]
type Paint = { rgb: RGB; a: number }

const THEME = read('assets/styles/neural-command.css')
/** A variable's value in the neural theme: its first definition, the :root block (the sovereign block overrides later). */
function themeVar(name: string): string {
  const m = THEME.match(new RegExp(`${name}:\\s*([^;]+);`))
  if (!m) throw new Error(`the theme does not define ${name}`)
  return m[1].trim()
}

/** A colour value as the browser resolves it under the neural theme. */
function paint(value: string): Paint {
  const v = value.trim()
  const whole = v.match(/^var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)$/)
  if (whole) return paint(themeVar(whole[1]))
  const s = v.replace(/var\(\s*(--[\w-]+)\s*\)/g, (_, n: string) => themeVar(n))
  const hex = s.match(/^#([0-9a-f]{6})$/i)
  if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as RGB, a: 1 }
  const rgba = s.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
  if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: rgba[4] === undefined ? 1 : Number(rgba[4]) }
  throw new Error(`a colour this test does not read: ${v}`)
}

function rule(css: string, selector: string): string {
  const at = css.indexOf(`${selector} {`)
  if (at < 0) throw new Error(`no rule for ${selector}`)
  return css.slice(at, css.indexOf('}', at))
}
const colourIn = (block: string): string | null => block.match(/(?:^|[\s;{])color:\s*([^;]+);/)?.[1] ?? null
const opacityIn = (block: string): number => {
  const m = block.match(/(?:^|[\s;{])opacity:\s*([\d.]+)\s*(?:;|$)/)
  return m ? Number(m[1]) : 1
}

/** The colour a person reads the text at: the rule's own colour, else its parent rule's, with both rules' opacity (an
 *  opacity fades everything inside the element, an inherited colour included). */
function readAt(css: string, selector: string, parent?: { css: string; selector: string }): Paint {
  const own = rule(css, selector)
  const up = parent ? rule(parent.css, parent.selector) : null
  const colour = colourIn(own) ?? (up ? colourIn(up) : null)
  if (!colour) throw new Error(`${selector} declares no colour and names no parent that does`)
  const p = paint(colour)
  return { rgb: p.rgb, a: p.a * opacityIn(own) * (up ? opacityIn(up) : 1) }
}

const hexRgb = (h: string): RGB => [0, 2, 4].map((i) => parseInt(h.slice(1 + i, 3 + i), 16)) as RGB
const over = (fg: Paint, bg: RGB): RGB => fg.rgb.map((c, i) => Math.round(fg.a * c + (1 - fg.a) * bg[i])) as RGB
function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
function ratio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** The background axe measured under all three texts. */
const MODAL = hexRgb('#12212e')
const onModal = (fg: Paint) => ratio(over(fg, MODAL), MODAL)

describe('the Engage outcome in the agent modal reads at least 4.5:1', () => {
  const modal = read('components/AgentDetailModal.vue')
  const panel = read('components/BuyServicePanel.vue')

  it('the price\'s unit, /req, beside the price', () => {
    expect(onModal(readAt(modal, '.adm-engage-per', { css: modal, selector: '.adm-engage-price' }))).toBeGreaterThanOrEqual(4.5)
  })

  it('the reason a door is shut', () => {
    expect(onModal(readAt(modal, '.adm-door-shut'))).toBeGreaterThanOrEqual(4.5)
  })

  it('the authorization on the receipt', () => {
    expect(onModal(readAt(panel, '.bsp-token', { css: panel, selector: '.bsp-receipt' }))).toBeGreaterThanOrEqual(4.5)
  })

  it('reads the three rules as they were the way axe measured them (a control)', () => {
    const was = [
      '.price { color: rgba(var(--nc-primary-rgb), 0.95); } .per { opacity: 0.6; font-size: 0.7rem; }',
      '.shut { margin: 0; color: rgba(var(--nc-primary-rgb), 0.45); }',
      '.receipt { color: var(--nc-text-muted, #94a3b8); } .token { opacity: 0.7; }',
    ]
    expect(over(readAt(was[0], '.per', { css: was[0], selector: '.price' }), MODAL)).toEqual(hexRgb('#08868b'))
    expect(over(readAt(was[1], '.shut'), MODAL)).toEqual(hexRgb('#0a7178'))
    expect(over(readAt(was[2], '.token', { css: was[2], selector: '.receipt' }), MODAL)).toEqual(hexRgb('#6a7179'))
    expect(ratio(hexRgb('#08868b'), MODAL)).toBeCloseTo(3.73, 1)
    expect(ratio(hexRgb('#0a7178'), MODAL)).toBeCloseTo(2.84, 1)
    expect(ratio(hexRgb('#6a7179'), MODAL)).toBeCloseTo(3.31, 1)
  })
})
