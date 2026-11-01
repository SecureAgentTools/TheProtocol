import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMessageBody from './ChatMessageBody.vue'
import fx from '@/services/chat/__fixtures__/serverMentions.json'

/**
 * V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1; the sessions' room seq 596-599): a mention is marked from what the
 * server resolved. The fixture is the server's own output, not a hand-made shape: the registry's
 * tests/test_chat_mention_shape_v0652.py compares it with services/chat_mentions.resolve_mentions, and each mention is
 * { key, ptype, developer_id, agent_did, token }. The viewer's own names are left empty here, so every mark below comes
 * from the server's list. BASE (57ecce954): the component read `label`, which nothing sends, so neither name was marked.
 */
const marks = (w: ReturnType<typeof mount>) => w.findAll('.cm-mention').map((s) => s.text())

describe('ChatMessageBody marks the mentions the server resolved', () => {
  it('both names the server resolved are marked; a name it did not resolve stays text', () => {
    const w = mount(ChatMessageBody, { props: { body: fx.body, mentions: fx.mentions, myKey: 'dev:9', myNames: [] } })
    expect(marks(w)).toEqual(['@maintainer', '@Scout'])
    expect(w.find('.cm-me').exists()).toBe(false)
    expect(w.text()).toContain('@nobody')
  })

  it('the viewer the server named stands out, by the key it stored', () => {
    const w = mount(ChatMessageBody, { props: { body: fx.body, mentions: fx.mentions, myKey: 'dev:6', myNames: [] } })
    expect(w.findAll('.cm-me').map((s) => s.text())).toEqual(['@maintainer'])
    expect(marks(w)).toEqual(['@maintainer', '@Scout'])
  })

  it('control: the same text without the server\'s list marks no one', () => {
    const w = mount(ChatMessageBody, { props: { body: fx.body, mentions: [], myKey: 'dev:6', myNames: [] } })
    expect(marks(w)).toEqual([])
  })
})
