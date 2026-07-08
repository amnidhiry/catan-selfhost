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

from catanatron import Game
from catanatron.models.player import Color, Player
from catanatron.models.enums import Action, ActionType, ActionPrompt
from catanatron.players.minimax import AlphaBetaPlayer
from catanatron.players.weighted_random import WeightedRandomPlayer

from .game_config import GAME_MODES, GameMode

PERSIST_DIR = Path("/data/rooms")
SEAT_ORDER = [Color.RED, Color.BLUE, Color.ORANGE, Color.WHITE]

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
    def start(self, mode_key: str, bonus_start: bool = False):
        mode = GAME_MODES[mode_key]
        n = len(self.seats)
        if not (mode.min_players <= n <= mode.max_players):
            raise ValueError(
                f"{mode.label} needs {mode.min_players}-{mode.max_players} players, have {n}"
            )
        self.mode = mode
        self.bonus_start = bonus_start
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
        if self.game.winning_color() is not None:
            self.phase = RoomPhase.OVER

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
