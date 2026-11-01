import { describe, it, expect } from 'vitest'
import { foldThreads, orderIdOf, type ThreadMsg } from './threads'

/**
 * V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f): threads in a room. A reply folds under the message it answers; the
 * messages that name a Guild order fold into that order's thread (its live card the root when in view); a thread is
 * drawn where its latest message is; its bar counts what it holds, what is new and what is for you; opened, its
 * messages follow the root in order; one that holds something new for you opens by itself. BASE (V0651): threads.ts does
 * not exist.
 */
const A = 'gwo_' + 'a'.repeat(24)
const B = 'gwo_' + 'b'.repeat(24)
let n = 0
const msg = (o: Partial<ThreadMsg>): ThreadMsg => ({ id: o.id ?? `m${++n}`, seq: o.seq ?? n, kind: 'text', body: '', sender_ptype: 'agent',
  sender_id: 'did:x:a', ...o })
const opts = (expanded: string[] = [], lastReadSeq = 0) => ({ expanded: new Set(expanded), lastReadSeq,
  isMine: (m: ThreadMsg) => m.sender_id === 'me', forMe: (m: ThreadMsg) => String(m.body).includes('@maintainer') })

describe('the order a message is about', () => {
  it('its card first, then the first order id its text names', () => {
    expect(orderIdOf({ id: 'x', seq: 1, kind: 'card', card: { type: 'guild.order.live', refs: { order_id: A } } })).toBe(A)
    expect(orderIdOf({ id: 'x', seq: 1, kind: 'card', card: { type: 'guild.order', data: { ref: B } } })).toBe(B)
    expect(orderIdOf({ id: 'x', seq: 1, kind: 'text', body: `BID on ${A}, and ${B}` })).toBe(A)
    expect(orderIdOf({ id: 'x', seq: 1, kind: 'text', body: 'gwo_short and gwo_' + 'z'.repeat(24) })).toBeNull()
    expect(orderIdOf({ id: 'x', seq: 1, kind: 'card', card: { type: 'progress', data: {} } })).toBeNull()
  })
})

describe('folding', () => {
  it('an order\'s messages fold into its thread, drawn where its latest message is', () => {
    n = 0
    const ms = [msg({ id: 'o1', body: `ORDER ${A}: build (ad)` }), msg({ id: 'x1', body: 'unrelated' }),
      msg({ id: 'o2', body: `BID on ${A}` }), msg({ id: 'x2', body: 'unrelated too' }), msg({ id: 'o3', body: `DONE ${A}` })]
    const f = foldThreads(ms, opts())
    expect(f.list.map((m) => m.id)).toEqual(['x1', 'x2', 'o1'])          // the thread at its latest message
    expect(f.bars.o1).toMatchObject({ kind: 'order', orderId: A, count: 2, expanded: false })
    expect(f.bars.o1.last?.id).toBe('o3')
    expect(f.rootOf).toEqual({ o2: 'o1', o3: 'o1' })
    const open = foldThreads(ms, opts([`o:${A}`]))
    expect(open.list.map((m) => m.id)).toEqual(['x1', 'x2', 'o1', 'o2', 'o3'])
    expect([...open.inThread]).toEqual(['o2', 'o3'])
  })

  it("the order's live card roots its thread, even after the first message that names it", () => {
    n = 0
    const ms = [msg({ id: 't1', body: `about ${A}` }),
      msg({ id: 'card', kind: 'card', card: { type: 'guild.order.live', refs: { order_id: A }, data: { order_id: A } } }),
      msg({ id: 't2', body: `DONE ${A}` })]
    const f = foldThreads(ms, opts())
    expect(f.list.map((m) => m.id)).toEqual(['card'])
    expect(f.bars.card.count).toBe(2)
  })

  it('a reply folds under the message it answers, and a reply to a folded message joins its thread', () => {
    n = 0
    const ms = [msg({ id: 'q' }), msg({ id: 'r1', reply_to: 'q' }), msg({ id: 'o1', body: `${B} posted` }),
      msg({ id: 'r2', reply_to: 'o1' }), msg({ id: 'o2', body: `BID ${B}` }), msg({ id: 'r3', reply_to: 'r1' })]
    const f = foldThreads(ms, opts())
    expect(f.list.map((m) => m.id)).toEqual(['o1', 'q'])
    expect(f.bars.q).toMatchObject({ kind: 'reply', count: 2 })       // r1, and r3 (a reply to r1)
    expect(f.bars.o1).toMatchObject({ kind: 'order', count: 2 })      // r2 (a reply to the order's root), o2
  })

  it('a reply to a message out of view stays where it is', () => {
    n = 0
    const f = foldThreads([msg({ id: 'r', reply_to: 'paged-out' }), msg({ id: 'x' })], opts())
    expect(f.list.map((m) => m.id)).toEqual(['r', 'x'])
    expect(f.bars).toEqual({})
  })

  it('the bar counts what is new to you (never your own) and what is for you', () => {
    n = 0
    const ms = [msg({ id: 'o1', seq: 1, body: `${A}` }), msg({ id: 'o2', seq: 2, body: `${A} @maintainer look` }),
      msg({ id: 'o3', seq: 3, body: `${A} mine`, sender_id: 'me' }), msg({ id: 'o4', seq: 4, body: `${A} latest` })]
    const f = foldThreads(ms, opts([], 1))
    expect(f.bars.o1).toMatchObject({ count: 3, unread: 2, forMe: 1 })
  })

  it('a thread that holds something new for you opens by itself, until read or folded by hand (seq 419)', () => {
    n = 0
    const ms = [msg({ id: 'o1', seq: 1, body: `ORDER ${A}: build (ad)` }), msg({ id: 'o2', seq: 2, body: `@maintainer approve ${A}?` }),
      msg({ id: 'o3', seq: 3, body: `BID on ${A}` })]
    const f = foldThreads(ms, opts([], 1))
    expect(f.list.map((m) => m.id)).toEqual(['o1', 'o2', 'o3'])              // the question is in view without a click
    expect(f.bars.o1).toMatchObject({ expanded: true, forMe: 1, forMeNew: 1, unread: 2 })
    const read = foldThreads(ms, opts([], 3))                                 // read: the thread folds again
    expect(read.list.map((m) => m.id)).toEqual(['o1'])
    expect(read.bars.o1).toMatchObject({ expanded: false, forMe: 1, forMeNew: 0 })
    const byHand = foldThreads(ms, { ...opts([], 1), collapsed: new Map([[`o:${A}`, 3]]) })
    expect(byHand.list.map((m) => m.id)).toEqual(['o1'])                      // folded by hand: it stays folded
    const newer = foldThreads([...ms, msg({ id: 'o4', seq: 4, body: `@maintainer and ${A}, again` })],
      { ...opts([], 1), collapsed: new Map([[`o:${A}`, 3]]) })
    expect(newer.bars.o1.expanded).toBe(true)                                 // ...until a newer message for you (seq 425)
    const newerNotForYou = foldThreads([...ms, msg({ id: 'o4', seq: 4, body: `BID again on ${A}` })],
      { ...opts([], 1), collapsed: new Map([[`o:${A}`, 3]]) })
    expect(newerNotForYou.bars.o1.expanded).toBe(false)
    const mine = foldThreads([msg({ id: 'p1', seq: 1, body: `${A}` }), msg({ id: 'p2', seq: 2, body: `${A} @maintainer`, sender_id: 'me' })],
      opts([], 0))
    expect(mine.bars.p1.expanded).toBe(false)                                 // your own message is never "for you"
  })

  it('nothing to fold: the room as it is', () => {
    n = 0
    const ms = [msg({ id: 'a' }), msg({ id: 'b' })]
    expect(foldThreads(ms, opts()).list).toEqual(ms)
  })
})
