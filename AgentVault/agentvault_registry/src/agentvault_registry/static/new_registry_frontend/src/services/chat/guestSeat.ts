/**
 * V0662 (OurChat lane, the organizations package's item 8): the console's half of a guest seat in an organization's room
 * (the registry's: services/chat_guests.py, POST /chat/conversations/{id}/guests, DELETE .../guests/{key}).
 *
 * The room's owner or an admin names one principal: an agent by its DID, a developer by id. A guest is shown as a guest in the
 * member sheet; the registry decides who may seat and remove (this only offers the controls to the room's operators, and the
 * registry still refuses anyone else).
 */
export type GuestTarget = { agent_did: string } | { developer_id: number }

/** What a person typed to name a guest: an agent DID (`did:...`) or a developer id (digits). Anything else is none. */
export function guestTarget(raw: string | null | undefined): GuestTarget | null {
  const s = String(raw ?? '').trim()
  if (/^did:[A-Za-z0-9._:%-]{3,250}$/.test(s)) return { agent_did: s }
  if (/^[1-9][0-9]{0,9}$/.test(s)) return { developer_id: Number(s) }
  return null
}

/** Whether the guest controls are offered: the room's operator sees them (the registry re-judges every press). */
export function canSeatGuests(room: { my_is_operator?: boolean } | null | undefined): boolean {
  return !!room?.my_is_operator
}
