import { describe, it, expect } from 'vitest'
import { batchRefs, cardPayload, foldPictures, isPictureMime, composerLift, keyboardInset, planSend } from './attachmentGroups'

/** V0664 (order gwo_c101e38685cd18581be34c2f, his phone report seq 3741 to 3761): a message sent with pictures reads as ONE message with its
 *  pictures in it, for every reader; the pictures of a reply belong to the reply; a picture shows as a picture. */
const media = (seq: number, who: string, at: string, extra: Record<string, any> = {}) => ({
  id: `m${seq}`, seq, kind: 'card', sender_ptype: 'developer', sender_id: who, created_at: at, reply_to: null,
  card: { v: 1, type: 'media', data: { attachment_id: `a${seq}`, name: `s${seq}.jpg`, mime: 'image/jpeg', bytes: 1000 } }, ...extra,
})
const text = (seq: number, who: string, at: string, extra: Record<string, any> = {}) => ({
  id: `m${seq}`, seq, kind: 'text', sender_ptype: 'developer', sender_id: who, created_at: at, reply_to: null, body: 'words', ...extra,
})

describe('which files are pictures', () => {
  it('the registry takes png, jpeg, webp and gif as pictures (svg never: it can carry script)', () => {
    for (const m of ['image/png', 'image/jpeg', 'image/webp', 'image/gif']) expect(isPictureMime(m)).toBe(true)
    for (const m of ['image/svg+xml', 'application/pdf', 'text/plain', '', undefined]) expect(isPictureMime(m as any)).toBe(false)
  })
})

describe('what the composer sends', () => {
  it('gives the cards and the text of one send one batch, readable from the client_ref alone', () => {
    const r = batchRefs('ab12cd34', 3)
    expect(r.cards).toEqual(['att-ab12cd34-0', 'att-ab12cd34-1', 'att-ab12cd34-2'])
    expect(r.text).toBe('att-ab12cd34-t')
    expect(new Set([...r.cards, r.text]).size).toBe(4)
    for (const ref of [...r.cards, r.text]) expect(ref.length).toBeGreaterThanOrEqual(8)
  })
  it('puts the reply on every card, so the pictures of a reply belong to the reply', () => {
    const p = planSend('ab12cd34', [{ id: 'f1' }, { id: 'f2' }], 'parent-1')
    expect(p.cards.map((c) => c.reply_to)).toEqual(['parent-1', 'parent-1'])
    expect(p.text.reply_to).toBe('parent-1')
    expect(planSend('ab12cd34', [{ id: 'f1' }], null).cards[0].reply_to).toBeUndefined()
  })
  it('a card payload is a card with its own client_ref', () => {
    expect(cardPayload({ v: 1, type: 'media', data: {} }, 'att-ab12cd34-0', 'p')).toEqual({ kind: 'card', card: { v: 1, type: 'media', data: {} }, client_ref: 'att-ab12cd34-0', reply_to: 'p' })
  })
})

describe('foldPictures: the pictures read as part of the message they came with', () => {
  it('folds the cards of one batch into the text that closes it', () => {
    const list = [media(1, '6', '2026-11-14T13:55:06Z', { client_ref: 'att-ab12cd34-0' }), media(2, '6', '2026-11-14T13:55:07Z', { client_ref: 'att-ab12cd34-1' }),
      text(3, '6', '2026-11-14T13:55:08Z', { client_ref: 'att-ab12cd34-t', reply_to: 'parent-1' })]
    const f = foldPictures(list)
    expect(f.list.map((m: any) => m.id)).toEqual(['m3'])
    expect(f.pictures.get('m3')?.map((m: any) => m.id)).toEqual(['m1', 'm2'])
  })
  it('does the same for a send from before the marker: the same sender, in a row, within two minutes of the text, whatever the reply says', () => {
    const list = [media(1, '6', '2026-11-14T13:55:06Z'), media(2, '6', '2026-11-14T13:55:07Z'), media(3, '6', '2026-11-14T13:55:08Z'),
      text(4, '6', '2026-11-14T13:55:08Z', { reply_to: 'parent-1' })]
    const f = foldPictures(list)
    expect(f.list.map((m: any) => m.id)).toEqual(['m4'])
    expect(f.pictures.get('m4')).toHaveLength(3)
  })
  it('never folds across another sender, across a long gap, or into nothing', () => {
    const other = [media(1, '6', '2026-11-14T13:55:06Z'), text(2, '7', '2026-11-14T13:55:07Z')]
    expect(foldPictures(other).list).toHaveLength(2)
    const late = [media(1, '6', '2026-11-14T13:50:00Z'), text(2, '6', '2026-11-14T13:55:07Z')]
    expect(foldPictures(late).list).toHaveLength(2)
    const alone = [media(1, '6', '2026-11-14T13:55:06Z')]
    const f = foldPictures(alone)
    expect(f.list.map((m: any) => m.id)).toEqual(['m1'])
    expect(f.pictures.size).toBe(0)
  })
  it('leaves a card that is not media, and a text that comes before its pictures, alone', () => {
    const pay = { ...media(1, '6', '2026-11-14T13:55:06Z'), card: { v: 1, type: 'pay.request', data: {} } }
    expect(foldPictures([pay, text(2, '6', '2026-11-14T13:55:07Z')]).list).toHaveLength(2)
    expect(foldPictures([text(1, '6', '2026-11-14T13:55:06Z'), media(2, '6', '2026-11-14T13:55:07Z')]).list).toHaveLength(2)
  })
  it('keeps a message that was taken back out of the folding, and an empty list empty', () => {
    const gone = [media(1, '6', '2026-11-14T13:55:06Z', { deleted_at: '2026-11-14T13:56:00Z' }), text(2, '6', '2026-11-14T13:55:07Z')]
    expect(foldPictures(gone).pictures.get('m2') || []).toEqual([])
    expect(foldPictures([]).list).toEqual([])
  })
})

describe('keyboardInset: what the keyboard covers', () => {
  it('is the layout height minus the visible height and the visible top, never negative', () => {
    expect(keyboardInset(851, 520, 0)).toBe(331)
    expect(keyboardInset(851, 500, 20)).toBe(331)
    expect(keyboardInset(851, 851, 0)).toBe(0)
    expect(keyboardInset(851, 900, 0)).toBe(0)
  })
  it('ignores a small difference (a browser bar, a notch)', () => {
    expect(keyboardInset(851, 800, 0)).toBe(0)
    expect(keyboardInset(851, 781, 0)).toBe(70)
  })
  it('reads missing numbers as no keyboard', () => {
    expect(keyboardInset(NaN, 500, 0)).toBe(0)
    expect(keyboardInset(851, undefined as any, 0)).toBe(0)
  })
})

describe('composerLift: how far the thread shrinks so the composer clears the keyboard', () => {
  it('is the part of the thread below the visible area, and only while a keyboard is up', () => {
    // a 851 px layout, the keyboard leaves 520 visible; the thread ends at 760 (a 91 px tab bar under it): lift by 240
    expect(composerLift(851, 520, 0, 760, 0)).toBe(240)
    // the lift already applied is part of the measurement: the same state read after the shrink gives the same answer
    expect(composerLift(851, 520, 0, 520, 240)).toBe(240)
    // no keyboard: no lift, whatever the bars do
    expect(composerLift(851, 800, 0, 760, 0)).toBe(0)
    expect(composerLift(851, 851, 0, 760, 0)).toBe(0)
  })
  it('never goes below zero and ignores a non-number', () => {
    expect(composerLift(851, 520, 0, 400, 0)).toBe(0)           // the thread already ends above the keyboard
    expect(composerLift(Number.NaN, 520, 0, 760, 0)).toBe(0)
    expect(composerLift(851, 520, 0, Number.NaN, 0)).toBe(0)
  })
})
