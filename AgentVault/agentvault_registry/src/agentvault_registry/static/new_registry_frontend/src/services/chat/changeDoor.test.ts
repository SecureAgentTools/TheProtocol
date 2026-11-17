/**
 * V0666 D3 (order gwo_542285271416c653ca39af3f): what /change <title> does in a conversation. In an organization's room it
 * opens the Code changes proposal prefilled for that organization's release line (the only active one, or a picker when it
 * has several), announced in this room; with none, or with code distributions off, or outside an organization's room, one
 * sentence says why and nothing opens. Red before D3: services/chat/changeDoor.ts does not exist.
 */
import { describe, expect, it } from 'vitest'
import { changeDoor, splitContent } from './changeDoor'

const tr = (_k: string, f: string, p?: Record<string, unknown>) => (p ? f.replace(/\{(\w+)\}/g, (_, k) => String(p[k])) : f)
const L = (slug: string, state = 'active') => ({ slug, title: `Line ${slug}`, release_name: `V0666_${slug}`, state })
const base = { enabled: true, orgId: 'org-a', convId: 'room-1', title: 'A seating chart' }

describe('/change in a conversation', () => {
  it('says code distributions are off, and opens nothing', () => {
    expect(changeDoor({ ...base, enabled: false, lines: [L('a')] }, tr)).toEqual({ kind: 'refuse', sentence: 'Code distributions are off on this registry.' })
  })
  it('outside an organization\'s room says where it works', () => {
    const d = changeDoor({ ...base, orgId: '', lines: [] }, tr)
    expect(d.kind).toBe('refuse')
    expect((d as any).sentence).toBe('/change works in a room of an organization: it proposes a change to that organization\'s release line.')
  })
  it('an organization with no line says so, and who creates one', () => {
    expect((changeDoor({ ...base, lines: [] }, tr) as any).sentence).toMatch(/has no release line yet; its owners and admins create one under Contributions/)
  })
  it('an organization whose every line is paused says so', () => {
    expect((changeDoor({ ...base, lines: [L('a', 'paused')] }, tr) as any).sentence).toMatch(/Every release line .* is paused/)
  })
  it('opens the proposal for the only active line, with the title and this room', () => {
    expect(changeDoor({ ...base, lines: [L('a'), L('b', 'paused')] }, tr)).toEqual({ kind: 'go',
      to: { name: 'code-changes-new', query: { line: 'a', room: 'room-1', title: 'A seating chart' } } })
    const noTitle = changeDoor({ ...base, title: '  ', lines: [L('a')] }, tr) as any
    expect(noTitle.to.query).toEqual({ line: 'a', room: 'room-1' })
  })
  it('offers a picker when the organization has several active lines', () => {
    const d = changeDoor({ ...base, lines: [L('a'), L('b')] }, tr) as any
    expect(d.kind).toBe('pick')
    expect(d.lines.map((x: any) => x.slug)).toEqual(['a', 'b'])
    expect(d.to('b')).toEqual({ name: 'code-changes-new', query: { line: 'b', room: 'room-1', title: 'A seating chart' } })
  })
  it('V0667 D5: "/change content <title>" opens the content proposal for the line, with the rest as its title; anything else is the code door as before', () => {
    expect(changeDoor({ ...base, title: 'content Quiet releases', lines: [L('a')] }, tr)).toEqual({ kind: 'go',
      to: { name: 'content-changes-new', query: { line: 'a', room: 'room-1', title: 'Quiet releases' } } })
    expect(changeDoor({ ...base, title: 'content', lines: [L('a')] }, tr)).toEqual({ kind: 'go', to: { name: 'content-changes-new', query: { line: 'a', room: 'room-1' } } })
    expect(changeDoor({ ...base, title: 'contention at the door', lines: [L('a')] }, tr)).toEqual({ kind: 'go', to: { name: 'code-changes-new', query: { line: 'a', room: 'room-1', title: 'contention at the door' } } })
    expect(splitContent('Content  a b')).toEqual({ content: true, title: 'a b' })
  })
})
