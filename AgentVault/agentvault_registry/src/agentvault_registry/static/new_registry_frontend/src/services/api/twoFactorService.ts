import { apiClient } from './client'

// TypeScript interfaces for 2FA
export interface TwoFactorSetupRequest {
  password: string
}

export interface TwoFactorSetupResponse {
  status: string
  qr_code: string
  secret: string
  backup_codes: string[]
}

export interface TwoFactorVerifyRequest {
  code: string
}

export interface TwoFactorDisableRequest {
  password: string
  /** A current authenticator code or an unused backup code: the server requires one. */
  code: string
}

export interface TwoFactorValidateRequest {
  partial_token: string
  code: string
}

export interface TwoFactorValidateResponse {
  access_token: string
  token_type: string
  /** §FEFRAME W1: the server returns one since V0502 (the same session a password login gets). */
  refresh_token?: string
  user?: any
  developer?: any  // Backend returns 'developer' not 'user'
}

export interface TwoFactorRecoverRequest {
  partial_token: string
  backup_code: string
}

export interface TwoFactorBackupCodesRequest {
  password: string
}

export interface TwoFactorBackupCodesResponse {
  backup_codes: string[]
}

export interface TwoFactorStatusResponse {
  enabled: boolean
  verified_at?: string
}

export interface BaseResponse {
  success: boolean
  message?: string
  error?: string
}

/**
 * Two-Factor Authentication Service
 * Handles all 2FA-related API calls
 */
class TwoFactorService {
  private basePath = '/auth/2fa'

  /**
   * Setup 2FA for the current user
   * Returns QR code, secret, and backup codes
   */
  async setup(password: string): Promise<TwoFactorSetupResponse> {
    try {
      const { data } = await apiClient.post<TwoFactorSetupResponse>(
        `${this.basePath}/setup`,
        { password }
      )
      
      // Debug: Log the raw response from backend
      import.meta.env.DEV && console.log('Raw 2FA setup response from backend:', data)
      import.meta.env.DEV && console.log('QR Code first 200 chars:', data.qr_code?.substring(0, 200))
      import.meta.env.DEV && console.log('Secret:', data.secret)
      import.meta.env.DEV && console.log('Backup codes count:', data.backup_codes?.length)
      
      return data
    } catch (error: any) {
      console.error('2FA setup error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to setup 2FA')
    }
  }

  /**
   * Verify 2FA code to complete setup
   */
  async verify(code: string): Promise<BaseResponse> {
    try {
      const { data } = await apiClient.post<BaseResponse>(
        `${this.basePath}/verify`,
        { code }
      )
      return data
    } catch (error: any) {
      console.error('2FA verify error:', error)
      throw new Error(error.response?.data?.detail || 'Invalid verification code')
    }
  }

  /**
   * Disable 2FA for the current user
   */
  async disable(password: string, code: string): Promise<BaseResponse> {
    try {
      const { data } = await apiClient.post<BaseResponse>(
        `${this.basePath}/disable`,
        { password, code } as TwoFactorDisableRequest
      )
      return data
    } catch (error: any) {
      console.error('2FA disable error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to disable 2FA')
    }
  }

  /**
   * Validate 2FA code during login
   * Used when user has 2FA enabled and needs to provide code
   */
  async validate(partialToken: string, code: string): Promise<TwoFactorValidateResponse> {
    try {
      const { data } = await apiClient.post<TwoFactorValidateResponse>(
        `${this.basePath}/validate`,
        { 
          partial_token: partialToken,
          code 
        }
      )
      return data
    } catch (error: any) {
      console.error('2FA validate error:', error)
      throw new Error(error.response?.data?.detail || 'Invalid 2FA code')
    }
  }

  /**
   * Recover account using backup code
   * Used when user doesn't have access to authenticator app
   */
  async recover(partialToken: string, backupCode: string): Promise<TwoFactorValidateResponse> {
    try {
      const { data } = await apiClient.post<TwoFactorValidateResponse>(
        `${this.basePath}/recover`,
        { 
          partial_token: partialToken,
          backup_code: backupCode 
        }
      )
      return data
    } catch (error: any) {
      console.error('2FA recover error:', error)
      throw new Error(error.response?.data?.detail || 'Invalid backup code')
    }
  }

  /**
   * Regenerate backup codes
   * Invalidates old codes and generates new ones
   */
  async regenerateBackupCodes(password: string): Promise<TwoFactorBackupCodesResponse> {
    try {
      const { data } = await apiClient.post<TwoFactorBackupCodesResponse>(
        `${this.basePath}/backup-codes`,
        { password }
      )
      return data
    } catch (error: any) {
      console.error('2FA regenerate backup codes error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to regenerate backup codes')
    }
  }

  /**
   * Get 2FA status for current user
   */
  async getStatus(): Promise<TwoFactorStatusResponse> {
    try {
      const { data } = await apiClient.get<TwoFactorStatusResponse>(
        `${this.basePath}/status`
      )
      return data
    } catch (error: any) {
      // §FESUITE (2026-10-05): every failure answered { enabled: false }, so Settings drew "Disabled" and the enable
      // button over a status it never read (a 502, a timeout, no answer). Only a registry without the endpoint (404)
      // answers "no two-factor here"; any other failure is thrown, so the store says the read failed (or keeps the
      // status it read before).
      if (error?.response?.status === 404) return { enabled: false }
      throw error
    }
  }
}

// Export singleton instance
export const twoFactorService = new TwoFactorService()
