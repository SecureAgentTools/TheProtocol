import { describe, it, expect } from 'vitest'
import { ACCEPT, MAX_FILE_BYTES, MAX_STAGED, classify, filesOf, humanSize, mimeOf } from './attachments'

/** V0662 (OurChat lane): what may be staged from a paste or a drop. BASE (528899987): attachments.ts does not exist and the
 *  composer takes no file. The rules follow the registry's (chat_media.py: five MB, ALLOWED_MIME; SVG refused because it
 *  can carry script). */
const f = (name: string, type: string, size = 100) => ({ name, type, size })

describe('the type a file goes up as', () => {
  it('is the browser\'s when the registry takes it', () => {
    expect(mimeOf(f('shot.png', 'image/png'))).toBe('image/png')
    expect(mimeOf(f('doc.pdf', 'application/pdf'))).toBe('application/pdf')
    expect(mimeOf(f('notes.txt', 'text/plain'))).toBe('text/plain')
  })

  it('drops a charset parameter and the case, for a file whose name says nothing (a clipboard file has none)', () => {
    expect(mimeOf(f('clipboard', 'Text/Plain; charset=utf-8'))).toBe('text/plain')
    expect(mimeOf(f('clipboard', 'IMAGE/PNG'))).toBe('image/png')
  })

  it('reads the name when the browser gives no type, as it does for markdown', () => {
    expect(mimeOf(f('plan.md', ''))).toBe('text/markdown')
    expect(mimeOf(f('plan.MD', ''))).toBe('text/markdown')
    expect(mimeOf(f('run.log', ''))).toBe('text/plain')
    expect(mimeOf(f('data.json', 'application/octet-stream'))).toBe('application/json')
  })

  it('takes the older aliases for the current names', () => {
    expect(mimeOf(f('a.md', 'text/x-markdown'))).toBe('text/markdown')
    expect(mimeOf(f('a.jpg', 'image/jpg'))).toBe('image/jpeg')
  })

  it('is empty for a type the registry does not take, whatever the name says', () => {
    expect(mimeOf(f('logo.svg', 'image/svg+xml'))).toBe('')
    expect(mimeOf(f('run.exe', 'application/x-msdownload'))).toBe('')
    expect(mimeOf(f('README', ''))).toBe('')
    expect(mimeOf(f('archive.zip', ''))).toBe('')
  })

  it('does not take a bare name for an extension', () => {
    expect(mimeOf(f('png', ''))).toBe('')
  })
})

describe('what may be staged', () => {
  it('accepts an image, a PDF and a text file, and says what kind each is', () => {
    expect(classify(f('a.png', 'image/png'), 0)).toEqual({ ok: true, mime: 'image/png', kind: 'image' })
    expect(classify(f('a.pdf', 'application/pdf'), 0)).toEqual({ ok: true, mime: 'application/pdf', kind: 'pdf' })
    expect(classify(f('a.md', ''), 0)).toEqual({ ok: true, mime: 'text/markdown', kind: 'text' })
  })

  it('holds the registry\'s size cap exactly: five MB passes, one byte more does not', () => {
    expect(classify(f('a.png', 'image/png', MAX_FILE_BYTES), 0).ok).toBe(true)
    expect(classify(f('a.png', 'image/png', MAX_FILE_BYTES + 1), 0)).toEqual({ ok: false, reason: 'too_big' })
  })

  it('refuses an empty file', () => {
    expect(classify(f('a.txt', 'text/plain', 0), 0)).toEqual({ ok: false, reason: 'empty' })
  })

  it('refuses SVG and anything else the registry does not take', () => {
    expect(classify(f('a.svg', 'image/svg+xml'), 0)).toEqual({ ok: false, reason: 'type' })
    expect(classify(f('a.zip', 'application/zip'), 0)).toEqual({ ok: false, reason: 'type' })
  })

  it('stops at five staged files', () => {
    expect(classify(f('a.png', 'image/png'), MAX_STAGED - 1).ok).toBe(true)
    expect(classify(f('a.png', 'image/png'), MAX_STAGED)).toEqual({ ok: false, reason: 'too_many' })
  })

  it('says "too many" before it says anything about the file', () => {
    expect(classify(f('a.zip', 'application/zip', 0), MAX_STAGED)).toEqual({ ok: false, reason: 'too_many' })
  })
})

describe('a size a person reads', () => {
  it('writes bytes, kilobytes and megabytes', () => {
    expect(humanSize(0)).toBe('0 B')
    expect(humanSize(412)).toBe('412 B')
    expect(humanSize(1536)).toBe('1.5 KB')
    expect(humanSize(52 * 1024)).toBe('52 KB')
    expect(humanSize(1.4 * 1024 * 1024)).toBe('1.4 MB')
  })

  it('writes nothing for a size that is not one', () => {
    expect(humanSize(NaN)).toBe('')
    expect(humanSize(-1)).toBe('')
  })
})

describe('the files a paste or a drop carries', () => {
  const file = (n: string) => new File(['x'], n, { type: 'text/plain' })

  it('is the files list when it has one', () => {
    expect(filesOf({ files: [file('a.txt'), file('b.txt')] }).map((x) => x.name)).toEqual(['a.txt', 'b.txt'])
  })

  it('falls back to file items, as a clipboard with an image gives them', () => {
    const items = [{ kind: 'string' }, { kind: 'file', getAsFile: () => file('shot.png') }, { kind: 'file', getAsFile: () => null }]
    expect(filesOf({ files: [], items }).map((x) => x.name)).toEqual(['shot.png'])
  })

  it('is empty for plain text, so a paste of words is left alone', () => {
    expect(filesOf({ files: [], items: [{ kind: 'string' }] })).toEqual([])
    expect(filesOf(null)).toEqual([])
    expect(filesOf(undefined)).toEqual([])
    expect(filesOf({})).toEqual([])
  })
})

describe('what the file chooser offers', () => {
  const offered = ACCEPT.split(',')

  it('lists the extensions and the types the staging takes', () => {
    for (const x of ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.txt', '.md', '.json', '.csv', 'image/png', 'application/pdf', 'text/markdown']) {
      expect(offered).toContain(x)
    }
  })

  it('does not offer SVG or anything else the staging refuses', () => {
    expect(ACCEPT).not.toMatch(/svg|zip|exe/i)
  })

  it('offers nothing the staging itself would refuse: every offered extension is accepted', () => {
    for (const ext of offered.filter((o) => o.startsWith('.'))) {
      expect(classify({ name: `file${ext}`, type: '', size: 10 }, 0).ok).toBe(true)
    }
    for (const mime of offered.filter((o) => !o.startsWith('.'))) {
      expect(classify({ name: 'file', type: mime, size: 10 }, 0).ok).toBe(true)
    }
  })
})
