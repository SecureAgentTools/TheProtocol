// Industry Blueprints — ordered catalogue.
// Priority ranking per strategy §2 (rail coverage + blocker fit +
// demonstrability). Adding industry #22 = one data file + one line here.

import { meridian } from './meridian'
import { hansa } from './hansa'
import { scrivener } from './scrivener'
import { dynamo } from './dynamo'
import { aegis } from './aegis'
import { civitas } from './civitas'
import { atelier } from './atelier'
import { vigil } from './vigil'
import { foundry } from './foundry'
import { crucible } from './crucible'
import { trunk } from './trunk'
import { bazaar } from './bazaar'
import { lifeline } from './lifeline'
import { keystone } from './keystone'
import { cadastre } from './cadastre'
import { arcadia } from './arcadia'
import { bulwark } from './bulwark'
import { demeter } from './demeter'
import { lyceum } from './lyceum'
import { ouroboros } from './ouroboros'
import { admiralty } from './admiralty'
import { alembic } from './alembic'
import { enclave } from './enclave'
import { zephyr } from './zephyr'
import { orrery } from './orrery'
import { hearth } from './hearth'
import { canopy } from './canopy'
import { cairn } from './cairn'

import type { Blueprint } from './types'

export const BLUEPRINTS: Blueprint[] = [
  meridian, hansa, scrivener,          // Tier I  — fully worked
  dynamo, aegis, civitas, atelier,     // Tier II — full anatomy
  // 8-12: drafted as Tier III sketches, graduated to full anatomy 2026-08-10
  vigil, foundry, crucible, trunk, bazaar,
  // From the Vault — the first nine sectors graduated to full drafts 2026-08-09
  lifeline, keystone, cadastre,        // 13-15: aid, construction, title
  arcadia, bulwark, demeter,           // 16-18: gaming, resilience, agriculture
  lyceum, ouroboros, admiralty,        // 19-21: credentials, circular, maritime
  // The frontier wave (2026-09-25): sectors arriving now, on the same live rails
  alembic,                             // 22: self-driving wet labs
  orrery,                              // 23: satellite passes and space traffic
  zephyr,                              // 24: drone corridors and vertiports
  hearth,                              // 25: household agents
  canopy,                              // 26: carbon removal and attestation
  enclave,                             // 27: data clean rooms
  cairn,                               // 28: off-world sites beyond live contact
]

export { RAILS, RAIL_BY_ID } from './rails'
export * from './types'

/** Sectors we can see but have not drafted (strategy §6, The Vault). */
export const VAULT: string[] = [
  'Legal aid and access to justice',
  'Pharmaceutical cold chain',
  'Sports, clubs and transfer markets',
  'Franchise operations',
  'Cooperative and community bookkeeping',
  'Compute and inference markets',
  'Open-source maintenance and dependency funding',
  'Autonomous vehicle fleets and charging',
  'Water rights and irrigation',
]
