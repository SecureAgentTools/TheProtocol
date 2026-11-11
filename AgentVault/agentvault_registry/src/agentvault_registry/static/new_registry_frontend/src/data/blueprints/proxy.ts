// V0659 (e): TheProtocol Proxy beside the blueprints. A blueprint's "Runs beside what you already have" block used to end on
// "Planned: a public proxy library"; the proxy ships with the SDK (0.8.0) and eight blueprints have a ready recipe in
// theprotocol-sdk/proxy/recipes/ (a spec, a fake of the legacy system, a README). This is the one list the console's
// blueprint section and the apex's static blueprint pages (scratchpad/gen_blueprint_static.mjs) both read, so the two
// never disagree about which blueprint has a recipe.

/** Docs chapter 37, The Proxy. */
export const PROXY_DOCS_URL = 'https://docs.theprotocol.cloud/build/proxy'

/** The recipes folder in the public repository. */
export const PROXY_RECIPES_URL = 'https://github.com/SecureAgentTools/TheProtocol/tree/main/theprotocol-sdk/proxy/recipes'

/** Blueprints with a written recipe; each recipe's folder is named for the blueprint's id. */
export const PROXY_RECIPE_IDS: readonly string[] = ['meridian', 'hansa', 'dynamo', 'bazaar', 'scrivener', 'lyceum', 'keystone', 'trunk']

/** The recipe's address for a blueprint, or null when its recipe is not written yet. */
export function proxyRecipeUrl(blueprintId: string): string | null {
  return PROXY_RECIPE_IDS.includes(blueprintId) ? `${PROXY_RECIPES_URL}/${blueprintId}` : null
}
