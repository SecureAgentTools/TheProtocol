/**
 * V0665 the contributor track: a worn EARNED ring or badge is drawn by the art's own components, with no flare tier needed; the old encirclements and corner badges are drawn exactly as
 * before (a user with no earned variant takes the old path); an earned ring replaces the old encirclement and the earned-mark collar (one ring, not two).
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UserAvatar from './UserAvatar.vue'

const stubs = { FlareEncirclement: { template: '<i data-testid="old-ring" />' }, FlareBadge: { template: '<i data-testid="old-badge" />' }, EarnedMarkCollar: { template: '<i data-testid="collar" />' },
  EarnedRing: { props: ['ringKey', 'size'], template: '<i data-testid="ua-earned-ring" :data-key="ringKey" :data-size="size" />' }, EarnedBadge: { props: ['badgeKey', 'size'], template: '<i data-testid="ua-earned-badge" :data-key="badgeKey" :data-size="size" />' } }
const mountIt = (user: any, props: Record<string, any> = {}) => mount(UserAvatar, { props: { user, size: 'md', ...props }, global: { stubs } })
const has = (w: any, id: string) => w.find(`[data-testid="${id}"]`).exists()

describe('the avatar with an earned ring or badge', () => {
  it('draws an earned ring with no flare tier at all, at the avatar size', () => {
    const w = mountIt({ name: 'Ada', flare_encirclement_variant: 'ember' }, { size: 'xl' })
    expect(has(w, 'ua-earned-ring')).toBe(true)
    expect(w.find('[data-testid="ua-earned-ring"]').attributes()).toMatchObject({ 'data-key': 'ember', 'data-size': '96' })
    expect(has(w, 'old-ring')).toBe(false)
  })

  it('draws an earned badge in the corner, smaller on a small avatar', () => {
    expect(mountIt({ name: 'Ada', flare_corner_variant: 'initiate' }, { size: 'xs' }).find('[data-testid="ua-earned-badge"]').attributes('data-size')).toBe('16')
    expect(mountIt({ name: 'Ada', flare_corner_variant: 'initiate' }, { size: 'xl' }).find('[data-testid="ua-earned-badge"]').attributes('data-size')).toBe('22')
  })

  it('an earned badge replaces the old corner badge, an earned ring the old ring and the collar (one of each)', () => {
    const w = mountIt({ name: 'Ada', flare_tier: 'shadow_chancellor', selected_encirclement_flare: 'shadow_chancellor', selected_corner_flare: 'founder', flare_encirclement_variant: 'lantern', flare_corner_variant: 'keystone',
      track_record: { jobs: 3 } })
    expect(has(w, 'ua-earned-ring')).toBe(true); expect(has(w, 'old-ring')).toBe(false); expect(has(w, 'collar')).toBe(false)
    expect(has(w, 'ua-earned-badge')).toBe(true); expect(has(w, 'old-badge')).toBe(false)
  })

  it('leaves the old path exactly as it was for an old variant: the old ring and the old corner badge', () => {
    const w = mountIt({ name: 'Ada', flare_tier: 'shadow_chancellor', selected_encirclement_flare: 'shadow_chancellor', selected_corner_flare: 'founder', flare_encirclement_variant: 'sauron', flare_corner_variant: 'phoenix' })
    expect(has(w, 'old-ring')).toBe(true); expect(has(w, 'old-badge')).toBe(true)
    expect(has(w, 'ua-earned-ring')).toBe(false); expect(has(w, 'ua-earned-badge')).toBe(false)
  })

  it('draws nothing extra for a user with no flare at all', () => {
    const w = mountIt({ name: 'Ada' })
    for (const id of ['ua-earned-ring', 'ua-earned-badge', 'old-ring', 'old-badge']) expect(has(w, id)).toBe(false)
  })

  it('a preview override with an earned ring key draws that ring', () => {
    expect(mountIt({ name: 'Ada' }, { variantOverride: 'abyss' }).find('[data-testid="ua-earned-ring"]').attributes('data-key')).toBe('abyss')
  })
})
