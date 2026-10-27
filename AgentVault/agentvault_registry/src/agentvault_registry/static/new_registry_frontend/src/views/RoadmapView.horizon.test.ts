import { describe, it, expect } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import RoadmapView from './RoadmapView.vue'

// §SUITES1018 (2026-10-19), his word: code changes do not run through the network yet, only its policy; the idea
// that they will sits on the Horizon, marked Idea, neither designed nor scheduled. Rendered, not read as source.
describe('roadmap horizon', () => {
  it('shows two entries on the horizon, the second marked Idea, and Idea in the status key', () => {
    const w = mount(RoadmapView, { global: { components: { RouterLink: RouterLinkStub } } })
    const horizon = w.findAll('.rm-horizon').find(h => h.find('.rm-horizon-label').text() === 'HORIZON')
    expect(horizon).toBeTruthy()
    const streams = horizon!.findAll('.rm-stream')
    expect(streams.map(s => s.find('.rm-h3').text())).toEqual([
      'A network that survives quantum computers',
      'The network decides its own code',
    ])
    expect(streams[1].find('.rm-stream-status').text()).toBe('Idea')
    expect(streams[1].find('.rm-glyph--idea').exists()).toBe(true)
    expect(streams[0].find('.rm-stream-status').text()).toBe('Planned')
    expect(w.findAll('.rm-key-item').map(k => k.text())).toEqual(['Live', 'In preparation', 'Designed', 'Planned', 'Idea'])
    w.unmount()
  })
})
