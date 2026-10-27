import { defineStore } from 'pinia'
import { ref, computed, nextTick, watch } from 'vue'
import type { User } from '@/types'
import { authService } from '@/services/auth'
import { useUIStore } from './ui'
import { firstTimeThisSession } from '@/services/oncePerSession'
import { apiClient } from '@/services/api/client'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { cannotActReason, cannotActSentence } from '@/services/agentActable'
import { agentDidsCache } from '@/services/agentDidsCache'
import { fiatOnrampService } from '@/services/api/fiatOnramp'
import { useTwoFactorStore } from './twoFactor'
import { useLogger } from '@/composables/useLogger'
import { mintAgentTokenAt, classifyAgentMintFailure, failedForWantOfAnAnswer, type AgentMintFailure } from '@/services/api/peerDirect'
import { needsMint } from '@/services/sessionHub'
import { createBackoffRetry } from '@/services/backoffRetry'

const log = useLogger('authStore')

export const useAuthStore = defineStore('auth', () => {
  // State
  const user = ref<User | null>(null)
  const token = ref<string | null>(null)
  const loading = ref(false)
  // PUSH LOGIN handshake state (see routers/push_login.py)
  const pushApprovalId = ref('')
  const pushApprovalExpiresIn = ref(0)
  const error = ref<string | null>(null)
  // 2026-05-10 — set to true when the most recent login failed because the
  // account is unverified (backend gates with REQUIRE_EMAIL_VERIFICATION and
  // surfaces X-Verification-Required:true header). Login views read this to
  // render an inline RESEND VERIFICATION CTA. Cleared on next login attempt
  // and on clearError().
  const verificationRequired = ref(false)
  const sessionExpiry = ref<Date | null>(null)
  const rememberMe = ref(false)
  
  // Agent context state
  const activeAgent = ref<any | null>(null)
  const agentToken = ref<string | null>(null)
  const availableAgents = ref<any[]>([])
  const agentLoading = ref(false)
/**
 * §DIDCHUNK — did the LAST agent fetch fail?
 *
 * Without this the switcher cannot tell "this developer owns no agents" from
 * "the request died", and it rendered the cheerful zero-state — "No agents yet,
 * spin up your first agent" — to an operator holding 4,432 of them. A failed
 * load must never be reported as a fact about the account.
 */
  const agentFetchFailed = ref(false)
  const showAgentSelector = ref(false)
  const credentialsChecked = ref(false) // Flag to ensure credentials are checked before rendering
  /** §FEFRAME W1: why the last agent sign-in failed (null after a success); the switcher words its message from it. */
  const lastAgentAuthFailure = ref<AgentMintFailure | null>(null)

  // §FEFRAME W1 — saved agent credentials belong to a developer: every read of the store is scoped to whoever is
  // logged in now (services/agentCredentialsStore.ts), so this store tells it who that is, on every change.
  watch(() => (user.value as any)?.id ?? null, (id) => agentCredentialsStore.setCurrentOwner(id), { immediate: true })

  // §FEFRAME W1 — a refresh that ran on the timer (services/auth.ts scheduleTokenRefresh) wrote the new token to storage
  // and never told this store, so `token` went stale and the pre-flight kept refreshing a token that was already fresh.
  authService.onTokens((t) => {
    token.value = t.access_token
    const exp = authService.getTokenExpiry(t.access_token)
    sessionExpiry.value = exp ? new Date(exp) : null
  })

  // Getters - check both store state and authService
  const isAuthenticated = computed(() => {
    const hasToken = !!token.value || !!authService.getAccessToken()
    const isValid = authService.isAuthenticated()
    import.meta.env.DEV && console.log('isAuthenticated check:', { hasToken, isValid })
    return hasToken && isValid
  })
  
  const userRole = computed(() => user.value?.role || null)

  // §FESUITE (2026-10-04): a console that booted while the registry could not answer kept no agent. The saved agent's
  // sign-in failed for want of an answer (or the agent list could not be read) and nothing tried again, so Mission
  // Control said "Select an agent in the top-right …" and a page that needs an agent asked the person to pick the one
  // they had picked, until a reload (lifecycle 60; sweeps/recovery on V0571 and V0572). The saved choice survives that
  // failure; the store now tries again on its own, backing off, without a toast per try, and stops once an agent is
  // active, when the person clears their agent, on sign-out, or when the registry answers with a refusal.
  const quietAgentRetry = ref(false)
  // whether the last agent sign-in failed for want of an answer (no answer, or a server error): only that is tried again
  let agentSignInOutage = false
  const agentRetry = createBackoffRetry(() => {
    if (activeAgent.value || !isAuthenticated.value) { agentRetry.cancel(); return }
    quietAgentRetry.value = true
    return fetchAvailableAgents({ force: true }).finally(() => { quietAgentRetry.value = false })
  })

  /**
   * §INVRBAC — an admin is anyone holding admin AUTHORITY, not only the legacy
   * `is_admin` super-flag.
   *
   * `role` is derived from `is_admin` alone in five places on the hydration paths, so
   * before this fix a developer holding, say, only `admin_federation` came back as
   * role='developer' and every `isAdmin` consumer (the federation store's four guards
   * among them) refused them work the backend would happily have done. The route guard
   * had already been taught this rule in 2026-05-08; the computed had not, so the two
   * disagreed about the same account.
   *
   * Fixed here rather than at the five mapping sites on purpose: one predicate cannot
   * drift from itself. The backend remains the authority — every admin route gates on
   * its own `require_admin_flag`, so being wrong here costs a visible control, never an
   * accepted action.
   */
  const isAdmin = computed(() => {
    if (userRole.value === 'admin') return true
    const u = user.value as unknown as Record<string, unknown> | null
    if (!u) return false
    return Boolean(
      u.admin_treasury || u.admin_support || u.admin_enforcement ||
      u.admin_federation || u.admin_platform,
    )
  })
  const isAgent = computed(() => userRole.value === 'agent')
  const isDeveloper = computed(() => userRole.value === 'developer')
  // §EXCISION-10 — `must_change_password` is enforced server-side (security.py::
  // require_admin 403s every admin call until it clears) but nothing in the UI ever
  // read it, so the flag was unusable: switching it on produced a dashboard of raw
  // errors. Surfaced here so the router guard can act on it.
  const mustChangePassword = computed(() => (user.value as any)?.must_change_password === true)

  const isFederationOperator = computed(() => (user.value as any)?.is_federation_operator ?? false)
  const federationOperatorStatus = computed(() => (user.value as any)?.federation_operator_status ?? null)
  
  const sessionInfo = computed(() => authService.getSessionInfo())
  const isSessionExpired = computed(() => {
    if (!sessionExpiry.value) return false
    return new Date() > sessionExpiry.value
  })

  // Actions
  async function login(
    credentials: { email: string; password: string },
    remember = false
  ): Promise<boolean> {
    loading.value = true
    error.value = null
    rememberMe.value = remember
    
    // Store remember preference so initializeAuth knows which storage to use
    if (remember) {
      localStorage.setItem('rememberMe', 'true')
    } else {
      localStorage.removeItem('rememberMe')
    }
    
    try {
      // Check if mock data is enabled
      // Real authentication
      const response = await authService.login(credentials, remember)
      
      import.meta.env.DEV && console.log('Auth store - full login response:', JSON.stringify(response))
      import.meta.env.DEV && console.log('Auth store - requires_2fa:', response.requires_2fa)
      import.meta.env.DEV && console.log('Auth store - partial_token:', response.partial_token)
      const responseAny = response as any
      import.meta.env.DEV && console.log('Auth store - developer_id:', responseAny.developer_id)
      
      // PUSH LOGIN: the password was right but this account requires phone approval. No token
      // exists yet — we poll until the phone signs, then redeem. Placed BEFORE the 2FA branch
      // because it is the stronger factor and the server issues one or the other, never both.
      if ((response as any).requires_push_approval) {
        pushApprovalId.value = (response as any).approval_id || ''
        pushApprovalExpiresIn.value = (response as any).approval_expires_in || 120
        loading.value = false
        return false
      }

      // Check if 2FA is required
      if (response.requires_2fa) {
        // Store partial_token in 2FA store
        const twoFactorStore = useTwoFactorStore()
        if (response.partial_token) {
          import.meta.env.DEV && console.log('Setting partial_token in 2FA store:', response.partial_token)
          twoFactorStore.setPartialToken(response.partial_token)
        } else if (responseAny.developer_id) {
          import.meta.env.DEV && console.log('Setting developer_id in 2FA store:', responseAny.developer_id)
          twoFactorStore.setDeveloperId(responseAny.developer_id)
        }
        
        // Clear loading state before returning
        loading.value = false
        
        // Return false to indicate login is not complete
        // The UI should show the 2FA modal
        return false
      }
      
      // Only process full login response if 2FA is not required
      // Check if the response has user and tokens (successful login)
      if (!response.user || !response.tokens) {
        console.error('Invalid login response - missing user or tokens')
        error.value = 'Invalid server response'
        return false
      }
      
      const { user: userData, tokens } = response
      
      import.meta.env.DEV && console.log('Auth store - login response:', { userData, tokens })
      
      user.value = userData
      token.value = tokens.access_token
      
      const expiry = authService.getTokenExpiry(tokens.access_token)
      sessionExpiry.value = expiry ? new Date(expiry) : null

      // §2026-06-03: hydrate the FULL developer profile (is_admin + admin_* sub-flags
      // + role) immediately. The /auth/login response carries only a minimal user, so
      // without this the admin sub-flags are absent until a later init — and a route
      // guard gating on `requiresAdminFlag` (e.g. /admin/fx, /admin/treasury) would
      // bounce the FIRST post-login navigation to mission-control before the flags
      // loaded (the 2nd nav then worked). authService.verify() GETs /developers/me and
      // returns the user WITH every admin_* flag. Best-effort: keep the minimal user
      // on failure (a later initializeAuth still hydrates).
      try {
        const verified = await authService.verify()
        if (verified?.user) user.value = verified.user
      } catch { /* keep minimal user; the guard's init path will hydrate later */ }

      import.meta.env.DEV && console.log('Auth store - state after login:', {
        user: user.value,
        token: !!token.value,
        isAuthenticated: isAuthenticated.value
      })
      
      const uiStore = useUIStore()
      uiStore.showSuccess('Welcome back!', `Logged in as ${userData.name || userData.email}`)
      
      // Fetch available agents if developer or admin (admins can also have agents)
      import.meta.env.DEV && console.log('Checking if should fetch agents:', {
        isDeveloper: isDeveloper.value,
        isAdmin: isAdmin.value,
        userRole: userRole.value,
        user: user.value
      })
      
      if (isDeveloper.value || isAdmin.value) {
        import.meta.env.DEV && console.log('User is developer/admin, fetching available agents...')
        await fetchAvailableAgents()
      } else {
        import.meta.env.DEV && console.log('User is NOT developer/admin, skipping agent fetch')
      }
      
      return true
    } catch (err: any) {
      // §FESUITE: a refused credential (a 4xx) is the person's mistake, already shown to them; only the unexpected is an error
      if (!err?.response?.status || err.response.status >= 500) console.error('Auth store - login error:', err)
      // Read both the unified-error-envelope detail (data.error.detail, also
      // promoted to data.detail by the response interceptor) and the legacy
      // flat detail.
      const respData: any = err.response?.data
      error.value = respData?.detail
        || respData?.error?.detail
        || err.message
        || 'Login failed'
      // Set verificationRequired flag if backend signaled it via the header
      // context (also flattened to data.contextHeaders by the interceptor).
      const ctxHeaders = respData?.contextHeaders
        || respData?.error?.context?.headers
      verificationRequired.value = ctxHeaders?.['X-Verification-Required'] === 'true'
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * The Log out BUTTON. `POST /auth/logout` bumps the developer's token_version, which ends this developer's sessions
   * on EVERY device (the product's "log out everywhere"), then the local teardown.
   */
  async function logout() {
    loading.value = true

    try {
      // Real logout
      await authService.logout()

      const uiStore = useUIStore()
      uiStore.showInfo('Logged out', 'You have been successfully logged out')
    } catch (err) {
      console.error('Logout error:', err)
    } finally {
      await teardownLocalState()
    }
  }

  /**
   * §FEFRAME W1 — an AUTOMATIC end of the session (a 401 after a failed refresh, a session that no longer verifies at
   * boot, a refresh the server refused, the socket's auth_expired). LOCAL ONLY: it never calls `POST /auth/logout`.
   * Before V0502 these paths called the button's logout, so one tab's transient 401 during a registry restart bumped
   * token_version and logged the person out on their phone too (§FRAMESHOWCASE residue 2, §RELEASEHARDEN D3).
   */
  async function endLocalSession(reason: string) {
    log.info(`ending the local session (${reason}); the server is not told, other devices stay signed in`)
    authService.clearAuth()
    await teardownLocalState()
  }

  async function teardownLocalState() {
    agentRetry.cancel()
    {
      // 2026-05-08 P2.2: invoke globalReset BEFORE clearing auth state to
      // wipe sibling Pinia stores so user-A's data doesn't leak into
      // user-B's session on a same-browser handover. See globalReset.ts.
      try {
        const { globalReset } = await import('./globalReset')
        globalReset()
      } catch (resetErr) {
        // non-fatal; auth-state still gets cleared below
        console.error('globalReset failed during logout', resetErr)
      }

      // §pass42 (2026-05-18) — Reverted the 2026-05-08 P4.1 "audit §6.4"
      // localStorage wipe on logout. Rationale for keeping these:
      //   * agentCredentialsStore is keyed by AGENT DID. AgentSwitcher's
      //     `mergeWithStoredCredentials` only decorates DIDs that the
      //     backend returned via `/developers/me/agents` — which is
      //     already scoped to the authenticated developer. User-A's
      //     credentials cannot appear in user-B's dropdown because the
      //     API never returns user-A's DIDs to user-B.
      //   * agentDidsCache is already keyed by developer.id internally
      //     (`cache[dev_<id>]`), so cross-user leak isn't possible there.
      // The P4.1 wipe was over-aggressive — every logout destroyed
      // Commander's pasted client_secrets, forcing manual re-entry on
      // every relog. Bulk-import-from-JSON existed precisely so people
      // could survive this, but the persistence layer should not be
      // resetting state it doesn't need to. Credentials now survive
      // logout/login cycles, matching the original intent documented at
      // services/agentCredentialsStore.ts:7-19.
      //
      // For paranoid users wanting an explicit credential purge, expose
      // a "Clear all stored credentials" button on Settings (separate
      // sprint) — but don't force it on every logout.
      //
      // §FEFRAME W1 (V0502): the premise above ("the API never returns
      // user-A's DIDs to user-B") stopped holding when §agentfinder began
      // synthesizing a switcher row from EVERY stored credential. What makes
      // keeping them safe now is that every read is scoped to the logged-in
      // developer (agentCredentialsStore.setCurrentOwner); the purge exists
      // as forgetCredential / forgetAllCredentials.

      // Clear state
      user.value = null
      token.value = null
      sessionExpiry.value = null
      rememberMe.value = false
      loading.value = false

      // Clear agent context
      clearActiveAgent()
      availableAgents.value = []

      // §FEFRAME W1 — what used to outlive the session: the per-registry sessions and their refresh tokens (the store
      // has no $reset, so globalReset skipped it), the two stored `user` copies (two writers, no remover), and the
      // unsealed secrets of a biometric vault (they leave memory with the session; the blob stays).
      try {
        const { useCommandSessions } = await import('./commandSessions')
        useCommandSessions().resetAll()
      } catch (e) { log.warn('the per-registry sessions could not be reset at logout', e) }
      try { localStorage.removeItem('user'); sessionStorage.removeItem('user') } catch { /* storage blocked */ }
      // §FEFRAME W4: the assistant's bring-your-own provider key (composables/useAssistantBrains.ts) is a secret of the
      // person who typed it; it outlived every logout and answered for the next person in this browser
      try { localStorage.removeItem('tp_byok') } catch { /* storage blocked */ }
      try {
        const { credentialVault } = await import('@/services/credentialVault')
        if (credentialVault.kdf() === 'webauthn-prf') credentialVault.relock()
      } catch { /* no vault */ }
      agentCredentialsStore.setCurrentOwner(null)
    }
  }

  async function register(userData: {
    email: string
    password: string
    name?: string
    invite_code?: string
  }): Promise<boolean> {
    loading.value = true
    error.value = null
    
    try {
      const newUser = await authService.register(userData)
      
      const uiStore = useUIStore()
      uiStore.showSuccess(
        'Registration successful!',
        'Please check your email to verify your account.'
      )
      
      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || err.message || 'Registration failed'
      return false
    } finally {
      loading.value = false
    }
  }

  /* §FESUITE (worker C measured it): the store starts a restore when it is created and the router guard started a second
     one beside it; a guard that checked a role against a user restored from storage (or none yet) refused an admin page
     the person holds. One restore at a time, and `authSettling()` lets the guard wait for it before it refuses. */
  let authInFlight: Promise<void> | null = null
  function initializeAuth(): Promise<void> {
    if (authInFlight) return authInFlight
    const run = initializeAuthNow().finally(() => { if (authInFlight === run) authInFlight = null })
    authInFlight = run
    return run
  }
  function authSettling(): Promise<void> | null { return authInFlight }

  async function initializeAuthNow() {
    import.meta.env.DEV && console.log('Initializing auth...')
    
    // Real auth initialization
    // Check if rememberMe was set
    rememberMe.value = localStorage.getItem('rememberMe') === 'true'
    
    // First, try to restore from storage
    let storedToken = authService.getAccessToken()
    if (!storedToken) {
      // §POCKETBRIDGE #PK24 (F7, S14) — the access token is sessionStorage-only
      // by design, so EVERY real app restart (installed PWA especially) arrives
      // here empty. The durable rememberMe refresh token was sitting in
      // localStorage the whole time and was never asked: cold boot went
      // straight to the login form. Ask it. A refusal (rotated password bumps
      // token_version, revocation, expiry) falls through to the login form
      // exactly as before — the lock screen, not the login wall, should greet
      // a returning user, and a password change must still log every device out.
      const refresh = authService.getRefreshToken()
      if (refresh) {
        try {
          const tokens = await authService.refreshAccessToken()
          if (tokens?.access_token) storedToken = tokens.access_token
        } catch { /* refresh refused — the login form is the honest answer */ }
      }
      if (!storedToken) {
        import.meta.env.DEV && console.log('No stored token found')
        return
      }
    }

    // Restore token immediately
    token.value = storedToken

    // 2026-04-25 — Re-arm the auto-refresh timer that's normally set only on
    // login. Without this, page reloads / long-lived tabs lose the timer and
    // the access token expires silently after 30 min, forcing reactive refresh
    // on every subsequent request (and previously: forcing logout via the
    // response interceptor when a non-exempt URL like /notifications/unread
    // got polled by the LED ticker).
    //
    // scheduleTokenRefresh handles three cases internally:
    //   • >5 min until expiry → set setTimeout for (expiry - 5min)
    //   • ≤5 min until expiry → fire refresh immediately (eager)
    //   • already expired but refresh_token still valid → fire refresh immediately
    authService.scheduleTokenRefresh(storedToken)

    // Try to restore user data from storage (check correct storage based on rememberMe)
    const storedUser = rememberMe.value
      ? localStorage.getItem('user')
      : sessionStorage.getItem('user') || localStorage.getItem('user')
    if (storedUser) {
      try {
        const userData = JSON.parse(storedUser)
        // Ensure role is set
        if (!userData.role) {
          // Admin role from backend only (no email-based override)
          userData.role = userData.is_admin ? 'admin' : 'developer'
        }
        user.value = userData
        import.meta.env.DEV && console.log('User restored from storage:', userData)
      } catch (e) {
        console.error('Failed to parse stored user data:', e)
      }
    }
    
    // §FEFRAME W1: NO axios default Authorization header. axios merges defaults BEFORE the request interceptor runs, so
    // this header rode every request the interceptor deliberately sent without one (the public venue reads at a foreign
    // agent's registry) and every request after logout until a reload. The interceptor sets the right token per call.
    
    // Now verify the session is still valid
    const sessionInfo = authService.getSessionInfo()
    
    if (sessionInfo.isActive) {
      // If we have sessionInfo.user, use it to update our user
      if (sessionInfo.user) {
        const userData = sessionInfo.user
        if (!userData.role) {
          // Admin role from backend only (no email-based override)
          userData.role = userData.is_admin ? 'admin' : 'developer'
        }
        user.value = userData
      }
      
      sessionExpiry.value = sessionInfo.expiresAt
      
      import.meta.env.DEV && console.log('Auth initialized:', {
        user: user.value,
        hasToken: !!token.value,
        role: user.value?.role
      })
      
      // Verify session is still valid with backend
      try {
        const verifiedUser = await authService.verifySession()
        if (verifiedUser) {
          // Update user with verified data
          if (!verifiedUser.role) {
            // Admin role from backend only (no email-based override)
            verifiedUser.role = verifiedUser.is_admin ? 'admin' : 'developer'
          }
          user.value = verifiedUser
          
          // Store updated user data
          const storage = rememberMe.value ? localStorage : sessionStorage
          storage.setItem('user', JSON.stringify(user.value))
          
          // Fetch agents for developers/admins. `force: true` bypasses the
          // agent-DIDs cache so a hard refresh always shows the latest list
          // (was BUG — stale cache hid newly-created agents for up to 30s).
          if (isDeveloper.value || isAdmin.value) {
            import.meta.env.DEV && console.log('Developer/Admin detected - fetching available agents (force)…')
            await fetchAvailableAgents({ force: true })
          }
        } else {
          import.meta.env.DEV && console.log('Session verification failed')
          await endLocalSession('the stored session no longer verifies')
        }
      } catch (err) {
        console.error('Session verification error:', err)
        // Don't logout on network errors, keep the local session
        // The user is probably still valid
      }
    } else {
      import.meta.env.DEV && console.log('Session expired or invalid')
      await endLocalSession('the stored session expired')
    }
  }

  async function refreshSession() {
    try {
      const tokens = await authService.refreshAccessToken()
      if (tokens) {
        token.value = tokens.access_token
        const expiry = authService.getTokenExpiry(tokens.access_token)
        sessionExpiry.value = expiry ? new Date(expiry) : null
        return true
      }
    } catch (err) {
      await endLocalSession('the server refused the refresh')
    }
    return false
  }

  async function requestPasswordReset(email: string): Promise<boolean> {
    loading.value = true
    error.value = null
    
    try {
      await authService.requestPasswordReset(email)
      
      const uiStore = useUIStore()
      uiStore.showSuccess(
        'Password reset email sent',
        'Please check your email for instructions to reset your password.'
      )
      
      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || 'Failed to send reset email'
      return false
    } finally {
      loading.value = false
    }
  }

  async function resetPassword(token: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    
    try {
      await authService.resetPassword(token, password)
      
      const uiStore = useUIStore()
      uiStore.showSuccess(
        'Password reset successful',
        'You can now log in with your new password.'
      )
      
      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || 'Failed to reset password'
      return false
    } finally {
      loading.value = false
    }
  }

  function checkAuth(requiredRole?: string): boolean {
    if (!isAuthenticated.value) {
      log.debug('checkAuth: Not authenticated')
      return false
    }
    if (!requiredRole) {
      log.debug('checkAuth: No role required, authenticated user allowed')
      return true
    }

    // RBAC audit fix (2026-05-08): the 'admin' role gate must accept users
    // with EITHER the legacy is_admin super-flag OR any granular admin
    // sub-flag (`admin_treasury`, `admin_platform`, `admin_enforcement`,
    // `admin_federation`, `admin_support`). Without this, sub-flag-only
    // admins were blocked at the route guard despite seeing matching
    // sidebar items — the per-endpoint backend gates would later reject
    // wrong-flag actions, but reaching the right-flag view was impossible
    // through the URL bar. Sidebar visibility still uses the per-flag
    // predicates in `usePermissions`, so users only see items they can
    // actually use; the route guard just stops being unconditionally
    // restrictive on sub-flag admins.
    if (requiredRole === 'admin') {
      const u = user.value as unknown as Record<string, unknown> | null
      if (!u) return false
      if (u.is_admin === true) return true
      const hasAnyAdminFlag = Boolean(
        u.admin_treasury || u.admin_support || u.admin_enforcement ||
        u.admin_federation || u.admin_platform,
      )
      log.debug('checkAuth(admin):', { is_admin: u.is_admin, hasAnyAdminFlag })
      return hasAnyAdminFlag
    }

    const hasRole = userRole.value === requiredRole
    log.debug('checkAuth:', {
      requiredRole,
      userRole: userRole.value,
      hasRole,
      user: user.value,
    })

    return hasRole
  }

  function clearError() {
    error.value = null
    verificationRequired.value = false
  }
  
  async function processSuccessfulLogin(loginData: {
    access_token: string
    token_type?: string
    user?: User
    refresh_token?: string
  }, remember?: boolean) {
    loading.value = true
    
    try {
      // Set the token
      token.value = loginData.access_token
      // Use remember flag or check if we already have rememberMe set (from original login)
      const shouldRemember = remember !== undefined ? remember : (rememberMe.value || localStorage.getItem('rememberMe') === 'true')
      rememberMe.value = shouldRemember
      
      // Store remember preference
      if (shouldRemember) {
        localStorage.setItem('rememberMe', 'true')
      } else {
        localStorage.removeItem('rememberMe')
      }
      
      authService.setTokens({
        access_token: loginData.access_token,
        refresh_token: loginData.refresh_token || '',
        token_type: loginData.token_type || 'bearer'
      }, shouldRemember)
      
      // §FEFRAME W1: no axios default Authorization header (see initializeAuth); the interceptor sets it per call.
      
      // Get user data if not provided
      if (loginData.user) {
        // Map role if not present
        const userData = loginData.user
        if (!userData.role) {
          // Map is_admin to role
          // Admin role from backend only
          // Admin role from backend only (no email-based override)
          userData.role = userData.is_admin ? 'admin' : 'developer'
        }
        user.value = userData
      } else {
        // Fetch user data using the token
        // §FESUITE: verify() now throws on "could not verify" (only a refusal answers valid:false); a login whose profile
        // cannot be read this moment keeps its token, and the restore or the guard hydrates the user later
        const verifyResponse = await authService.verify().catch(() => ({ valid: false, user: null as any }))
        if (verifyResponse.valid) {
          const userData = verifyResponse.user
          if (!userData.role) {
            // Admin role from backend only
            // Admin role from backend only (no email-based override)
            userData.role = userData.is_admin ? 'admin' : 'developer'
          }
          user.value = userData
        }
      }
      
      // Set session expiry
      const expiry = authService.getTokenExpiry(loginData.access_token)
      sessionExpiry.value = expiry ? new Date(expiry) : null
      
      // Store user data based on remember flag
      if (user.value) {
        const storage = shouldRemember ? window.localStorage : window.sessionStorage
        storage.setItem('user', JSON.stringify(user.value))
      }
      
      const uiStore = useUIStore()
      uiStore.showSuccess('Welcome back!', `Logged in as ${user.value?.name || user.value?.email}`)
      
      // Fetch available agents if developer or admin (CRITICAL FOR AGENT AUTH!)
      import.meta.env.DEV && console.log('processSuccessfulLogin - Checking if should fetch agents:', {
        isDeveloper: isDeveloper.value,
        isAdmin: isAdmin.value,
        userRole: userRole.value,
        user: user.value
      })
      
      if (isDeveloper.value || isAdmin.value) {
        import.meta.env.DEV && console.log('User is developer/admin, fetching available agents after 2FA...')
        await fetchAvailableAgents()
      } else {
        import.meta.env.DEV && console.log('User is NOT developer/admin, skipping agent fetch')
      }
      
      return true
    } catch (err) {
      console.error('Failed to process login:', err)
      error.value = 'Failed to complete login'
      return false
    } finally {
      loading.value = false
    }
  }

  // Agent-specific actions
  // §agentfinder (2026-07-26) — server-side finder. Resolves ANY of the
  // developer's agents by name or DID across the whole fleet (not just the
  // recency window loaded into availableAgents). Merges local credentials so
  // a found agent that the user already holds creds for is immediately
  // switchable; found agents without creds route through the add-credentials
  // flow (AgentSwitcher.selectAgent). The finder is additive over the local
  // list, never destructive. §FESUITE (V0577): a search that got no answer
  // returns null, not [] (the switcher said "No agents match… Searched your
  // whole fleet" over a search that never answered); [] is an answer of none.
  async function searchAgents(query: string): Promise<any[] | null> {
    const qq = (query || '').trim()
    if (qq.length < 2) return []
    if (!isAuthenticated.value || (!isDeveloper.value && !isAdmin.value)) return []
    try {
      const resp = await apiClient.get(
        `/developers/me/agents?q=${encodeURIComponent(qq)}&limit=50`
      )
      const raw = (resp.data as any[]) || []
      // Same credential-hygiene the main fetch uses: strip any backend
      // credential claims, then merge our locally-stored creds back in.
      const cleaned = raw.map((a: any) => {
        const c = { ...a }
        delete c.client_id; delete c.client_secret
        delete c.hasCredentials; delete c.hasInvalidCredentials
        return c
      })
      return agentCredentialsStore.mergeWithStoredCredentials(cleaned) || []
    } catch (e) {
      import.meta.env.DEV && console.warn('[Auth Store] searchAgents failed', e)
      return null
    }
  }

  /**
   * §OWNEDHOMES — a foreign agent's COSMETICS live at its own registry.
   *
   * "hypervisor hagrid is logged in on frame-c it works but its cosmetics from
   * registry-a is not loading which is sad." Measured, and he is exactly right:
   * `/fiat/flare/agent/{did}` answers `flare_tier: sovereign` at
   * api.theprotocol.cloud and **404** for the same DID on frame-c. The flare is
   * not mirrored and never will be — it is the home registry's record.
   *
   * The endpoint is public and sends `access-control-allow-origin: *`, so this
   * is one unauthenticated GET to the origin, cached for the session. BOUNDED
   * by the caller: this is a decoration, and §LAZYBAL was an unbounded
   * per-agent loop that left the whole switcher empty.
   */
  const foreignFlareCache = new Map<string, any>()
  async function hydrateForeignFlares(dids: string[], cap = 24): Promise<number> {
    const rows = availableAgents.value as any[]
    const byDid = new Map(rows.filter(a => a?.did).map(a => [String(a.did), a]))
    const work: Array<{ did: string; origin: string }> = []
    for (const raw of dids) {
      const did = String(raw || '')
      if (!did || work.length >= cap) continue
      const a = byDid.get(did)
      if (!a || a.flare_tier) continue                    // already has one
      const u = a.registry_url
      if (!u || typeof u !== 'string') continue
      let origin = ''
      try { const p = new URL(u); if (p.origin === window.location.origin) continue; origin = p.origin }
      catch { continue }
      if (foreignFlareCache.has(did)) {
        const cached = foreignFlareCache.get(did)
        if (cached) Object.assign(a, cached)
        continue
      }
      work.push({ did, origin })
    }
    if (!work.length) return 0
    let applied = 0

    /**
     * §COSMETICS (Commander 2026-08-21) — ask OUR OWN registry first.
     * Federation already mirrors every agent's flare into
     * `agent_cards.card_data.flare`, so the cosmetics for a foreign agent are
     * almost always sitting in the local database already. One batched local
     * call answers what used to be one cross-origin request per agent.
     * Anything the local mirror has never seen still falls through to the
     * per-origin path below, so this is strictly a saving.
     */
    const stillUnknown: Array<{ did: string; origin: string }> = []
    try {
      for (let i = 0; i < work.length; i += 100) {   // §DIDCHUNK: 300 DIDs is a rejected URL
        const slice = work.slice(i, i + 100)
        const { data } = await apiClient.get('/agents/cosmetics', {
          params: { dids: slice.map(w => w.did).join(',') },
        })
        const got = (data && data.cosmetics) || {}
        for (const w of slice) {
          const c = got[w.did]
          if (!c) { stillUnknown.push(w); continue }
          const patch = {
            flare_tier: c.flare_tier ?? null,
            flare_granted_at: c.flare_granted_at ?? null,
            flare_id: c.flare_id ?? null,
            flare_display_name: c.flare_display_name ?? null,
            flare_tagline: c.flare_tagline ?? null,
            flare_logo_url: c.flare_logo_url ?? null,
            flare_link_url: c.flare_link_url ?? null,
            flare_cause: c.flare_cause ?? null,
            flare_accent_color: c.flare_accent_color ?? null,
            flare_encirclement_variant: c.flare_encirclement_variant ?? null,
            flare_encirclement_overlay: c.flare_encirclement_overlay ?? null,
            flare_corner_variant: c.flare_corner_variant ?? null,
            bears_corner_flare: !!c.bears_corner_flare,
            bears_encirclement_flare: !!c.bears_encirclement_flare,
            selected_corner_flare: c.selected_corner_flare ?? null,
            selected_encirclement_flare: c.selected_encirclement_flare ?? null,
          }
          foreignFlareCache.set(w.did, patch)
          const a = byDid.get(w.did)
          if (a) { Object.assign(a, patch); applied++ }
        }
      }
      work.length = 0
      work.push(...stillUnknown)
    } catch {
      // The local resolver is an optimisation, never a requirement: if it is
      // unavailable (an older registry in the fleet), fall through untouched.
    }
    if (!work.length) {
      if (applied) availableAgents.value = [...(availableAgents.value as any[])]
      return applied
    }
    // Small concurrency: a dropdown that opens should not fire 24 requests at once.
    const CONC = 4
    for (let i = 0; i < work.length; i += CONC) {
      await Promise.all(work.slice(i, i + CONC).map(async ({ did, origin }) => {
        try {
          const f: any = await fiatOnrampService.getAgentFlare(did, origin)
          // A registry that HAS the agent but grants it no flare is a real
          // answer: cache the null so we never ask twice.
          const patch = f && f.flare_tier ? {
            flare_tier: f.flare_tier,
            flare_granted_at: f.flare_granted_at ?? null,
            flare_id: f.flare_id ?? null,
            flare_display_name: f.display_name ?? null,
            flare_tagline: f.tagline ?? null,
            flare_logo_url: f.logo_url ?? null,
            flare_link_url: f.link_url ?? null,
            flare_cause: f.cause ?? null,
            flare_accent_color: f.accent_color ?? null,
          } : null
          foreignFlareCache.set(did, patch)
          if (patch) {
            const a = byDid.get(did)
            if (a) { Object.assign(a, patch); applied++ }
          }
        } catch {
          // Unreachable home, or no such agent there. Remember the miss so an
          // open/close of the dropdown does not re-ask forever.
          foreignFlareCache.set(did, null)
        }
      }))
    }
    if (applied) availableAgents.value = [...(availableAgents.value as any[])]
    return applied
  }

  /* §FESUITE: one agent load at a time. A second caller while one is in flight (the router guard beside the layout's
     boot) shares it instead of starting another, and so waits for the saved agent's restore it would otherwise race:
     the guard used to see the list filled, the agent not yet switched, and abort a cold deep link to a blank page. */
  let agentsInFlight: Promise<void> | null = null
  function fetchAvailableAgents(opts?: { force?: boolean }): Promise<void> {
    if (agentsInFlight && !opts?.force) return agentsInFlight
    const run = fetchAvailableAgentsNow(opts).finally(() => { if (agentsInFlight === run) agentsInFlight = null })
    agentsInFlight = run
    return run
  }

  async function fetchAvailableAgentsNow(opts?: { force?: boolean }) {
    if (!isAuthenticated.value || (!isDeveloper.value && !isAdmin.value)) return

    const force = !!opts?.force
    agentLoading.value = true
    agentFetchFailed.value = false
    credentialsChecked.value = false // Reset flag at start
    import.meta.env.DEV && console.log('[Auth Store] Starting agent fetch', { force })
    try {
      import.meta.env.DEV && console.log('Fetching available agents from API...')

      // Try to use cached agents first (unless caller forces a refresh —
      // e.g. picker refresh button or hard-refresh init path).
      let agents = force ? null : agentDidsCache.getCachedAgents(user.value?.id)
      let usingCache = false

      if (!agents) {
        // §agentfinder (2026-07-26) — always force-include the agents we hold
        // local credentials for, so a working agent created long ago (behind
        // thousands of newer fixtures) is returned + hydrated despite the
        // created_at-DESC window cap. Without this, credentialed agents outside
        // the top-`limit` window never appear in the switcher at all, so no
        // amount of client-side sorting can surface them.
        /*
         * §DIDCHUNK (2026-08-20) — LOCAL FIRST, then top up in bounded chunks.
         *
         * This used to stuff up to 300 credentialed DIDs into ONE query string.
         * Measured against the live registry:
         *     50 dids →  2,372 char URL → 200
         *    150 dids →  6,972 char URL → 200
         *    300 dids → 13,872 char URL → REJECTED in 28ms, 0 bytes
         * So the moment an operator imported 600+ credentials, this request died
         * on its size, `agents` came back empty, and the switcher declared
         * "No agents yet" to someone who owns 4,432 of them. It got WORSE the
         * more credentials you had, which is the opposite of the intent.
         *
         * The base list is fetched with NO include_dids, so it can never be
         * rejected for length and the local fleet always paints. Credentialed
         * DIDs the base window missed are then topped up in chunks, and a failed
         * top-up is swallowed: it must never destroy a base list that worked.
         */
        // §FEFRAME W1: only agents saved for THIS registry can come back from it; a foreign DID in include_dids was
        // a guaranteed miss (up to 600 of them, six wasted round trips)
        const credentialedDids = Object.entries(agentCredentialsStore.getAllCredentials())
          .filter(([, c]) => {
            const u = c?.registry_url
            if (!u) return true
            try { return new URL(u).origin === window.location.origin } catch { return true }
          })
          .map(([did]) => did)
        /*
         * §COCKPITPOLISH P2 (2026-08-31) — `sort=live`, because the DEFAULT WINDOW was
         * the defect, not the ordering inside it. With no sort the server answers
         * created_at DESC, and on registry-a the newest 200 of a 4,130-agent account are
         * forge fixtures and `<no name>` rows: the switcher opened on a list containing
         * none of the operator's real agents, and no amount of client-side sorting can
         * surface an agent the response never contained. `live` orders by
         * `last_active_at DESC NULLS LAST` — the 21 agents that actually called this
         * registry come first, then everything else, nothing dropped.
         */
        const response = await apiClient.get('/developers/me/agents', { params: { sort: 'live' } })
        agents = response.data as any[]

        if (Array.isArray(agents) && credentialedDids.length) {
          const have = new Set(agents.map((a: any) => String(a?.did || '')))
          const missing = credentialedDids.filter(d => !have.has(d))
          const CHUNK = 100          // ~4.6 KB of URL — well inside what 150 proved safe
          const MAX = 600            // a hard stop, not a guess
          for (let i = 0; i < missing.length && i < MAX; i += CHUNK) {
            try {
              const top = await apiClient.get('/developers/me/agents', {
                params: { include_dids: missing.slice(i, i + CHUNK).join(',') },
              })
              for (const a of (top.data as any[]) || []) {
                const d = String(a?.did || '')
                if (d && !have.has(d)) { have.add(d); agents.push(a) }
              }
            } catch {
              // Partial is honest; empty is not. Keep what already loaded.
              break
            }
          }
        }
        
        // CRITICAL: Log what backend is sending
        import.meta.env.DEV && console.log('[Auth Store] 🚨 BACKEND RESPONSE - checking for credentials:');
        agents.forEach((a: any, idx: number) => {
          if (a.client_id || a.client_secret || a.hasCredentials) {
            import.meta.env.DEV && console.log(`  ⚠️ Agent ${idx}: Backend sent credentials! client_id=${!!a.client_id}, secret=${!!a.client_secret}, hasCredentials=${a.hasCredentials}`);
          }
        })
        
        // 🦉 FIX: Clean backend contamination IMMEDIATELY
        import.meta.env.DEV && console.log('[Auth Store] 🧹 CLEANING backend response to remove credential contamination...');
        agents = agents.map((agent: any) => {
          // Create clean copy without credential fields
          const cleaned = { ...agent }
          delete cleaned.hasCredentials     // Remove backend's false claims
          delete cleaned.hasInvalidCredentials
          delete cleaned.client_id          // Backend should never send these
          delete cleaned.client_secret
          
          import.meta.env.DEV && console.log(`[Auth Store] Cleaned ${agent.did?.substring(0, 30) || 'NO_DID'}...: removed backend credential claims`);
          return cleaned
        })
        
        // §FEFRAME W1: no early return here any more. A developer whose only agents live on other registries has none
        // on this one, and returning before the saved rows were merged left the switcher empty and
        // `credentialsChecked` false (the selector spun forever). The empty case is decided after the merge below.
        if (agents && agents.length) {
          // the server just confirmed these agents are this developer's: claim any unclaimed saved row for them
          agentCredentialsStore.claim(agents.map((a: any) => String(a?.did || '')).filter(Boolean))
          // Cache the agents for future use
          agentDidsCache.cacheAgents(agents, user.value?.id)
        }
      } else {
        usingCache = true
        import.meta.env.DEV && console.log(`Using cached agent list (${agents.length} agents)`)
      }
      
      // §FEFRAME W3: every row the server listed (or the cache of that list) is this developer's own agent: it can be
      // acted as through the owner rail with no saved secret (authenticateAsAgent). Saved-credential rows added below
      // carry no such mark.
      agents = agents.map((a: any) => ({ ...a, owned: true }))

      // Merge with stored credentials first
      const mergedAgents = agentCredentialsStore.mergeWithStoredCredentials(agents)
      if (!mergedAgents) return
      agents = mergedAgents

      // §agentfinder (2026-07-26) — belt-and-suspenders: if a stored-credential
      // agent is STILL missing after fetch+merge (backend omitted it, cache
      // path, or a transient error), synthesize a minimal row from the stored
      // credentials so the user's working set is NEVER invisible. These carry
      // hasCredentials=true and thus sort to the top; balances hydrate below
      // (or default to 0). This is the last line of defense behind the
      // server-side include_dids force-include.
      try {
        const stored = agentCredentialsStore.getAllCredentials()
        const present = new Set(agents.map((a: any) => a.did))
        for (const did of Object.keys(stored)) {
          if (present.has(did)) continue
          const c = stored[did]
          if (!c?.client_id || !c?.client_secret) continue
          agents.push({
            did,
            client_id: c.client_id,
            client_secret: c.client_secret,
            name: c.name || null,
            humanReadableId: c.humanReadableId,
            registry: c.registry,
            registry_url: c.registry_url,
            status: 'unknown',
            hasCredentials: true,
            hasInvalidCredentials: false,
            liquid_balance: '0',
            staked_balance: '0',
          })
        }
      } catch (e) {
        import.meta.env.DEV && console.warn('[Auth Store] synthesize-missing-credentialed failed', e)
      }

      if (!agents.length) {
        import.meta.env.DEV && console.log('No agents found for developer (none here, none saved)')
        availableAgents.value = []
        credentialsChecked.value = true
        return
      }
      
      // CRITICAL DEBUG: Log the state after merging
      import.meta.env.DEV && console.log('[Auth Store] 🔍 CREDENTIAL CHECK after merge:');
      agents.forEach((a: any) => {
        const hasActualCreds = !!(a.client_id && a.client_secret);
        const prefix = a.did?.substring(0, 30) || 'NO_DID';
        if (a.name?.includes('Charlie')) {
          import.meta.env.DEV && console.log(`  🦉 CHARLIE: ${prefix}... hasCredentials=${a.hasCredentials}, actualCreds=${hasActualCreds}`);
        } else {
          import.meta.env.DEV && console.log(`  📍 Agent: ${prefix}... hasCredentials=${a.hasCredentials}, actualCreds=${hasActualCreds}`);
        }
      });
      
      // DON'T CHANGE hasCredentials - trust what mergeWithStoredCredentials set
      // The merge function already handles everything correctly
      
      // CRITICAL: Mark credentials as checked NOW, before any async operations
      credentialsChecked.value = true
      import.meta.env.DEV && console.log('[Auth Store] ✅ Credentials checked! credentialsChecked = true')
      
      import.meta.env.DEV && console.log(`Found ${agents.length} agents, ${agents.filter((a: any) => a.hasCredentials).length} have credentials`)
      import.meta.env.DEV && console.log('Agent credentials check:', agents.map((a: any) => ({
        did: a.did.substring(0, 20) + '...',
        hasCredentials: a.hasCredentials,
        hasClientId: !!a.client_id,
        hasClientSecret: !!a.client_secret
      })))
      
      import.meta.env.DEV && console.log(`Fetching balances for ${agents.length} agents...`)
      
      // Only fetch balances for agents with ACTUAL credentials to avoid 401 errors
      /*
       * §LAZYBAL (2026-08-20) — PUBLISH THE LIST BEFORE HYDRATING BALANCES.
       *
       * Measured: with 608 stored credentials (560 of them FOREIGN) the switcher
       * showed "No agents yet" and never recovered, with NO error anywhere. The
       * list was not failing — it had not been assigned yet. Balance hydration
       * batches 50 DIDs at a time, the batch fails for agents this registry does
       * not own, and the fallback is `fetchIndividualBalances`: an UNBOUNDED
       * SEQUENTIAL loop, one HTTP request per agent. ~608 of those runs for
       * minutes while `availableAgents` sits at its initial [].
       *
       * Bisected: 0 creds -> 200 rows · 48 LOCAL creds -> 248 rows ·
       * 608 mixed creds -> 0 rows.
       *
       * So the agent list is published NOW, with zero balances, and re-published
       * once balances land. A slow number must never hide the thing it decorates.
       */
      availableAgents.value = agents.map((a: any) => ({
        ...a,
        liquidBalance: 0, stakedBalance: 0, totalBalance: 0, balance: 0,
        balancesPending: true,
      }))
      credentialsChecked.value = true

      /*
       * A FOREIGN agent has no balance ON THIS REGISTRY, so asking for one is a
       * guaranteed miss that costs a request and then a fallback request. Only
       * hydrate agents that live here.
       */
      const isLocalAgent = (a: any): boolean => {
        const u = a?.registry_url
        if (!u || typeof u !== 'string') return true          // no address = local
        try { return new URL(u).origin === window.location.origin } catch { return true }
      }
      const agentsWithCredentials = agents.filter((agent: any) => 
        agent.hasCredentials === true && agent.client_id && agent.client_secret && isLocalAgent(agent)
      )
      
      import.meta.env.DEV && console.log(`Filtered to ${agentsWithCredentials.length} agents with credentials (from ${agents.length} total)`)
      
      // Prepare agent DIDs for batch balance query (only those with credentials)
      const agentDids = agentsWithCredentials.map((agent: any) => agent.did)
      
      // Fetch all balances - batch in chunks of 50 (API limit)
      let balances: Record<string, any> = {}
      const BATCH_SIZE = 50
      
      if (agentDids.length <= BATCH_SIZE) {
        // Single batch request
        try {
          const balanceResponse = await apiClient.post('/developers/me/agents/balances', {
            agent_dids: agentDids
          })
          
          // Response is wrapped: {"balances": {did: {...}}} — unwrap it
          const rawData = balanceResponse.data || {}
          balances = rawData.balances || rawData
          import.meta.env.DEV && console.log('Batch balance response:', Object.keys(balances).length, 'balances received')
        } catch (balanceError: any) {
          console.error('Batch balance endpoint failed:', balanceError.response?.data || balanceError)
          
          // Fallback to individual queries, for the agents the batch asked about. §FESUITE (2026-10-09): it was handed
          // the WHOLE list, so a failed batch (a registry restart, a cold boot while the API failed) asked the balance of
          // up to 25 agents one by one that the batch never would: revoked agents (the route answers 404 for anything
          // not active), agents with no credentials in this browser, foreign agents (§LAZYBAL's guaranteed miss). The
          // multi-batch path below always passed its own batch.
          await fetchIndividualBalances(agentsWithCredentials, balances)
        }
      } else {
        // Multiple batches needed
        import.meta.env.DEV && console.log(`Processing ${Math.ceil(agentDids.length / BATCH_SIZE)} batches of ${BATCH_SIZE} agents each...`)
        
        for (let i = 0; i < agentDids.length; i += BATCH_SIZE) {
          const batchDids = agentDids.slice(i, i + BATCH_SIZE)
          import.meta.env.DEV && console.log(`Fetching batch ${Math.floor(i / BATCH_SIZE) + 1}: ${batchDids.length} agents`)
          
          try {
            const balanceResponse = await apiClient.post('/developers/me/agents/balances', {
              agent_dids: batchDids
            })
            
            // Merge this batch into the overall balances (unwrap {balances: {...}})
            const batchRaw = balanceResponse.data || {}
            Object.assign(balances, batchRaw.balances || batchRaw)
          } catch (batchError: any) {
            console.error(`Batch ${Math.floor(i / BATCH_SIZE) + 1} failed:`, batchError.response?.data || batchError)
            
            // Fallback to individual queries for this batch
            const batchAgents = agents.filter((a: any) => batchDids.includes(a.did))
            await fetchIndividualBalances(batchAgents, balances)
          }
        }
        
        import.meta.env.DEV && console.log('All batches complete. Total balances:', Object.keys(balances).length)
      }
      
      // Combine ALL agents with their balance data (including those without credentials)
      const agentsWithBalances = agents.map((agent: any) => {
        const balanceData = balances[agent.did] || {
          liquid_balance: '0',
          staked_balance: '0',
          total_balance: '0'
        }
        
        // Parse balance values — TEG batch endpoint returns "balance" (liquid only)
        // Registry API returns liquid_balance + staked_balance in the agent object
        // Combine both sources: prefer TEG for liquid, registry for staked
        const tegLiquid = parseFloat(balanceData.balance || balanceData.liquid_balance || '0')
        const registryStaked = parseFloat(agent.staked_balance || '0')
        const tegStaked = parseFloat(balanceData.staked_balance || '0')
        
        // Use TEG liquid balance (accurate), fall back to registry staked (TEG doesn't track staking)
        const liquidBalance = tegLiquid > 0 ? tegLiquid : parseFloat(agent.liquid_balance || '0')
        const stakedBalance = tegStaked > 0 ? tegStaked : registryStaked
        const totalBalance = parseFloat(balanceData.total_balance || (liquidBalance + stakedBalance).toString())
        
        // DO NOT OVERRIDE hasCredentials - trust what mergeWithStoredCredentials set!
        // The merge function already correctly determined if credentials exist in localStorage
        const hasCredsFromMerge = agent.hasCredentials || false
        
        import.meta.env.DEV && console.log(`Agent ${agent.name || agent.did}: Liquid=${liquidBalance}, Staked=${stakedBalance}, Total=${totalBalance}, HasCreds=${hasCredsFromMerge}`)
        
        return {
          ...agent,
          liquidBalance,
          stakedBalance,
          totalBalance,
          balance: totalBalance, // For backwards compatibility
          // KEEP hasCredentials from merge - DO NOT OVERRIDE!
          hasCredentials: agent.hasCredentials || false,
          hasInvalidCredentials: agent.hasInvalidCredentials || false,
          client_id: agent.client_id,
          client_secret: agent.client_secret
        }
      })
      
      // §pass43d (2026-05-19) — Canonical sort: agents with locally-stored
      // credentials FIRST (so users see actionable agents at the top of the
      // AgentSwitcher dropdown), then balance descending within each bucket.
      // AgentSelectorModal already does this same sort independently — moving
      // it to the store makes the canonical order match the modal's order so
      // the dropdown picker shows consistent ranking too. Audit of all 9
      // `availableAgents` consumers confirmed only AgentSwitcher reads order
      // (all others use find-by-did / .length / .filter — order-independent).
      agentsWithBalances.sort((a, b) => {
        const aCreds = !!(a.hasCredentials && !a.hasInvalidCredentials) ? 1 : 0
        const bCreds = !!(b.hasCredentials && !b.hasInvalidCredentials) ? 1 : 0
        if (aCreds !== bCreds) return bCreds - aCreds
        return (b.totalBalance || 0) - (a.totalBalance || 0)
      })
      
      /*
       * §LAZYBAL — assigning a NEW ARRAY REFERENCE is all Vue 3 needs. The old
       * `= []` + nextTick + set was cargo-cult, and it opened a real window in
       * which the fleet was empty; if anything after the clear failed or a
       * concurrent call interleaved, the window never closed.
       */
      availableAgents.value = [...agentsWithBalances]
      import.meta.env.DEV && console.log('[Auth Store] ✅ Agents set with forced reactivity update')
      
      import.meta.env.DEV && console.log('Agents sorted by balance:', agentsWithBalances.slice(0, 10).map(a => ({
        name: a.name || a.did,
        totalBalance: a.totalBalance,
        hasCredentials: a.hasCredentials
      })))
      
      // §pass42 (2026-05-18) — Honour previously-saved activeAgentId BEFORE
      // falling back to balance-based auto-select. The setter at switchAgent()
      // writes `localStorage.activeAgentId` on every successful switch but
      // nothing read it back on init, so every refresh defaulted to the
      // highest-balance agent (SYBIL in Commander's case). Now: prefer the
      // stored selection if (a) still in the agents list and (b) has valid
      // creds; otherwise fall through to balance-based pick.
      let selectableAgent = null
      try {
        const savedDid = localStorage.getItem('activeAgentId')
        if (savedDid) {
          const candidate = agentsWithBalances.find(agent =>
            agent.did === savedDid && !agent.hasInvalidCredentials && canActAs(agent)
          )
          if (candidate) {
            selectableAgent = candidate
            import.meta.env.DEV && console.log(`Restoring saved active agent: ${candidate.name || candidate.did}`)
          }
        }
      } catch { /* localStorage may not be available; fall through */ }

      // Fallback: highest-balance agent with credentials (one that can act at all: §MCPTEST30 V0640)
      if (!selectableAgent) {
        selectableAgent = agentsWithBalances.find(agent =>
          agent.hasCredentials && !agent.hasInvalidCredentials && agent.totalBalance > 0 && agent.client_id && agent.client_secret
          && !cannotActReason(agent)
        ) || agentsWithBalances.find(agent =>
          agent.hasCredentials && !agent.hasInvalidCredentials && agent.client_id && agent.client_secret
          && !cannotActReason(agent)
        )
      }
      // §FESUITE (2026-10-10): the ONLY agent you can act as here, yours on this registry with no secret saved in this
      // browser (canActAs: it signs in through your session, §FEFRAME W3). A member whose one agent was made elsewhere
      // (another browser, the API, a phone) signed in acting as nobody and met the picker on the first page that needs
      // an agent. With several such agents the console does not choose for them: they pick once, and it remembers.
      if (!selectableAgent) {
        const actable = agentsWithBalances.filter((agent: any) => !agent.hasInvalidCredentials && canActAs(agent))
        if (actable.length === 1) selectableAgent = actable[0]
      }

      if (selectableAgent) {
        import.meta.env.DEV && console.log(`Auto-selecting agent: ${selectableAgent.name || selectableAgent.did} (Total: ${selectableAgent.totalBalance}, Liquid: ${selectableAgent.liquidBalance}, Staked: ${selectableAgent.stakedBalance})`)
        const switched = await switchAgent(selectableAgent.did)
        // §FESUITE (2026-10-04): a sign-in that failed for want of an answer (none at all, or a server error) is tried
        // again on its own; a refusal (any 4xx: 401, 403, but also 400/404/422) is an answer, and is not (2026-10-05:
        // 'other' named every status but 401/403, so a refusal that will never change was asked again every minute)
        if (!switched && canActAs(selectableAgent) && agentSignInOutage) agentRetry.schedule()
      } else if (agents.length === 0) {
        // No agents at all - redirect to onboarding
        import.meta.env.DEV && console.log('No agents found - user should create their first agent')
        const uiStore = useUIStore()
        uiStore.showInfo(
          'No Agents Found',
          'Create your first agent to get started'
        )
        // Don't auto-redirect here, let router guards handle it
      } else {
        log.warn('None of this developer\'s agents has its credentials stored in this browser.')
        // §FESUITE (2026-10-02): this said "likely created from backend testing" on EVERY load for an account whose
        // agents' credentials live elsewhere (an agent made over the API or in another browser: every admin, every
        // page of the console suite). It now says what the console knows, names the two doors, and says it once per
        // browser session.
        if (firstTimeThisSession(`agent-credentials-elsewhere:${(user.value as any)?.id ?? ''}`)) {
          useUIStore().showWarning(
            'No agent can act in this browser yet',
            'None of your agents has its credentials stored here (agents made over the API or in another browser). Your developer session works as usual. To act as an agent, import its credentials from the agent switcher (Bulk Import) or reset them in My Agents.'
          )
        }
      }
      
    } catch (err: any) {
      console.error('Failed to fetch agents:', err)
      console.error('Error details:', err.response?.data)
      availableAgents.value = []
      agentFetchFailed.value = true   // say "could not load", never "you have none"
      // §FESUITE: and read it again on its own once the registry answers, when it did not answer (none, or a server
      // error); a refusal or the console's own error would answer the same way every minute
      if (failedForWantOfAnAnswer(err)) agentRetry.schedule()
      credentialsChecked.value = true // Even on error, mark as checked
    } finally {
      agentLoading.value = false
      credentialsChecked.value = true // §FEFRAME W1: every exit marks it, so no path can leave the selector spinning
    }
  }
  
  // Helper function to fetch individual balances
  async function fetchIndividualBalances(agents: any[], balances: Record<string, any>) {
    /*
     * §LAZYBAL — HARD CAP. This is a sequential one-request-per-agent loop used
     * as the fallback when a batch fails. Unbounded, it ran ~608 times and hung
     * the whole agent list for minutes. Anything past the cap is zero-filled:
     * a missing balance is a cosmetic gap, an invisible fleet is not.
     */
    const INDIVIDUAL_CAP = 25
    if (agents.length > INDIVIDUAL_CAP) {
      log.warn(`[Auth Store] balance fallback capped at ${INDIVIDUAL_CAP} of ${agents.length}; the rest read 0 until the batch endpoint recovers`)
      for (const a of agents.slice(INDIVIDUAL_CAP)) {
        balances[a.did] = { liquid_balance: '0', staked_balance: '0', total_balance: '0' }
      }
      agents = agents.slice(0, INDIVIDUAL_CAP)
    }
    import.meta.env.DEV && console.log(`Fetching individual balances for ${agents.length} agents...`)
    
    for (const agent of agents) {
      try {
        const individualBalance = await apiClient.get(`/developers/me/agents/${encodeURIComponent(agent.did)}/balance`)
        balances[agent.did] = individualBalance.data
        import.meta.env.DEV && console.log(`Individual balance for ${agent.did}:`, individualBalance.data)
      } catch (individualError) {
        log.warn(`Could not fetch balance for ${agent.did}:`, individualError)
        balances[agent.did] = {
          liquid_balance: '0',
          staked_balance: '0',
          total_balance: '0'
        }
      }
    }
  }
  
  /**
   * Set the active agent from an already-verified token.
   *
   * Used by AddCredentialsModal after its "test before saving" verify call
   * returns a valid access_token — no need to round-trip a second time.
   */
  function setActiveAgentFromToken(agent: any, accessToken: string): void {
    agentToken.value = accessToken
    activeAgent.value = {
      ...agent,
      hasCredentials: true,
      hasInvalidCredentials: false,
    }
    import.meta.env.DEV && console.log('[Auth Store] Active agent set from verify-call token:', {
      did: agent.did,
      name: agent.name,
      tokenPreview: accessToken.slice(0, 20) + '...',
    })
  }

  /**
   * §BRIDGE R11 #12 — where does this agent actually live?
   *
   * His architectural note, and he is right: *"you dont actually need to change
   * any money path. you just trigger the endpoints thru the web address of the
   * registry. all of them have adressed subdomains."*
   *
   * Every registry serves its OWN `/api/v1/auth/agent/token` on its own public
   * host, and those hosts already answer a cross-origin preflight from another
   * frame (verified live 2026-08-19: `OPTIONS` from a frame-c origin returned
   * 200 with `access-control-allow-origin` echoing the caller and
   * `allow-credentials: true`). So a foreign agent needs NO new endpoint, NO
   * relay and NO change to any money path — it needs its own address.
   *
   * Null means "this origin", which is every agent that existed before this.
   */
  const activeAgentRegistryUrl = computed<string | null>(() => {
    const u = activeAgent.value?.registry_url
    if (!u || typeof u !== 'string') return null
    try {
      const parsed = new URL(u)
      // Same origin is not "foreign" — never rewrite a base URL for nothing.
      if (parsed.origin === window.location.origin) return null
      return parsed.origin
    } catch { return null }
  })

  /** §FEFRAME W3: how the active agent's token was minted ('owner' = from your session, no secret), for the re-mint. */
  const agentTokenVia = ref<'owner' | 'hub' | 'secret' | null>(null)

  /** True when this agent lives on THIS registry (no foreign address). */
  function isLocalRow(agent: any): boolean {
    const u = agent?.registry_url
    if (!u || typeof u !== 'string') return true
    try { return new URL(u).origin === window.location.origin } catch { return true }
  }

  /** §FEFRAME W3: can the console act as this row? An agent you own here needs no secret; any other needs one, or a
   *  developer session on its registry held by the session hub. */
  function canActAs(agent: any): boolean {
    if (!agent) return false
    // §MCPTEST30 (V0640): a row the server lists as revoked or suspended cannot act by any road (services/agentActable)
    if (cannotActReason(agent)) return false
    if (agent.owned && isLocalRow(agent) && String(agent.did || '').startsWith('did:')) return true
    return !!(agent.client_id && agent.client_secret)
  }

  /** Whether the last agent sign-in failed for want of an answer (none at all, or a server error): the store tries that
   *  again by itself, so a page that needs an agent says the registry did not answer, never "no agent can act here". */
  function agentSignInWasAnOutage(): boolean {
    return agentSignInOutage
  }

  function adoptAgentToken(agent: any, token: string, via: 'owner' | 'hub' | 'secret'): void {
    lastAgentAuthFailure.value = null
    agentCredentialsStore.clearRejected(agent.did)
    agentToken.value = token
    agentTokenVia.value = via
    activeAgent.value = agent
  }

  async function authenticateAsAgent(agent: any): Promise<boolean> {
    // §FEFRAME W3 (V0504) — acting as your own agent needs no secret. An agent the server listed as yours, on this
    // registry, gets a short token from your session (POST /developers/me/agents/{did}/session-token); a foreign
    // agent gets one through your developer session on ITS registry when the session hub holds one. The saved secret
    // is the road for everything else (and the fallback when the owner rail refuses: an agent transferred away).
    // §FESUITE (2026-10-04): each sign-in states its own reason; a reason left from an earlier one must not decide this one
    lastAgentAuthFailure.value = null
    agentSignInOutage = false
    if (agent?.owned && isLocalRow(agent) && String(agent.did || '').startsWith('did:')) {
      try {
        const r = await apiClient.post(`/developers/me/agents/${encodeURIComponent(agent.did)}/session-token`)
        if (r?.data?.access_token) {
          adoptAgentToken(agent, r.data.access_token, 'owner')
          return true
        }
      } catch (e: any) {
        const st = e?.response?.status
        if (st !== 404 && st !== 403) log.warn('owner sign-in failed; trying a saved secret if there is one', st)
        // §FESUITE: no answer (or a server error) is the outage the store's second try waits out; an agent you own
        // with no saved secret has no other road, and with no reason recorded nothing tried again. A 401/403/404 here
        // is an answer about the session or the ownership, never about a saved secret, so it records nothing.
        if (failedForWantOfAnAnswer(e)) {
          lastAgentAuthFailure.value = classifyAgentMintFailure(e)
          agentSignInOutage = true
        }
      }
    } else if (!isLocalRow(agent) && String(agent.did || '').startsWith('did:')) {
      try {
        const { useSessionHub } = await import('./sessions')
        const { currentFrameManifest } = await import('@/composables/useFrameManifest')
        const { entryByOrigin } = await import('@/services/frameManifest')
        const m = currentFrameManifest()
        const e = m ? entryByOrigin(m, new URL(agent.registry_url).origin) : null
        const hub = useSessionHub()
        if (e && hub.isConnected(e.key)) {
          const tok = await hub.ensureAgentToken(e.key, agent.did)
          if (tok) {
            adoptAgentToken(agent, tok, 'hub')
            return true
          }
        }
      } catch { /* no hub road: the saved secret below */ }
    }
    try {
      // Make sure we have the agent's credentials
      if (!agent.client_id || !agent.client_secret) {
        console.error('Agent missing credentials:', agent.did)
        return false
      }
      
      import.meta.env.DEV && console.log('Authenticating as agent:', {
        did: agent.did,
        client_id: agent.client_id,
        name: agent.name
      })
      
      // A foreign agent authenticates at ITS OWN registry, by its own address.
      let foreignOrigin: string | null = null
      try {
        if (agent.registry_url) {
          const u = new URL(agent.registry_url)
          if (u.origin !== window.location.origin) foreignOrigin = u.origin
        }
      } catch { foreignOrigin = null }

      // §FEFRAME W1: the bare client (services/api/peerDirect.ts). Through apiClient the interceptor attached THIS
      // registry's developer token, so a foreign agent's sign-in handed it to another registry; a wrong local secret
      // also triggered a developer refresh and a retry. The request carries the agent's client credentials and nothing else.
      const response = { data: await mintAgentTokenAt(foreignOrigin, agent.client_id, agent.client_secret) }
      
      import.meta.env.DEV && console.log('Agent auth response:', {
        has_token: !!response.data.access_token,
        token_type: response.data.token_type
      })
      
      if (response.data.access_token) {
        adoptAgentToken(agent, response.data.access_token, 'secret')
        agentCredentialsStore.claim([agent.did])
        // §TOURBLOG-3: switcher rows carry did/name/creds but no flare fields, so the
        // header chip fell back to initials even for agents wearing an encirclement
        // (a sovereign agent's vanity was invisible the moment you flew it). Enrich
        // from the public flare endpoint, best-effort, off the auth path.
        // Credential-seeded rows store the CLIENT ID in `did` — the real DID rides
        // the agent JWT's `sub` claim, so decode that first and fall back to the row.
        let flareDid: string | null = agent.did?.startsWith?.('did:') ? agent.did : null
        try {
          const payload = JSON.parse(atob(response.data.access_token.split('.')[1] || ''))
          if (typeof payload?.sub === 'string' && payload.sub.startsWith('did:')) flareDid = payload.sub
        } catch { /* opaque token — row DID (if any) stays */ }
        if (flareDid) {
          void apiClient.get(`/fiat/flare/agent/${encodeURIComponent(flareDid)}`)
            .then(r => {
              if (r?.data && activeAgent.value?.did === agent.did) {
                Object.assign(agent, {
                  flare_tier: r.data.flare_tier ?? agent.flare_tier ?? null,
                  flare_granted_at: r.data.flare_granted_at ?? agent.flare_granted_at ?? null,
                })
              }
            })
            .catch(() => { /* no flare or endpoint dark — initials are the honest fallback */ })
        }
        import.meta.env.DEV && console.log('Agent token stored successfully:', {
          tokenPreview: agentToken.value?.substring(0, 20) + '...',
          agentDid: agent.did
        })
        return true
      }
      
      return false
    } catch (err: any) {
      lastAgentAuthFailure.value = classifyAgentMintFailure(err)
      agentSignInOutage = failedForWantOfAnAnswer(err)   // the secret's own answer decides, over the owner road's
      console.error('Agent authentication failed:', {
        failure: lastAgentAuthFailure.value,
        response: err.response?.data,
        status: err.response?.status
      })
      return false
    }
  }
  
  let _freshPromise: Promise<boolean> | null = null
  /** §FEFRAME W3: re-mint the active agent's token when it lapses within a minute, on the road it was minted on (an
   *  owner token lives OWNER_SESSION_TOKEN_MINUTES, 30 by default). The request interceptor asks before every agent
   *  request; concurrent asks share one mint. */
  async function ensureFreshAgentToken(): Promise<void> {
    if (!activeAgent.value || !agentToken.value || !needsMint(agentToken.value)) return
    if (!_freshPromise) _freshPromise = authenticateAsAgent(activeAgent.value).finally(() => { _freshPromise = null })
    await _freshPromise
  }

  async function switchAgent(agentId: string) {
    const agent = availableAgents.value.find(a => a.did === agentId)
    if (!agent) {
      console.error('Agent not found:', agentId)
      return false
    }
    
    // §MCPTEST30 (V0640): a revoked or suspended agent is said as such, never as one missing its credentials
    const cannot = cannotActReason(agent)
    if (cannot) {
      if (showAgentSelector.value) {
        useUIStore().showError(cannot === 'revoked' ? 'Agent deleted' : 'Agent suspended', cannotActSentence(agent, cannot))
      }
      return false
    }
    // Check the console can act as this agent (§FEFRAME W3: an agent you own here needs no saved secret)
    if (!canActAs(agent)) {
      console.error('Agent missing credentials, cannot authenticate:', agent.did)
      // Don't show error toast for auto-selection attempts
      if (showAgentSelector.value) {
        const uiStore = useUIStore()
        uiStore.showError(
          'Missing Agent Credentials',
          `Agent ${agent.name || agent.did} lacks authentication credentials. This agent may have been created from backend testing.`
        )
      }
      return false
    }
    
    agentLoading.value = true
    const uiStore = useUIStore()
    
    try {
      // Authenticate as the agent
      const success = await authenticateAsAgent(agent)
      
      if (success) {
        activeAgent.value = agent
        localStorage.setItem('activeAgentId', agent.did)
        agentRetry.cancel()
        
        // Show notification
        uiStore.showSuccess(
          'Agent Activated',
          `Now acting as ${agent.name || agent.did}`
        )
        
        // Close selector if open
        showAgentSelector.value = false
        
        return true
      } else {
        const why = lastAgentAuthFailure.value
        const label = agent.name || agent.did
        if (why === 'rejected') {
          // the ONLY answer that says the secret is wrong: remember it, so no page load retries it on its own
          agent.hasInvalidCredentials = true
          agentCredentialsStore.markRejected(agent.did)
          try { if (localStorage.getItem('activeAgentId') === agent.did) localStorage.removeItem('activeAgentId') } catch { /* blocked */ }
          uiStore.showError('Invalid Agent Credentials',
            `The registry refused the saved secret for ${label}. Re-enter it, or remove it from this browser.`)
        } else if (why === 'unreachable') {
          // one toast for the first failure; the store's own quiet tries say nothing until one succeeds
          if (!quietAgentRetry.value) uiStore.showError('Agent registry not reachable',
            `This console cannot reach ${label}'s registry (it does not accept this console yet, or it is offline). Nothing about the saved secret changed.`)
        } else if (why === 'suspended') {
          uiStore.showError('Agent suspended', `${label} is suspended on its registry; its owner can see the enforcement status there.`)
        } else {
          if (!quietAgentRetry.value) uiStore.showError('Agent sign-in failed', `Could not sign in as ${label}. Try again in a moment.`)
        }
        return false
      }
    } catch (err) {
      console.error('Failed to switch agent:', err)
      if (!quietAgentRetry.value) uiStore.showError('Agent Switch Failed', 'Could not switch to selected agent')
      return false
    } finally {
      agentLoading.value = false
    }
  }
  
  /** §FEFRAME W1 — remove one saved credential from this browser (only the logged-in developer's or an unclaimed one). */
  function forgetCredential(did: string) {
    agentCredentialsStore.removeCredentials(did)
    if (activeAgent.value?.did === did) clearActiveAgent()
    availableAgents.value = availableAgents.value.map((a: any) => a.did === did
      ? { ...a, client_id: undefined, client_secret: undefined, hasCredentials: false, hasInvalidCredentials: false }
      : a)
  }

  /** §FEFRAME W1 — remove every saved credential the logged-in developer can see from this browser. */
  function forgetAllCredentials() {
    agentCredentialsStore.clearAll()
    clearActiveAgent()
    availableAgents.value = availableAgents.value.map((a: any) => ({
      ...a, client_id: undefined, client_secret: undefined, hasCredentials: false, hasInvalidCredentials: false,
    }))
  }

  function clearActiveAgent() {
    agentRetry.cancel()   // the person chose no agent: no try may choose one for them
    activeAgent.value = null
    agentToken.value = null
    agentTokenVia.value = null
    localStorage.removeItem('activeAgentId')
  }
  
  function isAgentRequired(path: string): boolean {
    const agentPaths = ['/senate', '/galactic-map', '/agent-builder']
    return agentPaths.some(p => path.includes(p))
  }

  // Initialize on store creation
  initializeAuth()

  // PUSH LOGIN: the person may stop waiting (the login page's "Stop waiting", or leaving the page): the pause between
  // two polls ends at once then, so the form is back without a two-second lag, and nothing signs in afterwards
  let pushWaitStopped = false
  let pushWake: (() => void) | null = null
  function pushPause(): Promise<void> {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(() => { pushWake = null; resolve() }, 2000)
      pushWake = () => { clearTimeout(timer); pushWake = null; resolve() }
    })
  }
  function stopWaitingForPhone(): void {
    pushWaitStopped = true
    pushWake?.()
  }
  /** What this device says when the wait ends without a sign-in: what happened and what to do next. It said the bare
   *  state ("Sign-in denied", "Sign-in expired", "Approval expired"), §FESUITE lifecycle 84. */
  function pushWaitEnded(kind: string): string {
    if (kind === 'denied') return 'Your phone denied this sign-in.'
    if (kind === 'expired') return 'This sign-in was not approved in time. Sign in again to send a new request to your phone.'
    if (kind === 'gone') return 'This sign-in request is no longer waiting. Sign in again to send a new one.'
    return `Sign-in ${kind}`
  }

  /** PUSH LOGIN: verify on THIS device if it can, otherwise wait for the phone. */
  async function completePushLogin(): Promise<boolean> {
    if (!pushApprovalId.value) return false
    const { pushLoginApi } = await import('@/services/api/pushLogin')
    const id = pushApprovalId.value

    // If this very device holds the enrolled credential, prompt for the fingerprint HERE.
    // Pushing a notification to the device you are already holding — and which cannot open it
    // because it is not logged in yet — is a deadlock, not a security control.
    try {
      const { useDeviceSigner } = await import('@/composables/useDeviceSigner')
      const signer = useDeviceSigner()
      const { pocketCredentialId } = await import('@/composables/usePocketLock')
      const localCred = pocketCredentialId()
      if (localCred && signer.supported && await signer.platformAvailable()) {
        const ch = await pushLoginApi.challenge(id)
        // THIS device's credential. Handing it the account's first credential asked this browser
        // to sign with a key that lives in another phone's keystore.
        const a = await signer.sign(ch.challenge_hash, localCred)
        await pushLoginApi.approveDirect(id, a)
        const tok = await pushLoginApi.token(id)
        await processSuccessfulLogin({ access_token: tok.access_token, token_type: tok.token_type, refresh_token: tok.refresh_token })
        // The human just proved presence to get in. Demanding the lock's fingerprint again in the
        // same breath is two prompts for one intent — mark the session satisfied.
        const { markPocketUnlocked } = await import('@/composables/usePocketLock')
        markPocketUnlocked()
        pushApprovalId.value = ''
        return true
      }
    } catch (e) {
      // No credential on this device, or the human declined here — fall through to the phone.
      import.meta.env.DEV && console.log('local biometric approval unavailable:', e)
    }
    pushWaitStopped = false
    const deadline = Date.now() + (pushApprovalExpiresIn.value + 15) * 1000
    while (Date.now() < deadline) {
      if (pushWaitStopped) { pushApprovalId.value = ''; return false }
      // A single failed poll must not end the wait. Two minutes of polling across a phone network
      // will hit a blip; letting it throw stranded the browser on the login screen with no message
      // while the human was still looking at the fingerprint prompt.
      let status: string
      try {
        ({ status } = await pushLoginApi.status(id))
      } catch (e: any) {
        if (e?.response?.status === 404) { error.value = pushWaitEnded('gone'); pushApprovalId.value = ''; return false }
        await pushPause()
        continue
      }
      if (pushWaitStopped) { pushApprovalId.value = ''; return false }
      if (status === 'approved') {
        const tok = await pushLoginApi.token(id)
        await processSuccessfulLogin({ access_token: tok.access_token, token_type: tok.token_type, refresh_token: tok.refresh_token })
        pushApprovalId.value = ''
        return true
      }
      if (status !== 'pending') { error.value = pushWaitEnded(status); pushApprovalId.value = ''; return false }
      await pushPause()
    }
    if (pushWaitStopped) { pushApprovalId.value = ''; return false }
    error.value = pushWaitEnded('expired')
    pushApprovalId.value = ''
    return false
  }

  /**
   * Re-read the developer profile from /developers/me.
   * Used right after a forced password change: the server clears the flag in the same
   * request, and without re-hydrating, the guard would bounce the user straight back
   * into the change screen it just let them out of.
   * Answers whether the profile was READ (quick onboarding, 2026-10-09): on false the cached user is what it was, so a
   * caller must not present it as the registry's fresh answer ("could not verify" is not "still unverified").
   */
  async function refreshProfile(): Promise<boolean> {
    try {
      const verified = await authService.verify()
      if (verified?.user) { user.value = verified.user; return true }
      return false
    } catch { return false /* leave the cached user; initializeAuth will hydrate later */ }
  }

  return {
    // State
    user,
    token,
    loading,
    pushApprovalId,
    pushApprovalExpiresIn,
    completePushLogin,
    stopWaitingForPhone,
    error,
    verificationRequired,
    sessionExpiry,
    rememberMe,
    
    // Getters
    isAuthenticated,
    userRole,
    isAdmin,
    isAgent,
    isDeveloper,
    sessionInfo,
    isSessionExpired,
    isFederationOperator,
    mustChangePassword,
    federationOperatorStatus,

    // Actions
    hydrateForeignFlares,
    login,
    logout,
    endLocalSession,
    register,
    initializeAuth,
    refreshSession,
    requestPasswordReset,
    resetPassword,
    checkAuth,
    clearError,
    processSuccessfulLogin,
    refreshProfile,
    
    // Agent context
    activeAgent,
    activeAgentRegistryUrl,
    agentTokenVia,
    canActAs,
    agentSignInWasAnOutage,
    ensureFreshAgentToken,
    agentToken,
    availableAgents,
    agentLoading,
    agentFetchFailed,
    showAgentSelector,
    credentialsChecked,
    lastAgentAuthFailure,
    
    // Agent actions
    fetchAvailableAgents,
    authSettling,
    searchAgents,
    fetchIndividualBalances,
    authenticateAsAgent,
    setActiveAgentFromToken,
    switchAgent,
    clearActiveAgent,
    forgetCredential,
    forgetAllCredentials,
    isAgentRequired
  }
})
