/**
 * services/api/frameKit.ts: §HELLOFRAME, the applicant's side of the frame kit (routers/frame_kit.py).
 *
 * `mine()` reads the caller's own frame requests, the kit this frame publishes and the network to join. `link()` asks for
 * a single-use download link; the page hands that URL to the browser, whose own download manager fetches the file (a
 * 300 MB kit does not belong in a JavaScript blob). apiClient's baseURL already carries /api/v1.
 */
import { apiClient } from './client'
import type { FrameKitPage } from '@/services/frameKit'

export interface KitLink {
  url: string
  expires_in: number
  filename: string
  size_bytes: number
  sha256: string
}

export const frameKitService = {
  async mine(): Promise<FrameKitPage> {
    const resp = await apiClient.get('/frame-kit/me')
    return resp.data as FrameKitPage
  },
  async link(requestId: string): Promise<KitLink> {
    const resp = await apiClient.post(`/frame-kit/me/${encodeURIComponent(requestId)}/link`)
    return resp.data as KitLink
  },
}
