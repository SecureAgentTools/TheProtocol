/**
 * V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7): the MCP tester's Coverage tab.
 * From GET /admin/mcp-tester/coverage:
 *   - a card per target with its own counts (success, refusal only, not measured, failed of its tools) and its run;
 *     no count summed across targets;
 *   - a newer run still in flight is named on its target's card;
 *   - a table of the tools, a column per target: the class in words, the reason, a dash where a target does not list
 *     the tool; the gaps by default, "all" shows every tool, a search narrows;
 *   - a coverage that could not be read says so; a tester with no run says so in the server's words; Refresh reads again.
 * Red on 3f729e7c9: the component does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))

import McpCoverage from './McpCoverage.vue'

const A = 'flow_mcp_lifecycle_complete@sbx-alpha-registry:8000'
const B = 'flow_mcp_lifecycle_complete@nt261113a-registry:8000'
const ANSWER = {
  note: null,
  targets: [
    { key: A, run_id: '27c26bffae1b47e4', label: 'MCP Tester — sandbox-A', target: 'sbx-alpha-registry:8000', flow_name: 'flow_mcp_lifecycle_complete',
      started_at: 1763002800, finished_at: 1763003165, newer: { run_id: '9f00aa11bb22cc33', status: 'running', started_at: 1763090000 },
      counts: { tools: 777, failed: 0, success: 666, refusal_only: 42, not_measured: 69 } },
    { key: B, run_id: 'af9acb641ba64fe6', label: 'MCP Tester — sandbox-A', target: 'nt261113a-registry:8000', flow_name: 'flow_mcp_lifecycle_complete',
      started_at: 1762995600, finished_at: 1762995697, newer: null,
      counts: { tools: 755, failed: 0, success: 665, refusal_only: 28, not_measured: 62 } },
  ],
  tools: [
    { tool: 'getQuantumWorkload', tier: 'public', worst: 'refusal_only', by_target: {
      [A]: { class: 'refusal_only', reason: 'refusal only: the tool passed on a refusal', status: 404 }, [B]: { class: 'not_listed' } } },
    { tool: 'listFederationRegistryCards', tier: 'admin', worst: 'not_measured', by_target: {
      [A]: { class: 'not_measured', reason: 'NOT MEASURED: a federation peer reads it', status: 0 },
      [B]: { class: 'not_measured', reason: 'NOT MEASURED: a federation peer reads it', status: 0 } } },
    { tool: 'getMyBalance', tier: 'agent', worst: 'success', by_target: {
      [A]: { class: 'success', reason: '', status: 200 }, [B]: { class: 'success', reason: '', status: 200 } } },
  ],
}

async function page() {
  const w = mount(McpCoverage)
  await flushPromises()
  return w
}

describe('the Coverage tab', () => {
  beforeEach(() => { h.get.mockReset() })

  it('a card per target with its own counts and run, nothing summed', async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    expect(h.get).toHaveBeenCalledWith('/admin/mcp-tester/coverage')
    const cards = w.findAll('[data-testid="cov-target"]')
    expect(cards.map((c) => c.attributes('data-key'))).toEqual([A, B])
    expect(cards[0].find('[data-testid="cov-count-refusal_only"]').text()).toContain('42')
    expect(cards[1].find('[data-testid="cov-count-refusal_only"]').text()).toContain('28')
    expect(cards[0].text()).toContain('27c26bff')
    expect(w.find('[data-testid="cov-total"]').exists()).toBe(false)
    expect(w.text()).not.toContain('70')   // 42 + 28 is said nowhere
  })

  it('a newer run in flight is named on its card', async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    const cards = w.findAll('[data-testid="cov-target"]')
    expect(cards[0].find('[data-testid="cov-newer"]').text()).toContain('9f00aa11')
    expect(cards[1].find('[data-testid="cov-newer"]').exists()).toBe(false)
  })

  it('the table shows the gaps by default, a column per target, a dash where a target does not list the tool', async () => {
    h.get.mockResolvedValue({ data: ANSWER })
    const w = await page()
    const rows = w.findAll('[data-testid="cov-row"]')
    expect(rows.map((r) => r.attributes('data-tool'))).toEqual(['getQuantumWorkload', 'listFederationRegistryCards'])
    const cells = rows[0].findAll('[data-testid="cov-cell"]')
    expect(cells.map((c) => c.attributes('data-class'))).toEqual(['refusal_only', 'not_listed'])
    expect(cells[0].text()).toContain('refusal only: the tool passed on a refusal')
    expect(cells[1].text()).toContain('—')
    await w.find('[data-testid="cov-show-all"]').trigger('click')
    expect(w.findAll('[data-testid="cov-row"]')).toHaveLength(3)
    await w.find('[data-testid="cov-search"]').setValue('balance')
    expect(w.findAll('[data-testid="cov-row"]').map((r) => r.attributes('data-tool'))).toEqual(['getMyBalance'])
  })

  it('a coverage that could not be read says so; Refresh reads again', async () => {
    h.get.mockRejectedValue({ response: { status: 503 } })
    const w = await page()
    expect(w.find('[data-testid="cov-error"]').exists()).toBe(true)
    expect(w.findAll('[data-testid="cov-target"]')).toHaveLength(0)
    h.get.mockResolvedValue({ data: ANSWER })
    await w.find('[data-testid="cov-refresh"]').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-testid="cov-target"]')).toHaveLength(2)
    expect(w.find('[data-testid="cov-error"]').exists()).toBe(false)
  })

  it('a tester with no run says so in the server words', async () => {
    h.get.mockResolvedValue({ data: { targets: [], tools: [], note: 'The tester holds no completed MCP run.' } })
    const w = await page()
    expect(w.find('[data-testid="cov-note"]').text()).toContain('holds no completed MCP run')
  })
})

describe('the tester page carries the tab', () => {
  it('a Coverage tab that mounts the view', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '../../views/AdminMcpTester.vue'), 'utf8')
    expect(src).toMatch(/TAB_IDS: readonly TabId\[\] = \[[^\]]*'coverage'/)
    expect(src).toMatch(/v-if="activeTab === 'coverage'"[\s\S]{0,200}<McpCoverage/)
    expect(src).toContain("{ id: 'coverage' as const")
  })
})
