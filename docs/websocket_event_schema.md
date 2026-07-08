# Self-Hosted Catan — WebSocket Event Schema
**Derived from JSettlers2's message protocol (`soc.message`, 126 message types) and state machine (`soc.game.SOCGame`), adapted for FastAPI + catanatron_core + React.**

---

## 1. Session State Machine

JSettlers2's actual state constants, trimmed to what base-game Catan needs (dropping Seafarers/pirate/gold-hex states). These become a `GamePhase` enum in your FastAPI room manager:

```python
class GamePhase(str, Enum):
    # Lobby
    NEW = "new"                        # room created, players joining seats
    READY = "ready"                    # all seats filled/confirmed, about to start

    # Setup snake draft (JSettlers2: START1A/1B/2A/2B)
    SETUP_SETTLEMENT_1 = "setup_settlement_1"
    SETUP_ROAD_1 = "setup_road_1"
    SETUP_SETTLEMENT_2 = "setup_settlement_2"   # reverse order; resources granted here
    SETUP_ROAD_2 = "setup_road_2"

    # Main loop (JSettlers2: ROLL_OR_CARD -> PLAY1)
    ROLL_OR_CARD = "roll_or_card"      # current player must roll (or play dev card first)
    PLAY = "play"                      # rolled; trade/build/play-card until end_turn

    # Placement sub-states (entered from PLAY after a build request)
    PLACING_ROAD = "placing_road"
    PLACING_SETTLEMENT = "placing_settlement"
    PLACING_CITY = "placing_city"
    PLACING_ROBBER = "placing_robber"
    PLACING_FREE_ROAD_1 = "placing_free_road_1"  # Road Building dev card
    PLACING_FREE_ROAD_2 = "placing_free_road_2"

    # Multi-player-blocking states — THE critical insight from JSettlers2.
    # These states wait on a SET of players, not just current player.
    WAITING_FOR_DISCARDS = "waiting_for_discards"        # 7 rolled; all >7-card players
    WAITING_FOR_ROB_CHOOSE = "waiting_for_rob_choose"    # robber placed, pick victim
    WAITING_FOR_MONOPOLY = "waiting_for_monopoly"        # pick resource type
    WAITING_FOR_DISCOVERY = "waiting_for_discovery"      # Year of Plenty: pick 2 resources

    OVER = "over"
```

**Key structural rule (from `SOCGameHandler` line ~2773):** in `WAITING_FOR_DISCARDS`, the server tracks `players_owing_discard: set[Color]` and does not advance until the set is empty. Every blocking state carries a `waiting_on: list[player]` field in broadcasts so the UI can show "waiting for Alice, Bob…".

---

## 2. Message Envelope

All messages JSON over one WebSocket per player:

```json
{ "type": "<event_type>", "seq": 123, "data": { ... } }
```

- `seq`: server-assigned monotonic sequence per room. Client uses it to detect gaps after reconnect and request replay.
- Client→server messages get `{"type": "ack"|"error", "re_seq": ...}` responses. Invalid actions return `error` with a `reason` string (JSettlers2 pattern: `SOCRejectOffer.REASON_CANNOT_MAKE_OFFER` etc.).

---

## 3. Client → Server Events

### Lobby (JSettlers2: SOCJoinGame, SOCSitDown, SOCLeaveGame)
| type | data | notes |
|---|---|---|
| `join_room` | `{room_code, player_name, rejoin_token?}` | rejoin_token enables reconnect (§6) |
| `sit_down` | `{seat_color}` | claim a color |
| `leave_room` | `{}` | |
| `start_game` | `{config: {mode: "standard"\|"mini_2p"}}` | host only; picks map template + VP target |

### Turn actions (SOCRollDice, SOCEndTurn, SOCBuildRequest, SOCCancelBuildRequest)
| type | data | valid in phase |
|---|---|---|
| `roll_dice` | `{}` | ROLL_OR_CARD |
| `end_turn` | `{}` | PLAY |
| `build_request` | `{piece: "road"\|"settlement"\|"city"}` | PLAY → enters PLACING_* |
| `cancel_build` | `{}` | PLACING_* → back to PLAY |
| `place_piece` | `{piece, node_id?\|edge?}` | PLACING_*, SETUP_* |
| `buy_dev_card` | `{}` | PLAY |
| `play_dev_card` | `{card: "knight"\|"road_building"\|"year_of_plenty"\|"monopoly"}` | ROLL_OR_CARD or PLAY |

### Blocking-state responses (SOCDiscard, SOCChoosePlayer, SOCPickResources)
| type | data | valid in phase |
|---|---|---|
| `discard` | `{resources: {wood: 2, ore: 1, ...}}` | WAITING_FOR_DISCARDS (only if you owe) |
| `move_robber` | `{coordinate}` | PLACING_ROBBER |
| `choose_victim` | `{color}` | WAITING_FOR_ROB_CHOOSE |
| `pick_monopoly` | `{resource}` | WAITING_FOR_MONOPOLY |
| `pick_discovery` | `{resources}` | WAITING_FOR_DISCOVERY (exactly 2 total) |

### Trading (SOCMakeOffer, SOCAcceptOffer, SOCRejectOffer, SOCClearOffer, SOCBankTrade)
The crown-jewel protocol, transcribed nearly 1:1. From `SOCTradeOffer`:
`(from, to[], give: ResourceSet, get: ResourceSet)`

| type | data | notes |
|---|---|---|
| `bank_trade` | `{give: {wood: 4}, get: {ore: 1}}` | server validates rate vs. ports owned |
| `make_offer` | `{to: ["RED","BLUE"], give: {...}, get: {...}}` | only current player OR counteroffer to current player |
| `accept_offer` | `{offer_id}` | server executes swap atomically |
| `reject_offer` | `{offer_id}` | recorded + broadcast so offerer sees who declined |
| `clear_offer` | `{}` | retract own standing offer |

**Rules encoded server-side (all from JSettlers2's handler):**
1. Only one standing offer per player; new offer implicitly clears old (server emits `offer_cleared` first — the `SOCClearTradeMsg` pattern).
2. Non-current players may only direct offers *to* the current player (counteroffers).
3. All offers auto-clear on `end_turn`.
4. Give/get must be disjoint and non-empty (no gifting per official rules — "trade 0 cards" is disallowed).

---

## 4. Server → Client Events

### Broadcast to all in room
| type | data |
|---|---|
| `room_state` | `{players: [{name, color, connected, is_bot}], host, phase}` |
| `game_started` | `{config, board: {tiles, ports, robber}, seating_order}` |
| `phase_change` | `{phase, current_player, waiting_on: []}` |
| `dice_rolled` | `{player, d1, d2, total}` |
| `resources_gained` | `{gains: {"RED": {wood: 2}, ...}}` (public info — production is open) |
| `piece_placed` | `{player, piece, location}` |
| `robber_moved` | `{coordinate, victim?, stolen: bool}` (stolen card identity NOT broadcast) |
| `dev_card_bought` | `{player}` (count only, not which card) |
| `dev_card_played` | `{player, card}` (revealed on play) |
| `offer_made` / `offer_cleared` / `offer_rejected` | trade lifecycle |
| `trade_executed` | `{from, to, gave, got}` |
| `discard_progress` | `{done: ["RED"], waiting_on: ["BLUE"]}` |
| `longest_road` / `largest_army` | `{holder}` |
| `game_over` | `{winner, final_vps: {...}, revealed_vp_cards}` |
| `action_log` | `{text, player?}` — feeds the BGA-style log panel |

### Per-player (private channel — the hidden-info filter)
| type | data |
|---|---|
| `your_hand` | `{resources: {...}, dev_cards: [...], playable_dev_cards: [...]}` |
| `hand_counts` | `{"BLUE": {resources: 5, dev_cards: 2}, ...}` — what you see of others |
| `stolen_from_you` / `you_stole` | `{card}` — only the two parties learn the card |
| `discard_request` | `{must_discard: 4}` — JSettlers2's `SOCDiscardRequest`, sent only to owing players |
| `valid_actions` | `{actions: [...]}` — serialized from catanatron's `playable_actions`, drives UI button/node highlighting |

**Serializer rule:** one function `serialize_for(game, color)` produces the full state a given player is allowed to see. Broadcast = `serialize_for(game, color)` per connected socket. Never send raw `game.state`.

---

## 5. Mapping to catanatron actions

Your server translates events → `catanatron.models.actions.Action` and validates via `action in game.playable_actions` before `game.execute(action)`:

| WS event | catanatron ActionType |
|---|---|
| roll_dice | ROLL |
| place_piece(settlement) | BUILD_SETTLEMENT |
| place_piece(road) | BUILD_ROAD |
| place_piece(city) | BUILD_CITY |
| buy_dev_card | BUY_DEVELOPMENT_CARD |
| play_dev_card(knight) | PLAY_KNIGHT_CARD |
| move_robber + choose_victim | MOVE_ROBBER (combined action in catanatron) |
| bank_trade | MARITIME_TRADE |
| discard | DISCARD |
| end_turn | END_TURN |
| make/accept offer | OFFER_TRADE / ACCEPT_TRADE / REJECT_TRADE / CONFIRM_TRADE — **audit these first**; if thin, trade executes as server-level resource mutation outside the engine |

---

## 6. Reconnect Protocol (from SOCServer takeover constants + findRobotAskJoinGame)

1. On `join_room`, server issues `rejoin_token` (uuid) — client stores in localStorage-equivalent (in-memory + cookie).
2. Socket drop ≠ leaving. Seat marked `connected: false`, broadcast `room_state`.
3. Grace timers (JSettlers2's actual values, tunable): **30s** silent hold → then if it's their turn, pause with visible countdown → **150s** → policy kicks in.
4. Policy options (pick per-room at creation): `pause_forever` (friends), `auto_pass`, or `bot_takeover` — JSettlers2's `findRobotAskJoinGame` pattern; catanatron's bots make this nearly free: swap the seat's decide() to a bot Player until the human rejoins.
5. On rejoin with valid token: full `game_started`-equivalent snapshot + `your_hand` + events since last acked `seq`.

---

## 7. Room Manager Skeleton

```python
@dataclass
class Room:
    code: str                                # 4-letter join code
    host: str
    config: GameConfig                       # standard | mini_2p
    phase: GamePhase
    game: Optional[Game]                     # catanatron Game
    seats: dict[Color, Seat]                 # Seat: name, ws, rejoin_token, connected
    waiting_on: set[Color]                   # for blocking states
    standing_offers: dict[Color, TradeOffer]
    seq: int
    event_log: list[dict]                    # replay buffer for reconnect
    # persistence: pickle to disk every N actions -> survives container restart
```

Single asyncio lock per room around any `game.execute()` — one writer at a time makes the blocking-state logic trivially correct.
