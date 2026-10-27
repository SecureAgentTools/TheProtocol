import { config } from '@/config'

/**
 * The ONE reader of the stored access token (§FESUITE, 2026-10-01).
 *
 * The token lives in sessionStorage (§POCKETBRIDGE #PK24), with localStorage as the older tier. Ten call sites read it
 * themselves, and three read localStorage alone: the audit log's actor look-up sent "Bearer null" (every actor showed
 * as `admin:<id>`, each look-up a 401), its agent-name look-up and Admin CI/CD's sent no token at all. Others fell
 * back to a 'token' key nothing writes. A leaf module (it imports only the config), so a store or a composable can use
 * it without pulling the API client's graph into its own.
 */
export function readAccessToken(): string | null {
  try {
    return window.sessionStorage.getItem(config.auth.tokenKey) || window.localStorage.getItem(config.auth.tokenKey)
  } catch {
    return null
  }
}
