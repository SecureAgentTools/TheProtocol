/**
 * §DOCSFIX D6-108 (2026-10-16): the globe's registry panel reads the card the live route answers.
 *
 * GET /api/v1/public/registry-card takes `peer` and answers an envelope around the card. The globe asked `?registry=`,
 * the parameter of a second handler the route shadowed, and read the envelope as if it were the card, so a click on a
 * peer showed this registry's own envelope and the panel's card sections stayed empty. `fetchCard` is the one way to the
 * bare card: `peer` for a peer, nothing for this registry, the envelope's `card` returned.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: h.get } }))

import { registryCardView } from './registryCardView'

describe('registryCardView.fetchCard', () => {
  beforeEach(() => h.get.mockReset())

  it('asks for a peer by `peer` and returns the card inside the envelope', async () => {
    const card = { identity: { registry_name: 'asia' }, operator: { display_name: 'ASIA' } }
    h.get.mockResolvedValue({ data: { is_self: false, name: 'asia', card } })
    await expect(registryCardView.fetchCard('asia')).resolves.toEqual(card)
    expect(h.get).toHaveBeenCalledWith('/public/registry-card', { params: { peer: 'asia' } })
  })

  it('asks for this registry with no parameter', async () => {
    h.get.mockResolvedValue({ data: { is_self: true, name: 'EU', card: { identity: { registry_name: 'eu' } } } })
    await expect(registryCardView.fetchCard(null)).resolves.toEqual({ identity: { registry_name: 'eu' } })
    expect(h.get).toHaveBeenCalledWith('/public/registry-card', { params: {} })
  })

  it('answers null when the envelope carries no card', async () => {
    h.get.mockResolvedValue({ data: { is_self: false, name: 'asia', card: null } })
    await expect(registryCardView.fetchCard('asia')).resolves.toBeNull()
  })
})
