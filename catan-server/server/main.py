"""FastAPI WebSocket server — implements websocket_event_schema.md.

Envelope: {"type": ..., "seq": ..., "data": {...}}
Client actions map to catanatron ActionTypes (schema section 5).
"""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from catanatron.models.player import Color
from catanatron.models.enums import ActionType

from .rooms import registry, Room, RoomPhase, Seat
from .serializer import serialize_for
from .game_config import GAME_MODES

# Seconds between consecutive bot actions, so humans can watch bots play out
# their turn rather than seeing the board teleport to the end state.
BOT_STEP_PACING = 0.6


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.restore_all()
    yield


app = FastAPI(lifespan=lifespan)


# --- wire helpers -----------------------------------------------------------

async def send(ws: WebSocket, type_: str, data: dict, seq: int = 0):
    await ws.send_text(json.dumps({"type": type_, "seq": seq, "data": data}))


async def broadcast_state(room: Room):
    """Push each connected player their own filtered view (never raw state)."""
    for color, seat in room.seats.items():
        if seat.connected and seat.ws is not None:
            try:
                await send(
                    seat.ws,
                    "state",
                    serialize_for(room.game, color, room.seating)
                    | {"waiting_on": room.waiting_on()},
                    seq=room.seq,
                )
            except Exception:
                seat.connected = False


async def broadcast_room(room: Room):
    payload = {
        "code": room.code,
        "phase": room.phase.value,
        "players": [
            {
                "name": s.name,
                "color": c.value,
                "connected": s.connected,
                "is_bot": s.is_bot,
            }
            for c, s in room.seats.items()
        ],
        "modes": [
            {"key": m.key, "label": m.label, "min": m.min_players, "max": m.max_players}
            for m in GAME_MODES.values()
        ],
    }
    for seat in room.seats.values():
        if seat.connected and seat.ws is not None:
            try:
                await send(seat.ws, "room_state", payload)
            except Exception:
                seat.connected = False


async def broadcast_chat(room: Room):
    """Push the full (capped) chat log — messages and trade offers — to everyone."""
    payload = {"entries": room.chat_log}
    for seat in room.seats.values():
        if seat.connected and seat.ws is not None:
            try:
                await send(seat.ws, "chat", payload)
            except Exception:
                seat.connected = False


async def drive_bots(room: Room):
    """Advance the game through any consecutive bot decision points until it's a
    human's turn (or the game is over), broadcasting after each so humans watch
    the bots play. The loop naturally halts whenever a human is on the clock —
    including mid-bot-turn blocking states like a human having to discard on a
    bot's 7. Caller must hold room.lock.

    bot.decide() is CPU-bound (~1s worst case), so it runs in a worker thread to
    keep the event loop responsive for every other room.
    """
    steps = 0
    while (
        room.phase == RoomPhase.PLAYING
        and room.game.winning_color() is None
        and room.is_bot(room.game.state.current_color())
    ):
        color = room.game.state.current_color()
        bot = room.bot_player(color)
        if bot is None:
            break
        game = room.game
        try:
            action = await asyncio.to_thread(bot.decide, game, game.playable_actions)
            room.execute(color, action.action_type, action.value)
        except Exception:
            break  # never let a misbehaving bot wedge the room
        room.persist()
        await broadcast_state(room)
        steps += 1
        if steps > 3000:  # safety valve against a non-terminating bot loop
            break
        await asyncio.sleep(BOT_STEP_PACING)


# --- client->server action mapping (schema section 5) ----------------------

_COLOR_NAMES = {c.value for c in Color}


def _trade_tuple(wire_value):
    """Rehydrate an echoed trade tuple: JSON turned Color enums into their
    string names (e.g. CONFIRM_TRADE's 11th element, the accepting player).
    Convert back so tuple equality against playable_actions holds."""
    return tuple(
        Color[v] if isinstance(v, str) and v in _COLOR_NAMES else v
        for v in wire_value
    )


def parse_action(msg_type: str, data: dict):
    """Translate a wire event into (ActionType, value). Raises KeyError/ValueError."""
    if msg_type == "roll_dice":
        return ActionType.ROLL, None
    if msg_type == "end_turn":
        return ActionType.END_TURN, None
    if msg_type == "buy_dev_card":
        return ActionType.BUY_DEVELOPMENT_CARD, None
    if msg_type == "place_piece":
        piece = data["piece"]
        if piece == "settlement":
            return ActionType.BUILD_SETTLEMENT, data["node_id"]
        if piece == "city":
            return ActionType.BUILD_CITY, data["node_id"]
        if piece == "road":
            return ActionType.BUILD_ROAD, tuple(data["edge"])
        raise ValueError(f"unknown piece {piece}")
    if msg_type == "move_robber":
        # catanatron combines robber move + victim: (coordinate, victim_color|None)
        victim = Color[data["victim"]] if data.get("victim") else None
        return ActionType.MOVE_ROBBER, (tuple(data["coordinate"]), victim)
    if msg_type == "discard":
        # catanatron discards a random half of the hand in one action; there is
        # no per-card DISCARD_RESOURCE in the engine. Value is always None.
        return ActionType.DISCARD, None
    if msg_type == "play_dev_card":
        card = data["card"]
        if card == "knight":
            return ActionType.PLAY_KNIGHT_CARD, None
        if card == "road_building":
            return ActionType.PLAY_ROAD_BUILDING, None
        if card == "monopoly":
            return ActionType.PLAY_MONOPOLY, data["resource"]
        if card == "year_of_plenty":
            return ActionType.PLAY_YEAR_OF_PLENTY, tuple(data["resources"])
        raise ValueError(f"unknown dev card {card}")
    if msg_type == "bank_trade":
        # catanatron MARITIME_TRADE value: 10-tuple (give x5, get x5 freqdecks)
        return ActionType.MARITIME_TRADE, tuple(data["freqdeck"])
    if msg_type == "make_offer":
        return ActionType.OFFER_TRADE, tuple(data["freqdeck"])  # 10-tuple give+get
    if msg_type == "accept_offer":
        return ActionType.ACCEPT_TRADE, _trade_tuple(data["trade"])
    if msg_type == "reject_offer":
        return ActionType.REJECT_TRADE, _trade_tuple(data["trade"])
    if msg_type == "confirm_offer":
        return ActionType.CONFIRM_TRADE, _trade_tuple(data["trade"])
    if msg_type == "cancel_offer":
        return ActionType.CANCEL_TRADE, None
    raise ValueError(f"unknown message type {msg_type}")


# --- endpoints --------------------------------------------------------------

@app.post("/rooms")
async def create_room():
    room, host_token = registry.create()
    return {"code": room.code, "host_token": host_token}


@app.websocket("/ws/{room_code}")
async def game_socket(ws: WebSocket, room_code: str):
    await ws.accept()
    room = registry.rooms.get(room_code.upper())
    if room is None:
        await send(ws, "error", {"reason": "room_not_found"})
        await ws.close()
        return

    seat: Seat | None = None
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype, data = msg.get("type"), msg.get("data", {})

            # -- lobby / connection events --
            if mtype == "join_room":
                token = data.get("rejoin_token")
                existing = room.seat_by_token(token) if token else None
                if existing:                       # reconnect path
                    seat = existing
                    seat.ws, seat.connected = ws, True
                else:                              # fresh join
                    color = room.next_free_color()
                    if color is None or room.phase != RoomPhase.LOBBY:
                        await send(ws, "error", {"reason": "room_full_or_started"})
                        continue
                    seat = Seat(
                        name=data["player_name"][:24],
                        color=color,
                        rejoin_token=uuid.uuid4().hex,
                        ws=ws,
                    )
                    room.seats[color] = seat
                await send(ws, "joined", {
                    "color": seat.color.value,
                    "rejoin_token": seat.rejoin_token,
                })
                await broadcast_room(room)
                await send(ws, "chat", {"entries": room.chat_log})  # backfill feed
                if room.phase != RoomPhase.LOBBY:
                    await broadcast_state(room)     # rejoin mid-game: full snapshot
                continue

            if seat is None:
                await send(ws, "error", {"reason": "join_first"})
                continue

            # -- chat & non-blocking player-to-player trades --
            if mtype in ("chat_send", "trade_propose", "trade_accept", "trade_cancel"):
                resources_changed = False
                async with room.lock:
                    try:
                        if mtype == "chat_send":
                            room.post_chat(seat.color, data.get("text", ""))
                        elif mtype == "trade_propose":
                            room.propose_trade(seat.color, data.get("give"), data.get("get"))
                        elif mtype == "trade_accept":
                            room.accept_trade(data["offer_id"], seat.color)
                            resources_changed = True
                        else:  # trade_cancel
                            room.cancel_trade(data["offer_id"], seat.color)
                        room.persist()
                    except (ValueError, KeyError) as e:
                        await send(ws, "error", {"reason": str(e)})
                        continue
                await broadcast_chat(room)
                if resources_changed:
                    await broadcast_state(room)  # a swap moved cards between hands
                continue

            # -- host: manage bot seats (lobby only) --
            if mtype in ("add_bot", "remove_bot"):
                if data.get("host_token") != room.host_token:
                    await send(ws, "error", {"reason": "host_only"})
                    continue
                try:
                    if mtype == "add_bot":
                        room.add_bot(data.get("kind", "normal"))
                    else:
                        room.remove_bot(Color[data["color"]])
                except (ValueError, KeyError) as e:
                    await send(ws, "error", {"reason": str(e)})
                    continue
                await broadcast_room(room)
                continue

            if mtype == "start_game":
                if data.get("host_token") != room.host_token:
                    await send(ws, "error", {"reason": "host_only"})
                    continue
                async with room.lock:
                    try:
                        room.start(
                            data.get("mode", "standard"),
                            bonus_start=bool(data.get("bonus_start", False)),
                        )
                        room.persist()
                    except ValueError as e:
                        await send(ws, "error", {"reason": str(e)})
                        continue
                    await broadcast_room(room)
                    await broadcast_state(room)
                    await drive_bots(room)  # bots may open the setup draft
                continue

            # -- game actions --
            try:
                action_type, value = parse_action(mtype, data)
            except (KeyError, ValueError) as e:
                await send(ws, "error", {"reason": f"bad_message: {e}"})
                continue

            async with room.lock:
                try:
                    room.execute(seat.color, action_type, value)
                    room.persist()
                except PermissionError as e:
                    await send(ws, "error", {"reason": str(e)})
                    continue
                await broadcast_state(room)
                await drive_bots(room)  # advance through any bot turns that follow

    except WebSocketDisconnect:
        if seat is not None:
            seat.connected, seat.ws = False, None
            await broadcast_room(room)
