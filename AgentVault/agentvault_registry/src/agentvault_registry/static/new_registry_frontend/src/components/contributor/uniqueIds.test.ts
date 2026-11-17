/**
 * V0665: every instance of the art's SVG components gets ids of its own. The id counter lives at module scope, not inside <script setup> (where it restarted at 0 for each instance
 * and two instances on one page shared every gradient id: url(#id) then points into the first instance's defs).
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EarnedBadge from './EarnedBadge.vue'
import EarnedRing from './EarnedRing.vue'

const ids = (w: any): string[] => [...w.element.querySelectorAll('[id]')].map((e: Element) => e.id)

describe('the art components number their ids once for the page', () => {
  it('two badges share no id', () => {
    const a = ids(mount(EarnedBadge, { props: { badgeKey: 'initiate' } })), b = ids(mount(EarnedBadge, { props: { badgeKey: 'initiate' } }))
    expect(a.length).toBeGreaterThan(0)
    expect(a.filter((x) => b.includes(x))).toEqual([])
  })
  it('two rings share no id', () => {
    const a = ids(mount(EarnedRing, { props: { ringKey: 'ember', initials: 'AL' } })), b = ids(mount(EarnedRing, { props: { ringKey: 'ember', initials: 'AL' } }))
    expect(a.length).toBeGreaterThan(0)
    expect(a.filter((x) => b.includes(x))).toEqual([])
  })
})
