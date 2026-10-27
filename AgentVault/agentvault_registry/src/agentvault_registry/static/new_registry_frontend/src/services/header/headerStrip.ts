/**
 * §ALERTS header strip (2026-10-06, agentvault2-09). His words: "check why alerts are not connected to the header thing
 * where the broadcasts are displayed", then "can we make the new announcement bar optional in the settings? i really
 * like the led but polishing it would be cool additionally".
 *
 * The pure parts the two strips share (the LED ticker and the announcement bar): which broadcasts and alerts are shown,
 * in what order, in what words, and how the LED board spells text it has no glyph for. No network and no Vue here, so
 * every rule is unit-tested on its own (headerStrip.test.ts).
 *
 * Two rules the old ticker broke, kept here:
 *  - a read that failed is said as a failed read, never as "no alerts" / "<node> // ONLINE" (it asked an alerts path
 *    that does not exist, got a 404 on every scroll loop, and showed "NO ALERTS // MONITORING ACTIVE");
 *  - the alerts are vmalert's (GET /admin/alerts/active), not Prometheus's (it only scrapes here: an empty list by
 *    construction).
 */
import type { BroadcastItem } from '@/stores/notifications'

export type Rgb = [number, number, number]
export const C_CYAN: Rgb = [0, 210, 210]
export const C_GREEN: Rgb = [16, 220, 129]
export const C_AMBER: Rgb = [245, 180, 30]
export const C_RED: Rgb = [240, 70, 70]
export const C_DIM: Rgb = [110, 125, 140]

export type AlertsState = 'hidden' | 'loading' | 'ok' | 'unreadable' | 'not_configured'

export interface ActiveAlert {
  alertname: string
  title: string
  severity: string
  state: 'firing' | 'pending' | string
  env?: string | null
  labels: Record<string, string>
  active_since: string | null
}

export interface AlertCounts {
  firing: number
  pending: number
  page: number
  critical: number
  warning: number
  info: number
}

export const NO_COUNTS: AlertCounts = { firing: 0, pending: 0, page: 0, critical: 0, warning: 0, info: 0 }

/** One thing the strip shows. `broadcastId` lets a click open that broadcast; `alert` lets it name the alert. */
export interface StripItem {
  key: string
  kind: 'broadcast' | 'alert' | 'status'
  text: string
  color: Rgb
  broadcastId?: number
  severity?: string
  /** a status that a press can retry (a failed read) */
  retry?: 'broadcasts' | 'alerts'
}

type Translate = (key: string, fallback: string) => string

const BROADCAST_RANK: Record<string, number> = { critical: 0, warning: 1, maintenance: 2, info: 3 }
const ALERT_RANK: Record<string, number> = { page: 0, critical: 1, warning: 2, info: 3 }

/** Critical first, then warning, maintenance, info; newest first within a type. */
export function orderBroadcasts(items: readonly BroadcastItem[]): BroadcastItem[] {
  return [...items].sort((a, b) => {
    const r = (BROADCAST_RANK[a.broadcast_type] ?? 9) - (BROADCAST_RANK[b.broadcast_type] ?? 9)
    if (r !== 0) return r
    return (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0)
  })
}

/** One line of a broadcast body: markdown emphasis and links stripped, whitespace collapsed, capped. */
export function oneLine(body: string, max = 160): string {
  const flat = (body || '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*_`#>]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return flat.length > max ? flat.slice(0, max - 1).trimEnd() + '…' : flat
}

export function broadcastColor(type: string): Rgb {
  if (type === 'critical') return C_RED
  if (type === 'warning' || type === 'maintenance') return C_AMBER
  return C_CYAN
}

/** What the strip says in broadcasts mode. */
export function broadcastStripItems(items: readonly BroadcastItem[], read: { failed: boolean, loading: boolean },
                                    t: Translate): StripItem[] {
  if (!items.length) {
    if (read.failed) {
      return [{ key: 'b:failed', kind: 'status', retry: 'broadcasts', color: C_AMBER,
                text: t('ledTicker.broadcastsUnreadable', 'BROADCASTS COULD NOT BE READ  //  PRESS TO TRY AGAIN') }]
    }
    if (read.loading) {
      return [{ key: 'b:loading', kind: 'status', color: C_DIM, text: t('ledTicker.loadingBroadcasts', 'LOADING BROADCASTS...') }]
    }
    return [{ key: 'b:none', kind: 'status', color: C_CYAN, text: t('ledTicker.noNewBroadcasts', 'No new broadcasts') }]
  }
  return orderBroadcasts(items).map((b) => {
    const prefix = b.broadcast_type === 'critical' ? 'CRITICAL: '
      : b.broadcast_type === 'warning' ? 'WARNING: '
        : b.broadcast_type === 'maintenance' ? 'MAINTENANCE: ' : ''
    const body = oneLine(b.body)
    return { key: `b:${b.id}`, kind: 'broadcast' as const, broadcastId: b.id, color: broadcastColor(b.broadcast_type),
             text: body ? `${prefix}${b.title} - ${body}` : `${prefix}${b.title}` }
  })
}

/** The label that tells two alerts of one rule apart (a path, a device, a container, a frame, a job). */
export function alertDetail(labels: Record<string, string>): string {
  for (const k of ['path', 'device', 'name', 'frame', 'trust_domain', 'job', 'instance_name', 'worker', 'scope']) {
    const v = labels?.[k]
    if (v) return v
  }
  return ''
}

export function alertColor(a: Pick<ActiveAlert, 'severity' | 'state'>): Rgb {
  if (a.state !== 'firing') return C_AMBER
  if (a.severity === 'page' || a.severity === 'critical') return C_RED
  if (a.severity === 'warning') return C_AMBER
  return C_CYAN
}

/** Firing before pending; page and critical before warning and info; then by name. */
export function orderAlerts(alerts: readonly ActiveAlert[]): ActiveAlert[] {
  return [...alerts].sort((a, b) =>
    (a.state === 'firing' ? 0 : 1) - (b.state === 'firing' ? 0 : 1)
    || (ALERT_RANK[a.severity] ?? 9) - (ALERT_RANK[b.severity] ?? 9)
    || a.alertname.localeCompare(b.alertname))
}

/** What the strip says in alerts mode (admins only; `hidden` shows nothing). */
export function alertStripItems(state: AlertsState, alerts: readonly ActiveAlert[], t: Translate): StripItem[] {
  if (state === 'hidden') return []
  if (state === 'loading') return [{ key: 'a:loading', kind: 'status', color: C_DIM, text: t('ledTicker.loadingAlerts', 'LOADING ALERTS...') }]
  if (state === 'not_configured') {
    return [{ key: 'a:nocfg', kind: 'status', color: C_DIM,
              text: t('ledTicker.alertsNotConfigured', 'ALERTS ARE NOT CONFIGURED ON THIS REGISTRY') }]
  }
  if (state === 'unreadable') {
    return [{ key: 'a:failed', kind: 'status', retry: 'alerts', color: C_AMBER,
              text: t('ledTicker.alertsUnreadable', 'ALERTS COULD NOT BE READ  //  PRESS TO TRY AGAIN') }]
  }
  if (!alerts.length) return [{ key: 'a:none', kind: 'status', color: C_GREEN, text: t('ledTicker.noAlertsFiring', 'NO ALERTS FIRING') }]
  return orderAlerts(alerts).map((a) => {
    const sev = a.state === 'firing' ? (a.severity || 'alert').toUpperCase() : 'PENDING'
    const detail = alertDetail(a.labels)
    return { key: `a:${a.alertname}:${detail}:${a.state}`, kind: 'alert' as const, severity: a.severity,
             color: alertColor(a), text: `${sev}: ${a.title}${detail ? ` (${detail})` : ''}` }
  })
}

export interface AlertsChip {
  show: boolean
  tone: 'red' | 'amber' | 'green' | 'dim'
  label: string
  title: string
}

/** The announcement bar's alert chip (and the LED badge's count): one sentence per state, never a calm word for a
 *  failed read. `inhibited` warnings (held back by a firing critical of their family, as the alert e-mails do) are not
 *  counted, and the title says how many there are. */
export function alertsChip(state: AlertsState, counts: AlertCounts, reason: string | null, t: Translate,
                           inhibited = 0): AlertsChip {
  if (state === 'hidden') return { show: false, tone: 'dim', label: '', title: '' }
  if (state === 'loading') return { show: true, tone: 'dim', label: t('headerStrip.alertsReading', 'Alerts…'), title: '' }
  if (state === 'not_configured') {
    return { show: true, tone: 'dim', label: t('headerStrip.alertsNotConfigured', 'Alerts not configured'),
             title: t('headerStrip.alertsNotConfiguredTitle', 'This registry has no metrics store (VICTORIA_METRICS_URL), so its alerts cannot be read.') }
  }
  if (state === 'unreadable') {
    return { show: true, tone: 'amber', label: t('headerStrip.alertsUnreadable', 'Alerts unreadable'),
             title: t('headerStrip.alertsUnreadableTitle', 'The alerts could not be read just now, so this is not an all-clear.') + (reason ? ` Reason: ${reason}.` : '') }
  }
  if (counts.firing === 0) {
    return { show: true, tone: 'green', label: t('headerStrip.noAlerts', 'No alerts'),
             title: counts.pending ? `${counts.pending} pending` : t('headerStrip.noAlertsTitle', 'No alert is firing.') }
  }
  const severe = counts.page + counts.critical
  const held = inhibited > 0 ? ` · ${inhibited} ${t('headerStrip.heldBack', 'held back by a firing critical (as the alert e-mails do)')}` : ''
  return { show: true, tone: severe > 0 ? 'red' : 'amber',
           label: counts.firing === 1 ? t('headerStrip.oneAlert', '1 alert firing') : `${counts.firing} ${t('headerStrip.alertsFiring', 'alerts firing')}`,
           title: (severe > 0 ? `${severe} critical` : `${counts.warning + counts.info} warning`) + held }
}

const LED_MAP: Record<string, string> = {
  '‘': "'", '’': "'", '‚': "'", '′': "'", '“': '"', '”': '"', '„': '"', '″': '"',
  '–': '-', '—': '-', '−': '-', '‐': '-', '‑': '-', '…': '...', '•': '*', '·': '*',
  '→': '>', '←': '<', '×': 'x', ' ': ' ', ' ': ' ', ' ': ' ', 'ß': 'ss', 'Æ': 'AE',
  'æ': 'ae', 'Ø': 'O', 'ø': 'o', 'Œ': 'OE', 'œ': 'oe', '€': 'EUR', '£': 'GBP', '$': 'USD',
  '&': '+', '«': '<', '»': '>', '[': '(', ']': ')', '{': '(', '}': ')', ';': ',', '|': '/', '\\': '/', '~': '-',
  '^': "'", '`': "'",
}

/**
 * Text the LED board can draw: accents dropped (ä -> a), typographic marks mapped to their plain forms, line breaks to
 * spaces, and anything still without a glyph shown as "?" rather than silently as a gap.
 */
export function normalizeLedText(text: string, glyphs: Readonly<Record<string, unknown>>): string {
  const plain = (text || '').normalize('NFD').replace(/[̀-ͯ]/g, '')
  let out = ''
  for (const ch of plain) {
    if (glyphs[ch]) { out += ch; continue }
    if (ch === '\n' || ch === '\r' || ch === '\t') { out += ' '; continue }
    const mapped = LED_MAP[ch]
    if (mapped !== undefined) {
      out += [...mapped].every((c) => glyphs[c]) ? mapped : '?'
      continue
    }
    out += '?'
  }
  return out.replace(/ {2,}/g, (m) => (m.length > 2 ? '  ' : m))
}

/** "3m", "2h", "4d": the age of a broadcast or an alert, short enough for a strip. Empty when unknown. */
export function shortAge(iso: string | null | undefined, now: number = Date.now()): string {
  const ts = iso ? Date.parse(iso) : NaN
  if (!Number.isFinite(ts)) return ''
  const mins = Math.max(0, Math.floor((now - ts) / 60000))
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 48) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}
