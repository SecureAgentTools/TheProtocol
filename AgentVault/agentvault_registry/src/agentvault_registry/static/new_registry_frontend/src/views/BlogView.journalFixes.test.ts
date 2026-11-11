/**
 * V0657 (g), Guild order gwo_23243e5a73c667ea502fd137 (agentvault2-d3, 2026-11-06): three journal defects of the
 * docs backlog, held here so a later edit cannot quietly bring them back.
 *
 * - D6-847: post text dimmed with an inline opacity failed colour contrast on nine older posts (sign-offs at 0.7,
 *   figcaptions and a caption at 0.65: 46 elements, axe "serious", both screens). Text takes a muted colour instead.
 * - D6-848: /static/blog/license-drift-monitor.png exists nowhere (404 on /blog/sixteen-passes-three-days-one-restart-loop);
 *   the figure became a sentence that keeps its caption's facts.
 * - D6-849: the console suite's wording rule counts a journal alt text from V0644; 22 alts in 13 posts still used the
 *   stake, token, reward, float, share, stock, bank and earn words (measured with e2e/suite/support/wording.ts on the
 *   branch's console: 22 on v0656/cut, 0 here).
 */
import { describe, it, expect } from 'vitest'
import source from './BlogView.vue?raw'

const posts = source.slice(0, source.indexOf('<style'))   // the posts' HTML, not the page's own stylesheet

describe('the journal: contrast, images and wording (V0657 (g))', () => {
  it('D6-847: no post text is dimmed with an inline opacity', () => {
    const dimmed = [...posts.matchAll(/<(p|figcaption|span|em|small|div)\b[^>]*style="[^"]*\bopacity:\s*0?\.\d+[^"]*"/g)]
      .map((m) => m[0].slice(0, 120))
    expect(dimmed).toEqual([])
  })

  it('D6-848: no post names the image that exists nowhere', () => {
    expect(posts).not.toContain('license-drift-monitor.png')
    expect(posts).toContain('After the flip, the compliance monitor showed the two new workers')
  })

  it('D6-849: the alt texts reworded stay reworded', () => {
    const alts = [...posts.matchAll(/\balt="([^"]*)"/g)].map((m) => m[1])
    const old = ['token and token id values', 'operating float', 'history, staking', 'the reward waterfall', 'bank connectivity',
      'the stock Forgejo', 'token economy', 'transfers, staking', 'Staking Reward', 'The legend earns its place',
      'staked amount', 'staked total', 'Stock Neural', 'getting tokens', 'Tokens received', 'Hetzner Token', 'launch float',
      'I-SHARES', 'popover floats', 'sections: EARNED']
    for (const phrase of old) expect(alts.filter((a) => a.includes(phrase)), phrase).toEqual([])
  })
})
