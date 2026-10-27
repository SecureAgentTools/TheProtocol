import { slugify } from '@/composables/docs/useDocsMarkdown'

// The paper's own "# " title repeats the page hero's h1: the article drops
// it, so the page carries one h1.
export function paperArticle(body: string): string {
  return body.replace(/^\s*# [^\n]*\n/, '')
}

export interface PaperSection {
  id: string
  num: string
  label: string
}

// The contents list: every "## " section but the abstract. A numbered
// heading ("1. The problem") shows its number once, in the number column;
// the anchor id stays the whole heading's, as the renderer writes it.
export function paperContents(body: string): PaperSection[] {
  const sections: PaperSection[] = []
  for (const line of body.split('\n')) {
    const m = line.match(/^## (.+)$/)
    if (!m) continue
    const label = m[1].trim()
    if (!label || label === 'Abstract') continue
    const numbered = label.match(/^(\d+)\.\s+(.+)$/)
    sections.push({
      id: slugify(label),
      num: numbered ? numbered[1].padStart(2, '0') : '',
      label: numbered ? numbered[2] : label,
    })
  }
  return sections
}
