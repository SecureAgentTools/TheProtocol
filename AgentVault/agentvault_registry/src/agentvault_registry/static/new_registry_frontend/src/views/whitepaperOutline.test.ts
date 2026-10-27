import { describe, it, expect } from 'vitest'
import { renderDocsMarkdown, stripFrontmatter } from '@/composables/docs/useDocsMarkdown'
import paper from '@/assets/docs/whitepaper/accountable-quantum-compute.md?raw'
import { paperArticle, paperContents } from './whitepaperOutline'

const body = stripFrontmatter(paper)
const render = (md: string) => renderDocsMarkdown(md, { classPrefix: 'wp', headingAnchors: true })

describe('whitepaper outline', () => {
  it('renders the article without the title the hero already shows', () => {
    expect(render(body)).toMatch(/<h1[\s>]/)
    expect(render(paperArticle(body))).not.toMatch(/<h1[\s>]/)
  })
  it('numbers each contents entry once', () => {
    const toc = paperContents(body)
    expect(toc[0]).toMatchObject({ num: '01', label: 'The problem' })
    for (const s of toc) expect(s.label).not.toMatch(/^\d+\./)
    expect(toc.find((s) => s.label === 'References')?.num).toBe('')
  })
  it('points every entry at a heading the article renders', () => {
    const html = render(paperArticle(body))
    const toc = paperContents(body)
    expect(toc.length).toBeGreaterThan(10)
    for (const s of toc) expect(html).toContain(`id="${s.id}"`)
  })
})
