/**
 * V0665 art — the contributor track's NEW cosmetics: corner badges, encirclements (rings) and titles.
 *
 * His idea and approval (room seq 4063, 4070): achievements that unlock new corner badges, rings and titles for the people who
 * build the beast. THE DESIGN: sessionlogs2026/DESIGN_2026-11-14_CONTRIBUTOR_TRACK.md. This file is the ART's catalog: the keys, the
 * lineage (which existing item each new one grew from), what is drawn and how it is unlocked. The unlock records and the Track tab
 * are a later order; nothing here is purchasable, nothing moves value, and no OLD badge or ring is touched (the registry's catalogs in
 * core/registry_identity.py are pinned by tests/test_flare_catalog_pinned_v0665.py, and none of the old components is edited).
 *
 * A new key is NOT in the registry's catalogs on purpose: it is not equippable until the track's own order wires the unlock records.
 */
export type TrackKind = 'ring' | 'badge' | 'title'
/** logo: the avatar stays visible inside the ring. full: the art covers the avatar (the void / blackhole family). */
export type RingCover = 'logo' | 'full'

export interface RingItem {
  key: string
  cover: RingCover
  /** The existing ring this one grew from (never edited), or null for a new line. */
  lineage: string | null
  tier: number | null
}
export interface BadgeItem {
  key: string
  lineage: 'architect' | 'founder' | null
  tier: number | null
}
export interface TitleItem {
  key: string
  /** the effect's name, for the gallery */
  style: string
  /** a side quest off the main row */
  fun: boolean
  /** drawn by the art as a suggestion beyond the design's sixteen: it waits for his yes */
  proposed?: boolean
}

export const NEW_RINGS: readonly RingItem[] = [
  { key: 'lantern', cover: 'logo', lineage: null, tier: 2 },
  { key: 'ember', cover: 'logo', lineage: 'phoenix', tier: 4 },
  { key: 'eye-of-the-senate', cover: 'logo', lineage: 'sauron', tier: 6 },
  { key: 'event-horizon', cover: 'full', lineage: 'blackhole', tier: 8 },
  { key: 'abyss', cover: 'full', lineage: 'void', tier: 9 },
  { key: 'supernova', cover: 'logo', lineage: 'inferno', tier: 10 },
  { key: 'ouroboros', cover: 'logo', lineage: null, tier: null },
  { key: 'merkle-ring', cover: 'logo', lineage: null, tier: null },
  { key: 'lattice', cover: 'logo', lineage: null, tier: null },
  { key: 'quantum-halo', cover: 'logo', lineage: null, tier: null },
  { key: 'watcher', cover: 'logo', lineage: 'sauron', tier: null },
  { key: 'solar-flare', cover: 'logo', lineage: 'inferno', tier: null },
  { key: 'singularity', cover: 'full', lineage: 'blackhole', tier: null },
  { key: 'eclipse', cover: 'full', lineage: 'void', tier: null },
]

export const NEW_BADGES: readonly BadgeItem[] = [
  { key: 'initiate', lineage: 'architect', tier: 1 },
  { key: 'architect-prime', lineage: 'architect', tier: 3 },
  { key: 'keystone', lineage: 'architect', tier: 5 },
  { key: 'founders-seal', lineage: 'founder', tier: 7 },
  { key: 'crown-of-the-commons', lineage: 'founder', tier: 10 },
  { key: 'gatekeeper', lineage: null, tier: null },
  { key: 'ledger-seal', lineage: null, tier: null },
  { key: 'quill', lineage: null, tier: null },
  { key: 'anvil', lineage: null, tier: null },
  { key: 'lantern-key', lineage: null, tier: null },
]

export const NEW_TITLES: readonly TitleItem[] = [
  { key: 'first-light', style: 'dawn sweep', fun: false },
  { key: 'patchwright', style: 'engraved steel', fun: false },
  { key: 'second-pair-of-eyes', style: 'offset outlines', fun: false },
  { key: 'ballot-bearer', style: 'wax red small caps', fun: false },
  { key: 'exactly-once', style: 'typewriter', fun: false },
  { key: 'mutually-trusted', style: 'interlocked hairlines', fun: false },
  { key: 'keeper-of-delta-zero', style: 'LED matrix', fun: false },
  { key: 'senate-scribe', style: 'quill stroke', fun: false },
  { key: 'bug-slayer', style: 'glitch that settles', fun: false },
  { key: 'architect-of-the-beast', style: 'blueprint grid', fun: false },
  { key: 'beast-tamer', style: 'molten', fun: false },
  { key: 'event-horizon', style: 'black-hole lean', fun: false },
  { key: 'the-eye-sees-all', style: 'iris flame', fun: false },
  { key: 'founder-of-the-commons', style: 'holographic foil', fun: false },
  { key: 'it-works-on-my-frame', style: 'glitch that never settles', fun: true },
  { key: 'off-by-one', style: 'one letter off', fun: true },
  // beyond the design's sixteen: the art's own suggestions, in the same spirit (room seq 4085: named in the gallery for his yes)
  { key: 'dead-letter-whisperer', style: 'envelope grey and a fading postmark', fun: false, proposed: true },
  { key: 'rollback-ready', style: 'a rewind sweep', fun: false, proposed: true },
  { key: 'quorum-maker', style: 'tally strokes', fun: false, proposed: true },
  { key: 'clean-checkout', style: 'terminal green and a check mark', fun: false, proposed: true },
]

/**
 * Every title is a slim chamfered nameplate in its own material (his notes, room seq 4134: "every title gets a plate", one plate system).
 * The materials: steel, brass, blueprint film, wax, foil, an LED panel, carbon, smoked glass, paper, iron, bronze.
 */
export type PlateMaterial = 'steel' | 'brass' | 'blueprint' | 'wax' | 'foil' | 'led' | 'carbon' | 'glass' | 'paper' | 'iron' | 'bronze'
export const TITLE_MATERIAL: Record<string, PlateMaterial> = {
  'first-light': 'brass',
  patchwright: 'steel',
  'second-pair-of-eyes': 'glass',
  'ballot-bearer': 'wax',
  'exactly-once': 'led',
  'mutually-trusted': 'steel',
  'keeper-of-delta-zero': 'led',
  'senate-scribe': 'paper',
  'bug-slayer': 'carbon',
  'architect-of-the-beast': 'blueprint',
  'beast-tamer': 'iron',
  'event-horizon': 'glass',
  'the-eye-sees-all': 'bronze',
  'founder-of-the-commons': 'foil',
  'it-works-on-my-frame': 'carbon',
  'off-by-one': 'steel',
  'dead-letter-whisperer': 'paper',
  'rollback-ready': 'brass',
  'quorum-maker': 'steel',
  'clean-checkout': 'led',
}

/** The one-of-one plate of the commander flare tier (only his account holds it): drawn by CommanderPlate.vue, shown to that tier only. */
export const COMMANDER_TITLE_KEY = 'commander'

export const RING_KEYS = NEW_RINGS.map((r) => r.key)
export const BADGE_KEYS = NEW_BADGES.map((b) => b.key)
export const TITLE_KEYS = NEW_TITLES.map((t) => t.key)
export const PROPOSED_TITLE_KEYS = NEW_TITLES.filter((t) => t.proposed).map((t) => t.key)

/** The sizes the gallery shows (px): the sidebar's 22, a list row's 32 and a profile card's 96. */
export const GALLERY_SIZES = [22, 32, 96] as const
