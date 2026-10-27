/**
 * useLogger — production-aware console wrapper (2026-05-08).
 *
 * Replaces unguarded `console.log/warn/info/debug` calls. In production
 * builds (`import.meta.env.DEV === false`), info/warn/debug no-op so we
 * don't leak stack traces or internal state to user devtools. `error` is
 * kept everywhere — surfacing real errors helps both ops and debugging.
 *
 * Usage:
 *   import { useLogger } from '@/composables/useLogger'
 *   const log = useLogger('AgentProfile')   // optional namespace
 *   log.info('loaded', data)
 *   log.warn('falling back to default')
 *   log.error('fetch failed', err)
 *
 * Design notes:
 * - Stateless — no Vue lifecycle, returns plain object. Safe to call at
 *   module scope, inside composables, inside actions, anywhere.
 * - Namespace prefix is added in DEV only ("[Namespace] message") — keeps
 *   prod calls (errors) clean for log shippers.
 * - error() ALWAYS emits, even in prod. Wrap genuinely-noisy errors
 *   (e.g. polling-loop transients) at the call site; don't silence here.
 */

const isDev: boolean = (import.meta.env && import.meta.env.DEV) || false

export interface Logger {
  info(...args: unknown[]): void
  warn(...args: unknown[]): void
  debug(...args: unknown[]): void
  error(...args: unknown[]): void
}

const noop = (): void => { /* prod no-op */ }

export function useLogger(namespace?: string): Logger {
  if (isDev) {
    const prefix = namespace ? `[${namespace}]` : ''
    return {
      info:  prefix ? (...a: unknown[]) => console.info(prefix, ...a)  : (...a: unknown[]) => console.info(...a),
      warn:  prefix ? (...a: unknown[]) => console.warn(prefix, ...a)  : (...a: unknown[]) => console.warn(...a),
      debug: prefix ? (...a: unknown[]) => console.debug(prefix, ...a) : (...a: unknown[]) => console.debug(...a),
      error: prefix ? (...a: unknown[]) => console.error(prefix, ...a) : (...a: unknown[]) => console.error(...a),
    }
  }
  // Production: info/warn/debug no-op; error still emits (and gets the
  // namespace prefix only if one was provided, kept terse for log shippers).
  return {
    info: noop,
    warn: noop,
    debug: noop,
    error: namespace
      ? (...a: unknown[]) => console.error(`[${namespace}]`, ...a)
      : (...a: unknown[]) => console.error(...a),
  }
}
