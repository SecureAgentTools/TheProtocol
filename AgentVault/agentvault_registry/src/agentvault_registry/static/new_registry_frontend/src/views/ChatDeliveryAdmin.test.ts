/**
 * V0663 (order gwo_01681f32a8cfe7390b773532, his suggestion 6): the admins' chat delivery panel (#/admin/chat-delivery,
 * behind the federation admin flag). Per peer, from GET /admin/chat/federation/delivery: the verdict (given up, late,
 * waiting, clear), the rows waiting and the age of the oldest, the most attempts, the next attempt, the latest error
 * and the last delivery; the worker's last cycle and when this was read. A stuck delivery is the first line and says so.
 *   - a panel that could not be read says so, never "nothing waiting";
 *   - cross-registry chat switched off is said in words;
 *   - Refresh reads again.
 * Red on 117911286: the page does not exist.
 *
 * V0664 (order gwo_efdd53bd198423a5ec2b742d): the panel can act on one stuck row. A peer's rows open from its line
 * (GET /admin/chat/federation/delivery/rows), each with its state; Retry now and Drop are offered only where the server
 * says the row may take them (can_retry, can_drop); a drop asks for its reason first and sends it; after either the
 * panel and the rows are read again; a refusal is shown in the server's words. Red on b7ca684e9.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get, post: h.post }, apiClient: { get: h.get, post: h.post } }))

import ChatDeliveryAdmin from './ChatDeliveryAdmin.vue'

const ANSWER = {
  enabled: true, as_of: '2026-11-14T01:00:00+00:00', late_seconds: 120, max_attempts: 12,
  worker: { cycles: 812, delivered: 4200, failed: 3, at: '2026-11-14T00:59:58+00:00' },
  peers: [
    { peer_base_url: 'https://lisbon.example.org', name: 'lisbon', active_peer: true, waiting: 2, oldest_waiting_at: '2026-11-13T22:00:00+00:00',
      oldest_age_seconds: 10800, attempts_max: 12, given_up: 1, next_attempt_at: null, last_error: 'ConnectError: no answer',
      last_delivered_at: '2026-11-13T21:00:00+00:00', verdict: 'given_up' },
    { peer_base_url: 'https://asia.example.org', name: 'asia-registry', active_peer: true, waiting: 0, oldest_waiting_at: null,
      oldest_age_seconds: null, attempts_max: 0, given_up: 0, next_attempt_at: null, last_error: null,
      last_delivered_at: '2026-11-14T00:59:00+00:00', verdict: 'clear' },
  ],
}

async function page() {
  const w = mount(ChatDeliveryAdmin)
  await flushPromises()
  return w
}

describe('the chat delivery panel', () => {
  beforeEach(() => { h.get.mockReset() })   // braces: a returned function would run as a cleanup hook

  it('lists each peer with its verdict, the worst first', async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    expect(h.get).toHaveBeenCalledWith('/admin/chat/federation/delivery')
    const rows = w.findAll('[data-testid="cdp-row"]')
    expect(rows.map((r) => r.attributes('data-verdict'))).toEqual(['given_up', 'clear'])
    expect(rows[0].text()).toContain('lisbon')
    expect(rows[0].text()).toContain('ConnectError: no answer')
    expect(rows[0].find('[data-testid="cdp-age"]').text()).toMatch(/3\s*h/)
  })

  it('says at the top when something is stuck', async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    expect(w.find('[data-testid="cdp-headline"]').attributes('data-state')).toBe('stuck')
    h.get.mockResolvedValue({ data: { ...ANSWER, peers: [ANSWER.peers[1]] } })
    await w.find('[data-testid="cdp-refresh"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="cdp-headline"]').attributes('data-state')).toBe('clear')
  })

  it("shows the worker's last cycle and when this was read", async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    expect(w.find('[data-testid="cdp-worker"]').text()).toContain('812')
  })

  it('a panel that could not be read says so', async () => {
    h.get.mockRejectedValue({ response: { status: 503, data: { detail: 'down' } } })
    const w = await page()
    expect(w.find('[data-testid="cdp-error"]').exists()).toBe(true)
    expect(w.findAll('[data-testid="cdp-row"]').length).toBe(0)
  })

  it('cross-registry chat switched off is said in words', async () => {
    h.get.mockResolvedValue({ data: { ...ANSWER, enabled: false, peers: [] } })
    const w = await page()
    expect(w.find('[data-testid="cdp-off"]').exists()).toBe(true)
  })
})

describe('the panel is an admin page behind the federation flag', () => {
  it('has its route and its Administration entry', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const router = fs.readFileSync(path.resolve(__dirname, '../router/index.ts'), 'utf8')
    expect(router).toMatch(/path: 'admin\/chat-delivery'[\s\S]{0,200}requiresRole: 'admin', requiresAdminFlag: 'federation'/)
    const nav = fs.readFileSync(path.resolve(__dirname, '../services/nav/navTable.ts'), 'utf8')
    expect(nav).toContain("path: '/admin/chat-delivery'")
  })
})

const ROWS = {
  peer_base_url: 'https://lisbon.example.org', max_attempts: 12,
  rows: [
    { id: 'r1', kind: 'message', conversation_id: 'c1', seq: 4, attempts: 12, next_attempt_at: null, last_error: 'ConnectError: no answer',
      created_at: '2026-11-13T22:00:00+00:00', state: 'given_up', held_by: null, can_retry: true, can_drop: true },
    { id: 'r2', kind: 'event', conversation_id: 'c1', seq: 5, attempts: 0, next_attempt_at: '2026-11-14T00:00:00+00:00', last_error: null,
      created_at: '2026-11-13T22:01:00+00:00', state: 'due', held_by: null, can_retry: false, can_drop: false },
  ],
}

function answers() {
  h.get.mockImplementation((url: string) => Promise.resolve({ data: url.endsWith('/rows') ? ROWS : ANSWER }))
}

async function opened() {
  answers()
  const w = await page()
  await w.find('[data-testid="cdp-open"]').trigger('click')
  await flushPromises()
  return w
}

describe('the panel acts on one stuck row', () => {
  beforeEach(() => { h.get.mockReset(); h.post.mockReset() })

  it("opens a peer's rows with their state", async () => {
    const w = await opened()
    expect(h.get).toHaveBeenCalledWith('/admin/chat/federation/delivery/rows', { params: { peer: 'https://lisbon.example.org' } })
    const items = w.findAll('[data-testid="cdp-item"]')
    expect(items.map((i) => i.attributes('data-state'))).toEqual(['given_up', 'due'])
    expect(items[0].text()).toContain('ConnectError: no answer')
  })

  it('offers Retry now and Drop only where the server allows them', async () => {
    const w = await opened()
    const items = w.findAll('[data-testid="cdp-item"]')
    expect(items[0].find('[data-testid="cdp-retry"]').attributes('disabled')).toBeUndefined()
    expect(items[0].find('[data-testid="cdp-drop"]').attributes('disabled')).toBeUndefined()
    expect(items[1].find('[data-testid="cdp-retry"]').attributes('disabled')).toBeDefined()
    expect(items[1].find('[data-testid="cdp-drop"]').attributes('disabled')).toBeDefined()
  })

  it('retries a row and reads the panel again', async () => {
    const w = await opened()
    h.post.mockResolvedValue({ data: { ok: true } })
    const before = h.get.mock.calls.length
    await w.findAll('[data-testid="cdp-item"]')[0].find('[data-testid="cdp-retry"]').trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledWith('/admin/chat/federation/delivery/rows/r1/retry')
    expect(h.get.mock.calls.length).toBeGreaterThan(before)
  })

  it('a drop asks for its reason first and sends it', async () => {
    const w = await opened()
    h.post.mockResolvedValue({ data: { ok: true } })
    await w.findAll('[data-testid="cdp-item"]')[0].find('[data-testid="cdp-drop"]').trigger('click')
    expect(h.post).not.toHaveBeenCalled()
    const confirm = w.find('[data-testid="cdp-drop-confirm"]')
    expect(confirm.attributes('disabled')).toBeDefined()
    await w.find('[data-testid="cdp-reason"]').setValue('the peer left the federation')
    expect(w.find('[data-testid="cdp-drop-confirm"]').attributes('disabled')).toBeUndefined()
    await w.find('[data-testid="cdp-drop-confirm"]').trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledWith('/admin/chat/federation/delivery/rows/r1/drop', { reason: 'the peer left the federation' })
  })

  it("a refusal is shown in the server's words", async () => {
    const w = await opened()
    h.post.mockRejectedValue({ response: { status: 409, data: { code: 'due_now', detail: 'the row is being tried now' } } })
    await w.findAll('[data-testid="cdp-item"]')[0].find('[data-testid="cdp-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="cdp-act-error"]').text()).toContain('the row is being tried now')
  })

  it('a peer line counts its dropped rows', async () => {
    h.get.mockResolvedValue({ data: { ...ANSWER, peers: [{ ...ANSWER.peers[1], dropped: 3 }] } })
    const w = await page()
    expect(w.find('[data-testid="cdp-dropped"]').text()).toContain('3')
  })
})
