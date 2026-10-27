// registryCardView — read-only fetch of a registry card (self or a federated
// peer) for the reusable SovereignRegistryCard. Backed by the public endpoint
// GET /api/v1/public/registry-card?peer=<name> (B10, 2026-06-03). Registry
// cards are public signed documents, so no auth is required (apiClient still
// attaches the dev token harmlessly).
import { apiClient } from './client'

export interface RegistrySourceEnvelope {
  is_self: boolean
  name: string | null
  base_url: string | null
  card_etag: string | null
  card_signature_verified: boolean | null
  card_last_pulled_at: string | null
  public_card_url: string | null
  // §FEDLICENCE (2026-09-28): THIS registry's verdict about the source's network licence. For a peer it comes from our
  // own peer row, never from the card's claim; for self it is the card's own derived block. null = no verdict here.
  // Optional: an older registry does not send them.
  licence_state?: string | null
  licence_reason?: string | null
  licence_checked_at?: string | null
  card: any // full v0.4 registry card JSON
}

class RegistryCardViewService {
  /** Fetch a source registry's card. Omit/empty peerName → THIS registry's
   *  own signed card; otherwise the named federated peer's cached signed card. */
  async fetchSource(peerName?: string | null): Promise<RegistrySourceEnvelope> {
    const params: Record<string, string> = {}
    if (peerName && peerName.trim() && peerName.trim().toLowerCase() !== 'local') {
      params.peer = peerName.trim()
    }
    const r = await apiClient.get('/public/registry-card', { params })
    return r.data as RegistrySourceEnvelope
  }

  /** The bare card inside the envelope (null when the envelope carries none). §DOCSFIX D6-108 (2026-10-16): the globe's
   *  registry panel asked this route `?registry=`, the parameter of a second handler the route shadowed, and read the
   *  envelope as the card; it asks through here now. */
  async fetchCard(peerName?: string | null): Promise<any | null> {
    const env = await this.fetchSource(peerName)
    return env?.card ?? null
  }
}

export const registryCardView = new RegistryCardViewService()
