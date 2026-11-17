/** V0667 D7: a signed document saved as a file: named for its subject and kind, content the envelope whole and unchanged. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadSigned, fileNameOf } from './download'

describe('the signed document download', () => {
  afterEach(() => { vi.restoreAllMocks() })
  it('names a report for its release and a record for its change', () => {
    expect(fileNameOf({ kind: 'distribution.release.report', subject: 'V0666_lyceum' })).toBe('V0666_lyceum.report.json')
    expect(fileNameOf({ kind: 'distribution.change.record', subject: 'ct_abc' })).toBe('ct_abc.record.json')
    expect(fileNameOf({ kind: 'distribution.release.report', subject: '../../etc/x y' })).toBe('.._.._etc_x_y.report.json')
  })
  it('saves the envelope whole as JSON through a link it removes again', async () => {
    const made: Blob[] = []
    const url = vi.spyOn(URL, 'createObjectURL' as any).mockImplementation(((b: Blob) => { made.push(b); return 'blob:x' }) as any)
    ;(URL as any).revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const doc = { kind: 'distribution.release.report', subject: 'V0666_lyceum', report: { a: 1 }, digest: 'd' }
    downloadSigned(doc)
    expect(click).toHaveBeenCalledTimes(1); expect(url).toHaveBeenCalledTimes(1)
    expect(JSON.parse(await made[0].text())).toEqual(doc)
    expect(document.querySelector('a[download]')).toBeNull()
  })
})
