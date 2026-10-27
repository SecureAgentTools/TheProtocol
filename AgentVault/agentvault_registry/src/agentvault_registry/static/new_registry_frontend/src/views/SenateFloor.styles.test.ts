import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { fedStatusPill } from '@/services/governance/federationBallots'

/**
 * §MCPTEST30 (V0558): the federation tab's cards wore thirteen class names the stylesheet never defined and five colour
 * variables nothing defined, so a card's head read "#FEDVotingfederation_policy_change" and its tiles had no accent.
 * Nothing errors for either: an unknown class styles nothing and an unknown var() paints nothing. These tests hold
 * every class the template names, and every colour it reads, to a definition in the view.
 */
const src = fs.readFileSync(path.resolve(__dirname, 'SenateFloor.vue'), 'utf8')
const template = src.slice(src.indexOf('<template'), src.indexOf('<script'))
const style = [...src.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join('\n')
const hasRule = (cls: string) => new RegExp('\\.' + cls.replace(/[-_]/g, (c) => '\\' + c) + '(?![A-Za-z0-9_-])').test(style)

describe('the Senate floor names only what it styles', () => {
  it('every sn- class in the template has a rule in the view', () => {
    const names = new Set<string>()
    for (const m of template.matchAll(/\bclass="([^"]+)"/g)) m[1].split(/\s+/).filter((c) => c.startsWith('sn-')).forEach((c) => names.add(c))
    for (const m of template.matchAll(/'(sn-[a-z0-9_-]+)'/g)) if (!m[1].endsWith('--')) names.add(m[1])
    expect(names.size).toBeGreaterThan(100)
    expect([...names].filter((c) => !hasRule(c))).toEqual([])
  })

  it('every colour variable the view reads is defined in it, or is a theme token', () => {
    const used = new Set([...src.matchAll(/var\(--([a-z0-9-]+)/g)].map((m) => m[1]))
    const defined = new Set([...style.matchAll(/(?:^|[\s;{])--([a-z0-9-]+)\s*:/g)].map((m) => m[1]))
    expect(used.size).toBeGreaterThan(5)
    expect([...used].filter((v) => !v.startsWith('nc-') && !defined.has(v))).toEqual([])
  })

  it("a federation proposal's status pill is one the view styles, for every status the store knows", () => {
    for (const s of ['VOTING', 'PASSED', 'APPLIED', 'FAILED', 'VETOED', 'SOMETHING_NEW', '']) {
      expect(hasRule(fedStatusPill(s))).toBe(true)
    }
    expect(fedStatusPill('VOTING')).not.toBe(fedStatusPill('FAILED'))
    expect(fedStatusPill('passed')).toBe(fedStatusPill('APPLIED'))
  })

  it('the federation cards use the governance head, never the old unstyled one', () => {
    expect(template).not.toMatch(/sn-proposal-card__(header|id|status|type|timer)\b/)
    expect((template.match(/data-testid="senate-fed-head"/g) || []).length).toBe(2)
  })
})
