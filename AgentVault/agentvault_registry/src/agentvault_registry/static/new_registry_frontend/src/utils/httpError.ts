/**
 * utils/httpError.ts — §FEFRAME W1: what an HTTP failure says, read the way the registry writes it. Pure (no router,
 * no store) so it is unit-tested; utils/errorHandler.ts uses it.
 */

/**
 * The sentence a person can read from an error body: RFC 7807 `detail` / `title`, the unified envelope's
 * `error.detail`, FastAPI's validation list, or the legacy `message`.
 */
export function messageOf(data: any, fallback?: string): string {
  if (typeof data === 'string' && data.trim() && data.length < 400) return data
  if (data && typeof data === 'object') {
    const d = data.detail ?? data.error?.detail
    if (typeof d === 'string' && d.trim()) return d
    if (Array.isArray(d) && d.length) {
      const parts = d.map((x: any) => (x && typeof x === 'object' ? (x.msg || x.message) : String(x))).filter(Boolean)
      if (parts.length) return parts.slice(0, 3).join('; ')
    }
    if (typeof data.title === 'string' && data.title.trim()) return data.title
    if (typeof data.message === 'string' && data.message.trim()) return data.message
  }
  return fallback || 'Request failed'
}

export interface HttpErrorFields { statusCode?: number; code: string; message: string; details?: unknown }

/**
 * An axios failure as the handler needs it, or null for anything that is not an HTTP failure. An AxiosError IS an
 * Error, which is why the handler's old `instanceof Error` branch returned it untouched and never saw a status.
 */
export function httpErrorFields(error: any): HttpErrorFields | null {
  if (!(error?.isAxiosError || error?.response)) return null
  if (!error.response) return { code: 'NETWORK_ERROR', message: 'Network error' }
  const data = error.response.data
  return {
    statusCode: error.response.status,
    code: (data && typeof data === 'object' && (data.code || data.error?.type)) || 'HTTP_ERROR',
    message: messageOf(data, error.response.statusText),
    details: data,
  }
}
