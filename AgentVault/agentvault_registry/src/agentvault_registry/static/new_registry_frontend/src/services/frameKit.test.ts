import { describe, expect, it } from 'vitest'
import {
  commandText, formatBytes, frameAddress, frameSlug, hasPlaceholder, hostParts, pickRequest, sealTicks, shaGroups, shellQuote,
  shortSha, standing, standUpSteps, STACK_ROOT, type FrameKitRequest, type KitRelease,
} from './frameKit'

const SHA = '0f1e2d3c4b5a69788796a5b4c3d2e1f00123456789abcdeffedcba9876543210'

function request(changes: Partial<FrameKitRequest> = {}): FrameKitRequest {
  return {
    id: 'r1', status: 'approved', hosting: 'self', organization: 'Northwind', contact_name: 'Ada',
    contact_email: 'ada+frames@northwind.example', frame_name: 'northwind', display_name: 'Northwind Frame',
    hostname: 'frame.northwind.example', trust_domain: 'frame.northwind.example', ticker: 'NWD',
    currency_name: 'Northwind Unit', location: 'Lisbon', lat: 38.72234, lng: -9.1393, theme: 'neural', posture: 'production',
    created_at: '2026-09-16T10:00:00Z', approved_at: '2026-09-18T10:00:00Z',
    kit: { state: 'ready', sentence: null, downloads_used: 0, downloads_max: 5, available_until: '2026-10-18T10:00:00Z', last_download_at: null },
    progress: [],
    ...changes,
  }
}

const RELEASE: KitRelease = {
  name: 'theprotocol-frame-kit', version: '1.0.0-beta.4', filename: 'theprotocol-frame-kit-1.0.0-beta.4.tar.gz',
  size_bytes: 283_400_000, sha256: SHA, published_at: '2026-09-19T08:00:00Z', top_dir: 'theprotocol-frame-kit-1.0.0-beta.4',
}
const NETWORK = { name: 'TheProtocol', console: 'https://theprotocol.cloud' }
const byKey = (r = request(), release: KitRelease | null = RELEASE, network = NETWORK) =>
  Object.fromEntries(standUpSteps(r, release, network).map(s => [s.key, s]))

describe('shellQuote', () => {
  it('leaves plain words bare and single-quotes the rest, escaping a quote inside', () => {
    expect(shellQuote('frame.example.org')).toBe('frame.example.org')
    expect(shellQuote('ada+frames@northwind.example')).toBe('ada+frames@northwind.example')
    expect(shellQuote('Northwind Unit')).toBe("'Northwind Unit'")
    expect(shellQuote("Ada's Unit")).toBe("'Ada'\\''s Unit'")
    expect(shellQuote('$(rm -rf /)')).toBe("'$(rm -rf /)'")
    expect(shellQuote('')).toBe("''")
  })
})

describe('frameSlug', () => {
  it('follows frame-up’s name rule and falls back to the hostname, then to a safe default', () => {
    expect(frameSlug({ frame_name: 'northwind', hostname: null })).toBe('northwind')
    expect(frameSlug({ frame_name: 'North Wind_2', hostname: null })).toBe('north-wind-2')
    expect(frameSlug({ frame_name: '9-lives', hostname: null })).toBe('lives')
    expect(frameSlug({ frame_name: null, hostname: 'Frame.Example.org' })).toBe('frame')
    expect(frameSlug({ frame_name: 'x', hostname: 'ab.example' })).toBe('myframe')
    expect(frameSlug({ frame_name: 'a'.repeat(40), hostname: null })).toHaveLength(31)
  })
})

describe('standUpSteps', () => {
  it('walks the five steps in order', () => {
    expect(standUpSteps(request(), RELEASE, NETWORK).map(s => s.key)).toEqual(['unpack', 'dns', 'doctor', 'up', 'federate'])
  })

  it('unpacks the published archive into its own top directory, as one short script copied line by line', () => {
    const unpack = byKey().unpack.commands
    expect(unpack).toHaveLength(1)
    expect(commandText(unpack[0])).toBe([
      'tar xzf theprotocol-frame-kit-1.0.0-beta.4.tar.gz',
      'cd theprotocol-frame-kit-1.0.0-beta.4/scripts/distribution',
      './build.sh',
    ].join('\n'))
    expect(commandText(unpack[0])).not.toContain('\\')
  })

  it('fills frame-up with the request’s values, quoted, and leaves the relay as placeholders', () => {
    const up = byKey().up.commands[0]
    const text = commandText(up)
    expect(text).toContain('./frame-up.py --name northwind --public-name frame.northwind.example')
    expect(text).toContain("--ticker NWD --currency-name 'Northwind Unit' \\\n    --admin-email ada+frames@northwind.example \\")
    expect(text).toContain('--location-label Lisbon --lat 38.7223 --lng -9.1393')
    expect(text).toContain('--mail-server <your SMTP server>')
    expect(hasPlaceholder(up)).toBe(true)
    expect(text.split(' \\\n    ')).toHaveLength(7)
    // no line outgrows a laptop's command well (about 80 columns) unless a placeholder or a path makes it
    expect(Math.max(...text.split(' \\\n    ').map(l => l.length))).toBeLessThanOrEqual(80)
  })

  it('carries the name and mark the applicant chose, and never the form’s posture', () => {
    const text = commandText(byKey(request({ display_name: "Northwind's Frame", theme: 'sovereign' })).up.commands[0])
    expect(text).toContain("--frame-label 'Northwind'\\''s Frame' --theme sovereign")
    expect(text).not.toContain('--posture')
    const bare = commandText(byKey(request({ display_name: null, theme: null })).up.commands[0])
    expect(bare).not.toContain('--frame-label')
    expect(bare).not.toContain('--theme')
    expect(bare.split(' \\\n    ')).toHaveLength(6)
  })

  it('turns every value the request lacks into a placeholder instead of an empty flag', () => {
    const text = commandText(byKey(request({ ticker: null, currency_name: '', location: null, lat: null, lng: null })).up.commands[0])
    expect(text).toContain('--ticker <ticker>')
    expect(text).toContain('--currency-name <currency name>')
    expect(text).toContain('--location-label <city> --lat <latitude> --lng <longitude>')
  })

  it('federates with this network’s console and the secret file frame-up writes', () => {
    const text = commandText(byKey().federate.commands[0])
    expect(text.startsWith('./frame-federate.py \\\n    --stack-dir ')).toBe(true)
    expect(text).toContain(`--stack-dir ${STACK_ROOT}/northwind-<number frame-up printed>`)
    expect(text).toContain('--with https://theprotocol.cloud')
    expect(text).toContain(`--admin-secret-file ${STACK_ROOT}/northwind-secrets/.northwind_frame_admin.secret.json`)
    const noConsole = commandText(byKey(request(), RELEASE, { name: '', console: '' }).federate.commands[0])
    expect(noConsole).toContain('--with <network console>')
  })

  it('asks for the hostname and its wildcard in DNS, and says so when the request has no hostname', () => {
    expect(byKey().dns.records?.map(r => r.name)).toEqual(['frame.northwind.example', '*.frame.northwind.example'])
    const bare = byKey(request({ hostname: null, trust_domain: null }))
    expect(bare.dns.records?.map(r => r.name)).toEqual(['<your hostname>'])
    expect(commandText(bare.doctor.commands[0])).toBe('./frame-doctor.py --public-name <your hostname> --name northwind')
  })

  it('still reads when no kit is published yet', () => {
    expect(commandText(byKey(request(), null).unpack.commands[0]).split('\n')[0]).toBe('tar xzf theprotocol-frame-kit.tar.gz')
  })
})

describe('the seal', () => {
  it('draws one tick per hex digit, clockwise from the top, stronger for larger digits', () => {
    const ticks = sealTicks(SHA)
    expect(ticks).toHaveLength(64)
    expect(ticks[0].angle).toBe(0)
    expect(ticks[16].angle).toBe(90)
    expect(ticks[0].length).toBe(5)                 // '0'
    expect(ticks[1].length).toBeCloseTo(5 + 15 * 1.4) // 'f'
    expect(ticks[1].opacity).toBe(1)
    expect(ticks[0].opacity).toBe(0.32)
  })

  it('draws nothing for anything that is not a sha256', () => {
    expect(sealTicks('')).toEqual([])
    expect(sealTicks('abc')).toEqual([])
  })

  it('shows the part people compare', () => {
    expect(shortSha(SHA)).toBe('0f1e2d3c…76543210')
  })
})

describe('small formatters', () => {
  it('formats sizes in the reader’s locale', () => {
    expect(formatBytes(283_400_000, 'en')).toBe('283.4 MB')
    expect(formatBytes(283_400_000, 'de')).toBe('283,4 MB')
    expect(formatBytes(512, 'en')).toBe('512 B')
    expect(formatBytes(-1, 'en')).toBe('')
  })

  it('opens on the request asked for, else the newest self-hosted one, else the newest', () => {
    const hosted = request({ id: 'h', hosting: 'theprotocol' })
    const own = request({ id: 's' })
    expect(pickRequest([hosted, own])?.id).toBe('s')
    expect(pickRequest([hosted, own], 'h')?.id).toBe('h')
    expect(pickRequest([hosted])?.id).toBe('h')
    expect(pickRequest([])).toBeNull()
  })

  it('never opens on a declined request while one is still going', () => {
    const declined = request({ id: 'd', status: 'rejected' })
    const approved = request({ id: 'a' })
    const hosted = request({ id: 'h', hosting: 'theprotocol', status: 'pending' })
    expect(pickRequest([declined, approved])?.id).toBe('a')
    expect(pickRequest([declined, hosted])?.id).toBe('h')
    expect(pickRequest([declined])?.id).toBe('d')
    expect(pickRequest([declined, approved], 'd')?.id).toBe('d')
  })

  it('names where a request stands by its last step that happened', () => {
    const at = '2026-09-19T00:00:00Z'
    expect(standing({ progress: [{ key: 'requested', state: 'done', at }, { key: 'approved', state: 'current', at: null }] })).toBe('requested')
    expect(standing({ progress: [{ key: 'requested', state: 'done', at }, { key: 'declined', state: 'declined', at }] })).toBe('declined')
    expect(standing({ progress: [] })).toBeNull()
  })

  it('breaks a hostname after its dots, and leaves a name that is not one alone', () => {
    expect(hostParts('registry-frame-lisbon-01.northwind.example')).toEqual(['registry-frame-lisbon-01.', 'northwind.', 'example'])
    expect(hostParts('Harbour Frame')).toEqual(['Harbour Frame'])
    expect(hostParts('')).toEqual([])
    expect(hostParts('a.b.c').join('')).toBe('a.b.c')
  })

  it('groups a sha256 in eights for comparing, and nothing else', () => {
    expect(shaGroups(SHA)).toHaveLength(8)
    expect(shaGroups(SHA).join('')).toBe(SHA)
    expect(shaGroups('abc')).toEqual([])
  })

  it('leads with the hostname, else the name', () => {
    expect(frameAddress(request())).toBe('frame.northwind.example')
    expect(frameAddress(request({ hostname: null, trust_domain: null }))).toBe('Northwind Frame')
  })
})
