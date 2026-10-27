/**
 * services/frameKit.ts: §HELLOFRAME (his word 2026-09-19: "the operator-portal is outdated, make a glorious version for
 * the frame export").
 *
 * Everything the frame page decides, as pure functions so the view only renders: the commands a self-hosted applicant
 * runs (with their frame's values filled in and the values only they know left as visible placeholders), the shell
 * quoting of those values, the DNS records, the kit seal drawn from the kit's sha256, and the small formatters.
 * The registry (routers/frame_kit.py) decides who may download and when; this module never second-guesses it.
 */

export type KitState = 'ready' | 'locked' | 'expired' | 'exhausted' | 'unpublished' | 'rejected' | 'not_self_hosted'
export type StepState = 'done' | 'current' | 'ahead' | 'declined'
export type Hosting = 'self' | 'theprotocol' | null

export interface KitWindow {
  state: KitState
  sentence: string | null
  downloads_used: number
  downloads_max: number
  available_until: string | null
  last_download_at: string | null
}

export interface ProgressStep {
  key: string
  state: StepState
  at: string | null
}

export interface FrameKitRequest {
  id: string
  status: string
  hosting: Hosting
  organization: string | null
  contact_name: string | null
  contact_email: string | null
  frame_name: string | null
  display_name: string | null
  hostname: string | null
  trust_domain: string | null
  ticker: string | null
  currency_name: string | null
  location: string | null
  lat: number | null
  lng: number | null
  theme: 'neural' | 'sovereign' | null
  posture: string | null
  created_at: string
  approved_at: string | null
  kit: KitWindow
  progress: ProgressStep[]
}

export interface KitRelease {
  name: string
  version: string
  filename: string
  size_bytes: number
  sha256: string
  published_at: string
  top_dir: string
}

export interface FrameKitNetwork {
  name: string
  console: string
}

export interface FrameKitPage {
  requests: FrameKitRequest[]
  release: KitRelease | null
  release_note: string | null
  network: FrameKitNetwork
  window_days: number
  max_downloads: number
}

/** One piece of a command: literal text, or a value only the applicant knows (rendered as a placeholder). */
export interface Token {
  text: string
  placeholder?: boolean
}

/**
 * A command across one or more visual lines. By default the lines are ONE shell command, copied with backslash
 * continuations; a `script` is several commands, one per line, copied as they are and run in order.
 */
export interface Command {
  lines: Token[][]
  script?: boolean
}

export interface DnsRecord {
  type: 'A'
  name: string
  value: Token
}

export type StandUpKey = 'unpack' | 'dns' | 'doctor' | 'up' | 'federate'

export interface StandUpStep {
  key: StandUpKey
  commands: Command[]
  records?: DnsRecord[]
}

/** The stack root frame-up writes to by default (scripts/distribution/frame-up.py --stack-root). */
export const STACK_ROOT = '/opt/theprotocol/stack'

const SAFE = /^[A-Za-z0-9@%+=:,./_-]+$/

/** Quote a value for a POSIX shell, leaving plain words unquoted so the command stays readable. */
export function shellQuote(value: string): string {
  if (value !== '' && SAFE.test(value)) return value
  return `'${value.replace(/'/g, `'\\''`)}'`
}

/** frame-up's --name: lowercase letters, digits and dashes, a letter first, 3 to 31 characters. */
export function frameSlug(r: Pick<FrameKitRequest, 'frame_name' | 'hostname'>): string {
  const clean = (s: string) => s.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^[^a-z]+/, '').replace(/-+/g, '-').replace(/-+$/, '')
  const fromName = clean(r.frame_name || '')
  if (fromName.length >= 3) return fromName.slice(0, 31).replace(/-+$/, '')
  const fromHost = clean((r.hostname || '').split('.')[0] || '')
  return fromHost.length >= 3 ? fromHost.slice(0, 31).replace(/-+$/, '') : 'myframe'
}

const lit = (text: string): Token => ({ text })
const ph = (text: string): Token => ({ text, placeholder: true })
/** A flag and its value, quoted; a missing value becomes a placeholder. */
const flag = (name: string, value: string | number | null | undefined, placeholder: string): Token[] =>
  value === null || value === undefined || value === ''
    ? [lit(`${name} `), ph(placeholder)]
    : [lit(`${name} ${shellQuote(String(value))}`)]

function coordinate(n: number | null): string | null {
  return typeof n === 'number' && Number.isFinite(n) ? String(Math.round(n * 10000) / 10000) : null
}

/** The five steps from the kit to a federated frame, with this request's values filled in. */
export function standUpSteps(r: FrameKitRequest, release: KitRelease | null, network: FrameKitNetwork): StandUpStep[] {
  const slug = frameSlug(r)
  const host = (r.hostname || r.trust_domain || '').trim().toLowerCase()
  const hostTokens = (prefix: string): Token[] => (host ? [lit(`${prefix}${host}`)] : [lit(prefix), ph('<your hostname>')])
  const archive = release?.filename || 'theprotocol-frame-kit.tar.gz'
  const top = release?.top_dir || archive.replace(/\.tar\.gz$/, '')
  const joinPh = (parts: Token[][]): Token[] => parts.flatMap((p, i) => (i ? [lit(' '), ...p] : p))

  const unpack: Command[] = [{
    script: true,
    lines: [[lit(`tar xzf ${shellQuote(archive)}`)], [lit(`cd ${shellQuote(top)}/scripts/distribution`)], [lit('./build.sh')]],
  }]
  const doctor: Command[] = [{
    lines: [joinPh([[lit('./frame-doctor.py')], hostTokens('--public-name '), [lit(`--name ${slug}`)]])],
  }]
  // The name and mark the applicant chose in the request. The form's posture (pilot or production) is a stage of the
  // request, not frame-up's --posture, whose other value relaxes the frame's protections; it is never carried over.
  const label = (r.display_name || '').trim()
  const look = joinPh([
    ...(label ? [[lit(`--frame-label ${shellQuote(label)}`)]] : []),
    ...(r.theme ? [[lit(`--theme ${r.theme}`)]] : []),
  ])
  const up: Command[] = [{
    lines: [
      joinPh([[lit('./frame-up.py')], [lit(`--name ${slug}`)], hostTokens('--public-name ')]),
      ...(look.length ? [look] : []),
      joinPh([flag('--ticker', r.ticker, '<ticker>'), flag('--currency-name', r.currency_name, '<currency name>')]),
      flag('--admin-email', r.contact_email, '<your email>'),
      joinPh([flag('--location-label', r.location, '<city>'), flag('--lat', coordinate(r.lat), '<latitude>'),
        flag('--lng', coordinate(r.lng), '<longitude>')]),
      joinPh([[lit('--mail-server '), ph('<your SMTP server>')], [lit('--mail-address '), ph('<your sender address>')]]),
      [lit('--mail-token-file '), ph('<file holding the SMTP password>')],
    ],
  }]
  const federate: Command[] = [{
    lines: [
      [lit('./frame-federate.py')],
      [lit('--stack-dir '), lit(`${STACK_ROOT}/${slug}-`), ph('<number frame-up printed>')],
      network.console ? [lit(`--with ${shellQuote(network.console)}`)] : [lit('--with '), ph('<network console>')],
      [lit(`--admin-secret-file ${STACK_ROOT}/${slug}-secrets/.${slug}_frame_admin.secret.json`)],
    ],
  }]
  const records: DnsRecord[] = host
    ? [{ type: 'A', name: host, value: ph('<your host’s public IPv4>') },
       { type: 'A', name: `*.${host}`, value: ph('<the same address>') }]
    : [{ type: 'A', name: '<your hostname>', value: ph('<your host’s public IPv4>') }]
  return [
    { key: 'unpack', commands: unpack },
    { key: 'dns', commands: [], records },
    { key: 'doctor', commands: doctor },
    { key: 'up', commands: up },
    { key: 'federate', commands: federate },
  ]
}

/** The command as the shell reads it: lines joined with a backslash continuation, placeholders as written. */
export function commandText(c: Command): string {
  return c.lines.map(line => line.map(t => t.text).join('')).join(c.script ? '\n' : ' \\\n    ')
}

/** Whether a command still holds a value only the applicant can supply. */
export function hasPlaceholder(c: Command): boolean {
  return c.lines.some(line => line.some(t => t.placeholder))
}

export interface SealTick {
  angle: number
  length: number
  opacity: number
}

/**
 * The kit seal: one tick per hex digit of the sha256, clockwise from twelve o'clock, its length and strength the digit's
 * value. The same kit always draws the same seal, so two people can compare it at a glance; the page prints the full hex
 * and the command that checks it, because the seal is a picture of the checksum and not a replacement for it.
 */
export function sealTicks(sha256: string): SealTick[] {
  const hex = (sha256 || '').toLowerCase().replace(/[^0-9a-f]/g, '')
  if (hex.length !== 64) return []
  return [...hex].map((ch, i) => {
    const v = parseInt(ch, 16)
    return { angle: (i * 360) / 64, length: 5 + v * 1.4, opacity: Math.round((0.32 + (v / 15) * 0.68) * 100) / 100 }
  })
}

/** The first and last eight hex digits, the part people compare. */
export function shortSha(sha256: string): string {
  const s = (sha256 || '').toLowerCase()
  return s.length > 20 ? `${s.slice(0, 8)}…${s.slice(-8)}` : s
}

/** A byte count in the reader's locale, to one decimal above a megabyte. */
export function formatBytes(n: number, locale: string): string {
  if (!Number.isFinite(n) || n < 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let u = 0
  while (v >= 1000 && u < units.length - 1) { v /= 1000; u++ }
  const digits = u >= 2 ? 1 : 0
  return `${v.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${units[u]}`
}

/**
 * The request the page opens on: the one asked for, else the newest self-hosted one still going, else the newest one
 * still going, else the newest. A declined request never hides one that is alive (the list arrives newest first).
 */
export function pickRequest(requests: FrameKitRequest[], wanted?: string | null): FrameKitRequest | null {
  if (!requests.length) return null
  const alive = (r: FrameKitRequest) => r.status !== 'rejected'
  return requests.find(r => r.id === wanted)
    || requests.find(r => r.hosting === 'self' && alive(r))
    || requests.find(alive)
    || requests[0]
}

/** Where a request stands in one word: its last step that happened (the progress the registry sent). */
export function standing(r: Pick<FrameKitRequest, 'progress'>): string | null {
  const happened = r.progress.filter(s => s.state === 'done' || s.state === 'declined')
  return happened.length ? happened[happened.length - 1].key : null
}

/** A hostname in the pieces a line may break between: each label keeps its dot, so a wrap falls after a dot. */
export function hostParts(host: string): string[] {
  const h = (host || '').trim()
  if (!h || /\s/.test(h) || !h.includes('.')) return h ? [h] : []
  return h.split('.').map((label, i, all) => (i < all.length - 1 ? `${label}.` : label)).filter(Boolean)
}

/** A sha256 in groups of eight, the way people compare one against a terminal. */
export function shaGroups(sha256: string): string[] {
  const s = (sha256 || '').toLowerCase()
  return /^[0-9a-f]{64}$/.test(s) ? s.match(/.{8}/g) || [] : []
}

/** The address the page leads with: the hostname a self-hosted frame answers on, else its name. */
export function frameAddress(r: FrameKitRequest): string {
  return (r.hostname || r.trust_domain || r.display_name || r.frame_name || '').trim()
}
