// POCKET FRAME — device push registration API client (f-mobile, 2026-07-07).
// apiClient.baseURL already carries /api/v1, so paths here are relative.
// Developer-JWT surface. Rails: 'ntfy' live; 'fcm'/'apns' accepted-but-stubbed.
import { apiClient } from './client'

export interface DevicePrefs {
  event_types?: string[]        // allowlist; absent = delegation events only
  min_transfer_avt?: number     // presence opts into TokensTransferred pushes ≥ value
}

export interface PushDevice {
  id: number
  platform: 'android' | 'ios' | 'web'
  rail: 'ntfy' | 'fcm' | 'apns'
  target: string
  label: string | null
  enabled: boolean
  created_at?: string
  last_seen_at?: string
  /** §POCKETPAIR: registered with a paired API key (removing the device revokes it), and whether that key still works. */
  paired_key?: boolean
  paired_key_active?: boolean
}

export interface DeviceRegisterBody {
  platform: 'android' | 'ios' | 'web'
  rail: 'ntfy' | 'fcm' | 'apns'
  target: string
  label?: string | null
  prefs?: DevicePrefs | null
}

export interface PushConfig {
  ntfy_public_url: string      // public ntfy base for this frame (empty = not exposed)
  notify_enabled: boolean
}

class DevicePushApi {
  /** Public: this frame's ntfy public base, used to build the subscribe QR/deep-link. */
  async getConfig(): Promise<PushConfig> {
    const { data } = await apiClient.get('/devices/config')
    return data
  }

  async listMine(): Promise<{ devices: PushDevice[]; total: number }> {
    const { data } = await apiClient.get('/devices/mine')
    return data
  }

  async register(body: DeviceRegisterBody): Promise<PushDevice> {
    const { data } = await apiClient.post('/devices/register', body)
    return data
  }

  async remove(deviceId: number): Promise<{ ok: boolean; id: number; paired_key_revoked?: boolean }> {
    const { data } = await apiClient.delete(`/devices/${deviceId}`)
    return data
  }
  /** WEB PUSH — the app's own channel (no second app). */
  async webpushKey(): Promise<{ application_server_key: string; enabled: boolean }> {
    const { data } = await apiClient.get('/devices/webpush/key')
    return data
  }

  async webpushSubscribe(sub: PushSubscriptionJSON, label?: string): Promise<any> {
    const { data } = await apiClient.post('/devices/webpush/subscribe', {
      endpoint: sub.endpoint, keys: sub.keys, label,
    })
    return data
  }

  async webpushUnsubscribe(endpoint: string): Promise<any> {
    const { data } = await apiClient.post('/devices/webpush/unsubscribe', { endpoint, keys: {} })
    return data
  }
}

export const devicePushApi = new DevicePushApi()

/** Generate a boring, URL-safe ntfy topic (matches backend regex [A-Za-z0-9_-]{3,64}). */
export function randomNtfyTopic(): string {
  const rnd = Array.from(crypto.getRandomValues(new Uint8Array(9)))
    .map((b) => b.toString(36).padStart(2, '0'))
    .join('')
    .slice(0, 14)
  return `tp-${rnd}`
}
