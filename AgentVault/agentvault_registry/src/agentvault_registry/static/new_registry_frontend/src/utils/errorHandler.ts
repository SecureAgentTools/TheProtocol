/**
 * Global error handler for the application
 */

import type { App } from 'vue'
import { useUIStore } from '@/stores/ui'
import router from '@/router'
import { httpErrorFields } from '@/utils/httpError'

// Error types
export interface AppError extends Error {
  code?: string
  statusCode?: number
  details?: any
}

// Error severity levels
export enum ErrorSeverity {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical'
}

// Error handler class
export class ErrorHandler {
  private static instance: ErrorHandler
  private errorLog: AppError[] = []
  private maxLogSize = 100

  private constructor() {
    // Set up global handlers
    this.setupGlobalHandlers()
  }

  static getInstance(): ErrorHandler {
    if (!ErrorHandler.instance) {
      ErrorHandler.instance = new ErrorHandler()
    }
    return ErrorHandler.instance
  }

  /**
   * Set up global error handlers
   */
  private setupGlobalHandlers() {
    // Handle unhandled promise rejections
    window.addEventListener('unhandledrejection', (event) => {
      console.error('Unhandled promise rejection:', event.reason)
      this.handleError(event.reason, ErrorSeverity.HIGH)
      event.preventDefault()
    })

    // Handle global errors
    window.addEventListener('error', (event) => {
      // §MCFOLD (2026-09-02) — the browser's benign "ResizeObserver loop completed with undelivered
      // notifications" arrives here with `error === null` and was printed as `Global error: null` on
      // every dashboard load (measured identical before and after the fold). Not an error; not printed.
      if (/ResizeObserver loop/.test(String(event.message || ''))) return
      console.error('Global error:', event.error, event.message)
      this.handleError(event.error, ErrorSeverity.HIGH)
      event.preventDefault()
    })
  }

  /**
   * Handle an error
   */
  handleError(error: Error | AppError | any, severity: ErrorSeverity = ErrorSeverity.MEDIUM) {
    // Convert to AppError if needed
    const appError = this.normalizeError(error)
    
    // Log the error
    this.logError(appError)
    
    // Handle based on severity and type
    this.processError(appError, severity)
  }

  /**
   * Normalize error to AppError format
   */
  private normalizeError(error: any): AppError {
    // §FEFRAME W1 — an AxiosError IS an Error, so the old first branch returned it untouched: no `statusCode` (axios
    // puts the status on `response.status`), every status branch below was dead since it was written, and every failed
    // call got the generic "Request failed with status code N" toast. HTTP errors are read FIRST now.
    const http = httpErrorFields(error)
    if (http) {
      const appError = new Error(http.message) as AppError
      appError.code = http.code
      appError.statusCode = http.statusCode
      appError.details = http.details
      return appError
    }

    if (error instanceof Error) {
      return error as AppError
    }
    
    // Handle string errors
    if (typeof error === 'string') {
      return new Error(error) as AppError
    }
    
    // Default
    return new Error('An unknown error occurred') as AppError
  }

  /**
   * Log error for debugging
   */
  private logError(error: AppError) {
    this.errorLog.unshift(error)
    
    // Keep log size manageable
    if (this.errorLog.length > this.maxLogSize) {
      this.errorLog = this.errorLog.slice(0, this.maxLogSize)
    }
    
    // Log to console in development
    if (import.meta.env.DEV) {
      console.error('[ErrorHandler]', error)
    }
  }

  /**
   * Process error based on type and severity
   */
  private processError(error: AppError, severity: ErrorSeverity) {
    const uiStore = useUIStore()
    
    // Authentication errors: the API client's interceptor OWNS the session (it refreshes, retries, and ends the local
    // session only when a developer-tier 401 survives a refresh). Many 401s are expected answers: a visitor on a public
    // page (§DISCPUBLIC), an agent-tier call with no agent selected. §FEFRAME W1: this branch became reachable with the
    // normalization above, so it deliberately says nothing and redirects nowhere; before, it could not run at all.
    if (error.statusCode === 401) {
      return
    }
    
    // Handle permission errors
    if (error.statusCode === 403) {
      uiStore.showNotification({
        type: 'error',
        title: 'Access Denied',
        message: 'You do not have permission to perform this action.',
        duration: 7000
      })
      return
    }
    
    // Handle not found errors
    if (error.statusCode === 404) {
      uiStore.showNotification({
        type: 'warning',
        title: 'Not Found',
        message: error.message || 'The requested resource was not found.',
        duration: 5000
      })
      return
    }
    
    // Handle validation errors
    if (error.statusCode === 422 || error.code === 'VALIDATION_ERROR') {
      uiStore.showNotification({
        type: 'error',
        title: 'Validation Error',
        message: error.message || 'Please check your input and try again.',
        duration: 7000
      })
      return
    }
    
    // Handle server errors
    if (error.statusCode && error.statusCode >= 500) {
      uiStore.showNotification({
        type: 'error',
        title: 'Server Error',
        message: 'Something went wrong on our end. Please try again later.',
        persistent: severity === ErrorSeverity.CRITICAL,
        actions: severity === ErrorSeverity.CRITICAL ? [
          {
            label: 'Reload',
            handler: () => window.location.reload()
          }
        ] : undefined
      })
      return
    }
    
    // Handle network errors
    if (error.code === 'NETWORK_ERROR' || error.message.includes('Network')) {
      uiStore.showNotification({
        type: 'error',
        title: 'Connection Error',
        message: 'Unable to connect to the server. Please check your connection.',
        duration: 10000
      })
      return
    }
    
    // Default error handling
    const notificationType = severity === ErrorSeverity.LOW ? 'warning' : 'error'
    const duration = severity === ErrorSeverity.CRITICAL ? undefined : 7000
    
    uiStore.showNotification({
      type: notificationType,
      title: 'Error',
      message: error.message || 'An unexpected error occurred.',
      duration,
      persistent: severity === ErrorSeverity.CRITICAL
    })
  }

  /**
   * Get error log for debugging
   */
  getErrorLog(): AppError[] {
    return [...this.errorLog]
  }

  /**
   * Clear error log
   */
  clearErrorLog() {
    this.errorLog = []
  }
}

// Create and export singleton instance
export const errorHandler = ErrorHandler.getInstance()

// Vue plugin
export function setupErrorHandler(app: App) {
  // Add global error handler
  app.config.errorHandler = (err, instance, info) => {
    console.error('Vue error:', err, info)
    errorHandler.handleError(err, ErrorSeverity.HIGH)
  }
  
  // Add global property
  app.config.globalProperties.$errorHandler = errorHandler
  
  // Provide for injection
  app.provide('errorHandler', errorHandler)
}

// Composable
export function useErrorHandler() {
  return errorHandler
}
