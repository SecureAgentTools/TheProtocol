import { describe, it, expect } from 'vitest'
import { isMainframeOnlyRefusal, refusalDetail, MAINFRAME_ONLY_CODE } from './mainframeOnly'

const SENTENCE = 'This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain: they don\'t independently provision sub-operators, issue federation licenses, configure cross-frame bridges, or mint units. Use your federated mainframe\'s UI for these actions.'
const err = (status: number, data: unknown) => ({ response: { status, data } })

describe('D6-820 isMainframeOnlyRefusal: the refusal in both forms, nothing else', () => {
  it('reads V0640\'s form: 404 with the code word first (legacy detail and RFC 7807 error.detail)', () => {
    expect(isMainframeOnlyRefusal(err(404, { detail: `${MAINFRAME_ONLY_CODE}: ${SENTENCE}` }))).toBe(true)
    expect(isMainframeOnlyRefusal(err(404, { error: { detail: `mainframe_only: ${SENTENCE}`, type: 'not_found' } }))).toBe(true)
  })
  it('reads the form a registry before V0640 answers: 503 with the bare sentence', () => {
    expect(isMainframeOnlyRefusal(err(503, { detail: SENTENCE }))).toBe(true)
  })
  it('does not read an outage as the refusal (the old reading took every 503)', () => {
    expect(isMainframeOnlyRefusal(err(503, '<html>502 Bad Gateway</html>'))).toBe(false)
    expect(isMainframeOnlyRefusal(err(503, { detail: 'Database temporarily unavailable', error: { code: 'DATABASE_BUSY' } }))).toBe(false)
    expect(isMainframeOnlyRefusal(err(503, {}))).toBe(false)
  })
  it('does not read a plain 404 (an unknown operator) or the reverse guard as the refusal', () => {
    expect(isMainframeOnlyRefusal(err(404, { detail: 'Application not found.' }))).toBe(false)
    expect(isMainframeOnlyRefusal(err(404, { detail: 'operator_only: self-rename is for cloud-ops only. Mainframe admins use PUT /api/v1/admin/registry-card.' }))).toBe(false)
    expect(isMainframeOnlyRefusal(err(404, { detail: `the sentence later: ${MAINFRAME_ONLY_CODE}: x` }))).toBe(false)
  })
  it('a network error with no response is not the refusal', () => {
    expect(isMainframeOnlyRefusal({ message: 'Network Error' })).toBe(false)
    expect(isMainframeOnlyRefusal(null)).toBe(false)
  })
  it('refusalDetail reads the string forms and nothing else', () => {
    expect(refusalDetail('plain')).toBe('plain')
    expect(refusalDetail({ detail: { nested: true } })).toBe('')
    expect(refusalDetail(undefined)).toBe('')
  })
})
