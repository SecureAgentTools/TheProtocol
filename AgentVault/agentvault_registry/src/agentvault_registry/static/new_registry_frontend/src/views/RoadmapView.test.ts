import { describe, it, expect } from 'vitest'
import roadmap from './RoadmapView.vue?raw'
import paper from '@/assets/docs/whitepaper/accountable-quantum-compute.md?raw'
import whitepaperView from './WhitepaperView.vue?raw'
import router from '@/router/index.ts?raw'

// Words a public page of ours never uses, and the dash we never print.
const BANNED = /\b(earn\w*|rewards?|yield\w*|returns|dividends?|shares|stak(e|es|ed|ing)|invest\w*|profit\w*|bank\w*|stocks?|IPO|moat)\b/i

describe('roadmap page', () => {
  it('is a public route', () => {
    expect(router).toMatch(/path: '\/roadmap',[\s\S]{0,160}requiresAuth: false/)
  })
  it('links the new whitepaper, the 2025 original, compliance and blueprints', () => {
    for (const to of ['/whitepaper/quantum', '/compliance', '/blueprints']) expect(roadmap).toContain(`to: '${to}'`)
    expect(roadmap).toContain('to="/docs"')
    expect(roadmap).toContain("@/assets/papers/quantum-classical-interface-2025.pdf?url")
  })
  it('no longer shows the legacy platform whitepaper', () => {
    expect(whitepaperView).not.toContain('v2-draft.md')
    expect(roadmap).not.toContain("'/whitepaper'")
  })
  it('signs the note without a founder title and draws its own marks', () => {
    expect(roadmap).not.toMatch(/founder/i)
    expect(roadmap).not.toContain('mdi:')
  })
  it('puts code the network decides on the horizon as an idea, not as a plan', () => {
    // His word 2026-10-19: code changes do not run through the protocol yet, only its policy; the idea is
    // neither designed nor scheduled, so the page says Idea and nothing stronger.
    expect(roadmap).toContain("{ key: 'idea', label: 'Idea' }")
    expect(roadmap).toMatch(/title: 'The network decides its own code',\s*status: 'idea',/)
    expect(roadmap).toContain('.rm-glyph--idea .rm-glyph-ring')
  })
  it('keeps the public word list and no em dashes', () => {
    for (const text of [roadmap, paper]) {
      expect(text).not.toMatch(BANNED)
      expect(text).not.toContain('—')
    }
  })
})
