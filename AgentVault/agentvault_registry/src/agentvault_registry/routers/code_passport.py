"""V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511): the routes of services/code_passport.

On the HOME (a registry that does not govern code):
  GET  /api/v1/developers/me/code-passport             the press's state: who governs, the consent, the card's preview
  PUT  /api/v1/developers/me/code-passport             {"consent": true|false}: the press (never automatic) and taking it back
  POST /api/v1/code-passport/changes                   the developer's own agent proposes on the governing registry (relayed)
  POST /api/v1/code-passport/changes/{cid}/reviews     the developer's own agent reviews a change there (relayed)
  GET  /api/v1/developers/me/code-passport/repo-account   phase 4: the repository account on the code host, as the governing registry reads it
  POST /api/v1/developers/me/code-passport/repo-account   phase 4: link it through the press ({username, confirm, accept_terms}); the
                                                        one-time password is answered once
  POST /api/v1/federation/code-passport/standing       the governing registry's standing pull: a fresh card (consent required)
On the GOVERNING registry:
  POST /api/v1/federation/code-passport/{act}          a peer registry relays an act with its developer's signed card
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query, Security
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agentvault_registry import database
from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.routers.utils import get_current_agent
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import code_passport

router = APIRouter(tags=["Code passport"])


class ConsentIn(BaseModel):
    consent: bool


def _answer(result) -> JSONResponse:
    status, body = result
    return JSONResponse(status_code=status, content=body)


@router.get("/api/v1/developers/me/code-passport", summary="Taking part in code governance from this registry: the state and the card")
async def my_passport(agent_did: Optional[str] = Query(None, max_length=200), developer=Security(get_current_developer),
                      db=Depends(database.get_db)):
    return JSONResponse(status_code=200, content=await code_passport.consent_state(db, developer, agent_did))


@router.put("/api/v1/developers/me/code-passport", summary="Take part in code governance on the governing registry (or stop)")
async def set_my_passport(body: ConsentIn, developer=Security(get_current_developer), db=Depends(database.get_db)):
    if body.consent and not code_passport.available():          # taking it back stays possible whatever the network says
        status, code, sentence = code_passport.NO_GOVERNING
        return JSONResponse(status_code=status, content={"code": code, "detail": sentence})
    return JSONResponse(status_code=200, content=await code_passport.set_consent(db, developer, body.consent))


@router.post("/api/v1/code-passport/changes", status_code=201, summary="Propose a code change on the governing registry (your agent, relayed)")
async def relay_propose(body: Dict[str, Any] = Body(...), agent=Depends(get_current_agent), db=Depends(database.get_db)):
    return _answer(await code_passport.relay(db, agent, "propose", body))


@router.post("/api/v1/code-passport/changes/{cid}/reviews", summary="Review a code change on the governing registry (your agent, relayed)")
async def relay_review(cid: str, body: Dict[str, Any] = Body(...), agent=Depends(get_current_agent), db=Depends(database.get_db)):
    return _answer(await code_passport.relay(db, agent, "review", body, code_change_id=cid))


@router.get("/api/v1/developers/me/code-passport/repo-account", summary="Your repository account on the code host (taking part from here)")
async def relay_repo_status(agent_did: Optional[str] = Query(None, max_length=200), developer=Security(get_current_developer),
                            db=Depends(database.get_db)):
    return _answer(await code_passport.relay_for_developer(db, developer, "repo_status", {}, agent_did))


@router.post("/api/v1/developers/me/code-passport/repo-account", summary="Link a repository account on the code host (never automatic)")
async def relay_repo_link(body: Dict[str, Any] = Body(...), developer=Security(get_current_developer), db=Depends(database.get_db)):
    args = {k: body.get(k) for k in ("username", "confirm", "accept_terms")}
    status, out = await code_passport.relay_for_developer(db, developer, "repo_link", args, body.get("agent_did"))
    return JSONResponse(status_code=status, content=out, headers={"Cache-Control": "no-store"})


# registered before /{act}: a literal path first (FastAPI matches in registration order)
@router.post("/api/v1/federation/code-passport/standing", summary="The governing registry asks for a developer's standing (their card)")
async def federation_standing(body: Dict[str, Any] = Body(...), peer_spiffe: str = Depends(require_peer_registry_identity),
                              db=Depends(database.get_db)):
    return _answer(await code_passport.standing_card(db, peer_spiffe, body))


@router.post("/api/v1/federation/code-passport/{act}", summary="A peer registry relays its developer's act with their signed card")
async def federation_act(act: str, body: Dict[str, Any] = Body(...), peer_spiffe: str = Depends(require_peer_registry_identity),
                         db=Depends(database.get_db)):
    return _answer(await code_passport.accept(db, peer_spiffe, act, body))
