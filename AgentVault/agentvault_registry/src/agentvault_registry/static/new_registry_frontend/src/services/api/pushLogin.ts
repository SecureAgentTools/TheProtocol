/**
 * PUSH LOGIN (2026-07-25) — approve a sign-in from your phone with a fingerprint.
 * Ground truth: routers/push_login.py. Opt-in per developer; existing 2FA is untouched.
 */
import { apiClient } from './client'

export interface PushLoginRequestResult {
  available: boolean
  approval_id?: string
  expires_in?: number
  detail?: string
}

export const pushLoginApi = {
  /** Password already typed — ask the phone. Returns available:false uniformly when unusable. */
  request: (email: string, password: string) =>
    apiClient.post<PushLoginRequestResult>('/auth/push-login/request', { email, password }).then(r => r.data),

  /** Session-free: what to sign, for a device that may itself be the one logging in. */
  challenge: (id: string) =>
    apiClient.get<{ challenge_hash: string; credential_ids: string[]; requested_ip: string; expires_at: string }>(
      `/auth/push-login/${id}/challenge`).then(r => r.data),

  /** Approve with an assertion and no session — the assertion is the authentication. */
  approveDirect: (id: string, body: { credential_id?: string; authenticator_data: string;
                                      client_data_json: string; signature: string }) =>
    apiClient.post(`/auth/push-login/${id}/approve-direct`, body).then(r => r.data),

  status: (id: string) =>
    apiClient.get<{ status: string }>(`/auth/push-login/${id}/status`).then(r => r.data),

  detail: (id: string) =>
    apiClient.get(`/auth/push-login/${id}/detail`).then(r => r.data),

  approve: (id: string, body: { device_id: number; credential_id?: string;
                                authenticator_data: string; client_data_json: string; signature: string }) =>
    apiClient.post(`/auth/push-login/${id}/approve`, body).then(r => r.data),

  deny: (id: string) => apiClient.post(`/auth/push-login/${id}/deny`).then(r => r.data),

  token: (id: string) =>
    apiClient.post<{ access_token: string; token_type: string; refresh_token?: string }>(`/auth/push-login/${id}/token`).then(r => r.data),

  getSettings: () =>
    apiClient.get<{ push_login_enabled: boolean; device_ready: boolean }>('/auth/push-login/settings').then(r => r.data),

  setSettings: (enabled: boolean) =>
    apiClient.post('/auth/push-login/settings', { enabled }).then(r => r.data),
}
