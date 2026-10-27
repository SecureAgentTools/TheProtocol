import { describe, it, expect } from 'vitest'
import { LED_GLYPHS } from './ledFont'
import {
  alertStripItems, alertsChip, broadcastStripItems, normalizeLedText, oneLine, orderBroadcasts, shortAge,
  NO_COUNTS, C_AMBER, C_GREEN, C_RED, type ActiveAlert,
} from './headerStrip'
import type { BroadcastItem } from '@/stores/notifications'

/**
 * §ALERTS header strip (2026-10-06): the words both strips say. The old ticker said "NO ALERTS // MONITORING ACTIVE"
 * over a 404 and "<node> // ONLINE" over a failed broadcasts read; a failed read is said as a failed read here.
 */
const t = (_k: string, fallback: string) => fallback

const b = (id: number, type: BroadcastItem['broadcast_type'], created: string, title = `T${id}`, body = `B${id}`): BroadcastItem =>
  ({ id, title, body, broadcast_type: type, created_at: created })

const alert = (alertname: string, severity: string, state: string, labels: Record<string, string> = {}): ActiveAlert =>
  ({ alertname, title: alertname.replace(/([a-z])([A-Z])/g, '$1 $2'), severity, state, labels, active_since: null })

describe('broadcasts on the strip', () => {
  it('critical first, newest first within a kind', () => {
    const order = orderBroadcasts([
      b(1, 'info', '2026-10-06T08:00:00Z'), b(2, 'critical', '2026-10-05T08:00:00Z'),
      b(3, 'info', '2026-10-06T09:00:00Z'), b(4, 'warning', '2026-10-01T00:00:00Z'),
    ]).map((x) => x.id)
    expect(order).toEqual([2, 4, 3, 1])
  })

  it('a failed read with nothing to show is said, with a retry; never "online" or "none"', () => {
    const [item] = broadcastStripItems([], { failed: true, loading: false }, t)
    expect(item.kind).toBe('status')
    expect(item.retry).toBe('broadcasts')
    expect(item.text).toMatch(/COULD NOT BE READ/)
    expect(item.color).toEqual(C_AMBER)
  })

  it('"No new broadcasts" only after a read said so', () => {
    expect(broadcastStripItems([], { failed: false, loading: true }, t)[0].text).toMatch(/LOADING/)
    expect(broadcastStripItems([], { failed: false, loading: false }, t)[0].text).toBe('No new broadcasts')
  })

  it('each broadcast is one line with its kind, and carries its id for the press that opens it', () => {
    const items = broadcastStripItems([b(7, 'critical', '2026-10-06T08:00:00Z', 'Disk', '**Free** space\n now')], { failed: true, loading: false }, t)
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ kind: 'broadcast', broadcastId: 7, color: C_RED, text: 'CRITICAL: Disk - Free space now' })
  })

  it('one line of a body: links and emphasis dropped, capped', () => {
    expect(oneLine('see [the page](https://x.example) *now*')).toBe('see the page now')
    expect(oneLine('x'.repeat(200), 20)).toHaveLength(20)
  })
})

describe('alerts on the strip', () => {
  it('a person the route refuses has no alerts mode at all', () => {
    expect(alertStripItems('hidden', [], t)).toEqual([])
  })

  it('each state has its own words: never "no alerts" for a read that failed', () => {
    expect(alertStripItems('unreadable', [], t)[0]).toMatchObject({ retry: 'alerts', color: C_AMBER })
    expect(alertStripItems('unreadable', [], t)[0].text).toMatch(/COULD NOT BE READ/)
    expect(alertStripItems('not_configured', [], t)[0].text).toMatch(/NOT CONFIGURED/)
    expect(alertStripItems('loading', [], t)[0].text).toMatch(/LOADING/)
    expect(alertStripItems('ok', [], t)[0]).toMatchObject({ text: 'NO ALERTS FIRING', color: C_GREEN })
  })

  it('firing before pending, critical before warning, with the label that tells them apart', () => {
    const texts = alertStripItems('ok', [
      alert('LogWarningStorm', 'warning', 'pending'),
      alert('HostDiskSpaceLow', 'warning', 'firing', { device: '/dev/md2' }),
      alert('DiskSpaceCritical', 'critical', 'firing', { device: '/dev/md2' }),
    ], t).map((i) => i.text)
    expect(texts).toEqual([
      'CRITICAL: Disk Space Critical (/dev/md2)',
      'WARNING: Host Disk Space Low (/dev/md2)',
      'PENDING: Log Warning Storm',
    ])
  })
})

describe('the alert chip', () => {
  it('says each state in its own words and tone', () => {
    expect(alertsChip('hidden', NO_COUNTS, null, t).show).toBe(false)
    expect(alertsChip('unreadable', NO_COUNTS, 'http:503', t)).toMatchObject({ tone: 'amber', label: 'Alerts unreadable' })
    expect(alertsChip('unreadable', NO_COUNTS, 'http:503', t).title).toMatch(/not an all-clear\. Reason: http:503\.$/)
    expect(alertsChip('not_configured', NO_COUNTS, null, t).tone).toBe('dim')
    expect(alertsChip('ok', NO_COUNTS, null, t)).toMatchObject({ tone: 'green', label: 'No alerts' })
    expect(alertsChip('ok', { ...NO_COUNTS, firing: 1, warning: 1 }, null, t)).toMatchObject({ tone: 'amber', label: '1 alert firing' })
    expect(alertsChip('ok', { ...NO_COUNTS, firing: 3, critical: 1, warning: 2 }, null, t)).toMatchObject({ tone: 'red', label: '3 alerts firing' })
  })

  it('says how many warnings a firing critical holds back (the alert e-mails\' rule), and counts none of them', () => {
    const chip = alertsChip('ok', { ...NO_COUNTS, firing: 1, critical: 1 }, null, t, 1)
    expect(chip).toMatchObject({ tone: 'red', label: '1 alert firing' })
    expect(chip.title).toBe('1 critical · 1 held back by a firing critical (as the alert e-mails do)')
    expect(alertsChip('ok', { ...NO_COUNTS, firing: 1, critical: 1 }, null, t).title).toBe('1 critical')
  })
})

describe('text the LED board can draw', () => {
  it('drops accents, maps typographic marks, and shows "?" for a character it has no glyph for', () => {
    expect(normalizeLedText('Ladung für März', LED_GLYPHS)).toBe('Ladung fur Marz')
    expect(normalizeLedText('a — b – c “q” ‘s’ …', LED_GLYPHS)).toBe('a - b - c "q" \'s\' ...')
    expect(normalizeLedText('Straße', LED_GLYPHS)).toBe('Strasse')
    expect(normalizeLedText('cost 5€', LED_GLYPHS)).toBe('cost 5EUR')
    expect(normalizeLedText('漢', LED_GLYPHS)).toBe('?')
    expect(normalizeLedText('one\ntwo', LED_GLYPHS)).toBe('one two')
  })

  it('every character it returns has a glyph', () => {
    const out = normalizeLedText('Grüße — “test” ½ ✓ ~ ^ | [x] {y} € $ & ; →', LED_GLYPHS)
    for (const ch of out) expect(LED_GLYPHS[ch], `no glyph for ${JSON.stringify(ch)}`).toBeTruthy()
  })
})

describe('short ages', () => {
  it('minutes, hours, days; empty when unknown', () => {
    const now = Date.parse('2026-10-06T12:00:00Z')
    expect(shortAge('2026-10-06T11:58:00Z', now)).toBe('2m')
    expect(shortAge('2026-10-06T07:00:00Z', now)).toBe('5h')
    expect(shortAge('2026-10-01T12:00:00Z', now)).toBe('5d')
    expect(shortAge(null, now)).toBe('')
    expect(shortAge('not a date', now)).toBe('')
  })
})
