/**
 * §COCKPITDESK (2026-10-15) SECURITY — the theatre's log lines are HTML (v-html) and carry names someone else chose (an
 * agent's name, a registry's, a path's, a server's error text). Every value interpolated into a pushLog line goes through
 * esc(), and a concatenated server message too: an agent named <img src=x onerror=…> stays text.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = fs.readFileSync(path.resolve(__dirname, 'IronhandTheatre.vue'), 'utf8')

describe("the theatre's log lines", () => {
  it('escape every interpolated value', () => {
    const calls = [...SRC.matchAll(/pushLog\(\s*'[^']*'\s*,\s*`([^`]*)`/g)].map((m) => m[1])
    expect(calls.length, 'the log lines are found').toBeGreaterThan(10)
    const raw = calls.flatMap((c) => [...c.matchAll(/\$\{(?!esc\()([^}]*)\}/g)].map((m) => m[1]))
    expect(raw).toEqual([])
  })

  it('escape a concatenated server message', () => {
    const concat = [...SRC.matchAll(/pushLog\(\s*'[^']*'\s*,\s*'[^']*'\s*\+\s*([^,]+),/g)].map((m) => m[1].trim())
    expect(concat.length).toBeGreaterThan(0)
    expect(concat.filter((c) => !c.startsWith('esc('))).toEqual([])
  })
})
