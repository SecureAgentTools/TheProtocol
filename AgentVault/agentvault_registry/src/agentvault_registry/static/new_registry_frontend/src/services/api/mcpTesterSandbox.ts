/**
 * §TESTBED (2026-09-19): the MCP tester view's sandbox panel. `/admin/mcp-tester/sandbox/*` passes each request to the
 * host's frame runner, which provisions this frame's sandbox with the export's own tools (frame-up, frame-federate, each
 * cloud operator through its sandbox's own admin API). A registry with no runner that offers sandboxes answers
 * `available: false` with the reason.
 */
import { apiClient } from './client'
import type { JobState, ProgressEvent } from './frameRunner'

export interface SandboxTopology {
  frames: 1 | 2
  operators: boolean
  estimate_mib: number
}

export interface SandboxEntry {
  name: string
  public_name?: string
  console?: string
  tester?: string
  edge_health?: number | null
}

export interface SandboxJob {
  id: string
  op: 'sandbox_up' | 'sandbox_down' | string
  name: string
  state: JobState
  created?: string
  ended?: string | null
  exit_code?: number | null
  request?: { frames?: number; operators?: boolean } | null
}

export interface SandboxStatus {
  available: boolean
  frame: string
  reason?: 'no_runner' | 'refused' | 'is_sandbox'
  /** reason `is_sandbox`: the frame whose sandbox this is */
  parent?: string
  why?: string
  supported?: boolean
  sandboxes?: SandboxEntry[]
  job?: SandboxJob | null
  last_event?: ProgressEvent | null
  topologies?: SandboxTopology[]
  host?: { problems: string[]; mem_available_gib: number | null; busy: { id: string; op: string; name: string } | null }
}

export interface SandboxJobEvents {
  job: SandboxJob | null
  events: ProgressEvent[]
  next: number
}

export interface SandboxLogin {
  sandbox: string
  console?: string
  email: string
  password: string
}

export const mcpTesterSandboxApi = {
  async status(): Promise<SandboxStatus> {
    const { data } = await apiClient.get<SandboxStatus>('/admin/mcp-tester/sandbox')
    return data
  },
  async provision(frames: 1 | 2, operators: boolean): Promise<{ started: boolean; job: SandboxJob | null }> {
    const { data } = await apiClient.post('/admin/mcp-tester/sandbox', { frames, operators })
    return data
  },
  async teardown(): Promise<{ started: boolean; job: SandboxJob | null }> {
    const { data } = await apiClient.post('/admin/mcp-tester/sandbox/teardown', {})
    return data
  },
  async events(jobId: string, after = 0): Promise<SandboxJobEvents> {
    const { data } = await apiClient.get<SandboxJobEvents>(`/admin/mcp-tester/sandbox/jobs/${jobId}/events`, { params: { after } })
    return data
  },
  async reveal(which: 'a' | 'b'): Promise<SandboxLogin> {
    const { data } = await apiClient.post<SandboxLogin>('/admin/mcp-tester/sandbox/reveal', { which })
    return data
  },
}
