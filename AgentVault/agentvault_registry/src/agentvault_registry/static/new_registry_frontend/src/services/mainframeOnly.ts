/**
 * D6-820 (V0640): ONE reading of "this registry refused because the route runs on sovereign mainframes only".
 *
 * A registry that is not a sovereign mainframe refuses a frame-only route with 404 and a `detail` that starts with the
 * code word `mainframe_only:` (core/mainframe_gate.mainframe_only_refusal). A registry before V0640 answered 503 with
 * the bare sentence ("This feature runs on sovereign mainframes only. ..."), so a console one release apart from its
 * registry reads both forms. Any other answer is NOT this refusal: the console used to read every 503 as
 * "mainframe-only", which also named an outage (a 502/503 from the proxy, a pool that is down) a design decision.
 */
export const MAINFRAME_ONLY_CODE = 'mainframe_only'
const LEGACY_SENTENCE = 'runs on sovereign mainframes only'

/** The `detail` of an error body: the legacy top-level string, else the RFC 7807 `error.detail`; '' when neither. */
export function refusalDetail(data: unknown): string {
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    const d = (data as { detail?: unknown }).detail
    if (typeof d === 'string') return d
    const e = (data as { error?: { detail?: unknown } }).error
    if (e && typeof e === 'object' && typeof e.detail === 'string') return e.detail
  }
  return ''
}

/** True when an axios-shaped error is the mainframe-only refusal, in either form. */
export function isMainframeOnlyRefusal(err: unknown): boolean {
  const response = (err as { response?: { status?: number; data?: unknown } } | null)?.response
  if (!response) return false
  const detail = refusalDetail(response.data)
  if (response.status === 404) return detail.startsWith(`${MAINFRAME_ONLY_CODE}:`)
  if (response.status === 503) return detail.includes(LEGACY_SENTENCE)
  return false
}
