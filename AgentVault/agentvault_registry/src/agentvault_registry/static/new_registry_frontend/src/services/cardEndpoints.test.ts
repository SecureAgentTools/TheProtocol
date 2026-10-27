/**
 * §CARDLINK — the modal must find a card's addresses in EITHER legal dialect.
 *
 * The control is the first test: a canonical A2A v1.0 card (the shape the vendored
 * v1.0.1 schema REQUIRES — supportedInterfaces minItems 1, and no top-level url on
 * AgentCard at all) yields addresses here and yielded NOTHING under the old
 * `agent.url` read, which is why eleven sovereign agents displayed no endpoint.
 */
import { describe, it, expect } from 'vitest'
import { effectiveEndpoints, primaryEndpoint } from './cardEndpoints'

// Hypervisor Hagrid's real card, as the agent itself publishes and signs it.
const CANONICAL_V1 = {
  name: 'Hypervisor Hagrid',
  protocolVersion: '1.0',
  supportedInterfaces: [
    { url: 'https://hagrid.theprotocol.cloud/api/terminal/query', protocolBinding: 'REST', protocolVersion: '1.0' },
    { url: 'https://hagrid.theprotocol.cloud/api/frames', protocolBinding: 'REST', protocolVersion: '1.0' },
    { url: 'https://hagrid.theprotocol.cloud/api/gini', protocolBinding: 'REST', protocolVersion: '1.0' },
    { url: 'https://hagrid.theprotocol.cloud/api/conservation', protocolBinding: 'REST', protocolVersion: '1.0' },
  ],
}

const LEGACY_V03 = {
  name: 'WeatherAgent',
  url: 'https://eu.theprotocol.cloud/agents/weather-agent/a2a',
  preferredTransport: 'JSONRPC',
}

const DUAL_SHAPE = {
  name: 'Both',
  url: 'https://eu.theprotocol.cloud/agents/x/a2a',
  supportedInterfaces: [
    { url: 'https://eu.theprotocol.cloud/agents/x/a2a', protocolBinding: 'JSONRPC', protocolVersion: '1.0' },
  ],
}

describe('effectiveEndpoints', () => {
  it('THE CONTROL: a canonical v1.0 card has addresses even with no top-level url', () => {
    // exactly what the old modal asked, and why the section vanished for every sovereign
    expect((CANONICAL_V1 as any).url).toBeUndefined()
    const eps = effectiveEndpoints(CANONICAL_V1)
    expect(eps).toHaveLength(4)
    expect(eps[0].url).toBe('https://hagrid.theprotocol.cloud/api/terminal/query')
    expect(eps[0].protocolBinding).toBe('REST')
  })

  it('still reads the legacy dialect', () => {
    const eps = effectiveEndpoints(LEGACY_V03)
    expect(eps).toHaveLength(1)
    expect(eps[0].legacy).toBe(true)
    expect(eps[0].protocolBinding).toBe('JSONRPC')
  })

  it('a dual-shape card names ONE endpoint, not two', () => {
    expect(effectiveEndpoints(DUAL_SHAPE)).toHaveLength(1)
  })

  it('the agent decides which address is primary', () => {
    expect(primaryEndpoint(CANONICAL_V1)?.url).toContain('/api/terminal/query')
  })

  it('a card that names no address yields an empty list, never a guess', () => {
    for (const cd of [null, undefined, {}, { supportedInterfaces: [] }, { url: '' }, { supportedInterfaces: [{}] }]) {
      expect(effectiveEndpoints(cd as any)).toEqual([])
      expect(primaryEndpoint(cd as any)).toBeNull()
    }
  })
})
