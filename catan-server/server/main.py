"""FastAPI WebSocket server — implements websocket_event_schema.md.

Envelope: {"type": ..., "seq": ..., "data": {...}}
Client actions map to catanatron ActionTypes (schema section 5).
"""
import asyncio
import json
import random
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from catanatron.models.player import Color
from catanatron.models.enums import ActionType, ActionPrompt

from .rooms import registry, Room, RoomPhase, Seat
from .serializer import serialize_for, serialize_public_player, serialize_private_hand
from .game_config import GAME_MODES
from .bot_personas import BOT_PERSONAS
from . import bot_chat

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
                    | {"waiting_on": room.waiting_on(), "turn_deadline": room.turn_deadline},
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
            if not m.hidden
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


BOT_TRADE_THINK_SECONDS = 2.5  # give humans first dibs before a bot grabs it


async def bot_consider_offer(room: Room, offer_id: int):
    """After a short 'thinking' pause (so humans can accept first), let the first
    willing bot take an open chat offer. One arithmetic pass per bot — cheap."""
    await asyncio.sleep(BOT_TRADE_THINK_SECONDS)
    async with room.lock:
        offer = room._find_trade(offer_id)
        taker = room.first_bot_to_accept(offer_id)
        if taker is None:
            return
        try:
            room.accept_trade(offer_id, taker)
        except (ValueError, KeyError):
            return
        room.persist()
    await broadcast_chat(room)
    await broadcast_state(room)  # the swap moved cards between hands
    # A beat later, the bot reacts in character (never blocks the swap).
    asyncio.create_task(bot_flavor_line(
        room, taker,
        f"You just accepted {offer['name']}'s trade — you gave {offer['get']} "
        f"and got {offer['give']}. React briefly, in character.",
    ))


def _bot_seats(room: Room):
    """(color, persona) for each seated bot with a chat persona."""
    return [
        (c, BOT_PERSONAS[s.bot_persona_key])
        for c, s in room.seats.items()
        if s.is_bot and s.bot_persona_key in BOT_PERSONAS
    ]


def _bot_public_state(room: Room, color) -> dict:
    game = room.game
    vps = {
        c.value: serialize_public_player(game, c)["public_victory_points"]
        for c in room.seating
    }
    hand = serialize_private_hand(game, color)["resources"]  # bot knows its own
    mine = ", ".join(f"{n} {r.lower()}" for r, n in hand.items() if n) or "empty"
    return {
        "vps": vps,
        "current_player": game.state.current_color().value,
        "my_resources": mine,
    }


async def maybe_bot_reply(room: Room, text: str):
    """If a human chat line addresses a bot, reply (Haiku if on-topic, else a
    canned deflection). Fired after the human message is already broadcast, so
    chat feels instant and a slow API call never blocks anyone's turn."""
    if room.game is None:
        return
    bots = _bot_seats(room)
    if not bots:
        return
    color = bot_chat.find_addressed_bot(text, bots)
    if color is None or not room.bot_reply_allowed():
        return
    persona = BOT_PERSONAS[room.seats[color].bot_persona_key]
    vocab = {s.name.lower() for s in room.seats.values()}
    if not bot_chat.looks_on_topic(text, vocab):
        async with room.lock:
            room.post_chat(color, bot_chat.pick_deflection(persona))
        await broadcast_chat(room)
        return
    asyncio.create_task(_bot_haiku_reply(room, color, persona, text))


async def _bot_haiku_reply(room: Room, color, persona, text: str):
    recent = [
        f"{e['name']}: {e['text']}"
        for e in room.chat_log[-6:] if e.get("kind") == "msg"
    ]
    context = bot_chat.build_bot_context(
        persona, bot_chat.RULEBOOK,
        list(room.bot_move_log.get(color, [])),
        _bot_public_state(room, color), recent,
    )
    reply = await bot_chat.get_bot_reply(persona, context, text)
    async with room.lock:
        room.post_chat(color, reply)
    await broadcast_chat(room)


async def bot_flavor_line(room: Room, color, situation: str):
    """Unprompted in-character chat reacting to something the bot just did (a
    trade it accepted, an offer it made). Skipped without an API key — we don't
    spam canned deflections unprompted — and gated by the same reply cooldown."""
    seat = room.seats.get(color)
    if not seat or not seat.is_bot or seat.bot_persona_key not in BOT_PERSONAS:
        return
    if not bot_chat.haiku_available() or not room.bot_reply_allowed():
        return
    persona = BOT_PERSONAS[seat.bot_persona_key]
    recent = [f"{e['name']}: {e['text']}" for e in room.chat_log[-6:] if e.get("kind") == "msg"]
    context = bot_chat.build_bot_context(
        persona, bot_chat.RULEBOOK, list(room.bot_move_log.get(color, [])),
        _bot_public_state(room, color), recent,
    )
    reply = await bot_chat.get_bot_reply(persona, context, situation)
    async with room.lock:
        room.post_chat(color, reply)
    await broadcast_chat(room)


async def start_turn_timer(room: Room):
    """If a per-turn timer is on, arm a watcher for the current human turn.
    On expiry it force-advances the turn (see Room.force_advance_turn). Stale
    watchers no-op via the turn token, so there's nothing to cancel."""
    if room.turn_timer_seconds <= 0 or room.phase != RoomPhase.PLAYING:
        return
    token = room._turn_token
    room.turn_deadline = time.time() + room.turn_timer_seconds
    asyncio.create_task(_turn_timeout(room, token, room.turn_timer_seconds))


async def _turn_timeout(room: Room, token: int, seconds: int):
    await asyncio.sleep(seconds)
    async with room.lock:
        if room._turn_token != token or room.phase != RoomPhase.PLAYING:
            return  # the turn already ended; this watcher is stale
        room.force_advance_turn()
        room.persist()
    await broadcast_state(room)
    # The next seat's clock (if human) starts when THEY roll; if it's a bot,
    # drive it now — a human further along will arm their own timer on rolling.
    await drive_bots(room)


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
    while room.phase == RoomPhase.PLAYING and room.game.winning_color() is None:
        color = room.game.state.current_color()
        is_bot = room.is_bot(color)
        # In "random" discard mode the server drops a random half for humans too,
        # so a 7 never waits on a picker.
        rand_discard = (
            not is_bot
            and room.discard_mode == "random"
            and room.game.state.current_prompt == ActionPrompt.DISCARD
        )
        if not (is_bot or rand_discard):
            break

        pace = 0
        try:
            if is_bot:
                bot = room.bot_player(color)
                if bot is None:
                    break
                game = room.game
                # Once per turn, a bot with a real shortfall floats a fair chat
                # offer (capped so it never spams). Others may take it async.
                if (game.state.current_prompt == ActionPrompt.PLAY_TURN
                        and color not in room._bot_offered):
                    room._bot_offered.add(color)  # at most one attempt this turn
                    cand = room.bot_trade_candidate(color)
                    if cand:
                        give, get = cand
                        try:
                            oid = room.propose_trade(color, give, get)["id"]
                            room.persist()
                            await broadcast_chat(room)
                            asyncio.create_task(bot_consider_offer(room, oid))
                            asyncio.create_task(bot_flavor_line(
                                room, color,
                                f"You just offered a trade: giving {give} for {get}. "
                                f"Announce it to the table in character, briefly."))
                        except ValueError:
                            pass
                # Never let a bot initiate catanatron's blocking domestic-trade
                # flow (OFFER_TRADE): humans have no engine-trade UI, so a bot
                # offer would deadlock. END_TURN is always available, so filtering
                # it can't strand the bot.
                options = [a for a in game.playable_actions if a.action_type != ActionType.OFFER_TRADE]
                action = await asyncio.to_thread(bot.decide, game, options)
                room.execute(color, action.action_type, action.value)
                room.record_bot_move(color, action)  # for this bot's chat context
                pace = BOT_STEP_PACING
            else:  # random-mode human discard: drop all owed cards at once
                while (
                    room.game.state.current_prompt == ActionPrompt.DISCARD
                    and room.game.state.current_color() == color
                ):
                    opts = [a for a in room.game.playable_actions
                            if a.action_type == ActionType.DISCARD_RESOURCE]
                    if not opts:
                        break
                    a = random.choice(opts)
                    room.execute(color, a.action_type, a.value)
        except Exception:
            break  # never let a misbehaving bot/discard wedge the room
        room.persist()
        await broadcast_state(room)
        steps += 1
        if steps > 3000:  # safety valve against a non-terminating loop
            break
        if pace:
            await asyncio.sleep(pace)


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
        # The engine only supports per-card discards (DISCARD_RESOURCE); a random
        # half is auto-resolved server-side (see drive_bots), not sent from here.
        return ActionType.DISCARD_RESOURCE, data["resource"]
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
                new_offer_id = None
                async with room.lock:
                    try:
                        if mtype == "chat_send":
                            room.post_chat(seat.color, data.get("text", ""))
                        elif mtype == "trade_propose":
                            new_offer_id = room.propose_trade(
                                seat.color, data.get("give"), data.get("get")
                            )["id"]
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
                # Let bots mull a fresh offer (they accept after a short delay).
                if new_offer_id is not None and any(s.is_bot for s in room.seats.values()):
                    asyncio.create_task(bot_consider_offer(room, new_offer_id))
                # An addressed bot may reply in chat (async; never blocks).
                if mtype == "chat_send":
                    await maybe_bot_reply(room, data.get("text", ""))
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
                            turn_timer_seconds=int(data.get("turn_timer", 0) or 0),
                            discard_mode=data.get("discard_mode", "choose"),
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
                if mtype == "roll_dice":
                    await start_turn_timer(room)  # arm this human's turn clock
                await broadcast_state(room)
                await drive_bots(room)  # advance through any bot turns that follow

    except WebSocketDisconnect:
        if seat is not None:
            seat.connected, seat.ws = False, None
            await broadcast_room(room)
