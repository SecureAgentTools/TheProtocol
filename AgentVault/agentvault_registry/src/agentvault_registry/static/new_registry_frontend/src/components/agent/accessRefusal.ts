/**
 * §FESUITE (2026-10-10): what a refused action on the agent's Access panel says, in words. The panel wrote the server's
 * `detail` straight into its one error state, and a refused field (a rate limit of 0, a value of the wrong type) came out
 * without the field it is about. The registry's own 422 (errors.py, validation_exception_handler) carries the first
 * message as `detail`, the field in `error.field` ("body -> spend_policy -> rate_per_hour") and every refused field in
 * `error.context.errors` when there are several; FastAPI's default (a LIST of `{loc, msg}`, which drew as JSON) is read
 * too, for a service that answers with it; other refusals carry a string or an object.
 */

/** the last NAMED place of a field path: ['body', 'roles', 0] or "body -> roles -> 0" is the roles list: "roles" */
function fieldName(path: unknown): string {
  const parts = Array.isArray(path) ? path.map(String)
    : typeof path === 'string' ? path.split('->').map((s) => s.trim()) : []
  const named = parts.filter((x) => x && !['body', 'query', 'path'].includes(x) && !/^\d+$/.test(x))
  return named.length ? named[named.length - 1].replace(/_/g, ' ') : ''
}

const naming = (field: string, msg: string) => (field ? `${field}: ${msg}` : msg)
const text = (v: unknown) => (typeof v === 'string' ? v.trim() : '')

export function refusalText(e: any, fallback: string): string {
  const data = e?.response?.data
  const detail = data?.detail
  const own = data?.error
  if (own && typeof own === 'object') {
    const several = Array.isArray(own.context?.errors) ? own.context.errors : []
    const parts = several.map((x: any) => (text(x?.message) ? naming(fieldName(x?.field), text(x.message)) : '')).filter(Boolean)
    if (parts.length) return parts.join('; ')
    const msg = text(own.detail) || text(detail)
    if (msg && text(own.field)) return naming(fieldName(own.field), msg)
  }
  if (text(detail)) return text(detail)
  if (Array.isArray(detail)) {
    const parts = detail.map((d: any) => (text(d?.msg) ? naming(fieldName(d?.loc), text(d.msg)) : '')).filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  if (detail && typeof detail === 'object') {
    for (const k of ['message', 'detail', 'reason']) {
      const v = text((detail as Record<string, unknown>)[k])
      if (v) return v
    }
  }
  if (text(data?.title)) return text(data.title)   // RFC 7807's own sentence
  return text(e?.message) || fallback
}
