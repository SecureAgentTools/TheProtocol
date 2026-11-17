/**
 * V0662 (order gwo_16d8fb21303f269406eb772f, his suggestion 4): copy a link to an order, an agent, a blueprint step.
 * A link names the console the person typed (CLAUDE.md: sessions are per host), never an API base: this origin and
 * path, then the console's hash route. Red on f569f6a6e: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { consoleLink } from './consoleLink'

describe('a link to a console page', () => {
  it('this console\'s origin and path, then the hash route', () => {
    const loc = { origin: 'https://theprotocol.cloud', pathname: '/' }
    expect(consoleLink('/guild?order=gwo_1', loc)).toBe('https://theprotocol.cloud/#/guild?order=gwo_1')
    expect(consoleLink('blueprints/collegium?step=2', loc)).toBe('https://theprotocol.cloud/#/blueprints/collegium?step=2')
  })
  it('a console served under a path keeps it', () => {
    expect(consoleLink('/agent-profile/did%3Ax', { origin: 'https://api.example', pathname: '/ui/' }))
      .toBe('https://api.example/ui/#/agent-profile/did%3Ax')
  })
})
