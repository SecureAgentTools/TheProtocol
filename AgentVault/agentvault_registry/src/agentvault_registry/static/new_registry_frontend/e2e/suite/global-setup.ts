/**
 * Before any lifecycle (§FESUITE): the registry behind the console must answer, and a local build named by FESUITE_DIST
 * must exist, or every lifecycle would fail for the same reason and the run would read as a product collapse.
 */
import fs from 'node:fs'
import path from 'node:path'
import { request } from '@playwright/test'
import { API_URL, BASE_URL, DIST_DIR, HOST_MAP, RUN_ID, PREFIX, ensureOutDir } from './support/env'

export default async function globalSetup(): Promise<void> {
  if (!BASE_URL) throw new Error('FESUITE_BASE_URL is not set: name the console origin under test')
  if (DIST_DIR && !fs.existsSync(path.join(DIST_DIR, 'index.html'))) throw new Error(`FESUITE_DIST has no index.html: ${DIST_DIR}`)
  ensureOutDir()
  const ctx = await request.newContext({ baseURL: API_URL })
  try {
    const health = await ctx.get('/health', { failOnStatusCode: false })
    if (health.status() !== 200) throw new Error(`the registry at ${API_URL} answers /health with ${health.status()}`)
    const card = await ctx.get('/.well-known/registry-card.json', { failOnStatusCode: false })
    let version = 'unknown'
    let name = ''
    try {
      const c = await card.json()
      version = c?.identity?.software_version || 'unknown'
      name = c?.identity?.registry_name || ''
    } catch { /* stays unknown */ }
    process.env.FESUITE_TARGET_VERSION = version
    process.stdout.write(
      `[fesuite] run ${RUN_ID} (prefix ${PREFIX}): console ${BASE_URL}${HOST_MAP.length ? ' (mapped to this host)' : ''}, ` +
      `registry ${name || '?'} ${version}, build ${DIST_DIR ? 'local ' + DIST_DIR : 'as deployed'}\n`,
    )
  } finally {
    await ctx.dispose()
  }
}
