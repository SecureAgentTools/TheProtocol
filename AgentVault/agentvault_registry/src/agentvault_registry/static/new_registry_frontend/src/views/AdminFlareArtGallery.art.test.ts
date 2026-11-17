// V0665: every piece of artwork in the review gallery is an image with a name, and what is drawn inside it is hidden from the checker and from a screen reader
// (session-lead seq 4967, after the console proof's color-contrast finding on /admin/flare-art). The captions beside the art stay real text.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AdminFlareArtGallery from './AdminFlareArtGallery.vue'

const art = ['EarnedRing', 'EarnedBadge', 'TitleEmblem', 'CommanderPlate', 'FlareEncirclement', 'FlareBadge']
const stubs = Object.fromEntries(art.map((n) => [n, { template: `<i data-art="${n}">drawn text</i>` }]))

describe('the art gallery', () => {
  const w = mount(AdminFlareArtGallery, { global: { stubs } })
  const arts = w.findAll('[data-art]')

  it('draws a good amount of art, and every piece sits inside a named image', () => {
    expect(arts.length).toBeGreaterThan(100)
    for (const a of arts) {
      const host = a.element.closest('[role="img"]')
      expect(host, `${a.attributes('data-art')} has no image around it`).not.toBeNull()
      expect((host!.getAttribute('aria-label') || '').trim().length, 'the image has a name').toBeGreaterThan(3)
    }
  })

  it('hides what is drawn inside the image', () => {
    for (const a of arts) expect(a.element.closest('[aria-hidden="true"]'), a.attributes('data-art')).not.toBeNull()
  })

  it('names the sample avatars and cards as images too, and keeps the section captions as plain text', () => {
    const labels = w.findAll('[role="img"]').map((e) => e.attributes('aria-label') || '')
    expect(labels.some((l) => /Sidebar sample/.test(l)) && labels.some((l) => /Profile card sample/.test(l))).toBe(true)
    for (const cap of w.findAll('.fag-cap, .fag-cap2, .fag-tag')) expect(cap.element.closest('[aria-hidden="true"]')).toBeNull()
  })

  it('names the Eye Sees All option B samples as well', () => {
    const b = w.find('[data-testid="fag-title-the-eye-sees-all-b"]')
    expect(b.findAll('[role="img"]').length).toBe(6)                   // 3 samples on each of the 2 themes
  })
})
