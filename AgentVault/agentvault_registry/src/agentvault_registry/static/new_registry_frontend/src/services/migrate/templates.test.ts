import { describe, it, expect } from 'vitest'
import { DETAIL, FREE_LISTING, LISTING, STRUCTURE } from './m4Shapes.fixture'
import {
  kindWords, priceWords, listQuery, matchesFilters, tryItFree, writeYourOwn, readmeHtml, normalizeListing, normalizeDetail, decimalWords,
  DEFAULT_FILTERS, type TemplateListing,
} from './templates'

/** V0664 M5 (order gwo_5a4ea8476b97147f3056405e): the pure half of the Migrate console. The routes, the field names and the commands
 *  are the contract's (sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md §C, §D): /api/v1/workflow-templates, `tp-proxy migrate`. */
const free: TemplateListing = {
  id: 'wtpl_1', slug: 'crm-customers-to-postgres', title: 'Customers from a CRM table to PostgreSQL', summary: 'One table to one table',
  kind: 'migration', from_kind: 'sql', to_kind: 'sql', owner_agent_did: 'did:a:1', visibility: 'public', pricing_model: 'free',
  price: '0', price_currency: 'AVT', fork_share_bps: 2000, forked_from_template_id: null, current_version: 3,
  uses: 12, used_by: 6, certified: 4, forks: 2,
}
const paid: TemplateListing = { ...free, id: 'wtpl_2', slug: 'erp-orders-to-rest', title: 'ERP orders to a REST API', from_kind: 'sql', to_kind: 'rest', pricing_model: 'purchase', price: '25' }

describe('words', () => {
  it('names a kind in plain words', () => {
    expect(kindWords('sql')).toBe('a SQL database')
    expect(kindWords('file')).toBe('files')
    expect(kindWords('rest')).toBe('a REST API')
    expect(kindWords('weird')).toBe('weird')
  })
  it('says free or the price with its unit', () => {
    expect(priceWords(free)).toBe('Free')
    expect(priceWords(paid)).toBe('25 AVT')
  })
})

describe('the gallery filters', () => {
  it('sends only what is set, with the contract names (kind, from, to, pricing, q, sort)', () => {
    expect(listQuery(DEFAULT_FILTERS)).toEqual({ kind: 'migration', sort: 'new' })
    expect(listQuery({ from: 'sql', to: 'rest', price: 'paid', q: ' erp ', sort: 'uses' }))
      .toEqual({ kind: 'migration', from: 'sql', to: 'rest', pricing: 'purchase', q: 'erp', sort: 'uses' })
    expect(listQuery({ ...DEFAULT_FILTERS, price: 'free' }).pricing).toBe('free')
  })
  it('filters a list the same way when the registry answers with everything', () => {
    const all = [free, paid]
    expect(all.filter((t) => matchesFilters(t, { ...DEFAULT_FILTERS, to: 'rest' })).map((t) => t.id)).toEqual(['wtpl_2'])
    expect(all.filter((t) => matchesFilters(t, { ...DEFAULT_FILTERS, price: 'free' })).map((t) => t.id)).toEqual(['wtpl_1'])
    expect(all.filter((t) => matchesFilters(t, { ...DEFAULT_FILTERS, q: 'ORDERS' })).map((t) => t.id)).toEqual(['wtpl_2'])
    expect(all.filter((t) => matchesFilters(t, DEFAULT_FILTERS))).toHaveLength(2)
  })
})

describe('Try it free', () => {
  it('is install, get the kit, dry-run its sample (all three need no account and no system), then the same against their own system read-only', () => {
    const c = tryItFree({ ref: 'crm-customers-to-postgres', registry: 'https://eu.theprotocol.cloud', parameters: ['SOURCE_PASSWORD', 'SOURCE_ENGINE'] })
    expect(c).toHaveLength(4)
    expect(c[0]).toBe('pip install "theprotocol-sdk[proxy]"')
    expect(c[1]).toBe('tp-proxy migrate get crm-customers-to-postgres --registry https://eu.theprotocol.cloud --out crm-customers-to-postgres')
    expect(c[2]).toBe('tp-proxy migrate dry-run crm-customers-to-postgres --sample')
    expect(c[3]).toContain('tp-proxy migrate dry-run crm-customers-to-postgres')
    expect(c[3]).not.toContain('--sample')
    expect(c[3]).toContain('--set SOURCE_PASSWORD=env:SOURCE_PASSWORD')       // a secret is always an env reference, never typed
  })
  it('never offers a secret parameter any other way', () => {
    const c = tryItFree({ ref: 'x', registry: '', parameters: ['TARGET_TOKEN', 'API_KEY', 'PLAIN'] })
    expect(c[3]).toContain('--set TARGET_TOKEN=env:TARGET_TOKEN')
    expect(c[3]).toContain('--set API_KEY=env:API_KEY')
    expect(c[3]).not.toContain('PLAIN=')
  })
  it('write your own is new, check, publish', () => {
    const c = writeYourOwn()
    expect(c.map((l) => l.split(' ').slice(0, 3).join(' '))).toEqual(['tp-proxy migrate new', 'tp-proxy migrate check', 'tp-proxy migrate publish'])
  })
})

describe('what the registry answers (M4\'s shapes, exactly)', () => {
  it('reads a list item: the counts nested under counts, the price as a decimal without its trailing zeros', () => {
    const l = normalizeListing(LISTING)
    expect(l.uses).toBe(7)                           // kit_downloads
    expect(l.used_by).toBe(4)                        // instantiations
    expect(l.certified).toBe(2)
    expect(l.forks).toBe(1)
    expect(l.price).toBe('5')
    expect(priceWords(l)).toBe('5 AVT')
    expect(priceWords(normalizeListing(FREE_LISTING))).toBe('Free')
  })
  it('reads a listing with defaults for what an answer leaves out', () => {
    const l = normalizeListing({ id: 'wtpl_9', slug: 's', title: 'T', from_kind: 'file', to_kind: 'sql' })
    expect(l.pricing_model).toBe('free')
    expect([l.uses, l.used_by, l.certified, l.forks]).toEqual([0, 0, 0, 0])
    expect(l.price_currency).toBe('')
    expect(l.current_version).toBe(0)
  })
  it('reads the detail: the listing is the answer itself, the structure from the manifest, and never any files', () => {
    const d = normalizeDetail({ ...DETAIL, files: { 'proxy.yaml': 'secret mapping' } })
    expect(d.listing.id).toBe(LISTING.id)
    expect(d.listing.certified).toBe(2)
    expect(d.versions[0].version).toBe(1)
    expect(d.structure.steps.map((s) => s.key)).toEqual(['dry-run', 'reconcile'])
    expect(d.structure.steps[1].budget_share).toBe(60)
    expect(d.structure.parameter_names).toEqual(STRUCTURE.parameters)
    expect(d.structure.secret_parameters).toEqual(['SOURCE_PASSWORD'])
    expect(d.structure.connector_kinds).toEqual({ from: ['sql'], to: ['sql'] })
    expect(d.structure.field_counts).toEqual({ customers: 3 })
    expect(d.structure.what).toEqual({ from: 'a customers table', to: 'public.customers' })
    expect([d.structure.samples, d.structure.cutover_steps, d.structure.rollback]).toEqual([1, 4, 'auto'])
    expect((d as any).files).toBeUndefined()
  })
  it('reads a null or broken structure and an empty answer as an empty one', () => {
    for (const raw of [{}, { ...DETAIL, structure: null }, null, 'x']) {
      const d = normalizeDetail(raw)
      expect(d.structure.steps).toEqual([])
      expect(d.structure.field_counts).toEqual({})
    }
    expect(normalizeDetail({}).versions).toEqual([])
  })
  it('says a decimal without the zeros the column pads it with', () => {
    expect(decimalWords('5.0000000000')).toBe('5')
    expect(decimalWords('2.5000')).toBe('2.5')
    expect(decimalWords('0')).toBe('0')
    expect(decimalWords('12.340')).toBe('12.34')
    expect(decimalWords('x')).toBe('x')
  })
})

describe('the README', () => {
  it('is rendered through the sanitizing renderer, never as raw markup', () => {
    const html = readmeHtml('# Title\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[a](javascript:alert(1)) and [ok](https://example.org)')
    // raw markup is text (escaped), never an element; a javascript: address never becomes a link
    expect(html).not.toMatch(/<script/i)
    expect(html).not.toMatch(/<img/i)
    expect(html).not.toMatch(/href="javascript:/i)
    expect(html).not.toMatch(/<[a-z][^>]*\son[a-z]+=/i)
    expect(html).toContain('href="https://example.org"')
  })
})
