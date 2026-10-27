/**
 * services/frameRequestForm.ts: the public frame request form's rules (§FRAMEFORM rebuild, his word 2026-09-13: "the
 * frame-commander form is not correct anymore ... old legacy frames to choose to federate with ... no advanced settings").
 *
 * One testable place for everything the view only renders: the draft and its six steps, each field's rule (aligned to
 * the host frame runner's spec, so a request always maps into something the admin can plan and start), the addresses a
 * hosted frame gets, the partner frames read from the live network instead of a hardcoded list, the payload
 * POST /operators/request-frame takes, the saved draft, and the prefill the admin panel builds from a stored request.
 */
import {
  FRAME_FEATURE_SWITCHES,
  type FrameFeatureSwitch,
  type FrameRequestAdminRead,
  type FrameRequestAnswers,
  type FrameRequestCreate,
} from './api/frameRequests'

export const FRAME_DOMAIN = 'theprotocol.cloud'
export const DRAFT_STORAGE_KEY = 'fc_frame_request_draft'
const DRAFT_VERSION = 2

export type Hosting = 'theprotocol' | 'self'
export type FrameTheme = 'neural' | 'sovereign'
export type NetworkIntent = 'federate_later' | 'standalone' | 'standalone_test_operator'
export type Posture = 'pilot' | 'production'
/** Who runs the frame, which decides the network licence's plan (his words 2026-09-28: "free license for educational,
 * research and non profits. but enterprise and goverment orgs will not have the same privilige"). The same list as the
 * server's NETWORK_PLANS: the first four are free with no end date, enterprise and government free for the first year. */
export const LICENCE_CATEGORIES = ['private', 'educational', 'research', 'non-profit', 'enterprise', 'government'] as const
export type LicenceCategory = (typeof LICENCE_CATEGORIES)[number]
export const FIRST_YEAR_CATEGORIES: readonly LicenceCategory[] = ['enterprise', 'government']

export interface FrameRequestDraft {
  organization: string
  contact_name: string
  email: string
  create_account: boolean
  hosting: Hosting
  frame_name: string
  display_name: string
  hostname: string
  description: string
  theme: FrameTheme
  ticker: string
  currency_name: string
  mint: string
  genesis_grant: string
  location: string
  lat: string
  lng: string
  website: string
  tags: string[]
  intent: NetworkIntent
  partners: string[]
  /** '' = not stated; asked only when the frame means to federate (a standalone frame needs no licence) */
  licence_category: LicenceCategory | ''
  posture: Posture
  operators: number
  features: Record<string, string>
  use_case: string
  notes: string
  /** §LEGALKIT: the applicant accepted the Terms and the Federation Operator Terms; the server refuses without it */
  accept_terms: boolean
}
export type DraftField = keyof FrameRequestDraft

export const STEPS = ['contact', 'frame', 'currency', 'place', 'network', 'review'] as const
export type StepId = (typeof STEPS)[number]

export const STEP_FIELDS: Record<StepId, DraftField[]> = {
  contact: ['organization', 'contact_name', 'email'],
  frame: ['frame_name', 'display_name', 'hostname', 'description'],
  currency: ['ticker', 'currency_name', 'mint', 'genesis_grant'],
  place: ['location', 'lat', 'lng', 'website', 'tags'],
  network: ['partners', 'operators'],
  review: ['use_case', 'notes'],
}

export const LIMITS = {
  organization: 200, contact_name: 120, email: 200, display_name: 60, description: 400, currency_name: 40,
  location: 80, website: 200, tag: 24, tags: 8, partners: 8, use_case: 2000, use_case_min: 10, notes: 2000,
  hostname: 255, mint: 1_000_000_000, operators: 4,
} as const

// The host frame runner's NAME_RE intersected with the registry's rule: 3 to 31 characters, a letter first, no trailing '-'.
export const FRAME_NAME_RE = /^[a-z][a-z0-9-]{1,29}[a-z0-9]$/
export const TICKER_RE = /^[A-Z]{2,6}$/
const HOSTNAME_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

/** Names this platform already answers on: a request for one of them is refused at review, so the form says so now. */
export const RESERVED_FRAME_NAMES: ReadonlySet<string> = new Set([
  'api', 'www', 'registry', 'auditor', 'grafana', 'prometheus', 'alerts', 'dozzle', 'status', 'docs', 'git', 'images',
  'spire', 'mail', 'admin', 'eu', 'asia', 'sandbox-a', 'sandbox-b', 'sbx-alpha', 'sbx-beta', 'hetzner', 'hetzner-frame',
  'frame-b', 'frame-c',
])

/** A rule's answer: an i18n key, the English sentence it falls back to, and the values the sentence names. */
export interface FieldIssue {
  key: string
  fallback: string
  params?: Record<string, string | number>
}
export type DraftIssues = Partial<Record<DraftField, FieldIssue>>

const error = (key: string, fallback: string, params?: FieldIssue['params']): FieldIssue =>
  ({ key: `frameCommanderView.errors.${key}`, fallback, params })
const warning = (key: string, fallback: string, params?: FieldIssue['params']): FieldIssue =>
  ({ key: `frameCommanderView.warnings.${key}`, fallback, params })

export function defaultFeatures(catalog: FrameFeatureSwitch[] = FRAME_FEATURE_SWITCHES): Record<string, string> {
  return Object.fromEntries(catalog.map(sw => [sw.key, sw.def]))
}

export function blankDraft(): FrameRequestDraft {
  return {
    organization: '', contact_name: '', email: '', create_account: false,
    hosting: 'theprotocol', frame_name: '', display_name: '', hostname: '', description: '', theme: 'neural',
    ticker: '', currency_name: '', mint: '1000000', genesis_grant: '1000',
    location: '', lat: '', lng: '', website: '', tags: [],
    intent: 'federate_later', partners: [], licence_category: '', posture: 'pilot', operators: 0,
    features: defaultFeatures(),
    use_case: '', notes: '',
    accept_terms: false,
  }
}

/** A whole number as people type it ("1,000,000", "1 000 000"); null when it is not one. */
export function wholeNumber(value: string): number | null {
  const s = String(value ?? '').replace(/[\s,_']/g, '')
  return /^\d{1,10}$/.test(s) ? Number(s) : null
}

/** A coordinate as people type it ("47.84", "47,84"); null when it is not one. */
export function coordinate(value: string): number | null {
  const s = String(value ?? '').trim().replace(',', '.')
  return /^-?\d{1,3}(\.\d+)?$/.test(s) ? Number(s) : null
}

export function isHttpsUrl(value: string): boolean {
  const s = value.trim()
  if (!s || s.length > LIMITS.website || /\s/.test(s)) return false
  try {
    const u = new URL(s)
    return u.protocol === 'https:' && u.hostname.includes('.')
  } catch {
    return false
  }
}

export function validateDraft(d: FrameRequestDraft, takenNames: string[] = []): DraftIssues {
  const out: DraftIssues = {}
  const text = (field: DraftField, value: string, max: number, required: boolean) => {
    const v = value.trim()
    if (required && !v) out[field] = error('required', 'Required')
    else if (v.length > max) out[field] = error('tooLong', 'At most {max} characters', { max })
  }

  text('organization', d.organization, LIMITS.organization, true)
  text('contact_name', d.contact_name, LIMITS.contact_name, true)
  const email = d.email.trim()
  if (!email) out.email = error('required', 'Required')
  else if (email.length > LIMITS.email || !EMAIL_RE.test(email)) out.email = error('email', 'An email address like you@org.example')

  const name = d.frame_name.trim()
  const taken = new Set([...RESERVED_FRAME_NAMES, ...takenNames.map(n => n.toLowerCase())])
  if (!name) out.frame_name = error('required', 'Required')
  else if (!FRAME_NAME_RE.test(name)) {
    out.frame_name = error('frameName', '3 to 31 characters: lowercase letters, digits and hyphens, starting with a letter and not ending with a hyphen')
  } else if (taken.has(name)) out.frame_name = error('frameNameTaken', '{name} is already in use on this network', { name })
  text('display_name', d.display_name, LIMITS.display_name, true)
  if (d.hosting === 'self') {
    const host = d.hostname.trim().toLowerCase()
    if (!host) out.hostname = error('required', 'Required')
    else if (host.length > LIMITS.hostname || !HOSTNAME_RE.test(host)) out.hostname = error('hostname', 'A hostname like frame.example.org')
  }
  text('description', d.description, LIMITS.description, false)

  const ticker = d.ticker.trim()
  if (!ticker) out.ticker = error('required', 'Required')
  else if (!TICKER_RE.test(ticker)) out.ticker = error('ticker', '2 to 6 capital letters')
  text('currency_name', d.currency_name, LIMITS.currency_name, true)
  const mint = wholeNumber(d.mint)
  if (!d.mint.trim()) out.mint = error('required', 'Required')
  else if (mint === null || mint < 1 || mint > LIMITS.mint) out.mint = error('mint', 'A whole number from 1 to 1,000,000,000')
  if (d.genesis_grant.trim()) {
    const grant = wholeNumber(d.genesis_grant)
    if (grant === null || (mint !== null && grant > mint)) out.genesis_grant = error('grant', 'A whole number from 0 up to the genesis issuance')
  }

  text('location', d.location, LIMITS.location, true)
  const lat = coordinate(d.lat)
  const lng = coordinate(d.lng)
  if (!d.lat.trim()) out.lat = error('required', 'Required')
  else if (lat === null || lat < -90 || lat > 90) out.lat = error('lat', 'A latitude from -90 to 90')
  if (!d.lng.trim()) out.lng = error('required', 'Required')
  else if (lng === null || lng < -180 || lng > 180) out.lng = error('lng', 'A longitude from -180 to 180')
  if (d.website.trim() && !isHttpsUrl(d.website)) out.website = error('website', 'An https:// address of at most 200 characters')
  if (d.tags.length > LIMITS.tags || d.tags.some(tag => !tag.trim() || tag.length > LIMITS.tag)) {
    out.tags = error('tags', 'Up to {count} tags of at most {max} characters', { count: LIMITS.tags, max: LIMITS.tag })
  }

  if (d.partners.length > LIMITS.partners) out.partners = error('partners', 'Up to {max} frames', { max: LIMITS.partners })
  if (!Number.isInteger(d.operators) || d.operators < 0 || d.operators > LIMITS.operators) {
    out.operators = error('operators', 'From 0 to {max}', { max: LIMITS.operators })
  }

  const why = d.use_case.trim()
  if (!why) out.use_case = error('required', 'Required')
  else if (why.length < LIMITS.use_case_min) out.use_case = error('useCaseShort', 'At least {min} characters', { min: LIMITS.use_case_min })
  else if (why.length > LIMITS.use_case) out.use_case = error('tooLong', 'At most {max} characters', { max: LIMITS.use_case })
  text('notes', d.notes, LIMITS.notes, false)
  return out
}

export function stepIssues(issues: DraftIssues, step: StepId): DraftIssues {
  return Object.fromEntries(STEP_FIELDS[step].filter(f => issues[f]).map(f => [f, issues[f]])) as DraftIssues
}

/** The index of the first step still carrying an issue, or -1 when the whole draft is valid. */
export function firstStepWithIssues(issues: DraftIssues): number {
  return STEPS.findIndex(step => Object.keys(stepIssues(issues, step)).length > 0)
}

export interface FrameAddresses {
  console: string
  ledger: string | null
  trustDomain: string
  spiffe: string
  federation: string
}

/** Where the frame answers once it stands: the host frame runner derives every hosted address from the name. */
export function frameAddresses(
  d: Pick<FrameRequestDraft, 'frame_name' | 'hosting' | 'hostname'>, domain = FRAME_DOMAIN,
): FrameAddresses | null {
  if (d.hosting === 'self') {
    const host = d.hostname.trim().toLowerCase()
    if (!HOSTNAME_RE.test(host)) return null
    return { console: `https://${host}`, ledger: null, trustDomain: host, spiffe: `spiffe://${host}`, federation: `https://${host}:8443` }
  }
  const name = d.frame_name.trim()
  if (!FRAME_NAME_RE.test(name)) return null
  return {
    console: `https://${name}.${domain}`,
    ledger: `https://${name}-es.${domain}`,
    trustDomain: `${name}.${domain}`,
    spiffe: `spiffe://${name}.${domain}`,
    federation: `https://${name}.${domain}:8443`,
  }
}

const LEGAL_FORMS = new Set([
  'gmbh', 'ag', 'ug', 'kg', 'ohg', 'ev', 'ltd', 'limited', 'inc', 'llc', 'plc', 'sa', 'sas', 'sarl', 'srl', 'spa', 'bv',
  'nv', 'ab', 'as', 'oy', 'co', 'corp', 'company',
])

const words = (value: string): string[] =>
  value.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean)

/** A frame name offered from the organization's name ("Sovereign Org GmbH" -> "sovereign-org"), or '' when none fits. */
export function suggestFrameName(organization: string): string {
  const parts = words(organization)
  while (parts.length > 1 && LEGAL_FORMS.has(parts[parts.length - 1])) parts.pop()
  const slug = parts.join('-').replace(/^[^a-z]+/, '').slice(0, 31).replace(/-+$/, '')
  return FRAME_NAME_RE.test(slug) ? slug : ''
}

/** A ticker offered from a currency or frame name: initials for three words or more, else the first word's first letters. */
export function suggestTicker(source: string): string {
  const parts = words(source).map(w => w.replace(/[^a-z]/g, '')).filter(Boolean)
  if (!parts.length) return ''
  const ticker = (parts.length >= 3 ? parts.map(w => w[0]).join('').slice(0, 6) : parts[0].slice(0, 4)).toUpperCase()
  return TICKER_RE.test(ticker) ? ticker : ''
}

/** The advanced switches, grouped for the form. A test holds every catalog key to exactly one group. */
export const FEATURE_GROUPS: { id: string; keys: string[] }[] = [
  { id: 'economy', keys: ['agora_exchange', 'passport_trading', 'currency_exchange', 'guild', 'contracts', 'contract_templates', 'cross_frame_contracts', 'cosmetics_shop', 'fiat_onramp', 'staking', 'staking_rewards', 'agora_distributions', 'genesis_grant', 'reputation_bond'] },
  { id: 'agents', keys: ['agent_permissions', 'delegation', 'xreg_delegation', 'agent_mtls', 'liability_card', 'sub_agent_wallets', 'agent_forge', 'zk_proofs'] },
  { id: 'access', keys: ['invite_only', 'email_verification', 'chat', 'operator_desk', 'policy_engine'] },
  { id: 'governance', keys: ['governance_weight', 'federation_ballots', 'commons', 'jurisdiction'] },
  { id: 'operations', keys: ['canaries', 'simulation', 'api_test_harness'] },
]

/** Agent permissions and delegation move together: permissions enforced without delegation deny every capability token. */
export const PAIRED_FEATURES: [string, string][] = [['agent_permissions', 'delegation']]

export function setFeature(features: Record<string, string>, key: string, value: string): Record<string, string> {
  const next = { ...features, [key]: value }
  for (const [a, b] of PAIRED_FEATURES) {
    if (key === a) next[b] = value
    if (key === b) next[a] = value
  }
  return next
}

export function changedFeatures(
  features: Record<string, string>, catalog: FrameFeatureSwitch[] = FRAME_FEATURE_SWITCHES,
): Record<string, string> {
  return Object.fromEntries(
    catalog.filter(sw => features[sw.key] !== undefined && features[sw.key] !== sw.def).map(sw => [sw.key, features[sw.key]]),
  )
}

/** Things worth saying before submit, never blocking: a switch that needs something the request does not have.
 *  `kitOffered` (§HELLOFRAME, the registry's frame_kit_enabled): where the frame kit is offered, a self-hosted frame does
 *  NOT wait for the open-source release, so that warning is not said there. */
export function draftWarnings(d: FrameRequestDraft, opts: { kitOffered?: boolean } = {}): FieldIssue[] {
  const out: FieldIssue[] = []
  const federated = ['currency_exchange', 'cross_frame_contracts', 'xreg_delegation'].filter(k => d.features[k] === 'yes')
  if (d.intent !== 'federate_later' && federated.length) {
    out.push(warning('needsFederation', 'These only start working once the frame federates: {features}', { features: federated.join(', ') }))
  }
  if (d.features.email_verification === 'yes') out.push(warning('needsMail', 'Email verification needs a mail relay for your frame'))
  if (d.features.invite_only === 'no' && d.features.email_verification !== 'yes') {
    out.push(warning('openDoor', 'Open registration without email verification lets anyone in'))
  }
  if (d.posture === 'production' && d.features.api_test_harness === 'yes') {
    out.push(warning('harnessInProduction', 'The API test harness belongs on a test frame, not a production one'))
  }
  if (d.hosting === 'self' && !opts.kitOffered) out.push(warning('selfHosted', 'Running a frame on your own infrastructure waits for the open-source release'))
  return out
}

const FEDERATION_CHOICE: Record<NetworkIntent, 'A' | 'B' | 'C'> = {
  federate_later: 'A', standalone: 'B', standalone_test_operator: 'C',
}

/** The body POST /operators/request-frame takes. Empty groups are left out; the answers stay far under the 8 KB bound. */
export function buildRequestPayload(d: FrameRequestDraft, domain = FRAME_DOMAIN): FrameRequestCreate {
  const name = d.frame_name.trim()
  const hostname = d.hostname.trim().toLowerCase()
  const answers: FrameRequestAnswers = {}

  const features = changedFeatures(d.features)
  if (Object.keys(features).length) answers.features = features

  const treasury: NonNullable<FrameRequestAnswers['treasury']> = {}
  const mint = wholeNumber(d.mint)
  const grant = wholeNumber(d.genesis_grant)
  if (mint !== null) treasury.mint = String(mint)
  if (grant !== null) treasury.genesis_grant = String(grant)
  if (Object.keys(treasury).length) answers.treasury = treasury

  const card: NonNullable<FrameRequestAnswers['card']> = { theme: d.theme }
  if (d.description.trim()) card.description = d.description.trim()
  if (d.website.trim()) card.website = d.website.trim()
  if (d.location.trim()) card.location = d.location.trim()
  const lat = coordinate(d.lat)
  const lng = coordinate(d.lng)
  if (lat !== null && lng !== null) {
    card.lat = lat
    card.lng = lng
  }
  const tags = d.tags.map(tag => tag.trim()).filter(Boolean)
  if (tags.length) card.tags = tags
  answers.card = card

  answers.network = { intent: d.intent }
  if (d.intent === 'federate_later' && d.partners.length) answers.network.partners = [...d.partners]
  if (d.intent === 'federate_later' && d.licence_category) answers.network.licence_category = d.licence_category
  answers.provisioning = { hosting: d.hosting, posture: d.posture, operators: d.operators }

  const payload: FrameRequestCreate = {
    organization: d.organization.trim(),
    contact_name: d.contact_name.trim(),
    email: d.email.trim(),
    create_account: d.create_account,
    accept_terms: d.accept_terms === true,
    frame_name: name,
    display_name: d.display_name.trim(),
    trust_domain: d.hosting === 'self' ? hostname : `${name}.${domain}`,
    ticker: d.ticker.trim(),
    currency_name: d.currency_name.trim(),
    federation_choice: FEDERATION_CHOICE[d.intent],
    use_case: d.use_case.trim(),
    answers,
  }
  if (d.hosting === 'self') payload.hostname = hostname
  if (d.notes.trim()) payload.notes = d.notes.trim()
  return payload
}

export function isPristine(d: FrameRequestDraft): boolean {
  return JSON.stringify(d) === JSON.stringify(blankDraft())
}

export function serializeDraft(d: FrameRequestDraft, step: number): string {
  return JSON.stringify({ v: DRAFT_VERSION, step, draft: d })
}

const ENUMS: Partial<Record<DraftField, readonly string[]>> = {
  hosting: ['theprotocol', 'self'],
  theme: ['neural', 'sovereign'],
  intent: ['federate_later', 'standalone', 'standalone_test_operator'],
  licence_category: ['', ...LICENCE_CATEGORIES],
  posture: ['pilot', 'production'],
}

/** A saved draft read back: only known fields of the right type, valid enum values and catalog options; else null. */
export function restoreDraft(raw: string | null): { draft: FrameRequestDraft; step: number } | null {
  if (!raw) return null
  let doc: any
  try {
    doc = JSON.parse(raw)
  } catch {
    return null
  }
  if (!doc || doc.v !== DRAFT_VERSION || typeof doc.draft !== 'object' || doc.draft === null) return null
  const draft = blankDraft()
  // V0363 called the first stage "sandbox" (the frame runner's posture flag); a draft saved then still says so.
  const src = { ...(doc.draft as Record<string, unknown>) }
  if (src.posture === 'sandbox') src.posture = 'pilot'
  const target = draft as unknown as Record<string, unknown>
  for (const key of Object.keys(draft) as DraftField[]) {
    const want = draft[key]
    const got = src[key]
    if (key === 'features') {
      if (got && typeof got === 'object') {
        for (const sw of FRAME_FEATURE_SWITCHES) {
          const value = (got as Record<string, unknown>)[sw.key]
          if (typeof value === 'string' && sw.options.includes(value)) draft.features[sw.key] = value
        }
      }
    } else if (Array.isArray(want)) {
      if (Array.isArray(got) && got.every(x => typeof x === 'string')) target[key] = (got as string[]).slice(0, 16)
    } else if (typeof got === typeof want) {
      const allowed = ENUMS[key]
      if (!allowed || allowed.includes(got as string)) target[key] = got
    }
  }
  const step = Number.isInteger(doc.step) ? Math.min(Math.max(doc.step, 0), STEPS.length - 1) : 0
  return isPristine(draft) ? null : { draft, step }
}

export interface NetworkRegistry {
  registry_name?: string | null
  peer_type?: string | null
  public_url?: string | null
}
export interface PartnerOption {
  name: string
  url: string
  self: boolean
}

/** The frames a request may name as later partners: this frame first, then its peer frames. Operators are not frames. */
export function partnerOptions(registries: NetworkRegistry[], self: { name?: string | null; url?: string | null } | null): PartnerOption[] {
  const out = new Map<string, PartnerOption>()
  if (self?.name) out.set(self.name.toLowerCase(), { name: self.name, url: self.url || '', self: true })
  for (const r of registries) {
    const name = (r.registry_name || '').trim()
    if (r.peer_type !== 'frame' || !name || out.has(name.toLowerCase())) continue
    out.set(name.toLowerCase(), { name, url: r.public_url || '', self: false })
  }
  return [...out.values()].sort((a, b) => Number(b.self) - Number(a.self) || a.name.localeCompare(b.name))
}

/** Every name the network already answers on (frames and operators), for the name rule. */
export function networkNames(registries: NetworkRegistry[], selfName?: string | null): string[] {
  const names = registries.map(r => (r.registry_name || '').trim().toLowerCase()).filter(Boolean)
  if (selfName) names.push(selfName.trim().toLowerCase())
  return [...new Set(names)]
}

/** The latitude band the form's map shows: the self-hosted basemap is Web Mercator, and the poles waste the height. */
export const MAP_BAND = { north: 75, south: -55 } as const

const mercatorY = (lat: number): number => {
  const phi = (Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180
  return (1 - Math.log(Math.tan(Math.PI / 4 + phi / 2)) / Math.PI) / 2
}
const latitudeAt = (y: number): number => (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI

/** Where a band of latitudes sits on the whole Web Mercator square, as fractions of its height (0 = top). */
export function mercatorBandRange(band: { north: number; south: number } = MAP_BAND): { top: number; bottom: number } {
  return { top: mercatorY(band.north), bottom: mercatorY(band.south) }
}

/** A point on a Web Mercator map of the given size that shows the band's latitudes (the self-hosted basemap tiles). */
export function toMapPoint(
  lat: number, lng: number, width: number, height: number, band: { north: number; south: number } = MAP_BAND,
): { x: number; y: number } {
  const { top, bottom } = mercatorBandRange(band)
  const y = ((mercatorY(lat) - top) / (bottom - top)) * height
  return { x: ((lng + 180) / 360) * width, y: Math.min(height, Math.max(0, y)) }
}

/** The coordinates under a point of that map, rounded to two decimals and clamped to the band and the globe. */
export function fromMapPoint(
  x: number, y: number, width: number, height: number, band: { north: number; south: number } = MAP_BAND,
): { lat: number; lng: number } {
  const { top, bottom } = mercatorBandRange(band)
  const fraction = top + (Math.min(height, Math.max(0, y)) / height) * (bottom - top)
  const lng = Math.min(180, Math.max(-180, (x / width) * 360 - 180))
  return { lat: Math.round(latitudeAt(fraction) * 100) / 100, lng: Math.round(lng * 100) / 100 }
}

export interface ProvisioningPrefill {
  name?: string
  frame_label?: string
  ticker?: string
  currency_name?: string
  mint?: number
  theme?: FrameTheme
  description?: string
  operator_label?: string
  location_label?: string
  lat?: number
  lng?: number
  website?: string
}

/** What the admin panel's provisioning form takes from a stored request (rows from before the rebuild included). */
export function provisioningPrefill(r: FrameRequestAdminRead): ProvisioningPrefill {
  const card = r.answers?.card || {}
  const out: ProvisioningPrefill = {}
  if (r.frame_name) out.name = r.frame_name
  if (r.display_name) out.frame_label = r.display_name.slice(0, LIMITS.display_name)
  if (r.ticker) out.ticker = r.ticker
  if (r.currency_name) out.currency_name = r.currency_name.slice(0, LIMITS.currency_name)
  const mint = wholeNumber(String(r.answers?.treasury?.mint ?? ''))
  if (mint !== null && mint > 0) out.mint = mint
  if (card.theme === 'neural' || card.theme === 'sovereign') out.theme = card.theme
  const description = String(card.description || r.use_case || '').trim()
  if (description) out.description = description.slice(0, LIMITS.description)
  const operator = String(r.organization || r.contact_name || '').trim()
  if (operator) out.operator_label = operator.slice(0, 80)
  if (card.location) out.location_label = String(card.location).slice(0, LIMITS.location)
  const lat = coordinate(String(card.lat ?? ''))
  const lng = coordinate(String(card.lng ?? ''))
  if (lat !== null && lng !== null) {
    out.lat = lat
    out.lng = lng
  }
  if (card.website && isHttpsUrl(String(card.website))) out.website = String(card.website)
  return out
}

/** A stored request's tags, whichever shape the row carries. */
export function requestTags(r: FrameRequestAdminRead): string[] {
  const tags = r.answers?.card?.tags
  if (Array.isArray(tags)) return tags
  return typeof tags === 'string' ? tags.split(',').map(t => t.trim()).filter(Boolean) : []
}
