/**
 * V0657 (i), Guild order gwo_092998571152f25968c059be (agentvault2-d3, 2026-11-06): two facts the doc folder states,
 * held here so a later edit cannot quietly undo them.
 *
 * - The OurChat chapter explains wake modes: the three modes, who sets whose, what each lets through, the room line,
 *   and that the registry enforces it (each claim run against sbx-beta on V0656: 18 of 18).
 * - The treasury backstop is off on EU, ASIA and their operators since 2026-10-30, and off on a kit frame
 *   (stack ac186d59), so no chapter says it is on there, and no example answer shows it on.
 */
import { describe, it, expect } from 'vitest'
import ourchat from '@/assets/docs/oracle/34_ourchat.md?raw'
import staking from '@/assets/docs/oracle/03_staking.md?raw'
import security from '@/assets/docs/oracle/08_security.md?raw'
import configuration from '@/assets/docs/operator/02_configuration.md?raw'

function section(md: string, heading: string): string {
  const start = md.indexOf(`\n## ${heading}\n`)
  if (start < 0) return ''
  const next = md.indexOf('\n## ', start + heading.length + 4)
  return md.slice(start, next < 0 ? undefined : next)
}

describe('the OurChat chapter: wake modes', () => {
  const s = section(ourchat, 'Wake Modes')

  it('has its own section', () => {
    expect(s.length).toBeGreaterThan(500)
  })

  it('names the three modes and what each lets through', () => {
    for (const mode of ['`listen`', '`on-call`', '`off`']) expect(s).toContain(mode)
    expect(s).toMatch(/@-names it/)
    expect(s).toMatch(/direct conversation/)
    expect(s).toMatch(/decision on an approval or a choice it asked for/)
    expect(s).toMatch(/`@all`.*from the room's owner/)
  })

  it('says who sets whose: your own, and the owner signed in, never a key or an assistant', () => {
    expect(s).toMatch(/Every member sets its own/)
    expect(s).toMatch(/room's owner can also set another member's mode in an organization's room, from a signed-in console only/)
    expect(s).toMatch(/never an API key/)
    expect(s).toMatch(/through an assistant is refused/)
  })

  it('names the route, the room line and the enforcement', () => {
    expect(s).toContain('PUT /api/v1/chat/conversations/{id}/wake')
    expect(s).toMatch(/\*\*The room line\.\*\*/)
    expect(s).toMatch(/reaches the member it is about whatever its mode, and wakes no one else/)
    expect(s).toMatch(/\*\*The registry enforces it\.\*\*/)
    expect(s).toContain('room.wake_modes')
  })

  it('links only to sections the chapter has', () => {
    const anchors = [...s.matchAll(/\]\(#([a-z0-9-]+)\)/g)].map((m) => m[1])
    const headings = [...ourchat.matchAll(/^#{2,3} (.+)$/gm)].map((m) =>
      m[1].toLowerCase().replace(/[^a-z0-9 -]/g, '').trim().replace(/\s+/g, '-'))
    for (const a of anchors) expect(headings).toContain(a)
  })
})

describe('the treasury backstop: off on EU, ASIA, their operators and a kit frame', () => {
  it('no chapter says it is on for EU, ASIA or their operators', () => {
    for (const md of [staking, security, configuration]) {
      expect(md).not.toMatch(/on for EU, ASIA/i)
    }
  })

  it('the staking chapter says it is off there since 2026-10-30', () => {
    expect(staking).toMatch(/EU, ASIA and their cloud operators run it off since 2026-10-30/)
  })

  it('no example answer shows it on', () => {
    expect(staking).not.toMatch(/"treasury_backstop": true/)
  })

  it('the kit frame column and the security chapter say false', () => {
    expect(configuration).toMatch(/\| `REPUTATION_BOND_TREASURY_BACKSTOP` \| `false` \| `false` \|/)
    expect(security).not.toMatch(/REPUTATION_BOND_TREASURY_BACKSTOP=true/)
    expect(security).toMatch(/REPUTATION_BOND_TREASURY_BACKSTOP=false/)
  })
})
