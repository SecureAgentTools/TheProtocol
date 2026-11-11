/**
 * V0658 (r): an owner sees why his organization's mark does not show (the maintainer found no organization logo anywhere
 * on EU after V0657, the sessions' room seq 2136). V0657 (b) states the mark only while the organization is listed and
 * shows only a logo this registry hosts; nothing on screen said which held. OrgMarkWhy tells the people who can change
 * it which condition is missing, each with the one control that fixes it, offers an old logo address's image for upload,
 * and shows nothing to anyone else. A test per state; the controls; its texts' contrast.
 * RED on v0657/cut: OrgMarkWhy.vue does not exist.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ updateOrgSettings: vi.fn(), uploadLogo: vi.fn() }))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: { updateOrgSettings: h.updateOrgSettings, uploadLogo: h.uploadLogo },
}))

import OrgMarkWhy from './OrgMarkWhy.vue'

const HOSTED = '/api/v1/organizations/org-1/logo?v=abc123def456'
const OLD = 'https://old.example/brand/logo.png'
const owner = { orgId: 'org-1', canFix: true }
const why = (props: Record<string, unknown>) => mount(OrgMarkWhy, { props: { ...owner, ...props } })
const box = (w: ReturnType<typeof why>) => w.find('[data-testid="org-mark-why"]')

beforeEach(() => {
  h.updateOrgSettings.mockReset()
  h.uploadLogo.mockReset()
})

describe('which condition is missing, each with the control that fixes it', () => {
  it('not listed and no hosted logo: both reasons, each with its control', () => {
    const w = why({ listed: false, logo: null })
    expect(box(w).exists()).toBe(true)
    expect(box(w).attributes('data-missing')).toBe('listing logo')
    expect(w.find('[data-testid="org-mark-why-title"]').text()).toBe('Why its logo does not show')
    expect(w.find('[data-testid="org-mark-why-listing"]').text()).toContain('It is not listed')
    expect(w.find('[data-testid="org-mark-why-list"]').text()).toBe('List this organization publicly')
    expect(w.find('[data-testid="org-mark-why-logo"]').text()).toContain('No logo is hosted here')
    expect(w.find('[data-testid="org-mark-why-upload"]').attributes('accept')).toBe('image/png,image/jpeg')
  })

  it('not listed, with a hosted logo: only the listing, with its control', () => {
    const w = why({ listed: false, logo: HOSTED })
    expect(box(w).attributes('data-missing')).toBe('listing')
    expect(w.find('[data-testid="org-mark-why-list"]').exists()).toBe(true)
    expect(w.find('[data-testid="org-mark-why-logo"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-upload"]').exists()).toBe(false)
  })

  it('listed, with no hosted logo: only the logo, with its control', () => {
    const w = why({ listed: true, logo: null })
    expect(box(w).attributes('data-missing')).toBe('logo')
    expect(w.find('[data-testid="org-mark-why-listing"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-list"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-upload"]').exists()).toBe(true)
  })

  it('listed, with a hosted logo: the mark shows, and nothing is said', () => {
    expect(box(why({ listed: true, logo: HOSTED, logoUrl: OLD })).exists()).toBe(false)
  })

  it('anyone who cannot change it (a member, a visitor) sees nothing new, in every state', () => {
    for (const listed of [false, true]) {
      for (const logo of [null, HOSTED]) {
        const w = mount(OrgMarkWhy, { props: { orgId: 'org-1', canFix: false, listed, logo, logoUrl: OLD } })
        expect(w.find('[data-testid="org-mark-why"]').exists(), `listed=${listed} logo=${logo}`).toBe(false)
        expect(w.html(), 'no trace at all').toBe('<!--v-if-->')
      }
    }
    expect(mount(OrgMarkWhy, { props: { orgId: 'org-1', listed: false } }).find('[data-testid="org-mark-why"]').exists(),
      'not told it may change it: nothing').toBe(false)
  })
})

describe('an old logo address is offered for upload', () => {
  // The review of V0658 (r): the image loaded by itself in every owner's and admin's browser, on every view of the page,
  // from whatever host logo_url names (an admin, or an agent with the owner authority, still writes it unchecked), while
  // the logo panel beside it says a viewer's browser calls no other site. That host is asked only after a press now.
  it('an https one is offered, not loaded: nothing asks its host until "Show the old image here"', () => {
    const w = why({ listed: true, logo: null, logoUrl: OLD })
    const row = w.find('[data-testid="org-mark-why-legacy"]')
    expect(row.text()).toContain('old.example')
    expect(w.find('[data-testid="org-mark-why-legacy-image"]').exists(), 'no image before the press').toBe(false)
    expect(w.findAll('img'), 'nothing on the notice asks another host by itself').toHaveLength(0)
    expect(w.find('[data-testid="org-mark-why-legacy-show"]').text()).toBe('Show the old image here')
    const open = w.find('[data-testid="org-mark-why-legacy-open"]')
    expect(open.attributes('href')).toBe(OLD)
    expect(open.attributes('target')).toBe('_blank')
    expect(open.attributes('rel')).toContain('noopener')
    expect(open.attributes('rel')).toContain('noreferrer')
    expect(w.find('[data-testid="org-mark-why-upload"]').exists(), 'the upload control is in the same notice').toBe(true)
  })

  it('after the press it is shown here, without a referrer, to save and upload', async () => {
    const w = why({ listed: true, logo: null, logoUrl: OLD })
    await w.find('[data-testid="org-mark-why-legacy-show"]').trigger('click')
    const img = w.find('[data-testid="org-mark-why-legacy-image"]')
    expect(img.attributes('src')).toBe(OLD)
    expect(img.attributes('referrerpolicy')).toBe('no-referrer')
    expect(img.attributes('alt')).toBe('Its old logo')
    expect(w.find('[data-testid="org-mark-why-legacy-show"]').exists(), 'pressed once').toBe(false)
    expect(w.find('[data-testid="org-mark-why-legacy-open"]').attributes('href')).toBe(OLD)
  })

  it('another old address is not loaded until it is pressed again', async () => {
    const w = why({ listed: true, logo: null, logoUrl: OLD })
    await w.find('[data-testid="org-mark-why-legacy-show"]').trigger('click')
    expect(w.find('[data-testid="org-mark-why-legacy-image"]').exists()).toBe(true)
    await w.setProps({ logoUrl: 'https://other.example/mark.png' })
    expect(w.find('[data-testid="org-mark-why-legacy-image"]').exists(), 'the new host is not asked by itself').toBe(false)
    expect(w.find('[data-testid="org-mark-why-legacy"]').text()).toContain('other.example')
    expect(w.find('[data-testid="org-mark-why-legacy-show"]').exists()).toBe(true)
  })

  it('an http one is not loaded here (the console allows https images only), only opened', () => {
    const w = why({ listed: false, logo: null, logoUrl: 'http://old.example/l.jpg' })
    expect(w.find('[data-testid="org-mark-why-legacy"]').exists()).toBe(true)
    expect(w.find('[data-testid="org-mark-why-legacy-show"]').exists(), 'nothing to show here').toBe(false)
    expect(w.find('[data-testid="org-mark-why-legacy-image"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-legacy-open"]').attributes('href')).toBe('http://old.example/l.jpg')
  })

  it('an image that does not load says so, and keeps the address to open', async () => {
    const w = why({ listed: true, logo: null, logoUrl: OLD })
    await w.find('[data-testid="org-mark-why-legacy-show"]').trigger('click')
    await w.find('[data-testid="org-mark-why-legacy-image"]').trigger('error')
    expect(w.find('[data-testid="org-mark-why-legacy-image"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-legacy-broken"]').text()).toContain('old.example')
    expect(w.find('[data-testid="org-mark-why-legacy-open"]').exists()).toBe(true)
  })

  it('nothing is offered once a logo is hosted, nor for an address that is not http(s)', () => {
    expect(why({ listed: false, logo: HOSTED, logoUrl: OLD }).find('[data-testid="org-mark-why-legacy"]').exists()).toBe(false)
    for (const logoUrl of ['javascript:alert(1)', 'logo.png', '', null]) {
      expect(why({ listed: true, logo: null, logoUrl }).find('[data-testid="org-mark-why-legacy"]').exists(), String(logoUrl))
        .toBe(false)
    }
  })
})

describe('the controls', () => {
  it('"List this organization publicly" lists it and tells the page', async () => {
    h.updateOrgSettings.mockResolvedValue({ org_id: 'org-1', settings: { public_listing: true } })
    const w = why({ listed: false, logo: null })
    await w.find('[data-testid="org-mark-why-list"]').trigger('click')
    await flushPromises()
    expect(h.updateOrgSettings).toHaveBeenCalledTimes(1)
    expect(h.updateOrgSettings).toHaveBeenCalledWith('org-1', { public_listing: true })
    expect(w.emitted('changed')).toEqual([[{ listed: true }]])
    expect(w.find('[data-testid="org-mark-why-error"]').exists()).toBe(false)
  })

  it('a refused listing shows the server\'s words and tells the page nothing', async () => {
    h.updateOrgSettings.mockRejectedValue(Object.assign(new Error('Insufficient permissions'), {
      status: 403, detail: 'Insufficient permissions' }))
    const w = why({ listed: false, logo: HOSTED })
    await w.find('[data-testid="org-mark-why-list"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="org-mark-why-error"]').text()).toBe('Insufficient permissions')
    expect(w.emitted('changed')).toBeUndefined()
    expect(w.find('[data-testid="org-mark-why-list"]').attributes('disabled'), 'it can be pressed again').toBeUndefined()
  })

  it('the upload sends a PNG or a JPEG of at most 256 KB, refuses others before sending, and tells the page', async () => {
    h.uploadLogo.mockResolvedValue({ org_id: 'org-1', logo: HOSTED, size: 10, content_type: 'image/png' })
    const w = why({ listed: true, logo: null, logoUrl: OLD })
    const input = w.find('[data-testid="org-mark-why-upload"]')
    const pick = async (file: File) => {
      Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
      await input.trigger('change')
      await flushPromises()
    }
    await pick(new File([new Uint8Array(300 * 1024)], 'big.png', { type: 'image/png' }))
    expect(w.find('[data-testid="org-mark-why-error"]').text()).toContain('256 KB')
    await pick(new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }))
    expect(w.find('[data-testid="org-mark-why-error"]').text()).toContain('PNG')
    expect(h.uploadLogo).not.toHaveBeenCalled()
    const ok = new File([new Uint8Array(10)], 'logo.png', { type: 'image/png' })
    await pick(ok)
    expect(h.uploadLogo).toHaveBeenCalledTimes(1)
    expect(h.uploadLogo).toHaveBeenCalledWith('org-1', ok)
    expect(w.emitted('changed')).toEqual([[{ logo: HOSTED }]])
    expect(w.find('[data-testid="org-mark-why-error"]').exists()).toBe(false)
  })

  it('in the settings, where the logo panel below holds the upload, it points there instead of a second control', () => {
    const w = why({ listed: false, logo: null, logoUrl: OLD, uploadHere: false })
    expect(w.find('[data-testid="org-mark-why-upload"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-mark-why-upload-below"]').text()).toContain('Upload a logo')
    expect(w.find('[data-testid="org-mark-why-list"]').exists(), 'the listing control stays').toBe(true)
    expect(w.find('[data-testid="org-mark-why-legacy-show"]').exists(), 'the old image is still offered').toBe(true)
  })
})

describe('its layout', () => {
  // The review of V0658 (r), measured in Chromium: `.omw__why { flex: 1 1 320px }` is a width beside the button in a row,
  // but the old logo's sentence also wears .omw__why inside .omw__legacy, a column, where the same basis is a HEIGHT: a
  // 14 px sentence in a 320 px box, its row 338 px tall, "Open the old image" 324 px down. happy-dom lays nothing out,
  // so this reads the rules and the markup they meet.
  const sfc = fs.readFileSync(path.join(__dirname, 'OrgMarkWhy.vue'), 'utf8')
  const css = (sfc.match(/<style[^>]*>([\s\S]*?)<\/style>/)?.[1] || '').replace(/\/\*[\s\S]*?\*\//g, '')
  const rules = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }))
  const declares = (body: string, prop: RegExp) => body.split(';').some((d) => prop.test(d.split(':')[0].trim()))

  it('a reason takes its width basis only as a row\'s own child; no rule gives the sentence a basis anywhere else', () => {
    const basis = /^flex(-basis|-grow)?$/
    const loose = rules.filter((r) => r.sel.split(',').some((s) => /\.omw__why\b/.test(s) && !/\.omw__row\s*>\s*\.omw__why$/.test(s.trim())))
    expect(loose.length, 'the reason has its own rule (colour, size)').toBeGreaterThan(0)
    for (const r of loose) expect(declares(r.body, basis), `${r.sel} sets no flex basis`).toBe(false)
    const row = rules.find((r) => /^\.omw__row\s*>\s*\.omw__why$/.test(r.sel))
    expect(row?.body, 'beside its button in a row, it takes the width').toMatch(/flex:\s*1 1 320px/)
    expect(rules.find((r) => r.sel === '.omw__legacy')?.body, 'the old logo\'s sentence sits in a column').toMatch(/flex-direction:\s*column/)
  })

  it('the listing and logo reasons are rows\' own children; the old logo\'s sentence is not (a guard)', () => {
    const w = why({ listed: false, logo: null, logoUrl: OLD })
    const parentOf = (sel: string) => (w.find(sel).element.parentElement as HTMLElement).className
    expect(parentOf('[data-testid="org-mark-why-listing"] > .omw__why')).toContain('omw__row')
    expect(parentOf('[data-testid="org-mark-why-logo"] > .omw__why')).toContain('omw__row')
    expect(parentOf('[data-testid="org-mark-why-legacy"] .omw__why')).toBe('omw__legacy')
  })
})

describe('its texts read at least 4.5:1 on the organization page (the console proof\'s a11y check)', () => {
  type RGB = [number, number, number]
  type Paint = { rgb: RGB; a: number }
  const css = fs.readFileSync(path.join(__dirname, 'OrgMarkWhy.vue'), 'utf8')
  /** the value a rule declares for a property (its first), as RGB and alpha */
  function declared(selector: string, prop: 'color' | 'background'): Paint | null {
    const at = css.indexOf(`${selector} {`)
    if (at < 0) return null
    const block = css.slice(at, css.indexOf('}', at))
    const m = block.match(new RegExp(`(?:^|[\\s;{])${prop}:\\s*([^;]+);`))
    if (!m) return null
    const v = m[1].trim()
    const hex = v.match(/^#([0-9a-f]{6})$/i)
    if (hex) return { rgb: [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16)) as RGB, a: 1 }
    const rgba = v.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/)
    if (rgba) return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: rgba[4] === undefined ? 1 : Number(rgba[4]) }
    throw new Error(`a colour this test does not read: ${v}`)
  }
  const hexRgb = (x: string): RGB => [0, 2, 4].map((i) => parseInt(x.slice(1 + i, 3 + i), 16)) as RGB
  const over = (fg: Paint, bg: RGB): RGB => fg.rgb.map((c, i) => Math.round(fg.a * c + (1 - fg.a) * bg[i])) as RGB
  const lum = ([r, g, b]: RGB) => {
    const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 }
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
  }
  const ratio = (a: RGB, b: RGB) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }

  // the identity panel and the tab panel are #0d1626; axe measured #141d2d under the settings' logo controls
  for (const page of ['#0d1626', '#141d2d']) {
    it(`each text, over the notice's own background on ${page}`, () => {
      const panel = declared('.omw', 'background')
      const under = panel ? over(panel, hexRgb(page)) : hexRgb(page)
      for (const sel of ['.omw__title', '.omw__why', '.omw__hint', '.omw__link', '.omw__err']) {
        const fg = declared(sel, 'color')
        expect(fg, `${sel} declares its colour`).not.toBeNull()
        expect(ratio(over(fg!, under), under), sel).toBeGreaterThanOrEqual(4.5)
      }
      const btnBg = declared('.omw__btn', 'background')
      const btnUnder = btnBg ? over(btnBg, under) : under
      const btn = declared('.omw__btn', 'color')
      expect(btn, '.omw__btn declares its colour').not.toBeNull()
      expect(ratio(over(btn!, btnUnder), btnUnder), '.omw__btn').toBeGreaterThanOrEqual(4.5)
    })
  }
})
