/**
 * §FRAMEPROV P3 (2026-09-13): the admin_platform rail to the host frame runner.
 *
 * The registry passes every call to a root service on the host (tools/frame-runner/ in the stack repo) that stands
 * sandbox frames up with a closed job set. A refusal is the runner's own sentence in `detail` (409). A registry that
 * cannot reach the runner says so in the status answer (`available: false` and the reason).
 */
import type { AxiosRequestConfig } from 'axios'
import { apiClient } from './client'

/** A plan runs the standup driver's read-only checks (about 3 s measured); the runner's own ceiling is 300 s. */
const LONG_TIMEOUT_MS = 330_000

/** Never retried by the client: a 5xx from this rail is an answer, and a repeated act could double it. */
const once = (extra: AxiosRequestConfig = {}): AxiosRequestConfig =>
  ({ ...extra, _retryConfig: { retries: 0, retryDelay: 0 } }) as AxiosRequestConfig

export type FrameTheme = 'neural' | 'sovereign'

/** The runner's closed spec (SPEC_FIELDS in frame_runner.py): every field, nothing else. */
export interface FrameSpec {
  name: string
  frame_label: string
  ticker: string
  currency_name: string
  mint: number
  theme: FrameTheme
  description: string
  operator_label: string
  location_label: string
  lat: number
  lng: number
  website: string
  registry_image: string
  teg_image: string
}

export interface RunnerInfo {
  version: string
  uid: number
  active: string | null
  domain: string
  images: { registry: string[]; teg: string[] }
  resumable_steps: string[]
  spec_fields: string[]
  /** the posture every frame this runner builds is born with (its policy; absent on an older runner) */
  posture?: 'production' | 'sandbox'
  /** whether the runner's policy names an outbound mail relay for the frames it builds */
  mail_relay?: boolean
}

export type JobState = 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled' | 'lost'

export interface RunnerJob {
  id: string
  // ⚠ NOT A CLOSED SET OF THREE. The runner also runs operator_provision, operator_status and
  // operator_teardown, and this union said they could not exist — which is part of why the page's
  // `op !== 'teardown'` looked exhaustive when it was not. A type that cannot describe the data is a
  // second copy of an assumption, and this one shipped a page claiming a failed job had 'not run'.
  op: 'standup' | 'resume' | 'teardown' | 'operator_provision' | 'operator_status' | 'operator_teardown'
  name: string
  state: JobState
  created: string
  ended?: string | null
  exit_code?: number | null
  // From the runner's job record (JOB_FIELDS). `refused` means exit 3: nothing was written and a re-run is
  // safe. `reason` is the runner's own one-line, token-redacted sentence, null unless the job failed,
  // was cancelled or was lost. Optional because a runner older than these fields simply omits them.
  refused?: boolean | null
  reason?: string | null
  request?: Record<string, unknown> | null
}

export interface RunnerFrame {
  name: string
  state: string
  stack_dir?: string
  spec?: Partial<FrameSpec>
  built_by_job?: string
  created?: string
  updated?: string
  revealed_at?: string | null
}

export interface RunnerStatus {
  available: boolean
  reason: string | null
  runner: RunnerInfo | null
  active: RunnerJob | null
  jobs: RunnerJob[]
  frames: RunnerFrame[]
}

export interface PlanDocument {
  ok: boolean
  refusals: string[]
  warnings: string[]
  derived: Record<string, unknown>
}

export interface PlanResult {
  exit_code: number
  plan_ok: boolean
  plan: PlanDocument | null
  stderr_tail?: string
}

/** A standup re-plans on the host before it starts: `started: false` carries that plan and its refusals. */
export interface StartResult extends Partial<PlanResult> {
  started: boolean
  job?: RunnerJob
}

export interface ProgressEvent {
  ts?: string
  step?: string
  event: string
  verdict?: string
  sentence?: string
  urls?: Record<string, string>
  [extra: string]: unknown
}

export interface JobEvents {
  events: ProgressEvent[]
  next: number
  state: JobState
}

export interface RevealedCredential {
  admin_email: string
  admin_password: string
  console: string
}

const base = '/admin/frame-runner'
const seg = (v: string) => encodeURIComponent(v)

export const frameRunnerService = {
  async status(): Promise<RunnerStatus> {
    return (await apiClient.get(`${base}/status`, once())).data
  },
  async plan(spec: FrameSpec): Promise<PlanResult> {
    return (await apiClient.post(`${base}/plan`, spec, once({ timeout: LONG_TIMEOUT_MS }))).data
  },
  async start(spec: FrameSpec): Promise<StartResult> {
    return (await apiClient.post(`${base}/jobs`, spec, once({ timeout: LONG_TIMEOUT_MS }))).data
  },
  async job(id: string): Promise<{ job: RunnerJob; last_event: ProgressEvent | null }> {
    return (await apiClient.get(`${base}/jobs/${seg(id)}`, once())).data
  },
  async events(id: string, after = 0): Promise<JobEvents> {
    return (await apiClient.get(`${base}/jobs/${seg(id)}/events`, once({ params: { after } }))).data
  },
  async cancel(id: string): Promise<{ cancelling: string }> {
    return (await apiClient.post(`${base}/jobs/${seg(id)}/cancel`, undefined, once())).data
  },
  async resume(name: string, fromStep: string): Promise<{ started: boolean; job: RunnerJob }> {
    return (await apiClient.post(`${base}/frames/${seg(name)}/resume`, { from_step: fromStep }, once())).data
  },
  async teardown(name: string): Promise<{ started: boolean; job: RunnerJob }> {
    return (await apiClient.post(`${base}/frames/${seg(name)}/teardown`, undefined, once())).data
  },
  async reveal(name: string): Promise<RevealedCredential> {
    return (await apiClient.post(`${base}/frames/${seg(name)}/reveal`, undefined, once())).data
  },
}
