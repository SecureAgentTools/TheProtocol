import { describe, expect, it } from 'vitest'
import { firstTimeThisSession } from './oncePerSession'

function memoryStore(): Storage {
  const m = new Map<string, string>()
  return {
    get length() { return m.size },
    clear: () => m.clear(),
    getItem: (k: string) => (m.has(k) ? (m.get(k) as string) : null),
    key: (i: number) => [...m.keys()][i] ?? null,
    removeItem: (k: string) => { m.delete(k) },
    setItem: (k: string, v: string) => { m.set(k, v) },
  }
}

describe('a notice once per browser session', () => {
  it('says yes the first time and no after, per key', () => {
    const s = memoryStore()
    expect(firstTimeThisSession('a', s)).toBe(true)
    expect(firstTimeThisSession('a', s)).toBe(false)
    expect(firstTimeThisSession('a', s)).toBe(false)
    expect(firstTimeThisSession('b', s)).toBe(true)
  })

  it('says yes when storage is missing or refuses (shown twice beats never shown)', () => {
    expect(firstTimeThisSession('a', null)).toBe(true)
    const refusing = { ...memoryStore(), getItem: () => { throw new Error('blocked') } } as unknown as Storage
    expect(firstTimeThisSession('a', refusing)).toBe(true)
    expect(firstTimeThisSession('a', refusing)).toBe(true)
  })

  it('uses the real sessionStorage by default', () => {
    window.sessionStorage.removeItem('once-test')
    expect(firstTimeThisSession('once-test')).toBe(true)
    expect(firstTimeThisSession('once-test')).toBe(false)
    window.sessionStorage.removeItem('once-test')
  })
})
