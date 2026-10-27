// Deep architectures (strategy §18) — lazy loaders, one per industry.
// The Atlas never imports these; a chamber loads its module on navigation.
// Adding depth to an industry = one arch/<id>.ts file + one line here.
import type { BlueprintDeep } from '../types'

export const ARCH_LOADERS: Record<string, () => Promise<{ deep: BlueprintDeep }>> = {
  meridian: () => import('./meridian'),
  hansa: () => import('./hansa'),
  scrivener: () => import('./scrivener'),
  dynamo: () => import('./dynamo'),
  aegis: () => import('./aegis'),
  civitas: () => import('./civitas'),
  atelier: () => import('./atelier'),
  vigil: () => import('./vigil'),
  foundry: () => import('./foundry'),
  crucible: () => import('./crucible'),
  trunk: () => import('./trunk'),
  bazaar: () => import('./bazaar'),
  lifeline: () => import('./lifeline'),
  keystone: () => import('./keystone'),
  cadastre: () => import('./cadastre'),
  arcadia: () => import('./arcadia'),
  bulwark: () => import('./bulwark'),
  demeter: () => import('./demeter'),
  lyceum: () => import('./lyceum'),
  ouroboros: () => import('./ouroboros'),
  admiralty: () => import('./admiralty'),
  alembic: () => import('./alembic'),
  enclave: () => import('./enclave'),
  zephyr: () => import('./zephyr'),
  orrery: () => import('./orrery'),
  hearth: () => import('./hearth'),
  canopy: () => import('./canopy'),
  cairn: () => import('./cairn'),
}

export function hasDeep(id: string): boolean {
  return id in ARCH_LOADERS
}
