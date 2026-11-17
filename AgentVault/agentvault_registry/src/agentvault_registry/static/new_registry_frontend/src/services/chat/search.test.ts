import { describe, it, expect } from 'vitest'
import { SEARCH_MAX, loadedReaches, searchQuery, snippetParts } from './search'

/** V0662 (OurChat lane): search in a thread, the console's rules. BASE (c42be1743): the module does not exist. */

describe('the query worth sending', () => {
  it('is the trimmed text, from two characters up to a hundred', () => {
    expect(searchQuery('  release ')).toBe('release')
    expect(searchQuery('ab')).toBe('ab')
    expect(searchQuery('x'.repeat(SEARCH_MAX))).toHaveLength(SEARCH_MAX)
  })
  it('is none when too short, too long or empty', () => {
    expect(searchQuery('a')).toBeNull()
    expect(searchQuery('  a  ')).toBeNull()
    expect(searchQuery('')).toBeNull()
    expect(searchQuery(undefined)).toBeNull()
    expect(searchQuery('x'.repeat(SEARCH_MAX + 1))).toBeNull()
  })
})

describe('what is shown of a hit', () => {
  it('marks the first match, ignoring case, and keeps the words around it', () => {
    expect(snippetParts('The Release train leaves', 'release')).toEqual([
      { text: 'The ', hit: false }, { text: 'Release', hit: true }, { text: ' train leaves', hit: false }])
  })
  it('cuts a long line to a stretch around the match with ellipses', () => {
    const body = `${'a'.repeat(100)} needle ${'b'.repeat(100)}`
    const parts = snippetParts(body, 'needle', 10)
    expect(parts.map((p) => p.text).join('')).toBe(`…${'a'.repeat(9)} needle ${'b'.repeat(9)}…`)
    expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(['needle'])
  })
  it('a match at the start or the end has no empty parts', () => {
    expect(snippetParts('needle here', 'needle')).toEqual([{ text: 'needle', hit: true }, { text: ' here', hit: false }])
    expect(snippetParts('look: needle', 'needle')).toEqual([{ text: 'look: ', hit: false }, { text: 'needle', hit: true }])
    expect(snippetParts('needle', 'needle')).toEqual([{ text: 'needle', hit: true }])
  })
  it('collapses runs of whitespace and line breaks to one space', () => {
    expect(snippetParts('one\n\n  two   needle', 'needle').map((p) => p.text).join('')).toBe('one two needle')
  })
  it('shows the start of the line when nothing matches as typed (never throws)', () => {
    expect(snippetParts('hello world', 'zzz')).toEqual([{ text: 'hello world', hit: false }])
    expect(snippetParts('x'.repeat(500), 'zzz', 10)[0].text).toBe(`${'x'.repeat(20)}…`)
    expect(snippetParts(null, 'q')).toEqual([])
    expect(snippetParts('text', undefined)).toEqual([{ text: 'text', hit: false }])
  })
  it('keeps markup as text: a line\'s words never become HTML', () => {
    const parts = snippetParts('<img src=x onerror=1> needle', 'needle')
    expect(parts[0].text).toBe('<img src=x onerror=1> ')
    expect(parts[0].hit).toBe(false)
  })
})

describe('whether the loaded messages reach a seq', () => {
  it('is true when the oldest loaded is at or below it', () => {
    expect(loadedReaches([{ seq: 5 }, { seq: 6 }], 5)).toBe(true)
    expect(loadedReaches([{ seq: 5 }, { seq: 6 }], 6)).toBe(true)
    expect(loadedReaches([{ seq: 5 }], 4)).toBe(false)
    expect(loadedReaches([], 1)).toBe(false)
  })
})
