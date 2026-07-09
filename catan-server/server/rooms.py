"""Room/session management — the JSettlers2-derived state machine.

Key structural decisions (see websocket_event_schema.md for full provenance):
- One asyncio.Lock per room around game.execute(): single-writer correctness.
- Blocking states (discards, trade decisions) tracked via waiting_on sets.
- Seats keyed by rejoin_token, not by socket: disconnect != leave.
- Periodic pickle to disk so a container restart doesn't kill game night.
"""
import asyncio
import pickle
import random
import string
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from . import colors  # noqa: F401  — extends Color to 6 members (import for side effect)

from catanatron import Game
from catanatron.models.player import Color, Player
from catanatron.models.enums import Action, ActionType, ActionPrompt, RESOURCES
from catanatron.players.minimax import AlphaBetaPlayer
from catanatron.players.weighted_random import WeightedRandomPlayer
from catanatron.state_functions import player_key

from .game_config import GAME_MODES, GameMode

PERSIST_DIR = Path("/data/rooms")
SEAT_ORDER = [
    Color.RED, Color.BLUE, Color.ORANGE, Color.WHITE, Color.GREEN, Color.BROWN,
]
RESOURCE_NAMES = set(RESOURCES)
CHAT_LOG_CAP = 200  # keep the wire/replay payload bounded

# Bot difficulties the host can add to fill seats. AlphaBeta finishes games with
# sub-second moves; WeightedRandom is instant but plays randomly. (ValueFunction
# was rejected: it stalls in self-play.) Bot .decide() is CPU-bound — always run
# it off the event loop (see main.drive_bots).
BOT_KINDS: dict[str, type] = {
    "easy": WeightedRandomPlayer,
    "normal": AlphaBetaPlayer,
}
DEFAULT_BOT_KIND = "normal"


class HumanSeat(Player):
    """catanatron Player whose decide() is never called server-side;
    actions arrive over the websocket instead."""

    def decide(self, game, playable_actions):  # pragma: no cover
        raise RuntimeError("HumanSeat.decide should never be invoked")


def _make_bot(kind: str, color: Color) -> Player:
    return BOT_KINDS.get(kind, BOT_KINDS[DEFAULT_BOT_KIND])(color)


class RoomPhase(str, Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    OVER = "over"


@dataclass
class Seat:
    name: str
    color: Color
    rejoin_token: str
    connected: bool = True
    ws: Optional[object] = None  # fastapi WebSocket; not pickled
    is_bot: bool = False
    bot_kind: Optional[str] = None  # key into BOT_KINDS when is_bot


@dataclass
class Room:
    code: str
    host_token: str
    phase: RoomPhase = RoomPhase.LOBBY
    mode: Optional[GameMode] = None
    game: Optional[Game] = None
    seats: dict[Color, Seat] = field(default_factory=dict)
    seq: int = 0
    created_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # House rule (host-selected at start): pay out starting resources from BOTH
    # initial settlements instead of only the second (official rule).
    bonus_start: bool = False
    # color -> catanatron bot Player, populated at start()/restore(); the server
    # drives these seats' turns (see main.drive_bots). Not pickled directly.
    bot_players: dict = field(default_factory=dict)
    # Per-session chat log — plain messages AND non-blocking trade offers, in
    # one ordered list the client renders as a chat feed. Capped at CHAT_LOG_CAP.
    chat_log: list = field(default_factory=list)
    chat_seq: int = 0
    # Optional per-turn timer (host-selected, seconds; 0 = off). After a human
    # rolls, the server auto-ends the turn if they haven't within this window.
    turn_timer_seconds: int = 0
    # In-memory only (never pickled): bumped whenever a turn ends, so a pending
    # timeout watcher can tell its turn already finished. turn_deadline is the
    # epoch the current turn auto-ends (for the UI countdown), or None.
    _turn_token: int = 0
    turn_deadline: Optional[float] = None

    # --- lobby ---
    def next_free_color(self) -> Optional[Color]:
        for c in SEAT_ORDER:
            if c not in self.seats:
                return c
        return None

    def seat_by_token(self, token: str) -> Optional[Seat]:
        for seat in self.seats.values():
            if seat.rejoin_token == token:
                return seat
        return None

    def add_bot(self, kind: str = DEFAULT_BOT_KIND) -> Seat:
        if self.phase != RoomPhase.LOBBY:
            raise ValueError("game already started")
        color = self.next_free_color()
        if color is None:
            raise ValueError("no free seat")
        if kind not in BOT_KINDS:
            kind = DEFAULT_BOT_KIND
        n = sum(1 for s in self.seats.values() if s.is_bot) + 1
        seat = Seat(
            name=f"Bot {n}",
            color=color,
            rejoin_token="",
            connected=True,
            is_bot=True,
            bot_kind=kind,
        )
        self.seats[color] = seat
        return seat

    def remove_bot(self, color: Color) -> None:
        if self.phase != RoomPhase.LOBBY:
            raise ValueError("game already started")
        seat = self.seats.get(color)
        if seat is None or not seat.is_bot:
            raise ValueError("not a bot seat")
        del self.seats[color]

    # --- game start ---
    def start(self, mode_key: str, bonus_start: bool = False, turn_timer_seconds: int = 0):
        mode = GAME_MODES[mode_key]
        n = len(self.seats)
        if not (mode.min_players <= n <= mode.max_players):
            raise ValueError(
                f"{mode.label} needs {mode.min_players}-{mode.max_players} players, have {n}"
            )
        self.mode = mode
        self.bonus_start = bonus_start
        self.turn_timer_seconds = max(0, int(turn_timer_seconds or 0))
        seating = [c for c in SEAT_ORDER if c in self.seats]
        players = []
        self.bot_players = {}
        for c in seating:
            seat = self.seats[c]
            if seat.is_bot:
                bot = _make_bot(seat.bot_kind or DEFAULT_BOT_KIND, c)
                players.append(bot)
                self.bot_players[c] = bot
            else:
                players.append(HumanSeat(c))
        self.game = Game(
            players,
            vps_to_win=mode.vps_to_win,
            catan_map=mode.build_map(),
        )
        self.phase = RoomPhase.PLAYING

    # --- bots ---
    def is_bot(self, color: Color) -> bool:
        seat = self.seats.get(color)
        return bool(seat and seat.is_bot)

    def bot_player(self, color: Color) -> Optional[Player]:
        return self.bot_players.get(color)

    # --- chat & non-blocking trades ---------------------------------------
    # Player-to-player trades run OUTSIDE catanatron's blocking OFFER/DECIDE
    # flow: an offer is just a chat entry anyone may accept (first accept wins)
    # or ignore, so nobody has to wait on a table-wide decision. Accepting
    # executes an atomic resource swap between the two hands (the bank is not
    # involved; totals are conserved). Bank/port trades stay engine actions.

    def _append_chat(self, entry: dict) -> dict:
        self.chat_seq += 1
        entry["id"] = self.chat_seq
        entry["ts"] = time.time()
        self.chat_log.append(entry)
        if len(self.chat_log) > CHAT_LOG_CAP:
            del self.chat_log[: len(self.chat_log) - CHAT_LOG_CAP]
        return entry

    def _name_of(self, color: Color) -> str:
        seat = self.seats.get(color)
        return seat.name if seat else color.value

    def post_chat(self, color: Color, text: str) -> dict:
        text = str(text or "").strip()[:400]
        if not text:
            raise ValueError("empty message")
        return self._append_chat(
            {"kind": "msg", "color": color.value, "name": self._name_of(color), "text": text}
        )

    def _norm_deck(self, deck) -> dict:
        out = {}
        for key, val in (deck or {}).items():
            name = str(key).upper()
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if name in RESOURCE_NAMES and n > 0:
                out[name] = n
        return out

    def _can_afford(self, color: Color, deck: dict) -> bool:
        ps = self.game.state.player_state
        key = player_key(self.game.state, color)
        return all(ps[f"{key}_{r}_IN_HAND"] >= n for r, n in deck.items())

    def _trades_allowed(self) -> bool:
        return (
            self.phase == RoomPhase.PLAYING
            and self.game is not None
            and not self.game.state.is_initial_build_phase
            and not self.game.state.is_discarding
        )

    def propose_trade(self, color: Color, give, get) -> dict:
        if not self._trades_allowed():
            raise ValueError("trades aren't open right now")
        give, get = self._norm_deck(give), self._norm_deck(get)
        if not give or not get:
            raise ValueError("offer must give and get at least one card")
        if set(give) & set(get):
            raise ValueError("can't give and get the same resource")
        if not self._can_afford(color, give):
            raise ValueError("you don't have those cards")
        return self._append_chat({
            "kind": "trade", "color": color.value, "name": self._name_of(color),
            "give": give, "get": get,
            "status": "open", "accepted_by": None, "accepted_name": None,
        })

    # Cheap trade heuristic for bots: a resource is worth more the fewer you
    # hold (marginal utility), with wheat/ore a touch premium. A bot accepts
    # only a clearly favourable swap — no search, just arithmetic.
    _TRADE_WEIGHTS = {"WOOD": 1.0, "BRICK": 1.0, "SHEEP": 0.9, "WHEAT": 1.1, "ORE": 1.1}

    def bot_wants_trade(self, bot_color: Color, offer: dict) -> bool:
        give = offer["get"]   # the bot would GIVE what the proposer wants
        recv = offer["give"]  # ...and RECEIVE what the proposer offers
        if not self._can_afford(bot_color, give):
            return False
        # Never shed more cards than you gain — a 3-for-1 is bad however scarce
        # the single card is (the bank never does worse than 4-for-1).
        if sum(give.values()) > sum(recv.values()):
            return False
        ps = self.game.state.player_state
        key = player_key(self.game.state, bot_color)
        def value(r):  # scarcer in hand -> more valuable to the bot
            return self._TRADE_WEIGHTS[r] / (1 + ps[f"{key}_{r}_IN_HAND"])
        recv_val = sum(value(r) * n for r, n in recv.items())
        give_val = sum(value(r) * n for r, n in give.items())
        return recv_val > give_val * 1.15  # only take a clearly good deal

    def first_bot_to_accept(self, offer_id) -> Optional[Color]:
        """The first bot (in seat order) willing to take this open offer, if any."""
        offer = self._find_trade(offer_id)
        if offer is None or offer["status"] != "open":
            return None
        proposer = Color[offer["color"]]
        for color in SEAT_ORDER:
            seat = self.seats.get(color)
            if seat and seat.is_bot and color != proposer and self.bot_wants_trade(color, offer):
                return color
        return None

    def _find_trade(self, offer_id) -> Optional[dict]:
        for entry in self.chat_log:
            if entry.get("kind") == "trade" and entry["id"] == offer_id:
                return entry
        return None

    def accept_trade(self, offer_id, responder: Color) -> dict:
        entry = self._find_trade(offer_id)
        if entry is None or entry["status"] != "open":
            raise ValueError("that offer is no longer open")
        if not self._trades_allowed():
            raise ValueError("trades aren't open right now")
        proposer = Color[entry["color"]]
        if responder == proposer:
            raise ValueError("can't accept your own offer")
        give, get = entry["give"], entry["get"]  # proposer gives `give`, wants `get`
        if not self._can_afford(proposer, give):
            entry["status"] = "cancelled"  # proposer spent the cards meanwhile
            raise ValueError("offer expired — proposer no longer has those cards")
        if not self._can_afford(responder, get):
            raise ValueError("you don't have those cards")
        self._swap(proposer, give, responder, get)
        self._refresh_playable_actions()  # trade happened outside game.execute()
        entry["status"] = "done"
        entry["accepted_by"] = responder.value
        entry["accepted_name"] = self._name_of(responder)
        return entry

    def cancel_trade(self, offer_id, color: Color) -> dict:
        entry = self._find_trade(offer_id)
        if entry is None or entry["status"] != "open":
            raise ValueError("that offer is no longer open")
        if Color[entry["color"]] != color:
            raise ValueError("only the proposer can cancel")
        entry["status"] = "cancelled"
        return entry

    def _refresh_playable_actions(self) -> None:
        """catanatron caches game.playable_actions and only recomputes it inside
        game.execute(). Chat trades change hands OUTSIDE the engine, so recompute
        by hand — otherwise the current player's build options stay stale (you'd
        get resources from a trade but no new place-road/settlement option)."""
        from catanatron.models.actions import generate_playable_actions

        self.game.playable_actions = generate_playable_actions(self.game.state)

    def _swap(self, a_color: Color, a_gives: dict, b_color: Color, b_gives: dict) -> None:
        ps = self.game.state.player_state
        ak, bk = player_key(self.game.state, a_color), player_key(self.game.state, b_color)
        for r, n in a_gives.items():
            ps[f"{ak}_{r}_IN_HAND"] -= n
            ps[f"{bk}_{r}_IN_HAND"] += n
        for r, n in b_gives.items():
            ps[f"{bk}_{r}_IN_HAND"] -= n
            ps[f"{ak}_{r}_IN_HAND"] += n

    @property
    def seating(self) -> list[Color]:
        if self.game is None:
            return [c for c in SEAT_ORDER if c in self.seats]
        return list(self.game.state.colors)

    # --- action execution (call while holding self.lock) ---
    def execute(self, color: Color, action_type: ActionType, value) -> None:
        from catanatron.game import is_valid_action
        from catanatron.models.enums import SETTLEMENT

        action = Action(color, action_type, value)
        if not is_valid_action(
            self.game.playable_actions, self.game.state, action
        ):
            raise PermissionError(f"Invalid action {action_type.value} for {color.value}")
        self.game.execute(action)

        # House rule (opt-in): starting resources from BOTH initial settlements,
        # not just the second (which the engine already pays out in
        # apply_build_settlement). After the engine executes the FIRST initial
        # settlement, mirror that payout. `value` is the node_id.
        state = self.game.state
        if (
            self.bonus_start
            and action_type == ActionType.BUILD_SETTLEMENT
            and state.is_initial_build_phase
            and len(state.buildings_by_color[color][SETTLEMENT]) == 1
        ):
            self._grant_starting_resources(color, value)

        self.seq += 1
        # A turn ending invalidates any pending turn-timer watcher for that turn.
        if action_type == ActionType.END_TURN:
            self._turn_token += 1
            self.turn_deadline = None
        if self.game.winning_color() is not None:
            self.phase = RoomPhase.OVER

    def force_advance_turn(self) -> None:
        """Turn-timer timeout: drive the current turn to its end with minimal
        auto choices. Whatever the player already did stands; we only resolve
        anything blocking an END_TURN (robber, discards, dev-card placement),
        then end the turn. Preferring END_TURN means we never build/buy for them.
        Call while holding self.lock."""
        start_token = self._turn_token
        steps = 0
        while (
            self.phase == RoomPhase.PLAYING
            and self.game.winning_color() is None
            and self._turn_token == start_token
            and steps < 200
        ):
            actions = self.game.playable_actions
            if not actions:
                break
            chosen = next(
                (a for a in actions if a.action_type == ActionType.END_TURN),
                actions[0],
            )
            self.execute(chosen.color, chosen.action_type, chosen.value)
            steps += 1

    def _grant_starting_resources(self, color: Color, node_id: int) -> None:
        """Pay out one card per adjacent resource tile, drawing from the bank —
        identical to the engine's second-settlement grant."""
        from catanatron.models.decks import freqdeck_draw
        from catanatron.state_functions import player_key

        state = self.game.state
        key = player_key(state, color)
        for tile in state.board.map.adjacent_tiles[node_id]:
            if tile.resource is not None:
                freqdeck_draw(state.resource_freqdeck, 1, tile.resource)
                state.player_state[f"{key}_{tile.resource}_IN_HAND"] += 1

    def waiting_on(self) -> list[str]:
        """Which players the game is blocked on (for UI display)."""
        prompt = self.game.state.current_prompt
        if prompt in (ActionPrompt.DISCARD, ActionPrompt.DECIDE_TRADE):
            return [self.game.state.current_color().value]
        return []

    # --- persistence ---
    def persist(self):
        PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "code": self.code,
            "host_token": self.host_token,
            "phase": self.phase,
            "mode_key": self.mode.key if self.mode else None,
            "game": self.game,
            "seats": {
                c: {
                    "name": s.name,
                    "rejoin_token": s.rejoin_token,
                    "is_bot": s.is_bot,
                    "bot_kind": s.bot_kind,
                }
                for c, s in self.seats.items()
            },
            "seq": self.seq,
            "bonus_start": self.bonus_start,
            "chat_log": self.chat_log,
            "chat_seq": self.chat_seq,
            "turn_timer_seconds": self.turn_timer_seconds,
        }
        (PERSIST_DIR / f"{self.code}.pkl").write_bytes(pickle.dumps(snapshot))

    @classmethod
    def restore(cls, path: Path) -> "Room":
        snap = pickle.loads(path.read_bytes())
        room = cls(code=snap["code"], host_token=snap["host_token"])
        room.phase = snap["phase"]
        room.mode = GAME_MODES.get(snap["mode_key"]) if snap["mode_key"] else None
        room.game = snap["game"]
        room.seq = snap["seq"]
        room.bonus_start = snap.get("bonus_start", False)
        room.chat_log = snap.get("chat_log", [])
        room.chat_seq = snap.get("chat_seq", 0)
        room.turn_timer_seconds = snap.get("turn_timer_seconds", 0)
        for color, s in snap["seats"].items():
            is_bot = s.get("is_bot", False)
            room.seats[color] = Seat(
                name=s["name"],
                color=color,
                rejoin_token=s["rejoin_token"],
                connected=is_bot,  # bots are always "present"
                is_bot=is_bot,
                bot_kind=s.get("bot_kind"),
            )
        # Rebuild bot decision-makers (stateless; no need to reuse the pickled
        # instances inside the restored game).
        for color, seat in room.seats.items():
            if seat.is_bot:
                room.bot_players[color] = _make_bot(
                    seat.bot_kind or DEFAULT_BOT_KIND, color
                )
        return room


class RoomRegistry:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def create(self) -> tuple[Room, str]:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        while code in self.rooms:
            code = "".join(random.choices(string.ascii_uppercase, k=4))
        host_token = uuid.uuid4().hex
        room = Room(code=code, host_token=host_token)
        self.rooms[code] = room
        return room, host_token

    def restore_all(self):
        if PERSIST_DIR.exists():
            for path in PERSIST_DIR.glob("*.pkl"):
                try:
                    room = Room.restore(path)
                    self.rooms[room.code] = room
                except Exception:
                    continue  # corrupt snapshot: skip, don't crash boot


registry = RoomRegistry()
