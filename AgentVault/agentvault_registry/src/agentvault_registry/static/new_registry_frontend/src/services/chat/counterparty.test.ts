import { describe, expect, it } from 'vitest'
import { blockTargetFor, householdJoinPrompt, identityKind, identityPid, parseRemoteAddress } from './counterparty'

const REMOTE = { ptype: 'remote', developer_id: null, agent_did: null, remote_key: 'did:theprotocol:b:w@https://sandbox-b.test' }

describe('a counterparty on a peer registry (§TWOAGENT G1 household, V0436)', () => {
  it('is blocked by its ADDRESS, not as a developer with no id (that answered 422)', () => {
    expect(blockTargetFor(REMOTE)).toEqual({ ptype: 'remote', remote_key: REMOTE.remote_key })
  })
  it('renders as its own kind, identified by its address', () => {
    expect(identityKind('remote')).toBe('remote')
    expect(identityPid(REMOTE)).toBe(REMOTE.remote_key)
  })
  it('never builds a block the server can only refuse', () => {
    expect(blockTargetFor({ ptype: 'remote', remote_key: null })).toBeNull()
    expect(blockTargetFor({ ptype: 'agent', agent_did: '' })).toBeNull()
    expect(blockTargetFor({ ptype: 'developer', developer_id: null })).toBeNull()
    expect(blockTargetFor(null)).toBeNull()
  })
})

describe('control: local counterparties are unchanged', () => {
  it('an agent is blocked by DID and a developer by id', () => {
    expect(blockTargetFor({ ptype: 'agent', agent_did: 'did:theprotocol:x' })).toEqual({ ptype: 'agent', agent_did: 'did:theprotocol:x' })
    expect(blockTargetFor({ ptype: 'developer', developer_id: 7 })).toEqual({ ptype: 'developer', developer_id: 7 })
    expect(identityKind('developer')).toBe('developer')
    expect(identityKind(undefined)).toBe('developer')
    expect(identityPid({ ptype: 'developer', developer_id: 7 })).toBe(7)
  })
})


describe('starting a thread with someone on another registry (V0437)', () => {
  it('reads an address in every form a person types, in the server\'s one key form', () => {
    const want = 'ana@https://sandbox-b.test'
    for (const raw of ['ana@https://sandbox-b.test', 'Ana@HTTPS://Sandbox-B.Test/', '@ana@sandbox-b.test', ' ana@sandbox-b.test ']) {
      expect(parseRemoteAddress(raw)?.key).toBe(want)
    }
    expect(parseRemoteAddress('did:theprotocol:b:w@https://sandbox-b.test')?.isAgent).toBe(true)
  })
  it('splits on the LAST @ (a handle cannot smuggle a second address)', () => {
    expect(parseRemoteAddress('a@evil.test@https://sandbox-b.test')?.origin).toBe('https://sandbox-b.test')
  })
  it('a bare handle, a dotless host or garbage is not an address', () => {
    expect(parseRemoteAddress('ana')).toBeNull()
    expect(parseRemoteAddress('@ana')).toBeNull()
    expect(parseRemoteAddress('ana@localhost')).toBeNull()
    expect(parseRemoteAddress('ana@')).toBeNull()
    expect(parseRemoteAddress('')).toBeNull()
  })
})

describe('the consent question before an owner is announced (V0437)', () => {
  it('recognises the server\'s 409 and returns its sentence', () => {
    const e = { status: 409, detail: 'household_join_confirm: opening this thread tells the other side that you joined, as the owner of W. Open it again with join=true to continue.' }
    expect(householdJoinPrompt(e)).toMatch(/^opening this thread tells the other side/)
  })
  it('control: any other error is not the question', () => {
    expect(householdJoinPrompt({ status: 409, detail: 'you have left this conversation' })).toBeNull()
    expect(householdJoinPrompt({ status: 403, detail: 'household_join_confirm: x' })).toBeNull()
    expect(householdJoinPrompt(null)).toBeNull()
  })
})
