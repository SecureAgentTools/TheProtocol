import axios from 'axios'
import { isJwtExpired } from './tokenExpiry'
import type { AxiosInstance, AxiosError, AxiosRequestConfig } from 'axios'
import { config } from '@/config'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { authService } from '@/services/auth'
import { errorHandler } from '@/utils/errorHandler'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('apiClient')

// Retry configuration
interface RetryConfig {
  retries: number
  retryDelay: number
  retryCondition?: (error: AxiosError) => boolean
}

const defaultRetryConfig: RetryConfig = {
  retries: 1,
  retryDelay: 2000,
  retryCondition: (error) => {
    // Only retry on 5xx server errors, NOT on timeouts or network errors.
    // With a single uvicorn worker, retrying timeouts just piles more requests
    // onto an already overloaded backend, making everything slower.
    return !!error.response && error.response.status >= 500 && error.response.status < 600
  }
}

/**
 * §FEFRAME W4 residue (V0521, his "improvements also approved" 2026-10-01): a READ that hangs shows an error after a
 * minute instead of a five-minute spinner. A write keeps the long wait: a write the server still completes after the
 * browser gave up invites a second press, and a second press of a transfer is a second charge.
 * The instance's own default is 0, which means "the caller set none"; the request interceptor turns it into
 * READ_TIMEOUT_MS for a GET or HEAD and into config.api.timeout (300 s) for anything else. A caller's own timeout always
 * wins (the health checks' 5 and 10 minutes, IRONHAND's 15 s...). 60 s, not 30: EU's console vhost already ends any
 * request at nginx's 60 s, and in 30 days its requests over 30 s were the long-lived streams (which are not axios
 * calls) plus at most 13 others (SESSION_LOG_2026-09-30_FEFRAME.md, the timeout census).
 */
export const READ_TIMEOUT_MS = 60_000
export function effectiveTimeout(method: string | undefined, timeout: number | undefined): number {
  if (timeout) return timeout
  const m = (method || 'get').toLowerCase()
  return m === 'get' || m === 'head' ? READ_TIMEOUT_MS : config.api.timeout
}

// Create axios instance
export const apiClient: AxiosInstance = axios.create({
  baseURL: config.api.baseURL,
  timeout: 0, // "the caller set none": effectiveTimeout() above decides per method
  headers: {
    'Content-Type': 'application/json'
  }
})

/**
 * §FESUITE (2026-10-05): what the client may send again on its own after a 5xx: a read, never a write. A 5xx on a write
 * does not say whether it was done: the registry answers 503 when its call to the TEG timed out AFTER the TEG committed,
 * and nginx answers 502/504 for a worker that died or ran long after its commit; a second send of that transfer was a
 * second transfer. An Idempotency-Key does not make a write safe to re-send here either: not every endpoint declares it
 * (/teg/system-transfer does not) and none passes it on to the TEG. A write reports its failure; the person decides.
 * §FESUITE (2026-10-10): a POST that only reads is named here, one by one (the balances batch: a list of DIDs too long
 * for a query string), and is treated as the read it is, here and by failedOnALeftPage. Every other POST is a write.
 */
const READ_ONLY_POSTS: readonly RegExp[] = [/(^|\/)developers\/me\/agents\/balances\/?$/]

export function mayResendOnItsOwn(method: string | undefined, url?: string): boolean {
  const m = (method || 'get').toLowerCase()
  if (m === 'get' || m === 'head' || m === 'options') return true
  if (m !== 'post' || !url) return false
  const path = String(url).split('?')[0]
  return READ_ONLY_POSTS.some((re) => re.test(path))
}

/** The console's page as the hash router shows it (path only, no query). */
export function currentPagePath(): string {
  try { return (window.location.hash || '').replace(/^#/, '').split('?')[0] || '/' } catch { return '' }
}

/** §FESUITE (2026-10-09; agentvault2-b2 named it 2026-10-05): a READ whose page is gone does not speak on the next
 *  page. The global error toast ("Server Error", "Connection Error") is raised here for any failed call, so a read a page
 *  started and the person left before it failed put its toast over a page that asked nothing (PocketOrgs, PocketTrade,
 *  ExchangeDesk and the AGORA fundamentals panel never cancel theirs). The page that asked is the one whose notices say
 *  its read failed; a write always reports (its outcome matters wherever the person is now). */
export function failedOnALeftPage(method: string | undefined, askedOn: string | undefined, now: string, url?: string): boolean {
  return mayResendOnItsOwn(method, url) && !!askedOn && !!now && askedOn !== now
}

// Add retry capability
function setupRetry(instance: AxiosInstance) {
  instance.interceptors.response.use(
    response => response,
    async error => {
      const config = error.config as (AxiosRequestConfig & { _retry?: number, _retryConfig?: RetryConfig }) | undefined
      // an error that is not a failed request (thrown before one was made) has nothing to send again
      if (!config) return Promise.reject(error)
      const retryConfig = config._retryConfig || defaultRetryConfig

      if (!config._retry) {
        config._retry = 0
      }

      if (config._retry >= retryConfig.retries || !retryConfig.retryCondition?.(error) || !mayResendOnItsOwn(config.method, config.url)) {
        return Promise.reject(error)
      }
      
      config._retry++
      
      // Show retry notification
      const uiStore = useUIStore()
      uiStore.showInfo(
        'Connection Issue',
        `Retrying request... (Attempt ${config._retry}/${retryConfig.retries})`
      )
      
      // Wait before retrying
      await new Promise(resolve => setTimeout(resolve, retryConfig.retryDelay * (config._retry || 1)))
      
      return instance(config)
    }
  )
}

import { marketPath } from './tier'
import { wholeLedgerRefusalSentence } from './ledgerRefusal'
import { actsAsAgent, asksAboutSession, type SentTier } from './authTiers'

function explicitAuthorization(requestConfig: AxiosRequestConfig): string | null {
  const h: any = requestConfig.headers
  if (!h) return null
  const v = typeof h.get === 'function' ? h.get('Authorization') : (h.Authorization ?? h.authorization)
  return v ? String(v) : null
}

/**
 * §FOREIGNACT (2026-08-24) — PUBLIC venue reads must follow the acting agent too.
 *
 * `GET /exchange/listings` (and book/trades/candles) is PUBLIC, so it was served
 * by whichever registry the page is on, while `POST /exchange/orders` is
 * agent-tier and already went to the acting agent's HOME. Acting as a foreign
 * agent therefore meant browsing one venue and trading on another: you read
 * frame-c's book and your order landed on registry-a's.
 *
 * Today that fails safely — the two venues' symbols do not overlap, so the order
 * 404s. It is luck, not design: `placeOrder` takes a `listing` string, and the
 * day two frames both list a symbol, a price read from one venue would place a
 * real order on the other. Reading the venue you can actually trade on removes
 * the class instead of warning about it.
 *
 * Auth is deliberately DROPPED on these: they are public, and this page's
 * developer token belongs to a different registry.
 */
function followsActingVenue(url?: string, method?: string): boolean {
  if (!url) return false
  url = marketPath(url)   // /agora/… and /exchange/… are one market (tier.ts)
  if (!url.includes('/exchange/')) return false
  // The org treasury desk (/exchange/organizations/…) is DEVELOPER-tier and the
  // org lives on THIS registry — redirecting it would send it somewhere it does
  // not exist, without the token it needs. Same for anything /admin/.
  if (url.includes('/exchange/organizations/')) return false
  if (url.includes('/admin/')) return false
  // PUBLIC READS ONLY. Developer-tier writes (create a listing, declare a
  // dividend, tally a proposal) are this developer's acts on this registry.
  return (method || 'get').toLowerCase() === 'get'
}

// Request interceptor for auth
apiClient.interceptors.request.use(
  async (requestConfig) => {
    requestConfig.timeout = effectiveTimeout(requestConfig.method, requestConfig.timeout)
    // the page that asked (a retry keeps the first send's), for failedOnALeftPage
    const tagged = requestConfig as typeof requestConfig & { askedOnPage?: string }
    if (tagged.askedOnPage === undefined) tagged.askedOnPage = currentPagePath()
    // Get auth store instance - need to import inside interceptor to avoid circular dependency
    const authStore = useAuthStore()

    // §BATCH8 item 9 (2026-09-06) — pre-flight: a DEVELOPER token whose `exp` is already past is not sent.
    // One deduped refresh first (authService.refreshAccessToken shares its promise across callers); if the
    // refresh fails the request goes out once and the response interceptor's existing path logs out.
    // Before this, an expired session fired every poller with the dead token — six 401s in a second read
    // as a bruteforce to CrowdSec and banned his own VPN exit.
    const agentTier = actsAsAgent(requestConfig.url, requestConfig.method, requestConfig.baseURL)
    // §FEFRAME W3: a token the CALLER named is not second-guessed (it was overwritten with the active agent's or the
    // developer's, whichever the tier guessed); W1's rule still holds: it never travels to another registry
    const callerToken = explicitAuthorization(requestConfig)
    if (!agentTier) {
      const url = requestConfig.url || ''
      const devToken = authStore.token
      if (devToken && isJwtExpired(devToken) && !url.includes('/auth/refresh') && !url.includes('/auth/login')
          && authService.getRefreshToken()) {
        try {
          const tokens = await authService.refreshAccessToken()
          if (tokens?.access_token) authStore.token = tokens.access_token
        } catch (e) {
          log.warn('pre-flight refresh of an expired developer token failed; the request goes out once', e)
        }
      }
    }
    
    // Choose correct token based on endpoint
    let token: string | null = null
    let sent: SentTier = 'public'
    
    if (agentTier) {
      // §FEFRAME W3: a token about to lapse is re-minted on its own road first (an owner token lives 30 minutes)
      try { await authStore.ensureFreshAgentToken?.() } catch { /* the request goes out; a 401 says the rest */ }
      // Use agent token for agent-specific endpoints
      token = authStore.agentToken
      /**
       * §BRIDGE R11 #12 — a foreign agent's calls go to ITS OWN registry.
       *
       * ONE seam, deliberately. Threading a base URL through every agent-scoped
       * caller is how two code paths end up disagreeing about which registry
       * they are talking to (§FANOUTFIX); this is the single place that already
       * knows "this request is being made AS an agent", so it is the only place
       * that has to know WHERE that agent lives.
       *
       * The agent JWT above was minted BY that registry, so sending it anywhere
       * else would 401 — the token and the address must move together, and here
       * they do. `activeAgentRegistryUrl` is null for every local agent, so a
       * fleet that has never imported a foreign credential is untouched.
       */
      const foreign = authStore.activeAgentRegistryUrl
      sent = token ? 'agent' : 'public'
      if (foreign && !requestConfig.baseURL?.startsWith(foreign)) {
        requestConfig.baseURL = `${foreign}/api/v1`
        // §FEFRAME W1: to another registry goes that registry's agent token or nothing, never this one's
        if (!token) requestConfig.headers.delete?.('Authorization')
        sent = 'foreign'
      } else if (callerToken) {
        token = null          // the caller named its token: keep it
        sent = 'caller'
      }
    } else {
      // Use developer token for general endpoints
      token = authService.getAccessToken()
      sent = token ? 'developer' : 'public'
      // §FOREIGNACT — public venue reads follow the acting agent's registry so
      // the book you read is the book you trade on. Unauthenticated: this
      // registry's developer token means nothing at the agent's home.
      const foreignVenue = authStore.activeAgentRegistryUrl
      if (foreignVenue && followsActingVenue(requestConfig.url, requestConfig.method)
          && !requestConfig.baseURL?.startsWith(foreignVenue)) {
        requestConfig.baseURL = `${foreignVenue}/api/v1`
        token = null
        // §FEFRAME W1: a PUBLIC read at another registry carries no credential at all; delete whatever a caller or a
        // default put on it (axios merges defaults before this interceptor runs)
        requestConfig.headers.delete?.('Authorization')
        sent = 'foreign'
      } else if (callerToken && (!token || callerToken !== `Bearer ${token}`)) {
        token = null          // the caller named another token: keep it, and it says nothing about this session
        sent = 'caller'
      }
    }
    
    if (token) {
      requestConfig.headers.Authorization = `Bearer ${token}`
    }
    ;(requestConfig as any)._tpSent = sent

    // §pass14 (2026-05-15) — Defensive cache-busting for authenticated GETs.
    // Many of our state endpoints (/developers/me/agents, /fiat/flare/status,
    // balances, etc.) return without an explicit Cache-Control header, which
    // makes browsers apply heuristic caching to GETs (stale state after a
    // POST-then-reload sequence). Send Cache-Control: no-cache on every
    // request so the browser revalidates with the server; combined with
    // server-side `no-store` on the auth-bearing endpoints this guarantees
    // fresh state on every page load.
    if ((requestConfig.method || 'get').toLowerCase() === 'get') {
      if (!requestConfig.headers['Cache-Control']) {
        requestConfig.headers['Cache-Control'] = 'no-cache'
      }
    }

    // Add request ID for tracking
    requestConfig.headers['X-Request-ID'] = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

    return requestConfig
  },
  (error) => {
    errorHandler.handleError(error)
    return Promise.reject(error)
  }
)

/** §FEFRAME W3 — ask the SESSION (not the route) whether it still stands: 'refreshed' (a new access token is in place),
 *  'valid' (no refresh token, but /developers/me answers), 'refused' (the server refused the session itself), or
 *  'unknown' (it could not be asked: network, 5xx). Only 'refused' ends a session. */
async function sessionVerdict(): Promise<'refreshed' | 'valid' | 'refused' | 'unknown'> {
  const statusOf = (e: any): number | undefined => e?.response?.status
  if (authService.getRefreshToken()) {
    try {
      const tokens = await authService.refreshAccessToken()
      if (tokens?.access_token) {
        const authStore = useAuthStore()
        authStore.token = tokens.access_token
        return 'refreshed'
      }
      return 'unknown'
    } catch (e) {
      const st = statusOf(e)
      return st === 400 || st === 401 || st === 403 ? 'refused' : 'unknown'
    }
  }
  try {
    await apiClient.get('/developers/me', { _skipLogoutOn401: true } as any)
    return 'valid'
  } catch (e) {
    return statusOf(e) === 401 ? 'refused' : 'unknown'
  }
}

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => {
    // Handle successful responses
    return response
  },
  async (error: AxiosError) => {
    const authStore = useAuthStore()
    const uiStore = useUIStore()

    // 2026-05-10 — Normalize unified-error envelope to the legacy shape that
    // most call sites still read. Backend's errors.py wraps HTTPException as
    // {error: {detail, type, context}} — but ~20 frontend sites read
    // err.response.data.detail directly. Promote it once here so every caller
    // that does `err.response?.data?.detail` Just Works. Defensive: only
    // writes data.detail if it's not already set, preserving any legacy
    // endpoints that emit {detail: …} flat.
    if (error.response?.data && typeof error.response.data === 'object') {
      const data: any = error.response.data
      const wrappedDetail = data?.error?.detail
      if (wrappedDetail && data.detail == null) {
        data.detail = wrappedDetail
      }
      // Also surface the headers context (e.g., X-Verification-Required) so
      // call sites can branch on response shape without reaching deep into
      // body.error.context.headers.
      const wrappedHeaders = data?.error?.context?.headers
      if (wrappedHeaders && data.contextHeaders == null) {
        data.contextHeaders = wrappedHeaders
      }
    }

    // Handle auth errors
    if (error.response?.status === 401) {
      const requestConfig = error.config as (AxiosRequestConfig & {
        _refreshAttempted?: boolean
        _skipLogoutOn401?: boolean
      }) | undefined
      const requestUrl = requestConfig?.url || ''
      const isLoginEndpoint = requestUrl.includes('/auth/login')
      const isRefreshEndpoint = requestUrl.includes('/auth/refresh')
      const isOnLoginPage = window.location.hash === '#/login' || window.location.pathname.includes('/login')
      // §DISCPUBLIC (2026-09-06) — A SESSION THAT NEVER EXISTED CANNOT EXPIRE.
      // Discovery is now servable without a session (/#/explore), and a visitor's
      // page fires the same reads a member's does; the owner-tier ones answer 401
      // by design. Before this, ONE such 401 (contracts/v2/engage-preview, measured)
      // ran the logout branch: POST /auth/logout, "Session Expired", and a redirect
      // to #/login — a visitor thrown off a public page by a refusal that was the
      // correct answer to their request. Naming that one URL would have closed this
      // instance and left the class open for the next public surface, so the guard
      // is the state, not the path: no developer token in the store ⇒ nothing to
      // tear down, nothing to tell the person about. (The refresh-then-retry branch
      // below is already gated on a refresh_token, which a visitor also lacks.)
      const hasSession = !!authStore.token
      const sent: SentTier | undefined = (requestConfig as any)?._tpSent

      // §FEFRAME W3 (V0504) — ONE rule decides whether a 401 ends the session, replacing the 14-fragment no-logout list
      // (/federation/, /admin/, /agent-cards, /attestations, ...; every entry was earned by a 401 that tore a session
      // down without the session being at fault). A 401 says something about THIS session only when it was refused WITH
      // this console's own developer token; then the session itself is asked once:
      //   - the refresh token is refused (or, without one, GET /developers/me is refused)  -> the session ended
      //   - the refresh succeeds                                                            -> the request is retried
      //     once; a second 401 is the route's own answer (a business refusal, a peer's 401 through the relay)
      //   - the refresh cannot be asked (network, 5xx)                                      -> nothing ends
      // A 401 on an agent token, a foreign registry, a public read or a token the caller named ends nothing. A session
      // that never existed cannot expire (§DISCPUBLIC). The end itself stays LOCAL (§FEFRAME W1).
      const askSession = !!requestConfig && asksAboutSession({
        sent, hasSession, isLogin: isLoginEndpoint, isRefresh: isRefreshEndpoint, onLoginPage: isOnLoginPage,
        skip: requestConfig._skipLogoutOn401 === true,
      })

      if (askSession && !requestConfig!._refreshAttempted) {
        const verdict = await sessionVerdict()
        if (verdict === 'refreshed') {
          requestConfig!._refreshAttempted = true
          if (requestConfig!.headers) {
            requestConfig!.headers.Authorization = `Bearer ${authService.getAccessToken()}`
          }
          log.debug(`refreshed token on 401, retrying ${requestConfig!.method?.toUpperCase()} ${requestUrl}`)
          return apiClient(requestConfig!)
        }
        if (verdict === 'refused') {
          await authStore.endLocalSession(`401 on ${requestUrl} after the refresh failed (the session itself was refused)`)
          window.location.href = '#/login'
          uiStore.showError('Session Expired', 'Please log in again to continue.')
        } else if (verdict === 'valid') {
          log.debug(`Auth interceptor: 401 on ${requestUrl} while the session is valid: the route's own answer`)
        } else {
          log.debug(`Auth interceptor: 401 on ${requestUrl}; the session could not be asked (network), nothing ends`)
        }
      } else if (!hasSession) {
        log.debug(`Auth interceptor: 401 on ${requestUrl} with no session — public view, not logging out`)
      } else {
        log.debug(`Auth interceptor: 401 on ${requestUrl} (${sent || 'unknown'} token${requestConfig?._refreshAttempted ? ', after a refresh' : ''}), the session is not at fault`)
      }
    }
    
    // Handle rate limiting
    if (error.response?.status === 429) {
      const retryAfter = error.response.headers['retry-after']
      uiStore.showWarning(
        'Rate Limited',
        `Too many requests. Please wait ${retryAfter || 'a moment'} before trying again.`
      )
    }
    
    // §LEDGERGATE: the TEG refused a value movement because its ledger cannot record it right now. Nothing moved, and
    // the request is not sent again on its own (a write never is): say the sentence, not "Server Error". V0598: only
    // a refusal passed on whole; one inside a route's own words (several legs) is left to those words.
    const ledgerSentence = wholeLedgerRefusalSentence(error)
    if (ledgerSentence) {
      uiStore.showLedgerRefusal(ledgerSentence)
      return Promise.reject(error)
    }

    // Pass to global error handler — but SKIP for auth-related 401s on login/register
    // endpoints, since the auth store handles those errors itself.
    // Calling errorHandler here would trigger router.push('/login') + persistent
    // notification, which causes cascading failures when already on the login page.
    const isAuthEndpoint = error.config?.url?.includes('/auth/login') ||
                           error.config?.url?.includes('/auth/register') ||
                           error.config?.url?.includes('/auth/recover-account') ||
                           error.config?.url?.includes('/auth/set-new-password')
    const isAuthError = error.response?.status === 401 || error.response?.status === 400
    // Retryable 503s (they carry Retry-After) are transient + self-healing — e.g.
    // the auth layer returning 503 on a momentary DB-pool blip instead of a
    // spurious 401. Don't alarm the user with a "Server Error" toast; the next
    // poll cycle succeeds. (Root cause of the frame-c auto-logout, fixed 2026-07-05.)
    const isRetryable503 =
      error.response?.status === 503 && !!error.response?.headers?.['retry-after']
    // §FESUITE: a request may name statuses it expects as an answer (an optional resource's 404, a boundary's 403);
    // the caller handles those, so no global toast says "Not Found" over a page that is working as designed.
    const expected = (error.config as { expectedStatuses?: number[] } | undefined)?.expectedStatuses
    const isExpected = !!(expected && error.response && expected.includes(error.response.status))

    const leftPage = failedOnALeftPage(error.config?.method,
      (error.config as { askedOnPage?: string } | undefined)?.askedOnPage, currentPagePath(), error.config?.url)

    if (!(isAuthEndpoint && isAuthError) && !isRetryable503 && !isExpected && !leftPage) {
      errorHandler.handleError(error)
    } else if (leftPage) {
      log.debug(`a read of a page the person left failed (${error.config?.url}): no toast on the page they are on now`)
    }
    
    return Promise.reject(error)
  }
)

// Set up retry logic
setupRetry(apiClient)

// Mock servers removed — all endpoints use real backend

// Helper functions
export function withRetry<T>(request: () => Promise<T>, retryConfig?: Partial<RetryConfig>): Promise<T> {
  const config = { ...defaultRetryConfig, ...retryConfig }
  return request().catch(async (error) => {
    let lastError = error
    
    for (let i = 0; i < config.retries; i++) {
      try {
        await new Promise(resolve => setTimeout(resolve, config.retryDelay * (i + 1)))
        return await request()
      } catch (err) {
        lastError = err
        if (!config.retryCondition?.(err as AxiosError)) {
          throw err
        }
      }
    }
    
    throw lastError
  })
}

export default apiClient

declare module 'axios' {
  interface AxiosRequestConfig {
    /** §FESUITE: statuses this request expects as an answer, not an error; the client shows no global toast for them. */
    expectedStatuses?: number[]
  }
}
