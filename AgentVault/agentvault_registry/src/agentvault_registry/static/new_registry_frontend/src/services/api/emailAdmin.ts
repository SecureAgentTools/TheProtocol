/**
 * services/api/emailAdmin.ts — Admin email-template preview wrapper.
 *
 * Build #10 (2026-05-07) — frontend wrapper for the existing email preview
 * endpoints (already shipping in routers/admin_email_preview.py — no new
 * backend code needed for this build).
 *
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export type EmailTheme = 'neural' | 'sovereign'

export interface EmailPaletteEntry {
  [key: string]: any
}

export interface EmailListResponse {
  templates: string[]
  themes: EmailTheme[]
  neural_palette?: EmailPaletteEntry
  sovereign_palette?: EmailPaletteEntry
}

class EmailAdminService {
  private base = '/admin/email'

  /** GET /admin/email/preview — list templates + themes + palettes */
  async list(): Promise<EmailListResponse> {
    try {
      const resp = await apiClient.get(`${this.base}/preview`)
      return resp.data
    } catch (err) {
      console.error('Failed to list email templates:', err)
      throw err
    }
  }

  /** GET /admin/email/preview/{template}?theme= — rendered HTML (inlined). */
  async previewHtml(template: string, theme: EmailTheme = 'neural', inline: boolean = true): Promise<string> {
    try {
      const resp = await apiClient.get(`${this.base}/preview/${encodeURIComponent(template)}`, {
        params: { theme, inline: inline ? 'true' : 'false' },
        responseType: 'text',
        transformResponse: (raw) => raw,  // skip JSON parsing; backend returns text/html
      })
      return resp.data
    } catch (err) {
      console.error(`Failed to preview ${template}:`, err)
      throw err
    }
  }

  /** GET /admin/email/preview/{template}/text — plain-text alternative */
  async previewText(template: string): Promise<string> {
    try {
      const resp = await apiClient.get(`${this.base}/preview/${encodeURIComponent(template)}/text`, {
        responseType: 'text',
        transformResponse: (raw) => raw,
      })
      return resp.data
    } catch (err) {
      console.error(`Failed to preview text for ${template}:`, err)
      throw err
    }
  }
}

export const emailAdminService = new EmailAdminService()

// ── §2026-07-29 — Email Studio SEND capability ──────────────────────────────
// Senders are the identities the SMTP relay will actually accept (Proton binds
// From: to the authenticated address); the backend lists exactly those.

export interface EmailSender {
  id: string
  theme: EmailTheme
  from_email: string
  from_name: string
  hint: string
}

export interface EmailSendRequest {
  template: string
  subject: string
  recipients: string[]
  cc?: string[]
  bcc?: string[]
  theme: EmailTheme
  sender?: string
  context?: Record<string, any>
}

export interface EmailSendResponse {
  sent: boolean
  template: string
  theme: EmailTheme
  recipients: string[]
  count: number
}

class EmailSendService {
  private base = '/admin/email'

  /** GET /admin/email/senders — configured From-identities (no secrets). */
  async senders(): Promise<{ senders: EmailSender[]; smtp_configured: boolean }> {
    const resp = await apiClient.get(`${this.base}/senders`)
    return resp.data
  }

  /** GET /admin/email/context/{template} — sample context + suggested subject. */
  async sampleContext(template: string): Promise<{ template: string; context: Record<string, any>; suggested_subject: string }> {
    const resp = await apiClient.get(`${this.base}/context/${encodeURIComponent(template)}`)
    return resp.data
  }

  /** POST /admin/email/send — a REAL send. Merge order matches preview exactly. */
  async send(req: EmailSendRequest): Promise<EmailSendResponse> {
    const resp = await apiClient.post(`${this.base}/send`, req)
    return resp.data
  }
}

export const emailSendService = new EmailSendService()

// Context-aware previews for the send dialog: what it shows IS what goes out,
// because both feed the same renderer with the same merged context.
export const emailPreviewWithContext = {
  async html(template: string, theme: EmailTheme, context: Record<string, any>): Promise<string> {
    const resp = await apiClient.post(
      `/admin/email/preview/${encodeURIComponent(template)}`,
      context,
      { params: { theme }, responseType: 'text', transformResponse: (raw: any) => raw },
    )
    return resp.data
  },
  async text(template: string, context: Record<string, any>): Promise<string> {
    const resp = await apiClient.post(
      `/admin/email/preview/${encodeURIComponent(template)}/text`,
      context,
      { responseType: 'text', transformResponse: (raw: any) => raw },
    )
    return resp.data
  },
}
