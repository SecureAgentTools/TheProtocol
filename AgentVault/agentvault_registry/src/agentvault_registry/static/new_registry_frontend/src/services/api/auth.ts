import { apiClient } from './client'
import type { User } from '@/types'

interface LoginRequest {
  email: string
  password: string
}

interface LoginResponse {
  access_token?: string
  token_type?: string
  user?: User
  refresh_token?: string // Optional - backend may not return it
  requires_2fa?: boolean // 2FA required flag
  partial_token?: string // Partial token for 2FA validation
  message?: string // Optional message from backend
}

interface VerifyResponse {
  valid: boolean
  user: User
}

interface RefreshTokenRequest {
  refresh_token: string
}

interface RefreshTokenResponse {
  access_token: string
  refresh_token?: string
  token_type: string
}

interface PasswordResetRequest {
  email: string
}

interface PasswordResetConfirm {
  token: string
  password: string
}

interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

interface TwoFactorSetup {
  qr_code: string
  secret: string
}

export const authApi = {
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const formData = new FormData()
    formData.append('username', credentials.email)
    formData.append('password', credentials.password)
    
    try {
      // Tell the server whether THIS browser can raise its own biometric prompt. If it can, the
      // server skips the push — notifying the very device that is about to approve locally just
      // produced alerts for approvals that were already consumed by the time they were tapped.
      let localCapable = '0'
      try {
        const { pocketCredentialId } = await import('@/composables/usePocketLock')
        localCapable = pocketCredentialId() ? '1' : '0'
      } catch { /* composable unavailable — treat as not capable */ }

      const { data } = await apiClient.post<LoginResponse>('/auth/login', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'X-Push-Login-Local': localCapable,
        }
      })
      
      // Log the response structure for debugging
      import.meta.env.DEV && console.log('Raw login response:', data)
      
      return data
    } catch (error) {
      // §FESUITE: a refused credential (a 4xx) is the person's mistake, already shown to them; only the unexpected is an error
      const status = (error as any)?.response?.status
      if (!status || status >= 500) console.error('Login API error:', error)
      throw error
    }
  },

  async logout(): Promise<void> {
    await apiClient.post('/auth/logout')
  },

  async verify(): Promise<VerifyResponse> {
    // The backend doesn't have a /auth/verify endpoint for session verification
    // Instead, we can use /developers/me to verify the session
    try {
      const { data } = await apiClient.get<any>('/developers/me')
      
      // Map is_admin from backend to role for frontend
      let role: 'admin' | 'developer' | 'agent' | 'user' = 'developer'
      if (data.is_admin === true) {
        role = 'admin'
      }
      
      // Log the mapping for debugging
      import.meta.env.DEV && console.log('Backend /developers/me response:', {
        id: data.id,
        email: data.email,
        is_admin: data.is_admin,
        mapped_role: role
      })
      
      // Transform developer data to match VerifyResponse format
      // RBAC audit fix (2026-05-08): forward the 5 granular admin sub-flags
      // so usePermissions().can() works for sub-flag-only admins. Without
      // this, the verify() handler synthesised a user object with only
      // `is_admin` — sub-flags came back from /developers/me but were
      // silently dropped here, making the entire granular RBAC layer
      // non-functional on the UI.
      return {
        valid: true,
        user: {
          id: data.id.toString(),
          email: data.email,
          name: data.name || data.email.split('@')[0],
          role: role,  // Use the mapped role
          is_admin: data.is_admin,  // Include the is_admin field
          admin_treasury:    Boolean(data.admin_treasury),
          admin_support:     Boolean(data.admin_support),
          admin_enforcement: Boolean(data.admin_enforcement),
          admin_federation:  Boolean(data.admin_federation),
          admin_platform:    Boolean(data.admin_platform),
          // §EXCISION-10 — the SAME class of bug the comment above describes: this
          // mapper is a WHITELIST, so any field it does not name is silently dropped.
          // `must_change_password` came back from /developers/me and vanished here,
          // leaving the router guard permanently false and the forced-change screen
          // unreachable. An E2E with a negative control caught it; the marker was in
          // the bundle and the backend was correct, so nothing else would have.
          must_change_password: Boolean(data.must_change_password),
          // §LEGALKIT (Terms § 10.2): the console asks for renewed acceptance from these three.
          tos_accepted_version: data.tos_accepted_version ?? null,
          tos_current_version: data.tos_current_version ?? null,
          tos_reconsent_required: Boolean(data.tos_reconsent_required),
          reconsent_documents: Array.isArray(data.reconsent_documents) ? data.reconsent_documents.filter((d: unknown) => typeof d === 'string') : [],
          is_active: data.is_verified || true,
          // Quick onboarding (2026-10-09): whether the email is confirmed, as the registry said it (it refuses a
          // bootstrap token, so an agent, to a developer who has not). Absent on an older registry: unknown, not false.
          is_verified: typeof data.is_verified === 'boolean' ? data.is_verified : undefined,
          created_at: data.created_at || new Date().toISOString(),
          is_federation_operator: data.is_federation_operator || false,
          federation_operator_status: data.federation_operator_status || null,
          // PB-1 backer flare cosmetic (2026-05-09) — null until first fiat purchase.
          flare_tier: data.flare_tier || null,
          flare_granted_at: data.flare_granted_at || null,
          // Hardening: unique id + customization (null until buyer customizes).
          flare_id: data.flare_id || null,
          flare_display_name: data.flare_display_name || null,
          flare_tagline: data.flare_tagline || null,
          flare_logo_url: data.flare_logo_url || null,
          flare_link_url: data.flare_link_url || null,
          flare_cause: data.flare_cause || null,
          flare_accent_color: data.flare_accent_color || null,
          // 2026-05-11 §12 — dual-slot flare display selection (corner +
          // encirclement). DashboardHeader reads these to compose the avatar.
          selected_corner_flare: data.selected_corner_flare || null,
          selected_encirclement_flare: data.selected_encirclement_flare || null,
          // 2026-05-12 §14 — encirclement aesthetic variant. Only meaningful
          // when wearing an encirclement-class flare (today: shadow_chancellor).
          // Default 'sauron' on grant; user can switch via FlareManager.
          flare_encirclement_variant: data.flare_encirclement_variant || null,
          // 2026-05-13 §28 — broken-machine OVERLAY axis (orthogonal to variant).
          // Without this line, the sidebar/header avatars miss the overlay
          // because verify() shapes the user object before storage and drops
          // any unlisted field.
          flare_encirclement_overlay: data.flare_encirclement_overlay || null,
          // 2026-05-13 §20 — admin corner badge variant override.
          flare_corner_variant: data.flare_corner_variant || null,
          // 2026-05-12 §15 — celebration ack timestamp. NULL +
          // flare_tier='shadow_chancellor' triggers the upgrade modal once.
          flare_celebration_seen_at: data.flare_celebration_seen_at || null,
          // W2 (2026-05-09) — GDPR Art. 17 deletion state. Forward all 3
          // fields so the Settings → Danger Zone + DashboardHeader banner
          // can render the active vs. pending-deletion countdown.
          deletion_status: data.deletion_status || null,
          deletion_requested_at: data.deletion_requested_at || null,
          anonymized_at: data.anonymized_at || null,
        }
      }
    } catch (error: any) {
      // §FESUITE: only a REFUSAL (401/403) says the session is not valid. A 5xx, a timeout or no network says nothing
      // about the session ("could not verify") and is thrown, so a caller keeps what it has: before, every failure read
      // as "invalid", and a page load during a registry restart or at its database's connection ceiling (measured on
      // sbx-alpha, 2026-10-01) wrote null over the stored user and ended the session.
      const status = error?.response?.status
      if (status === 401 || status === 403) {
        return {
          valid: false,
          user: null as any
        }
      }
      throw error
    }
  },

  async register(userData: {
    email: string
    password: string
    name?: string
    invite_code?: string
  }): Promise<User> {
    const { data } = await apiClient.post<User>('/auth/register', userData)
    return data
  },

  async refreshToken(refreshToken: string): Promise<RefreshTokenResponse> {
    const { data } = await apiClient.post<RefreshTokenResponse>('/auth/refresh', {
      refresh_token: refreshToken
    })
    return data
  },

  async requestPasswordReset(email: string): Promise<void> {
    await apiClient.post('/auth/forgot-password', { email })
  },

  /** The registry's answer is its own sentence: it also answers 200 when the account is already verified, or when a
   *  cooldown sent nothing (quick onboarding reads it rather than saying "Sent" over any 200). */
  async resendVerification(email: string): Promise<{ message?: string }> {
    const { data } = await apiClient.post('/auth/resend-verification', { email })
    return data && typeof data === 'object' ? (data as { message?: string }) : {}
  },

  async resetPassword(token: string, password: string): Promise<void> {
    await apiClient.post('/auth/reset-password', {
      token,
      new_password: password
    })
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await apiClient.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword
    })
  },

  async enableTwoFactor(): Promise<TwoFactorSetup> {
    const { data } = await apiClient.post<TwoFactorSetup>('/auth/2fa/setup')
    return data
  },

  async verifyTwoFactor(code: string): Promise<void> {
    await apiClient.post('/auth/2fa/verify', { code })
  },

  async disableTwoFactor(code: string): Promise<void> {
    await apiClient.post('/auth/2fa/disable', { code })
  }
}
