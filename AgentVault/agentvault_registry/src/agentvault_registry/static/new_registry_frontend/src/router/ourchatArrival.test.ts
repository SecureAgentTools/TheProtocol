import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** The pocket thread route asks the landing decision on a page's first arrival (services/uiMode.arrivesInDesk) and hands a wide
 *  window to the desk thread, the message (`?m=`) and the rest of the query kept. The route's path and name do not change: push
 *  notifications, handle QRs and every link in the wild still resolve. */
const src = readFileSync(resolve(__dirname, 'index.ts'), 'utf8')

describe('the pocket thread route', () => {
  it('keeps its path and name and asks the arrival rule', () => {
    const i = src.indexOf("name: 'pocket-ourchat-thread'")
    expect(i).toBeGreaterThan(-1)
    const line = src.slice(src.lastIndexOf('\n', i), src.indexOf('\n', i))
    expect(line).toContain("path: ':id'")
    expect(line).toMatch(/beforeEnter/)
    expect(line).toContain('arrivesInDesk')
  })
  it('hands the desk thread the same id and query', () => {
    const i = src.indexOf('arrivesInDesk(')
    const block = src.slice(i - 400, i + 400)
    expect(block).toContain("name: 'desk-ourchat-thread'")
    expect(block).toMatch(/query: to\.query/)
  })
})
