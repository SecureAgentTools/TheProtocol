import { ref } from 'vue'
import { jwtDecode } from 'jwt-decode'
import { config } from '@/config'
import { readAccessToken } from '@/services/accessToken'
import { authApi } from '@/services/api/auth'
import { useLogger } from '@/composables/useLogger'
import type { User } from '@/types'

const log = useLogger('auth')

// Ensure browser globals are available
declare const window: Window & typeof globalThis

interface TokenPayload {
  exp: number
  iat: number
  sub: string
  role?: string
  email?: string
  name?: string
  user_id?: string
}

interface AuthTokens {
  access_token: string
  refresh_token?: string
  token_type: string
}

// TEST_USERS removed — auth must always go through the backend

class AuthService {
  private refreshTokenTimeout?: ReturnType<typeof setTimeout>
  private tokenRefreshPromise?: Promise<AuthTokens>
  private tokenListeners = new Set<(t: AuthTokens) => void>()

  /**
   * §FEFRAME W1 — tell a listener (the auth store) about EVERY new token pair, including the ones the refresh timer
   * mints on its own. Returns the unsubscribe.
   */
  onTokens(fn: (t: AuthTokens) => void): () => void {
    this.tokenListeners.add(fn)
    return () => { this.tokenListeners.delete(fn) }
  }

  /**
   * Get stored access token.
   *
   * #1 (2026-05-08) — Token tier-split. The access token now lives in
   * `sessionStorage` (browser-tab scope) so a long-lived background tab
   * can't exfiltrate a still-valid token after the user closes the active
   * window. The localStorage fallback is purely for migration safety:
   * users logged in under the OLD layout (access in localStorage) keep
   * their session until the next refresh-rotation moves it into
   * sessionStorage. Drop the fallback in a future cycle once the migration
   * window has elapsed.
   */
  getAccessToken(): string | null {
    return readAccessToken()
  }

  /**
   * Get stored refresh token.
   *
   * Refresh token tier is `rememberMe`-driven:
   *  - rememberMe=true → localStorage (survives browser restart, used to
   *    silently re-mint an access token on next page load).
   *  - rememberMe=false → sessionStorage (dies with the tab).
   * Read-order is localStorage-first because that's the more durable tier;
   * if both are populated (rare, only via a stale-state edge case), the
   * persistent one wins and self-corrects on next rotation.
   */
  getRefreshToken(): string | null {
    return window.localStorage.getItem(config.auth.refreshTokenKey)
        || window.sessionStorage.getItem(config.auth.refreshTokenKey)
  }

  /**
   * Store auth tokens.
   *
   * #1 (2026-05-08) — Tier-split. The access token ALWAYS lands in
   * sessionStorage (browser-tab scope, dies on tab close). The refresh
   * token tier is caller-controlled:
   *  - On the explicit-login path (`rememberMe` defined) — honor the
   *    user's choice: localStorage when remembering, sessionStorage
   *    otherwise.
   *  - On the silent refresh-rotation path (`rememberMe === undefined`) —
   *    stick with whichever tier currently holds the OLD refresh token,
   *    so the user's persistence preference is preserved across the swap.
   */
  setTokens(tokens: AuthTokens, rememberMe?: boolean): void {
    // Access token ALWAYS in sessionStorage (browser-tab scope).
    window.sessionStorage.setItem(config.auth.tokenKey, tokens.access_token)
    // Defensive: if a legacy access token still sits in localStorage from
    // before the tier-split, evict it now so subsequent reads return the
    // fresh sessionStorage value (not the stale localStorage one via the
    // migration fallback in getAccessToken).
    window.localStorage.removeItem(config.auth.tokenKey)

    if (tokens.refresh_token) {
      let refreshStorage: Storage
      if (rememberMe === undefined) {
        // Refresh-rotation: keep the existing tier.
        refreshStorage = window.localStorage.getItem(config.auth.refreshTokenKey)
          ? window.localStorage
          : window.sessionStorage
      } else {
        refreshStorage = rememberMe ? window.localStorage : window.sessionStorage
      }
      refreshStorage.setItem(config.auth.refreshTokenKey, tokens.refresh_token)
      // Clear the OTHER tier so we never have stale refresh tokens lingering.
      const otherStorage = refreshStorage === window.localStorage
        ? window.sessionStorage
        : window.localStorage
      otherStorage.removeItem(config.auth.refreshTokenKey)
    }

    // Set up automatic token refresh
    this.scheduleTokenRefresh(tokens.access_token)
    for (const fn of this.tokenListeners) {
      try { fn(tokens) } catch (e) { log.warn('a token listener failed', e) }
    }
  }

  /**
   * Clear all auth data
   */
  clearAuth(): void {
    // Clear timeouts
    if (this.refreshTokenTimeout) {
      clearTimeout(this.refreshTokenTimeout)
    }

    // Clear storage - ensure globals are available
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(config.auth.tokenKey)
      window.localStorage.removeItem(config.auth.refreshTokenKey)
      window.localStorage.removeItem(config.auth.userKey)
      
      window.sessionStorage.removeItem(config.auth.tokenKey)
      window.sessionStorage.removeItem(config.auth.refreshTokenKey)
      window.sessionStorage.removeItem(config.auth.userKey)
    }
  }

  /**
   * Check if token is expired
   */
  isTokenExpired(token: string): boolean {
    try {
      const decoded = jwtDecode<TokenPayload>(token)
      const currentTime = Date.now() / 1000
      return decoded.exp < currentTime
    } catch (error) {
      // Cannot decode → treat as expired/invalid
      return true
    }
  }

  /**
   * Get token expiry time in milliseconds
   */
  getTokenExpiry(token: string): number | null {
    try {
      const decoded = jwtDecode<TokenPayload>(token)
      return decoded.exp * 1000
    } catch {
      return null  // Cannot decode → no valid expiry
    }
  }

  /**
   * Schedule automatic token refresh.
   *
   * Public so the auth store can call it from initializeAuth() on every page
   * load — without that, the timer is only set on a fresh login and any tab
   * reload silently drops it, letting the access token expire unobserved.
   *
   * If the token is ALREADY inside the 5-minute refresh window (or expired),
   * we fire refreshAccessToken() immediately instead of silently doing nothing
   * — failures here are non-fatal because the response interceptor's reactive
   * refresh-then-retry will catch any remaining 401.
   */
  scheduleTokenRefresh(token: string): void {
    // Clear existing timeout
    if (this.refreshTokenTimeout) {
      clearTimeout(this.refreshTokenTimeout)
    }

    const expiry = this.getTokenExpiry(token)
    if (!expiry) return

    // Refresh 5 minutes before expiry
    const refreshTime = expiry - Date.now() - (5 * 60 * 1000)

    if (refreshTime > 0) {
      this.refreshTokenTimeout = setTimeout(() => {
        this.refreshAccessToken().catch(err =>
          log.debug('scheduled refresh failed:', err)
        )
      }, refreshTime)
    } else {
      // Already inside refresh window (or past expiry) → eager refresh now.
      this.refreshAccessToken().catch(err =>
        log.debug('eager refresh on init/restore failed:', err)
      )
    }
  }

  // createMockToken removed — no mock tokens in production

  /**
   * Extract user from JWT token
   */
  private getUserFromToken(token: string, email: string): User {
    try {
      const decoded = jwtDecode<TokenPayload>(token)
      return {
        id: decoded.sub || decoded.user_id || '1',
        email: decoded.email || email,
        name: decoded.name || email.split('@')[0],
        role: (decoded.role as 'admin' | 'developer' | 'agent' | 'user') || 'user',
        is_admin: decoded.role === 'admin', // Set is_admin based on role
        is_active: true,
        created_at: new Date().toISOString()
      }
    } catch (error) {
      console.error('Failed to decode token:', error)
      // Return default user
      return {
        id: '1',
        email: email,
        name: email.split('@')[0],
        role: 'user',
        is_admin: false,
        is_active: true,
        created_at: new Date().toISOString()
      }
    }
  }

  /**
   * Refresh access token using refresh token
   */
  async refreshAccessToken(): Promise<AuthTokens | null> {
    // Prevent multiple simultaneous refresh requests
    if (this.tokenRefreshPromise) {
      return this.tokenRefreshPromise
    }

    const refreshToken = this.getRefreshToken()
    if (!refreshToken) return null

    this.tokenRefreshPromise = authApi.refreshToken(refreshToken)
      .then(tokens => {
        this.setTokens(tokens)
        this.tokenRefreshPromise = undefined
        return tokens
      })
      .catch(error => {
        this.tokenRefreshPromise = undefined
        // §FEFRAME W3: clear the session only when the server REFUSED the refresh token (400/401/403). A network error
        // or a 5xx is not a verdict on the session: clearing on it ended sessions that were fine (a registry restart,
        // a dropped connection), and the next request simply asks again.
        const st = (error as any)?.response?.status
        if (st === 400 || st === 401 || st === 403) this.clearAuth()
        throw error
      })

    return this.tokenRefreshPromise
  }

  /**
   * Login user
   */
  async login(
    credentials: { email: string; password: string },
    rememberMe = false
  ): Promise<{ user: User; tokens: AuthTokens; requires_2fa?: boolean; partial_token?: string }> {
    try {
      const response = await authApi.login(credentials)
      
      // Log response for debugging
      import.meta.env.DEV && console.log('Raw login response:', response)
      
      // Check if 2FA is required
      if (response.requires_2fa) {
        // Return early with 2FA flag - DO NOT process tokens or fetch user
        return {
          user: null as any,
          tokens: { access_token: '', token_type: 'Bearer' },
          requires_2fa: true,
          partial_token: response.partial_token || ''
        }
      }
      
      // PUSH LOGIN: an empty token here is not a failure — the server is telling us this account
      // needs a biometric approval. Throwing "no access token received" was actively misleading.
      if ((response as any).requires_push_approval) {
        return {
          user: null as any,
          tokens: { access_token: '', token_type: 'Bearer' },
          requires_push_approval: true,
          approval_id: (response as any).approval_id || '',
          approval_expires_in: (response as any).approval_expires_in || 120,
        } as any
      }

      // Only proceed if we have a valid access token
      if (!response.access_token) {
        throw new Error('No access token received from server')
      }
      
      // Extract token details
      const access_token = response.access_token
      const token_type = response.token_type || 'Bearer'
      
      // Store tokens FIRST before making any authenticated requests
      this.setTokens(
        {
          access_token,
          refresh_token: response.refresh_token,
          token_type
        },
        rememberMe
      )
      
      // Small delay to ensure token is available in storage
      await new Promise(resolve => setTimeout(resolve, 10))
      
      // Get user from response or fetch from API
      let user: User
      if (response.user) {
        user = response.user
        // Map is_admin to role if role is missing
        if (!user.role && user.is_admin !== undefined) {
          user.role = user.is_admin ? 'admin' : 'developer'
        }
      } else {
        // The backend login endpoint only returns token, not user data
        // We need to fetch user data separately
        import.meta.env.DEV && console.log('No user data in login response, fetching from /developers/me')
        try {
          const { user: verifiedUser } = await authApi.verify()
          user = verifiedUser
        } catch (error) {
          console.error('Failed to fetch user data after login:', error)
          // Fallback: Create user from token
          user = this.getUserFromToken(access_token, credentials.email)
          
          // TEST_USERS fallback removed — auth always from backend
        }
      }
      
      // Store user data
      const storage = rememberMe ? window.localStorage : window.sessionStorage
      storage.setItem(config.auth.userKey, JSON.stringify(user))
      
      return {
        user,
        tokens: {
          access_token,
          refresh_token: response.refresh_token,
          token_type
        },
        requires_2fa: false
      }
    } catch (error: any) {
      // §FESUITE: a refused credential (a 4xx) is the person's mistake, already shown to them; only the unexpected is an error
      if (!error?.response?.status || error.response.status >= 500) console.error('Login error:', error)
      throw error
    }
  }

  /**
   * Logout user
   */
  async logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch (error) {
      console.error('Logout API error:', error)
    } finally {
      this.clearAuth()
    }
  }

  /**
   * Get current user from storage
   */
  getCurrentUser(): User | null {
    const userStr = window.localStorage.getItem(config.auth.userKey) || 
                   window.sessionStorage.getItem(config.auth.userKey)
    
    if (!userStr) return null
    
    try {
      return JSON.parse(userStr)
    } catch {
      return null
    }
  }

  /**
   * Verify current session
   */
  async verify(): Promise<{ valid: boolean; user: User }> {
    return authApi.verify()
  }
  
  /**
   * Verify current session
   */
  async verifySession(): Promise<User | null> {
    const token = this.getAccessToken()
    if (!token) return null

    // Check if token is expired
    if (this.isTokenExpired(token)) {
      // Try to refresh
      try {
        await this.refreshAccessToken()
      } catch {
        return null
      }
    }

    let response: Awaited<ReturnType<typeof authApi.verify>>
    try {
      response = await authApi.verify()
    } catch (e) {
      // §FESUITE: "could not verify" (a 5xx, a timeout, no network): a stored user carries on; with none, the caller is
      // told, so it keeps the session it has instead of ending it on the registry's trouble
      const stored = this.getCurrentUser()
      if (stored) return stored
      throw e
    }
    // a refusal: the session is not valid (and null is never written over the stored user)
    if (!response.valid || !response.user) return null

    // Update stored user data
    const storage = typeof window !== 'undefined' && window.localStorage.getItem(config.auth.userKey) ? window.localStorage : window.sessionStorage
    storage.setItem(config.auth.userKey, JSON.stringify(response.user))

    return response.user
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    const token = this.getAccessToken()
    if (!token) {
      import.meta.env.DEV && console.log('No token found')
      return false
    }
    
    const expired = this.isTokenExpired(token)
    import.meta.env.DEV && console.log('isAuthenticated:', { hasToken: !!token, expired })
    return !expired
  }

  /**
   * Register new user
   */
  async register(userData: {
    email: string
    password: string
    name?: string
  }): Promise<User> {
    return authApi.register(userData)
  }

  /**
   * Request password reset
   */
  async requestPasswordReset(email: string): Promise<void> {
    return authApi.requestPasswordReset(email)
  }

  /**
   * Reset password with token
   */
  async resetPassword(token: string, newPassword: string): Promise<void> {
    return authApi.resetPassword(token, newPassword)
  }

  /**
   * Change password for authenticated user
   */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    return authApi.changePassword(currentPassword, newPassword)
  }

  /**
   * Enable two-factor authentication
   */
  async enableTwoFactor(): Promise<{ qr_code: string; secret: string }> {
    return authApi.enableTwoFactor()
  }

  /**
   * Verify two-factor code
   */
  async verifyTwoFactor(code: string): Promise<void> {
    return authApi.verifyTwoFactor(code)
  }

  /**
   * Get session info
   */
  getSessionInfo(): {
    isActive: boolean
    expiresAt: Date | null
    user: User | null
  } {
    const token = this.getAccessToken()
    const user = this.getCurrentUser()
    
    if (!token) {
      return {
        isActive: false,
        expiresAt: null,
        user: null
      }
    }

    const expiry = this.getTokenExpiry(token)
    
    return {
      isActive: !this.isTokenExpired(token),
      expiresAt: expiry ? new Date(expiry) : null,
      user
    }
  }
}

// Export singleton instance
export const authService = new AuthService()

// Export types
export type { AuthTokens, TokenPayload }
