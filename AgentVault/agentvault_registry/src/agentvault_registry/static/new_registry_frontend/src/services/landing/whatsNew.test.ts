// V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4424 via session-lead seq 4430): a "What's new" strip on the landing
// page, read from the docs' release notes (chapter 38, newest release first): that release's member lines, their bold
// lead-ins and first sentences, a few of them, never a line with a value word.
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { parseWhatsNew } from './whatsNew'

const MD = `# Release Notes

*intro*

## V0700

**For members**

- **Mentions you cannot miss.** The thread marks the line that names you. A second sentence. ([OurChat](/docs/34#rooms))
- **Locks that pay out.** Stake a little and earn a lot. ([Economy](/docs/02))
- **Compare two agent cards.** Two cards side by side with every difference marked, from an agent's page or at \`#/cards/compare\`.
- **Workflows.** An agent can lay out several Guild orders as one run.
- **Empty lists say why.** Discovery names the filters that made it empty.
- **A fifth.** Not shown.

**For operators**

- **Chat Delivery.** Operator only.

## V0699

**For members**

- **Older.** Not this release.
`

describe('What\'s new, from the release notes', () => {
  it('the newest release, its member lines: the lead-in and its first sentence, at most four, none with a value word', () => {
    const out = parseWhatsNew(MD, 4)
    expect(out.version).toBe('V0700')
    expect(out.items.map((i) => i.title)).toEqual(['Mentions you cannot miss', 'Compare two agent cards', 'Workflows', 'Empty lists say why'])
    expect(out.items[0]!.line).toBe('The thread marks the line that names you.')
    expect(out.items[1]!.line).toBe('Two cards side by side with every difference marked, from an agent\'s page or at #/cards/compare.')
  })

  it('nothing to say when the notes hold no release or no member lines', () => {
    expect(parseWhatsNew('# Release Notes\n\nnothing yet', 4)).toEqual({ version: '', items: [] })
    expect(parseWhatsNew('## V0701\n\n**For operators**\n\n- **X.** y.', 4).items).toEqual([])
  })

  it('reads the real chapter: a release name and at least three lines', () => {
    const md = fs.readFileSync(path.resolve(__dirname, '../../assets/docs/oracle/38_release_notes.md'), 'utf8')
    const out = parseWhatsNew(md, 4)
    expect(out.version).toMatch(/^V\d{4}$/)
    expect(out.items.length).toBeGreaterThanOrEqual(3)
    for (const i of out.items) expect(i.line).not.toMatch(/\]\(|\`/)
  })
})
