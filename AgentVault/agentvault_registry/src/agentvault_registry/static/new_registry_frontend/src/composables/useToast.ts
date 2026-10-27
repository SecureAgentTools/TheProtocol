/**
 * Toasts for code that asks `useToast()` (§FESUITE). This composable used to keep its own list that no component ever
 * rendered, so every message sent through it (the whole CI/CD area: "Pipeline created", every failure, and the
 * pipeline's webhook secret) appeared nowhere. It now hands each message to the one toast system the app mounts (the
 * ui store's NotificationSystem); the calls are unchanged, so callers need no edit.
 */
import { useUIStore } from '@/stores/ui'

export interface Toast {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message?: string
  duration?: number
}

export function useToast() {
  const addToast = (toast: Omit<Toast, 'id'>): string => {
    const id = useUIStore().showNotification({
      type: toast.type,
      title: toast.title,
      message: toast.message,
      ...(toast.duration ? { duration: toast.duration } : {}),
    })
    return String(id ?? '')
  }

  const success = (title: string, message?: string, duration?: number) =>
    addToast({ type: 'success', title, message, duration })

  const error = (title: string, message?: string, duration?: number) =>
    addToast({ type: 'error', title, message, duration: duration || 8000 })

  const warning = (title: string, message?: string, duration?: number) =>
    addToast({ type: 'warning', title, message, duration })

  const info = (title: string, message?: string, duration?: number) =>
    addToast({ type: 'info', title, message, duration })

  return { addToast, success, error, warning, info }
}
