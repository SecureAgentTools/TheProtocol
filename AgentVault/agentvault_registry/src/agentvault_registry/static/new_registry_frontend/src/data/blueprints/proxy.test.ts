// V0659 (e): the proxy line under a blueprint's legacy block links a recipe only where one is written, and its addresses
// are the public ones (the docs site's chapter 37, the recipes folder in the public repository).
import { describe, it, expect } from 'vitest'
import { BLUEPRINTS, PROXY_DOCS_URL, PROXY_RECIPES_URL, PROXY_RECIPE_IDS, proxyRecipeUrl } from './index'

describe('TheProtocol Proxy beside the blueprints', () => {
  it('names the eight written recipes, once each', () => {
    expect([...PROXY_RECIPE_IDS].sort()).toEqual(['bazaar', 'dynamo', 'hansa', 'keystone', 'lyceum', 'meridian', 'scrivener', 'trunk'])
    expect(new Set(PROXY_RECIPE_IDS).size).toBe(PROXY_RECIPE_IDS.length)
  })

  it('gives every recipe a blueprint that shows the legacy block the line sits in', () => {
    for (const id of PROXY_RECIPE_IDS) {
      const bp = BLUEPRINTS.find((b) => b.id === id)
      expect(bp, id).toBeDefined()
      expect(bp!.legacy?.length ?? 0, id).toBeGreaterThan(0)
    }
  })

  it("links a recipe by the blueprint's id, and none where no recipe is written", () => {
    expect(proxyRecipeUrl('hansa')).toBe(`${PROXY_RECIPES_URL}/hansa`)
    const without = BLUEPRINTS.filter((b) => !PROXY_RECIPE_IDS.includes(b.id))
    expect(without.length).toBeGreaterThan(0)
    for (const b of without) expect(proxyRecipeUrl(b.id), b.id).toBeNull()
  })

  it('points at public https addresses', () => {
    expect(PROXY_DOCS_URL).toBe('https://docs.theprotocol.cloud/build/proxy')
    expect(PROXY_RECIPES_URL.startsWith('https://github.com/SecureAgentTools/TheProtocol/tree/main/theprotocol-sdk/proxy/recipes')).toBe(true)
  })
})
