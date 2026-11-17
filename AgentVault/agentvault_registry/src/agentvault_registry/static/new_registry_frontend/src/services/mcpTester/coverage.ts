// V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7): the MCP tester's coverage, per tool and per target,
// as GET /admin/mcp-tester/coverage answers it (routers/mcp_tester_coverage.py). The counts are per target and never
// summed: the same tool is refusal only on one target and reaches its success path on another.

export type CoverageClass = 'failed' | 'refusal_only' | 'not_measured' | 'success' | 'not_listed'

export interface CoverageCell { class: CoverageClass, reason?: string, status?: number | null }

export interface CoverageTool {
  tool: string
  tier: string
  worst: CoverageClass
  by_target: Record<string, CoverageCell>
}

export interface CoverageCounts { tools: number, failed: number, success: number, refusal_only: number, not_measured: number }

export interface CoverageTarget {
  key: string
  run_id: string
  label: string
  target: string
  flow_name: string
  started_at: number | null
  finished_at: number | null
  counts: CoverageCounts
  newer?: { run_id: string, status: string, started_at: number | null } | null
  rows_expired?: string
  pass_pct?: number | null
}

export interface CoverageAnswer { targets: CoverageTarget[], tools: CoverageTool[], note: string | null }

/** What the table shows: the gaps (the default), one class on any target, or every tool. */
export type CoverageShow = 'gaps' | 'failed' | 'refusal_only' | 'not_measured' | 'success' | 'all'

const GAPS: ReadonlySet<CoverageClass> = new Set(['failed', 'refusal_only', 'not_measured'])

export function filterTools(tools: CoverageTool[], o: { show: CoverageShow, tier?: string, query?: string }): CoverageTool[] {
  const q = (o.query || '').trim().toLowerCase()
  return tools.filter((t) => {
    const classes = Object.values(t.by_target || {}).map((c) => c.class)
    if (o.show === 'gaps' && !classes.some((c) => GAPS.has(c))) return false
    if (o.show !== 'gaps' && o.show !== 'all' && !classes.includes(o.show)) return false
    if (o.tier && t.tier !== o.tier) return false
    if (q && !t.tool.toLowerCase().includes(q)) return false
    return true
  })
}
