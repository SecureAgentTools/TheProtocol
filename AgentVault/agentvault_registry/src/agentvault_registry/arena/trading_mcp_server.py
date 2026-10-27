"""
Market Mayhem MCP Server — Separate connector at /mcp/trading

Tools:
  trade_join       — Join/create a trading session
  trade_look       — See market prices, your portfolio, recent trades
  trade_buy        — Buy commodity at market price
  trade_sell       — Sell commodity at market price
  trade_short      — Open a short position
  trade_limit      — Place a limit order
  trade_portfolio  — Detailed portfolio breakdown
  trade_history    — Price history for charting
  trade_status     — Game state, leaderboard
  trade_list_games — List active/recent games
"""

import json
import logging
import uuid
import asyncio
from typing import Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..core.public_url import public_base_url

from .trading_engine import TradingGameState, Commodity, COMMODITY_BASE_PRICES
from .redis_state import RedisStringMap, game_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Trading MCP"])

# Game engine objects stay in local memory (not serializable)
from .redis_object_store import RedisObjectStore
from .player_identity import resolve_player_id, refused_response  # D6-633
_trading_games: RedisObjectStore = RedisObjectStore(
    "trading_games", TradingGameState.from_dict, TradingGameState.to_dict
)
# Agent-to-game mapping — synced to Redis for cross-worker visibility
_agent_to_game: RedisStringMap = RedisStringMap("trading_agent_to_game")
_bot_counter = 0

TRADING_SERVER_INFO = {
    "name": "MarketMayhem",
    "version": "1.0.0",
    "description": "Market Mayhem — Trade 5 volatile commodities against AI bots. Buy, sell, short, place limits. Insider tips. 50 rounds. Richest agent wins.",
    "capabilities": {"tools": {"listChanged": False}},
    "protocolVersion": "2025-11-25",
}

TRADING_TOOL_SCHEMAS = [
    {
        "name": "trade_join",
        "description": "Join or create a Market Mayhem trading session. Starts with 10,000 credits and 5 of each commodity. Add AI bot traders to compete against.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Your trader name", "default": "Trader"},
                "match_id": {"type": "string", "description": "Game to join (omit for new game)"},
                "add_bots": {"type": "integer", "description": "Number of AI bot traders (1-6)", "default": 3},
                "agent_token": {"type": "string", "description": "Not needed: a call made with an agent token of this registry in the Authorization header links its results to that agent's DID"},
            },
        }
    },
    {
        "name": "trade_look",
        "description": "View the market: current prices with % changes, your portfolio, recent trades by others, any insider tips you have, and pending orders. Call this before making decisions.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "trade_buy",
        "description": "Buy a commodity at the current market price. Costs credits. Buying pushes the price up. PRICE IMPACT: each unit traded moves the market ~2% (a 10-unit buy moves price ~20%). Split large orders across rounds to reduce slippage — the response includes a slippage_warning on orders that move price >10%.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string", "enum": ["ENERGY", "DATA", "COMPUTE", "TRUST", "DARK"], "description": "Commodity to buy"},
                "quantity": {"type": "integer", "description": "Number of units to buy", "default": 1},
            },
            "required": ["commodity"]
        }
    },
    {
        "name": "trade_sell",
        "description": "Sell a commodity you hold at the current market price for credits. Selling pushes the price down. PRICE IMPACT: each unit sold moves the market ~2% (a 10-unit sell moves price ~20%). Split large orders across rounds to reduce slippage — the response includes a slippage_warning on orders that move price >10%.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string", "enum": ["ENERGY", "DATA", "COMPUTE", "TRUST", "DARK"], "description": "Commodity to sell"},
                "quantity": {"type": "integer", "description": "Number of units to sell", "default": 1},
            },
            "required": ["commodity"]
        }
    },
    {
        "name": "trade_short",
        "description": "Open a short position — bet the price goes down. You receive credits now but owe the commodity back later. Requires 50% margin. Charges interest each round. PRICE IMPACT: opening a short moves the market down ~2% per unit. Response includes a slippage_warning on shorts that move price >10%.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string", "enum": ["ENERGY", "DATA", "COMPUTE", "TRUST", "DARK"]},
                "quantity": {"type": "integer", "description": "Number of units to short", "default": 1},
            },
            "required": ["commodity"]
        }
    },
    {
        "name": "trade_limit",
        "description": "Place a limit order that executes when the price reaches your target. Buy limits execute when price drops to your level. Sell limits execute when price rises to your level.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string", "enum": ["ENERGY", "DATA", "COMPUTE", "TRUST", "DARK"]},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "quantity": {"type": "integer", "default": 1},
                "limit_price": {"type": "number", "description": "Price at which the order should execute"},
            },
            "required": ["commodity", "side", "limit_price"]
        }
    },
    {
        "name": "trade_portfolio",
        "description": "View your detailed portfolio: credits, holdings with values, short positions with P&L, net worth, and your rank.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "trade_history",
        "description": "Get price history for one or all commodities. Useful for analyzing trends before trading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string", "enum": ["ENERGY", "DATA", "COMPUTE", "TRUST", "DARK"], "description": "Specific commodity (omit for all)"},
            },
        }
    },
    {
        "name": "trade_step",
        "description": "Advance the game by one round. Prices move, events may occur, limit orders execute, short interest is charged. Bots trade automatically.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "trade_status",
        "description": "Game status: round number, leaderboard rankings, recent events.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "trade_list_games",
        "description": "List all active and recent Market Mayhem games.",
        "inputSchema": {"type": "object", "properties": {}}
    },
]


async def _handle_trading_tool(tool_name: str, args: Dict, agent_id: str) -> Dict:
    global _bot_counter

    if tool_name == "trade_list_games":
        games = []
        for gid, g in await _trading_games.aitems():
            games.append({
                "match_id": gid, "traders": len(g.traders), "round": g.round_num,
                "finished": g.finished, "started": g.started,
                "winner": g.traders.get(g.winner, None) and g.traders[g.winner].name if g.winner else None,
            })
        return {"games": games}

    if tool_name == "trade_join":
        name = args.get("agent_name", "Trader")
        match_id = args.get("match_id")
        add_bots = min(6, max(0, int(args.get("add_bots", 3))))

        from .game_persistence import resolve_agent_did
        agent_did = resolve_agent_did(agent_id)  # D6-629: the verified player links its results

        if not match_id:
            match_id = f"MM-{uuid.uuid4().hex[:8].upper()}"
            game = TradingGameState(match_id=match_id)
        else:
            game = await _trading_games.aget(match_id)
            if not game:
                return {"error": "Game not found"}

        if game.started:
            return {"error": "Game already started"}

        trader = game.add_trader(agent_id, name)

        # Register in Redis for cross-worker visibility
        player_ids = list(game.traders.keys())
        await game_registry.register_game(match_id, "trading", player_ids)

        # Store DID
        if agent_did:
            if not hasattr(game, '_agent_dids'):
                game._agent_dids = {}
            game._agent_dids[agent_id] = agent_did

        # Add bots
        bot_names = ["Goldman", "Citadel", "BlackRock", "Bridgewater", "Renaissance", "TwoSigma"]
        for i in range(add_bots):
            _bot_counter += 1
            bot_id = f"bot:trader:{uuid.uuid4().hex[:6]}"
            bot_name = f"BOT-{bot_names[_bot_counter % len(bot_names)]}"
            game.add_trader(bot_id, bot_name)

        # Auto-start
        if len(game.traders) >= 2:
            game.start_game()

        # Persist state to Redis and mapping for cross-worker visibility.
        await _trading_games.aset(match_id, game)
        _agent_to_game[agent_id] = match_id
        await _agent_to_game.aset(agent_id, match_id)

        return {
            "match_id": match_id,
            "started": game.started,
            "your_name": name,
            "starting_credits": trader.credits,
            "starting_holdings": dict(trader.holdings),
            "traders": len(game.traders),
            "commodities": {c.value: round(game.prices[c.value], 2) for c in Commodity},
            "identified_as": agent_did,
            "message": f"Game started! You have {game.max_rounds} rounds. Use trade_look to see the market, trade_buy/trade_sell to trade, trade_step to advance rounds.",
        }

    # Need active game
    game_id = await _agent_to_game.aget(agent_id)
    game = await _trading_games.aget(game_id) if game_id else None
    if not game:
        return {"error": "Not in a game. Call trade_join first."}

    if tool_name == "trade_look":
        return game.get_market_view(agent_id)

    if tool_name == "trade_buy":
        commodity = args.get("commodity", "")
        quantity = int(args.get("quantity", 1))
        result = game.market_buy(agent_id, commodity, quantity)
        # Auto-advance round after trade
        if result.get("success"):
            round_result = game.advance_round(agent_id=agent_id)
            result["round_advanced"] = round_result
            if game.finished:
                _persist_trading_result(game)
        await _trading_games.aset(game_id, game)
        return result

    if tool_name == "trade_sell":
        commodity = args.get("commodity", "")
        quantity = int(args.get("quantity", 1))
        result = game.market_sell(agent_id, commodity, quantity)
        if result.get("success"):
            round_result = game.advance_round(agent_id=agent_id)
            result["round_advanced"] = round_result
            if game.finished:
                _persist_trading_result(game)
        await _trading_games.aset(game_id, game)
        return result

    if tool_name == "trade_short":
        commodity = args.get("commodity", "")
        quantity = int(args.get("quantity", 1))
        result = game.short_sell(agent_id, commodity, quantity)
        if result.get("success"):
            round_result = game.advance_round(agent_id=agent_id)
            result["round_advanced"] = round_result
            if game.finished:
                _persist_trading_result(game)
        await _trading_games.aset(game_id, game)
        return result

    if tool_name == "trade_limit":
        commodity = args.get("commodity", "")
        side = args.get("side", "buy")
        quantity = int(args.get("quantity", 1))
        limit_price = float(args.get("limit_price", 0))
        result = game.place_limit_order(agent_id, commodity, side, quantity, limit_price)
        await _trading_games.aset(game_id, game)
        return result

    if tool_name == "trade_portfolio":
        return game.get_portfolio(agent_id)

    if tool_name == "trade_history":
        commodity = args.get("commodity")
        return game.get_price_history(commodity)

    if tool_name == "trade_step":
        result = game.advance_round(agent_id=agent_id)
        if game.finished:
            _persist_trading_result(game)
        await _trading_games.aset(game_id, game)
        return result

    if tool_name == "trade_status":
        return {
            "round": game.round_num,
            "max_rounds": game.max_rounds,
            "started": game.started,
            "finished": game.finished,
            "winner": game.traders.get(game.winner, None).name if game.winner and game.winner in game.traders else None,
            "leaderboard": game.get_leaderboard(),
            "recent_events": [{"round": e["round"], "name": e["name"]} for e in game.event_log[-5:]],
        }

    return {"error": f"Unknown tool: {tool_name}"}


def _persist_trading_result(game: TradingGameState):
    """Persist trading game results to DB."""
    if getattr(game, '_persisted', False):
        return
    game._persisted = True
    try:
        from .game_persistence import persist_game_results

        agent_dids = getattr(game, '_agent_dids', {})
        rankings = sorted(game.traders.values(), key=lambda t: t.net_worth(game.prices), reverse=True)

        results = []
        for idx, trader in enumerate(rankings):
            results.append({
                "match_id": game.match_id,
                "game_type": "trading",
                "agent_did": agent_dids.get(trader.agent_id),
                "agent_name": trader.name,
                "score": int(trader.net_worth(game.prices)),
                "placement": idx + 1,
                "turns": game.round_num,
                "stats": {
                    "credits": round(trader.credits, 2),
                    "total_trades": len(trader.trades),
                    "net_worth": round(trader.net_worth(game.prices), 2),
                    "holdings": dict(trader.holdings),
                },
                "is_bot": trader.is_bot,
            })

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(persist_game_results(results))
        except RuntimeError:
            asyncio.run(persist_game_results(results))
    except Exception as e:
        logger.error(f"[Trading] Failed to persist results for {game.match_id}: {e}")


# ── JSON-RPC ──────────────────────────────────────────────────────────────

@router.post("", summary="Trading MCP Streamable HTTP")
async def trading_post(request: Request):
    try:
        raw = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    if not isinstance(raw, dict):
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Body must be JSON object"}})

    rid = raw.get("id")
    method = raw.get("method", "")
    params = raw.get("params", {}) or {}
    if isinstance(params, list):
        params = {}

    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "MarketMayhem", "version": "1.0.0", "description": TRADING_SERVER_INFO["description"]},
            "instructions": "Market Mayhem — call trade_join to start, trade_look to see the market, trade_buy/trade_sell to trade. 50 rounds, richest wins!",
        }})
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})
    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}}) if rid else JSONResponse(status_code=200, content={})
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": TRADING_TOOL_SCHEMAS}})
    if method == "resources/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"resources": []}})
    if method == "prompts/list":
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        valid = {t["name"] for t in TRADING_TOOL_SCHEMAS}
        if tool_name not in valid:
            return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown: {tool_name}"}})
        agent_id = await resolve_player_id(request)  # D6-633: a verified agent token of this registry, or none
        if agent_id is None:
            return refused_response(rid)
        result = await _handle_trading_tool(tool_name, arguments, agent_id)
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}], "isError": "error" in result}})

    return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


@router.get("", summary="Trading MCP GET")
async def trading_get(request: Request):
    async def _s():
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': TRADING_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield "event: ping\ndata: {}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/rpc")
async def trading_rpc(request: Request):
    return await trading_post(request)


@router.post("/sse")
async def trading_sse_post(request: Request):
    resp = await trading_post(request)
    body = resp.body.decode("utf-8")
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        async def _s():
            yield f"event: message\ndata: {body}\n\n"
        return StreamingResponse(_s(), status_code=200, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    return resp


@router.get("/sse")
async def trading_sse(request: Request):
    async def _s():
        # §DOCSFIX D6-631 (2026-10-16): the registry the client reached, never one fixed host (an operator may still name one)
        yield f"event: endpoint\ndata: {public_base_url(request)}/mcp/trading/rpc\n\n"
        yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': TRADING_SERVER_INFO})}\n\n"
        try:
            while True:
                await asyncio.sleep(30)
                yield "event: ping\ndata: {}\n\n"
        except:
            pass
    return StreamingResponse(_s(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/tools")
async def trading_tools():
    return {"server": "MarketMayhem", "tools": TRADING_TOOL_SCHEMAS, "total": len(TRADING_TOOL_SCHEMAS)}


@router.get("/health")
async def trading_health():
    games = await _trading_games.avalues()
    return {"status": "ok", "server": "MarketMayhem", "active_games": sum(1 for g in games if g.started and not g.finished), "total_games": len(games)}


@router.get("/games")
async def list_trading_games():
    games = []
    for gid, g in await _trading_games.aitems():
        w = g.traders.get(g.winner) if g.winner else None
        games.append({
            "match_id": gid, "traders": len(g.traders), "round": g.round_num,
            "max_rounds": g.max_rounds, "finished": g.finished, "started": g.started,
            "winner": w.name if w else None,
            "trader_names": [t.name for t in g.traders.values()],
        })
    return {"games": games}


@router.get("/games/{game_id}")
async def get_trading_game(game_id: str):
    game = await _trading_games.aget(game_id)
    if not game:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    # Auto-advance for spectator polling
    if game.started and not game.finished:
        game.advance_round()
        if game.finished:
            _persist_trading_result(game)
        await _trading_games.aset(game_id, game)
    return {"state": game.get_spectator_state()}
