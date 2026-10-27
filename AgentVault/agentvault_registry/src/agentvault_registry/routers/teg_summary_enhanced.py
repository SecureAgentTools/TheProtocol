"""
Enhanced TEG Summary endpoint that returns real data.

This module fixes the hardcoded treasury balance issue and provides
accurate economic footprint data for developers.
"""
from typing import Annotated, List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from decimal import Decimal
import logging
import os
import asyncio
import httpx

from ..database import get_db
from ..models import Developer, Agent
from ..schemas_enhanced import TEGSummaryEnhanced
from ..security import get_current_developer
from ..teg_client import get_teg_client
from ..config import settings

logger = logging.getLogger(__name__)

# Frame-native currency (AVT=Frame-A · JDAY=Frame-B · BVT=Frame-C); never hardcode 'AVT'. (#26)
_FRAME_CCY = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"

router = APIRouter()


# 2026-07-27: the duplicate `GET /me/teg-summary` that lived here was DELETED.
# It never served: developers.router registers at main.py:561, this router at :710, and
# FastAPI resolves by REGISTRATION ORDER, not path specificity — so every request hit
# developers.py::get_teg_summary. Two live definitions of one path is a trap: this one
# returned `total_agents` where the served one returns `agent_count`, so "fixing" the
# shadowing by reordering would have silently broken Mission Control's agent count AND
# Pocket's agent chip at once. `/me/teg-summary/treasury` below is UNIQUE to this router
# (Mission Control, MCP getMyTreasuryBalance, api-tester all call it) and therefore stays.



@router.get("/me/teg-summary/treasury",
            summary="Get real treasury balance",
            description="Returns the actual treasury balance, not hardcoded values")
async def get_treasury_balance(
    current_developer: Annotated[Developer, Security(get_current_developer)]
) -> Dict[str, Any]:
    """
    Get the real treasury balance from TEG Layer.
    
    This endpoint specifically addresses the hardcoded 713,651 AVT issue
    by fetching the actual treasury balance from the TEG Layer.
    """
    try:
        teg_client = get_teg_client()
        
        # Get treasury balance
        treasury_did = settings.TEG_SYSTEM_TREASURY_DID or "did:theprotocol:treasury"
        treasury_balance = await teg_client.get_balance(treasury_did)
        
        # Get additional treasury info if available
        # §MONEY-R27: get_treasury_info() used to FABRICATE supply figures when the TEG was
        # unreachable; it now raises. A bare `except:` would turn that into an empty dict, which
        # is the same two-state collapse one level up — the caller cannot tell "the TEG reported
        # nothing extra" from "we could not reach the TEG". Say which.
        treasury_info: dict = {}
        info_available = True
        try:
            treasury_info = await teg_client.get_treasury_info()
        except Exception as e:  # noqa: BLE001 — degrade, but never silently
            info_available = False
            logger.warning("Treasury detail unavailable (the balance above is still real): %s", e)
        
        return {
            "treasury_did": treasury_did,
            "balance": str(treasury_balance),
            "currency": _FRAME_CCY,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "note": "This is the REAL treasury balance, not hardcoded",
            "additional_info": treasury_info,
            "additional_info_available": info_available
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch treasury balance: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch treasury balance from TEG Layer"
        )
