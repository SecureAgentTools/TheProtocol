import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** V0663 (browser pass, seq 3591), what the emulation reproduced (a 393 px phone with the viewport shrunk to 520 px, six lines
 *  typed): the banner, the app header, a room name wrapped to three lines and the members row left the thread 20 px, and the
 *  Pocket bar cut the send button. In a short window the room name is one line, the members row folds away and the bar leaves
 *  while the composer has the focus. The hosting line stays: it is the visibility law, never hidden. A real phone must confirm. */
const thread = readFileSync(resolve(__dirname, 'PocketOurStateThread.vue'), 'utf8')
const shell = readFileSync(resolve(__dirname, 'PocketShell.vue'), 'utf8')
const mediaBlock = (src: string) => {
  const i = src.indexOf('@media (max-height: 560px)')
  expect(i, 'a short-window block').toBeGreaterThan(-1)
  let depth = 0
  for (let j = src.indexOf('{', i); j < src.length; j++) {
    if (src[j] === '{') depth++
    if (src[j] === '}' && --depth === 0) return src.slice(i, j + 1)
  }
  return ''
}

describe('a short window (a keyboard open)', () => {
  it('keeps the room name on one line', () => {
    const b = mediaBlock(thread)
    expect(b).toMatch(/\.ost-room-title\s*\{[^}]*white-space: nowrap[^}]*text-overflow: ellipsis/s)
  })
  it('folds the room panel away and never touches the hosting line', () => {
    const b = mediaBlock(thread)
    expect(b).toMatch(/\.rp-head\)?\s*\{[^}]*display: none/s)
    expect(b).not.toMatch(/\.ost-hosting\s*\{[^}]*display: none/s)
  })
  it('takes the Pocket bar away while the composer has the focus', () => {
    const b = mediaBlock(shell)
    expect(b).toMatch(/\.ost-input:focus/)
    expect(b).toMatch(/\.pk-bar\s*\{[^}]*display: none/s)
  })
})
