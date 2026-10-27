import { appLocale } from '@/services/appLocale'
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { twoFactorService, type TwoFactorSetupResponse, type TwoFactorStatusResponse } from '@/services/api/twoFactorService'
import { useAuthStore } from './auth'
import { useUIStore } from './ui'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('twoFactor')

export const useTwoFactorStore = defineStore('twoFactor', () => {
  // State
  const isEnabled = ref(false)
  const verifiedAt = ref<string | null>(null)
  const isSettingUp = ref(false)
  const isVerifying = ref(false)
  const isDisabling = ref(false)
  const isCheckingStatus = ref(false)
  // §FESUITE (2026-10-05): whether the status was read. A failed read set isEnabled to false, so Settings drew "Disabled"
  // and "Enable Two-Factor Authentication" over an account whose 2FA may be on; a failed read now changes nothing it did
  // not read, and the panel says the status could not be read (a failed refresh keeps the last answer).
  const statusRead = ref<'idle' | 'loading' | 'ok' | 'failed'>('idle')
  
  // Setup data temporarily stored during setup process
  const setupData = ref<{
    qrCode: string
    secret: string
    /** §DISCREFINE — otpauth:// tap-to-add link; a phone cannot scan its own screen. */
    otpauthUri?: string
    backupCodes: string[]
  } | null>(null)
  
  // Partial token for 2FA validation during login (not used currently)
  const partialToken = ref<string | null>(null)
  
  // Developer ID for 2FA validation during login
  const developerId = ref<number | null>(null)
  
  // Computed
  const needsTwoFactorAuth = computed(() => developerId.value !== null || partialToken.value !== null)
  
  // Actions
  
  /**
   * Check 2FA status for current user
   */
  async function checkStatus() {
    isCheckingStatus.value = true
    if (statusRead.value !== 'ok') statusRead.value = 'loading'
    try {
      const response = await twoFactorService.getStatus()
      isEnabled.value = response.enabled
      verifiedAt.value = response.verified_at || null
      statusRead.value = 'ok'
      return response
    } catch (error) {
      log.warn('Failed to check 2FA status:', error)
      if (statusRead.value !== 'ok') statusRead.value = 'failed'
    } finally {
      isCheckingStatus.value = false
    }
  }
  
  /**
   * Start 2FA setup process
   */
  async function startSetup(password: string) {
    const uiStore = useUIStore()
    isSettingUp.value = true
    setupData.value = null
    
    try {
      const response = await twoFactorService.setup(password)
      
      // Store setup data temporarily
      setupData.value = {
        qrCode: response.qr_code,
        secret: response.secret,
        otpauthUri: (response as any).otpauth_uri || '',
        backupCodes: response.backup_codes
      }
      
      return { 
        success: true, 
        data: setupData.value 
      }
    } catch (error: any) {
      uiStore.showError('Setup Failed', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    } finally {
      isSettingUp.value = false
    }
  }
  
  /**
   * Complete 2FA setup by verifying code
   */
  async function completeSetup(code: string) {
    const uiStore = useUIStore()
    isVerifying.value = true
    
    try {
      await twoFactorService.verify(code)
      
      // Update status
      isEnabled.value = true
      verifiedAt.value = new Date().toISOString()
      statusRead.value = 'ok'
      
      uiStore.showSuccess('2FA Enabled', 'Two-factor authentication has been successfully enabled')
      
      return { 
        success: true,
        backupCodes: setupData.value?.backupCodes || []
      }
    } catch (error: any) {
      uiStore.showError('Verification Failed', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    } finally {
      isVerifying.value = false
    }
  }
  
  /**
   * Disable 2FA
   */
  async function disable(password: string, code: string) {
    const uiStore = useUIStore()
    isDisabling.value = true
    
    try {
      await twoFactorService.disable(password, code)
      
      // Update status
      isEnabled.value = false
      verifiedAt.value = null
      setupData.value = null
      statusRead.value = 'ok'
      
      uiStore.showSuccess('2FA Disabled', 'Two-factor authentication has been disabled')
      
      return { success: true }
    } catch (error: any) {
      uiStore.showError('Disable Failed', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    } finally {
      isDisabling.value = false
    }
  }
  
  /**
   * Validate 2FA code during login
   */
  async function validateCode(code: string) {
    const authStore = useAuthStore()
    const uiStore = useUIStore()
    
    // Check for partial token first (if backend sends it)
    // Otherwise, we need to handle differently
    if (!partialToken.value && !developerId.value) {
      throw new Error('No 2FA session available')
    }
    
    try {
      // For now, use partial token if available
      // TODO: Backend needs to properly return partial_token
      const response = await twoFactorService.validate(partialToken.value || 'temp-token', code)
      
      // Clear session data
      partialToken.value = null
      developerId.value = null
      
      // Set the access token in auth store
      if (response.access_token) {
        // Process the successful login with the full token
        // Backend returns 'developer' not 'user', so map it
        let user = response.user || response.developer
        
        // Transform developer data to user format if needed
        if (user && !user.role) {
          // Admin role from backend only
          // email-based admin removed
          user = {
            ...user,
            role: user.is_admin ? 'admin' : 'developer',
            is_active: true
          }
        }
        
        import.meta.env.DEV && console.log('2FA validateCode - Processed user data:', user)
        
        await authStore.processSuccessfulLogin({
          access_token: response.access_token,
          token_type: response.token_type || 'bearer',
          // §FEFRAME W1: without it a 2FA session could not refresh and ended hard at the access token's expiry
          refresh_token: (response as any).refresh_token,
          user: user
        })  // rememberMe flag is already set in auth store from initial login
      }
      
      return { success: true }
    } catch (error: any) {
      uiStore.showError('Invalid Code', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    }
  }
  
  /**
   * Recover using backup code
   */
  async function recoverWithBackupCode(backupCode: string) {
    const authStore = useAuthStore()
    const uiStore = useUIStore()
    
    if (!partialToken.value) {
      throw new Error('No partial token available')
    }
    
    try {
      const response = await twoFactorService.recover(partialToken.value, backupCode)
      
      // Clear partial token
      partialToken.value = null
      
      // Set the access token in auth store
      if (response.access_token) {
        // Backend returns 'developer' not 'user', so map it
        let user = response.user || response.developer
        
        // Transform developer data to user format if needed
        if (user && !user.role) {
          // Admin role from backend only
          // email-based admin removed
          user = {
            ...user,
            role: user.is_admin ? 'admin' : 'developer',
            is_active: true
          }
        }
        
        import.meta.env.DEV && console.log('2FA recoverWithBackupCode - Processed user data:', user)
        
        await authStore.processSuccessfulLogin({
          access_token: response.access_token,
          token_type: response.token_type || 'bearer',
          // §FEFRAME W1: without it a 2FA session could not refresh and ended hard at the access token's expiry
          refresh_token: (response as any).refresh_token,
          user: user
        })
      }
      
      uiStore.showSuccess('Access Granted', 'Successfully logged in with backup code')
      
      return { success: true }
    } catch (error: any) {
      uiStore.showError('Invalid Backup Code', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    }
  }
  
  /**
   * Regenerate backup codes
   */
  async function regenerateBackupCodes(password: string) {
    const uiStore = useUIStore()
    
    try {
      const response = await twoFactorService.regenerateBackupCodes(password)
      
      uiStore.showSuccess('Codes Regenerated', 'New backup codes have been generated')
      
      return { 
        success: true, 
        backupCodes: response.backup_codes 
      }
    } catch (error: any) {
      uiStore.showError('Regeneration Failed', error.message)
      return { 
        success: false, 
        error: error.message 
      }
    }
  }
  
  /**
   * Set developer ID when 2FA is required during login
   */
  function setDeveloperId(id: number) {
    developerId.value = id
  }
  
  /**
   * Set partial token when 2FA is required during login
   */
  function setPartialToken(token: string) {
    partialToken.value = token
  }
  
  /**
   * Clear partial token
   */
  function clearPartialToken() {
    partialToken.value = null
  }
  
  /**
   * Clear all 2FA data
   */
  function clearData() {
    setupData.value = null
    partialToken.value = null
  }
  
  /**
   * Download backup codes as text file
   */
  function downloadBackupCodes(codes: string[]) {
    const content = [
      'TheProtocol 2FA Backup Codes',
      '============================',
      '',
      'Keep these codes in a safe place.',
      'Each code can only be used once.',
      '',
      ...codes.map((code, index) => `${index + 1}. ${code}`),
      '',
      `Generated: ${new Date().toLocaleString(appLocale())}`
    ].join('\n')
    
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `theprotocol-2fa-backup-codes-${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout. Critical for 2FA
  // hygiene — must clear partialToken + setupData since they're auth secrets.
  function $reset() {
    isEnabled.value = false
    verifiedAt.value = null
    isSettingUp.value = false
    isVerifying.value = false
    isDisabling.value = false
    isCheckingStatus.value = false
    statusRead.value = 'idle'
    setupData.value = null
    partialToken.value = null
    developerId.value = null
  }

  return {
    // State
    isEnabled,
    verifiedAt,
    isSettingUp,
    isVerifying,
    isDisabling,
    isCheckingStatus,
    statusRead,
    setupData,
    $reset,
    partialToken,
    developerId,
    
    // Computed
    needsTwoFactorAuth,
    
    // Actions
    checkStatus,
    startSetup,
    completeSetup,
    disable,
    validateCode,
    recoverWithBackupCode,
    regenerateBackupCodes,
    setPartialToken,
    clearPartialToken,
    setDeveloperId,
    clearData,
    downloadBackupCodes
  }
})
