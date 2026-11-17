import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./client', () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }))
import { apiClient } from './client'
import { listTemplates, getTemplate, getVersion, purchaseTemplate, forkTemplate, instantiateTemplate, createTemplate, publishVersion } from './workflowTemplates'
import { DEFAULT_FILTERS } from '@/services/migrate/templates'
import { DETAIL, FORKED, INSTANTIATED, LISTING, VERSION } from '@/services/migrate/m4Shapes.fixture'

const get = apiClient.get as unknown as ReturnType<typeof vi.fn>
const post = apiClient.post as unknown as ReturnType<typeof vi.fn>

/** V0664 M5: the client speaks M4's routes and answers exactly (sessionlogs2026/M4_ANSWER_SHAPES_2026-11-14.md). */
beforeEach(() => { get.mockReset(); post.mockReset() })

describe('the template library client', () => {
  it('lists with the contract query and reads {items: [...]}, a bare list too, and drops a row with no id or title', async () => {
    get.mockResolvedValue({ data: { items: [LISTING, { slug: 'no-id-or-title' }] } })
    const rows = await listTemplates({ ...DEFAULT_FILTERS, price: 'free', from: 'sql' })
    expect(get).toHaveBeenCalledWith('/workflow-templates', { params: { kind: 'migration', from: 'sql', pricing: 'free', sort: 'new' } })
    expect(rows.map((r) => r.id)).toEqual([LISTING.id])
    expect(rows[0].uses).toBe(7)
    get.mockResolvedValue({ data: [{ id: 'wtpl_2', slug: 's2', title: 'T2' }] })
    expect((await listTemplates(DEFAULT_FILTERS))[0].id).toBe('wtpl_2')
    get.mockResolvedValue({ data: 'not a list' })
    expect(await listTemplates(DEFAULT_FILTERS)).toEqual([])                  // a non-list is none
  })
  it('reads one template page: the listing is the answer itself', async () => {
    get.mockResolvedValue({ data: DETAIL })
    const d = await getTemplate(LISTING.id)
    expect(get).toHaveBeenCalledWith(`/workflow-templates/${LISTING.id}`)
    expect(d.listing.title).toBe('CRM to Postgres')
    expect(d.structure.steps[0].key).toBe('dry-run')
  })
  it('reads a version\'s files from the version route (the kit route counts a download; a page view must not) and keeps only text files', async () => {
    get.mockResolvedValue({ data: { ...VERSION, files: { ...VERSION.files, bad: 5 } } })
    const k = await getVersion(LISTING.id, 1)
    expect(get).toHaveBeenCalledWith(`/workflow-templates/${LISTING.id}/versions/1`)
    expect(Object.keys(k.files)).toEqual(Object.keys(VERSION.files))
    expect(k.content_hash).toBe(VERSION.content_hash)
  })
  it('buys (bought, again, owner all read as done), forks (template_id) and instantiates (a budget is required)', async () => {
    for (const body of [{ ok: true, template_id: 'x', price: '5', currency: 'AVT', parent_share: null }, { ok: true, already: 'purchased' }, { ok: true, already: 'owner' }]) {
      post.mockResolvedValue({ data: body })
      expect((await purchaseTemplate(LISTING.id)).ok).toBe(true)
    }
    expect(post).toHaveBeenLastCalledWith(`/workflow-templates/${LISTING.id}/purchase`, {})
    post.mockResolvedValue({ data: FORKED })
    expect((await forkTemplate(LISTING.id)).id).toBe(FORKED.template_id)
    expect(post).toHaveBeenLastCalledWith(`/workflow-templates/${LISTING.id}/fork`, {})
    post.mockResolvedValue({ data: INSTANTIATED })
    expect((await instantiateTemplate(LISTING.id, { total_budget: 30 })).workflow_id).toBe('wf_1')
    expect(post).toHaveBeenLastCalledWith(`/workflow-templates/${LISTING.id}/instantiate`, { total_budget: 30 })
  })
  it('creates a private free draft from the kit\'s files and publishes a version on the registry\'s routes', async () => {
    post.mockResolvedValue({ data: { template_id: 'wtpl_9', version: 1, content_hash: 'h', published: false } })
    const r = await createTemplate({ slug: 'orders-to-pg', title: 'Orders', files: { 'migration.yaml': 'x' } })
    expect(post).toHaveBeenLastCalledWith('/workflow-templates', { kind: 'migration', visibility: 'private', pricing_model: 'free', slug: 'orders-to-pg', title: 'Orders', files: { 'migration.yaml': 'x' } }, { expectedStatuses: [400, 402, 403, 409, 422, 429] })
    expect(r).toEqual({ template_id: 'wtpl_9', version: 1, content_hash: 'h', published: false })
    post.mockResolvedValue({ data: { published: true } })
    expect((await publishVersion('wtpl_9', 1)).published).toBe(true)
    expect(post).toHaveBeenLastCalledWith('/workflow-templates/wtpl_9/versions/1/publish', {}, { expectedStatuses: [400, 402, 403, 409, 422, 429] })
  })
})
